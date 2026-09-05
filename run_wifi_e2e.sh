#!/usr/bin/env bash
set -euo pipefail

lab_root="$(cd "$(dirname "$0")" && pwd)"
root="${OPENPILOT_ROOT:?set OPENPILOT_ROOT to the checkout under test}"
cd "$root"
python="${WIFI_E2E_PYTHON:-$root/.venv/bin/python}"

if [[ "${1:-}" != --isolated ]]; then
  [[ "${WIFI_E2E_VM:-}" == 1 && "$EUID" == 0 ]] || {
    echo 'Run with WIFI_E2E_VM=1 as root in a disposable Linux VM, never on a comma device.' >&2
    exit 77
  }
  [[ ! -e /AGNOS ]] || { echo "Refusing to run on a comma device." >&2; exit 77; }
  case "$root/:$lab_root/" in /tmp/*|/run/*|/data/*|*:/tmp/*|*:/run/*|*:/data/*)
    echo 'The checkout must be outside /tmp, /run, and /data, which this test isolates.' >&2; exit 77 ;;
  esac
  [[ ! -d /sys/module/mac80211_hwsim ]] || { echo 'hwsim is already in use.' >&2; exit 77; }
  [[ -z "$(find /sys/class/ieee80211 -mindepth 1 -maxdepth 1 2>/dev/null)" ]] || {
    echo 'Refusing to run on a host with existing Wi-Fi radios.' >&2; exit 77
  }
  for cmd in ip iw modprobe unshare mount hostapd wpa_supplicant wpa_cli udhcpc dnsmasq dbus-daemon NetworkManager nmcli curl netplan; do
    command -v "$cmd" >/dev/null || { echo "Missing prerequisite: $cmd" >&2; exit 77; }
  done
  [[ -x "$python" && -x /etc/udhcpc/default.script ]] || {
    echo 'The project Python and /etc/udhcpc/default.script are required.' >&2; exit 77
  }
  "$python" -c 'import pytest' || { echo "Install requirements.txt first." >&2; exit 77; }
  modinfo mac80211_hwsim >/dev/null 2>&1 || { echo "Missing kernel module: mac80211_hwsim" >&2; exit 77; }
  modprobe mac80211_hwsim radios=4 || { echo "Cannot load mac80211_hwsim" >&2; exit 77; }
  trap 'modprobe -r mac80211_hwsim' EXIT
  export WIFI_E2E_OUTER_MNT="$(readlink /proc/self/ns/mnt)"
  unshare --mount --pid --fork --mount-proc --kill-child "$0" --isolated "$@"
  exit $?
fi
[[ "$EUID" == 0 && "${WIFI_E2E_VM:-}" == 1 && -n "${WIFI_E2E_OUTER_MNT:-}" &&
   "$(readlink /proc/self/ns/mnt)" != "$WIFI_E2E_OUTER_MNT" ]] || {
  echo '--isolated must only be entered through the namespace runner.' >&2; exit 77
}
shift
mount --make-rprivate /
for dir in /run /tmp /data /etc/NetworkManager /etc/netplan /etc/netns /var/lib/NetworkManager /var/lib/misc; do
  mkdir -p "$dir"
  mount -t tmpfs tmpfs "$dir"
done
mkdir -p /run/dbus /data/etc/NetworkManager/system-connections /etc/NetworkManager/system-connections
mount --bind /data/etc/NetworkManager/system-connections /etc/NetworkManager/system-connections
# Each ip-netns exec also receives its own resolver file from /etc/netns/<name>.
resolv_target="$(readlink -m /etc/resolv.conf)"
mkdir -p "$(dirname "$resolv_target")"
touch "$resolv_target" /tmp/resolv.conf
mount --bind /tmp/resolv.conf "$resolv_target"
if [[ -f /etc/dnsmasq.conf ]]; then
  touch /tmp/dnsmasq.conf
  mount --bind /tmp/dnsmasq.conf /etc/dnsmasq.conf
fi
if [[ -d /etc/dnsmasq.d ]]; then mount -t tmpfs tmpfs /etc/dnsmasq.d; fi
touch /run/wifi-e2e-isolated
export WIFI_E2E=1 PYTHONPATH="$root" RAYLIB_BACKEND=headless
exec "$python" -m pytest -o addopts='' -vv -s "$lab_root/test_wifi_e2e.py" "$@"
