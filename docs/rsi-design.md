# RSI design for aura-harness

Status: design for milestones M1–M4 (2026-10-23). Aura pin: `a6c63aa19`, with a crash-restart supervisor for aura#4670.

aura-harness already runs a closed self-evolution loop: solver → proposer → scope guard → worldline trial → held-out gate → KEEP/ROLLBACK, all audited. This document maps eight recent harness-RSI papers onto that loop, says what each changes here, and fixes the scope of the next four milestones. Every claim below about a paper comes from its arXiv abstract. Where a design choice goes further than the abstract, it is marked *ours*.

## 1. What the papers say, and what we take

| paper | core idea (from the abstract) | what we adopt | milestone |
|---|---|---|---|
| **2610.18813** Self-Evolving Agent Harness (survey/theory) | Accepted revisions persist across runs. *Update targets* are separated from *proposal* and *admission*. Interpreted state, tools/code, repository-level control logic and plugin composition are different targets. Continual-PAC analysis gives a retention bound conditional on historical regression budgets, and a high-probability admission rule on fresh, independent validation data. Runtime privileges need independent safeguards. | Three explicit layers: `Target` (what may change), `ProposalSource` (who proposes), `Admission` (who decides). A **retention gate** with a cumulative regression budget, and a **fresh-validation** admission stage. The guard stays outside the evolvable code. | M1 (split, retention), M2 (fresh validation) |
| **2609.32423** PluginRSI | The harness is a composition of atomised plugins. Plugins improve independently, accumulate in a shared library, and are recombined each iteration. The library speeds up later optimisation and transfers. | The five mutable defines become **plugins** with their own scope, compiler and validator. Every admitted variant goes into a **plugin library** with provenance. Recombination is a `composition` target. | M1 (plugins, library), M2 (recombination) |
| **2609.14857** ModularRSI | Contrast success and failure on the *same task* and aggregate across tasks to find recurring deficiencies. Five modules, each evolving in a restricted scope, then an integration stage. Evolution tasks are disjoint from evaluation tasks. | Per-plugin restricted scope, which is the existing one-component rule made explicit. Evidence = recurring signature across tasks (we already require `min_evidence`). M3 adds paired success/failure contrast on real trajectories. Evolution and evaluation streams stay disjoint (the held-out split). | M1, M3 |
| **2609.24972** RRSI | Regularise proposal and selection: a temporally annealed **edit budget** per candidate, novelty from evolution history, a **critic** that screens benchmark-specific proposals, and a **pruner** that removes changes that are too small, too expensive or no longer useful. | Proposal budget (edits per candidate and candidates per step, annealed). Critic = a rule that rejects edits keyed on a single task id/project or justified by one window only. Pruner = periodic ablation of each kept plugin edit; drop it if it is no longer useful. | M2 |
| **2610.15150** Harmony Harness | Multi-objective evolution: keep solutions across a **Pareto frontier** and avoid a hand-made diversity metric. Factorise general mechanisms vs environment-specific adaptations, then compose them dynamically. | A **Pareto archive** over (held-out success, tokens/task, retention). The live harness is one archive member, chosen by a declared preference. General vs phase-specific plugin variants are tagged in the library. | M2 |
| **2610.19424** VideoHarness-SRSI | Validation overfitting, search-budget dilution and the early-experience trap share one root: the same noisy validation evidence drives both revisions and search strategy. Fix: content-free feedback to the proposer, instrumented warm-up, mechanisms developed in isolated probe branches before factorial composition. | The proposer gets **verdicts only**, never held-out scores: this is already true, and it becomes a tested invariant. Isolated probe branches = one worldline per candidate (already). Admission evidence (fresh split) is never reused for search. | M1 (invariant), M2 |
| **2610.14224** Harness² | Without ground-truth verifiers, use a contrastive **Propose-Probe-Compose** step at task level, plus a harness-level recursion that distils edits into a continual-improvement harness. | Probe = trial in a worldline against paired replays (the env is seeded, so replays are paired). Compose = M2 recombination. Harness-level recursion = the library plus its statistics feeding the proposer prior. | M2, M3 |
| **2609.38372** Self-Evolving Harness on Multiple Tasks | The same frozen model, on the same harness version, solves and then proposes by reading complete run records. Multi-domain batches, strict train/held-out separation, OOD evaluation. Two stages: pretraining, then continual training. Emergent mechanisms: output truncation, history compaction, independent review. | M3: real developer trajectories (build/test/fix) across several small repos as the multi-domain batch. A local LLM *or* a scripted proposer reads full run records. An OOD repo is never used in evolution. Our `compress` plugin is the truncation mechanism the paper reports as emergent. | M3 |
| **2610.07792** ServeLearnBench (benchmark) | Evolving-environment streams: agents must infer hidden, changing policies from outcome feedback only. Hidden-Dependent vs Fully Specified split shows adaptation can break already-correct behaviour; exploration (distinct answers per policy) tracks final reward across harnesses (ρ=1.00); knowledge acquisition after first success is a separate bottleneck; a strict accept gate (SkillOpt, ~1 in 9 steps) explores least and learns slowest. | *Measurement only* (`rsi/metrics.py`, `run_rsi(measure=True)`): HD/FS task labels (`env.task_label`), FS/HD regressions vs the frozen seed harness, AULC10 after a fact version change, AUC_E per failure signature, AUC_KA after the first KEEP, acceptance rate / first-KEEP latency, serving vs learning cost (replayed executions, LLM tokens/USD). No admission change. | M7 (measure) |

Common thread: **separate what may change, who proposes it and who admits it; admit only on evidence the search never saw; keep a library, not just a current version; never let the evolved code touch its own guard.** aura-harness already has the last property (the guard lives in `server.aura`, outside the workspace). The milestones add the others.

## 2. Architecture after M1–M4

```
             ┌──────────── ProposalSource ────────────┐
trajectories │ rule proposer (today) · scripted (M3)  │   Proposal = (target, plugin, edit, evidence sig, provenance)
──────────►  │ local LLM (M3) · recombiner (M2)        │──────────────┐
             └─────────────────────────────────────────┘              ▼
                                                     ┌──────────── Admission (host + Aura) ─────────────┐
                                                     │ 1 target policy   (control-logic: never)         │
                                                     │ 2 plugin scope    (restricted edit scope)        │
                                                     │ 3 critic          (M2: benchmark-specific?)      │
                                                     │ 4 guard + trial   (server.aura, worldline)       │
                                                     │ 5 gate            (window held-out, paired)      │
                                                     │ 6 retention gate  (old windows, regression budget)│
                                                     │ 7 fresh validation(M2: unseen split, one use)    │
                                                     └──────────────────────────┬───────────────────────┘
                                                                                 ▼
                                    live harness (Aura root) ◄── KEEP ── plugin library + Pareto archive (M2)
                                                                                 │
                                                                 audit ledger (host, persistent; M4: why/diff/rollback)
```

### Update targets (2610.18813)

| target | here | admissible? |
|---|---|---|
| `state`: a table edit inside one plugin | `route-tool`, `compress`, `retry-limit`, `memory-ttl`, `delegate` bodies compiled from tables | yes |
| `code`: a free-form body for a mutable plugin | LLM hook, Lisp body | yes, through guard + gate (M3) |
| `control`: runtime boundary, guard, loop | `context-budget`, `max-steps`, `allowed-tools`, `sandbox-level`, `server.aura` | **never**: blocked and audited |
| `composition`: a set of library variants | recombination of admitted plugin variants | yes (M2) |

### Retention gate (M1)

The window gate checks that a candidate is better on *recent* held-out tasks. It cannot see forgetting: an edit can win the current window and break what an earlier KEEP fixed. The paper's retention bound is conditional on a historical regression budget, so:

* At every KEEP, the gate window (its tasks plus the memory checkpoint) is appended to a **retention suite**, keeping the newest `R` windows (default 4).
* A candidate that passes the window gate is replayed on each retention window that does *not* overlap the current window. For held-out tasks only, each one the live harness solves and the candidate fails is a regression, and each one the candidate solves and the live harness fails is a recovery.
* Admission requires `regressions − recoveries ≤ budget_left`. `budget_left = ⌊ρ · |retention held-out|⌋ − spent`, where `spent` accumulates the net regressions of earlier admissions and decays by one every `D` tasks (default ρ = 0.05, D = 50). The cumulative spend is the historical regression budget.
* With the retention gate off, the loop must reproduce the legacy loop bit for bit (tested).

### Supervisor for aura#4670

On `a6c63aa19` the control plane can SIGSEGV after a few rebinds of fuzzed bodies. The supervisor keeps a host ledger of every admitted rebind (`name`, `body`, `desc`, version). On `harness process exited` it does the following:
1. Respawns `server.aura` and replays the ledger with `APPLY` as actor `supervisor-replay`.
2. Checks that the replayed `TABLE` equals the last known table.
3. Retries the failed call once. If the retry crashes too, the operation is reported as a blocked trial (reason `control plane crashed (aura#4670)`) and the process restarts again.

Every restart is recorded in the host audit ledger, and the process-local audit of the dead process is lost (the host ledger is the audit of record from M4).

## 3. Milestones

| | scope | done when |
|---|---|---|
| **M1** | Plugins + plugin library; `Target` / `ProposalSource` / `Admission` split; retention gate; supervisor; `rsi` CLI and bench. | Retention off reproduces the legacy bench exactly. Retention on is measured on 5 seeds × 400 tasks (success, held-out, tokens, KEEPs, retention vetoes). The supervisor is tested by fault injection and on the #4670 trace. Tests green. |
| **M2** | Pareto archive (success, tokens, retention). Proposal budget (annealed edits per candidate, candidates per step). Critic and pruner. Fresh-validation admission (one-use split). Library recombination. | Ablation table on the bench and noise30/100: each piece on/off. Archive and pruned-edit report. Tests. |
| **M3** | Real developer trajectories: small Python repos with seeded bugs; build/test/fix loop. The harness plugins drive real tools (`grep`/`rg`, `sed`/patch, `pytest`), with truncation and retry. Scripted proposer by default, local LLM (OpenAI-compatible URL) optional. Evolution repos disjoint from eval repos, plus an OOD repo. | End-to-end run with frozen vs evolved harness on held-out repos. No external API needed. Numbers in the README with caveats. |
| **M4** | User-facing audit: `python3 -m aura_harness audit` lists changes with **why** (evidence sig, trajectories, gate/retention scores), **diff** (old/new body and table delta), and **one-command rollback** (`audit rollback <id>`, itself guarded and audited). Persistent JSONL ledger. | Demo transcript in the README. Rollback restores the exact earlier table (tested), including across a supervisor restart. |

## 4. Invariants (tests enforce them)

1. Control-logic targets are never admitted. Every attempt is audited.
2. The proposer never sees held-out task ids, held-out scores or retention scores, only verdicts (2610.19424: content-free feedback).
3. Admission evidence is paired and replayable from seeds.
4. Retention off == the legacy loop (verdicts, tables and success, per seed).
5. A supervisor restart preserves the live table exactly.

## 5. Risks

* **Simulated environment.** Gains in M1/M2 are on the seeded simulator. M3 is the first contact with real trajectories, and it is small.
* **Retention vs distribution shift.** After the shift at task 200, an old skill may be *right* to forget. The decaying budget is the knob, and the M1 numbers show its cost.
* **aura#4670.** Restarts replay the ledger, so cost grows with history. A compacted snapshot (`SOURCE` → `set-code`) is the fallback if ledgers get long.
