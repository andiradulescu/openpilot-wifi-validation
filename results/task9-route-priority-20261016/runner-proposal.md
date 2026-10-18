# Proposed runner scope expansion

Status: BLOCKED, decision key `udev-runner-scope`. This proposal has not been applied. Source remains at `c47761b0b51e8965a067aed71001fd09471579c0`. No further NM execution is authorized until the explicit answer.

The one newly requested project path is `run_wifi_e2e.sh` in the validation harness. The brief permits edits only to `wifi_e2e.py` and `test_wifi_e2e.py`; firstmate confirmed that this third file needs approval.

`runner-proposal.patch` adds four lines immediately after the existing udev snapshot and before /run isolation. It preserves a separate read-only bind of original live host udev data at `/tmp/wifi-e2e-udev/live` and exports `WIFI_E2E_UDEV_DATA` for the route fixture. The frozen `/run/udev/data` snapshot and its private read-only mount remain exactly as before for existing radio cases. The proposal uses the already isolated /tmp and adds no daemon, package, source API, or device action.

Existing runner SHA-256: `a9d88f62b3e266e61508bf09548fcceb40b9e883ba01795b409610e71aa132e8`.

## Small accompanying helper change, not yet implemented

In the existing `check_route_priority` helper in `wifi_e2e.py`:

1. Select the snapshot source with `Path(os.environ.get('WIFI_E2E_UDEV_DATA', '/run/udev/data'))`. Fail clearly if a configured source is unavailable; do not silently use the frozen view instead.
2. After creating each veth pair, while both endpoints still belong to the host network namespace, read their actual ifindexes from sysfs. Keep the existing udev settle call.
3. Use a fixed bounded barrier, for example a five-second monotonic deadline with short polling, requiring each real `n<ifindex>` record to exist in that source and contain a nonzero `I:` initialization timestamp. On expiry, retain the observed facts and fail setup. Never fabricate metadata or force away NM platform initialization.
4. Copy that real live source to the existing private `p / 'udev-data'` snapshot before moving the pair. Keep the private NM mount read-only and retain real NM-managed DHCP Ethernet, unmanaged WLAN, traffic, ARP, transient route, DNS, and cleanup assertions.

The standalone path retains its current live `/run/udev/data` source when the environment variable is absent. Under the full runner, the explicit preserved bind supplies the host data that `/proc/1/root/run/udev/data` cannot reach from its private PID/proc namespace.

After approval: implement only these setup changes, freeze a distinct staged harness directory for each run, verify exact source/harness hashes, obtain focused green behavior, then run the final full suite on the same frozen bytes. Do not count the current 53 passed/2 failed full run as green. Do not commit the failing harness or deploy the device.
