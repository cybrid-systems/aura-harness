"""Gate wall time with candidate replays run sequentially vs in a 4-process pool (same verdicts expected)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aura_harness.agent import run_stream  # noqa: E402

out = {}
for jobs in (1, 4):
    r = run_stream("aura-gated", 0, jobs=jobs)
    out[jobs] = r
    print(f"jobs={jobs} gate p50={r['gate']['p50_ms']} ms p99={r['gate']['p99_ms']} ms wall={r['wall_s']} s "
          f"success={r['success']:.3f}")
same = [(v["verdict"], v["chosen"]) for v in out[1]["verdicts"]] == [(v["verdict"], v["chosen"]) for v in out[4]["verdicts"]]
print("same verdicts:", same)
