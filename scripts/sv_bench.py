"""Swarm (orchestrator-free, aura/swarm.aura free mode) vs supervisor (orchestrated, aura/supervisor.aura) bench.

python scripts/sv_bench.py [--ns 1,2,4,8,16] [--k 1024] [--f 64]
Per N: correctness (lost / duplicate tasks, accepted), throughput, claim/dispatch-to-merge latency, ask/reply
round trip, worker-failure recovery, cooperative cancel, and the Aura orch:* primitives at N
(supervise-batch failure recovery, scope-cancel-all). Writes results/sv-bench.json and results/sv-bench.md.
Needs AURA_BIN (and AURA_CWD = an Aura checkout for std/). Same toy task and K/F for both modes.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aura_harness.swarm import run, run_expr, run_supervisor, validate, validate_supervisor  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def g(r: dict, k: str, d=0):
    return r.get(k, d)


def tput(r):
    return round(g(r, "done") / (g(r, "wall-ms") / 1000), 1) if g(r, "wall-ms") else 0


def mean(r, s, n):
    return round(g(r, s) / g(r, n), 2) if g(r, n) else "-"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ns", default="1,2,4,8,16")
    ap.add_argument("--k", type=int, default=1024)
    ap.add_argument("--f", type=int, default=64)
    ap.add_argument("--cap", type=int, default=20000)
    ap.add_argument("--iters", type=int, default=2000000)
    a = ap.parse_args()
    ns = [int(x) for x in a.ns.split(",")]
    out = {"aura_bin": os.environ.get("AURA_BIN"), "K": a.k, "F": a.f, "rows": []}
    out["orch_ask"] = run_expr("(orch-ask-probe 500)", {"exp": "orch-ask"}, supervisor=True)
    print(json.dumps(out["orch_ask"]), flush=True)
    for n in ns:
        sw = run("free", n, a.k, a.f, a.cap, timeout=1800)
        sw["dup-merges"] = g(sw, "commits") - g(sw, "done")
        sw["lost"] = a.k - g(sw, "done")
        sv_ = validate(n, a.k, a.f, a.cap)
        sv = run_supervisor(n, a.k, a.f, a.iters, timeout=1800)
        svv = validate_supervisor(n, a.k, a.f, a.iters)
        row = {"N": n, "swarm": sw, "swarm_validate": sv_, "supervisor": sv, "supervisor_validate": svv}
        out["rows"].append(row)
        print(json.dumps(row), flush=True)
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "sv-bench.json").write_text(json.dumps(out, indent=1))
    L = ["# swarm vs supervisor bench", "", f"K={a.k} subtasks, F={a.f} families, bin={out['aura_bin']}. Same toy task "
         "(aura/swarm.aura); swarm = free mode (N self-organizing workers), supervisor = 1 planner fiber + N stateless "
         "workers (aura/supervisor.aura). Single runs, wall-clock ms; no speedup claim (Aura fibers interleave on one "
         "evaluator, see aura#4707).", "",
         "## correctness, throughput, latency", "",
         "| N | mode | done / K | lost | dup merges | accepted | wall ms | tasks/s | mean latency ms | max latency ms | evals | worker turns / jobs |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in out["rows"]:
        for mode in ("swarm", "supervisor"):
            x = r[mode]
            L.append(f"| {r['N']} | {mode} | {g(x,'done')} / {a.k} | {g(x,'lost')} | {g(x,'dup-merges')} | {g(x,'accepted')} | {g(x,'wall-ms')} | {tput(x)} | {mean(x,'lat-ms','merged')} | {g(x,'lat-max-ms')} | {g(x,'evals')} | {g(x,'turns-done')} |")
    L += ["", "## ask/reply round trip (supervisor)", "",
          "Job RTT = dispatch on the worker inbox channel -> result back on the supervisor channel (includes the window scan). "
          "Ping = empty request/reply over the same channels, one outstanding at a time.", "",
          "| N | job RTT mean ms | job RTT max ms | jobs | ping mean ms | ping max ms | pings |", "|---|---|---|---|---|---|---|"]
    for r in out["rows"]:
        x, p = r["supervisor"], r["supervisor_validate"]["ping"]
        L.append(f"| {r['N']} | {mean(x,'rtt-ms','rtt-n')} | {g(x,'rtt-max-ms')} | {g(x,'rtt-n')} | {mean(p,'ping-wall-ms','ping-n')} | {g(p,'ping-max-ms')} | {g(p,'ping-n')} |")
    oa = out["orch_ask"]
    L += ["", f"orch:agent-ask to an in-process responder (timeout 500 ms): status={g(oa,'ask-status')}, elapsed {g(oa,'ask-ms')} ms, "
          f"responder agent-reply status={g(oa,'ask-reply-status')} (aura#4722).", "",
          "## worker failure (worker 0 raises holding work) and cooperative cancel", "",
          "| N | mode | join errors | recovered via | done | accepted | wall ms | cancel: stop->last exit ms | done at stop | partial valid |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for r in out["rows"]:
        f1, c1 = r["swarm_validate"]["fail"], r["swarm_validate"]["cancel"]
        f2, c2 = r["supervisor_validate"]["fail"], r["supervisor_validate"]["cancel"]
        L.append(f"| {r['N']} | swarm | {g(f1,'join-error')} | {g(f1,'claims-stolen')} lease steals | {g(f1,'done')} | {g(f1,'accepted')} | {g(f1,'wall-ms')} | {g(c1,'cancel-lat-ms')} | {g(c1,'done')} | {g(c1,'done-valid')} |")
        L.append(f"| {r['N']} | supervisor | {g(f2,'join-error')} | {g(f2,'jobs-redispatched')} re-dispatched jobs | {g(f2,'done')} | {g(f2,'accepted')} | {g(f2,'wall-ms')} | {g(c2,'cancel-lat-ms')} | {g(c2,'done')} | {g(c2,'done-valid')} |")
    L += ["", "## Aura orch:* primitives at N", "",
          "supervise-batch: N tasks, task 0 raises, policy collect-all :max-retries 1. scope-cancel-all: N orch:scope-spawn bodies "
          "looping on fiber:yield; cancel, yield 2000 times, count body steps, then scope-join-all :timeout-ms 1000; then set the "
          "cooperative stop flag and join again.", "",
          "| N | supervise-batch default watch: status ok/err ran | :watch-scope #f: status ok/err ran | cancel-all cancelled | body steps after cancel | join-all(1000ms) status / ms | after stop flag: status / ms |",
          "|---|---|---|---|---|---|---|"]
    for r in out["rows"]:
        o = r["supervisor_validate"]["orch"]
        L.append(f"| {r['N']} | {g(o,'sbw-status')} {g(o,'sbw-ok')}/{g(o,'sbw-err')} ran {g(o,'sbw-ran')} | {g(o,'sbn-status')} {g(o,'sbn-ok')}/{g(o,'sbn-err')} ran {g(o,'sbn-ran')} | {g(o,'cx-cancelled')} | {g(o,'cx-steps-after-cancel')} | {g(o,'cx-join-status')} / {g(o,'cx-join-ms')} | {g(o,'cx-join2-status')} / {g(o,'cx-join2-ms')} |")
    (ROOT / "results" / "sv-bench.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
