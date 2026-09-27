# Comma four device validation

Date: 2026-09-27. Device: comma-12462a9b. Initial hostname access selected wlan0 192.168.1.108, so no Wi-Fi changes were made until the user attached Ethernet. Thereafter strict host-key-checked SSH used 192.168.1.199 with HostKeyAlias=comma-12462a9b. The actual client 192.168.1.171 has a source-bound reply route through eth0. Device was offroad and checkout clean.

## Install and handoff

Fetched the published wifi-wpa-supplicant branch, verified FETCH_HEAD exactly 8869c2f5639eaab178954d60c23e939a6c050ceb, checked it out and rebooted. New boot ID: 181ea9ac-0101-4476-81e4-c98e26ce4052. The first early observation was before time synchronization and showed wlan0 unmanaged without a socket. At 08:33:44 UTC, before UI startup completed, NetworkManager reported connected to systeam5. The startup build then finished and UI PID 52124 appeared. At 08:34:46 UTC, handoff was complete: NetworkManager unmanaged, managed supplicant PID 52334, udhcpc PID 52378, systeam5 COMPLETED, address 192.168.1.108, DNS server 192.168.1.1. Route metrics: Ethernet 100, Wi-Fi 600, cellular 1000.

`ping -c 3 -W 2 -I wlan0 1.1.1.1`: 3/3 received. Both initial and post-reboot cellular probes (`ping -c 3 -W 2 -I ppp0 1.1.1.1`) received 2/3 replies. A subsequent `ping -c 5 -W 2 -I ppp0 1.1.1.1` received 5/5 replies. Preserve those initial losses; no loss-free cellular continuity claim. An intermediate startup probe found ppp0 absent before it was created.

## Touchscreen test prerequisite

systeam5 appears in legacy netplan file /data/etc/netplan/90-NM-b185a9e7-ddec-4cd7-9fc2-2d3a6f4cde15.yaml and also has a persistent openpilot connection systeam5.nmconnection profile. No passwords were read into evidence. Forget and subsequent UI checks are pending. No source modifications, unit/lint reruns, or new implementation deviations. No full Task 10 pass claimed. These artifacts have not been pushed.
