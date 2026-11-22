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
patches and worldlines. The harness never opens trials. KEEP/ROLLBACK is
the **scoped-grant judge flow** (aura#5377/#5382): the host derives a
keep+rollback token scoped to one worldline (`bus:grant bits=24 channels
loans expires worldline`) and hands it over out-of-band; the harness
activates it (`BUSGRANT` → `bus:grant-activate`), keeping its read/publish
bits and gaining keep+rollback on that worldline only, then judges it
(`BUSJUDGE`). Without an active grant scoped to the worldline a keep is
refused — locally (`no-grant`) and by the coordinator (`permission`).
There is no local path around the grant.

Since aura#5377 the host serves **multiple peers concurrently** (poll
event loop, per-session isolation): the proposer, the harness judge and
other tools attach to the same image and audit at the same time; a
crashed peer only rolls back its own pending trials.

## Channel mapping

| channel | what the harness does |
|---|---|
| metrics | reads perf's hypothesis keys (K → base-ms) and the summary keys 900001/900002; publishes its verdicts: `910000 + wl` → 1 release / 0 reject, `920000 + wl` → held-out ok count, `930000 + wl` → held-out task count |
| worldlines | reads the coordinator's trial records (id, parent, state, constraint result, patch range); state 0 pending / 1 kept / 2 rolled / 3 rejected / 4 canary (observation window, aura#5381). The channel is append-only: a settled trial appears again with its final state |
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

## Scoped-grant judge flow (aura#5377/#5382)

1. The proposer (role perf, caps `read|publish|trial`) opens a trial,
   publishes the candidate define source (`bus:publish-source`) and a
   source-carrier patch (`bus:publish-patch node bus:source-field index
   wl gen`, field marker `4294967280`), then binds the evidence five-tuple
   (`bus:candidate-digest` → `bus:bind-evidence wl baseline candidate
   workload seed verifier`).
2. The host (workspace owner, maintainer caps incl. `grant`) derives a
   scoped token: `bus:grant msid 24 255 0 0 wl` — keep(8)+rollback(16),
   all channels, no loan quota, no expiry, scoped to `wl`. The token
   travels out-of-band (control plane), never through a candidate body.
3. `BUSGRANT <token> <wl>` activates it: `bus:grant-activate` returns
   `(ok bits worldline)`; the session keeps read/publish and gains
   keep+rollback scoped to that one worldline.
4. `BUSJUDGE <wl> [pass|fail]` reads the worldline's evidence
   (`bus:evidence`) and its committed patch records (`bus:query` channel
   3), runs the hidden-set regression replay (the harness's existing
   bench + guard post-check; `pass`/`fail` forces the outcome for tests),
   then `bus:keep` on pass or `bus:rollback` on fail, and reports the
   verdict with the worldline's final state (`kept`, `rolled`, or
   `canary` when the host runs an observation window).

With `AURA_BUS_EVIDENCE=1` the coordinator re-checks the five-tuple at
KEEP (stale baseline / candidate-hash mismatch / missing evidence are
`validation-failed`); with `AURA_BUS_CANARY_WINDOW=N` a KEEP enters state
4 (canary) and seals when N metric ticks at/above
`AURA_BUS_CANARY_FLOOR` arrive on `AURA_BUS_CANARY_KEY` (or the judge
seals early with `bus:canary-confirm`); a floor breach auto-reverts.
Defaults off = v0.3.0 behavior.

## Control-plane commands

`BUSATTACH`, `BUSMETRICS [gen count]`, `BUSWORLDLINES`,
`BUSVERDICT wl release|reject ok n`, `BUSGRANT token wl`,
`BUSJUDGE wl [pass|fail]`, `BUSAUDIT [wl]`, `BUSFINISH`
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
≥ v0.3.1 for the judge tests; skipped otherwise): a perf-shaped peer
publishes and trials, the harness reads the same image, publishes a
verdict a later peer reads back, `none` vs `error` stays distinct, bus-off
is identical, and a bus verb in a candidate body is blocked. The judge
tests run the closed loop against a live host: without a grant a keep is
refused permission; with the host's scoped grant the harness activates it
and KEEPs the pending worldline (state 1 kept, or 4 canary when the host
runs an observation window).

## Primitive surface note

`server.aura` uses the post-v0.2.1 spellings (`mutate :snapshot`,
`mutate :restore`, `stats:get "orch:metrics"`); the retired `ast:`/`orch:`
aliases were unregistered in aura c58f7afa3.
