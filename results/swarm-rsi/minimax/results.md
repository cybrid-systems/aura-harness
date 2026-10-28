seeds [0, 1, 2, 3, 4], 160-task evolution stream (test layout moves at task 80), eval: 40 fresh held-out-repo tasks + 30 OOD-repo tasks per seed

| config | stream success | held-out success | held-out tokens / task | OOD success | OOD tokens / task | KEEP / ROLLBACK | false KEEPs (rate) |
|---|---|---|---|---|---|---|---|
| LLM + stat admission (M5b) | 22.0% | 56.0% | 11,784 | 45.3% | 9,982 | 1.4 / 0.6 | 0/7 (0%) |
| LLM + swarm + stat admission | 26.2% | 62.5% | 10,076 | 53.3% | 9,267 | 1.4 / 0.8 | 0/7 (0%) |
| LLM + better() | 69.2% | 91.0% | 13,030 | 74.0% | 10,970 | 5.4 / 4.2 | 9/27 (33%) |
| LLM + swarm + better() | 73.6% | 93.5% | 12,434 | 76.0% | 10,485 | 4.2 / 4.8 | 4/21 (19%) |

| config | wall s / seed | LLM calls (cache hits) | candidates gated / KEEP by LLM / KEEP by script | malformed responses / mutations | prompt+completion tokens | cost USD (total) |
|---|---|---|---|---|---|---|
| LLM + stat admission (M5b) | 47 | 1 (343) | 364 / 7 / 0 | 0 / 0 of 364 | 1,291+4,127 | 0.0000 |
| LLM + swarm + stat admission | 520 | 84 (264) | 364 / 3 / 0 | 0 / 0 of 365 | 110,266+145,445 | 0.0000 |
| LLM + better() | 54 | 0 (88) | 92 / 27 / 0 | 0 / 0 of 92 | 0+0 | 0.0000 |
| LLM + swarm + better() | 358 | 38 (47) | 90 / 11 / 0 | 0 / 0 of 90 | 51,044+66,422 | 0.0000 |

Kept edits (seed 0, RSI loop): 
Kept edits (seed 0, LLM + stat admission (M5b)): compress test-log grep-errors/1000; route edit->apply-patch
Kept edits (seed 0, LLM + swarm + stat admission): compress test-log grep-errors/1000; route edit->apply-patch
Kept edits (seed 0, LLM + better()): compress test-log grep-errors/1000; route edit->apply-patch; ttl test-cmd=10; ttl test-cmd=0; ttl test-cmd=10; ttl test-cmd=0
Kept edits (seed 0, LLM + swarm + better()): compress test-log grep-errors/1000; route edit->apply-patch; ttl test-cmd=5

| config | FS run / base (regr / recov) | HD run / base | AULC10 run / base | AUC_E (repeat) | AUC_KA | accept rate | first-KEEP latency | replay execs / served | LLM tokens / USD |
|---|---|---|---|---|---|---|---|---|---|
| LLM + stat admission (M5b) | 0.0 / 0.0% (0.0 / 0.0) | 44.0 / 0.0% | 41.6 / 0.0% | 0.37 (0.00) | 48.0% | 0.73 | 62.2 | 3.19 | 1084 / 0.0000 |
| LLM + swarm + stat admission | 0.0 / 0.0% (0.0 / 0.0) | 52.5 / 0.0% | 50.0 / 0.0% | 0.83 (0.00) | 56.0% | 0.63 | 62.2 | 7.26 | 51142 / 0.0000 |
| LLM + better() | 55.5 / 0.0% (0.0 / 44.4) | 83.0 / 0.0% | 78.7 / 0.0% | 0.59 (0.11) | 64.0% | 0.59 | 1.8 | 5.06 | 0 / 0.0000 |
| LLM + swarm + better() | 59.0 / 0.0% (0.0 / 47.2) | 88.2 / 0.0% | 85.2 / 0.0% | 1.36 (0.03) | 68.0% | 0.46 | 0.4 | 19.32 | 23493 / 0.0000 |

| config | KEEP / decisions (KEEP rate) | KEEPs by swarm-refined cand. | LLM tokens / KEEP | first KEEP at task (mean) | wall s / KEEP | false KEEPs (regressions) | FS regressions | held-out | OOD | swarm attempts / seed |
|---|---|---|---|---|---|---|---|---|---|---|
| LLM + stat admission (M5b) | 7 / 10 (70%) | - | 100,484 | 82 (5/5 seeds) | 33.4 | 0/7 | 0 | 56.0% | 45.3% | 0 |
| LLM + swarm + stat admission | 7 / 11 (64%) | 4 | 111,173 | 82 (5/5 seeds) | 371.2 | 0/7 | 0 | 62.5% | 53.3% | 21 |
| LLM + better() | 27 / 48 (56%) | - | 7,174 | 20 (5/5 seeds) | 10.0 | 9/27 | 0 | 91.0% | 74.0% | 0 |
| LLM + swarm + better() | 21 / 45 (47%) | 10 | 9,415 | 20 (5/5 seeds) | 85.1 | 4/21 | 0 | 93.5% | 76.0% | 56 |

Paired over seeds (LLM+swarm minus LLM-only, same provider): mean diff, exact sign-flip p

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
