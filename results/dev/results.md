seeds [0, 1, 2, 3, 4], 160-task evolution stream (test layout moves at task 80), eval: 40 fresh held-out-repo tasks + 30 OOD-repo tasks per seed

| config | stream success | held-out success | held-out tokens / task | OOD success | OOD tokens / task | KEEP / ROLLBACK |
|---|---|---|---|---|---|---|
| frozen seed harness | 0.0% | 0.0% | 1,694 | 0.0% | 1,700 | 0.0 / 0.0 |
| RSI loop (M1) | 76.5% | 95.5% | 12,831 | 74.7% | 11,121 | 4.2 / 3.8 |
| RSI + recombination (M2 pick) | 76.5% | 95.5% | 12,831 | 74.7% | 11,121 | 4.2 / 3.8 |
| RSI + retention (rho=0.05) | 76.8% | 95.5% | 12,941 | 74.0% | 11,018 | 4.2 / 3.6 |

Kept edits (seed 0, RSI loop): compress test-log grep-errors/800; route edit->apply-patch; retry grep|timeout=3
