### noise 0.3
seeds [0, 1, 2, 3, 4], 400 tasks per stream, shift at task 200

| mode | success (mean, min–max) | window 1 / 2 / 3 / 4 | held-out tasks | tokens / task | proposals | KEEP / ROLLBACK | blocked scope attempts |
|---|---|---|---|---|---|---|---|
| **Aura, gated** | 62.9% (57.8–69.2) | 51 / 77 / 56 / 68 | 64.6% | 8,193 | 20.4 | 12.0 / 8.4 | 1.0 |
| Aura, no gate | 52.6% (51.0–54.2) | 47 / 72 / 37 / 54 | 53.9% | 9,364 | 27.0 | 27.0 / 0.0 | 1.0 |

Failure modes (share of all tasks):

| mode | info-lost | tool-error | context-overflow | step-limit | stale-memory | handoff-loss | model-error |
|---|---|---|---|---|---|---|---|
| **Aura, gated** | 11.1% | 12.1% | 3.5% | 0.0% | 2.9% | 0.7% | 6.9% |
| Aura, no gate | 16.8% | 12.1% | 7.4% | 0.0% | 2.4% | 0.8% | 7.8% |

Tokens per task by window:

| mode | w1 | w2 | w3 | w4 |
|---|---|---|---|---|
| **Aura, gated** | 7,856 | 7,333 | 8,567 | 9,017 |
| Aura, no gate | 8,533 | 8,071 | 9,946 | 10,906 |

Gate / change latency (host-measured, p50 over all seeds' events) and stream wall time:

| mode | per change (apply or verdict) p50 | gate total p50 | trial call p50 | stream wall s (mean) |
|---|---|---|---|---|
| **Aura, gated** | 10.5 ms | 82 ms | 32 ms | 2.0 |
| Aura, no gate | 12.2 ms | 0 ms | 0 ms | 0.5 |

Kept mutations (count across seeds):

* **Aura, gated**: `ttl test-cmd=40` ×6, `route edit->apply-patch` ×5, `compress code-file head/1600` ×4, `compress test-log tail/800` ×4, `ttl repo-layout=160` ×4, `ttl db-schema=40` ×4, `compress service-log grep-errors/800` ×4, `delegate refactor>=6` ×3, `route search->lsp-find` ×3, `retry sql|rate-limit=3` ×2, `delegate refactor>=2` ×2, `compress service-log head/1600` ×1
* Aura, no gate: `compress service-log tail/1600` ×14, `compress service-log head-tail/1600` ×11, `ttl test-cmd=40` ×8, `route edit->apply-patch` ×8, `compress code-file head/1600` ×6, `ttl db-schema=40` ×6, `compress test-log head/1600` ×5, `compress test-log tail/1600` ×5, `compress service-log head/1600` ×5, `ttl repo-layout=40` ×5, `retry grep|timeout=3` ×5, `compress test-log tail/800` ×5
