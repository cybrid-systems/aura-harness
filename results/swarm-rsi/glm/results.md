seeds [0, 1, 2, 3, 4], 160-task evolution stream (test layout moves at task 80), eval: 40 fresh held-out-repo tasks + 30 OOD-repo tasks per seed

| config | stream success | held-out success | held-out tokens / task | OOD success | OOD tokens / task | KEEP / ROLLBACK | false KEEPs (rate) |
|---|---|---|---|---|---|---|---|
| LLM + stat admission (M5b) | 21.5% | 45.5% | 11,654 | 33.3% | 10,726 | 1.2 / 0.6 | 0/6 (0%) |
| LLM + swarm + stat admission | 26.0% | 51.5% | 9,115 | 45.3% | 8,566 | 1.2 / 0.6 | 0/6 (0%) |
| LLM + better() | 69.9% | 92.0% | 12,898 | 74.7% | 11,153 | 4.0 / 3.6 | 1/20 (5%) |
| LLM + swarm + better() | 73.5% | 94.5% | 12,242 | 71.3% | 10,665 | 4.2 / 3.4 | 3/21 (14%) |

| config | wall s / seed | LLM calls (cache hits) | candidates gated / KEEP by LLM / KEEP by script | malformed responses / mutations | prompt+completion tokens | cost USD (total) |
|---|---|---|---|---|---|---|
| LLM + stat admission (M5b) | 1089 | 204 (137) | 405 / 6 / 0 | 0 / 0 of 405 | 224,268+151,512 | 0.0892 |
| LLM + swarm + stat admission | 730 | 107 (244) | 431 / 1 / 0 | 0 / 0 of 431 | 119,862+82,679 | 0.0490 |
| LLM + better() | 493 | 31 (47) | 99 / 20 / 0 | 0 / 0 of 99 | 36,103+37,822 | 0.0227 |
| LLM + swarm + better() | 422 | 32 (46) | 93 / 8 / 0 | 0 / 0 of 93 | 36,471+34,682 | 0.0206 |

Kept edits (seed 0, RSI loop): 
Kept edits (seed 0, LLM + stat admission (M5b)): compress test-log head-tail/1500
Kept edits (seed 0, LLM + swarm + stat admission): compress test-log head-tail/400
Kept edits (seed 0, LLM + better()): compress test-log head-tail/1500; route edit->apply-patch; compress test-log grep-errors/800; retry grep|timeout=3
Kept edits (seed 0, LLM + swarm + better()): compress test-log head-tail/400; route edit->apply-patch; compress test-log grep-errors/150; ttl test-cmd=12; route test->pytest-q

| config | FS run / base (regr / recov) | HD run / base | AULC10 run / base | AUC_E (repeat) | AUC_KA | accept rate | first-KEEP latency | replay execs / served | LLM tokens / USD |
|---|---|---|---|---|---|---|---|---|---|
| LLM + stat admission (M5b) | 0.0 / 0.0% (0.0 / 0.0) | 43.0 / 0.0% | 41.4 / 0.0% | 0.30 (0.00) | 48.0% | 0.70 | 62.2 | 2.61 | 75156 / 0.0178 |
| LLM + swarm + stat admission | 0.0 / 0.0% (0.0 / 0.0) | 52.0 / 0.0% | 50.4 / 0.0% | 0.90 (0.00) | 56.0% | 0.70 | 62.2 | 7.49 | 40508 / 0.0098 |
| LLM + better() | 55.5 / 0.0% (0.0 / 44.4) | 84.2 / 0.0% | 79.9 / 0.0% | 1.07 (0.00) | 64.0% | 0.55 | 3.6 | 4.58 | 14785 / 0.0046 |
| LLM + swarm + better() | 60.5 / 0.0% (0.0 / 48.4) | 86.5 / 0.0% | 81.6 / 0.0% | 1.59 (0.00) | 68.0% | 0.56 | 1.4 | 18.80 | 14231 / 0.0041 |

| config | KEEP / decisions (KEEP rate) | KEEPs by swarm-refined cand. | LLM tokens / KEEP | first KEEP at task (mean) | wall s / KEEP | false KEEPs (regressions) | FS regressions | held-out | OOD | swarm attempts / seed |
|---|---|---|---|---|---|---|---|---|---|---|
| LLM + stat admission (M5b) | 6 / 9 (67%) | - | 103,934 | 82 (5/5 seeds) | 907.7 | 0/6 | 0 | 45.5% | 33.3% | 0 |
| LLM + swarm + stat admission | 6 / 9 (67%) | 5 | 106,688 | 82 (5/5 seeds) | 608.1 | 0/6 | 0 | 51.5% | 45.3% | 23 |
| LLM + better() | 20 / 38 (53%) | - | 7,808 | 20 (5/5 seeds) | 123.2 | 1/20 | 0 | 92.0% | 74.7% | 0 |
| LLM + swarm + better() | 21 / 38 (55%) | 13 | 7,222 | 20 (5/5 seeds) | 100.4 | 3/21 | 0 | 94.5% | 71.3% | 56 |

Paired over seeds (LLM+swarm minus LLM-only, same provider): mean diff, exact sign-flip p

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
