#!/usr/bin/env python3
"""Issue #4943 — false-kill audit for the cheap-first polish prefilter.

The surrogate run logs every cheap-first polish batch to
`polish-drops.jsonl`: the forwarded probes with their full goal, and every
dropped probe with its cheap score and genome. This script samples 10 % of
the dropped probes per batch, re-evaluates them on the full five held-out
streams, and reports the false-kill rate:

  false kill = the sampled probe's full goal is >= the worst forwarded
               probe's full goal in the same batch (it would have been an
               equally good forward and the prefilter threw it away).

It also reports the stricter ">= median forwarded" rate and the share of
false kills that would themselves satisfy the acceptance point.

Usage:
  python3 scripts/false_kill_4943.py \
      --dir results/evo/moead-surrogate --sample 0.10 \
      --json results/evo/moead-surrogate/false-kill.json
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
from pathlib import Path

from aura_harness.evo import genome as G
from aura_harness.evo.evaluate import evaluate

ROOT = Path(__file__).resolve().parents[1]
ISSUE_SUCCESS = 0.634
ISSUE_TOKEN_CUT = 0.90 * 8377.0


def goal_of(m: dict) -> float:
    return m["success"] - 1e-4 * max(0.0, m["tokens"] - ISSUE_TOKEN_CUT)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="false_kill_4943")
    ap.add_argument("--dir", default=str(ROOT / "results" / "evo" / "moead-surrogate"))
    ap.add_argument("--sample", type=float, default=0.10)
    ap.add_argument("--seed", type=int, default=4943)
    ap.add_argument("--json", default="")
    a = ap.parse_args(argv)

    base = Path(a.dir)
    rng = random.Random(a.seed)
    per_seed = []
    all_sampled = all_kills = all_strict = all_better = all_accept = 0
    for drops_file in sorted(base.glob("seed*/polish-drops.jsonl")):
        seed = int(drops_file.parent.name.removeprefix("seed"))
        rows = [json.loads(line) for line in drops_file.read_text().splitlines() if line.strip()]
        sampled = kills = strict = better = accept = 0
        sampled_goals: list[float] = []
        for row in rows:
            kept = row.get("kept_full") or []
            dropped = row.get("dropped") or []
            if not kept or not dropped:
                continue
            k = max(1, int(round(len(dropped) * a.sample)))
            for d in rng.sample(dropped, min(k, len(dropped))):
                tbl = G.decode(d["genome"])
                m = evaluate(tbl, seeds=(0, 1, 2, 3, 4), n=400)
                g = goal_of(m)
                sampled += 1
                sampled_goals.append(g)
                kept_goals = [x["goal"] for x in kept]
                if g >= min(kept_goals):
                    kills += 1
                    if m["success"] >= ISSUE_SUCCESS and m["tokens"] <= ISSUE_TOKEN_CUT:
                        accept += 1
                if g >= statistics.median(kept_goals):
                    strict += 1
                if g >= max(kept_goals):
                    better += 1
        per_seed.append({
            "seed": seed,
            "batches": len(rows),
            "dropped": sum(len(r.get("dropped") or []) for r in rows),
            "sampled": sampled,
            "false_kills": kills,
            "rate": (kills / sampled) if sampled else None,
            "strict_false_kills": strict,
            "strict_rate": (strict / sampled) if sampled else None,
            "better_than_best_forwarded": better,
            "better_than_best_rate": (better / sampled) if sampled else None,
            "false_kills_that_pass_acceptance": accept,
            "sampled_goal_mean": statistics.mean(sampled_goals) if sampled_goals else None,
        })
        all_sampled += sampled
        all_kills += kills
        all_strict += strict
        all_better += better
        all_accept += accept

    summary = {
        "sample": a.sample,
        "rng_seed": a.seed,
        "per_seed": per_seed,
        "sampled": all_sampled,
        "false_kills": all_kills,
        "false_kill_rate": (all_kills / all_sampled) if all_sampled else None,
        "strict_false_kills": all_strict,
        "strict_false_kill_rate": (all_strict / all_sampled) if all_sampled else None,
        "better_than_best_forwarded": all_better,
        "better_than_best_rate": (all_better / all_sampled) if all_sampled else None,
        "false_kills_that_pass_acceptance": all_accept,
    }
    text = json.dumps(summary, indent=1)
    print(text)
    if a.json:
        Path(a.json).write_text(text + chr(10))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
