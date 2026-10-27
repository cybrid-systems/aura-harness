seeds [0, 1, 2, 3, 4], 160-task evolution stream (test layout moves at task 80), eval: 40 fresh held-out-repo tasks + 30 OOD-repo tasks per seed

| config | stream success | held-out success | held-out tokens / task | OOD success | OOD tokens / task | KEEP / ROLLBACK | false KEEPs (rate) |
|---|---|---|---|---|---|---|---|
| RSI + LLM proposer (M5) | 69.2% | 91.0% | 13,030 | 74.0% | 10,970 | 5.4 / 4.2 | 9/27 (33%) |
| LLM + stat admission (M5b) | 20.4% | 38.0% | 10,562 | 31.3% | 9,074 | 1.0 / 1.0 | 0/5 (0%) |

| config | wall s / seed | LLM calls (cache hits) | candidates gated / KEEP by LLM / KEEP by script | malformed responses / mutations | prompt+completion tokens | cost USD (total) |
|---|---|---|---|---|---|---|
| RSI + LLM proposer (M5) | 57 | 0 (88) | 92 / 27 / 0 | 0 / 0 of 92 | 0+0 | 0.0000 |
| LLM + stat admission (M5b) | 400 | 50 (291) | 359 / 5 / 0 | 0 / 0 of 359 | 64,837+81,429 | 0.0000 |

Kept edits (seed 0, RSI loop): 
Kept edits (seed 0, RSI + LLM proposer (M5)): compress test-log grep-errors/1000; route edit->apply-patch; ttl test-cmd=10; ttl test-cmd=0; ttl test-cmd=10; ttl test-cmd=0
Kept edits (seed 0, LLM + stat admission (M5b)): compress test-log grep-errors/1000

| config | FS run / base (regr / recov) | HD run / base | AULC10 run / base | AUC_E (repeat) | AUC_KA | accept rate | first-KEEP latency | replay execs / served | LLM tokens / USD |
|---|---|---|---|---|---|---|---|---|---|
| RSI + LLM proposer (M5) | 55.5 / 0.0% (0.0 / 44.4) | 83.0 / 0.0% | 78.7 / 0.0% | 0.59 (0.11) | 64.0% | 0.59 | 1.8 | 5.06 | 0 / 0.0000 |
| LLM + stat admission (M5b) | 0.0 / 0.0% (0.0 / 0.0) | 40.8 / 0.0% | 38.4 / 0.0% | 0.16 (0.00) | 48.0% | 0.65 | 68.8 | 3.24 | 29253 / 0.0000 |
