seeds [0, 1, 2], 480-task evolution stream (test layout moves at task 240), eval: 40 fresh held-out-repo tasks + 30 OOD-repo tasks per seed

| config | stream success | held-out success | held-out tokens / task | OOD success | OOD tokens / task | KEEP / ROLLBACK | false KEEPs (rate) |
|---|---|---|---|---|---|---|---|
| frozen seed harness | 0.0% | 0.0% | 1,670 | 0.0% | 1,715 | 0.0 / 0.0 | 0/0 (0%) |
| RSI loop (M1) | 89.4% | 100.0% | 13,665 | 78.9% | 11,798 | 6.3 / 6.0 | 6/19 (32%) |
| scripted + stat admission (M5b) | 69.6% | 93.3% | 13,765 | 78.9% | 11,678 | 2.0 / 4.3 | 0/6 (0%) |
| RSI + LLM proposer (M5) | 84.9% | 94.2% | 11,856 | 85.6% | 10,670 | 6.0 / 7.3 | 1/18 (6%) |
| LLM + stat admission (M5b) | 43.5% | 67.5% | 13,921 | 55.6% | 12,709 | 2.7 / 3.3 | 1/8 (12%) |

| config | wall s / seed | LLM calls (cache hits) | candidates gated / KEEP by LLM / KEEP by script | malformed responses / mutations | prompt+completion tokens | cost USD (total) |
|---|---|---|---|---|---|---|
| frozen seed harness | 0 | - | - | - | - | - |
| RSI loop (M1) | 159 | - | - | - | - | - |
| scripted + stat admission (M5b) | 155 | - | - | - | - | - |
| RSI + LLM proposer (M5) | 296 | 0 (66) | 94 / 18 / 0 | 2 / 0 of 94 | 0+0 | 0.0000 |
| LLM + stat admission (M5b) | 580 | 38 (492) | 845 / 8 / 0 | 2 / 0 of 847 | 48,681+14,901 | 0.0106 |

Kept edits (seed 0, RSI loop): compress test-log grep-errors/800; route edit->apply-patch; retry grep|timeout=3; ttl test-cmd=40; ttl test-cmd=0; ttl test-cmd=160
Kept edits (seed 0, RSI + LLM proposer (M5)): compress test-log grep-errors/2000; route edit->apply-patch; compress test-log grep-errors/1000; retry grep|timeout=3; ttl test-cmd=20
Kept edits (seed 0, LLM + stat admission (M5b)): compress test-log grep-errors/2000; route edit->apply-patch; compress test-log grep-errors/1200
