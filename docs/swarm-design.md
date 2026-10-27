# Swarm: Agensh-style self-organizing workers on Aura fibers

Status: MVP (`aura/swarm.aura`, driver `aura_harness/swarm.py`, bench `scripts/swarm_bench.py`, results `results/swarm-bench.{md,json}`).
Source idea: Agensh (arXiv:2609.26781, github.com/microsoft/Agensh, MIT). We borrow the coordination design, not the code.

## What we borrow

Agensh drops the central orchestrator: N *identical* workers share three pieces of infrastructure and each runs the same loop.

| Agensh | Here (Aura) |
|---|---|
| worker process | one Aura fiber (`fiber:spawn`) |
| DM / broadcast mailbox | one `channel:create` per worker (`dm!`, `drain-inbox`); broadcast = board |
| append-only typed board, `grep`, push-newest | `board` list + counter; `board-post!`, `board-grep`, `board-new cursor upto` |
| entry types | `OBSERVED` `FACT` `FAIL` `CLAIM` `RELEASE` `PATCH_SUMMARY` |
| shared git-like workspace | per-family version `ws-ver` + `ws-log`; `ws-merge!` = fast-forward or rebase-on-mismatch, rollback if verify fails |
| loop Gather → Claim → Act → Verify → Merge | `gather!` `pick`/`claim!` `act!` `verify?` `merge!` in `worker-turn` |

Gather reads only board entries up to the round snapshot plus DMs, so each worker's view is stale by design. `pick` decides from that view, then `claim!` does a live check-and-insert. A lost race counts as a claim conflict, and the loser DMs the owner ("WANT i"). An owner that has not started yet can release on request (negotiated release). Act reuses `FACT` entries posted by other workers for the same family (knowledge reuse), or else scans a window and posts `OBSERVED`, `FACT` or `FAIL`.

**Toy task (deterministic mock proposer, no LLM):** K subtasks in F families. Subtask i (family g = i mod F) needs a root x of x²+gx+7 ≡ 0 (mod 997) with x ≡ i (mod 3), or a proof that none exists. Each check is O(1) and the answers are fully determined. **Acceptance:** every subtask merged exactly once, and each merged answer re-verified (`all-accepted?`). DeepSeek can be plugged into `act!` later. It is not used here.

## Two runners

* **epoch**: each round spawns N fibers, one per worker turn, and joins them. The root fiber only ticks the clock and never assigns tasks.
* **free**: one long-lived fiber per worker, with `fiber:yield` between turns. This is the true Agensh shape, but it depends on cooperative interleaving (see findings).

## Aura fiber findings (as of agx copy of aura-pw build b211a5def = main 569ec0408 + tc-infer WIP)

1. `--serve-async` loses fibers: bodies that allocate are never run and `fiber:join` returns void. Even trivial bodies are lost at scale (N=1024 → 970 voids). So the bench uses CLI `--load` (thread backend).
2. CLI thread backend: `fiber:join` returns void for some fibers, and their bodies never run (turns run < spawned). Micro: N=32 gives 30 voids, N=1024 gives 941. The `par20` repro gives 17/20. Related to #4495 and #4356.
3. `fiber:yield` does not interleave siblings in either mode. Order is `3 3 3 2 2 2 1 1 1`. In free mode a single worker merges all K tasks (`max-worker-share = K`), so there is no self-organization. Same family as #4358.
4. In both modes fiber bodies are serialized (CLI: a body mutex). Wall time grows with N, with no parallel speed-up.
5. `channel:recv` blocks the OS thread (condvar), so it deadlocks under serve-async. The MVP uses `try-recv` only.
6. Misc: `((lambda (j) (lambda () j)) 3)` gives unbound `j`. serve-async multi-form exec drops defines. The only clock is `monotonic-ms` (phase timers are ms sums).

**Workarounds in the MVP:** CLI backend, `try-recv` only, non-allocating `hash-ref` defaults, one form per exec in serve mode, explicit `else` in `cond`. A turn lost to a void join is just a lost turn: the protocol self-heals because unfinished claims are released or retried.

Filed: #4697 (CLI drops fibers), #4698 (serve-async drops allocating fibers), #4699 (yield doesn't interleave / serialized bodies), #4700 (recv blocks thread), #4701 (closure unbound), #4702 (serve-async multi-define exec) — all on cybrid-systems/aura.

## Results (K=1024, F=64, CLI backend)

See `results/swarm-bench.md`. Summary:

| N | rounds | wall s | gather s | claim s | turns lost (void) | conflicts on done | peak RSS MB |
|---|---|---|---|---|---|---|---|
| 1 | 1991 | 4.3 | 0.4 | 2.3 | 7 | 0 | 129 |
| 8 | 915 | 18.1 | 1.9 | 12.2 | 95 | 5004 | 176 |
| 32 | 88 | 6.2 | 3.3 | 0.9 | 43 | 315 | 138 |
| 128 | 27 | 16.3 | 13.0 | 0.8 | 1 | 512 | 202 |
| 1024 | 16 | 422.8 | 403.9 | 5.4 | 1 | 0 | 531 |

Micro: board append about 16 µs/entry (20k in 314 ms), grep over 20k in 57 ms, channel send+recv about 3 µs/msg, spawn 1024 fibers in 32 ms (+28.6 MB).

Rounds drop with N as expected (1991 → 16), so the coordination works. Wall time does not drop, because fibers are serialized. At large N, gather dominates: each worker re-reads all new board entries, so the cost is O(N · board). N=8 herds: workers with the same FACT knowledge pick the same task, which shows up as conflicts on done tasks and claim time.

## Next

* Per-worker gather cursor with a type index (grep by type instead of a full scan), and randomized pick among known-family candidates to stop herding.
* Re-run free mode once `fiber:yield` interleaves. Re-run serve-async once fibers stop being lost.
* Put a DeepSeek proposer behind `act!` (key file only, never logged).

## Multi-fiber validation (Aura main 572beb276, CLI thread backend, K=1024, F=64)

Harness changes: sound scan protocol (OBSERVED payloads carry `from:to:roots`; FACT/FAIL
only once every window of [0,P) is covered — the old skip-ahead gave false FAILs once
fibers really interleaved), claim leases (`16+8N` ticks, stale claims are stealable),
claim-to-merge latency, failure injection, a `stop` flag for cooperative cancel and a
per-worker policy rebind (`mutate:rebind` + `eval-current` on `pol-<w>`).
Runners: `run-rebind`, `run-fail`, `run-cancel`; `scripts/swarm_bench.py --validate`.

Findings (full tables: `results/swarm-bench.md`; old serialized run:
`results/swarm-bench-baseline-b211a5def.md`):

- Correctness: accepted=1 for every N in 1..32, epoch and free; 0 void joins (baseline
  lost 7-95 turns); 0 dup merges; free mode now self-organizes (max share 1024/N-ish
  vs 1024 for one worker in the baseline).
- No multi-core speedup: fiber bodies are serialized (body mutex), so free-mode wall
  time grows 4.2 s → 8.5 s from N=1 to 32 and tasks/s falls 242 → 121; latency grows
  with N (mean 1.1 → 155 ms).
- Rebind under contention: ~480-495 rebinds per run, 0 failures, 0 stale reads,
  mean 3.5-8.3 ms, max 25 ms; wall cost 1.5-3.2x vs no rebind.
- Failure: the raising worker surfaces as exactly one join error; for N≥2 its claim is
  taken over through the lease (claims-stolen=1) and the run is accepted. N=1 has no
  peer, so it is (correctly) not accepted.
- Cancel (no `fiber:cancel` primitive; cooperative `stop`): last worker exits 0-3 ms
  after stop; partial results always valid. Workers stopped mid-turn leave their claim
  held (lease-recoverable): claims left = N at N≥8.
- Aura bugs found: tier JIT worker wiped all hash tables (fixed in Aura 572beb276);
  serve-async SIGSEGV in `maybe_reclaim_tw_unreachable` with yield + allocation;
  hash tables returned by fibers emptied/aliased before join; a stats-hash key string
  corrupted under rebind with N≥2 (tests therefore assert only accepted/done-valid).
