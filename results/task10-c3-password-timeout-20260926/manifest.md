# Password-change timeout correction

Date: 2026-09-26. Approved after the Task 10 password-change failure captured in `../task10-c3-dnsmasq-leasefile-20260926/10-password-change-failure.log` through `12-password-change-teardown.log`.

## Change and provenance

The command socket is replaced after a receive timeout so a late reply cannot become a later command's response. WpaCtrl.request/ok accept an optional timeout; default commands retain two seconds, and all three AP-removal sites use the existing ten-second AP limit. Receive waits use an absolute deadline. The public WifiManager interface is unchanged.

Intermediate green commits: `43f64a171` (late reply recovery) and `ae96f2f2e5cb2e916d3bcbc4694b07953a703228` (bounded AP teardown). Final two-commit source shape:

- `e7a2132d4e684e9f81f0cd22845a8484c2e44da5`: implementation.
- `6b21c429302be2361be2c3fe6037b4b6611b1ec6`: tests.

The final tree equals ae96f2f2e, verified with git diff --exit-code. QEMU received the commits through a local bundle and its candidate files matched FETCH_HEAD before its detached checkout was aligned. No GitHub push.

Host and QEMU SHA-256 values:

- manager: `fffe9ff917b4551782ab1837a4454e5319fb08367b4ed228e5b664b7bbde4b9e`
- test: `7e83928c789df0781b0af585bfef753d799157ebe826f467d68833876492eba2`

## Actual checks

QEMU checkout root `/workspace/openpilot`; base command `.venv/bin/python tools/test_runner.py openpilot/system/ui/lib/tests/test_wifi_manager.py`.

| Log | Command suffix | Result |
| --- | --- | --- |
| 01-control-red.log | -k TestWpaCtrl -v | 1 passed, 1 failed: PING received stale OK |
| 02-control-green.log | -k TestWpaCtrl -v | 2 passed, 0 failed |
| 03-password-red.log | -k test_tethering_password_change_waits_for_slow_ap_removal -v | 0 passed, 1 failed: 2.2-second AP removal exceeds the ordinary timeout |
| 04-suite-green-lint.log | -v | 82 passed, 0 failed; Ruff and ty passed |
| 05-squashed.log | -v | 82 passed, 0 failed on the exact final HEAD |

Lint commands: `.venv/bin/ruff check openpilot/system/ui/lib` and `.venv/bin/ty check openpilot/system/ui/lib/wifi_manager.py`. Host source diff and spec/plan diff checks passed. Raw logs retain their original formatting.

The fake supplicant now tolerates ConnectionRefusedError when replying to a timed-out client that closed its socket. No assertion was weakened. Two regressions were added through the existing control-client and public password-change seams.

## Deviations and remaining limits

The approved amendment adds bounded AP-removal waits and replacement of timed-out command sockets to the original plan. The optional timeout parameter is internal to WpaCtrl. No other review findings were addressed, and no UI/hardware.py changes were made. The earlier lease-file fix remains intact. REVIEW.md and unrelated harness/VM changes were preserved.

The device failure demonstrated a timeout awaiting AP removal; existing driver timestamps suggested slow teardown but did not measure the command response. The fake-supplicant tests reproduce the timeout and late-reply hazards. Physical password-change acceptance must still be verified on the installed candidate; passing unit tests alone do not establish that result. The full hwsim matrix was not rerun.

## Size

`git diff --shortstat 0cf294d85`: `8 files changed, 2927 insertions(+), 1725 deletions(-)`.

Manager: 1071 lines. Tests: 2046 lines.

## Device installation and physical retry blocker

Installed the local bundle on the clean, offroad comma three over `comma@192.168.1.199` and rebooted. Device source/test hashes match the tested hashes. New boot ID `5afbedc8-d038-49d4-a756-20d33f6c1339`; HEAD `6b21c429302be2361be2c3fe6037b4b6611b1ec6`. UI started and station status became COMPLETED on systeam5 at 192.168.1.105.

Before any hotspot retry, the source-bound management lookup unexpectedly selected wlan0. Eth0 still has carrier and 192.168.1.199/24; NetworkManager reports connected. Its default route is metric 100, but its 192.168.1.0/24 connected route is absent. Only a 192.168.1.1/32 gateway route remains on eth0, while the WLAN /24 has metric 600. The /24 therefore wins for the management client 192.168.1.171. Evidence: 08-device-postboot.log and 09-device-route-blocker.log.

No hotspot retry was requested after discovering this failed Ethernet-routing prerequisite, and no route correction was applied. Physical password-change acceptance remains unverified. Proposed temporary correction: `sudo ip -4 route replace 192.168.1.0/24 dev eth0 proto kernel scope link src 192.168.1.199 metric 100`, followed by source-bound route verification. The cause of the missing route is not established.

Deployment used a local bundle rather than a GitHub fetch, preserving the user's requirement to see physical success before publication. No push or PR action was performed.

## Approved temporary Ethernet-route restoration

At device time 2026-09-26 16:42:40 UTC, applied the explicitly approved command `sudo ip -4 route replace 192.168.1.0/24 dev eth0 proto kernel scope link src 192.168.1.199 metric 100`. The source-bound route from 192.168.1.199 to the actual SSH client 192.168.1.171 then selected eth0. Both Ethernet metric-100 and WLAN metric-600 connected routes were present. Same device boot and source HEAD; station remained COMPLETED on systeam5. Evidence: `10-device-route-restored.log`.

This is a temporary runtime route, not a persistent fix for the missing-route cause. The physical password-change and phone browsing retry has been requested; its result is pending. No source changes or unit/lint runs were made for this route restoration.

## Physical password-change acceptance: passed

The user completed the retry and explicitly confirmed "Stays ON and HTTPS loads" after changing the password, reconnecting the phone, and loading a fresh HTTPS page with mobile data off.

Direct IPv4 SSH from the Mac to 192.168.1.199 timed out. The router still resolved that address to the device's Ethernet MAC d0:37:45:1c:70:d9 and pinged it successfully (2 sent, 2 received). Router neighbor inspection identified Ethernet IPv6 address 2a02:2f04:c20c:d600:ac97:ae49:67a5:8ca5. SSH through that address succeeded with StrictHostKeyChecking=yes and HostKeyAlias=192.168.1.199, verifying the existing device key. Device `ip -6 addr show eth0` confirmed the address belongs to Ethernet. No wlan0 SSH was used. The Mac's `arp -n 192.168.1.199` returned no entry; the direct IPv4-access cause remains unproven and no further route or neighbor changes were made.

At 16:44:56 UTC, same boot ID and HEAD 6b21c4293: supplicant COMPLETED in AP mode on weedle-bbc2, IPv4 192.168.43.1. Syslog records dnsmasq PID 55780 starting at 16:42:57.894, exiting at 16:43:07.435, and replacement PID 56144 starting at 16:43:07.788. The new process uses the explicit runtime lease file. DHCPACK at 16:44:00.375 assigned OnePlus-6 address 192.168.43.186. Forwarding is 1; tagged MASQUERADE counted 28 packets / 17739 bytes. The inspected recent console window contained no password-change failure or timeout traceback. Evidence: 11-password-retry-ipv6.log.

This confirms one successful physical password-change/reconnect/browser retry on the correction. It does not prove every AP teardown duration or resolve the distinct Ethernet route/IPv4-access issues. Device verification used Ethernet IPv6 as a documented transport deviation after IPv4 failed. No password was read or stored. No new unit or lint runs in this physical-verification turn. Task 10 UI restart survival, remaining recovery/rollback checks and comma-four acceptance remain incomplete.
