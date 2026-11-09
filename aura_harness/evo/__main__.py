"""CLI: python3 -m aura_harness.evo --seeds 0 1 2 3 4 --out results/evo/moead

Runs the evo search described in run.py, one independent search seed per
output directory, and writes the aggregated summary.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
from pathlib import Path

from .evaluate import baseline_point
from .run import Cfg, run, run_worker

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASELINE = ROOT / "results" / "evo" / "baseline-bench.json"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m aura_harness.evo")
    ap.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2, 3, 4])
    ap.add_argument("--gens", type=int, default=12)
    ap.add_argument("--ask", type=int, default=6)
    ap.add_argument("--propose", type=int, default=3)
    ap.add_argument("--H", type=int, default=4)
    ap.add_argument("--T", type=int, default=5)
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--surrogate", action="store_true")
    ap.add_argument("--no-prescreen", action="store_true")
    ap.add_argument("--no-staged", action="store_true")
    ap.add_argument("--gate", type=float, default=0.45)
    ap.add_argument("--race-margin", type=float, default=0.05)
    ap.add_argument("--race", action="store_true")
    ap.add_argument("--restarts", type=int, default=0, help="kill/restart the Aura process N times mid-run")
    ap.add_argument("--hv-target", type=float, default=None)
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--polish-rounds", type=int, default=2)
    ap.add_argument("--polish-cap", type=int, default=84)
    ap.add_argument("--max-gens", type=int, default=36)
    ap.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    ap.add_argument("--out", default=str(ROOT / "results" / "evo" / "moead"))
    ap.add_argument("--tag", default="moead")
    a = ap.parse_args(argv)

    with open(a.baseline) as fh:
        bench = json.load(fh)
    base = baseline_point(bench)
    # The issue's acceptance point: the gated bench's five-seed held-out mean
    # (63.4%, 8,377 tokens). Latency comes from the gated tables, re-scored on
    # the same streams, because the README never measured it.
    base["issue"] = {"success": 0.634, "tokens": 8377.0,
                     "latency": base["mean"]["latency"]}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "baseline-point.json", "w") as fh:
        json.dump(base, fh, indent=1)

    jobs = []
    for s in a.seeds:
        cfg = Cfg(search_seed=s, gens=a.gens, ask=a.ask, propose=a.propose, H=a.H, T=a.T,
                  n=a.n, surrogate=a.surrogate, prescreen=not a.no_prescreen,
                  staged=not a.no_staged, gate=a.gate,
                  hv_target=a.hv_target, max_gens=a.max_gens,
                  polish_rounds=a.polish_rounds, polish_cap=a.polish_cap,
                  race_margin=a.race_margin, race=a.race,
                  restarts_at=tuple(range(3, max(3, a.max_gens), 4))[:a.restarts] if a.restarts else (),
                  tag=a.tag)
        jobs.append((cfg, base, str(out / f"seed{s}")))
    if a.jobs > 1 and len(jobs) > 1:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(a.jobs) as ex:
            results = list(ex.map(run_worker, jobs))
    else:
        results = [run_worker(j) for j in jobs]

    summary = {
        "tag": a.tag, "surrogate": a.surrogate, "staged": not a.no_staged,
        "gens": a.gens, "seeds": a.seeds, "baseline": base["mean"],
        "per_seed": [{"seed": r["search_seed"], "front": r["front"],
                      "criteria": r["criteria"], "full_evals": r["full_evals"],
                      "cheap_evals": r["cheap_evals"],
                      "full_evals_to_target": r["full_evals_to_target"],
                      "hv": r["hv"], "restarts": r["restarts"]} for r in results],
    }
    summary["all_seeds_pass"] = all(r["criteria"]["dominates_baseline"] and r["criteria"]["token_cut_10"]
                                    for r in results)
    summary["full_evals_total"] = sum(r["full_evals"] for r in results)
    targets = [r["full_evals_to_target"] for r in results]
    summary["full_evals_to_target_total"] = (
        sum(targets) if all(t is not None for t in targets) else None)
    with open(out / "summary.json", "w") as fh:
        json.dump(summary, fh, indent=1)
    print(json.dumps({k: summary[k] for k in ("tag", "all_seeds_pass", "full_evals_total",
                                              "baseline")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
