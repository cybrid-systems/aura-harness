#!/usr/bin/env bash
# 一键复跑 validation/（需 AURA_BIN；在 CI 镜像里跑）。结果写到 validation/results/。
# 内存紧张的机器上一次只跑一个容器；每个 suite 失败（如 OOM）可单独重跑，不必从头来。
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
: "${AURA_BIN:?set AURA_BIN}"
for s in invariants safety repro faults "improve 0.0" "improve 0.3" "improve 1.0"; do
  scripts/in-docker.sh "python3 validation/rsi_validate.py $s" || echo "suite $s failed (rerun it alone)"
done
scripts/in-docker.sh "python3 validation/harm_forward.py; python3 validation/harm_stat.py; python3 validation/protocol_probe.py; python3 validation/audit_restart.py"
PROBE_TIMEOUT=900 PROBE_TAIL=8 validation/run_probes.sh validation/probes/*.aura > validation/results/probes-$(basename "$(dirname "$AURA_BIN")").txt
