"""Driver for aura/swarm.aura: Agensh-style orchestrator-free workers on Aura fibers.

Runs one `aura --serve-async` process (real scheduler fibers), loads swarm.aura one top-level form per `exec`
(serve-async drops plain defines from multi-form execs), then runs experiments and reads RSS from /proc.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SWARM = ROOT / "aura" / "swarm.aura"


def forms(src: str) -> list[str]:
    out, depth, cur, i, n = [], 0, [], 0, len(src)
    while i < n:
        c = src[i]
        if c == ";" and depth == 0:
            while i < n and src[i] != "\n":
                i += 1
            continue
        if c == ";":
            while i < n and src[i] != "\n":
                i += 1
            continue
        if c == '"':
            j = i + 1
            while j < n and src[j] != '"':
                j += 2 if src[j] == "\\" else 1
            cur.append(src[i:j + 1]); i = j + 1; continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        if depth > 0 or c == ")" or not c.isspace():
            cur.append(c)
        if depth == 0 and cur and c == ")":
            out.append("".join(cur)); cur = []
        i += 1
    return out


class Aura:
    def __init__(self, timeout: float = 600, workers: int | None = None):
        aura = os.environ.get("AURA_BIN") or "aura"
        env = dict(os.environ, AURA_SANDBOX="off", AURA_PIPELINE_STRICT="0")
        args = [aura, "--serve-async"] + ([f"--worker-threads={workers}"] if workers else [])
        self.p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  text=True, bufsize=1, env=env, cwd=os.environ.get("AURA_CWD") or None)
        self.timeout = timeout

    def exec(self, code: str, timeout: float | None = None) -> dict:
        self.p.stdin.write(json.dumps({"cmd": "exec", "code": code}) + "\n")
        self.p.stdin.flush()
        box: list = []
        t = threading.Thread(target=lambda: box.append(self.p.stdout.readline()), daemon=True)
        t.start(); t.join(timeout or self.timeout)
        if not box or not box[0]:
            self.close()
            raise TimeoutError(f"aura exec timed out / died: {code[:80]}")
        d = json.loads(box[0])
        if d.get("status") == "error":
            raise RuntimeError(f"aura error: {d.get('msg')} in {code[:120]}")
        return d

    def value(self, code: str, timeout: float | None = None) -> str:
        d = self.exec(code, timeout)
        v = d.get("value", "")
        return v.strip('"') if isinstance(v, str) else str(v)

    def rss_kb(self) -> int:
        try:
            for line in open(f"/proc/{self.p.pid}/status"):
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
        except OSError:
            pass
        return -1

    def load_swarm(self):
        for f in forms(SWARM.read_text()):
            self.exec(f)

    def close(self):
        try:
            self.p.kill(); self.p.wait(timeout=5)
        except Exception:
            pass


def kv(s: str) -> dict:
    out = {}
    for part in s.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            try:
                out[k] = float(v) if "." in v else int(v)
            except ValueError:
                out[k] = v
    return out


def _cli(expr: str, timeout: float = 600) -> tuple[str, int, float]:
    """CLI backend: one process per run; returns (last display line, peak RSS kB, wall ms)."""
    import tempfile
    aura = os.environ.get("AURA_BIN") or "aura"
    env = dict(os.environ, AURA_SANDBOX="off", AURA_PIPELINE_STRICT="0")
    with tempfile.NamedTemporaryFile("w", suffix=".aura", delete=False) as fh:
        # evaluate first: runtime warnings printed during the run must not split the @@ line
        fh.write(SWARM.read_text() + f'\n(define swarm-result {expr})\n(newline) (display "@@") (display swarm-result) (newline)\n')
        path = fh.name
    t0 = time.perf_counter()
    p = subprocess.Popen([aura, "--load", path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
                         cwd=os.environ.get("AURA_CWD") or None)
    peak = [0]

    def poll():
        while p.poll() is None:
            try:
                for line in open(f"/proc/{p.pid}/status"):
                    if line.startswith("VmHWM:"):
                        peak[0] = max(peak[0], int(line.split()[1]))
            except OSError:
                pass
            time.sleep(0.005)
    th = threading.Thread(target=poll, daemon=True); th.start()
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill(); out, err = p.communicate()
        raise TimeoutError(f"aura timed out: {expr}")
    finally:
        os.unlink(path)
    wall = (time.perf_counter() - t0) * 1000
    for line in out.splitlines():
        if line.startswith("@@"):
            return line[2:].strip().strip('"'), peak[0], wall
    raise RuntimeError(f"no result for {expr}: {out[-500:]} {err[-500:]}")


def run(mode: str, n: int, k: int, f: int, cap: int, timeout: float = 600, backend: str = "cli") -> dict:
    call = f"(run-epochs {n} {k} {f} {cap})" if mode == "epoch" else f"(run-free {n} {k} {f} {cap})"
    if backend == "cli":
        v, peak, wall = _cli(call, timeout)
        res = kv(v)
        res["peak-rss-kb"] = peak
        res["process-wall-ms"] = round(wall, 1)
    else:
        a = Aura(timeout)
        try:
            a.load_swarm()
            r0 = a.rss_kb()
            res = kv(a.value(call, timeout))
            res["rss-delta-kb"] = a.rss_kb() - r0
        finally:
            a.close()
    res.update(mode=mode, N=n, K=k, F=f, backend=backend)
    return res


def run_expr(expr: str, tag: dict, timeout: float = 900) -> dict:
    """CLI run of any swarm.aura runner expression (rebind / fail / cancel)."""
    v, peak, wall = _cli(expr, timeout)
    res = kv(v)
    res["peak-rss-kb"] = peak
    res["process-wall-ms"] = round(wall, 1)
    res.update(tag)
    return res


def validate(n: int, k: int, f: int, cap: int = 20000, rb_every: int = 4, kill_at: int = 3, cancel_ms: int = 300) -> dict:
    """Multi-fiber validation set for one N: per-worker policy rebind under contention, a worker that dies holding a
    claim (lease takeover), and cooperative cancel mid-run."""
    return {
        "rebind": run_expr(f"(run-rebind {n} {k} {f} {cap} {rb_every})", {"exp": "rebind", "N": n, "every": rb_every}),
        "fail": run_expr(f"(run-fail {n} {k} {f} {cap} {kill_at})", {"exp": "fail", "N": n, "kill_at": kill_at}),
        "cancel": run_expr(f"(run-cancel {n} {k} {f} {cap} {cancel_ms})", {"exp": "cancel", "N": n, "after_ms": cancel_ms}),
    }


def micro(n_fibers: list[int], board_n: int = 20000, chan_n: int = 20000, backend: str = "cli") -> dict:
    if backend == "cli":
        out = {"board": kv(_cli(f"(bench-board {board_n})")[0]), "chan": kv(_cli(f"(bench-chan {chan_n})")[0]), "spawn": []}
        base = _cli("0")[1]
        for n in n_fibers:
            v, peak, _ = _cli(f"(bench-spawn {n})")
            d = kv(v); d["peak-rss-kb"] = peak; d["rss-over-idle-kb"] = peak - base
            out["spawn"].append(d)
        return out
    a = Aura()
    try:
        a.load_swarm()
        out = {"spawn": [], "board": kv(a.value(f"(bench-board {board_n})")), "chan": kv(a.value(f"(bench-chan {chan_n})"))}
        for n in n_fibers:
            r0 = a.rss_kb()
            d = kv(a.value(f"(bench-spawn {n})"))
            d["rss-delta-kb"] = a.rss_kb() - r0
            out["spawn"].append(d)
        return out
    finally:
        a.close()


if __name__ == "__main__":
    import sys
    print(json.dumps(run(sys.argv[1], *map(int, sys.argv[2:6]), backend=os.environ.get("SWARM_BACKEND", "cli")), indent=1))
