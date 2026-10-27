# swarm vs supervisor bench

K=1024 subtasks, F=64 families, bin=/workspace/rv/bin-main235/build-rel/aura. Same toy task (aura/swarm.aura); swarm = free mode (N self-organizing workers), supervisor = 1 planner fiber + N stateless workers (aura/supervisor.aura). Single runs, wall-clock ms; no speedup claim (Aura fibers interleave on one evaluator, see aura#4707).

## correctness, throughput, latency

| N | mode | done / K | lost | dup merges | accepted | wall ms | tasks/s | mean latency ms | max latency ms | evals | worker turns / jobs |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | swarm | 1024 / 1024 | 0 | 0 | 1 | 4717 | 217.1 | 1.25 | 221 | 63808 | 1984 |
| 1 | supervisor | 1024 / 1024 | 0 | 0 | 1 | 1288 | 795.0 | 21.57 | 31 | 63808 | 1024 |
| 2 | swarm | 1024 / 1024 | 0 | 0 | 1 | 5842 | 175.3 | 3.32 | 84 | 63808 | 1984 |
| 2 | supervisor | 1024 / 1024 | 0 | 0 | 1 | 1266 | 808.8 | 22.31 | 27 | 63808 | 1024 |
| 4 | swarm | 1024 / 1024 | 0 | 0 | 1 | 5797 | 176.6 | 7.74 | 128 | 63808 | 1984 |
| 4 | supervisor | 1024 / 1024 | 0 | 0 | 1 | 1290 | 793.8 | 25.03 | 29 | 63808 | 1024 |
| 8 | swarm | 1024 / 1024 | 0 | 0 | 1 | 5793 | 176.8 | 18.7 | 350 | 63808 | 1984 |
| 8 | supervisor | 1024 / 1024 | 0 | 0 | 1 | 1087 | 942.0 | 24.83 | 29 | 63808 | 1024 |
| 16 | swarm | 1024 / 1024 | 0 | 0 | 1 | 7043 | 145.4 | 55.62 | 915 | 63808 | 1984 |
| 16 | supervisor | 1024 / 1024 | 0 | 0 | 1 | 1142 | 896.7 | 34.44 | 39 | 63808 | 1024 |

## ask/reply round trip (supervisor)

Job RTT = dispatch on the worker inbox channel -> result back on the supervisor channel (includes the window scan). Ping = empty request/reply over the same channels, one outstanding at a time.

| N | job RTT mean ms | job RTT max ms | jobs | ping mean ms | ping max ms | pings |
|---|---|---|---|---|---|---|
| 1 | 2.22 | 7 | 1024 | 0.2 | 1 | 50 |
| 2 | 4.39 | 8 | 1024 | 0.27 | 1 | 100 |
| 4 | 8.99 | 13 | 1024 | 0.45 | 2 | 200 |
| 8 | 15.08 | 18 | 1024 | 0.62 | 2 | 400 |
| 16 | 31.73 | 37 | 1024 | 0.78 | 4 | 800 |

orch:agent-ask to an in-process responder (timeout 500 ms): status=timeout, elapsed 5000 ms, responder agent-reply status=unknown-corr (aura#4722).

## worker failure (worker 0 raises holding work) and cooperative cancel

| N | mode | join errors | recovered via | done | accepted | wall ms | cancel: stop->last exit ms | done at stop | partial valid |
|---|---|---|---|---|---|---|---|---|---|
| 1 | swarm | 1 | 0 lease steals | 0 | 0 | 211 | 0 | 63 | 1 |
| 1 | supervisor | 1 | 2 re-dispatched jobs | 0 | 0 | 210 | 1 | 224 | 1 |
| 2 | swarm | 1 | 1 lease steals | 1024 | 1 | 4632 | 1 | 60 | 1 |
| 2 | supervisor | 1 | 2 re-dispatched jobs | 1024 | 1 | 1198 | 0 | 240 | 1 |
| 4 | swarm | 1 | 1 lease steals | 1024 | 1 | 5616 | 1 | 56 | 1 |
| 4 | supervisor | 1 | 2 re-dispatched jobs | 1024 | 1 | 1165 | 2 | 256 | 1 |
| 8 | swarm | 1 | 1 lease steals | 1024 | 1 | 5466 | 1 | 14 | 1 |
| 8 | supervisor | 1 | 2 re-dispatched jobs | 1024 | 1 | 1148 | 1 | 256 | 1 |
| 16 | swarm | 1 | 1 lease steals | 1024 | 1 | 6584 | 3 | 0 | 1 |
| 16 | supervisor | 1 | 2 re-dispatched jobs | 1024 | 1 | 1045 | 0 | 272 | 1 |

## Aura orch:* primitives at N

supervise-batch: N tasks, task 0 raises, policy collect-all :max-retries 1. scope-cancel-all: N orch:scope-spawn bodies looping on fiber:yield; cancel, yield 2000 times, count body steps, then scope-join-all :timeout-ms 1000; then set the cooperative stop flag and join again.

| N | supervise-batch default watch: status ok/err ran | :watch-scope #f: status ok/err ran | cancel-all cancelled | body steps after cancel | join-all(1000ms) status / ms | after stop flag: status / ms |
|---|---|---|---|---|---|---|
| 1 | ok 0/0 ran 0 | partial 0/1 ran 0 | 1 | 0 | timeout / 3001 | ok / 0 |
| 2 | ok 0/0 ran 0 | partial 1/1 ran 1 | 2 | 0 | timeout / 3002 | ok / 2 |
| 4 | ok 0/0 ran 0 | partial 3/1 ran 3 | 4 | 0 | timeout / 3001 | ok / 2 |
| 8 | ok 0/0 ran 0 | partial 7/1 ran 7 | 8 | 0 | timeout / 3002 | ok / 4 |
| 16 | ok 0/0 ran 0 | partial 15/1 ran 15 | 16 | 0 | timeout / 3002 | ok / 5 |
