### snapshot worldlines
seeds [0, 1, 2, 3, 4], 400 tasks per stream, shift at task 200

| mode | success (mean, min–max) | window 1 / 2 / 3 / 4 | held-out tasks | tokens / task | proposals | KEEP / ROLLBACK | blocked scope attempts |
|---|---|---|---|---|---|---|---|
| **Aura, gated** | 63.4% (59.0–68.2) | 53 / 76 / 56 / 68 | 64.0% | 8,377 | 19.8 | 12.0 / 7.8 | 1.0 |

Failure modes (share of all tasks):

| mode | info-lost | tool-error | context-overflow | step-limit | stale-memory | handoff-loss | model-error |
|---|---|---|---|---|---|---|---|
| **Aura, gated** | 11.6% | 11.4% | 3.7% | 0.0% | 2.8% | 0.6% | 6.6% |

Tokens per task by window:

| mode | w1 | w2 | w3 | w4 |
|---|---|---|---|---|
| **Aura, gated** | 7,809 | 6,941 | 8,943 | 9,815 |

Gate / change latency (host-measured, p50 over all seeds' events) and stream wall time:

| mode | per change (apply or verdict) p50 | gate total p50 | trial call p50 | stream wall s (mean) |
|---|---|---|---|---|
| **Aura, gated** | 7.4 ms | 61 ms | 23 ms | 1.5 |

Kept mutations (count across seeds):

* **Aura, gated**: `ttl test-cmd=40` ×5, `compress service-log grep-errors/800` ×5, `route edit->apply-patch` ×5, `ttl repo-layout=40` ×5, `compress test-log tail/800` ×4, `retry sql|rate-limit=3` ×4, `ttl db-schema=40` ×4, `compress code-file head/1600` ×3, `delegate refactor>=2` ×3, `retry grep|timeout=3` ×3, `delegate refactor>=6` ×2, `compress code-file summarize/800` ×2
