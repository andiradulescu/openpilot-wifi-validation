# Comma three station-mode UI restart

Date: 2026-09-26. Device: comma-cb80a5fa, managed exclusively through Ethernet IPv4 192.168.1.199. Source HEAD: 8869c2f5639eaab178954d60c23e939a6c050ceb. User stopped tethering and authorized this test.

## Results

Preflight: clean device checkout, IsOffroad=1, systeam5 COMPLETED in station mode, wlan0 address 192.168.1.105, Ethernet reply route to the actual SSH client 192.168.1.171. `ping -c 3 -W 1 -I wlan0 1.1.1.1`: 3 transmitted, 3 received, 0% loss. The IsOffroad value has no newline in the raw log and appears immediately before the route output.

The UI was stopped at 18:49:58 UTC. The planned 40 individual `ping -c1 -W1 -I wlan0 1.1.1.1` probes, spaced by 0.5 seconds, produced 40 ok and zero LOST. Supplicant PID 38624 and udhcpc PID 112199 remained unchanged. UI restart was launched at 18:50:20 UTC using `/data/openpilot` as working directory and the activated `/usr/local/venv` environment.

After the planned 45-second settling period, verification at 18:51:22 UTC found UI PID 113292, the same supplicant and udhcpc PIDs, systeam5 COMPLETED, and the same station IPv4 address. Post-restart `ping -c 3 -W 1 -I wlan0 1.1.1.1`: 3 transmitted, 3 received, 0% loss. Wired SSH succeeded and its reply route selected eth0. The legacy NAT POSTROUTING chain contained only its ACCEPT policy, confirming hotspot rule removal.

Station-mode UI restart passes. No source changes or unit/lint reruns were needed. The restart used the already amended plan command; an EXIT trap restored the UI if the probe script failed. No new implementation deviations or GitHub actions.

## Other physical observations

Before stopping tethering, the user reported another password change while tethering was ON and confirmed the phone rejoined and loaded a fresh HTTPS page with mobile data off. A separate wired SSH check at 18:45:29 UTC succeeded, selected eth0 for replies, and found forwarding=1. This user observation is separate from the automated station restart evidence above.

## Remaining validation

Reboot autoconnect, supplicant and DHCP-client crash recovery, rollback compatibility, and comma four cellular validation remain. The prior hotspot restart's 15 phone-probe timeouts and intermittent Ethernet IPv4 root cause are unresolved. The existing temporary Ethernet subnet route is still present; this test does not establish a persistent fix for it. Full hwsim qualification is incomplete.

## Source size

`git diff --shortstat 0cf294d85`: `8 files changed, 2933 insertions(+), 1726 deletions(-)`.
Manager: 1072 lines. Tests: 2050 lines.
