# Hotspot lease-file correction validation

Date: 2026-09-26. This is local/QEMU validation; the correction has not been installed or accepted on physical hardware.

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
