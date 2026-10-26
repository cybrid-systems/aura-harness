# swarm bench (aura/swarm.aura)

K=1024 subtasks, F=64 families, backend=cli, bin=/workspace/agx/aura

## epoch mode (one fiber per worker turn; ticker only advances time)

| N | rounds | wall ms | spawn ms | join ms | gather | claim | act | verify | merge (ms, summed over turns) | turns run / spawned | join void | claim conflicts (live / already-done) | DMs (sent, mean latency rounds) | rebase / rollback | fact reuse | evals | board entries | peak RSS MB | accepted |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 1991 | 4348 | 130 | 4196 | 405 | 2284 | 415 | 31 | 59 | 1984 / 1991 | 7 | 0 / 0 | 0, - | 0 / 0 | 960 | 63808 | 3136 | 129.3 | 1 |
| 8 | 915 | 18114 | 296 | 17805 | 1901 | 12210 | 576 | 49 | 73 | 7225 / 7320 | 95 | 0 / 5004 | 0, - | 16 / 0 | 944 | 79568 | 3405 | 175.5 | 1 |
| 32 | 88 | 6159 | 93 | 6065 | 3320 | 903 | 632 | 39 | 74 | 2773 / 2816 | 43 | 0 / 315 | 0, - | 32 / 0 | 928 | 95328 | 3674 | 138.4 | 1 |
| 128 | 27 | 16262 | 111 | 16150 | 13043 | 791 | 854 | 42 | 131 | 3455 / 3456 | 1 | 0 / 512 | 0, - | 64 / 0 | 896 | 127552 | 4223 | 201.7 | 1 |
| 1024 | 16 | 422845 | 576 | 422269 | 403853 | 5350 | 6725 | 156 | 132 | 16383 / 16384 | 1 | 0 / 0 | 0, - | 960 / 0 | 0 | 1020864 | 19455 | 531.0 | 1 |

## free mode (one long-lived fiber per worker, fiber:yield between turns)

| N | wall ms | spawn ms | done | max tasks merged by one worker | turns run | join void | peak RSS MB |
|---|---|---|---|---|---|---|---|
| 1 | 3066 | 0 | 1024 | 1024 | 1984 | 0 | 122.3 |
| 8 | 3088 | 1 | 1024 | 1024 | 1984 | 1 | 119.2 |
| 32 | 3105 | 1 | 1024 | 1024 | 1984 | 0 | 120.5 |
| 128 | 3150 | 3 | 1024 | 1024 | 1984 | 0 | 124.7 |
| 1024 | 3251 | 39 | 1024 | 1024 | 1984 | 0 | 167.8 |

## micro

board: {'appends': 20000, 'append-ms': 314, 'grep-ms': 57, 'grep-hits': 542, 'new100-ms': 0}

channel: {'msgs': 20000, 'send-ms': 28, 'recv-ms': 34}

| N fibers | spawn ms | join ms | join void | peak RSS MB | RSS over idle MB |
|---|---|---|---|---|---|
| 1 | 0 | 1 | 0 | 97.4 | 0.0 |
| 8 | 1 | 1 | 0 | 97.6 | 0.3 |
| 32 | 1 | 1 | 30 | 97.7 | 0.4 |
| 128 | 4 | 5 | 30 | 101.1 | 3.7 |
| 1024 | 32 | 18 | 941 | 125.9 | 28.6 |
