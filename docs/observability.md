# Observability: per-run traces, cost attribution, OTLP export

`aura_harness/obs.py` adds an opt-in trace to the RSI loop (`run_rsi`) and to the swarm/supervisor modes
(`aura/swarm.aura`, `aura/supervisor.aura`). It is **off by default**. Every instrumented entry point takes `tracer=None`;
when no tracer is passed, nothing is recorded and the hot path costs only an `if tr:` check. Verdicts are identical with
tracing on and off (`tests/test_obs.py::test_rsi_trace_off_is_identical`).

```bash
python3 -m aura_harness trace rsi --seed 1 --n 400 --otlp runs/rsi.otlp.json --jsonl runs/rsi.spans.jsonl
python3 -m aura_harness trace swarm --N 4 --K 256 --F 32 --otlp runs/swarm.otlp.json
python3 -m aura_harness trace supervisor --N 4 --K 256 --F 32
```
Each command prints a span summary and a validation block. It exits 1 if validation fails. As a library:
`from aura_harness.obs import Tracer; t = Tracer(); run_rsi(seed, tracer=t); t.write_otlp(path)`.
`obs.from_env` / `obs.finish` honour `AURA_HARNESS_OBS=1`, `AURA_HARNESS_OTLP=<file>` and `AURA_HARNESS_TRACE_JSONL=<file>`.

## Spans

| span | parent | one per | key attributes |
|---|---|---|---|
| `rsi.run` | – | run | label, seed, n, worldlines, world, `count.*`, `llm.prompt_tokens/completion_tokens/calls/usd`, `aura.version`, `aura.root_mlog` |
| `rsi.task` | run | stream task | `task.id/kind/phase/heldout/success/tokens/steps/solve_ms`; **cost attribution**: `cost.wall_ms`, `cost.mutations` (KEEPs + ungated applies landed during the task), `cost.llm_tokens`, `cost.llm_usd` |
| `rsi.candidate_round` | task | proposer output reaching the guard | sig, why, n_candidates, `llm.tokens`, `llm.calls`, propose_ms, trial_ms, verdict, actor (`pruner` for ablations) |
| `rsi.proposal` | round | candidate | `cand.i/desc/name/target`, proposer (`rule`/`llm`), `llm.model`, `llm.provider`, round token/call/usd totals |
| `rsi.trial` | round | candidate | `trial.ok`, `trial.reason` (guard / worldline / host target veto), `trial.aura_ms`, `aura.prov` |
| `rsi.gate` | round | gated round | `gate.base`, `gate.window`, `gate.scores` (paired replay per candidate), `gate.ms` |
| `rsi.verdict` | round | decision | `verdict` KEEP / ROLLBACK / PENDING (stat admission), `verdict.where` (`aura`, or `host` for critic vetoes), `chosen`, **`reason`**, `aura.version`, `aura.prov`, `aura.root_mid`, `aura.root_mlog`, verdict.ms |
| `rsi.apply` | task | ungated / stat-gate APPLY | actor, cand.desc, ok, reason, `aura.prov`, `aura.version` |
| `swarm.run` / `supervisor.run` | – | run | every scalar counter of the run (`done`, `merged`, `evals`, `wall-ms`, …), `validation.ok` |
| `swarm.task` / `supervisor.task` | run | merged or rolled-back task attempt | `task.id`, worker(s), outcome, **`cost.wall_ms`** (claim→merge), **`cost.evals`**, **`cost.mutations`** (rebinds by that worker during the task) |

**Mutation provenance id.** `aura.prov` has the form `ws<workspace>/m<mutation_id>`. `server.aura` reads it from Aura's
own `query:last-mutation-provenance` right after the guarded `mutate:rebind`. The control plane's audit log (`LOG`) stores
the same id in each entry's `prov` field. The `PROV` command returns Aura's root `(query :mutation-log)`,
`query:last-mutation-provenance` and `orch:metrics` (`AuraHarness.prov()`).

**Per-task rows in Aura.** `aura/swarm.aura` has a `trace-on` flag (default `#f`). When it is on, each worker counts the
evals and rebinds it spends on its claimed task in its own fiber-private state, and writes one row on merge or rollback:
`task,worker,t-claim,t-end,evals,rebinds,outcome`. The host turns these rows into spans (`obs.swarm_trace`).

## OTLP

`Tracer.write_otlp` writes the OTLP/JSON `ExportTraceServiceRequest` shape:
- `resourceSpans[].resource.attributes`
- `scopeSpans[].scope = aura_harness.obs`
- spans with a 32-hex `traceId`, 16-hex `spanId`/`parentSpanId`, `startTimeUnixNano`/`endTimeUnixNano`, typed
  attributes and `status`.

An OpenTelemetry Collector can ingest the file with its `otlpjsonfile` receiver, or you can `POST` it to `/v1/traces`.
The harness itself sends nothing anywhere.

## Validation against Aura

`obs.validate_rsi(tracer, audit, prov)` joins the host trace with the control plane's audit log and Aura's provenance:
- trial count == `trial-ws`/`trial-snap` + `blocked` audit entries;
- KEEP / ungated KEEP / ROLLBACK counts match the audit log;
- every admitted trial and every KEEP carries an Aura mutation id (`/m<id>`, id > 0);
- the KEEP provenance ids in the trace equal those in the audit log, in order;
- control-plane version == KEEPs + ungated KEEPs.

After a control-plane restart, the server-side log before the restart is gone, so the count checks report
`n/a (restart)`.

`obs.swarm_trace` checks the rows against the run's own counters:
- merged rows == `merged`;
- distinct merged tasks == `done`;
- no duplicate merges;
- rollback rows == `rolled-back`.

**Finding on Aura e6f4169e0.** The per-task (fiber-private) eval attribution *exceeds* the shared `evals` counter, e.g.
9970 vs 9906. Since aura#4717 P4/P5, fiber bodies run in parallel, and the shared read-modify-write
`(hash-set! m k (+ n (hash-ref m k 0)))` loses increments. Concurrent `hash-set!` can also corrupt state (aura#4730; the
COW-overlay answer is aura#4715). The trace reports this under `warnings` / `shared_counter_lost` instead of failing
validation, because the per-task numbers are the exact ones.

Measured overhead and validation results on the current pin are in the README, section "Observability".
