# openpilot Wi-Fi validation

External qualification for the `wifi-wpa-supplicant` branch of `andiradulescu/openpilot`. The small regression and file-backed integration tests live with openpilot; this repository owns the disposable-VM setup and virtual-radio scenarios.

The runner takes an existing checkout and a full SHA. It does not checkout, patch, commit, or push openpilot. Dirty checkouts are rejected unless `--allow-dirty` is explicitly supplied; those results are development evidence, not a clean-commit signoff.

## Run the in-tree tests

Prepare openpilot's normal Python environment, then run:

```sh
python3 run.py --checkout /workspace/openpilot --sha <full-commit-sha> --suite unit
```

This uses openpilot's `tools/test_runner.py`, not pytest, and requires no virtual radios or root privileges. It covers the checked-out Wi-Fi unit tests and the in-tree integration tests when present in that revision.

## Run real Linux Wi-Fi services

**Use a disposable Linux VM, never a comma device or a workstation with Wi-Fi radios.** The hwsim runner loads a kernel module and isolates runtime files, profiles, resolver state, and network namespaces. It requires root, `CAP_SYS_MODULE`, and `mac80211_hwsim` for the running kernel.

On Ubuntu, install `iproute2 iw kmod util-linux hostapd wpasupplicant udhcpc dnsmasq-base network-manager netplan.io dbus iptables curl`. Also install the matching kernel modules package when `modinfo mac80211_hwsim` fails. `/etc/udhcpc/default.script` and the `netdev` group must exist.

Install the external runner's dependency into the test environment without changing openpilot's dependency files:

```sh
uv pip install --python /workspace/openpilot/.venv/bin/python -r requirements.txt
sudo env PATH="$PATH" WIFI_E2E_VM=1 python3 run.py \
  --checkout /workspace/openpilot --sha <full-commit-sha> --suite hwsim --filter forget
```

Remove `--filter forget` for the full matrix. The checkout and this repository must be outside `/tmp`, `/run`, and `/data`, which are isolated by the runner.

The lab uses real `wpa_supplicant`, `hostapd`, DHCP, DNS, firewall rules, NetworkManager profile reading, and HTTP probes. A veth link represents the alternate cellular route; it is not a modem test. It calls `WifiManager` through a separate process rather than clicking on the graphical UI. See the [kernel's hwsim documentation](https://wireless.docs.kernel.org/en/latest/en/users/drivers/mac80211_hwsim.html).

The hwsim suite is still a prototype. It has been collected and its prerequisite guards exercised, but it has not completed a virtual-radio run. The current Sprite lacks `mac80211_hwsim`; a blocked run is not a passing suite.

## Results

Each run writes `results/<run>/manifest.json` and `run.log`. The manifest records the openpilot SHA and dirty state, harness SHA and source hashes, tool versions, command, and exit status. hwsim also writes JUnit and per-service logs. A prerequisite failure is `blocked`, never `passed`.

Keep results with both revisions; a PR number alone does not identify the tested code. Logs use synthetic lab profiles. Do not attach real device credentials or private logs.

## Acceptance boundaries

The virtual-radio matrix covers connection and credential retry, saved-network switching, forget and profile regeneration, metering, station/AP transitions, hotspot password changes, forwarding, and service/UI-process recovery. The tests intentionally keep unmet requirements failing.

v3 hands `wlan0` to `wpa_supplicant` once per boot and never hands it back; the hand-back test performs the rollback procedure itself.

A regression that reports a refused deletion honestly does **not** establish that runtime-only or Netplan-backed profiles can be deleted. Persistent-source support still needs validation against the actual device layout. Likewise, a unit pass does not establish DHCP, RF, firmware, actual LTE, reboot, or NetworkManager rollback behavior on comma hardware.

For each defect found here, put the smallest faithful regression next to its fix in openpilot. Keep VM infrastructure changes here instead of adding them to the implementation PR. Do not request automated PR reviews or push fixes from this runner.
