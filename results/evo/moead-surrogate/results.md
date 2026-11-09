### surrogate prescreen — Issue #4943 acceptance (5 seeds)

Config: `gens=10 ask=10 propose=4 H=6 T=5 n=400 polish-rounds=2
polish-cap=84`; the surrogate arms add `--surrogate --max-gens 10`. Aura
lib: the `issue/fin4943` worktree (`AURA_PATH=<worktree>/lib`).

```sh
# A. baseline: full evaluation for every candidate
python3 -m aura_harness.evo --seeds 0 1 2 3 4 --gens 10 --ask 10 \
  --propose 4 --H 6 --T 5 --n 400 --polish-rounds 2 --polish-cap 84 \
  --jobs 5 --out results/evo/moead-nosurr --tag nosurr

# B. prescreen only (the first cut): GP/kNN ranks proposals, polish is full
python3 -m aura_harness.evo --seeds 0 1 2 3 4 --gens 10 --ask 10 \
  --propose 4 --H 6 --T 5 --n 400 --polish-rounds 2 --polish-cap 84 \
  --surrogate --max-gens 10 --polish-full 0 --jobs 5 \
  --out results/evo/moead-surrogate --tag prescreen-only

# C. prescreen + cheap-first polish (the second cut)
python3 -m aura_harness.evo --seeds 0 1 2 3 4 --gens 10 --ask 10 \
  --propose 4 --H 6 --T 5 --n 400 --polish-rounds 2 --polish-cap 84 \
  --surrogate --max-gens 10 --polish-full 16 --jobs 5 \
  --out results/evo/moead-surrogate --tag surrogate
```

"Full evaluations to target" is the count when the front first contains a
point that dominates the gated baseline and satisfies the 10 % token cut —
the issue's "same held-out success" point. All arms reach it on all five
seeds (`all_seeds_pass: true`).

| arm | seed 0 | 1 | 2 | 3 | 4 | total | vs A | vs B |
|---|---|---|---|---|---|---|---|---|
| A no surrogate | 291 | 287 | 130 | 132 | 303 | **1143** | — | — |
| B prescreen only | 252 | 22 | 103 | 104 | 180 | **661** | 42.2 % | — |
| C cheap-first polish | 71 | 22 | 41 | 45 | 58 | **237** | **79.3 %** | 64.1 % |

The acceptance bar is 40 %. On this tree the first cut alone is already at
42.2 %; the cheap-first polish takes it to **79.3 %**. (The earlier
27.7 % figure came from a run whose `run.json` records a `polish_values`
field that is not in HEAD, so its exact wiring cannot be reproduced here;
A/B/C above are the reproducible decomposition.)

All full evaluations: 1,706 (A) → 1,520 (B) → 429 (C), i.e. 74.9 % fewer
than A overall. Counting a cheap evaluation (1 seed × 200 tasks) as half a
full one (5 seeds × 400 tasks), simulated compute is 2,807 / 2,416 / 1,347
full-equivalents — 52 % less for C, so the saving is not bought by moving
work into the cheap stage.

What the second cut changed:

* the memetic polish sweep was the remaining cost: 84 coordinate probes ×
  4 batches per seed. Every probe is now scored on the cheap stream, the
  best probe **per gene** (a sweep tests one gene at a time) by distance to
  the acceptance point is kept, and only `--polish-full` (16) pay the full
  held-out evaluation.
* each prefilter is recorded in `generations[].screen.polish`
  (`n`, `cheap`, `kept`), so dropped probes remain auditable.
* `--polish-full 48` measures the same 78.8 % and the same front: the
  gate is the goal ranking, not the count. `0` restores arm B.

Front quality (reported, not part of the harness acceptance). Final
hypervolume against `[0.40, 9800, 250]`, ratio to arm A per seed:

| arm | 0 | 1 | 2 | 3 | 4 | mean |
|---|---|---|---|---|---|---|
| B prescreen only | 1.063 | 0.761 | 0.981 | 0.984 | 1.047 | 0.967 |
| C cheap-first | 0.973 | 0.727 | 0.829 | 0.845 | 0.856 | 0.846 |

The goal-directed polish converges on the acceptance knee, so the
token/latency wings lose hypervolume even though success and the token cut
are met on every seed. Arm B nearly preserves the front at 42.2 %; the
choice between B and C is a front-spread vs evaluation-budget trade. The
HV-parity item is the separate ZDT1 test in `std/surrogate`.

Files: `summary.json` (C), `prescreen-only.json` (B),
`baseline-nosurr.json` (A), one `seedN/run.json` + `evo-log.jsonl` per
seed (C).
