# Comma four device validation

Date: 2026-09-27. Device: comma-12462a9b. Initial hostname access selected wlan0 192.168.1.108, so no Wi-Fi changes were made until the user attached Ethernet. Thereafter strict host-key-checked SSH used 192.168.1.199 with HostKeyAlias=comma-12462a9b. The actual client 192.168.1.171 has a source-bound reply route through eth0. Device was offroad and checkout clean.

## Install and handoff

Fetched the published wifi-wpa-supplicant branch, verified FETCH_HEAD exactly 8869c2f5639eaab178954d60c23e939a6c050ceb, checked it out and rebooted. New boot ID: 181ea9ac-0101-4476-81e4-c98e26ce4052. The first early observation was before time synchronization and showed wlan0 unmanaged without a socket. At 08:33:44 UTC, before UI startup completed, NetworkManager reported connected to systeam5. The startup build then finished and UI PID 52124 appeared. At 08:34:46 UTC, handoff was complete: NetworkManager unmanaged, managed supplicant PID 52334, udhcpc PID 52378, systeam5 COMPLETED, address 192.168.1.108, DNS server 192.168.1.1. Route metrics: Ethernet 100, Wi-Fi 600, cellular 1000.

`ping -c 3 -W 2 -I wlan0 1.1.1.1`: 3/3 received. Both initial and post-reboot cellular probes (`ping -c 3 -W 2 -I ppp0 1.1.1.1`) received 2/3 replies. A subsequent `ping -c 5 -W 2 -I ppp0 1.1.1.1` received 5/5 replies. Preserve those initial losses; no loss-free cellular continuity claim. An intermediate startup probe found ppp0 absent before it was created.

## Touchscreen test prerequisite

systeam5 appears in legacy netplan file /data/etc/netplan/90-NM-b185a9e7-ddec-4cd7-9fc2-2d3a6f4cde15.yaml and also has a persistent openpilot connection systeam5.nmconnection profile. No passwords were read into evidence. Forget and subsequent UI checks are pending. No source modifications, unit/lint reruns, or new implementation deviations. No full Task 10 pass claimed. These artifacts have not been pushed.

## Legacy-profile Forget

The user reported completing Forget on systeam5. At 11:47:31 UTC, Ethernet SSH succeeded and the source-bound reply route to 192.168.1.171 selected eth0. Supplicant LIST_NETWORKS contained no systeam5 entry. No systeam5 contents matched files in /data/etc/netplan, /data/etc/NetworkManager/system-connections, or /run/NetworkManager/system-connections; the original netplan YAML was absent. No credentials were printed. Legacy-profile removal PASS.

The device was connected to the other saved network systeam, so it did not remain disconnected. This does not invalidate removal of systeam5; it means no claim of a disconnected station state is made. Reconnection to systeam5 with a correct password and remaining touchscreen tests are pending.

## Correct-password reconnection

The user reported reconnecting. At 11:49:03 UTC, supplicant reported systeam5 COMPLETED (network ID 6), IPv4 192.168.1.108. The new persistent profile /data/etc/NetworkManager/system-connections/systeam5.nmconnection exists with mode 0600 and metered unset. The hardware API reported network type 6 (ethernet per cereal/log.capnp) and metered False with Ethernet attached; this does not verify the plan's Wi-Fi-selected hardware-network-type assertion. Ethernet reply routing remained through eth0. `ping -c 3 -W 1 -I wlan0 1.1.1.1`: 3 transmitted, 3 received, 0% loss. Correct-password association, persistence, and Wi-Fi internet PASS. Hardware Wi-Fi selection remains a separate coverage gap while Ethernet is the preferred route. No source changes or test/lint reruns.

## Wrong-password cleanup

The user reported "done showed incorrect password", then "I also deleted system ssid". At 12:09:34 UTC, supplicant was SCANNING and LIST_NETWORKS contained neither systeam5 nor systeam, and no temporary entry for the failed systeam5 attempt. No systeam5 contents matched files in the persistent keyfile, runtime keyfile, or netplan directories. Ethernet SSH succeeded with replies routed through eth0. Failed-attempt cleanup PASS. The user subsequently confirmed exactly one incorrect-password retry prompt. Wrong-password prompt behavior and failed-attempt cleanup PASS. Supplicant STATUS still reported the previous IPv4 address 192.168.1.108 while SCANNING; this is recorded without claiming an active station connection or diagnosing address cleanup. No source or device changes were made by this verification.

## Reconnect after wrong-password test

The user reconnected with the correct password, leaving metering unchanged. At 12:18:21 UTC, systeam5 was COMPLETED with IPv4 192.168.1.108, a persistent mode-0600 profile, and metered unset. `ping -c 3 -W 1 -I wlan0 1.1.1.1`: 3 transmitted, 3 received, 0% loss. Wired SSH reply routing still selected eth0. Correct-password recovery PASS. Metered toggle remains pending.

## Metered toggle

After the user selected metered, verification at 12:19:41 UTC found systeam5 still COMPLETED and its persistent profile changed from metered unset to metered=1. In the device venv, HARDWARE.get_network_metered(log.DeviceState.NetworkType.wifi) returned True. HARDWARE.get_network_type() remained 6 (ethernet), whose metered value was False, consistent with wired management remaining preferred. The source-bound management reply route selected eth0. Metered persistence and explicit Wi-Fi hardware reporting PASS. No source changes or unit/lint reruns.

## Hotspot browsing with Ethernet and cellular uplinks

The user confirmed phone browsing with mobile data disabled, then reported "works on both without and with eth plugged in". This is physical user-observed browsing across Ethernet removal and reinsertion. No SSH capture or before/after cellular counter pair was collected during the unplugged interval, so packet-level attribution and zero-loss failover are not independently established.

At 12:25:56 UTC after Ethernet was reattached, wired SSH verified weedle-ca83 in AP mode, COMPLETED, 192.168.43.1; phone lease 192.168.43.220; forwarding=1; the tagged openpilot-tethering MASQUERADE rule; supplicant PID 52334 and dnsmasq PID 96947. Only Ethernet (metric 100) and ppp0 (metric 1000) had default routes; wlan0 was serving the AP. ppp0 was UP with RX 4577928 bytes and TX 321971 bytes, but these cumulative counters do not isolate the user's browsing. Ethernet reply routing selected eth0.

Hotspot association, DHCP/NAT state, and physical browsing with and without Ethernet PASS at the stated observation levels. UI password change, hotspot-off station recovery, UI restart, remaining recovery tests, and station Wi-Fi-to-cellular failover remain pending. No source changes, unit/lint reruns, or new implementation deviations.

## Password change with hotspot active

In response to the request to change the password while tethering was ON, reconnect with the new password, and browse fresh HTTPS with mobile data off, the user confirmed "works". At 12:28:04 UTC, wired SSH verified weedle-ca83 still COMPLETED in AP mode at 192.168.43.1, the phone lease at 192.168.43.220 renewed, forwarding=1, and the tagged NAT rule present. Supplicant PID remained 52334; dnsmasq changed from 96947 to 100318, consistent with hotspot service restart. The Ethernet reply route selected eth0. Password-change physical acceptance PASS. No password was read or recorded. Hotspot-off station recovery and subsequent restart/recovery tests remain pending.

## Hotspot off and station UI restart

The user disabled tethering and reported station recovery. At 12:32:21 UTC, systeam5 was COMPLETED with 192.168.1.108, the hotspot NAT rule was absent, Ethernet reply routing selected eth0, and the device was offroad. `ping -c 3 -W 1 -I wlan0 1.1.1.1`: 3 transmitted, 3 received. Hotspot-off cleanup and station reconnection PASS.

At 12:32:50 UTC the UI was stopped. The planned 40 individual `ping -c1 -W1 -I wlan0 1.1.1.1` probes, separated by 0.5 seconds, returned 40 ok and zero LOST. Supplicant PID 52334 and udhcpc PID 100296 were unchanged. UI restart launched at 12:33:12 UTC using the amended checkout-cwd and activated-venv command, with an EXIT trap for restoration if the probe script failed. After the 45-second settling period, verification at 12:34:14 UTC found UI PID 104054 running, the same daemon PIDs, systeam5 COMPLETED, and Ethernet reply routing still on eth0. Post-restart `ping -c 3 -W 1 -I wlan0 1.1.1.1`: 3 transmitted, 3 received. Station UI restart PASS: 40/40 downtime probes and 3/3 post-restart probes. No source changes, unit/lint reruns, or new implementation deviations. Hotspot-mode UI restart remains pending.

## Hotspot UI restart

At 12:51:24 UTC, the offroad device had weedle-ca83 active, phone lease 192.168.43.220, forwarding=1, supplicant PID 52334 and dnsmasq PID 107641. Preflight `ping -c 3 -W 1 -I wlan0 192.168.43.220`: 3/3 replies. Ethernet reply routing selected eth0.

UI stop at 12:51:48 UTC followed by 40 individual `ping -c1 -W1 -I wlan0 192.168.43.220` probes spaced by 0.5 seconds produced 40 ok and zero LOST. Both daemon PIDs were unchanged and forwarding stayed 1. UI restart launched at 12:52:13 UTC using the amended cwd/venv command and an EXIT restoration trap. After the planned 45-second settling period, verification at 12:53:20 UTC found UI PID 110219, the same daemon PIDs, AP COMPLETED, forwarding=1, the same phone lease, and the tagged NAT rule. Wired SSH worked and replies used eth0. Post-restart `ping -c 3 -W 1 -I wlan0 192.168.43.220`: 3/3 replies.

Automated hotspot restart checks PASS: 40/40 downtime probes and 3/3 afterward, with daemon adoption and forwarding preserved. The user subsequently confirmed fresh post-restart phone HTTPS browsing with mobile data off: "works". Physical hotspot restart acceptance PASS. No source changes, unit/lint reruns, or new implementation deviations.

## Reboot autoconnect and daemon crash recovery

After the user disabled tethering, preflight at 12:56:38 UTC verified systeam5 COMPLETED, offroad state, clean source HEAD 8869c2f5639eaab178954d60c23e939a6c050ceb, hotspot NAT rule absent, and management replies routed through eth0. The authorized reboot succeeded. Boot ID changed from 181ea9ac-0101-4476-81e4-c98e26ce4052 to f1adb808-3e89-4783-a3f6-eb00f6975077. The early 12:57:24 UTC observation preceded UI/Wi-Fi daemon startup. At 12:58:11 UTC, UI PID 25913 was running, supplicant PID 30279 and DHCP PID 31103 were active, systeam5 was COMPLETED at 192.168.1.108, and Wi-Fi-bound internet probes received 3/3 replies. No user input was needed. Reboot autoconnect PASS.

For each crash test, a host-streamed Python standard-library script verified IsOffroad=1, the pidfile, and the process command line, then issued sudo kill -9 to that managed wlan0 daemon only. It polled once per second for a different live PID, systeam5 COMPLETED, and a successful `ping -c1 -W1 -I wlan0 1.1.1.1`, with a 35-second deadline measured using time.monotonic(). No script was installed on the device.

- Supplicant: PID 30279 → 53773, recovery observed at 9.574 seconds, 1/1 internet reply. PASS.
- udhcpc: PID 31103 → 53853, recovery observed at 1.119 seconds, 1/1 internet reply. PASS. This measures process respawn and connectivity, not a separately captured fresh DHCP exchange; the existing address may survive the client crash.

At 12:59:16 UTC, the same UI PID and recovered daemon PIDs were present, wired SSH succeeded with replies through eth0, and `ping -c 3 -W 1 -I wlan0 1.1.1.1` received 3/3 replies. Recovery acceptance: 3 checks passed, 0 failed, with 8/8 acceptance probe replies across reboot, both crashes, and final verification. No source changes, unit/lint reruns, or new implementation deviations.

Station Wi-Fi-to-cellular failover and return remain pending. Ethernet currently has the preferred default route, so simply losing station Wi-Fi while Ethernet stays connected would not prove cellular failover. Existing full-matrix and rollback limitations remain unchanged.
