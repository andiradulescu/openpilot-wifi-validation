# Comma three reboot and crash recovery

Local date: 2026-09-27 (Europe/Bucharest); device logs use UTC 2026-09-26, 21:10–21:13. Device comma-cb80a5fa, clean source HEAD 8869c2f5639eaab178954d60c23e939a6c050ceb. All SSH used Ethernet IPv4 192.168.1.199. User explicitly approved reboot autoconnect and both daemon crash tests. IsOffroad=1 was checked before each mutation.

## Reboot autoconnect

Boot ID changed from 5afbedc8-d038-49d4-a756-20d33f6c1339 to 7dbc2624-69fa-42f8-8134-03523914f372. The first early-startup observation at 21:11:01 UTC found no UI or managed Wi-Fi daemons yet; the ping invocation failed with Network is unreachable. This startup observation is preserved, not counted as a completed autoconnect test.

At 21:11:39 UTC, without user input, UI PID 29019 was running, supplicant PID 33775 and udhcpc PID 34300 were present, and systeam5 was COMPLETED with IPv4 192.168.1.105. `ping -c 3 -W 1 -I wlan0 1.1.1.1`: 3 transmitted, 3 received, 0% loss. Reboot autoconnect PASS.

## Crash recovery

For each test, a host-streamed Python standard-library script checked the target pidfile and /proc command line, issued `sudo kill -9 <verified PID>`, and polled once per second for a different live PID, systeam5 COMPLETED, and a successful `ping -c1 -W1 -I wlan0 1.1.1.1`. The deadline was 35 seconds and timing used time.monotonic(). No script was installed on the device.

- Supplicant: PID 33775 → 54685; recovery observed at 9.547 seconds, 1 ping transmitted and received. PASS.
- udhcpc: PID 34300 → 55058; recovery observed at 1.132 seconds, 1 ping transmitted and received. PASS. This verifies process respawn and connectivity; it does not independently measure a fresh DHCP exchange because the existing address can survive a client crash.

Final verification at 21:13:03 UTC: same UI PID 29019 and recovered daemon PIDs, clean source checkout unchanged, wired SSH successful, reply route to the Mac selected eth0. `ping -c 3 -W 1 -I wlan0 1.1.1.1`: 3 transmitted, 3 received, 0% loss.

## Ethernet and remaining scope

The Ethernet 192.168.1.0/24 route was present after reboot before Wi-Fi startup and remained present after autoconnect and both crashes. No route repair was applied in this run. This does not establish the cause of its earlier disappearance or resolve the previously intermittent Ethernet issue.

Step 5 results: 3 checks passed, 0 failed (autoconnect, supplicant recovery, DHCP-client recovery). Successful acceptance probes total 8 transmitted and 8 received, plus the separately recorded early-startup unreachable result. No source changes, unit tests, or lint reruns. No new plan deviations; scripted observation supplied timing and process-identity checks around the planned kill commands. No GitHub actions.

Remaining: rollback compatibility, comma four cellular/device validation, full hwsim qualification, the prior hotspot restart's 15 probe timeouts, and Ethernet root-cause resolution.
