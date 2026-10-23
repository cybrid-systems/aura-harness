"""Simulated agentic task environment + a frozen, seeded "model".

Everything here is the data plane and runs in the host. The harness is consulted only through a materialised decision
table (see control.py): route[need], compress[kind] = (strategy, limit), retry["tool|err"], ttl[fact],
delegate["kind|nsub"], budget, max_steps.

Every random draw is keyed by (seed, task id, step label, attempt, salt), so a task replayed under a different harness
meets the same tools and the same model: base and candidate harnesses are compared on paired outcomes.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

NEEDS_TOOLS = {            # capability map the proposer knows (tool docs)
    "search": ["grep", "rg-json", "lsp-find"],
    "read": ["cat"],
    "edit": ["sed", "apply-patch"],
    "test": ["pytest", "pytest-q"],
    "query-db": ["sql"],
    "logs": ["journal"],
}
FACT_OF = {"bugfix": "test-cmd", "feature": "test-cmd", "data": "db-schema", "triage": "repo-layout",
           "refactor": "repo-layout"}
TEMPLATES = {
    "bugfix": ["search", "read", "edit", "test"],
    "feature": ["search", "read", "edit", "edit", "test"],
    "data": ["query-db", "query-db", "read"],
    "triage": ["logs", "search", "read"],
}
SUBTASK = ["search", "read", "edit"]
MIX = {0: {"bugfix": .35, "feature": .25, "data": .25, "triage": .10, "refactor": .05},
       1: {"bugfix": .20, "feature": .10, "data": .15, "triage": .30, "refactor": .25}}
PROJECTS = ["api", "web", "etl"]
TRANSIENT = {"timeout", "rate-limit"}
ERRLINE_KINDS = {"test-log", "service-log"}

SYSTEM_TOKENS = 300
STEP_OUT_TOKENS = 60
ERR_TOKENS = 80
FACT_TOKENS = 60
HANDOFF_TOKENS = 150
SUMMARY_TOKENS = 120
DELEGATE_OVERHEAD = 400
SUMMARIZE_OUT = 150


def _rng(*key) -> random.Random:
    return random.Random(":".join(str(k) for k in key))


@dataclass
class Task:
    id: int
    phase: int
    kind: str
    project: str
    nsub: int
    heldout: bool


def heldout_of(tid: int) -> bool:
    return ((tid * 2654435761) >> 7) % 2 == 1


def make_stream(seed: int, n: int = 400, shift: int = 200) -> list[Task]:
    r = _rng("stream", seed)
    out = []
    for i in range(n):
        ph = 0 if i < shift else 1
        kinds, ws = zip(*MIX[ph].items())
        k = r.choices(kinds, ws)[0]
        nsub = r.randint(2, 6) if k == "refactor" else 1
        out.append(Task(i, ph, k, r.choice(PROJECTS), nsub, heldout_of(i)))
    return out


# ------------------------------------------------------------------ tools
def tool_output(tool: str, phase: int, rr: random.Random) -> tuple[str, int, float]:
    """-> (output kind, length in tokens, relative position of the key line)"""
    if tool == "grep":
        return "search-results", rr.randint(150, 900), rr.uniform(0, .3)
    if tool == "rg-json":
        return "search-results", 3 * rr.randint(150, 900), rr.uniform(0, .3)
    if tool == "lsp-find":
        return "search-results", rr.randint(80, 250), rr.uniform(0, .2)
    if tool == "cat":
        return "code-file", rr.randint(300, 1600), rr.uniform(0, 1)
    if tool in ("sed", "apply-patch"):
        return "patch-result", rr.randint(60, 150), 0.0
    if tool == "pytest":
        return "test-log", int(rr.randint(400, 3000) * (1.5 if phase else 1)), rr.uniform(.85, 1)
    if tool == "pytest-q":
        return "test-log", int(rr.randint(400, 3000) * (1.5 if phase else 1)) // 4, rr.uniform(.6, 1)
    if tool == "sql":
        return "sql-rows", rr.randint(100, 1500), rr.uniform(0, .5)
    if tool == "journal":
        return "service-log", rr.randint(1500, 7000), rr.uniform(.2, .8)
    return "config", rr.randint(300, 500), rr.uniform(0, .1)


def tool_error(tool: str, phase: int) -> list[tuple[str, float]]:
    """per-call error kinds and probabilities"""
    return {
        "grep": [("timeout", .02)] if phase == 0 else [("timeout", .45)],
        "rg-json": [("timeout", .02)],
        "lsp-find": [("not-found", 1.0)] if phase == 0 else [("timeout", .03)],
        "cat": [("not-found", .01)],
        "sed": [("bad-args", .30)],
        "apply-patch": [("bad-args", .04)],
        "pytest": [("timeout", .03 if phase == 0 else .12)],
        "pytest-q": [("timeout", .03 if phase == 0 else .12)],
        "sql": [("rate-limit", .05 if phase == 0 else .35)],
        "journal": [("timeout", .05)],
    }.get(tool, [])


def compress_obs(kind, length, pos, strategy, limit, rr) -> tuple[bool, int, int]:
    """-> (key line kept, tokens added to context, extra tokens spent outside the context)"""
    if strategy == "none" or length <= limit and strategy in ("head", "tail", "head-tail"):
        return True, length, 0
    if strategy == "head":
        return pos * length <= limit, limit, 0
    if strategy == "tail":
        return (1 - pos) * length <= limit, limit, 0
    if strategy == "head-tail":
        return pos * length <= limit / 2 or (1 - pos) * length <= limit / 2, limit, 0
    if strategy == "grep-errors":
        kept = rr.random() < (.95 if kind in ERRLINE_KINDS else .25)
        return kept, min(max(40, int(.06 * length)), limit), 0
    if strategy == "summarize":
        return rr.random() < .85, SUMMARIZE_OUT, int(.3 * length)
    return False, 0, 0


# ------------------------------------------------------------------ model + episode
@dataclass
class Episode:
    """trajectory of one task under one harness"""
    task: Task
    success: bool = False
    mode: str = ""                  # failure mode
    fail: dict = field(default_factory=dict)
    cost: int = 0                   # simulated tokens (prompt tokens of every model call + outputs + side calls)
    steps: int = 0
    calls: list = field(default_factory=list)
    rediscovered: list = field(default_factory=list)
    max_fill: float = 0.0
    delegated: bool = False
    biggest_kind: str = ""
    biggest_len: int = 0
    retry_tools: dict = field(default_factory=dict)
    # M6 (dev world v2 only): task tier, staged-hook nudges, simulated latency, a fix that passed the visible tests
    # but not the hidden grader (claimed success), and the final source of every buggy function (for synth tests)
    tier: str = ""
    nudges: int = 0
    latency: float = 0.0
    claimed: bool = False
    final_src: dict = field(default_factory=dict)

    def summary(self) -> dict:
        t = self.task
        extra = {"tier": self.tier, "nudges": self.nudges, "claimed": self.claimed} if self.tier else {}
        return {**extra, "id": t.id, "kind": t.kind, "phase": t.phase, "project": t.project, "nsub": t.nsub,
                "heldout": t.heldout, "success": self.success, "mode": self.mode, "fail": self.fail,
                "cost": self.cost, "steps": self.steps, "rediscovered": self.rediscovered,
                "max_fill": round(self.max_fill, 3), "delegated": self.delegated, "biggest_kind": self.biggest_kind}


class Fail(Exception):
    def __init__(self, mode, **info):
        super().__init__(mode)
        self.mode, self.info = mode, info


class Agent:
    """one agent context (main or sub-agent) running steps under the harness table"""

    def __init__(self, ep: Episode, table: dict, seed: int, label: str, base_ctx: int):
        self.ep, self.tb, self.seed, self.label = ep, table, seed, label
        self.ctx = base_ctx
        self.steps = 0

    def model_call(self, extra_cost: int = 0):
        self.ep.cost += self.ctx + STEP_OUT_TOKENS + extra_cost
        self.ctx += STEP_OUT_TOKENS

    def step(self, j: str, need: str):
        tb, t, ep = self.tb, self.ep.task, self.ep
        tool = tb["route"]["read" if need == "read-config" else need]
        attempt = 0
        prev_err = None
        while True:
            self.steps += 1
            ep.steps += 1
            if self.steps > tb["max_steps"]:
                raise Fail("step-limit", need=need, tool=tool, agent=self.label)
            rr = _rng(self.seed, t.id, self.label, j, attempt, "tool")
            err = None
            if prev_err and prev_err not in TRANSIENT:
                err = prev_err if rr.random() < (.85 if prev_err == "bad-args" else 1.0) else None
            else:
                for e, p in tool_error(tool, t.phase):
                    if rr.random() < p:
                        err = e
                        break
            if err is None:
                break
            self.ctx += ERR_TOKENS
            self.model_call()
            lim = tb["retry"].get(f"{tool}|{err}", 1)
            if attempt >= lim:
                raise Fail("tool-error", need=need, tool=tool, err=err, transient=err in TRANSIENT, attempts=attempt + 1)
            ep.retry_tools[(tool, err)] = ep.retry_tools.get((tool, err), 0) + 1
            attempt += 1
            prev_err = err
        ro = _rng(self.seed, t.id, self.label, j, "out")
        kind, length, pos = tool_output("config-file" if need == "read-config" else tool, t.phase, ro)
        strat, limit = tb["compress"][kind]
        kept, toks, extra = compress_obs(kind, length, pos, strat, limit, _rng(self.seed, t.id, self.label, j, "cmp"))
        if length > ep.biggest_len:
            ep.biggest_len, ep.biggest_kind = length, kind
        self.ctx += toks
        budget = tb["budget"]
        fill = self.ctx / budget
        ep.max_fill = max(ep.max_fill, fill)
        self.model_call(extra)
        rm = _rng(self.seed, t.id, self.label, j, "model")
        info = dict(need=need, tool=tool, kind=kind, strategy=strat, limit=limit, length=length, agent=self.label)
        if fill > 1.0:
            self.ctx = budget          # the harness hard-truncates the oldest context
            if rm.random() < .5:
                raise Fail("context-overflow", **info)
        if not kept and rm.random() < .85:
            raise Fail("info-lost", **info)
        p = .985 * (.93 if fill > .8 else 1.0)
        if rm.random() > p:
            raise Fail("model-error", **info)
        ep.calls.append((need, tool, kind, attempt))


class Memory:
    """project facts learned by earlier tasks; the harness decides (memory-ttl) how long a fact is carried"""

    def __init__(self, seed: int):
        self.seed = seed
        self.known: dict = {}        # (project, fact) -> (version, learned_at)

    def copy(self) -> "Memory":
        m = Memory(self.seed)
        m.known = dict(self.known)
        return m


def fact_version(seed: int, project: str, fact: str, tid: int, shift: int) -> int:
    """facts change: test-cmd for everyone at the shift (new test runner), and rare per-project changes"""
    v = 1 if (fact == "test-cmd" and tid >= shift) else 0
    r = _rng("facts", seed, project, fact)
    t = 0
    while True:
        t += r.randint(80, 300)
        if t > tid:
            break
        v += 10
    return v


def run_task(task: Task, table: dict, mem: Memory, seed: int, shift: int = 200) -> Episode:
    if getattr(task, "dev", False):              # M3: real developer trajectories (devenv.py)
        from .devenv import run_dev
        return run_dev(task, table, mem, seed)
    ep = Episode(task)
    fact = FACT_OF[task.kind]
    cur = fact_version(seed, task.project, fact, task.id, shift)
    held = mem.known.get((task.project, fact))
    ttl = table["ttl"].get(fact, 0)
    carried = held is not None and ttl > 0 and task.id - held[1] <= ttl
    main = Agent(ep, table, seed, "main", SYSTEM_TOKENS + (FACT_TOKENS if carried else 0))
    try:
        need_discover = True
        if carried:
            if held[0] == cur:
                need_discover = False
            elif _rng(seed, task.id, "stale").random() < .6:
                raise Fail("stale-memory", fact=fact, age=task.id - held[1])
        if need_discover:
            if held is not None and held[0] == cur:
                ep.rediscovered.append(fact)
            main.step("discover", "read-config")
            mem.known[(task.project, fact)] = (cur, task.id)
        if task.kind == "refactor":
            if table["delegate"].get(f"refactor|{task.nsub}", "inline") == "delegate":
                ep.delegated = True
                for s in range(task.nsub):
                    sub = Agent(ep, table, seed, f"sub{s}", SYSTEM_TOKENS + HANDOFF_TOKENS)
                    ep.cost += DELEGATE_OVERHEAD
                    for k, need in enumerate(SUBTASK):
                        sub.step(f"s{s}.{k}", need)
                    if _rng(seed, task.id, f"handoff{s}").random() < .04:
                        raise Fail("handoff-loss", sub=s)
                    main.ctx += SUMMARY_TOKENS
            else:
                for s in range(task.nsub):
                    for k, need in enumerate(SUBTASK):
                        main.step(f"s{s}.{k}", need)
            main.step("final", "test")
        else:
            for k, need in enumerate(TEMPLATES[task.kind]):
                main.step(str(k), need)
        ep.success = True
    except Fail as f:
        ep.mode, ep.fail = f.mode, f.info
    return ep

