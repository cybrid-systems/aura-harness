### noise 1.0
seeds [0, 1, 2, 3, 4], 400 tasks per stream, shift at task 200

| mode | success (mean, min–max) | window 1 / 2 / 3 / 4 | held-out tasks | tokens / task | proposals | KEEP / ROLLBACK | blocked scope attempts |
|---|---|---|---|---|---|---|---|
| **Aura, gated** | 37.8% (27.3–45.0) | 35 / 47 / 31 / 38 | 39.7% | 7,148 | 28.4 | 8.2 / 20.2 | 0.0 |
| Aura, no gate | 29.5% (29.5–29.8) | 32 / 39 / 23 / 25 | 31.1% | 7,753 | 38.6 | 38.6 / 0.0 | 0.0 |

Failure modes (share of all tasks):

| mode | info-lost | tool-error | context-overflow | step-limit | stale-memory | handoff-loss | model-error |
|---|---|---|---|---|---|---|---|
| **Aura, gated** | 26.9% | 24.9% | 3.4% | 0.0% | 2.1% | 0.0% | 4.8% |
| Aura, no gate | 31.3% | 25.7% | 6.0% | 0.0% | 1.7% | 0.0% | 5.8% |

Tokens per task by window:

| mode | w1 | w2 | w3 | w4 |
|---|---|---|---|---|
| **Aura, gated** | 7,627 | 6,762 | 7,064 | 7,139 |
| Aura, no gate | 7,535 | 7,065 | 7,956 | 8,455 |

Gate / change latency (host-measured, p50 over all seeds' events) and stream wall time:

| mode | per change (apply or verdict) p50 | gate total p50 | trial call p50 | stream wall s (mean) |
|---|---|---|---|---|
| **Aura, gated** | 4.9 ms | 199 ms | 141 ms | 6.9 |
| Aura, no gate | 68.4 ms | 0 ms | 0 ms | 2.8 |

Kept mutations (count across seeds):

* **Aura, gated**: `ttl test-cmd=40` ×5, `ttl db-schema=40` ×5, `compress code-file head/1600` ×4, `route edit->apply-patch` ×3, `compress test-log tail/800` ×3, `ttl repo-layout=40` ×2, `ttl repo-layout=160` ×2, `compress service-log grep-errors/800` ×2, `compress service-log head/1600` ×1, `compress service-log grep-errors/1600` ×1, `compress search-results summarize/800` ×1, `ttl repo-layout=80` ×1
* Aura, no gate: `ttl test-cmd=40` ×13, `ttl test-cmd=10` ×12, `ttl db-schema=40` ×11, `ttl db-schema=10` ×11, `ttl repo-layout=40` ×9, `ttl db-schema=20` ×9, `ttl repo-layout=10` ×8, `ttl test-cmd=20` ×7, `compress search-results head/1600` ×5, `compress service-log head/1600` ×5, `compress config head/1600` ×5, `compress patch-result head/1600` ×5
