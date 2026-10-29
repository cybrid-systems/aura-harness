# LLM proposes, swarm fine-tunes: a local searcher inside the RSI loop

`aura_harness/rsi/localsearch.py` (`SwarmRefiner`), switched on with `M2Config(swarm=True)`; bench `dev-bench --set swarm`.

## Where it sits

```
RuleSource / LLMProposer  ->  CandidateQueue (stat mode keeps its queue)  ->  SwarmRefiner  ->  critic / recombine / budget
   -> h.trial (Aura guard, server.aura)  ->  window gate (selection split)  ->  stat admission on fresh one-use tasks
   -> h.apply / ROLLBACK  ->  ledger
```

The LLM decides *what* to change: a typed mutation (route / compress / retry / ttl / delegate). The swarm refines the
*parameters* of that mutation. For each of up to `max_parents=3` LLM candidates of a round, it hill-climbs for `swarm_rounds=2`
rounds over at most `swarm_width=6` typed neighbours:

| kind | neighbours |
|---|---|
| compress | limit ×0.5 / ×0.75 / ×1.5 / ×2 (rounded to 50, 100-2000), other strategies |
| retry | n−1, n+1, 0, n+2 (0-5) |
| ttl | n/2, 2n, n±10, 0 |
| delegate | threshold ±1 or inline; from inline: 3, 5 |
| route | the other tools for the same need |

Every neighbour is built with the LLM validator (`rsi/llm.build`), so it is range-checked and is an ordinary `Candidate`. Refined
candidates go *in front of* their parents in the round, and both continue through the unchanged critic, Aura guard, gate and
admission. The swarm never admits anything itself.

## Coordinator path (no shared mutation, aura#4730)

The refiner is the single writer. Workers are pure functions (`train_score`): each replays the window's **evidence** tasks on a
private copy of the memory with the candidate applied to a copy of the harness table, and returns one tuple `(ok, n, tokens)` as
its message. The workers run through the loop's `pmap` (a process pool when `--jobs > 1`). The coordinator assigns attempt ids
`sw<task>.<k>`, records each attempt and keeps the best by `better()` (more evidence successes, then fewer tokens).

## Admission stays honest

The swarm scores on evidence tasks only, which is what the proposer sees. Held-out tasks are kept for the gate's selection split
and for the fresh one-use admission split, so the sign test in stat admission is the same test as without the swarm. The refine
hook runs only when the window has `min_heldout` held-out tasks, as the gate requires. Replayed evidence tasks are added to
`learn` replay, so the existing replay cost metric includes the swarm's cost.

## Providers

`AURA_LLM_PROVIDER=deepseek | minimax | glm | mixed | a,b` (`rsi/llm.py`, `PROVIDERS`). An unknown name raises.
* `glm`: `glm-5.3-flash` on `open.bigmodel.cn/api/coding/paas/v4`. The key is read per request from `GLM_KEY_FILE` (default `~/.glm-key`). `AURA_GLM_MODEL/BASE_URL/MAX_OUT/PRICE` override the defaults.
* `minimax`: `MiniMax-M3.1-Flash`. The key file and the base URL come from `minimax.env` (`AURA_MINIMAX_ENV`), so they match aura-scm-agents.
* `deepseek`: `deepseek-flash`, key from `DEEPSEEK_KEY_FILE`.

`reasoning_effort` is sent only to DeepSeek. Keys are never cached, logged or written; `tests/test_localsearch.py` asserts this for GLM.

## Traces and ledger

`RsiTrace.swarm(info)` emits an `rsi.swarm` span with one `rsi.swarm_attempt` child per attempt. Each child carries
`swarm.attempt_id`, `parent_id`, `desc`, `round`, `ok`, `n`, `tokens` and `accepted`; the round span carries `swarm.attempt_ids`.
Each refined candidate has meta `proposer="llm+swarm"`, plus `swarm={parent, parent_id, attempt_id, lineage}`. Proposal spans, ledger
`admit` events and verdicts carry `swarm_attempt`. The run output reports `swarm` (attempts, improved, kept, kept_attempts) and
`llm.swarm_kept`.

## Results: dev-bench `--set swarm`, 5 seeds x 160 tasks, `--n 160`

Same M3 world and seeds as M5/M5b. "LLM-only" is the M5/M5b proposer; "LLM+swarm" adds `SwarmRefiner`. A false KEEP lowers
success on the independent post-hoc fresh held-out set, or is reverted by a later KEEP. LLM tokens / KEEP counts prompt+completion
tokens including cache replays (`equiv_tokens`), so cached and live runs are comparable. Wall time depends on provider latency
and on box load. Results: `results/swarm-rsi/{deepseek,glm,minimax}` (`results.md`, `results.json`, ledgers).

### DeepSeek (`deepseek-flash`)

| config | KEEP / decisions (KEEP rate) | KEEPs by swarm-refined cand. | LLM tokens / KEEP | first KEEP at task (mean) | wall s / KEEP | false KEEPs (regressions) | FS regressions | held-out | OOD | swarm attempts / seed |
|---|---|---|---|---|---|---|---|---|---|---|
| LLM + stat admission (M5b) | 5 / 7 (71%) | - | 102,598 | 82 (5/5 seeds) | 27.2 | 0/5 | 0 | 30.5% | 22.0% | 0 |
| LLM + swarm + stat admission | 7 / 9 (78%) | 5 | 72,468 | 82 (5/5 seeds) | 59.6 | 0/7 | 0 | 63.0% | 53.3% | 25 |
| LLM + better() | 24 / 45 (53%) | - | 5,719 | 20 (5/5 seeds) | 22.3 | 0/24 | 0 | 94.0% | 78.0% | 0 |
| LLM + swarm + better() | 19 / 40 (48%) | 10 | 6,506 | 20 (5/5 seeds) | 52.7 | 3/19 | 0 | 95.0% | 73.3% | 67 |

Paired over seeds (LLM+swarm minus LLM-only), exact sign-flip p:

| admission | metric | mean diff | p | wins/ties/losses |
|---|---|---|---|---|
| stat admission | held-out success | +0.325 | 0.062 | 5/0/0 |
| stat admission | OOD success | +0.313 | 0.125 | 4/1/0 |
| stat admission | stream success | +0.089 | 0.062 | 5/0/0 |
| stat admission | KEEPs | +0.400 | 0.500 | 2/3/0 |
| stat admission | false KEEPs | +0.000 | 1.000 | 0/5/0 |
| better() | held-out success | +0.010 | 0.750 | 2/2/1 |
| better() | OOD success | -0.047 | 0.250 | 0/2/3 |
| better() | stream success | +0.061 | 0.125 | 4/1/0 |
| better() | KEEPs | -1.000 | 0.250 | 1/0/4 |
| better() | false KEEPs | +0.600 | 0.500 | 2/3/0 |

### GLM (`glm-5.3-flash`)

| config | KEEP / decisions (KEEP rate) | KEEPs by swarm-refined cand. | LLM tokens / KEEP | first KEEP at task (mean) | wall s / KEEP | false KEEPs (regressions) | FS regressions | held-out | OOD | swarm attempts / seed |
|---|---|---|---|---|---|---|---|---|---|---|
| LLM + stat admission (M5b) | 6 / 9 (67%) | - | 103,934 | 82 (5/5 seeds) | 907.7 | 0/6 | 0 | 45.5% | 33.3% | 0 |
| LLM + swarm + stat admission | 6 / 9 (67%) | 5 | 106,688 | 82 (5/5 seeds) | 608.1 | 0/6 | 0 | 51.5% | 45.3% | 23 |
| LLM + better() | 20 / 38 (53%) | - | 7,808 | 20 (5/5 seeds) | 123.2 | 1/20 | 0 | 92.0% | 74.7% | 0 |
| LLM + swarm + better() | 21 / 38 (55%) | 13 | 7,222 | 20 (5/5 seeds) | 100.4 | 3/21 | 0 | 94.5% | 71.3% | 56 |

Paired over seeds (LLM+swarm minus LLM-only), exact sign-flip p:

| admission | metric | mean diff | p | wins/ties/losses |
|---|---|---|---|---|
| stat admission | held-out success | +0.060 | 0.250 | 3/2/0 |
| stat admission | OOD success | +0.120 | 0.250 | 3/2/0 |
| stat admission | stream success | +0.045 | 0.062 | 5/0/0 |
| stat admission | KEEPs | +0.000 | 1.000 | 0/5/0 |
| stat admission | false KEEPs | +0.000 | 1.000 | 0/5/0 |
| better() | held-out success | +0.025 | 0.375 | 3/1/1 |
| better() | OOD success | -0.033 | 0.500 | 0/3/2 |
| better() | stream success | +0.036 | 0.250 | 3/0/2 |
| better() | KEEPs | +0.200 | 1.000 | 2/2/1 |
| better() | false KEEPs | +0.400 | 1.000 | 1/4/0 |

### MiniMax (`MiniMax-M3.1-Flash`)

| config | KEEP / decisions (KEEP rate) | KEEPs by swarm-refined cand. | LLM tokens / KEEP | first KEEP at task (mean) | wall s / KEEP | false KEEPs (regressions) | FS regressions | held-out | OOD | swarm attempts / seed |
|---|---|---|---|---|---|---|---|---|---|---|
| LLM + stat admission (M5b) | 7 / 10 (70%) | - | 100,484 | 82 (5/5 seeds) | 33.4 | 0/7 | 0 | 56.0% | 45.3% | 0 |
| LLM + swarm + stat admission | 7 / 11 (64%) | 4 | 111,173 | 82 (5/5 seeds) | 371.2 | 0/7 | 0 | 62.5% | 53.3% | 21 |
| LLM + better() | 27 / 48 (56%) | - | 7,174 | 20 (5/5 seeds) | 10.0 | 9/27 | 0 | 91.0% | 74.0% | 0 |
| LLM + swarm + better() | 21 / 45 (47%) | 10 | 9,415 | 20 (5/5 seeds) | 85.1 | 4/21 | 0 | 93.5% | 76.0% | 56 |

Paired over seeds (LLM+swarm minus LLM-only), exact sign-flip p:

| admission | metric | mean diff | p | wins/ties/losses |
|---|---|---|---|---|
| stat admission | held-out success | +0.065 | 0.500 | 2/3/0 |
| stat admission | OOD success | +0.080 | 0.500 | 2/3/0 |
| stat admission | stream success | +0.042 | 0.125 | 4/1/0 |
| stat admission | KEEPs | +0.000 | 1.000 | 0/5/0 |
| stat admission | false KEEPs | +0.000 | 1.000 | 0/5/0 |
| better() | held-out success | +0.025 | 0.750 | 2/2/1 |
| better() | OOD success | +0.020 | 0.625 | 3/1/1 |
| better() | stream success | +0.044 | 0.062 | 5/0/0 |
| better() | KEEPs | -1.200 | 0.250 | 1/0/4 |
| better() | false KEEPs | -1.000 | 0.375 | 1/1/3 |

### Reading

* **Stat admission (the honest path).** The swarm never adds a false KEEP (0 for every provider and arm) and raises held-out and
  OOD success for every provider: DeepSeek +32.5 / +31.3 pts (5/0/0 wins, p=0.062), GLM +6.0 / +12.0 pts (p=0.25),
  MiniMax +6.5 / +8.0 pts (p=0.5). With 5 seeds the smallest possible two-sided p is 0.0625, so none of these is significant
  at 0.05. DeepSeek is the clear case; GLM and MiniMax are positive, but the evidence for them is weak.
* **Tokens per KEEP** go down with DeepSeek (102.6k → 72.5k), stay level with GLM (103.9k → 106.7k) and go up with MiniMax
  (100.5k → 111.2k). The swarm costs no LLM calls itself, but it changes which proposals are asked for next.
* **Time to KEEP.** The first KEEP comes at the same stream task (82 under stat, 20 under better()), because admission waits for
  fresh tasks either way. Wall s / KEEP rises because the evidence replays run on the box (MiniMax 33 → 371 s, DeepSeek 27 → 60 s).
  It falls only for GLM (908 → 608 s), whose LLM latency dominates.
* **better() admission.** The swarm gains little on held-out (+1.0 to +2.5 pts) and makes fewer KEEPs. It adds false KEEPs with
  DeepSeek (0 → 3) and GLM (1 → 3), and removes some with MiniMax (9 → 4). Fine-tuning parameters against evidence makes the
  weak better() gate easier to pass. Pair the swarm with stat admission.
* **FS regressions:** 0 in every arm.
* DeepSeek LLM+swarm+stat matches the scripted+stat row of M5b exactly on held-out and OOD (63.0% / 53.3%, 0/7 false KEEPs).
  The kept edits differ, though: on seed 0 the swarm keeps `compress grep-errors/500` + `route edit->apply-patch`. So both are
  probably solving the same task subset; this was not checked further.
* Caveats: 5 seeds; one scripted world. MiniMax cost is not tallied, because no list price is pinned (`AURA_MINIMAX_PRICE`);
  tokens are reported instead. The DeepSeek run is a full cache replay of an earlier live run (109 + 33 live calls,
  $0.019 + $0.010). GLM made 204 + 107 + 31 + 32 live calls ($0.089 / $0.049 / $0.023 / $0.021).

## Tests

The new tests are `tests/test_localsearch.py`: 8 tests, 7 pass and 1 is skipped. They cover the neighbours, the coordinator as single
writer, attempt ids in traces and the ledger, honest admission, providers, and the absence of the GLM key on disk.
`tests/test_metrics.py` gained a test for the MiniMax env file. On `e6f4169e0` these modules pass: audit, devenv, env, fuzz, llm,
localsearch, m6, metrics, queue, stat, and rsi (`test_supervisor_survives_4670_trace` excluded).

**Re-check on `d54b2117d` (2026-10-29):** `test_control` (25, one expected failure, aura#4764), `test_obs` (10), `test_supervisor` (5), `test_localsearch` (8)
and `test_rsi` (15, including `test_supervisor_survives_4670_trace`) pass. `test_swarm` passes except for a rare deadlock (aura#4765, retried) and a
rare `claims-held=1` after cancel (aura#4761). The supervisor's dead workers were a tick-lease artefact of parallel bodies. Leases are now
wall-clock as well (README, "Re-check on d54b2117d"). The single-writer design stays: parallel `set!` read-modify-writes still lose
updates (aura#4761), and `set!` after an overlay commit is dropped (aura#4757).

On `e6f4169e0` these failed in exactly the same way on the parent commit `8428257`, so they were not caused by this change:
* `test_control` (5 failures) and `test_obs`, `test_supervisor`, `test_swarm`. Their fiber/swarm Aura programs fail with
  `cannot resolve 'std/list'` or `<error>`; see aura#4730.
* `test_rsi.test_supervisor_survives_4670_trace`, which hangs.
