seeds [0, 1, 2, 3, 4], 160-task evolution stream (test layout moves at task 80), eval: 40 fresh held-out-repo tasks + 30 OOD-repo tasks per seed

| config | stream success | held-out success | held-out tokens / task | OOD success | OOD tokens / task | KEEP / ROLLBACK | false KEEPs (rate) |
|---|---|---|---|---|---|---|---|
| RSI + LLM proposer (M5) | 64.0% | 87.0% | 12,177 | 80.0% | 10,472 | 6.2 / 3.2 | 4/31 (13%) |
| LLM + stat admission (M5b) | 17.6% | 30.5% | 12,286 | 22.0% | 10,039 | 1.0 / 0.4 | 0/5 (0%) |

| config | wall s / seed | LLM calls (cache hits) | candidates gated / KEEP by LLM / KEEP by script | malformed responses / mutations | prompt+completion tokens | cost USD (total) |
|---|---|---|---|---|---|---|
| RSI + LLM proposer (M5) | 211 | 40 (48) | 113 / 31 / 0 | 0 / 0 of 113 | 53,490+48,341 | 0.0085 |
| LLM + stat admission (M5b) | 55 | 6 (46) | 63 / 5 / 0 | 0 / 0 of 63 | 7,792+8,952 | 0.0002 |

Kept edits (seed 0, RSI loop): 
Kept edits (seed 0, RSI + LLM proposer (M5)): compress test-log grep-errors/2000; route edit->apply-patch; route test->pytest-q; retry grep|timeout=2; delegate refactor>=3
Kept edits (seed 0, LLM + stat admission (M5b)): compress test-log grep-errors/2000

| config | FS run / base (regr / recov) | HD run / base | AULC10 run / base | AUC_E (repeat) | AUC_KA | accept rate | first-KEEP latency | replay execs / served | LLM tokens / USD |
|---|---|---|---|---|---|---|---|---|---|
| RSI + LLM proposer (M5) | 51.0 / 0.0% (0.0 / 40.8) | 77.0 / 0.0% | 73.7 / 0.0% | 1.15 (0.02) | 64.0% | 0.67 | 4.6 | 5.83 | 20366 / 0.0017 |
| LLM + stat admission (M5b) | 0.0 / 0.0% (0.0 / 0.0) | 35.2 / 0.0% | 33.8 / 0.0% | 0.10 (0.00) | 44.0% | 0.80 | 62.0 | 2.45 | 3349 / 0.0000 |
