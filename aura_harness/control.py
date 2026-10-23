"""Harness backends.

AuraHarness: the harness is workspace defines in one long-lived `aura aura/server.aura` process. A change is a guarded
`mutate:rebind` + `eval-current` in place; a trial runs in a forked worldline (a `workspace :create` child, or
`ast:snapshot`/`ast:restore` on the root); the audit log lives in the same process.

FileHarness (baseline): the same harness as a Python source file served by a small process. A change edits the file
and restarts the process; a trial copies the directory, edits the copy and starts a throwaway process on it.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .harness import COMPONENT, MUTABLE, PROTECTED, Candidate, normalize, post_check, to_python

ROOT = Path(__file__).resolve().parents[1]
TRACE = os.environ.get("AURA_HARNESS_TRACE")


def aura_env() -> tuple[str, dict]:
    aura = os.environ.get("AURA_BIN") or "aura"
    env = os.environ.copy()
    lib = os.environ.get("AURA_LIB")
    if lib:
        env["AURA_PATH"] = lib + (":" + env["AURA_PATH"] if env.get("AURA_PATH") else "")
    # set-code / mutate:rebind from a local program still need the sandbox off: aura soft refuses rebinds (cybrid-systems/aura#4609)
    env.setdefault("AURA_SANDBOX", "off")
    env.setdefault("AURA_PIPELINE_STRICT", "0")
    return aura, env


def _clean(s) -> str:
    return str(s).replace("\t", " ").replace("\n", " ")


class _Pipe:
    def __init__(self, argv, env=None, cwd=None):
        self.p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, bufsize=1, env=env, cwd=cwd)
        self.lat: dict[str, list[float]] = {}

    def read(self) -> dict:
        while True:
            line = self.p.stdout.readline()
            if not line:
                err = self.p.stderr.read()[-2000:] if self.p.stderr else ""
                raise RuntimeError(f"harness process exited (rc={self.p.poll()}): {err}")
            if line.startswith("R "):
                return json.loads(line[2:])

    def call(self, cmd, *fields, tag=None) -> dict:
        line = "\t".join([cmd, *[_clean(f) for f in fields]]) + "\n"
        if TRACE:
            with open(TRACE, "a") as fh:
                fh.write(line)
        t0 = time.perf_counter()
        self.p.stdin.write(line)
        self.p.stdin.flush()
        r = self.read()
        self.lat.setdefault(tag or cmd, []).append(time.perf_counter() - t0)
        if "error" in r:
            raise RuntimeError(f"harness: {r['error']}")
        return r

    def close(self):
        try:
            self.p.stdin.write("QUIT\n")
            self.p.stdin.flush()
            self.p.wait(timeout=10)
        except Exception:
            self.p.kill()
            self.p.wait()
        for fh in (self.p.stdin, self.p.stdout, self.p.stderr):
            try:
                fh.close()
            except Exception:
                pass


class AuraHarness:
    kind = "aura"

    def __init__(self, worldlines: str = "ws", server: str | None = None):
        aura, env = aura_env()
        t0 = time.perf_counter()
        self.pipe = _Pipe([aura, server or str(ROOT / "aura" / "server.aura")], env=env, cwd=str(ROOT))
        r = self.pipe.read()
        if not r.get("ready"):
            raise RuntimeError(f"aura control plane failed to start: {r}")
        self.startup_s = time.perf_counter() - t0
        self.worldlines = worldlines
        self.lat = self.pipe.lat

    def table(self) -> dict:
        return normalize(self.pipe.call("TABLE")["table"])

    def decide(self, comp, a="", b=""):
        return self.pipe.call("D", comp, a, b, tag="DECIDE")["v"]

    def apply(self, ts, c: Candidate, actor="proposer") -> dict:
        r = self.pipe.call("APPLY", ts, c.name, c.aura_body(), c.desc, actor, tag="APPLY")
        if r.get("ok"):
            r["table"] = normalize(r["table"])
        return r

    def trial(self, ts, cands: list[Candidate], actor="proposer") -> list[dict]:
        fields = []
        for c in cands:
            fields += [c.name, c.aura_body(), c.desc]
        r = self.pipe.call("TRIAL", self.worldlines, ts, actor, len(cands), *fields, tag="TRIAL")
        out = r["trials"]
        for t in out:
            if t["ok"]:
                t["table"] = normalize(t["table"])
        return out

    def verdict(self, ts, chosen: int, scores, why, actor="gate") -> dict:
        r = self.pipe.call("VERDICT", ts, chosen, json.dumps(scores), why, actor, tag="VERDICT")
        if r.get("table"):
            r["table"] = normalize(r["table"])
        return r

    def source(self) -> str:
        return self.pipe.call("SOURCE")["source"]

    def log(self) -> list[dict]:
        return self.pipe.call("LOG")["log"] or []

    def close(self):
        self.pipe.close()


# ------------------------------------------------------------------ file-edit + reload baseline
SEED_PY = {
    "route-tool": {"search": "grep", "read": "cat", "edit": "sed", "test": "pytest", "query-db": "sql", "logs": "journal"},
    "compress": None, "retry-limit": None, "memory-ttl": None, "delegate": None,
    "task-tier": None, "tool-budget": None,
}
LIMITS_PY = """# PROTECTED runtime boundary: the harness editor never writes this file
def context_budget():
    return 4000
def max_steps():
    return 30
def allowed_tools():
    return ["grep", "rg-json", "lsp-find", "cat", "sed", "apply-patch", "pytest", "pytest-q", "sql", "journal"]
def sandbox_level():
    return "restricted"
"""


def _seed_components(seed_table: dict) -> dict:
    return {name: seed_table[COMPONENT[name]] for name in MUTABLE}


def write_harness_dir(d: Path, comps: dict):
    d.mkdir(parents=True, exist_ok=True)
    (d / "limits.py").write_text(LIMITS_PY)
    src = "# mutable harness policy layer (edited by the proposer, then the server is restarted)\n"
    src += "\n".join(to_python(name, comps[name]) for name in MUTABLE)
    (d / "harness_live.py").write_text(src)


class FileHarness:
    kind = "file"

    def __init__(self, seed_table: dict, workdir: Path | None = None):
        self.dir = Path(workdir or tempfile.mkdtemp(prefix="aura-harness-file-"))
        self.comps = _seed_components(seed_table)
        write_harness_dir(self.dir / "live", self.comps)
        self.lat: dict[str, list[float]] = {}
        self.version = 0
        self.audit: list[dict] = []
        self.boundary = None
        self._start()
        self.boundary = self._table_raw(self.pipe)

    def _spawn(self, d: Path) -> _Pipe:
        p = _Pipe([sys.executable, "-m", "aura_harness.file_server", str(d)], cwd=str(ROOT))
        p.read()
        return p

    def _start(self):
        t0 = time.perf_counter()
        self.pipe = self._spawn(self.dir / "live")
        self.lat.setdefault("RESTART", []).append(time.perf_counter() - t0)

    def _table_raw(self, pipe) -> dict:
        return pipe.call("TABLE")["table"]

    def table(self) -> dict:
        return normalize(self._table_raw(self.pipe))

    def decide(self, comp, a="", b=""):
        t0 = time.perf_counter()
        v = self.pipe.call("D", comp, a, b)["v"]
        self.lat.setdefault("DECIDE", []).append(time.perf_counter() - t0)
        return v

    def _guard(self, c: Candidate) -> str | None:
        if c.name in PROTECTED:
            return f"protected define: {c.name}"
        if c.name not in MUTABLE:
            return f"not in mutation allowlist: {c.name}"
        if c.py_body() is None:
            return "free-form body not supported by the file backend"
        return None

    def _log(self, ts, op, c, reason="", extra=""):
        self.audit.append({"seq": len(self.audit) + 1, "ts": ts, "op": op, "name": c.name if c else "",
                           "why": c.desc if c else "", "reason": reason, "version": self.version, "extra": extra})

    def _edit_and_restart(self, comps) -> dict | str:
        """edit the live file, restart, post-check; on failure write the old file back and restart again"""
        old = (self.dir / "live" / "harness_live.py").read_text()
        write_harness_dir(self.dir / "live", comps)
        self.pipe.close()
        self._start()
        tb = self._table_raw(self.pipe)
        pr = post_check(tb, self.boundary)
        if pr:
            (self.dir / "live" / "harness_live.py").write_text(old)
            self.pipe.close()
            self._start()
            return pr
        return tb

    def apply(self, ts, c: Candidate, actor="proposer") -> dict:
        t0 = time.perf_counter()
        g = self._guard(c)
        if g:
            self._log(ts, "blocked", c, g)
            self.lat.setdefault("APPLY", []).append(time.perf_counter() - t0)
            return {"ok": False, "blocked": True, "reason": g}
        comps = dict(self.comps, **{c.name: c.value})
        r = self._edit_and_restart(comps)
        self.lat.setdefault("APPLY", []).append(time.perf_counter() - t0)
        if isinstance(r, str):
            self._log(ts, "blocked", c, r)
            return {"ok": False, "blocked": True, "reason": r}
        self.comps = comps
        self.version += 1
        self._log(ts, "keep-ungated", c)
        return {"ok": True, "version": self.version, "table": normalize(r)}

    def trial(self, ts, cands: list[Candidate], actor="proposer") -> list[dict]:
        t0 = time.perf_counter()
        self._trials = cands
        out = []
        for i, c in enumerate(cands):
            g = self._guard(c)
            if g:
                self._log(ts, "blocked", c, g)
                out.append({"i": i, "ok": False, "reason": g, "table": None})
                continue
            d = Path(tempfile.mkdtemp(prefix="trial-", dir=self.dir))
            write_harness_dir(d, dict(self.comps, **{c.name: c.value}))
            p = self._spawn(d)
            tb = self._table_raw(p)
            p.close()
            shutil.rmtree(d, ignore_errors=True)
            pr = post_check(tb, self.boundary)
            if pr:
                self._log(ts, "blocked", c, pr)
                out.append({"i": i, "ok": False, "reason": pr, "table": None})
            else:
                self._log(ts, "trial-copy", c)
                out.append({"i": i, "ok": True, "reason": "", "table": normalize(tb)})
        self.lat.setdefault("TRIAL", []).append(time.perf_counter() - t0)
        return out

    def verdict(self, ts, chosen: int, scores, why, actor="gate") -> dict:
        t0 = time.perf_counter()
        if 0 <= chosen < len(self._trials):
            c = self._trials[chosen]
            comps = dict(self.comps, **{c.name: c.value})
            r = self._edit_and_restart(comps)
            self.lat.setdefault("VERDICT", []).append(time.perf_counter() - t0)
            if isinstance(r, str):
                self._log(ts, "rollback", c, r, json.dumps(scores))
                return {"verdict": "ROLLBACK", "version": self.version}
            self.comps = comps
            self.version += 1
            self._log(ts, "keep", c, json.dumps(scores))
            return {"verdict": "KEEP", "version": self.version, "table": normalize(r)}
        self._log(ts, "rollback", None, json.dumps(scores))
        self.lat.setdefault("VERDICT", []).append(time.perf_counter() - t0)
        return {"verdict": "ROLLBACK", "version": self.version}

    def source(self) -> str:
        return (self.dir / "live" / "harness_live.py").read_text()

    def log(self) -> list[dict]:
        return self.audit

    def close(self):
        self.pipe.close()
        shutil.rmtree(self.dir, ignore_errors=True)
