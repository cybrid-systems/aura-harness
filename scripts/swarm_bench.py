"""Fiber-scaling bench for aura/swarm.aura (Agensh-style self-organizing workers).

python scripts/swarm_bench.py [--ns 1,8,32,128,1024] [--k 1024] [--f 64] [--reps 1]
Writes results/swarm-bench.json and results/swarm-bench.md. Needs AURA_BIN (and AURA_CWD = an Aura checkout for std/).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aura_harness.swarm import micro, run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ns", default="1,8,32,128,1024")
    ap.add_argument("--k", type=int, default=1024)
    ap.add_argument("--f", type=int, default=64)
    ap.add_argument("--cap", type=int, default=20000)
    ap.add_argument("--backend", default=os.environ.get("SWARM_BACKEND", "cli"))
    a = ap.parse_args()
    ns = [int(x) for x in a.ns.split(",")]
    out = {"aura_bin": os.environ.get("AURA_BIN"), "K": a.k, "F": a.f, "backend": a.backend, "epoch": [], "free": []}
    out["micro"] = micro(ns, backend=a.backend)
    print(json.dumps(out["micro"]), flush=True)
    for n in ns:
        r = run("epoch", n, a.k, a.f, a.cap, timeout=1800, backend=a.backend)
        out["epoch"].append(r); print(json.dumps(r), flush=True)
    for n in ns:
        r = run("free", n, a.k, a.f, a.cap, timeout=1800, backend=a.backend)
        out["free"].append(r); print(json.dumps(r), flush=True)
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "swarm-bench.json").write_text(json.dumps(out, indent=1))
    g = lambda r, k: r.get(k, 0)
    L = ["# swarm bench (aura/swarm.aura)", "", f"K={a.k} subtasks, F={a.f} families, backend={a.backend}, bin={out['aura_bin']}", "",
         "## epoch mode (one fiber per worker turn; ticker only advances time)", "",
         "| N | rounds | wall ms | spawn ms | join ms | gather | claim | act | verify | merge (ms, summed over turns) | turns run / spawned | join void | claim conflicts (live / already-done) | DMs (sent, mean latency rounds) | rebase / rollback | fact reuse | evals | board entries | peak RSS MB | accepted |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in out["epoch"]:
        dm = g(r, "dm-recv")
        L.append(f"| {r['N']} | {g(r,'rounds')} | {g(r,'wall-ms')} | {g(r,'t-spawn')} | {g(r,'t-join')} | {g(r,'t-gather')} | {g(r,'t-claim')} | {g(r,'t-act')} | {g(r,'t-verify')} | {g(r,'t-merge')} | {g(r,'turns-done')} / {g(r,'rounds')*r['N']} | {g(r,'join-void')} | {g(r,'claim-conflicts')} / {g(r,'claim-conflict-done')} | {g(r,'dm-sent')}, {round(g(r,'dm-latency-rounds')/dm,2) if dm else '-'} | {g(r,'merge-rebase')} / {g(r,'rolled-back')} | {g(r,'fact-reuse')} | {g(r,'evals')} | {g(r,'board')} | {round(g(r,'peak-rss-kb')/1024,1)} | {g(r,'accepted')} |")
    L += ["", "## free mode (one long-lived fiber per worker, fiber:yield between turns)", "",
          "| N | wall ms | spawn ms | done | max tasks merged by one worker | turns run | join void | peak RSS MB |", "|---|---|---|---|---|---|---|---|"]
    for r in out["free"]:
        L.append(f"| {r['N']} | {g(r,'wall-ms')} | {g(r,'t-spawn')} | {g(r,'done')} | {g(r,'max-worker-share')} | {g(r,'turns-done')} | {g(r,'join-void')} | {round(g(r,'peak-rss-kb')/1024,1)} |")
    mi = out["micro"]
    L += ["", "## micro", "", f"board: {mi['board']}", "", f"channel: {mi['chan']}", "",
          "| N fibers | spawn ms | join ms | join void | peak RSS MB | RSS over idle MB |", "|---|---|---|---|---|---|"]
    for d in mi["spawn"]:
        L.append(f"| {d.get('n')} | {d.get('spawn-ms')} | {d.get('join-ms')} | {d.get('join-void')} | {round(d.get('peak-rss-kb',0)/1024,1)} | {round(d.get('rss-over-idle-kb',0)/1024,1)} |")
    (ROOT / "results" / "swarm-bench.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
