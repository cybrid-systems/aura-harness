"""Harness-size sweep: how the guarded control plane scales with the number of MUTABLE defines.

For each N in --knobs, one Aura control-plane process is started with AURA_HARNESS_KNOBS=N (N extra mutable
knob-i defines, see aura/server.aura) and --reps rounds of TABLE / DECIDE / APPLY / TRIAL(ws)+VERDICT /
TRIAL(snap)+VERDICT are timed (p50 ms), plus startup, RSS and the in-process BENCH breakdown (us).
  python3 scripts/size_sweep.py --knobs 0,50,200,500,1000 --reps 20 --out results/size/sweep.json
  python3 scripts/size_sweep.py --chunk 0 ...   # one flat aggregator define: knob rebinds hit aura#4615
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aura_harness.control import AuraHarness  # noqa: E402
from aura_harness.harness import Candidate  # noqa: E402

BENCH_KEYS = ("decision_call_us", "materialize_table_us", "rebind_eval_us", "snapshot_us", "restore_eval_us",
              "guarded_apply_us", "trial_ws_us")


def rss_kb(pid: int) -> int:
    try:
        for line in open(f"/proc/{pid}/status"):
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except OSError:
        pass
    return -1


def knob_cand(r: random.Random, n: int, i: int, bad: bool = False) -> Candidate:
    if n == 0:
        v = 9 if bad else r.randint(0, 5)
        return Candidate("retry-limit", None, "sweep", "sweep", f"s{i}",
                         raw_aura=f"(lambda (tool err) (cond (else {v})))")
    k = r.randrange(n)
    v = 500 if bad else r.randint(0, 100)
    return Candidate(f"knob-{k}", None, "sweep", "sweep", f"s{i} knob-{k}",
                     raw_aura=f"(lambda (x) (cond ((equal? x {r.randrange(4)}) {v}) (else 10)))")


def p50(xs):
    return round(1000 * statistics.median(xs), 2) if xs else None


def run(n: int, reps: int, seed: int) -> dict:
    os.environ["AURA_HARNESS_KNOBS"] = str(n)
    r = random.Random(seed)
    h = AuraHarness("ws")
    pid = h.pipe.p.pid
    lat = {k: [] for k in ("TABLE", "DECIDE", "APPLY", "TRIAL_ws", "VERDICT_ws", "TRIAL_snap", "VERDICT_snap", "SOURCE")}

    def tm(key, f):
        t = time.perf_counter(); out = f(); lat[key].append(time.perf_counter() - t); return out

    i = 0
    for _ in range(reps):
        i += 1
        tm("TABLE", h.table)
        tm("DECIDE", lambda: h.decide("route", "search"))
        res = tm("APPLY", lambda: h.apply(i, knob_cand(r, n, i)))
        assert res.get("ok"), res
        for wl in ("ws", "snap"):
            i += 1
            h.worldlines = wl
            trs = tm(f"TRIAL_{wl}", lambda: h.trial(i, [knob_cand(r, n, i), knob_cand(r, n, i, bad=True)]))
            assert trs[0]["ok"] and not trs[1]["ok"], trs
            tm(f"VERDICT_{wl}", lambda: h.verdict(i, -1, {"base": [0]}, "sweep rollback"))
    src = tm("SOURCE", h.source)
    bench = h.pipe.call("BENCH", 3)
    row = {"knobs": n, "defines": 9 + n + (1 if n else 0), "source_chars": len(src),
           "startup_s": round(h.startup_s, 3), "rss_mb": round(rss_kb(pid) / 1024, 1)}
    row.update({f"{k.lower()}_ms_p50": p50(v) for k, v in lat.items()})
    row["bench_us"] = {k: bench.get(k) for k in BENCH_KEYS}
    h.close()
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--knobs", default="0,50,200,500")
    ap.add_argument("--reps", type=int, default=20)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--chunk", type=int, default=16, help="knobs per knobs-chunk-j caller; 0 = one flat aggregator (aura#4615)")
    ap.add_argument("--out", default="runs/size_sweep.json")
    a = ap.parse_args()
    os.environ["AURA_HARNESS_KNOB_CHUNK"] = str(a.chunk)
    rows = []
    for n in [int(x) for x in a.knobs.split(",")]:
        row = run(n, a.reps, a.seed)
        rows.append(row)
        print(json.dumps(row), flush=True)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps({"reps": a.reps, "chunk": a.chunk, "rows": rows}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
