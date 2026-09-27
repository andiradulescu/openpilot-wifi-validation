# Release station DHCP lease on disconnect

Date: 2026-09-27. Approved spec amendment after the failed physical failover captured in ../task10-c4-20260927/failover.jsonl. The former spec explicitly sent no signal on DISCONNECTED. During the physical outage this left the Wi-Fi default at metric 600 preferred over cellular at 1000, with 45/45 main-outage probes failing. The user approved changing this policy before implementation.

## Implementation

Under the existing manager lock, refresh supplicant status and send SIGUSR2 to the live udhcpc only if current state is not COMPLETED and mode is not AP. Keep the daemon running; the existing CONNECTED handler sends SIGUSR1. A stale disconnect after reconnection leaves the lease intact. Only wifi_manager.py and its existing test file changed. Public API, UI, hardware.py, and DHCP hook are unchanged. Installed BusyBox 1.36.1 documents USR2 as lease release, and the stock deconfig hook flushes the interface address and routes.

## Red and green evidence

Tests ran in the existing QEMU checkout /workspace/openpilot with its venv. `.venv/bin/python tools/test_runner.py openpilot/system/ui/lib/tests/test_wifi_manager.py -k link_loss -v`: 0 passed, 1 failed before production edits, because no SIGUSR2 was recorded. The existing state/callback assertions were preserved and extended with release, daemon lifetime, and reconnection renewal expectations. A new stale-disconnect test asserts no release after a completed association.

`.venv/bin/python tools/test_runner.py openpilot/system/ui/lib/tests/test_wifi_manager.py -v`: 83 passed, 0 failed after implementation. `.venv/bin/ruff check openpilot/system/ui/lib`: passed. `.venv/bin/ty check openpilot/system/ui/lib/wifi_manager.py`: passed. Intermediate green commit: 8931b477c. The mandatory two-commit squash produced implementation 9297ad36b and tests 9f1e7ada0990a703ce22424737396ad2fb22bd08. Before/after Git tree IDs matched: 70740a700e8b54dbb3b96daf6ca2a3424a9a3644. Full suite on the exact squashed checkout: 83 passed, 0 failed. Host diff check passed.

Test-command correction: the first attempted `-k "link_loss or stale_disconnect"` selected zero tests; the repository runner requires its literal filter, so the actual red run used `-k link_loss`. VM checkout initially refused unstaged test copies even though they matched the new commit. After verifying both files exactly matched FETCH_HEAD, they were staged and checkout proceeded without discarding work. No assertions were weakened.

## Device installation and pending validation

The clean offroad comma four at Ethernet 192.168.1.199 received a local Git bundle, checked out 9f1e7ada0, and restarted its UI using /data/openpilot and the existing /usr/local/venv. Host and device hashes match:

- manager: 1a560f373932451d1373bb977f7d9ba1de542e6278df86669a97bbe7febdc77b
- test: 8d05771773a4de6a89d72ae3a5e968d9b2d752a1c593971f073547fb076d4d82

Physical failover retest completed with the results below. Unit assertions prove signal dispatch, not actual route cleanup or cellular traffic. While the UI is dead there is no manager event handling, so daemon survival does not prove cellular failover in that state. Comma three remains on the previous revision. No GitHub push or PR operation was performed.

## Size and deviations

`git diff --shortstat 0cf294d85`: 8 files changed, 2974 insertions(+), 1726 deletions(-). Manager: 1077 lines. Tests: 2086 lines. Approved deviation: release the DHCP lease on station disconnect, replacing the former explicit no-signal policy. Local bundles avoid publication during validation. Unrelated REVIEW.md, run_wifi_e2e.sh, wifi_e2e.py, and vm/ were preserved.

## Retest readiness

At 14:39:48 UTC, UI PID 76110 was running the clean 9f1e7ada0 checkout, systeam5 was COMPLETED, existing udhcpc PID 53853 remained alive, Ethernet reply routing selected eth0, and Wi-Fi-bound probes received 3/3 replies. The new detached recorder PID 76667 was verified parented to PID 1 in a separate SSH connection and recorded successful probes with Ethernet selected. It writes /tmp/wifi-failover-20260927-1440.jsonl and stops on its matching .stop marker or after its bounded recording window. The user subsequently confirmed completing the unplug/AP-disable/AP-enable/replug sequence; results follow.

## Physical failover retest

The user completed the same four-step sequence. The bounded recorder captured 14:40:13 through 15:10:13 UTC and stopped automatically at elapsed 1801.953 seconds. It captured Wi-Fi loss and recovery, but stopped before Ethernet reinsertion was observed; later live verification covers the final Ethernet state. Across 849 recorded probes: 839 passed, 10 failed.

- Ethernet baseline: 370 passed, 0 failed.
- Initial Wi-Fi-only interval: 28 passed, 2 failed.
- Main Wi-Fi outage, 14:54:15.669846 through 14:57:03.370611 UTC: route lookups before and after probes selected ppp0, the Wi-Fi default was absent, and supplicant reported SCANNING without its previous IPv4 address. Cellular probes: 67 passed, 8 failed.
- After Wi-Fi returned: 274 passed, 0 failed on wlan0.
- A later sampled transition contained one successful wlan0 probe followed by DISCONNECTED status, one successful ppp0 probe while SCANNING, then 98 successful wlan0 probes. The initiating cause of that later brief transition was not recorded.

All 76 samples selecting ppp0 had no wlan0 default; 68 passed and 8 timed out. The same pre-fix scenario never selected ppp0 and failed all 45 main-outage probes. This counterfactual establishes that the lease-release change corrects the stale preferred-route failure. Cellular traffic and return to Wi-Fi are verified. Zero-loss failover is not claimed, and the eight cellular probe timeouts are not explained by these samples. Probe timeout was one second. No exact link-loss-to-route-switch latency is claimed from sampled observations.

At 15:27:58 UTC, final wired SSH verified HEAD 9f1e7ada0990a703ce22424737396ad2fb22bd08, systeam5 COMPLETED at 192.168.1.108, the original udhcpc PID 53853 still alive, Wi-Fi and cellular defaults restored behind Ethernet, and the reply route to the Mac 192.168.1.158 through eth0. The same DHCP daemon survived lease release and reacquisition. Physical station Wi-Fi-to-cellular-to-Wi-Fi failover PASS with the recorded probe-loss limits. No new source edits or test/lint reruns followed the successful exact-tree suite. No push was performed.
