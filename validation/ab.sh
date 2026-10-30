#!/usr/bin/env bash
# A/B：同一台机器同一时段，aura main 69d360068 vs 仓库 pin a6c63aa19 —— BENCH 延迟、longrun 600 步、p7b/p7d 增长探针
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
for tag in main pin; do
  if [ $tag = main ]; then export AURA_BIN=/workspace/ahv-bin/aura; else export AURA_BIN=/workspace/ahv-bin-pin/aura; fi
  echo "##### $tag $AURA_BIN"
  scripts/in-docker.sh "uptime; python3 -m aura_harness latency | grep -E 'rt_ms|guarded_apply_us|trial_ws_us|rebind_eval_us' | head -12; python3 scripts/longrun.py --steps 600 --block 100 --out validation/results/longrun600-$tag.json | grep step"
  PROBE_TAIL=2 validation/run_probes.sh validation/probes/p7b*.aura validation/probes/p7d*.aura validation/probes/p1_*.aura validation/probes/p5b*.aura validation/probes/p6*.aura
done
