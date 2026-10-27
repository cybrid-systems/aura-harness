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
| RSI loop (M1) | 67 | - | - | - | - | - |
| scripted + stat admission (M5b) | 40 | - | - | - | - | - |
| RSI + LLM proposer (M5) | 62 | 0 (85) | 124 / 24 / 0 | 0 / 0 of 124 | 0+0 | 0.0000 |
| LLM + stat admission (M5b) | 22 | 0 (52) | 69 / 5 / 0 | 0 / 0 of 69 | 0+0 | 0.0000 |

Kept edits (seed 0, RSI loop): compress test-log grep-errors/800; route edit->apply-patch; retry grep|timeout=3
Kept edits (seed 0, RSI + LLM proposer (M5)): compress test-log grep-errors/2000; route edit->apply-patch; compress test-log grep-errors/1000; retry grep|timeout=3
Kept edits (seed 0, LLM + stat admission (M5b)): compress test-log grep-errors/2000

| config | FS run / base (regr / recov) | HD run / base | AULC10 run / base | AUC_E (repeat) | AUC_KA | accept rate | first-KEEP latency | replay execs / served | LLM tokens / USD |
|---|---|---|---|---|---|---|---|---|---|
| RSI loop (M1) | 61.7 / 0.0% (0.0 / 49.4) | 91.2 / 0.0% | 88.4 / 0.0% | 1.89 (0.36) | 68.0% | 0.53 | 0.7 | 6.13 | - / - |
| scripted + stat admission (M5b) | 0.0 / 0.0% (0.0 / 0.0) | 53.0 / 0.0% | 50.4 / 0.0% | 2.70 (0.00) | 56.0% | 0.73 | 62.2 | 3.64 | - / - |
| RSI + LLM proposer (M5) | 51.5 / 0.0% (0.0 / 41.2) | 85.2 / 0.0% | 80.0 / 0.0% | 1.43 (0.02) | 64.0% | 0.56 | 3.0 | 5.90 | 0 / 0.0000 |
| LLM + stat admission (M5b) | 0.0 / 0.0% (0.0 / 0.0) | 35.2 / 0.0% | 33.8 / 0.0% | 0.10 (0.00) | 44.0% | 0.80 | 62.0 | 2.40 | 0 / 0.0000 |
