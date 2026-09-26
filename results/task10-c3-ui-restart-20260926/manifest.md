# Hotspot survival across UI restart

Date: 2026-09-26. Device comma-cb80a5fa; source `6b21c429302be2361be2c3fe6037b4b6611b1ec6`; boot `5afbedc8-d038-49d4-a756-20d33f6c1339`. Management used the verified eth0 IPv6 address with the existing SSH host key. Offroad=1.

## Observations

Before stopping UI: hotspot weedle-bbc2 active, phone lease 192.168.43.186, wpa_supplicant PID 38624, dnsmasq PID 56144, tagged NAT rule present, forwarding previously verified as 1.

After `tmux kill-session -t comma`, 40 probes (`ping -c1 -W1 -I wlan0 192.168.43.186`, 0.5-second intervals) returned **40 ok, 0 LOST**. Both daemon PIDs remained unchanged and supplicant stayed COMPLETED in AP mode. This proves local hotspot reachability during UI absence; it is not a continuous internet-availability measurement.

The plan's literal restart command exited because `/data/openpilot/launch_openpilot.sh` executes `./launch_chffrplus.sh` relative to its working directory. Starting tmux with `-c /data/openpilot` fixed that but exposed a second launch prerequisite: system Python could not import capnp. The existing `/usr/local/venv/bin/python` imported capnp successfully. Launching with the existing venv activated brought manager/UI back:

```
tmux new -s comma -c /data/openpilot -d 'bash -c "source /usr/local/venv/bin/activate; exec ./launch_openpilot.sh"'
```

No package installation or source edits were made. The launch log's modem identifiers were redacted before archival.

After UI startup, both Wi-Fi daemon PIDs were still 38624 and 56144, AP status was COMPLETED, the client lease remained, and the NAT rule remained. However, forwarding changed to **0**. At 16:53:58 UTC it was still 0 with PrimeType=0. Code inspection shows WifiManager initializes `_ipv4_forward=False`, then hotspot adoption calls `_ensure_tethering_services`, which writes that value to sysctl. The UI supplies Prime-derived forwarding policy from the network settings update path. This reset violates hotspot internet continuity across UI restart. The user was asked to check a fresh HTTPS page without opening settings; no response was yet available when this record was written.

Result: daemon survival and client reachability passed (40/40). Full hotspot restart survival **failed** due to forwarding reset. A browser observation remains separate and pending. Station-mode UI restart has not been tested in this run.

## Separate Ethernet IPv4 finding

Ethernet IPv4 is expected to continue working during tethering. Router ping to the device's wired IPv4 passed earlier, and Ethernet IPv6 SSH remained available. The Mac's direct IPv4 SSH and two fresh ping probes failed. Its route points to en0, but no ARP entry for 192.168.1.199 was shown. The cause remains unproven; no Mac networking changes were made. The manually restored device Ethernet /24 route remains a temporary correction, not a persistent resolution of its missing-on-reboot behavior.

## Deviations and limits

- AP-mode probes targeted the attached phone rather than the plan's station-uplink 1.1.1.1 target, and checked dnsmasq rather than udhcpc PID. The AP's uplink is Ethernet.
- Management used Ethernet IPv6 after direct wired IPv4 access failed.
- The restart required the checkout working directory and existing device venv, omitted by the plan's literal command. Both failed launch attempts are preserved.
- No new unit tests or lint runs; no source changes, GitHub pushes or PR actions.

Raw evidence: 01-preflight.log through 08-forwarding-reset.log. Task 10 remains incomplete.
