#!/usr/bin/env bash
# Everything behind the README numbers: acceptance, scope guard, latency, 4-mode bench, noise ablation,
# worldline-mode check, parallel-replay gate timing. Outputs under runs/ (results/ holds the committed copies).
#   AURA_BIN=~/aura/build-rel/aura scripts/bench.sh --docker
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
: "${AURA_BIN:?set AURA_BIN to an Aura build-rel/aura}"
run() { if [ "${DOCKER_MODE:-0}" = 1 ]; then scripts/in-docker.sh "$*"; else bash -c "$*"; fi; }
if [ "${1:-}" = "--docker" ]; then DOCKER_MODE=1; shift; fi
export AURA_SANDBOX=off AURA_PIPELINE_STRICT=0   # aura soft refuses mutate:rebind: cybrid-systems/aura#4609
SEEDS="${SEEDS:-0 1 2 3 4}"; JOBS="${JOBS:-3}"
mkdir -p runs
echo "== acceptance";       run "python3 -m aura_harness acceptance" | tee runs/acceptance.txt
echo "== scope guard";      run "python3 -m aura_harness guard" | tee runs/guard.txt
echo "== latency";          run "python3 -m aura_harness latency --n 20" | tee runs/latency.json
echo "== bench";            run "python3 -m aura_harness bench --seeds $SEEDS --jobs $JOBS --out runs/bench --title 'clean diagnoses'"
echo "== noise 0.3";        run "python3 -m aura_harness bench --seeds $SEEDS --jobs $JOBS --noise 0.3 --modes aura-gated aura-nogate --out runs/noise30 --title 'noise 0.3'"
echo "== noise 1.0";        run "python3 -m aura_harness bench --seeds $SEEDS --jobs $JOBS --noise 1.0 --modes aura-gated aura-nogate --out runs/noise100 --title 'noise 1.0'"
echo "== snapshot worldlines"; run "python3 -m aura_harness bench --seeds $SEEDS --jobs $JOBS --modes aura-gated --worldlines snap --out runs/snap --title 'snapshot worldlines'"
echo "== parallel replay";  run "python3 scripts/parallel_replay.py" | tee runs/parallel.txt
echo DONE
