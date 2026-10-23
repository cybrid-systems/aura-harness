dev world v2, seeds [0, 1, 2, 3, 4], 160-task stream; eval on 40 fresh held-out-repo + 30 OOD-repo tasks per seed. tokens = simulated context + reasoning tokens per task; latency = simulated model seconds per task; cost-of-pass = tokens / success.

| config | tier | held-out success | held-out tokens | held-out latency s | held-out cost-of-pass | OOD success | OOD tokens | wrong-fix rate (HO) | wall s / seed | LLM USD (total) |
|---|---|---|---|---|---|---|---|---|---|---|
| M5 scripted (RSI M1) | - | 76.5% | 16,696 | 12.6 | 21,900 | 68.0% | 15,832 | 14.0% | 179 | - |
| M5 LLM proposer | - | 0.0% | 2,951 | 3.4 | 118,033 | 0.0% | 2,950 | 0.0% | 53 | 0.0087 |
| M6 full | lite | 76.5% | 16,370 | 11.9 | 21,505 | 66.0% | 15,433 | 14.0% | 163 | 0.0313 |
| M6 full | medium | 80.0% | 16,914 | 13.2 | 21,215 | 70.7% | 15,985 | 12.0% | 163 | 0.0313 |
| M6 full | heavy | 84.0% | 18,646 | 17.5 | 22,423 | 74.7% | 17,388 | 8.0% | 163 | 0.0313 |
| M6 router only | lite | 72.5% | 15,964 | 11.8 | 22,259 | 68.0% | 15,937 | 13.5% | 98 | 0.0185 |
| M6 router only | medium | 79.0% | 17,782 | 14.3 | 22,590 | 72.0% | 16,397 | 10.5% | 98 | 0.0185 |
| M6 router only | heavy | 81.0% | 20,079 | 17.8 | 24,742 | 72.7% | 18,619 | 9.5% | 98 | 0.0185 |
| M6 hook only | lite | 76.5% | 15,864 | 12.1 | 20,837 | 68.0% | 15,058 | 14.0% | 56 | 0.0071 |
| M6 hook only | medium | 76.5% | 15,864 | 12.1 | 20,837 | 68.0% | 15,058 | 14.0% | 56 | 0.0071 |
| M6 hook only | heavy | 76.5% | 15,864 | 12.1 | 20,837 | 68.0% | 15,058 | 14.0% | 56 | 0.0071 |
| M6 full, scripted planner | lite | 77.5% | 16,141 | 11.4 | 20,940 | 69.3% | 15,542 | 13.0% | 65 | - |
| M6 full, scripted planner | medium | 80.5% | 16,913 | 13.0 | 20,992 | 68.7% | 15,821 | 10.0% | 65 | - |
| M6 full, scripted planner | heavy | 85.5% | 18,940 | 17.1 | 22,269 | 73.3% | 17,435 | 5.0% | 65 | - |
| M6 full, label-free (synth tests) | lite | 79.0% | 16,584 | 13.2 | 21,177 | 68.7% | 15,494 | 11.0% | 201 | 0.0525 |
| M6 full, label-free (synth tests) | medium | 76.0% | 16,469 | 13.3 | 21,776 | 70.0% | 15,823 | 11.0% | 201 | 0.0525 |
| M6 full, label-free (synth tests) | heavy | 79.0% | 17,613 | 16.1 | 22,413 | 74.7% | 17,170 | 8.0% | 201 | 0.0525 |

| config | tier admitted (lite/medium/heavy, of seeds) | pool candidates evaluated | guard-blocked plans | plans LLM / scripted | malformed mutations | LLM calls (cache hits) |
|---|---|---|---|---|---|---|
| M6 full | 2/3/4 | 64 | 0 | 63 / 45 | 0 of 295 | 28 (8) |
| M6 router only | 1/2/3 | 46 | 0 | 72 / 18 | 0 of 283 | 18 (12) |
| M6 hook only | 2/2/2 | 21 | 0 | 48 / 12 | 0 of 196 | 7 (13) |
| M6 full, scripted planner | 5/5/5 | 34 | 0 | 0 / 126 | 0 of 142 | - |
| M6 full, label-free (synth tests) | 3/3/4 | 63 | 0 | 69 / 45 | 0 of 327 | 99 (205) |

Tiers (M6 full, seed 0): lite=e2c0 [tier bugfix[1-1]->lean; hook standard 5/9/20]; medium=e2c0 [tier bugfix[1-1]->lean; hook standard 5/9/20]; heavy=e2c2 [hook standard 8/12/20]
Tiers (M6 router only, seed 0): lite=h0 [h0]; medium=e0c2 [tier bugfix[3-7]->deep; retry pytest|timeout=3; delegate refactor>=2]; heavy=e1c2 [tier bugfix[1-2]->deep; retry grep|timeout=3; compress test-log head-tail/800]
Tiers (M6 hook only, seed 0): lite=h0 [h0]; medium=h0 [h0]; heavy=h0 [h0]
Tiers (M6 full, scripted planner, seed 0): lite=e0c0 [tier bugfix[1-1]->lean; hook standard 5/9/20]; medium=e0c0 [tier bugfix[1-1]->lean; hook standard 5/9/20]; heavy=e1c0 [tier refactor[3-7]->deep]
Tiers (M6 full, label-free (synth tests), seed 0): lite=e3c6 [tier refactor[3-7]->deep]; medium=e3c4 [compress test-log fold/500; tier bugfix[1-2]->lean; ttl repo-layout=150; retry pytest|timeout=2]; heavy=e3c4 [compress test-log fold/500; tier bugfix[1-2]->lean; ttl repo-layout=150; retry pytest|timeout=2]

Label-free failure recall on 341 distinct claimed-success episodes (157 are wrong fixes by the hidden grader):

| signal | failure recall | false alarms on correct fixes | no signal |
|---|---|---|---|
| synthesized tests (10/function, fixed) | 83.4% (131/157) | 3.3% | 0 |
| LLM judge | 100.0% (157/157) | 0.0% | 0 |
