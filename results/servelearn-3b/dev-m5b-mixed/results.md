seeds [0, 1, 2, 3, 4], 160-task evolution stream (test layout moves at task 80), eval: 40 fresh held-out-repo tasks + 30 OOD-repo tasks per seed

| config | stream success | held-out success | held-out tokens / task | OOD success | OOD tokens / task | KEEP / ROLLBACK | false KEEPs (rate) |
|---|---|---|---|---|---|---|---|
| RSI + LLM proposer (M5) | 68.4% | 89.5% | 11,319 | 81.3% | 10,423 | 6.0 / 4.0 | 5/30 (17%) |
| LLM + stat admission (M5b) | 16.2% | 30.5% | 12,286 | 22.0% | 10,039 | 1.0 / 1.2 | 0/5 (0%) |

| config | wall s / seed | LLM calls (cache hits) | candidates gated / KEEP by LLM / KEEP by script | malformed responses / mutations | prompt+completion tokens | cost USD (total) |
|---|---|---|---|---|---|---|
| RSI + LLM proposer (M5) | 75 | 2 (88) | 115 / 30 / 0 | 0 / 0 of 115 | 2,749+3,737 | 0.0006 |
| LLM + stat admission (M5b) | 119 | 26 (305) | 419 / 5 / 0 | 0 / 0 of 424 | 33,461+26,691 | 0.0033 |

Kept edits (seed 0, RSI loop): 
Kept edits (seed 0, RSI + LLM proposer (M5)): compress test-log grep-errors/2000; route edit->apply-patch; compress test-log grep-errors/1000; retry grep|timeout=3
Kept edits (seed 0, LLM + stat admission (M5b)): compress test-log grep-errors/2000

| config | FS run / base (regr / recov) | HD run / base | AULC10 run / base | AUC_E (repeat) | AUC_KA | accept rate | first-KEEP latency | replay execs / served | LLM tokens / USD |
|---|---|---|---|---|---|---|---|---|---|
| RSI + LLM proposer (M5) | 52.0 / 0.0% (0.0 / 41.6) | 84.8 / 0.0% | 81.5 / 0.0% | 1.07 (0.02) | 64.0% | 0.62 | 4.0 | 6.13 | 1297 / 0.0001 |
| LLM + stat admission (M5b) | 0.0 / 0.0% (0.0 / 0.0) | 32.5 / 0.0% | 29.8 / 0.0% | 0.43 (0.00) | 48.0% | 0.62 | 68.8 | 3.87 | 12030 / 0.0007 |
