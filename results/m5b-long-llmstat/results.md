seeds [0, 1, 2], 480-task evolution stream (test layout moves at task 240), eval: 40 fresh held-out-repo tasks + 30 OOD-repo tasks per seed

| config | stream success | held-out success | held-out tokens / task | OOD success | OOD tokens / task | KEEP / ROLLBACK | false KEEPs (rate) |
|---|---|---|---|---|---|---|---|
| LLM + stat admission (M5b) | 48.6% | 80.0% | 15,142 | 73.3% | 13,041 | 3.0 / 2.3 | 1/9 (11%) |

| config | wall s / seed | LLM calls (cache hits) | candidates gated / KEEP by LLM / KEEP by script | malformed responses / mutations | prompt+completion tokens | cost USD (total) |
|---|---|---|---|---|---|---|
| LLM + stat admission (M5b) | 180 | 17 (27) | 62 / 9 / 0 | 1 / 0 of 62 | 22,021+9,133 | 0.0063 |

Kept edits (seed 0, RSI loop): 
Kept edits (seed 0, LLM + stat admission (M5b)): compress test-log grep-errors/2000; route edit->apply-patch; compress test-log head-tail/1000
