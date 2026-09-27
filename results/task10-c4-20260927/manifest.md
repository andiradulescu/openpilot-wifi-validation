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
