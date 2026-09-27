# Task 9 traced hwsim and CI evidence

## Provenance and integrity

This directory preserves the supplied evidence without changing its source files:

| Material | Source | SHA-256 |
| --- | --- | --- |
| Complete observer archive | `/private/tmp/wifi-trace-ci-evidence-20260927.tar.gz` | `dfb1f9a52a05653f8a5aa9c1b4ea7cc684e2281820831191a85f382a33cbf7c1` |
| Observer program | `/private/tmp/wifi_trace_observer.py` | `047f2a191e7c61f9157776fd5b9d5932430a24a1b794d27e3d62e04159c3e10e` |
| Pre-existing harness correction archive | `../task9-20260927/harness.patch` | `5beb987abfc3795dc7bce573c7af04cbf1353cbfd4466320d9cf0b7f5269e37a` |

The archive hash was verified before copying. An archive-content scan found no credentials or private keys. Its only
password-pattern matches are the synthetic `password123` test fixture in the two expected failure logs.

## Complete observer runs

All eight selected one case from the 52-case hwsim suite and deselected the other 51 cases. They contain observer
process, packet, and DHCP trace coverage. Earlier observer attempts without valid process and packet coverage are not
used for causal claims.

| Trace | Source SHA | Scan constraint | Result |
| --- | --- | --- | --- |
| `wifi-trace-9_wz4p7o` | `f02354e40638` | none | pass |
| `wifi-trace-ywhe_km1` | `f02354e40638` | none | DNS failure |
| `wifi-trace-_nt4o_97` | `f02354e40638` | none, with `iw` and ARP capture | DNS failure |
| `wifi-trace-ol8_25sq` | `7dd283517c49` | `freq_list=2412` | pass |
| `wifi-trace-853sqwiv` | `7dd283517c49` | none | pass |
| `wifi-trace-v965lk33` | `7dd283517c49` | `freq_list=2412` | pass |
| `wifi-trace-w7zybnrd` | `7dd283517c49` | `freq_list=2412` | pass |
| `wifi-trace-n59nrzjq` | `7dd283517c49` | none | pass |

The complete set is therefore six passes and two DNS failures. The three constrained runs passed. They do not establish
deterministic causality because unbounded runs also passed.

## What the traces establish

- In the `_nt4o_97` DNS-failure interval after association, observer samples retain `wpa_state=COMPLETED`,
  `ip_address=10.10.0.74`, the wlan0 default route at metric 600, and the WLAN connected prefix at metric 600. There
  is no DHCP deconfiguration or IPv4 removal in that interval. A normal pre-association DHCP deconfig is present
  earlier in the trace and is not the later DNS failure.
- The failing DNS probe packets leave the DUT after the completed association but do not appear in the WAN capture for
  that probe. Earlier DNS packets do appear on both captures and receive replies, so this is a fixture timing/coverage
  observation, not proof of a permanent forwarding failure.
- `_nt4o_97` records a later unbounded scan beginning before the manager reopen and remaining active until teardown.
  In constrained runs, the initial unbounded scan had already started before the diagnostic setting took effect; later
  channel-1 scans finished in about 37 ms. The archive records no basis to attribute a deterministic failure to scan
  breadth or to physical hardware.

This evidence concerns the disposable hwsim fixture only. It neither proves a comma hardware defect nor validates a
physical device.

## CI password-getter correction

The archived CI logs preserve the narrow source correction following upstream PR #38968 commit
`8869c2f56...`. The generic `Create UI Report` job called `tethering_password`; the former getter reached
`_hotspot_profile()` and could call `write_profile()` with `sudo install` against generic-runner paths. The cached
getter reads a matching AP PSK under the manager lock and returns `""` when absent. Initialization, the explicit
setter, and tethering activation remain the provisioning paths.

`ci-password-getter-red.log` records 85 passed and one expected `unexpected profile write` failure.
`ci-password-getter-green.log` records 86 passed. Ruff and ty both report `All checks passed!` in their archived logs.
The final source tree is `116f080878deb894a063d01995c77dd7cf84abf8`, reshaped as implementation
`42957fa73` and tests `314a68bc90ae490aa79784b6f371f54158b2753c`.

## Ownership and remaining boundary

The tracked `run_wifi_e2e.sh` and `wifi_e2e.py` corrections pre-existed this evidence bundle and were independently
audited as task-owned. Their exact pre-existing patch is preserved at `../task9-20260927/harness.patch`; this bundle
does not claim authorship of those hunks. `vm/` and source `REVIEW.md` are outside this evidence scope.

The final full VM matrix was still running when this manifest was prepared. This record does not claim that matrix
passed, that CI is green now, or that any branch was pushed.
