"""Client for aura/evo_server.aura.

One long-lived Aura process owns the MOEA/D state, the Pareto archive, the
proposal grammar, the surrogate and the evo worldline. restart() kills it and
resumes from the log, which is how the two-restart lineage test is run.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class EvoDriver:
    def __init__(self, log: str, aura_bin: str | None = None, aura_lib: str | None = None,
                 server: str | None = None, verbose: bool = False):
        self.log = str(log)
        self.aura_bin = aura_bin or os.environ.get("AURA_BIN") or "aura"
        self.aura_lib = aura_lib or os.environ.get("AURA_LIB")
        self.server = server or str(ROOT / "aura" / "evo_server.aura")
        self.verbose = verbose
        self.p = None
        self.restarts = 0
        self._start()

    def _env(self) -> dict:
        env = os.environ.copy()
        env["AURA_EVO_LOG"] = self.log
        if self.aura_lib:
            env["AURA_PATH"] = self.aura_lib + (":" + env["AURA_PATH"] if env.get("AURA_PATH") else "")
        env.setdefault("AURA_SANDBOX", "off")
        env.setdefault("AURA_PIPELINE_STRICT", "0")
        return env

    def _start(self):
        self.p = subprocess.Popen([self.aura_bin, "--preset", "dev", self.server],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, bufsize=1,
                                  env=self._env(), cwd=str(ROOT))
        r = self._read()
        if not r.get("ready"):
            raise RuntimeError(f"evo control plane failed to start: {r}")

    def _read(self) -> dict:
        while True:
            line = self.p.stdout.readline()
            if not line:
                err = self.p.stderr.read()[-4000:] if self.p.stderr else ""
                raise RuntimeError(f"evo server exited rc={self.p.poll()}: {err}")
            if line.startswith("R\t"):
                return json.loads(line[2:])

    def call(self, cmd: str, **payload) -> dict:
        self.p.stdin.write(cmd + "\t" + json.dumps(payload) + "\n")
        self.p.stdin.flush()
        r = self._read()
        if self.verbose:
            sys.stderr.write(f"{cmd} -> {json.dumps(r)[:300]}\n")
        if "error" in r:
            raise RuntimeError(f"evo server: {r['error']}")
        return r

    # ── commands ────────────────────────────────────────────────────
    def init(self, seed: int, dim: int, H: int, T: int, search: str,
             tip: str = "", gen: int = 0, resume: list | None = None) -> dict:
        return self.call("INIT", seed=seed, dim=dim, H=H, T=T, search=search,
                         tip=tip, gen=gen, resume=resume or [])

    def ask(self, k: int) -> dict:
        return self.call("ASK", k=k)

    def propose(self, k: int, parent: list[float], gen: int, seed: int) -> dict:
        return self.call("PROPOSE", k=k, parent=parent, gen=gen, seed=seed)

    def tell(self, evals: list[dict], elite: int = -1, gen: int = 0) -> dict:
        return self.call("TELL", evals=evals, elite=elite, gen=gen)

    def front(self) -> list[dict]:
        return self.call("FRONT").get("front", [])

    def screen(self, X: list[list[float]], y: list[float],
               cands: list[list[float]], k: int) -> dict:
        return self.call("SCREEN", X=X, y=y, cands=cands, k=k)

    def hv(self, front: list[list[float]], ref: list[float],
           dirs=("max", "min", "min")) -> float:
        return self.call("HV", front=front, ref=ref, dirs=list(dirs)).get("hv", 0.0)

    def record(self, **kw) -> dict:
        return self.call("RECORD", **kw)

    def stats(self) -> dict:
        return self.call("STATS")

    def restart(self):
        """Kill the Aura process; the caller re-INITs with the log's resume set."""
        try:
            self.p.stdin.write("QUIT\n")
            self.p.stdin.flush()
            self.p.wait(timeout=5)
        except Exception:
            self.p.kill()
            self.p.wait()
        for fh in (self.p.stdin, self.p.stdout, self.p.stderr):
            try:
                fh.close()
            except Exception:
                pass
        self.restarts += 1
        self._start()

    def close(self):
        try:
            self.p.stdin.write("QUIT\n")
            self.p.stdin.flush()
            self.p.wait(timeout=5)
        except Exception:
            self.p.kill()
            self.p.wait()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
