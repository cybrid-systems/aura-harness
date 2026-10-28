# swarm vs supervisor bench on Aura e6f4169e0 (parallel fiber bodies, #4717)

K=1024, F=64, 3 runs per cell, timeout 150 s, host-mode Release build, AURA_TIER_JIT=1. Produced by a resilient per-N loop because `scripts/sv_bench.py` aborts on the first failed run (it died at N=2). The box was shared with another bench, so treat wall times as ±15%. Previous numbers (235bcfa6b, serialized bodies): `sv-bench-235bcfa6b.md`, `swarm-bench-prev.md`.

| N | mode | runs accepted / 3 | done (per run) | tasks/s (accepted runs) | join errors / workers dead (per run) | failures |
|---|---|---|---|---|---|---|
| 1 | swarm | 3 | 1024, 1024, 1024 | 152.1, 155.6, 161.1 | 0, 0, 0 |  |
| 1 | supervisor | 0 | 0, –, 736 | – | 1, –, 1 | timeout 150 s (livelock) |
| 2 | swarm | 3 | 1024, 1024, 1024 | 132.8, 132.8, 130.9 | 0, 0, 0 |  |
| 2 | supervisor | 1 | 944, 1024, 720 | 572.1 | 2, 1, 2 |  |
| 4 | swarm | 3 | 1024, 1024, 1024 | 123.6, 130.5, 117.2 | 2, 2, 1 |  |
| 4 | supervisor | 2 | –, 1024, 1024 | 669.3, 662.8 | –, 3, 3 | timeout 150 s (livelock) |
| 8 | swarm | 3 | 1024, 1024, 1024 | 133.4, 139.5, 131.5 | 6, 6, 6 |  |
| 8 | supervisor | 1 | –, –, 1024 | 682.7 | –, –, 7 | SIGABRT; timeout 150 s (livelock) |
| 16 | swarm | 1 | 1024, –, – | 112.7 | 13, –, – | 349:53: `unbound variable: n` |
| 16 | supervisor | 0 | –, –, – | – | –, –, – | 553:48: `unbound variable: n`; timeout 150 s (livelock) |
| 32 | swarm | 0 | –, –, – | – | –, –, – | 349:53: `unbound variable: n` |
| 32 | supervisor | 0 | –, –, – | – | –, –, – | 553:48: `unbound variable: n` |

Every failure here is aura#4730: `hash-set!` on a shared hash from parallel bodies corrupts lexical environments, and the run either loses a worker (`join-error`/`workers-dead`), spins forever or dies with `unbound variable: n` in the main thread's spawn loop (deterministic at N≥16). See the README section *Re-check on e6f4169e0*.
