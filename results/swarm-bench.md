# swarm bench (aura/swarm.aura)

K=1024 subtasks, F=64 families, backend=cli, bin=/workspace/rv/bin-fix/build-rel/aura

## epoch mode (one fiber per worker turn; ticker only advances time)

| N | rounds | wall ms | spawn ms | join ms | gather | claim | act | verify | merge (ms, summed over turns) | turns run / spawned | join void | claim conflicts (live / already-done) | DMs (sent, mean latency rounds) | rebase / rollback | fact reuse | evals | board entries | peak RSS MB | accepted |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 1984 | 5772 | 139 | 5593 | 451 | 3002 | 630 | 37 | 76 | 1984 / 1984 | 0 | 0 / 0 | 0, - | 0 / 0 | 960 | 63808 | 3136 | 142.0 | 1 |
| 2 | 1542 | 9389 | 143 | 9215 | 843 | 5588 | 740 | 35 | 75 | 3084 / 3084 | 0 | 0 / 950 | 0, - | 10 / 0 | 950 | 73778 | 3306 | 160.0 | 1 |
| 4 | 1243 | 15428 | 171 | 15242 | 1547 | 9871 | 854 | 51 | 73 | 4972 / 4972 | 0 | 5 / 2623 | 5, 1.0 | 24 / 0 | 936 | 87736 | 3544 | 203.5 | 1 |
| 8 | 915 | 24520 | 279 | 24236 | 2594 | 16239 | 794 | 67 | 98 | 7320 / 7320 | 0 | 0 / 5096 | 0, - | 16 / 0 | 944 | 79760 | 3408 | 237.8 | 1 |
| 16 | 574 | 31741 | 302 | 31431 | 5160 | 19151 | 1105 | 78 | 107 | 9184 / 9184 | 0 | 0 / 6480 | 0, - | 48 / 0 | 912 | 111664 | 3952 | 279.9 | 1 |
| 32 | 83 | 10838 | 73 | 10764 | 7182 | 808 | 925 | 41 | 113 | 2656 / 2656 | 0 | 0 / 192 | 0, - | 32 / 0 | 928 | 95712 | 3680 | 174.2 | 1 |

## free mode (one long-lived fiber per worker, fiber:yield between turns)

| N | wall ms | spawn ms | done | max tasks merged by one worker | turns run | join void | peak RSS MB |
|---|---|---|---|---|---|---|---|
| 1 | 4229 | 0 | 1024 | 1024 | 1984 | 0 | 149.4 |
| 2 | 4855 | 0 | 1024 | 512 | 1984 | 0 | 155.1 |
| 4 | 5183 | 0 | 1024 | 268 | 1984 | 0 | 168.2 |
| 8 | 5536 | 0 | 1024 | 159 | 1984 | 0 | 199.6 |
| 16 | 6594 | 1 | 1024 | 68 | 1984 | 0 | 250.3 |
| 32 | 8477 | 1 | 1024 | 36 | 1989 | 0 | 363.1 |

## throughput and claim-to-merge latency

| mode | N | wall ms | tasks/s | mean latency ms | max latency ms | turns | accepted |
|---|---|---|---|---|---|---|---|
| epoch | 1 | 5772 | 177.4 | 1.8 | 34 | 1984 | 1 |
| epoch | 2 | 9389 | 109.1 | 4.6 | 156 | 3084 | 1 |
| epoch | 4 | 15428 | 66.4 | 12.1 | 178 | 4972 | 1 |
| epoch | 8 | 24520 | 41.8 | 29.7 | 520 | 7320 | 1 |
| epoch | 16 | 31741 | 32.3 | 107.8 | 1171 | 9184 | 1 |
| epoch | 32 | 10838 | 94.5 | 235.1 | 2686 | 2656 | 1 |
| free | 1 | 4229 | 242.1 | 1.1 | 217 | 1984 | 1 |
| free | 2 | 4855 | 210.9 | 2.8 | 71 | 1984 | 1 |
| free | 4 | 5183 | 197.6 | 7.1 | 125 | 1984 | 1 |
| free | 8 | 5536 | 185.0 | 17.8 | 329 | 1984 | 1 |
| free | 16 | 6594 | 155.3 | 52.6 | 919 | 1984 | 1 |
| free | 32 | 8477 | 120.8 | 155.0 | 2515 | 1989 | 1 |

## vs serialized baseline (swarm-bench-baseline-b211a5def.json, same K/F)

| mode | N | baseline wall ms | now wall ms | baseline turns lost (void) | now | baseline max worker share | now |
|---|---|---|---|---|---|---|---|
| epoch | 1 | 4348 | 5772 | 7 | 0 | - | - |
| epoch | 8 | 18114 | 24520 | 95 | 0 | - | - |
| epoch | 32 | 6159 | 10838 | 43 | 0 | - | - |
| free | 1 | 3066 | 4229 | 0 | 0 | 1024 | 1024 |
| free | 8 | 3088 | 5536 | 1 | 0 | 1024 | 159 |
| free | 32 | 3105 | 8477 | 0 | 0 | 1024 | 36 |

## concurrent per-worker policy rebind (free mode, each worker rebinds its own pol-<w> every 4 turns)

| N | rebinds | fail | stale reads | mean rebind ms | max rebind ms | wall ms | dup merges | accepted |
|---|---|---|---|---|---|---|---|---|
| 1 | 495 | 0 | 0 | 4.11 | 10 | 6398 | 0 | 1 |
| 2 | 494 | 0 | 0 | 4.86 | 21 | 7423 | 0 | 1 |
| 4 | 492 | 0 | 0 | 3.5 | 9 | 9204 | 0 | 1 |
| 8 | 491 | 0 | 0 | 4.53 | 12 | 13276 | 0 | 1 |
| 16 | 480 | 0 | 0 | 5.92 | 23 | 17782 | 0 | 1 |
| 32 | 480 | 0 | 0 | 8.31 | 25 | 27171 | 0 | 1 |

## worker failure (worker 0 raises while holding a claim) and cooperative cancel

| N | fail: join errors | claims stolen (lease) | done | accepted | wall ms | cancel: stop->last exit ms | done at stop | claims left | partial results valid |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | 0 | 0 | 0 | 215 | 0 | 76 | 0 | 1 |
| 2 | 1 | 1 | 1024 | 1 | 4207 | 1 | 64 | 2 | 1 |
| 4 | 1 | 1 | 1024 | 1 | 5395 | 1 | 63 | 0 | 1 |
| 8 | 1 | 1 | 1024 | 1 | 5528 | 1 | 4 | 4 | 1 |
| 16 | 1 | 1 | 1024 | 1 | 6193 | 3 | 0 | 16 | 1 |
| 32 | 1 | 1 | 1024 | 1 | 8199 | 3 | 0 | 32 | 1 |

## micro

board: {'appends': 20000, 'append-ms': 311, 'grep-ms': 55, 'grep-hits': 542, 'new100-ms': 0}

channel: {'msgs': 20000, 'send-ms': 29, 'recv-ms': 35}

| N fibers | spawn ms | join ms | join void | peak RSS MB | RSS over idle MB |
|---|---|---|---|---|---|
| 1 | 0 | 0 | 0 | 108.9 | 0.6 |
| 2 | 0 | 1 | 0 | 107.9 | -0.4 |
| 4 | 0 | 1 | 0 | 108.7 | 0.3 |
| 8 | 0 | 1 | 0 | 109.1 | 0.8 |
| 16 | 0 | 2 | 0 | 109.4 | 1.1 |
| 32 | 1 | 2 | 0 | 109.6 | 1.3 |
