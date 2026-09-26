# Hotspot startup diagnosis

Observed on 2026-09-26 over wired SSH to comma@192.168.1.199.

- Hostname: comma-cb80a5fa
- Installed commit: 2be8594264cb6de9e607dda4cd33fb4b875cf4f6
- Boot ID: 1fb00c9b-cc53-4a8d-8580-00d500a561da
- wifi_manager.py SHA-256: 55a24580388876918aee577385fcdd3c54d5ab8f6322aebc93789af31c6c336c
- Device reports IsOffroad=1.

## Observed failure

The user reported Enable Tethering briefly stalls and returns to OFF.
Existing console tracebacks show `_start_tethering` reached `_ensure_tethering_services(True)` and the dnsmasq subprocess exited with status 3. Cleanup then timed out receiving the response to REMOVE_NETWORK.

The device's existing /var/log/syslog contains:

```
2026-09-26T10:39:11.947943+00:00 comma-cb80a5fa dnsmasq[55321]: cannot open or create lease file /var/lib/misc/dnsmasq.leases: No such file or directory
2026-09-26T10:40:00.339900+00:00 comma-cb80a5fa dnsmasq[55936]: cannot open or create lease file /var/lib/misc/dnsmasq.leases: No such file or directory
```

Read-only checks confirm `/var/lib/misc` is absent and `/run` is writable. `dnsmasq --help` identifies `/var/lib/misc/dnsmasq.leases` as the default lease file. Installed dnsmasq is version 2.90. The implementation specifies the PID file but not the lease file.

## State after the failed attempts

Wired SSH succeeds. WPA status is INACTIVE, the three saved station networks are disabled, wlan0 has no IPv4 address, dnsmasq is absent, and the legacy NAT POSTROUTING chain contains no tethering rule. The supplicant and udhcpc processes are present. IPv4 forwarding is 1.

## Proposed bounded correction

Specify `--dhcp-leasefile=/run/dnsmasq.wlan0.leases` in the existing dnsmasq launch command, with a regression test and an explicit spec/plan correction. This proposal has not been applied or tested. The subsequent cleanup timeout is separately observed; this evidence does not establish its cause or show that the lease-file correction resolves it.

## Evidence boundary

Only read-only device commands were run. Existing logs capture two failures; no new hotspot attempt was triggered. No source or device configuration was changed. Local untracked REVIEW.md was preserved. No tests, lint, commits, pushes, or fleet mutations were performed.
