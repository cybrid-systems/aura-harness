# swarm vs supervisor bench on Aura d54b2117d

K=1024, F=64, 2 runs per cell, timeout 150 s, host-mode Release build, 8 vCPU. Leases need both the tick bound and 100 ms of wall time (`aura/swarm.aura`). Same calls as `scripts/sv_bench.py`: `run("free", N, 1024, 64, 20000)` and `run_supervisor(N, 1024, 64, 2000000)`. Previous: `sv-bench-e6f4169e0.md`.

| N | mode | accepted / runs | done | tasks/s (per run) | workers dead | lost / dup merges | peak RSS |
|---|---|---|---|---|---|---|---|
| 1 | swarm | 2/2 | 1024, 1024 | 157.5, 158.0 | 0, 0 | – | 149 MB |
| 1 | supervisor | 2/2 | 1024, 1024 | 734.1, 835.9 | 0, 0 | 0/0, 0/0 | 154 MB |
| 2 | swarm | 2/2 | 1024, 1024 | 138.3, 139.5 | 0, 0 | – | 166 MB |
| 2 | supervisor | 2/2 | 1024, 1024 | 918.4, 948.1 | 0, 0 | 0/0, 0/0 | 141 MB |
| 4 | swarm | 2/2 | 1024, 1024 | 106.2, 108.2 | 0, 0 | – | 200 MB |
| 4 | supervisor | 2/2 | 1024, 1024 | 696.6, 660.2 | 0, 0 | 0/0, 0/0 | 142 MB |
| 8 | swarm | 2/2 | 1024, 1024 | 98.6, 101.5 | 0, 0 | – | 242 MB |
| 8 | supervisor | 2/2 | 1024, 1024 | 467.4, 472.1 | 0, 0 | 0/0, 0/0 | 146 MB |
| 16 | swarm | 2/2 | 1024, 1024 | 78.4, 78.0 | 0, 0 | – | 356 MB |
| 16 | supervisor | 2/2 | 1024, 1024 | 299.5, 278.0 | 0, 0 | 0/0, 0/0 | 160 MB |
