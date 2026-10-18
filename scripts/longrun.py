"""Long-run growth stress: N guarded changes / trial+verdict cycles in ONE Aura control-plane process.

Every block of --block steps prints p50 latency of APPLY, TRIAL (2 candidates), VERDICT (KEEP) and a DECIDE, the
control-plane RSS, and (every --bench-every blocks) the in-process BENCH breakdown, so growth can be attributed.
  python3 scripts/longrun.py --steps 2000 --block 100 --out runs/longrun.json
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aura_harness.control import AuraHarness  # noqa: E402
from aura_harness.env import NEEDS_TOOLS  # noqa: E402
from aura_harness.harness import COMPONENT, KINDS, MUTABLE, NEEDS, Candidate, delegate_map  # noqa: E402


def rand_cand(r: random.Random, tb: dict, i: int) -> Candidate:
    name = r.choice(MUTABLE)
    v = json.loads(json.dumps(tb[COMPONENT[name]]))
    if name == "route-tool":
        n = r.choice(NEEDS)
        v[n] = r.choice(NEEDS_TOOLS[n])
    elif name == "compress":
        v[r.choice(KINDS)] = [r.choice(["tail", "head-tail", "summarize", "grep-errors"]), r.choice([400, 800, 1600])]
    elif name == "retry-limit":
        v[r.choice(list(v))] = r.randint(0, 5)
    elif name == "memory-ttl":
        v[r.choice(list(v))] = r.choice([0, 40, 160])
    else:
        v = delegate_map({"refactor": r.randint(2, 6)})
    return Candidate(name, v, "longrun", "longrun", f"lr{i} {name}")


def rss_kb(pid: int) -> int:
    try:
        for line in open(f"/proc/{pid}/status"):
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except OSError:
        pass
    return -1


def p50(xs):
    return round(1000 * statistics.median(xs), 2) if xs else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=2000)
    ap.add_argument("--block", type=int, default=100)
    ap.add_argument("--bench-every", type=int, default=5)
    ap.add_argument("--worldlines", default="ws")
    ap.add_argument("--out", default="runs/longrun.json")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--mix", default="all", choices=["all", "apply", "trial-rollback", "trial-keep"],
                    help="which operations to repeat (all = apply / trial+keep / trial+rollback in turn)")
    a = ap.parse_args()
    r = random.Random(a.seed)
    h = AuraHarness(a.worldlines)
    pid = h.pipe.p.pid
    tb = h.table()
    rows = []
    t_start = time.perf_counter()
    blk = {"APPLY": [], "TRIAL": [], "VERDICT": [], "DECIDE": [], "SOURCE": []}
    for i in range(1, a.steps + 1):
        kind = {"all": i % 3, "apply": 0, "trial-keep": 1, "trial-rollback": 2}[a.mix]
        if kind == 0:
            t = time.perf_counter(); res = h.apply(i, rand_cand(r, tb, i)); blk["APPLY"].append(time.perf_counter() - t)
            if res.get("ok"):
                tb = res["table"]
        else:
            cands = [rand_cand(r, tb, i), rand_cand(r, tb, i + 100000)]
            t = time.perf_counter(); trs = h.trial(i, cands); blk["TRIAL"].append(time.perf_counter() - t)
            chosen = 0 if (kind == 1 and trs[0]["ok"]) else -1
            t = time.perf_counter(); v = h.verdict(i, chosen, {"base": [0]}, "longrun"); blk["VERDICT"].append(time.perf_counter() - t)
            if v.get("table"):
                tb = v["table"]
        t = time.perf_counter(); h.decide("route", "search"); blk["DECIDE"].append(time.perf_counter() - t)
        if i % a.block == 0:
            t = time.perf_counter(); src = h.source(); blk["SOURCE"].append(time.perf_counter() - t)
            ver = h.pipe.call("VERSION")
            row = {"step": i, "rss_mb": round(rss_kb(pid) / 1024, 1), "source_chars": len(src),
                   "compactions": ver.get("compactions"),
                   "wall_s": round(time.perf_counter() - t_start, 1)}
            row.update({f"{k.lower()}_ms_p50": p50(v) for k, v in blk.items()})
            if (i // a.block) % a.bench_every == 0 or i == a.block:
                row["bench_us"] = h.pipe.call("BENCH", 5)
            rows.append(row)
            print(json.dumps({k: v for k, v in row.items() if k != "bench_us"}), flush=True)
            if "bench_us" in row:
                b = row["bench_us"]
                print("   bench:", {k: b[k] for k in ("decision_call_us", "materialize_table_us", "rebind_eval_us",
                                                      "snapshot_us", "restore_eval_us", "guarded_apply_us", "trial_ws_us")}, flush=True)
            blk = {k: [] for k in blk}
    log_n = len(h.log())
    h.close()
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps({"steps": a.steps, "worldlines": a.worldlines, "audit_entries": log_n, "rows": rows}, indent=1))
    print("audit entries", log_n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
