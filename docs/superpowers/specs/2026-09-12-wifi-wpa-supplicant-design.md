# openpilot Wi-Fi without NetworkManager, v3 design

Date: 2026-09-12
Target: commaai/openpilot issue #37752. Supersedes upstream PR #38330 and fork PR andiradulescu/openpilot#26.
Branch: `wifi-wpa-supplicant` in `/Volumes/Stuff/openpilot-wifi-v3`, based on comma/master `0cf294d85`.
Repository layout note: the openpilot tree is nested, so paths below are relative to `openpilot/` inside the checkout.

## Goal

Replace the D-Bus/jeepney/NetworkManager Wi-Fi path in `system/ui/lib/wifi_manager.py` with direct control of
`wpa_supplicant`, `udhcpc` and `dnsmasq`, keeping the public `WifiManager` contract identical so no UI, setup or
updater code changes. Ship the smallest diff that makes every UI-reachable Wi-Fi and tethering path work, roughly the
size of Adeeb's reference PR #37662 (+1264/-1592). Paths not reachable from the UI are not implemented.

## Non-goals

- Removing NetworkManager from AGNOS. It keeps managing eth0 and is left running.
- Handing wlan0 back to NetworkManager without a reboot.
- A separate Wi-Fi daemon or RPC layer. Cellular already lives in `common/hardware/comma/modem.py`; Wi-Fi stays in the
  UI process because setup and the updater run without manager.
- Migrating or rewriting saved profiles in bulk.
- New UI callbacks or dialogs (the `forget_failed` callback from PR #26 is dropped).
- Changes to `hardware.py`. It already reads the supplicant socket at `/run/wpa_supplicant/wlan0` and `metered=` from
  keyfiles by SSID; v3 keeps both conventions so it works unchanged.

## Production facts the design depends on

Verified on a comma three running AGNOS 19.6 (kernel 4.9.103) and on the April 2026 stock-device dump:

- wpa_supplicant 2.10 runs as a system service `-u -s -O DIR=/run/wpa_supplicant GROUP=netdev`. The directory is
  root:netdev 750; the `comma` user is in `netdev`, `root` and `sudo`, and sudo is passwordless.
- BusyBox 1.36.1 `udhcpc` with `/etc/udhcpc/default.script`. That script sets the address, adds the default route at
  metric 0, and pushes DNS to systemd-resolved through the `/sbin/resolvconf` shim. `/etc/resolv.conf` is the resolved
  stub.
- dnsmasq 2.90 and hostapd 2.10 are installed with their services disabled. NetworkManager implements the hotspot as a
  wpa_supplicant `mode=2` network on this hardware, so AP mode in the supplicant is proven on the device.
- `iptables` 1.8.10 is the nf_tables variant and fails on this kernel. `iptables-legacy` works.
- NetworkManager 1.46 is netplan-patched. Every profile saved by today's openpilot, including the Hotspot, is a YAML at
  `/data/etc/netplan/90-NM-<uuid>.yaml` plus a keyfile regenerated at boot at
  `/run/NetworkManager/system-connections/netplan-NM-<uuid>[-<ssid>].nmconnection`. Persistent keyfiles live in
  `/data/etc/NetworkManager/system-connections` (root, mode 600) behind the `/etc/NetworkManager/system-connections`
  symlink. NetworkManager reads both locations.
- Keyfile SSIDs are either a literal string or a `byte;byte;...;` list.
- Default route metrics today: eth0 100, wlan0 600, ppp0 1000 (set by `modem.py`).
- `jeepney` is already listed under "these should be removed" in `pyproject.toml`.

## Public contract (unchanged)

Consumers: `system/ui/widgets/network.py`, `selfdrive/ui/mici/layouts/settings/network/{network_layout,wifi_ui}.py`,
`selfdrive/ui/layouts/settings/settings.py`, `system/ui/{tici_setup,mici_setup,tici_updater}.py`, the validation
harness. They use exactly:

- Types: `Network(ssid, strength, security_type, is_tethering)`, `SecurityType`, `MeteredType`, `ConnectStatus`,
  `WifiState(ssid, status)`, `normalize_ssid()`.
- Mutations: `set_active`, `connect_to_network(ssid, password, hidden=False)`, `activate_connection(ssid, block=False)`,
  `forget_connection(ssid, block=False)`, `set_current_network_metered`, `set_tethering_active`,
  `set_tethering_password`, `set_ipv4_forward`, `process_callbacks`, `stop`.
- Reads: `networks` (sorted: current, then saved, then strength, then name), `wifi_state`, `ipv4_address`,
  `current_network_metered`, `connecting_to_ssid`, `connected_ssid`, `tethering_password`, `is_tethering_active()`,
  `is_connection_saved(ssid)`.
- Callbacks via `add_callbacks`: `need_auth(ssid)`, `activated()`, `forgotten(ssid)`, `networks_updated(networks)`,
  `disconnected()`. Callbacks are queued and run from `process_callbacks()` on the UI thread, as today.

## Files

| Path | Change |
| --- | --- |
| `system/ui/lib/wifi_manager.py` | Rewritten. Target about 600 lines. |
| `system/ui/lib/wpa_supplicant.conf` | New, static: `ctrl_interface=DIR=/run/wpa_supplicant GROUP=netdev` and `update_config=0`. No secrets. |
| `system/ui/lib/udhcpc.script` | New, executable. Runs `/etc/udhcpc/default.script "$1"`, then on `bound`/`renew` replaces the wlan0 default route with metric 600. |
| `system/ui/lib/tests/test_wifi_manager.py` | New. Replaces `test_handle_state_change.py`. |
| `system/ui/lib/networkmanager.py` | Deleted. |
| `system/ui/lib/tests/test_handle_state_change.py` | Deleted. |
| `pyproject.toml`, `uv.lock` | Remove `jeepney`. |

Nothing else changes. `launch_chffrplus.sh` keeps its `.nmmeta` cleanup.

## Process ownership and lifecycle

Constants: `WPA_CTRL_DIR = /run/wpa_supplicant`, socket `/run/wpa_supplicant/wlan0`,
`WPA_PID = /run/wpa_supplicant/wlan0.pid`, `UDHCPC_PID = /run/udhcpc.wlan0.pid`, `DNSMASQ_PID = /run/dnsmasq.wlan0.pid`.
Root-owned processes are started with `sudo`, `start_new_session=True`, and stdio to `DEVNULL`, the same way `modem.py`
starts pppd. Pidfiles are written by the daemons themselves (`-P` / `-p` / `--pid-file`).

Init runs in a background thread, as upstream does:

1. If `WPA_PID` names a live process, adopt it: open the control socket, `STATUS`, and derive state. `mode=AP` means
   tethering is active; `wpa_state=COMPLETED` means connected to `ssid`; the associating states mean connecting.
   If connected and udhcpc is alive, send it `SIGUSR1` (renew). If connected and udhcpc is dead, start it. If tethering
   and dnsmasq is dead or the NAT rule is missing, start or add them.
2. Otherwise take the interface: `sudo nmcli dev set wlan0 managed no` (best effort, `check=False`, so a future AGNOS
   without NetworkManager still works), wait up to 5 seconds for NetworkManager's `/run/wpa_supplicant/wlan0` socket
   to disappear, then `sudo wpa_supplicant -B -i wlan0 -D nl80211 -c <repo conf> -P WPA_PID`, open the control socket,
   and load every saved station profile into the daemon over the socket. Then start udhcpc.
3. Ensure a Hotspot profile exists (create the keyfile with the upstream defaults when none has `mode=ap`), read the
   tethering password, and start the scan and monitor threads.

`stop()` sets the exit flag, joins the threads and closes both sockets. It never signals a daemon. A dead or restarted
UI leaves station or hotspot networking running; the next `WifiManager` adopts it through step 1.

One udhcpc runs for the life of the supplicant: `sudo udhcpc -i wlan0 -f -R -s <repo script> -p UDHCPC_PID`. On
every CONNECTED event the manager sends `SIGUSR1` so a new network gets a fresh lease immediately. Nothing is sent on
DISCONNECTED, so a reconnect to the same AP while the UI is dead keeps its valid lease, and a UI restart renews.
Tethering start kills udhcpc; tethering stop restarts it.

## Storage

Profiles are NetworkManager keyfiles parsed with `configparser`. Reads use `sudo_read` from `common/utils.py`.
Writes go through `sudo install -m 600` of a temp file. Both directories are scanned:
`/data/etc/NetworkManager/system-connections` (persistent) and `/run/NetworkManager/system-connections`
(netplan-generated at boot). A profile is `type=wifi` with an SSID, a `uuid`, optional `psk`, `hidden`, `metered`, and
`mode`. `mode=ap` is the hotspot. Profiles without `uuid` or `ssid` are ignored with a warning.

Identity for UI purposes is the SSID, as upstream. A saved network is any profile with that SSID.

- Save: a new station network is written only on its first successful CONNECTED, as upstream persisted on ACTIVATED,
  so wrong passwords never land on disk. The file is `<quoted ssid>.nmconnection` using `urllib.parse.quote(ssid,
  safe="")`, with the same sections upstream produced through D-Bus: `[connection] id="openpilot connection <ssid>"
  uuid type=wifi autoconnect-retries=0`, `[wifi] ssid mode=infrastructure hidden`, `[wifi-security] key-mgmt=wpa-psk
  psk` when a password exists, `[ipv4] method=auto dns-priority=600`, `[ipv6] method=ignore`.
- Forget: for every profile with that SSID, remove its keyfile; if the file name starts with `netplan-NM-`, also remove
  `/data/etc/netplan/90-NM-<uuid>.yaml`. Remove the matching supplicant networks. Fire `forgotten(ssid)` in every case,
  as upstream did, and log any removal failure with `cloudlog.exception`.
- Edit (metering, hotspot password): rewrite the profile as a persistent keyfile with the changed key and remove any
  other sources for that UUID (runtime copy and YAML). Netplan-origin profiles therefore become persistent keyfiles on
  first edit. This reuses forget and save rather than adding a third write path.
- Hotspot: SSID `weedle-<dongle prefix>` and password `swagswagcomma` by default. `tethering_password` reads the psk.
  `set_tethering_password` edits the profile and restarts tethering when active.
- Metering: `set_current_network_metered` edits the connected profile. `current_network_metered` is read from the
  connected profile on every status refresh. This is exactly what `hardware.py` reads for `deviceState`.

## Supplicant control

A small client in the same module (about 80 lines): one datagram socket for commands with request/reply, one attached
socket for events, `decode_ssid()` for wpa_supplicant's printf-style escapes (`\xNN`, `\\`, `\"`, `\e`, `\n`, `\r`,
`\t`), and `parse_scan_results()`. SSIDs are sent to the supplicant as hex (`SET_NETWORK n ssid <hex>`) so no
quoting rules apply. PSKs are sent quoted, with `"` and `\` escaped.

Loading a saved station profile: `ADD_NETWORK`, `SET_NETWORK n ssid <hex>`, `SET_NETWORK n psk "<psk>"` or
`SET_NETWORK n key_mgmt NONE`, `SET_NETWORK n scan_ssid 1` when hidden, `ENABLE_NETWORK n`. The manager keeps an
`id -> ssid` map, rebuilt from `LIST_NETWORKS` when adopting.

## Station flow

`connect_to_network(ssid, password, hidden)` sets `WifiState(ssid, CONNECTING)`, forgets any existing profile for the
SSID (upstream behaviour), adds the network, remembers it as pending, and `SELECT_NETWORK`s it. `activate_connection`
sets CONNECTING and `SELECT_NETWORK`s the saved network's id. `SELECT_NETWORK` disables the others, so every terminal
event ends with `ENABLE_NETWORK all` to restore autoconnect.

`ConnectStatus.CONNECTED` means the station has an IPv4 address, which is what NetworkManager's ACTIVATED meant and
what setup uses to decide the device is online. A completed WPA handshake without an address is still CONNECTING.
The manager remembers the SSID the user selected until a terminal outcome, so status refreshes never clear a
selection that the supplicant has not acted on yet. This replaces upstream's epoch counter.

The monitor thread handles:

- `CTRL-EVENT-CONNECTED`: renew or start udhcpc, `ENABLE_NETWORK all`, then poll `STATUS` every 0.5 s for
  `ip_address=`. On an address: set `WifiState(ssid, CONNECTED)`, write the pending profile if it matches, refresh
  metering, queue `activated`. If the association drops during the wait, return and let the next event decide. After
  `DHCP_TIMEOUT_SECONDS = 45` (NetworkManager's `ipv4.dhcp-timeout` default) without an address: `DISABLE_NETWORK`
  that id so the supplicant stops looping on it, set DISCONNECTED, queue `disconnected`.
- `CTRL-EVENT-SSID-TEMP-DISABLED ... reason=WRONG_KEY` for the SSID in the current state: `REMOVE_NETWORK` it so the
  supplicant stops retrying and the UI is asked once, set DISCONNECTED, `ENABLE_NETWORK all`, queue `need_auth(ssid)`.
  A saved profile stays on disk; activating it later re-adds the network from the profile.
- `CTRL-EVENT-DISCONNECTED`: refresh from `STATUS`. If the state was CONNECTED and no selection is pending, set
  DISCONNECTED, clear IP and metering, queue `disconnected`. While a selection is pending the supplicant keeps
  retrying, so state is kept, matching upstream's open TODO for SSID-not-found.
- `CTRL-EVENT-SCAN-RESULTS`: refresh networks.
- Receive timeout (every second): health check. If `PING` gets no `PONG`, run the start sequence again, which respawns
  a crashed supplicant and reloads saved networks. If the state is a station state and udhcpc is dead, start it.

The supplicant's own autoconnect to a saved network is picked up by the status refresh: the associating states map to
CONNECTING with the supplicant's SSID, so no "Trying to associate" text parsing is needed.

The scan thread issues `SCAN` every 5 seconds while active. `_update_networks` parses `SCAN_RESULTS`, keeps the
strongest BSS per SSID, converts dBm to percent with NetworkManager's formula (-40 dBm is 100 %, -100 dBm is 0 %),
maps flags to `SecurityType` (PSK is WPA, no WPA or WEP token is OPEN, anything else is UNSUPPORTED, matching
upstream's three outcomes), marks the hotspot SSID, then re-reads `STATUS` to self-heal state, IP (`ip_address=`) and
metering, and queues `networks_updated`. `set_active(True)` triggers an immediate refresh as upstream does.

Passphrases are never quoted on the control socket. A WPA passphrase is converted to the raw 256-bit PSK with
`hashlib.pbkdf2_hmac("sha1", passphrase, ssid, 4096, 32)` (IEEE 802.11i) and sent as 64 hex characters; a keyfile
`psk` that is already 64 hex characters is sent as is. The keyfile keeps the passphrase for NetworkManager rollback.

## Tethering

Start: set `WifiState(hotspot ssid, CONNECTING)`, kill udhcpc, add an AP network in the same supplicant
(`ssid <hex>`, `mode 2`, `frequency 2437`, `key_mgmt WPA-PSK`, `proto RSN`, `pairwise CCMP`, `psk "<psk>"`),
`SELECT_NETWORK` it, wait for `AP-ENABLED`, then `sudo ip addr flush dev wlan0`, `sudo ip addr add
192.168.43.1/24 dev wlan0`, `sudo dnsmasq --interface=wlan0 --bind-interfaces --except-interface=lo
--dhcp-range=192.168.43.2,192.168.43.254,24h --pid-file=DNSMASQ_PID`, `sudo iptables-legacy -t nat -A POSTROUTING
-s 192.168.43.0/24 ! -d 192.168.43.0/24 -j MASQUERADE -m comment --comment openpilot-tethering`, and
`sudo sysctl net.ipv4.ip_forward=<1 if the ipv4_forward flag else 0>`. Then `WifiState(hotspot ssid, CONNECTED)`,
`ipv4_address = 192.168.43.1`, queue `activated`. The NAT rule matches by source subnet, as NetworkManager's shared mode
does, so tethering survives the uplink changing between eth0 and ppp0.

Stop: kill dnsmasq by pidfile, delete the NAT rule, `REMOVE_NETWORK` the AP network, `ENABLE_NETWORK all`, flush the
address, restart udhcpc, set DISCONNECTED, queue `disconnected`. The supplicant then reconnects to saved networks on its
own and the normal CONNECTED path runs.

Adopt with `mode=AP`: state CONNECTED to the hotspot SSID, IP 192.168.43.1, dnsmasq and the NAT rule ensured
(`iptables-legacy -C` before `-A`).

`set_ipv4_forward(enabled)` stores the flag and, when tethering is active, applies the sysctl immediately. The prime
type can change while the hotspot is up, and the harness exercises that path.

## Error handling

Failures are visible in the local idiom: `cloudlog.warning` for expected misses (no supplicant reply, profile missing),
`cloudlog.exception` for unexpected ones, and every failed mutation resets state by re-reading `STATUS` so the UI never
sticks in CONNECTING. Subprocess calls that must succeed use `check=True` inside try blocks that log and reset;
best-effort teardown uses `check=False`. No swallowed exceptions without a log line.

## Tests in tree

`system/ui/lib/tests/test_wifi_manager.py`, `OpenpilotTestCase` with `Mocker`, run through
`tools/test_runner.py`. A fake supplicant lives in the test: a scripted command-to-reply map plus an `emit(event)` that
feeds the monitor thread. `subprocess.run` and `Popen` are patched to record argv, `os.kill` is patched, and profile
directories are temp dirs injected through module constants. The suite covers each UI-reachable flow once:

1. Fresh start: unmanage, wait for socket, spawn, load keyfile and netplan-origin profiles (literal and byte-list SSIDs,
   hidden, open), create the Hotspot keyfile, start udhcpc.
2. Adopt a connected station: state, IP, metering, udhcpc renewed, no spawn.
3. Adopt a hotspot: tethering active, IP 192.168.43.1, dnsmasq and NAT ensured.
4. Scan results: strongest per SSID, security mapping, hotspot flag, escape decoding, sort order.
5. Connect success: keyfile written with the expected sections, `activated`, `connected_ssid`, renew, enable all.
6. Wrong password: `need_auth`, nothing written, network removed, state DISCONNECTED.
7. Activate a saved network selects its id.
8. Forget a keyfile profile, a netplan-origin profile (YAML and runtime copy removed), and the connected network
   (state cleared, `forgotten` queued).
9. Metering on a keyfile profile and on a netplan-origin profile (migrated to persistent).
10. Tethering on and off: recorded commands, state, `activated` then `disconnected`; password change while active
    rewrites the profile and restarts.
11. Disconnected event clears state and queues `disconnected`.
12. `stop()` records no kill or teardown commands.

Target under 400 lines, table-driven with `SubTests` where cases differ only in data.

## External validation

In `andiradulescu/openpilot-wifi-validation` (this repository, branch `wifi-v3`):

- Adapt constants and assertions to v3: control dir `/run/wpa_supplicant`, pidfiles above, NAT comment
  `openpilot-tethering`, no `active_profile` file, metering asserted from the keyfile. The hand-back test drops the
  removed `restore_networkmanager` snippet and instead kills the v3 daemons and runs `nmcli dev set wlan0 managed yes`
  itself, which is the documented rollback procedure.
- Build a disposable QEMU Ubuntu 24.04 arm64 VM with `linux-modules-extra` for `mac80211_hwsim` (OrbStack's kernel
  lacks it). Run `--suite unit` and the full `--suite hwsim` matrix against the v3 SHA; record manifests.
- Device pass on the comma three at 192.168.1.105 (currently on PR #26 code, so install v3, reboot, verify adoption,
  station, hotspot with a real client, UI kill survival, reboot autoconnect) and on a comma four for the LTE/ppp0
  priority and tethering over cellular. The comma four host is still to be named by Andi.
- Rollback: install comma/master, reboot, confirm NetworkManager connects to networks saved by v3.
- Bonus target: five connect-to-IP timings on a known WPA2 network against master.

## PR shape

One upstream PR from `wifi-wpa-supplicant`, two commits: the implementation with deletions and dependency removal, and
the test file. PR body: what changed, why, exact verification (unit run, hwsim manifest SHA, device runs, rollback),
benchmark table, and the rollback procedure. Close #38330 with a pointer. No history essays, no agent notices.
