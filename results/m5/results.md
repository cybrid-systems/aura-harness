seeds [0, 1, 2, 3, 4], 160-task evolution stream (test layout moves at task 80), eval: 40 fresh held-out-repo tasks + 30 OOD-repo tasks per seed

| config | stream success | held-out success | held-out tokens / task | OOD success | OOD tokens / task | KEEP / ROLLBACK | false KEEPs (rate) |
|---|---|---|---|---|---|---|---|
| frozen seed harness | 0.0% | 0.0% | 1,694 | 0.0% | 1,700 | 0.0 / 0.0 | 0/0 (0%) |
| RSI loop (M1) | 76.5% | 95.5% | 12,831 | 74.7% | 11,121 | 4.2 / 3.8 | 6/21 (29%) |
| RSI + LLM proposer (M5) | 68.4% | 94.0% | 12,918 | 78.0% | 11,043 | 4.8 / 4.2 | 0/24 (0%) |
| RSI + LLM+scripted hybrid (M5) | 76.6% | 95.5% | 12,845 | 74.7% | 11,103 | 4.0 / 3.8 | 5/20 (25%) |

| config | wall s / seed | LLM calls (cache hits) | candidates gated / KEEP by LLM / KEEP by script | malformed responses / mutations | prompt+completion tokens | cost USD (total) |
|---|---|---|---|---|---|---|
| frozen seed harness | 0 | - | - | - | - | - |
| RSI loop (M1) | 79 | - | - | - | - | - |
| RSI + LLM proposer (M5) | 119 | 79 (6) | 125 / 24 / 0 | 0 / 0 of 125 | 99,199+29,472 | 0.0215 |
| RSI + LLM+scripted hybrid (M5) | 95 | 34 (45) | 102 / 9 / 11 | 0 / 0 of 102 | 45,124+12,824 | 0.0093 |

Kept edits (seed 0, RSI loop): compress test-log grep-errors/800; route edit->apply-patch; retry grep|timeout=3
Kept edits (seed 0, RSI + LLM proposer (M5)): compress test-log grep-errors/2000; route edit->apply-patch; compress test-log grep-errors/1000; retry grep|timeout=3
Kept edits (seed 0, RSI + LLM+scripted hybrid (M5)): compress test-log grep-errors/800; route edit->apply-patch; retry grep|timeout=3
