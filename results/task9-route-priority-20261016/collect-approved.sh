#!/bin/bash
set -euo pipefail
base=/tmp/wifi-route-priority-20261016-1620
harness="$base/harness-approved-20261018-1540"
cd "$base/source"
ln -sfn /workspace/openpilot/.venv .venv
date -u
pwd
sha256sum "$harness"/*.py "$harness"/*.sh "$harness/requirements.txt" \
  openpilot/system/ui/lib/udhcpc.script openpilot/system/ui/lib/wifi_manager.py \
  openpilot/system/ui/lib/tests/test_wifi_manager.py /etc/resolv.conf
ip -j -4 route show
ip -br link
ip netns list
test ! -d /sys/module/mac80211_hwsim
test ! -e /sys/class/net/c4routee
test ! -e /sys/class/net/c4routew
sudo tar --exclude=udev-data --exclude=__pycache__ -czf "$base/approved-hwsim-artifacts.tar.gz" \
  -C "$harness/task-results" focused full
sudo chmod 644 "$base/approved-hwsim-artifacts.tar.gz"
sha256sum "$base/approved-hwsim-artifacts.tar.gz"
