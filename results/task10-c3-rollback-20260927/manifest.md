# Comma three rollback compatibility

Local date 2026-09-27; UTC logs 2026-09-26. User approved rollback testing and the exact remote branch pushes. Source wifi-wpa-supplicant was pushed with a lease pinned to 2be8594264cb6de9e607dda4cd33fb4b875cf4f6; remote readback confirmed 8869c2f5639eaab178954d60c23e939a6c050ceb. Validation wifi-v3 fast-forwarded to e796043754047d847ce3c6e1a5407342c95003ac, also confirmed by remote readback. These later rollback artifacts are not included in that push.

The clean offroad device at Ethernet 192.168.1.199 was checked out to 0cf294d85fbaffd94a83f08536cf7a1bb3e75c80 and rebooted. The original v3 commit remains available locally and on the published branch for restoration.

The first early-startup observation at 21:22:16 UTC showed wlan0 unmanaged, no UI process, and ping failed with Network is unreachable. At 21:22:51 UTC, UI PID 29865 was running, NetworkManager reported 100 (connected), active connection openpilot connection systeam5, and IPv4 192.168.1.105. No manual networking repair was applied. `ping -c 3 -W 1 -I wlan0 1.1.1.1`: 3 transmitted, 3 received, 0% loss. Ethernet remained available with its connected subnet route.

Rollback saved-network autoconnect: PASS. The early-startup result is preserved separately from settled acceptance. Original-UI hotspot association passed, but browsing failed as reported by the user: "it connected but no internet". Restoration to v3 has not yet run; execution stopped at this failed rollback check under the requested stop rule. No source changes or unit/lint reruns. No new plan deviations.

## Hotspot browsing failure

At 21:27:23 UTC, NetworkManager reported Hotspot active at 192.168.43.1. Forwarding was 1, the FORWARD policy was ACCEPT, and Ethernet uplink probes received 3/3 replies. The legacy NAT table had no rules. At 21:27:45 UTC, the phone had lease 192.168.43.168 and a REACHABLE neighbor entry. The Hotspot profile used ipv4.method=shared. NetworkManager configuration selected firewall-backend=iptables, while the generic iptables command used nf_tables and failed with Could not fetch rule set generation id: Invalid argument. nft list ruleset likewise failed with cache initialization failed: Invalid argument.

These observations support a firewall-backend mismatch preventing NetworkManager NAT setup. The exact NetworkManager invocation and causality have not been proved with a counterfactual repair. No firewall, alternatives, or system configuration changes were made, and no claim is made that the migration caused this mismatch. The working v3 implementation explicitly used iptables-legacy.

Rollback result: saved-network autoconnect PASS; hotspot association PASS; hotspot browsing FAIL. The original plan's fully working rollback criterion is not met. Fixing the original version or changing system firewall configuration would be additional work, so neither was improvised. At the failure checkpoint, the device remained on 0cf294d85 with the original hotspot active; the subsequent authorized restoration is recorded below.

## Restore v3

The user approved restoring the tested v3 commit. At 21:29:30 UTC the clean offroad device checked out 8869c2f5639eaab178954d60c23e939a6c050ceb and rebooted. New boot ID: a3331ee9-c550-44db-b6d1-555802bef743. Early startup at 21:30:08 UTC had no managed Wi-Fi socket yet. At 21:30:41 UTC the UI was running (PID 32865), supplicant PID 37127 and udhcpc PID 37587 were active, and systeam5 was COMPLETED in station mode with IPv4 192.168.1.105. NetworkManager reported wlan0 unmanaged as expected for v3. Wired SSH worked and the source-bound reply route selected eth0. Both Ethernet and Wi-Fi subnet routes were present. `ping -c 3 -W 1 -I wlan0 1.1.1.1`: 3 transmitted, 3 received, 0% loss. Restoration PASS.

No system firewall configuration was changed. Rollback hotspot browsing remains FAIL. Restoration used the exact tested/published commit rather than relying on the device's possibly stale FETCH_HEAD. These restoration artifacts are local and have not been pushed.
