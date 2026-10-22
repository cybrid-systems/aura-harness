"""M3: real developer trajectories (docs/rsi-design.md). Small generated Python repos with seeded bugs; a scripted,
deterministic "model" runs a build/test/fix loop with REAL tools on REAL files:

  test     pytest   -> `python3 -m unittest discover -v`  (verbose; the image has no pytest)
           pytest-q -> `python3 -m unittest discover`     (quiet: dots, failures, summary)
  search   grep -> `grep -rn`, rg-json -> `rg --json`, lsp-find -> an ast scan printing path:line
  read     cat
  edit     sed -> `sed -i 's/OLD/NEW/'` with the OLD/NEW text unescaped (as a naive agent writes it: breaks on / * [ .)
           apply-patch -> exact text replacement, prints a unified diff

Every harness decision is real: routing picks the command, `compress` truncates the real output (head / tail /
head-tail / grep-errors / summarize=outline), `retry-limit` governs retries after tool faults, `memory-ttl` carries the
repo's test layout across tasks, `delegate` runs each bug of a multi-bug task in a fresh sub-agent context. Tool faults
(timeouts, rate limits) are injected deterministically per (seed, task, step, attempt): the sandbox is flaky, the tools
are real. Context use is measured in tokens = chars / 4 of what the model kept.

Episodes carry the same failure-mode schema as env.py, so the existing proposer, Aura control plane, gate, retention
and M2 pieces run unchanged. Held-out tasks come from repos the proposer never sees; OOD tasks from a repo with a
different style that is used in no evolution step.
"""
from __future__ import annotations

import ast
import difflib
import json
import os
import random
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .env import Episode, Fail, Memory

TRAIN_REPOS = ["api", "web", "etl"]
HELDOUT_REPOS = ["billing", "search"]
OOD_REPOS = ["geo"]
SYSTEM_TOKENS, STEP_TOKENS, HANDOFF_TOKENS, DELEGATE_OVERHEAD, SUMMARY_TOKENS, FACT_TOKENS = 300, 60, 150, 400, 120, 60
CACHE_DIR = Path(os.environ.get("AURA_HARNESS_DEV_DIR", tempfile.gettempdir())) / "aura-harness-dev"

# ---------------------------------------------------------------- repo generation
TEMPLATES = {
    "add": ("def {f}(x):\n    return x + {k}\n", ["+ {k}", "- {k}"], ["{f}(1) == 1 + {k}", "{f}(-{k}) == 0"]),
    "mean": ("def {f}(xs):\n    return sum(xs) / len(xs)\n", ["/ len(xs)", "/ (len(xs) + 1)"],
             ["{f}([2, 4]) == 3", "{f}([5]) == 5"]),
    "window": ("def {f}(xs, k):\n    return [sum(xs[i:i + k]) for i in range(len(xs) - k + 1)]\n",
               ["- k + 1", "- k"], ["{f}([1, 2, 3], 2) == [3, 5]", "{f}([1, 1], 2) == [2]"]),
    "count": ("def {f}(xs, t):\n    n = 0\n    for x in xs:\n        if x >= t:\n            n += 1\n    return n\n",
              [">= t", "> t"], ["{f}([1, 2, 3], 2) == 2", "{f}([5], 5) == 1"]),
    "scale": ("def {f}(x):\n    return x * {k}\n", ["* {k}", "* ({k} + 1)"], ["{f}(2) == 2 * {k}", "{f}(0) == 0"]),
    "join": ("def {f}(parts):\n    return \"-\".join(p.strip() for p in parts)\n", ['"-"', '"_"'],
             ["{f}([' a', 'b ']) == 'a-b'", "{f}(['x']) == 'x'"]),
    "clamp": ("def {f}(x, lo, hi):\n    if x < lo:\n        return lo\n    if x > hi:\n        return hi\n    return x\n",
              ["x > hi", "x >= hi + 1 and x > hi + 1"], ["{f}(11, 0, 10) == 10", "{f}(5, 0, 10) == 5"]),
}
# the model's fix rules: the inverse edits a developer tries first, in order
FIX_RULES = [(" - (\\d+)$", " + \\1"), ("/ \\(len\\(xs\\) \\+ 1\\)", "/ len(xs)"), ("len\\(xs\\) - k\\)", "len(xs) - k + 1)"),
             ("x > t:", "x >= t:"), ("\\* \\((\\d+) \\+ 1\\)", "* \\1"), ('"_"', '"-"'),
             ("x >= hi \\+ 1 and x > hi \\+ 1", "x > hi")]
FILLER = ('def _helper_{m}_{j}(value):\n    """Internal helper kept for backwards compatibility.\n\n'
          '    It normalises ``value`` the way the old {m} pipeline did; callers outside this module\n'
          '    should not rely on it. See docs/{m}.md for the history of this function.\n    """\n'
          '    if value is None:\n        return 0\n    return value\n')


def _rng(*k):
    return random.Random(":".join(map(str, k)))


@dataclass(frozen=True)
class Repo:
    name: str
    mods: tuple          # ((module, ((fname, template, k), ...)), ...)
    style: str           # "flat" | "ood"


def make_repo(name: str) -> Repo:
    r = _rng("repo", name)
    nm = 9 if name in OOD_REPOS else 7
    mods = []
    for i in range(nm):
        fs = []
        for j, t in enumerate(r.sample(sorted(TEMPLATES), 5)):
            fs.append((f"{t}_{name}{i}{j}", t, r.randint(2, 9)))
        mods.append((f"m{i}", tuple(fs)))
    return Repo(name, tuple(mods), "ood" if name in OOD_REPOS else "flat")


def tests_dir(repo: Repo, phase: int) -> str:
    return "tests" if phase == 0 else "test/unit"


def render(repo: Repo, phase: int, bugs: list[tuple[str, str]]) -> dict[str, str]:
    """-> {path: text}; bugs = [(fname, template)] whose mutation is applied"""
    files = {}
    r = _rng("layout", repo.name)
    bugged = {f for f, _ in bugs}
    td = tests_dir(repo, phase)
    for mod, fs in repo.mods:
        parts = []
        nf = r.randint(3, 6) if repo.style == "flat" else r.randint(6, 9)
        for j in range(nf):
            parts.append(FILLER.format(m=mod, j=j))
        for fname, t, k in fs:
            src, (good, bad), _ = TEMPLATES[t]
            body = src.format(f=fname, k=k)
            if fname in bugged:
                body = body.replace(good.format(k=k), bad.format(k=k), 1)
            parts.insert(r.randint(0, len(parts)), body)
        if repo.style == "ood":       # OOD style: everything inside a class-free module with a long header
            parts.insert(0, '"""' + ("Module %s of the geo toolkit. " % mod) * 30 + '"""\n')
        files[f"pkg/{mod}.py"] = "\n\n".join(parts)
        tl = [f"import unittest\nfrom pkg.{mod} import *\n\n\nclass T(unittest.TestCase):"]
        for fname, t, k in fs:
            for n, a in enumerate(TEMPLATES[t][2]):
                tl.append(f"    def test_{fname}_{n}(self):\n        self.assertTrue({a.format(f=fname, k=k)})\n")
        files[f"{td}/test_{mod}.py"] = "\n".join(tl) + "\n"
    files["pkg/__init__.py"] = ""
    for d in (td.split("/")[0], td) if "/" in td else (td,):
        files[f"{d}/__init__.py"] = ""
    files["harness.cfg"] = ("# build settings\nlint = ruff\nformat = black\n" + "# legacy\n" * 6 +
                            f"test_dir = {td}\nrunner = unittest\n")
    return files


# ---------------------------------------------------------------- tasks
@dataclass(frozen=True)
class DevTask:
    id: int
    phase: int
    kind: str           # "bugfix" (1 bug) | "refactor" (nsub bugs: multi-file fix)
    project: str        # repo name
    nsub: int
    heldout: bool
    bugs: tuple         # ((fname, template), ...)
    ood: bool = False
    dev: bool = True


def make_stream(seed: int, n: int = 160, shift: int = 80, heldout_every: int = 2) -> list[DevTask]:
    r = _rng("devstream", seed)
    out = []
    for i in range(n):
        ph = 0 if i < shift else 1
        held = i % heldout_every == 1
        repo = make_repo(r.choice(HELDOUT_REPOS if held else TRAIN_REPOS))
        multi = r.random() < (.2 if ph == 0 else .4)
        nb = r.randint(2, 3) if multi else 1
        fs = [f for _, mfs in repo.mods for f in mfs]
        picks = r.sample(fs, nb)
        out.append(DevTask(i, ph, "refactor" if multi else "bugfix", repo.name, nb, held,
                           tuple((f, t) for f, t, _ in picks)))
    return out


def ood_tasks(seed: int, n: int = 30, phase: int = 1) -> list[DevTask]:
    r = _rng("ood", seed)
    repo = make_repo(OOD_REPOS[0])
    fs = [f for _, mfs in repo.mods for f in mfs]
    out = []
    for i in range(n):
        multi = r.random() < .3
        nb = r.randint(2, 3) if multi else 1
        picks = r.sample(fs, nb)
        out.append(DevTask(100000 + i, phase, "refactor" if multi else "bugfix", repo.name, nb, True,
                           tuple((f, t) for f, t, _ in picks), ood=True))
    return out


# ---------------------------------------------------------------- tools (real)
FAULTS = {"grep": [("timeout", .15)], "rg-json": [("rate-limit", .10)], "lsp-find": [("not-found", .12)],
          "pytest": [("timeout", .10)], "pytest-q": [("timeout", .05)], "apply-patch": [("timeout", .03)]}
TRANSIENT = {"timeout", "rate-limit"}
KIND_OF = {"grep": "search-results", "rg-json": "search-results", "lsp-find": "search-results", "cat": "code-file",
           "sed": "patch-result", "apply-patch": "patch-result", "pytest": "test-log", "pytest-q": "test-log"}


def sh(argv, cwd) -> tuple[int, str]:
    p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=60)
    return p.returncode, p.stdout + p.stderr


def lsp_find(cwd, name) -> str:
    out = []
    for p in sorted(Path(cwd, "pkg").glob("*.py")):
        try:
            for node in ast.walk(ast.parse(p.read_text())):
                if isinstance(node, ast.FunctionDef) and node.name == name:
                    out.append(f"pkg/{p.name}:{node.lineno}: def {name}")
        except SyntaxError:
            out.append(f"pkg/{p.name}: syntax error")
    return "\n".join(out) + "\n"


ERR_RE = re.compile(r"(def |assert|Error|FAIL|Traceback|File \"|^Ran |^OK|FAILED)")


def compress(text: str, strategy: str, limit_tokens: int) -> str:
    lim = limit_tokens * 4
    if strategy == "none" or len(text) <= lim:
        return text
    if strategy == "head":
        return text[:lim]
    if strategy == "tail":
        return text[-lim:]
    if strategy == "head-tail":
        return text[:lim // 2] + "\n...\n" + text[-lim // 2:]
    lines = text.splitlines()
    if strategy == "grep-errors":
        keep = [ln for ln in lines if ERR_RE.search(ln)]
    else:   # summarize = outline: def lines and the 4 lines after each, plus failure markers
        keep, k = [], 0
        for ln in lines:
            if ln.startswith("def ") or ERR_RE.search(ln) and not ln.startswith("    "):
                k = 5
            if k > 0:
                keep.append(ln)
                k -= 1
    return "\n".join(keep)[:lim]


# ---------------------------------------------------------------- the scripted model + agent loop
class DevAgent:
    def __init__(self, ep, tb, seed, label, ctx, cwd, task):
        self.ep, self.tb, self.seed, self.label, self.ctx, self.cwd, self.t = ep, tb, seed, label, ctx, cwd, task
        self.steps = 0
        self.n = 0

    def _charge(self, text):
        toks = len(text) // 4
        self.ctx += toks + STEP_TOKENS
        self.ep.cost += self.ctx
        self.ep.max_fill = max(self.ep.max_fill, self.ctx / self.tb["budget"])
        if self.ctx > self.tb["budget"]:
            raise Fail("context-overflow", agent=self.label, kind=self._kind, tool=self._tool)

    def tool(self, need, argv_of, kind=None):
        """run one tool call under routing / faults / retry / compression -> kept observation, raw output, rc"""
        tool = self.tb["route"][need]
        self._tool, self._kind = tool, kind or KIND_OF.get(tool, "config")
        attempt, j = 0, self.n
        self.n += 1
        while True:
            self.steps += 1
            self.ep.steps += 1
            if self.steps > self.tb["max_steps"]:
                raise Fail("step-limit", need=need, tool=tool, agent=self.label)
            rr = _rng(self.seed, self.t.id, self.label, j, attempt, "fault")
            err = next((e for e, p in FAULTS.get(tool, []) if rr.random() < p), None)
            if err is None:
                break
            self._charge(f"error: {tool}: {err}")
            if attempt >= self.tb["retry"].get(f"{tool}|{err}", 1):
                raise Fail("tool-error", need=need, tool=tool, err=err, transient=True, attempts=attempt + 1)
            self.ep.retry_tools[(tool, err)] = self.ep.retry_tools.get((tool, err), 0) + 1
            attempt += 1
        rc, raw = argv_of(tool)
        strat, limit = self.tb["compress"][self._kind]
        kept = compress(raw, strat, limit)
        if len(raw) > self.ep.biggest_len:
            self.ep.biggest_len, self.ep.biggest_kind = len(raw), self._kind
        self._charge(kept)
        self.ep.calls.append((need, tool, self._kind, attempt))
        return kept, raw, rc, dict(need=need, tool=tool, kind=self._kind, strategy=strat, limit=limit, length=len(raw))

    # -- concrete steps
    def run_tests(self, tdir):
        def argv(tool):
            a = ["python3", "-B", "-m", "unittest", "discover", "-s", tdir, "-t", "."] + (["-v"] if tool == "pytest" else [])
            return sh(a, self.cwd)
        kept, raw, rc, info = self.tool("test", argv)
        if "Ran 0 tests" in raw or "ImportError" in raw and "Start directory" in raw or "No such file" in raw:
            return None, info, raw
        failing = re.findall(r"^(?:FAIL|ERROR): test_(\w+?)_\d+ ", kept, re.M)
        return (rc == 0, failing, raw), info, raw

    def find(self, fname):
        def argv(tool):
            if tool == "grep":
                return sh(["grep", "-rn", f"def {fname}(", "pkg"], self.cwd)
            if tool == "rg-json":
                return sh(["rg", "--json", f"def {fname}\\(", "pkg"], self.cwd)
            if tool == "lsp-find":
                return 0, lsp_find(self.cwd, fname)
            return sh(["grep", "-rln", fname, "pkg"], self.cwd)
        kept, raw, rc, info = self.tool("search", argv)
        m = re.search(r"(pkg/m\d+\.py)", kept)
        if not m:
            raise Fail("info-lost", **info)
        return m.group(1)

    def read(self, path, fname):
        kept, raw, rc, info = self.tool("read", lambda tool: sh(["cat", path], self.cwd))
        lines = kept.splitlines()
        try:
            i = next(k for k, ln in enumerate(lines) if ln.startswith(f"def {fname}("))
        except StopIteration:
            raise Fail("info-lost", **info)
        body = []
        for ln in lines[i + 1:]:
            if not ln.startswith("    "):
                break
            body.append(ln)
        return body, info

    def edit(self, path, old, new):
        def argv(tool):
            if tool == "sed":
                before = Path(self.cwd, path).read_text()
                rc, out = sh(["sed", "-i", f"s/{old}/{new}/", path], self.cwd)
                if rc == 0 and Path(self.cwd, path).read_text() == before:
                    return 1, "sed: pattern did not match\n"
                return rc, out
            p = Path(self.cwd, path)
            a = p.read_text()
            if old not in a:
                return 1, "apply-patch: hunk failed\n"
            b = a.replace(old, new, 1)
            p.write_text(b)
            return 0, "".join(difflib.unified_diff(a.splitlines(True), b.splitlines(True), path, path))
        kept, raw, rc, info = self.tool("edit", argv)
        if rc != 0:
            raise Fail("tool-error", need="edit", tool=info["tool"], err="bad-args", transient=False, attempts=1)

    def fix_one(self, tdir, fname):
        path = self.find(fname)
        body, info = self.read(path, fname)
        cands = []
        for ln in body:
            for pat, rep in FIX_RULES:
                if re.search(pat, ln):
                    cands.append((ln, re.sub(pat, rep, ln)))
        if not cands:
            raise Fail("info-lost", **info)
        for old, new in cands:
            backup = Path(self.cwd, path).read_text()
            self.edit(path, old.strip(), new.strip())
            res, tinfo, _ = self.run_tests(tdir)
            if res is None:
                raise Fail("info-lost", **tinfo)
            if fname not in res[1] and (res[0] or res[1] or True):
                return res
            Path(self.cwd, path).write_text(backup)            # revert (free: editor undo)
        raise Fail("info-lost", **info)


def _materialise(task: DevTask) -> str:
    d = tempfile.mkdtemp(prefix=f"t{task.id}-", dir=_tmp())
    repo = make_repo(task.project)
    for p, text in render(repo, task.phase, list(task.bugs)).items():
        fp = Path(d, p)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(text)
    return d


def _tmp():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return str(CACHE_DIR)


def _run(task: DevTask, tb: dict, mem: Memory, seed: int) -> Episode:
    ep = Episode(task)
    cwd = _materialise(task)
    fact = "test-cmd"
    cur = tests_dir(make_repo(task.project), task.phase)
    held = mem.known.get((task.project, fact))
    ttl = tb["ttl"].get(fact, 0)
    carried = held is not None and ttl > 0 and task.id - held[1] <= ttl
    main = DevAgent(ep, tb, seed, "main", SYSTEM_TOKENS + (FACT_TOKENS if carried else 0), cwd, task)
    main._kind, main._tool = "config", "cat"
    try:
        tdir = held[0] if carried else None
        if tdir is None:
            if held is not None and held[0] == cur:
                ep.rediscovered.append(fact)
            kept, raw, rc, info = main.tool("read", lambda tool: sh(["cat", "harness.cfg"], cwd), kind="config")
            m = re.search(r"test_dir = (\S+)", kept)
            if not m:
                raise Fail("info-lost", **info)
            tdir = m.group(1)
            mem.known[(task.project, fact)] = (tdir, task.id)
        res, info, raw = main.run_tests(tdir)
        if res is None:
            raise Fail("stale-memory", fact=fact, age=task.id - held[1]) if carried else Fail("info-lost", **info)
        failing = list(dict.fromkeys(res[1]))
        if not failing:
            raise Fail("info-lost", **info)
        deleg = task.kind == "refactor" and tb["delegate"].get(f"refactor|{task.nsub}", "inline") == "delegate"
        ep.delegated = deleg
        done = set()
        k = 0
        while failing:
            fname = failing[0]
            if fname in done:
                raise Fail("info-lost", **info)
            done.add(fname)
            if deleg:
                sub = DevAgent(ep, tb, seed, f"sub{k}", SYSTEM_TOKENS + HANDOFF_TOKENS, cwd, task)
                ep.cost += DELEGATE_OVERHEAD
                res = sub.fix_one(tdir, fname)
                if _rng(seed, task.id, f"handoff{k}").random() < .04:
                    raise Fail("handoff-loss", sub=k)
                main.ctx += SUMMARY_TOKENS
                main._charge("")
            else:
                res = main.fix_one(tdir, fname)
            k += 1
            failing = [f for f in dict.fromkeys(res[1]) if f not in done] if not res[0] else []
            if not res[0] and not failing:
                raise Fail("info-lost", kind="test-log", tool=tb["route"]["test"], need="test",
                           strategy=tb["compress"]["test-log"][0], limit=tb["compress"]["test-log"][1])
        ep.success = True
    except Fail as f:
        ep.mode, ep.fail = f.mode, f.info
    finally:
        shutil.rmtree(cwd, ignore_errors=True)
    return ep


# ---------------------------------------------------------------- decision-trace cache (exact)
class _Rec(dict):
    """records every table entry a run consults, so a cached episode is reused only if the new table agrees on all"""

    def __init__(self, tb, log, path=()):
        super().__init__(tb)
        self._log, self._path = log, path

    def __getitem__(self, k):
        v = dict.__getitem__(self, k)
        p = self._path + (k,)
        if isinstance(v, dict):
            return _Rec(v, self._log, p)
        self._log[p] = json.dumps(v)
        return v

    def get(self, k, d=None):
        return self[k] if k in self else d


_CACHE: dict = {}


def _lookup(tb, entries):
    for path, v in entries.items():
        x = tb
        for k in path:
            if not isinstance(x, dict) or k not in x:
                return False
            x = x[k]
        if json.dumps(x) != v:
            return False
    return True


def run_dev(task: DevTask, tb: dict, mem: Memory, seed: int) -> Episode:
    held = mem.known.get((task.project, "test-cmd"))
    key = (seed, task, json.dumps(held))
    for entries, ep, upd in _CACHE.get(key, []):
        if _lookup(tb, entries):
            if upd is not None:
                mem.known[(task.project, "test-cmd")] = upd
            return ep
    log: dict = {}
    before = mem.known.get((task.project, "test-cmd"))
    ep = _run(task, _Rec(tb, log), mem, seed)
    after = mem.known.get((task.project, "test-cmd"))
    _CACHE.setdefault(key, []).append((log, ep, after if after != before else None))
    return ep
