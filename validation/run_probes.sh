#!/usr/bin/env bash
# Aura 原语探针：每个 probes/*.aura 在 dev 镜像里跑一次，打印最后几行判定 + RSS / 耗时
#   AURA_BIN=... validation/run_probes.sh [probe...]
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
ps=("$@"); [ ${#ps[@]} -eq 0 ] && ps=(validation/probes/*.aura)
for p in "${ps[@]}"; do
  echo "== $p"
  scripts/in-docker.sh "PROBE_TIMEOUT=${PROBE_TIMEOUT:-300} PROBE_TAIL=${PROBE_TAIL:-6} python3 validation/runone.py $p"
done
