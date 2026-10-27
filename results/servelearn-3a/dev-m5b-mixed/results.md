seeds [0, 1, 2, 3, 4], 160-task evolution stream (test layout moves at task 80), eval: 40 fresh held-out-repo tasks + 30 OOD-repo tasks per seed

| config | stream success | held-out success | held-out tokens / task | OOD success | OOD tokens / task | KEEP / ROLLBACK | false KEEPs (rate) |
|---|---|---|---|---|---|---|---|
| RSI + LLM proposer (M5) | 68.4% | 89.5% | 11,319 | 81.3% | 10,423 | 6.0 / 4.0 | 5/30 (17%) |
| LLM + stat admission (M5b) | 17.6% | 30.5% | 12,286 | 22.0% | 10,039 | 1.0 / 0.4 | 0/5 (0%) |

| config | wall s / seed | LLM calls (cache hits) | candidates gated / KEEP by LLM / KEEP by script | malformed responses / mutations | prompt+completion tokens | cost USD (total) |
|---|---|---|---|---|---|---|
| RSI + LLM proposer (M5) | 130 | 15 (76) | 115 / 30 / 0 | 0 / 0 of 115 | 20,463+35,921 | 0.0038 |
| LLM + stat admission (M5b) | 345 | 106 (238) | 436 / 5 / 0 | 0 / 0 of 441 | 135,303+92,475 | 0.0121 |

Kept edits (seed 0, RSI loop): 
Kept edits (seed 0, RSI + LLM proposer (M5)): compress test-log grep-errors/2000; route edit->apply-patch; compress test-log grep-errors/1000; retry grep|timeout=3
Kept edits (seed 0, LLM + stat admission (M5b)): compress test-log grep-errors/2000

| config | FS run / base (regr / recov) | HD run / base | AULC10 run / base | AUC_E (repeat) | AUC_KA | accept rate | first-KEEP latency | replay execs / served | LLM tokens / USD |
|---|---|---|---|---|---|---|---|---|---|
| RSI + LLM proposer (M5) | 52.0 / 0.0% (0.0 / 41.6) | 84.8 / 0.0% | 81.5 / 0.0% | 1.06 (0.02) | 64.0% | 0.62 | 4.0 | 6.08 | 11277 / 0.0008 |
| LLM + stat admission (M5b) | 0.0 / 0.0% (0.0 / 0.0) | 35.2 / 0.0% | 33.8 / 0.0% | 0.10 (0.00) | 44.0% | 0.80 | 62.0 | 2.50 | 45556 / 0.0024 |
