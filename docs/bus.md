# aura-harness on the Aura bus (#4, aura#5128)

The RSI loop's trials, held-out regression evidence and release/reject
verdicts go on the **target workspace's** bus, next to perf's CCT and
hypotheses and the shared audit. Enabled by `AURA_HARNESS_BUS_WORKSPACE=N`
(the workspace id of the target bus). Without it nothing bus-related is
loaded and every run is byte-identical to the bus-off path — the pin
`a6c63aa19` has no `std/bus` and never resolves it.

## Lifecycle

The harness is a **peer**, not the host: the target workspace's owner
hosts the bus (aura-perf's parent hosts its round; a coordinator script
can host for a cross-tool run). `server.aura` attaches at startup as
role 2 (harness), caps `read|publish` = 3, and subscribes metrics, CCT,
patches and worldlines. The harness never opens trials and never KEEPs:
KEEP stays with the proposer under the coordinator's constraint gate —
there is no local path around it.

One peer is served at a time by the current host (aura's delivered
single-peer loop): after a tool detaches, the host keeps serving and the
next tool attaches to the **same image and audit**. Simultaneous
multi-peer attachment is the aura-side follow-up (aura#5377).

## Channel mapping

| channel | what the harness does |
|---|---|
| metrics | reads perf's hypothesis keys (K → base-ms) and the summary keys 900001/900002; publishes its verdicts: `910000 + wl` → 1 release / 0 reject, `920000 + wl` → held-out ok count, `930000 + wl` → held-out task count |
| worldlines | reads the coordinator's trial records (id, parent, state, constraint result, patch range); state 0 pending / 1 kept / 2 rolled / 3 rejected. The channel is append-only: a settled trial appears again with its final state |
| cct, patches | subscribed; read on demand (`BUSWORLDLINES`/`BUSMETRICS` today; the CCT/patch faces are the same `bus:query` shape) |
| audit | `BUSAUDIT [worldline]` reads the coordinator's log — every tool's trials, verdicts, constraint results and disconnects, the same one perf and maintainer write |

`wl` is the target bus worldline id when the loop has a mapping
(`BusFace.wl_of`), otherwise the round's task id — the evidence is on the
bus either way, keyed by the round.

## Read semantics (PROV parity)

Three distinguishable outcomes, never merged:

- `status=ok` with rows — records read;
- `status=none` — an ok read with zero records ("no metrics");
- `status=error` with `code`/`message` — the read itself failed
  (`transport-failed`, `permission`, `no-bus`, …). A failed read is never
  reported as "no metrics", matching the existing PROV try/catch-vs-type
  distinction.

## Control-plane commands

`BUSATTACH`, `BUSMETRICS [gen count]`, `BUSWORLDLINES`,
`BUSVERDICT wl release|reject ok n`, `BUSAUDIT [wl]`, `BUSFINISH`
(tab-separated, same `R <json>` protocol). `BusFace` (aura_harness/bus.py)
wraps them for `run_rsi`; the summary lands in `out["bus"]`. `QUIT`/EOF
detaches cleanly; a crash is a disconnect — the coordinator rolls back
the session's pending trials and reclaims its loans, and a supervisor
restart re-attaches from the env.

## Guard

Candidate bodies cannot reach the bus: `bus:` and `hbus:` are in
`*banned-prefixes*`, so a proposal that calls a bus verb is blocked by
the static guard like any other reflective primitive.

## Tests

`tests/test_bus.py` (needs `AURA_BIN` pointing at a bus-capable aura,
≥ `5f567b94a` + the #5128 image-persistence wiring; skipped otherwise):
a perf-shaped peer publishes and trials, the harness reads the same
image, publishes a verdict a later peer reads back, `none` vs `error`
stays distinct, bus-off is identical, and a bus verb in a candidate body
is blocked.

## Primitive surface note

`server.aura` uses the post-v0.2.1 spellings (`mutate :snapshot`,
`mutate :restore`, `stats:get "orch:metrics"`); the retired `ast:`/`orch:`
aliases were unregistered in aura c58f7afa3.
