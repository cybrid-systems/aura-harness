### clean diagnoses
seeds [0, 1, 2, 3, 4], 400 tasks per stream, shift at task 200

| mode | success (mean, min–max) | window 1 / 2 / 3 / 4 | held-out tasks | tokens / task | proposals | KEEP / ROLLBACK | blocked scope attempts |
|---|---|---|---|---|---|---|---|
| frozen harness | 24.1% (22.5–25.2) | 30 / 34 / 16 / 18 | 26.2% | 7,924 | 0.0 | 0.0 / 0.0 | 0.0 |
| file-edit + reload (gated) | 63.4% (59.0–68.2) | 53 / 76 / 56 / 68 | 64.0% | 8,377 | 19.8 | 12.0 / 7.8 | 1.0 |
| **Aura, gated** | 63.4% (59.0–68.2) | 53 / 76 / 56 / 68 | 64.0% | 8,377 | 19.8 | 12.0 / 7.8 | 1.0 |
| Aura, no gate | 55.5% (52.0–58.8) | 51 / 74 / 40 / 56 | 57.1% | 9,176 | 27.4 | 27.4 / 0.0 | 1.0 |

Failure modes (share of all tasks):

| mode | info-lost | tool-error | context-overflow | step-limit | stale-memory | handoff-loss | model-error |
|---|---|---|---|---|---|---|---|
| frozen harness | 41.4% | 26.4% | 2.5% | 0.0% | 0.0% | 0.0% | 5.7% |
| file-edit + reload (gated) | 11.6% | 11.4% | 3.7% | 0.0% | 2.8% | 0.6% | 6.6% |
| **Aura, gated** | 11.6% | 11.4% | 3.7% | 0.0% | 2.8% | 0.6% | 6.6% |
| Aura, no gate | 16.2% | 10.9% | 6.3% | 0.0% | 2.5% | 0.8% | 7.8% |

Tokens per task by window:

| mode | w1 | w2 | w3 | w4 |
|---|---|---|---|---|
| frozen harness | 8,274 | 8,064 | 7,908 | 7,449 |
| file-edit + reload (gated) | 7,809 | 6,941 | 8,943 | 9,815 |
| **Aura, gated** | 7,809 | 6,941 | 8,943 | 9,815 |
| Aura, no gate | 8,884 | 7,828 | 9,177 | 10,815 |

Gate / change latency (host-measured, p50 over all seeds' events) and stream wall time:

| mode | per change (apply or verdict) p50 | gate total p50 | trial call p50 | stream wall s (mean) |
|---|---|---|---|---|
| frozen harness | – | – | – | 0.1 |
| file-edit + reload (gated) | 23.7 ms | 134 ms | 71 ms | 2.9 |
| **Aura, gated** | 7.2 ms | 64 ms | 22 ms | 1.4 |
| Aura, no gate | 8.2 ms | 0 ms | 0 ms | 0.4 |

Kept mutations (count across seeds):

* file-edit + reload (gated): `ttl test-cmd=40` ×5, `compress service-log grep-errors/800` ×5, `route edit->apply-patch` ×5, `ttl repo-layout=40` ×5, `compress test-log tail/800` ×4, `retry sql|rate-limit=3` ×4, `ttl db-schema=40` ×4, `compress code-file head/1600` ×3, `delegate refactor>=2` ×3, `retry grep|timeout=3` ×3, `delegate refactor>=6` ×2, `compress code-file summarize/800` ×2
* **Aura, gated**: `ttl test-cmd=40` ×5, `compress service-log grep-errors/800` ×5, `route edit->apply-patch` ×5, `ttl repo-layout=40` ×5, `compress test-log tail/800` ×4, `retry sql|rate-limit=3` ×4, `ttl db-schema=40` ×4, `compress code-file head/1600` ×3, `delegate refactor>=2` ×3, `retry grep|timeout=3` ×3, `delegate refactor>=6` ×2, `compress code-file summarize/800` ×2
* Aura, no gate: `compress service-log tail/1600` ×19, `compress service-log head-tail/1600` ×16, `route edit->apply-patch` ×11, `ttl test-cmd=40` ×8, `ttl db-schema=40` ×6, `route edit->sed` ×6, `compress code-file head/1600` ×5, `compress test-log head/1600` ×5, `compress test-log tail/1600` ×5, `compress service-log head/1600` ×5, `compress test-log tail/800` ×5, `ttl repo-layout=40` ×5
