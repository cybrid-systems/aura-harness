seeds [0, 1, 2, 3, 4], 160-task evolution stream (test layout moves at task 80), eval: 40 fresh held-out-repo tasks + 30 OOD-repo tasks per seed

| config | stream success | held-out success | held-out tokens / task | OOD success | OOD tokens / task | KEEP / ROLLBACK | false KEEPs (rate) |
|---|---|---|---|---|---|---|---|
| LLM + stat admission (M5b) | 17.6% | 30.5% | 12,286 | 22.0% | 10,039 | 1.0 / 0.4 | 0/5 (0%) |
| LLM + swarm + stat admission | 26.5% | 63.0% | 10,132 | 53.3% | 8,877 | 1.4 / 0.4 | 0/7 (0%) |
| LLM + better() | 68.4% | 94.0% | 12,918 | 78.0% | 11,043 | 4.8 / 4.2 | 0/24 (0%) |
| LLM + swarm + better() | 74.5% | 95.0% | 12,851 | 73.3% | 11,028 | 3.8 / 4.2 | 3/19 (16%) |

| config | wall s / seed | LLM calls (cache hits) | candidates gated / KEEP by LLM / KEEP by script | malformed responses / mutations | prompt+completion tokens | cost USD (total) |
|---|---|---|---|---|---|---|
| LLM + stat admission (M5b) | 27 | 0 (344) | 503 / 5 / 0 | 2 / 0 of 506 | 0+0 | 0.0000 |
| LLM + swarm + stat admission | 83 | 0 (352) | 478 / 2 / 0 | 0 / 0 of 481 | 0+0 | 0.0000 |
| LLM + better() | 107 | 0 (85) | 124 / 24 / 0 | 0 / 0 of 124 | 0+0 | 0.0000 |
| LLM + swarm + better() | 200 | 0 (80) | 107 / 9 / 0 | 0 / 0 of 107 | 0+0 | 0.0000 |

Kept edits (seed 0, RSI loop): 
Kept edits (seed 0, LLM + stat admission (M5b)): compress test-log grep-errors/2000
Kept edits (seed 0, LLM + swarm + stat admission): compress test-log grep-errors/500; route edit->apply-patch
Kept edits (seed 0, LLM + better()): compress test-log grep-errors/2000; route edit->apply-patch; compress test-log grep-errors/1000; retry grep|timeout=3
Kept edits (seed 0, LLM + swarm + better()): compress test-log grep-errors/500; route edit->apply-patch; retry grep|timeout=3

| config | FS run / base (regr / recov) | HD run / base | AULC10 run / base | AUC_E (repeat) | AUC_KA | accept rate | first-KEEP latency | replay execs / served | LLM tokens / USD |
|---|---|---|---|---|---|---|---|---|---|
| LLM + stat admission (M5b) | 0.0 / 0.0% (0.0 / 0.0) | 35.2 / 0.0% | 33.8 / 0.0% | 0.20 (0.00) | 44.0% | 0.80 | 62.0 | 2.68 | 0 / 0.0000 |
| LLM + swarm + stat admission | 0.0 / 0.0% (0.0 / 0.0) | 53.0 / 0.0% | 50.4 / 0.0% | 1.40 (0.00) | 56.0% | 0.83 | 62.2 | 8.76 | 0 / 0.0000 |
| LLM + better() | 51.5 / 0.0% (0.0 / 41.2) | 85.2 / 0.0% | 80.0 / 0.0% | 1.43 (0.02) | 64.0% | 0.56 | 3.0 | 5.90 | 0 / 0.0000 |
| LLM + swarm + better() | 62.2 / 0.0% (0.0 / 49.8) | 86.8 / 0.0% | 81.2 / 0.0% | 1.88 (0.02) | 68.0% | 0.49 | 0.7 | 21.84 | 0 / 0.0000 |

| config | KEEP / decisions (KEEP rate) | KEEPs by swarm-refined cand. | LLM tokens / KEEP | first KEEP at task (mean) | wall s / KEEP | false KEEPs (regressions) | FS regressions | held-out | OOD | swarm attempts / seed |
|---|---|---|---|---|---|---|---|---|---|---|
| LLM + stat admission (M5b) | 5 / 7 (71%) | - | 102,598 | 82 (5/5 seeds) | 27.2 | 0/5 | 0 | 30.5% | 22.0% | 0 |
| LLM + swarm + stat admission | 7 / 9 (78%) | 5 | 72,468 | 82 (5/5 seeds) | 59.6 | 0/7 | 0 | 63.0% | 53.3% | 25 |
| LLM + better() | 24 / 45 (53%) | - | 5,719 | 20 (5/5 seeds) | 22.3 | 0/24 | 0 | 94.0% | 78.0% | 0 |
| LLM + swarm + better() | 19 / 40 (48%) | 10 | 6,506 | 20 (5/5 seeds) | 52.7 | 3/19 | 0 | 95.0% | 73.3% | 67 |

Paired over seeds (LLM+swarm minus LLM-only, same provider): mean diff, exact sign-flip p

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
