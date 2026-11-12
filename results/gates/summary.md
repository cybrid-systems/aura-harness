# Dual gate and structured proposer

Aura binary: `aura 0.2.1 (f8e4d307b8603b3cb517221862cdaa39c61e5030)` (`f8e4d307b8603b3cb517221862cdaa39c61e5030`).
Stream: 5 seeds × 400 tasks, shift at 200, `supervise=False`, worldlines `ws`.
Held-out is the stream's fixed hash split. No LLM. Not a claim about the historical noise 0/0.3/1.0 sweep beyond the clean `better()` row.

| config | success | held-out | tokens/task | KEEP | ROLLBACK | harm KEEP | known harm KEEP | joint KEEP | relevance | protected proposals |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `r0-better-harm` | 62.20% | 62.60% | 8510 | 14.8 | 9.2 | 10 | 9 | 0 | 98.4% | 5 |
| `r0-better-clean` | 63.35% | 64.00% | 8377 | 12.0 | 7.8 | 0 | 0 | 0 | 98.1% | 5 |
| `r1-dual-harm` | 63.35% | 64.00% | 8377 | 12.0 | 7.8 | 0 | 0 | 0 | 98.1% | 5 |
| `r1-dual-clean` | 63.35% | 64.00% | 8377 | 12.0 | 7.8 | 0 | 0 | 0 | 98.1% | 5 |
| `r1-structured-better` | 64.70% | 65.40% | 8917 | 12.8 | 7.4 | 0 | 0 | 13 | 100.0% | 0 |
| `r1-structured-dual` | 64.70% | 65.40% | 8917 | 12.8 | 7.4 | 0 | 0 | 13 | 100.0% | 0 |
| `r2-dual-thin-clean` | 63.25% | 63.80% | 8329 | 11.4 | 8.2 | 0 | 0 | 0 | 98.1% | 5 |
| `r2-dual-thin-harm` | 63.25% | 63.80% | 8329 | 11.4 | 8.2 | 0 | 0 | 0 | 98.1% | 5 |
| `r2-structured-dual-harm` | 64.70% | 65.40% | 8917 | 12.8 | 7.4 | 0 | 0 | 13 | 100.0% | 0 |
| `r3-structured-errline` | 62.45% | 62.80% | 8251 | 12.4 | 8.2 | 0 | 0 | 8 | 100.0% | 0 |
| `r3-structured-errline-harm` | 62.45% | 62.80% | 8251 | 12.4 | 8.2 | 0 | 0 | 8 | 100.0% | 0 |

Per seed harm KEEP counts (all injected labels, then the original ttl/compress pair):

- `r0-better-harm`: s0=0 (known 0), s1=2 (known 2), s2=1 (known 1), s3=5 (known 4), s4=2 (known 2)
- `r1-dual-harm`: s0=0 (known 0), s1=0 (known 0), s2=0 (known 0), s3=0 (known 0), s4=0 (known 0)
- `r2-dual-thin-harm`: s0=0 (known 0), s1=0 (known 0), s2=0 (known 0), s3=0 (known 0), s4=0 (known 0)
- `r2-structured-dual-harm`: s0=0 (known 0), s1=0 (known 0), s2=0 (known 0), s3=0 (known 0), s4=0 (known 0)
- `r3-structured-errline-harm`: s0=0 (known 0), s1=0 (known 0), s2=0 (known 0), s3=0 (known 0), s4=0 (known 0)

Kept edits that are taxonomy joints (`joint-strategy-limit`), by seed:

- `r1-structured-better`: s0: ['compress code-file head-tail/1600', 'compress service-log grep-errors/1600']; s1: ['compress code-file summarize/1600', 'compress service-log grep-errors/1600']; s2: ['compress test-log tail/1600', 'compress code-file head-tail/1600', 'compress service-log grep-errors/1600']; s3: ['compress test-log grep-errors/1600', 'compress code-file head-tail/1600', 'compress service-log grep-errors/1600']; s4: ['compress test-log tail/1600', 'compress code-file summarize/1600', 'compress service-log grep-errors/1600']
- `r1-structured-dual`: s0: ['compress code-file head-tail/1600', 'compress service-log grep-errors/1600']; s1: ['compress code-file summarize/1600', 'compress service-log grep-errors/1600']; s2: ['compress test-log tail/1600', 'compress code-file head-tail/1600', 'compress service-log grep-errors/1600']; s3: ['compress test-log grep-errors/1600', 'compress code-file head-tail/1600', 'compress service-log grep-errors/1600']; s4: ['compress test-log tail/1600', 'compress code-file summarize/1600', 'compress service-log grep-errors/1600']
- `r2-structured-dual-harm`: s0: ['compress code-file head-tail/1600', 'compress service-log grep-errors/1600']; s1: ['compress code-file summarize/1600', 'compress service-log grep-errors/1600']; s2: ['compress test-log tail/1600', 'compress code-file head-tail/1600', 'compress service-log grep-errors/1600']; s3: ['compress test-log grep-errors/1600', 'compress code-file head-tail/1600', 'compress service-log grep-errors/1600']; s4: ['compress test-log tail/1600', 'compress code-file summarize/1600', 'compress service-log grep-errors/1600']
- `r3-structured-errline`: s0: ['compress service-log grep-errors/1600']; s1: ['compress service-log grep-errors/1600']; s2: ['compress test-log tail/1600', 'compress service-log grep-errors/1600']; s3: ['compress test-log grep-errors/1600', 'compress service-log grep-errors/1600']; s4: ['compress test-log tail/1600', 'compress service-log grep-errors/1600']
- `r3-structured-errline-harm`: s0: ['compress service-log grep-errors/1600']; s1: ['compress service-log grep-errors/1600']; s2: ['compress test-log tail/1600', 'compress service-log grep-errors/1600']; s3: ['compress test-log grep-errors/1600', 'compress service-log grep-errors/1600']; s4: ['compress test-log tail/1600', 'compress service-log grep-errors/1600']

## Rounds

Round 0 reproduced the hole. `better()` on the injected suite KEPT 9 times `HARM ttl all 0` and once `HARM retry all 0`, on 4 of 5 seeds. `HARM compress all head/50` did not win a window in this rerun. The 2026-10-30 note recorded 8 ttl KEEPs on an older Aura pin; this rerun also injects the retry wipe, so the count is not claimed to be identical. Clean `better()` matches the README bench exactly: 63.35%, held-out 64.00%, 8377 tokens/task, 12.0 KEEP / 7.8 ROLLBACK.

Round 1 is the dual gate (structure + solution, `dual_thin` off) and the structured proposer with joints on every output kind. Dual gate harm KEEP is 0, and the clean closed-grammar row is unchanged (same successes, same KEEPs). Every injected harm in that run was rejected on the structure side (`clears memory the evidence does not name`, `compress policy is under the floor for every kind`, `clears retries the evidence does not name`, or a no-op). The solution gate is the backstop: a window `better()` would KEEP is still rejected for those shapes (`tests/test_gates.py`). Structured search, same seeds, raises mean success to 64.70% and held-out to 65.40%, at 8917 tokens/task. It KEEPs 13 joint edits the flat grammar never emits (for example `compress service-log grep-errors/1600`). Relevance of emitted candidates goes from 98.1% to 100%, and the protected budget raise is not proposed (0 vs 5). Seed 2 is the regression: 68.0% → 65.5%.

Round 2 turned on `dual_thin` (reject a destructive edit whose held-out gain is ≤4 tasks and whose cost rises more than 5%). Harm KEEP stays 0. Clean success falls to 63.25% and held-out to 63.80%, with 11.4 KEEPs instead of 12.0. The extra rule does not buy safety on this suite, so it stays off.

Round 3 restricted strategy×limit joints to error-line kinds (`test-log`, `service-log`), on the hypothesis that code-file joints caused the seed 2 drop. Held-out fell to 62.80%, below the closed grammar, and seed 2 did not recover. That restriction is not the default. `joint_kinds="errline"` still reproduces it.

Not run: noise 0.3 / 1.0, the statistical-admission sweep, `supervise=True`, and the MOEA/D `evo_server` genome search. Trials and verdicts in this matrix go through `aura/server.aura` worldlines (`mutate` snapshot / restore, `VERDICT` KEEP / ROLLBACK, audit `LOG`). The repo pin was not changed.
