# Hotspot lease-file correction validation

Date: 2026-09-26. This records local/QEMU validation and subsequent physical installation. Hotspot startup, client DHCP, and HTTPS browsing with mobile data disabled have passed on comma three.

## Revisions and scope

- Prior source HEAD: `2be8594264cb6de9e607dda4cd33fb4b875cf4f6`.
- Green intermediate commit: `6c81b5755` (`wifi: store hotspot leases in the runtime directory`).
- Final implementation commit: `52e2f700c45f735f8d718000de7a88b083d76673`.
- Final test commit: `6ca796e338a955e16fd6c63869ee4c19baa81d5b`.
- The squashed tree equals the intermediate tree, verified with `git diff --exit-code 6c81b5755 HEAD`.
- Source changes: explicit dnsmasq runtime lease-file argument; exact command assertion; synchronization of an existing recovery test with the manager lock. No assertions removed or relaxed.
- Diagnosis in `diagnosis.md` records the earlier read-only physical-device inspection, before this correction.

## Environment and provenance

Existing QEMU/HVF Ubuntu VM `wifi-e2e`, Linux `6.8.0-139-generic`; Python 3.12.13, Ruff 0.16.3, ty 0.0.72. Checkout `/workspace/openpilot`.

The launcher stopped at `hdiutil makehybrid`; QEMU was started directly using the existing disk, firmware and seed ISO from `/Users/andiradulescu/vms/wifi-e2e`. SSH forwarding was bound to `127.0.0.1:2222` instead of all host interfaces. A dedicated temporary known-hosts file was used for the locally verified QEMU listener; the existing localhost host-key entry was preserved.

Candidate files were copied to QEMU. Host and guest SHA-256 values matched:

- `openpilot/system/ui/lib/wifi_manager.py`: `edddf19581f031ae50634f5002a6cb2595e45d99f8d308c621000f2891d4b061`
- `openpilot/system/ui/lib/tests/test_wifi_manager.py`: `4e0bf9c6af22d06b28183407e41bc1c0d9f4df47a1b38b94fff1dcf4d95402f3`

Final commits were transferred using a local Git bundle, with no GitHub push. QEMU's files matched FETCH_HEAD before its detached checkout was aligned, and the final run used a clean checkout at `6ca796e338a955e16fd6c63869ee4c19baa81d5b`.

## Checks

All suite runs used `.venv/bin/python tools/test_runner.py openpilot/system/ui/lib/tests/test_wifi_manager.py -v` from the QEMU checkout root.

| Evidence | Result |
| --- | --- |
| `01-red.log` | 79 passed, 1 failed: missing lease-file argument in `test_tethering_on_then_off` |
| `02-recovery-race.log` | 79 passed, 1 failed: lease regression passes; existing recovery test observes CONNECTING before restart completes |
| `03-green-lint-hashes.log` | 80 passed, 0 failed; Ruff and ty passed; candidate hashes recorded |
| `04-squashed.log` | 80 passed, 0 failed on the final squashed source HEAD |

Lint commands: `.venv/bin/ruff check openpilot/system/ui/lib` and `.venv/bin/ty check openpilot/system/ui/lib/wifi_manager.py`. Host `git diff --check` passed.

## Deviations and limits

1. Approved spec/plan amendment: choose `/run/dnsmasq.wlan0.leases` because the tested device lacks `/var/lib/misc`.
2. Unexpected test failure: `test_fresh_supplicant_restart_clears_pending_hotspot_state` waited for fields cleared early in `_start_supplicant`, then asserted state before the restart's `_refresh_status`. The recovery path holds `_lock`; the test now acquires that lock before all five unchanged assertions. No production recovery behavior changed.
3. Restarted QEMU directly with its existing seed ISO after the launch script failed at ISO generation; restricted SSH forwarding to localhost and used a dedicated host-key file.

No physical hotspot retry, DHCP lease, browser acceptance, or cleanup-timeout recovery is established by these tests. The full hwsim matrix was not rerun. Task 10 remains incomplete. Existing `REVIEW.md`, `run_wifi_e2e.sh`, `wifi_e2e.py`, and `vm/` changes were preserved and excluded from these commits.

## Size

`git diff --shortstat 0cf294d85`: `8 files changed, 2871 insertions(+), 1725 deletions(-)`.

Line counts: manager 1061; test 2000.

## Physical installation and post-reboot verification

Installed the local Git bundle on comma three over `comma@192.168.1.199`, without a GitHub push, and rebooted. The device was offroad with a clean checkout before installation. The manager and test hashes matched the tested candidate.

Post-reboot boot ID: `b34746a2-124e-4b7d-a1cc-1c86cd8b0e5f`; clean HEAD `6ca796e338a955e16fd6c63869ee4c19baa81d5b`. The UI started the repository supplicant and udhcpc. Station status reached `COMPLETED` on `systeam5`, with IPv4 `192.168.1.105`. All SSH used eth0 address `192.168.1.199`; source-bound route to the actual client `192.168.1.171` selected eth0.

Before the touchscreen hotspot retry: no tethering NAT rule, forwarding 0, PrimeType 0. Evidence: `05-device-preflight.log`, `06-device-install.log`, `07-device-postboot.log`. This snapshot precedes the successful hotspot retry recorded below.

Deployment deviation authorized by the request to verify the device before publishing: fetched the local Git bundle instead of fetching from GitHub. The install and reboot otherwise follow Task 10.

## Physical hotspot and DHCP verification

At device time 2026-09-26 16:21:17 UTC, the user reported a phone connected to tethering. Wired SSH confirmed the same boot and installed HEAD. Supplicant status was `COMPLETED`, `mode=AP`, SSID `weedle-bbc2`, frequency 2437, IP `192.168.43.1/24`.

Dnsmasq PID 72500 was running with `--dhcp-leasefile=/run/dnsmasq.wlan0.leases`. Its lease file contained OnePlus-6 at `192.168.43.186`; syslog recorded DHCPACK at 16:20:44 UTC. IPv4 forwarding was 1. The tagged MASQUERADE rule counted 62 packets / 24671 bytes. The source-bound management route still selected eth0. Evidence: `08-device-client.log`.

The optional `iw dev wlan0 station dump` inspection could not run because `iw` is not installed; no package was installed. DHCP evidence does not depend on that command. The user subsequently confirmed: "Page loads with mobile data off". This is physical browser acceptance, distinct from the SSH-observed lease and NAT evidence. Hotspot-off restoration, password change, UI restart survival, and the other Task 10 checks remain pending.

Outcome: the original Enable Tethering failure is resolved on this comma three at `6ca796e338a955e16fd6c63869ee4c19baa81d5b`. Hotspot startup, DHCP, and client HTTPS browsing passed. The separately observed cleanup timeout has not been independently reproduced or declared fixed. No new unit or lint runs were performed during this device-only verification.
