# Preserve forwarding during hotspot adoption

Date: 2026-09-26. Approved after the forwarding reset documented in `../task10-c3-ui-restart-20260926/manifest.md`.

## Implementation and checks

WifiManager initially has no forwarding policy (`None`). Hotspot adoption leaves the live kernel value unchanged until an explicit policy arrives. Explicit False and True still apply immediately. A fresh hotspot without a policy retains the previous forwarding-disabled default. This changes only the manager and its existing adoption test; public WifiManager API is unchanged.

Intermediate green commit: `deff4a8f4bfccc1e1839e709044bf65cc99cf1db`. Final source commits: `17d587f06224392c4a8476b88cb2b3c99c5681f7` (implementation) and `8869c2f5639eaab178954d60c23e939a6c050ceb` (tests). The squashed tree was verified identical to the intermediate tree.

Tests ran in the existing QEMU checkout `/workspace/openpilot` with `.venv/bin/python tools/test_runner.py openpilot/system/ui/lib/tests/test_wifi_manager.py`:

- `-k test_adopts_running_hotspot -v`: 0 passed, 1 failed before implementation, because adoption issued sysctl (01-red.log).
- `-v`: 82 passed, 0 failed after implementation (02-green-lint.log).
- `.venv/bin/ruff check openpilot/system/ui/lib`: passed.
- `.venv/bin/ty check openpilot/system/ui/lib/wifi_manager.py`: passed.
- `-v` on exact squashed HEAD 8869c2f563: 82 passed, 0 failed (03-squashed.log).
- Host source and documentation diff checks passed.

Host, QEMU, and installed device file hashes match:

- manager: `aa0a9125c68627ca15c4a73a4e652ebe2a07dd7591d9ad3a58f93e38849da6b5`
- test: `c21b4d413a1d23b0cb8c87cc099d84cad46882fbe63d0dd91ba95e45f75f7876`

## Device staging and pending physical verification

The clean, offroad comma three received the local Git bundle and checked out 8869c2f563 over Ethernet IPv4. No reboot or UI restart has been performed for this candidate yet; the existing UI process still has its previous code loaded. Supplicant PID 38624 and dnsmasq PID 56144 remained live. Forwarding was still 0 from the earlier failed adoption test. The user has been asked to open Network → Advanced to reapply the existing UI policy before the enabled-forwarding survival retry. That action and the physical retry are pending. No claim of hardware correction is made yet.

## Ethernet IPv4 investigation

Without another route or neighbor mutation, the Mac's fresh ping probe recovered: 4 transmitted, 4 received, 0% loss. Direct IPv4 SSH then succeeded. A passive AF_PACKET ARP capture on device eth0 observed the Mac's request and a reply involving the wired MAC. The capture did not change routes or install tools. The Mac's arp command still printed no entry despite successful probes, so that output alone is not sufficient to diagnose the prior failure.

The current device route selects eth0 for the management client. The Ethernet profile uses DHCP plus static 192.168.2.2/24, automatic route metric, ignore-auto-routes=no, and no explicit static routes. The stock udhcpc hook's operations are interface-scoped. These reads do not establish the cause of the previously absent Ethernet /24 route, nor explain the transient direct-IPv4 access failure. The earlier temporary route correction is not a persistent fix. Evidence: 06-eth-arp.log through 08-eth-profile.log.

## Deviations and remaining work

Approved amendment: retain an unset policy until the UI supplies it, instead of treating unset as False. The existing test's old expected adoption sysctl was replaced with an exact no-write expectation and explicit OFF/ON assertions; no assertions were dropped to hide a failure. The plan restart command now includes the checkout working directory and existing venv, both proven necessary in the prior physical run. Local Git bundles replace publication while validation is ongoing. No other source files, UI, hardware.py, or unrelated review findings changed. No GitHub push or PR action.

The enabled-forwarding physical restart, station-mode restart, remaining Task 10 checks, full hwsim matrix, and Ethernet root-cause resolution remain incomplete.

## Size

`git diff --shortstat 0cf294d85`: `8 files changed, 2933 insertions(+), 1726 deletions(-)`.
Manager: 1072 lines. Tests: 2050 lines.
