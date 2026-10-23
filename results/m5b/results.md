seeds [0, 1, 2, 3, 4], 160-task evolution stream (test layout moves at task 80), eval: 40 fresh held-out-repo tasks + 30 OOD-repo tasks per seed

| config | stream success | held-out success | held-out tokens / task | OOD success | OOD tokens / task | KEEP / ROLLBACK | false KEEPs (rate) |
|---|---|---|---|---|---|---|---|
| frozen seed harness | 0.0% | 0.0% | 1,694 | 0.0% | 1,700 | 0.0 / 0.0 | 0/0 (0%) |
| RSI loop (M1) | 76.5% | 95.5% | 12,831 | 74.7% | 11,121 | 4.2 / 3.8 | 6/21 (29%) |
| scripted + stat admission (M5b) | 26.5% | 63.0% | 10,137 | 53.3% | 8,879 | 1.4 / 0.6 | 0/7 (0%) |
| RSI + LLM proposer (M5) | 68.4% | 94.0% | 12,918 | 78.0% | 11,043 | 4.8 / 4.2 | 0/24 (0%) |
| LLM + stat admission (M5b) | 17.6% | 30.5% | 12,286 | 22.0% | 10,039 | 1.0 / 0.4 | 0/5 (0%) |

| config | wall s / seed | LLM calls (cache hits) | candidates gated / KEEP by LLM / KEEP by script | malformed responses / mutations | prompt+completion tokens | cost USD (total) |
|---|---|---|---|---|---|---|
| frozen seed harness | 0 | - | - | - | - | - |
| RSI loop (M1) | 76 | - | - | - | - | - |
| scripted + stat admission (M5b) | 41 | - | - | - | - | - |
| RSI + LLM proposer (M5) | 74 | 0 (85) | 124 / 24 / 0 | 0 / 0 of 124 | 0+0 | 0.0000 |
| LLM + stat admission (M5b) | 116 | 165 (179) | 503 / 5 / 0 | 2 / 0 of 506 | 202,468+51,943 | 0.0379 |

Kept edits (seed 0, RSI loop): compress test-log grep-errors/800; route edit->apply-patch; retry grep|timeout=3
Kept edits (seed 0, RSI + LLM proposer (M5)): compress test-log grep-errors/2000; route edit->apply-patch; compress test-log grep-errors/1000; retry grep|timeout=3
Kept edits (seed 0, LLM + stat admission (M5b)): compress test-log grep-errors/2000
