# Task 9 matrix repair evidence

## Archived baseline

- Archive: `task9-final-314a68bc9-full-hwsim-artifacts.tar.gz`
- Original: `/private/tmp/task9-final-314a68bc9-full-hwsim-artifacts.tar.gz`
- SHA-256: `98b8e2e86ef8edc83855a5808c404b38ef830050ff25fee92bcb1da4b7b5e36d`
- Contents: 820 files, including the run manifest, JUnit report, full `run.log`, service diagnostics, and unit, Ruff, ty, and filtered-hwsim logs.
- Archive inspection found no private-key headers, authorization headers, API-key markers, or token markers. Fixture credentials are synthetic.

This is the full hwsim matrix at source `314a68bc90ae490aa79784b6f371f54158b2753c`, harness snapshot `e966eb74613b8a9507ba495c3a0ba8e8ba78d1ab`. It ran from 2026-09-27T21:00:40.225349+00:00 through 2026-09-27T21:15:08.708872+00:00 and finished with exit code 1: **29 passed, 23 failed, 868.01 seconds**. The archive's source tree was clean; its harness tree had the three task-owned modified files. This record is failing baseline evidence. It is not validation of the repairs below and does not claim a green matrix.

## Completed repair evidence archive

- Archive: `wifi-repair-evidence-17c5a1b3-complete.tar.gz`
- Original: `/private/tmp/wifi-repair-evidence-17c5a1b3-complete.tar.gz`
- SHA-256: `347774573e5974dbff99184b9372299700382d720dc2c6c44cbcaacb81843814`
- Contents: 1,305 regular files in 1,475 archive members. The archive has no special files. A content scan found no private-key
  headers, authorization headers, API-key markers, or token markers; fixture credentials are synthetic.

The archive records source `17c5a1b3b7318aebc034ed1ed695495dccbc07b2`, tree
`1cb7857d3550ad4120dd1d6cb5e0cc177d639793`. It preserves the unresolved hwsim evidence, including the unaffected
group at `results/20260927T215833553910Z-17c5a1b3b731-hwsim`: **37 passed, 7 failed, 9 deselected**, exit code 1.
It also records the two confirmed local CI UI-report replays, normal and `--big`, with exit code 0 for each. The first
attempts stopped because the local environment lacked `coverage`; the archive contains the declared locked
`coverage==7.15.4` installation log and the succeeding confirmation logs. Remote CI was not rerun. This archive does
not claim an all-green hwsim matrix, remote CI, or acceptance.

## Final narrowed-mount evidence archive

- Archive: `wifi-repair-evidence-17c5a1b3-final-data-only-udev.tar.gz`
- Original: `/private/tmp/wifi-repair-evidence-17c5a1b3-final-data-only-udev.tar.gz`
- SHA-256: `95c7cf04d310ae4e1ab01b5285ae8dc6fe773191e3cd52a6b92b325680481d66`
- Contents: 2,966 regular files in 3,467 archive members, with no special files or unsafe paths.

The parent verified the copied hash, final JUnit result of 44 tests with zero failures and zero errors, and the archive
member counts above. The archive body scan found no credential markers; fixture credentials are synthetic. It covers
the filtered 44-test narrowed-mount group recorded below, not the nine excluded tests, remote CI, or physical hardware.

## Repairs derived from the baseline

### Fixture isolation and persistent NetworkManager state

- Bind isolated `/data/etc/netplan` onto `/etc/netplan`, alongside the existing isolated NetworkManager-profile bind. The production manager removes a netplan-origin YAML from `/data/etc/netplan`; the former fixture wrote and regenerated it from a distinct `/etc/netplan`, allowing a forgotten UUID to reappear.
- Clear `/run/NetworkManager/devices` during each fixture setup as attempted runtime-state hygiene. Network namespaces do not isolate that state, but this has not been established as the cause of the remaining handoff failure.

These changes retain the netplan forget assertion and the handoff behavior under test. They do not set `wlan0` managed in the pre-UI path, which would conceal the unmanaged-device condition.

### Completed unaffected-run fixture diagnosis

The unaffected run at `results/20260927T215833553910Z-17c5a1b3b731-hwsim` finished with **37 passed, 7 failed,
9 deselected, 300.25 seconds**. Five failures were the profile-write fault-injection cases: failed Forget,
failed metering, new-profile write failure, and both tethering-password writes. Each performed its expected write:
Forget reported the profile unsaved, metering became `1`, the new station profile saved without a `save_failed` event,
and the hotspot password became `new-password123`. The fixture mounted `PROFILE_DIR` read-only in pytest's mount
namespace after the worker had started. The worker runs through `ip netns exec`, whose mount namespace did not receive
that later mount. The fault therefore did not reach the manager's `sudo install` writer.

The harness now uses `nsenter -t <manager-pid> -m` for the bind-remount and unmount, so the fault applies in the
worker's own mount namespace. It verifies a live manager before injecting the fault and directly probes a C-locale
`touch` in that namespace; only `Read-only file system` is accepted, while a writable probe is removed and raises
before a test can infer a fault from later assertions. The initial repair had static evidence; the focused run below
later passed all five read-only profile-write cases.

The same run's `True-netplan` Forget case recreated UUID `9458bb1a-0b29-4b9d-a729-ca28d38bb68a` after
`netplan generate`. A standalone `netplan generate --root-dir` diagnostic used the prior `wifis.wlan0` seed and
produced `netplan-wlan0-Test%20A.nmconnection`, which does not match the production removal prefix
`netplan-NM-`. The corrected fixture uses the NetworkManager `NM-<uuid>` definition key and `match.name: wlan0`;
the same isolated diagnostic produced `netplan-NM-test-uuid-Test%20A.nmconnection`, with UUID, password, and
passthrough values intact. This matches the production prefix without changing production Forget behavior.

The focused fixture run at `results/20260927T221636470571Z-17c5a1b3b731-hwsim` used the pre-socket-timeout
`wifi_e2e.py` revision `c814969ea593e8b0dcb94c854f69e4a79ed61346d35acb4718fd35a41f86ae37`. It finished with
**6 passed, 2 failed, 45 deselected, 83.15 seconds**. The six intended repairs passed: `True-netplan` Forget and
the five read-only profile-write cases. The selection also included `False-netplan`, which failed in the known
unresolved selection-policy path, plus the remaining NetworkManager handoff case. This is not evidence that the
later socket-timeout revision `719c4262edc028ba896a34071c63858e3c5a8be0e799b9b0d4ec27130c12b733` ran in a guest.

### NetworkManager handoff diagnosis

The handoff-only red run at `results/20260927T223023338280Z-17c5a1b3b731-hwsim` finished with **1 failed,
52 deselected, 0.79 seconds**. Its journal SHA-256 is
`586138094487e889b5dc0af8ad2238741ae3f7d241db870a4867109308d031b4`; the fixture diagnostic log
`wifi-e2e-de13qg9b/udev-diagnostic.log` has SHA-256
`f5583a28c91fa478dc0ed2a8475a646c496c4c7ebfd9a53550ec8baaebfb172a`.

The diagnostic recorded original DUT `wlan3`, ifindex 1038, and `/run/udev/data/n1038` before the radio move.
That record had the initialization timestamp and link properties but no `NM_UNMANAGED`. After the move and rename,
the ifindex remained 1038 but the live shared udev database no longer contained `n1038`; live udev information
correctly named `wlan0`. Its snapshot also retained the old `ID_NET_NAME=wlan3` and `SYSTEMD_ALIAS`, so the repair
keeps the complete initialized database keyed by the stable ifindex rather than inventing per-radio property rewrites.

The runner now waits up to five seconds for udev, snapshots initialized `/run/udev/data` before radio moves, and binds
that private snapshot read-only into isolated `/run/udev`. The snapshot trial at
`results/20260927T223312757380Z-17c5a1b3b731-hwsim` advanced through the initial NetworkManager connection and HTTP,
then the UI connection, metering, and shutdown. It still finished **1 failed, 52 deselected, 10.34 seconds** at the
explicit handback: `managed yes` was issued at 22:33:23.059, `connection up` at .076, while NetworkManager reported
supplicant ready and disconnected at .079. Its journal SHA-256 is
`a935c2cb80e1ebafdc6a4c2596e3aee5230622d3f01a0c829c012ff1607099a3`.

The test waits, without sleeping or retrying the activation, for numeric `GENERAL.STATE` 30 through 100 after its
single `managed yes`. The one-case diagnostic at
`results/20260927T223956391447Z-17c5a1b3b731-hwsim` passed with **1 passed, 52 deselected, 16.89 seconds**. Its
fixture metering log has SHA-256 `c67d8f25104741897c7cb4b9babb604390ffbdf3cd34da4e4eace7764fe56ef5` and records a
mode-0600 persistent profile containing `metered=1`, while NetworkManager still reported `unknown` after the UI setter
and after `managed yes`. One `nmcli connection reload` changed that cache value to `yes`, which remained after the
existing single `connection up`. The permanent harness retains only that one reload after readiness before the existing
activation, HTTP, and persistence assertions; its temporary diagnostics were restored exactly.

### Netplan setup failure after initialized-NetworkManager coverage

The broader 44-case post-repair run completed with **43 passed, 1 failed, 9 deselected, 293.88 seconds**. Its sole
failure was `test_forget_removes_every_persistent_source[True-netplan]` during fixture setup at `netplan generate`,
before the Forget operation. The one-case stderr diagnostic at
`results/20260927T224905525470Z-17c5a1b3b731-hwsim` finished with **1 failed, 52 deselected, 0.84 seconds** and
captured `ERROR: cannot create directory /run/udev/rules.d: Read-only file system`, followed by the daemon-reload
failure. The original whole-directory read-only udev bind therefore prevented Netplan setup; it was not Forget
behavior evidence.

The runner now leaves its private `/run/udev` writable and binds only the copied initialized `/run/udev/data` subtree
read-only. This preserves the stable-ifindex udev data needed for the NetworkManager handoff while permitting
Netplan's private `rules.d` directory. The final narrowed-mount group at
`results/20260927T225020838235Z-17c5a1b3b731-hwsim` passed with **44 passed, 0 failed, 9 deselected, 303.93 seconds**,
exit code 0. It used source `17c5a1b3b7318aebc034ed1ed695495dccbc07b2` and harness SHA-256 values
`a9d88f62b3e266e61508bf09548fcceb40b9e883ba01795b409610e71aa132e8` (`run_wifi_e2e.sh`),
`2023136f03643e20dd4901cb6367e9f05926de91b61c8e2966d117c9e682c6b2` (`wifi_e2e.py`), and
`48f50174d8fb87ee4df6b49cd5172826f2efbf97041c527775f73d1cd9eb192b` (`test_wifi_e2e.py`). The executable invocation was
`sudo env PATH="$PATH" WIFI_E2E_VM=1 python3 /workspace/openpilot-wifi-validation/run.py --checkout /workspace/openpilot --sha 17c5a1b3b7318aebc034ed1ed695495dccbc07b2 --suite hwsim --filter 'not rejected_tethering_password_completes_ui and not switch_saved_networks and not dhcp_timeout_then_another_selection and not (forget_removes_every_persistent_source and False)'`.
The group collected 53 tests and intentionally excluded nine, so it is green coverage of the stated 44-test scope,
not a green all-53 claim.

### Completion barriers and recovery readiness

- The worker can capture the single thread started by selected asynchronous setters and join it with a 35-second operation budget. Setter calls use a 40-second socket timeout so the caller does not expire before that barrier; ordinary requests retain their 15-second timeout. Metering and tethering-password tests use this harness-only completion barrier instead of waiting for `networks_updated`, which is not a setter-completion callback. Persistence, state, and client assertions remain in place.
- The DHCP timeout case alone now waits 50 seconds for the specified 45-second source timeout before expecting `disconnected`.
- The udhcpc recovery case waits for a new pid **and** a metric-600 wlan0 default route plus the expected resolver before its existing connected-state and HTTP assertions. A new pid alone could coexist with stale manager-visible IPv4 state.

### Test contracts reconciled with the specification

- A failed profile removal still emits `forgotten(ssid)`, while the test retains both saved-state and exact profile-byte preservation checks.
- A hidden missing-network request while tethering turns the AP off and remains CONNECTING with the target unsaved; the test checks that state instead of expecting tethering to remain active.
- Saved-profile authentication failure uses `activate_connection` after replacing the AP with a wrong password, preserving the existing profile-byte assertion. A separate replacement failure test covers `connect_to_network`'s specified forget-first behavior before authentication fails.
- The new-profile write-failure test observes the harness `save_failed` instrumentation from the failed profile write, then requires connected status and IPv4, no saved profile, no `activated` callback, and working HTTP. The instrumentation is harness-only and records the actual write exception.

## Focused source validation after the baseline

- `389be2b0`: status-refresh repair. The focused source suite went red at **86 passed, 1 error**, then green at **87 passed**.
- `1542b525`: escaped-PSK NetworkManager keyfile repair. The focused source suite went red at **87 passed, 1 failure**, then green at **88 passed**; Ruff and ty were green. An earlier NameError came from test setup and was corrected before the behavior red run, so it is not treated as behavior evidence.
- The real escaped-PSK NetworkManager hwsim case passed at `results/20260927T213141625888Z-1542b52525b0-hwsim`: **1 selected, 52 deselected, 5.76 seconds**.
- `17c5a1b3b7318aebc034ed1ed695495dccbc07b2`: post-association `ENABLE_NETWORK <id> no-connect` candidate. The focused source suite went red at **88 passed, 1 failure, 24.54 seconds**, then green at **89 passed, 24.63 seconds**; Ruff and ty passed. The real switch case still failed at `results/20260927T215300417475Z-17c5a1b3b731-hwsim`: **1 failed, 52 deselected, 39.72 seconds**, ending back on Test A. Numeric `no-connect` is therefore insufficient and is not accepted specification behavior.
- Causal switch trace: `trace/tmp/wifi-causal-lease-switch-worker.vET2f6` failed with **1 failed, 52 deselected, 39.45 seconds**. Worker 168671 matched the DUT network namespace. Test B was CONNECTED as id 1 at `1790546249.729`; the only later enable operations were `ENABLE_NETWORK 0 no-connect` and `ENABLE_NETWORK 1 no-connect` at `.832`. The periodic scan ran from `1790546251.058` to SCAN-RESULTS at `.452`, followed by Test B disconnect and Test A connect. No new select or enable command was recorded. Runtime-priority policy remains an open decision.
- The validated source tree is clean at `17c5a1b3b7318aebc034ed1ed695495dccbc07b2`, tree `1cb7857d3550ad4120dd1d6cb5e0cc177d639793`.

These are focused checks. The complete post-repair hwsim matrix has not run, so no full-matrix or CI-green claim follows from them.

## Plan deviations and current scope

The 2026-09-27 repair work made the following evidence-backed changes to the original plan. This list distinguishes
accepted behavior from a source candidate that remains rejected by hwsim evidence.

- **CI getter:** the UI-report path can read `tethering_password` before hotspot lifecycle setup. The getter now reads a
  matching cached AP profile under the existing lock and returns `""` when absent; it neither creates nor writes a profile.
  Explicit initialization, setter calls, and activation-time provisioning retain their write behavior. This corrects the
  generic-runner `sudo install` failure from the earlier getter path.
- **Failed profile save:** after a profile write fails, the manager clears pending state and refreshes actual `STATUS`
  without forcing a disconnect. The status remains CONNECTED only while STATUS still reports station IPv4; no activated
  callback is emitted for the unsaved profile. This is the `389be2b0` status-refresh repair with the 86-pass/one-error to
  87-pass focused source result recorded above.
- **GLib keyfile encoding:** profile serialization and decoding handle backslashes, literal spaces, newline, tab, and
  carriage return. The contract is intentionally limited to those characters, rather than a generic whitespace claim.
  This is the `1542b525` escaped-PSK repair and its source and hwsim evidence above.
- **Selection candidate, not accepted:** numeric post-association `ENABLE_NETWORK <id> no-connect` was unit-green but
  integration-red in the switch case. It is retained only as causal evidence; it is not an adopted selection policy or a
  claim that saved-network switching is fixed.
- **Harness fixture and contract corrections:** the isolated fixture now binds its netplan storage at the manager's real
  path, generates the matching `netplan-NM-` keyfile form, applies profile write faults inside the worker mount namespace,
  snapshots initialized udev data before radio moves, keeps bash as PID 1 for orphan reaping, and uses bounded operation,
  DHCP, daemon-recovery, and NetworkManager-handoff readiness barriers. The handoff reload is a single cache reload after
  readiness before the existing activation. Contract updates preserve bytes and saved state on failed Forget, separate
  saved-auth and replacement-failure paths, expect AP-off CONNECTING for a hidden missing network, and observe completed
  failed saves before asserting current STATUS, profile, callback, and HTTP outcomes. Clearing NetworkManager runtime
  device state remains hygiene, not an established cause.
- **Local CI replay:** the archive contains the failed local UI-report attempts due to missing coverage, the declared
  local `coverage==7.15.4` installation, and successful normal and `--big` replays. Remote CI was not rerun.

Two policy decisions remain open: invalid-hotspot-password rejection behavior, and the runtime priority/reselection
policy needed for saved-network switching after periodic scans. No code or specification policy change for either is
claimed here.

## Pending scope

The invalid-hotspot-password rejection cases remain unchanged pending a separate behavior decision. The unaffected
44-case hwsim matrix from `17c5a1b3b7318aebc034ed1ed695495dccbc07b2` completed with 37 passed, 7 failed, and
9 deselected, as recorded above. The later narrowed-mount 44-case verification is recorded above; its nine excluded
tests remain outside that green scope. No invalid-password policy change or commit has been made from this evidence
folder.
