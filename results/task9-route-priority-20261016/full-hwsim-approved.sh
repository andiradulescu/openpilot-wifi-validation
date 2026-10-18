#!/bin/bash
set -euo pipefail
base=/tmp/wifi-route-priority-20261016-1620
exec sudo unshare -m --propagation private bash -s -- "$@" <<'ISOLATED'
set -euo pipefail
base=/tmp/wifi-route-priority-20261016-1620
phase="$1"
shift
case "$phase" in focused|full) ;; *) exit 64 ;; esac
harness="$base/harness-approved-20261018-1540"
mkdir -p "$harness/task-venv" "$harness/task-results/$phase"
mount --bind /workspace/openpilot/.venv "$harness/task-venv"
mount -o remount,bind,ro "$harness/task-venv"
mount --rbind "$harness" /workspace/openpilot-wifi-validation
for submodule in opendbc_repo msgq_repo panda rednose_repo teleoprtc_repo tinygrad_repo; do
  mount --bind "/workspace/openpilot/$submodule" "$base/source/$submodule"
  mount -o remount,bind,ro "$base/source/$submodule"
done
ln -sfn /workspace/openpilot-wifi-validation/task-venv "$base/source/.venv"
mount --rbind "$base/source" /workspace/openpilot
cd /workspace/openpilot
exec env WIFI_E2E_VM=1 OPENPILOT_ROOT=/workspace/openpilot \
  WIFI_E2E_LOG_DIR="/workspace/openpilot-wifi-validation/task-results/$phase" \
  bash /workspace/openpilot-wifi-validation/run_wifi_e2e.sh \
  --junitxml="/workspace/openpilot-wifi-validation/task-results/$phase/junit.xml" "$@"
ISOLATED
