"""Latency: Aura in-process (BENCH), host round trips for a decision, a guarded change and a trial, against the
file-edit + reload baseline (edit harness_live.py, restart the decision process)."""
from __future__ import annotations

import json
import statistics as st
import time

from .control import AuraHarness, FileHarness
from .harness import Candidate, seed_table


def _p(xs, q=.5):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def _cands(tb, n):
    out = []
    for i in range(n):
        m = dict(tb["retry"])
        m["sql|rate-limit"] = 2 + (i % 3)
        out.append(Candidate("retry-limit", m, "bench", "bench", f"retry sql|rate-limit={2 + i % 3}"))
    return out


def no_set_code_server() -> str:
    """aura#4585 ablation: the same server with the seed harness pasted in as plain program defines (no set-code).
    Learning is impossible there in principle (no workspace), but it shows what the host-program path costs
    without the post-set-code slowdown."""
    import re
    import tempfile
    from .control import ROOT
    src = (ROOT / "aura" / "harness_seed.aura").read_text() + "\n" + re.sub(
        r"^\(set-code \(read-file \*seed-path\*\)\)\n\(eval-current\)\n", "",
        (ROOT / "aura" / "server.aura").read_text(), flags=re.M)
    fd, path = tempfile.mkstemp(suffix=".aura", dir=str(ROOT / ".scratch") if (ROOT / ".scratch").exists() else None)
    with open(fd, "w") as fh:
        fh.write(src)
    return path


def measure(n: int = 20) -> dict:
    res = {}
    import os
    path = no_set_code_server()
    b = AuraHarness("ws", server=path)
    res["ablation_4585_no_set_code_in_process_us"] = b.pipe.call("BENCH", n)
    for _ in range(300):
        b.decide("retry", "sql", "rate-limit")
    res["ablation_4585_no_set_code_decision_rt_ms"] = 1000 * _p(b.lat["DECIDE"])
    b.close()
    os.unlink(path)
    a = AuraHarness("ws")
    res["aura_in_process_us"] = a.pipe.call("BENCH", n)
    for comp, x, y in [("route", "search", ""), ("compress", "test-log", ""), ("retry", "sql", "rate-limit")]:
        for _ in range(100):
            a.decide(comp, x, y)
    res["aura_decision_rt_ms"] = 1000 * _p(a.lat["DECIDE"])
    tb = a.table()
    t = []
    for c in _cands(tb, n):
        t0 = time.perf_counter()
        r = a.apply(0, c)
        t.append(time.perf_counter() - t0)
        assert r["ok"], r
    res["aura_guarded_change_rt_ms"] = 1000 * _p(t)
    for mode in ("ws", "snap"):
        a.worldlines = mode
        t = []
        for _ in range(max(3, n // 4)):
            t0 = time.perf_counter()
            a.trial(0, _cands(tb, 3))
            t.append((time.perf_counter() - t0) / 3)
        res[f"aura_trial_{mode}_per_candidate_ms"] = 1000 * _p(t)
    t = []
    blocked = Candidate("context-budget", None, "bench", "bench", "raise budget", raw_aura="(lambda () 8000)")
    for _ in range(n):
        t0 = time.perf_counter()
        r = a.apply(0, blocked)
        t.append(time.perf_counter() - t0)
        assert not r["ok"]
    res["aura_blocked_attempt_rt_ms"] = 1000 * _p(t)
    res["aura_startup_s"] = a.startup_s
    a.close()

    f = FileHarness(seed_table())
    for comp, x, y in [("route", "search", ""), ("compress", "test-log", ""), ("retry", "sql", "rate-limit")]:
        for _ in range(100):
            f.decide(comp, x, y)
    res["file_decision_rt_ms"] = 1000 * _p(f.lat["DECIDE"])
    tb = f.table()
    t = []
    for c in _cands(tb, n):
        t0 = time.perf_counter()
        r = f.apply(0, c)
        t.append(time.perf_counter() - t0)
        assert r["ok"], r
    res["file_change_edit_restart_ms"] = 1000 * _p(t)
    res["file_restart_only_ms"] = 1000 * _p(f.lat["RESTART"])
    t = []
    for _ in range(max(3, n // 4)):
        t0 = time.perf_counter()
        f.trial(0, _cands(tb, 3))
        t.append((time.perf_counter() - t0) / 3)
    res["file_trial_copy_per_candidate_ms"] = 1000 * _p(t)
    f.close()
    return res


def main(n: int = 20):
    r = measure(n)
    print(json.dumps(r, indent=1))
