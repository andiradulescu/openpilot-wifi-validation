# DHCP route-priority implementation handoff

For firstmate. BLOCKED on the permanent NM harness prerequisite and its runner scope. The source fix is committed and its worktree is clean. No done status is claimed.

## Source and scope

- Isolated worktree: `/Users/andiradulescu/.treehouse/openpilot-c4d26a/2/openpilot`. Both `pwd -P` and `git rev-parse --show-toplevel` matched before any mutation.
- Branch: `fix/wifi-route-priority`.
- Exact base: `510f9b76b63800756c0258acad794cfa9623d08f`; availability was verified before `git checkout -b fix/wifi-route-priority 510f9b76b63800756c0258acad794cfa9623d08f --`.
- Incremental source commit: `c47761b0b51e8965a067aed71001fd09471579c0`, `wifi: install DHCP routes at metric 600 from the start`, author Andrei Radulescu <andi.radulescu@gmail.com>.
- The existing `d92b0a572` implementation and `510f9b76b` test commits remain unchanged. `wifi-wpa-supplicant` still resolves to the exact base. No rebase, squash, landing, push, forge write, deployment, physical access or VM lifecycle action occurred.
- Full source diff: only `openpilot/system/ui/lib/udhcpc.script` (+30/-9) and `openpilot/system/ui/lib/tests/test_wifi_manager.py` (+98/-35), total +128/-44. `wifi_manager.py` is unchanged, including its public interface.
- Complete committed diff and refreshed status were inspected. Source worktree is clean.

The hook assigns the lease using `ip addr replace ... noprefixroute`, then installs the connected unicast prefix and default directly at metric 600. It removes old lease addresses on IP/prefix change, keeps same-subnet renew idempotent, retains MTU/broadcast handling, uses an onlink default for /32, and removes obsolete defaults when the lease has no router. Bound/renew retain the stock resolver payload and its resolvconf/file fallback. Deconfig, leasefail, nak and unknown events still execute the stock script, retaining cleanup and error status. No `arp_announce` setting was added.

Tests cover the initial installation order and metric, renew and /32, router selection, resolver payload and file fallback, absence of a router, stock cleanup/error delegation, executable mode, and successful manager startup when optional nmcli returns command-not-found. The unit fixture substitutes only resolver paths to prevent host writes and records network command boundaries. Real Linux integration runs use the unchanged production hook bytes.

## Evidence and red/green results

All evidence paths below are relative to `/Users/andiradulescu/Projects/firstmate/data/wifi-route-priority/`.

Original report and physical-control JSON were read completely. Original evidence archive SHA-256 was verified as `4b562f411d5445de0a719ed98ee76373e6772f685fa585975d3ee5ed3aa4581b`; its runnable lab was reused. No new design-only scout ran.

The VM was accessed only with:

```sh
ssh -p 2222 -o BatchMode=yes -o ConnectTimeout=5 -o UserKnownHostsFile=/private/tmp/wifi-e2e-20260926-known-hosts -o StrictHostKeyChecking=yes ubuntu@127.0.0.1
```

No trust-store changes, accept-new, device access, or parent-owned QEMU start/stop/reboot occurred. New VM material is under `/tmp/wifi-route-priority-20261016-1620`. The old lab directory was not changed.

### Initial real-network matrix

Exact lab command pattern, invoked over that SSH connection from the isolated host root:

```sh
sudo python3 /tmp/wifi-route-priority-20261016-1620/lab.py \
  /tmp/wifi-route-priority-20261016-1620 TRIAL MODE HOOK
```

`MODE` was `no-nm` or `nm`. Red used the copied unchanged base hook at `/tmp/wifi-route-priority-20261016-1620/udhcpc.script`; green used the exact candidate at `/tmp/wifi-route-priority-20261016-1620/source/openpilot/system/ui/lib/udhcpc.script`. SSH's remote lab cwd for these four initial runs was `/home/ubuntu`; all source runner/check commands used the isolated source root. Lab command/output details are in each trial's `commands.jsonl`.

| Trial | Exit | Cycles | Metric-0 unicast installs | Ethernet prefix deletions | Wired-source UDP seen through WLAN | WLAN ARP claiming wired IP |
|---|---:|---:|---:|---:|---:|---:|
| red-no-nm | 1, expected regression | 10 | 30 | 0 | 25 | 9 |
| red-nm | 1, expected regression | 10 | 30 | 1 | 775 | 13 |
| green-no-nm | 0 | 10 | 0 | 0 | 0 | 0 |
| green-nm | 0 | 10 | 0 | 0 | 0 | 0 |

Each cycle runs deconfig, bound, and same-subnet renew. Each green trial observed 30 WLAN unicast route installations, all metric 600, and 30 source-bound peer lookups through Ethernet. Captures contain 1335 wired UDP frames in green-no-nm and 1358 in green-nm, zero wired-source frames emitted through WLAN. Offline analysis also verified every deconfig snapshot had no WLAN IPv4 address or route. Classless routes survive same-subnet renew. DNS integration receives the expected add/delete requests and lease payload. Host uplink routes and resolver hashes matched before/after every trial; task namespaces/processes were removed.

`evidence/red-no-nm.log`, `red-nm.log`, `green-no-nm.log`, `green-nm.log` retain raw output. `evidence/first-matrix.tar.gz` retains the runnable lab, commands, copied hooks, netlink logs, pcaps, private NM logs/strace, snapshots and results, excluding copied system udev state and sockets. `analyze_matrix.py` parses packet bytes and snapshots; `evidence/matrix-summary.json` records its assertions and counts.

The no-NM case has no NM daemon in the DUT, non-executable bind masks over nmcli/NetworkManager, and an isolated /run with no system-bus socket during hook execution. **It simulates package absence; the VM image still has the NM package outside those namespaces.** The NM case runs real NM owning DHCP Ethernet `.199`, WLAN unmanaged `.108`, and a common bridged L2 with peer `.171`. Traffic runs throughout hook execution. This is stronger than checking final routes.

Both initial green trials used wlan0.arp_announce=0. Correct route installation and the packet evidence remove the demonstrated need for announce=2 in this reproduction. This is not a claim that announce=2 can never be useful elsewhere or that hardware acceptance has occurred.

### Source unit, lint and type checks

Host: macOS 27.0.1 arm64; Python 3.12.13; Ruff 0.16.3; ty 0.0.72 (62ebbecc7). VM: Ubuntu arm64, kernel 6.8.0-142-generic; Python 3.12.13; Ruff 0.16.3; ty 0.0.72. The prior evidence matched VM/device BusyBox and NM binary hashes; this task reuses those installed prerequisites.

Host source cwd for every command: isolated worktree root. VM source cwd: `/tmp/wifi-route-priority-20261016-1620/source`. The VM source snapshot comes from `git archive` of the exact base, with the task files copied byte-for-byte. The existing native Params library was reused, not replaced by a fake module; SHA-256 `b7951ba2752bdfa11b611bcefd02e918516711edddea00be3edae48019c81f3d`. The library and existing venv are validation prerequisites, not source-branch changes.

| Command | Result | Evidence |
|---|---|---|
| `uv sync --frozen` before submodule initialization | exit 1, uninitialized opendbc_repo, no test executed | evidence/uv-sync.log |
| `GIT_LFS_SKIP_SMUDGE=1 git submodule update --init --recursive` | exit 0, declared pinned submodules only; firstmate explicitly authorized this prerequisite | evidence/submodule-init.log |
| `uv sync --frozen` after initialization | exit 0 | evidence/uv-sync-after-submodules.log |
| `uv sync --frozen --extra testing` | exit 0 | evidence/uv-sync-testing.log |
| Host `.venv/bin/python tools/test_runner.py openpilot/system/ui/lib/tests/test_wifi_manager.py -k installs_routes_at_wifi_metric -v` | 1 collection error: missing native libparams_c.dylib; environment failure, not test red | evidence/red-unit.log |
| VM `PYTHONPATH=$PWD .venv/bin/python tools/test_runner.py openpilot/system/ui/lib/tests/test_wifi_manager.py -k installs_routes_at_wifi_metric -v` with unchanged hook | 1 failed test, 3 expected subcase failures, missing noprefixroute installation | evidence/red-unit-vm.log and red-unit-vm-final-test.log |
| VM `PYTHONPATH=$PWD .venv/bin/python tools/test_runner.py openpilot/system/ui/lib/tests/test_wifi_manager.py -v` | 95 passed, 0 failures/errors/skips, exit 0; final source run 24.45 s | evidence/final-source-checks-vm.log |
| Host `.venv/bin/ruff check openpilot/system/ui/lib` | exit 0, all checks passed | evidence/final-ruff-host.log |
| Host `.venv/bin/ty check openpilot/system/ui/lib/wifi_manager.py` | exit 0, all checks passed | evidence/final-ty-host.log |
| VM `.venv/bin/ruff check openpilot/system/ui/lib` | exit 0 | evidence/final-source-checks-vm.log |
| VM `.venv/bin/ty check openpilot/system/ui/lib/wifi_manager.py openpilot/system/ui/lib/tests/test_wifi_manager.py` | exit 0 | evidence/final-source-checks-vm.log |
| `sh -n openpilot/system/ui/lib/udhcpc.script` and `git diff --check` | exit 0 | executed from isolated root, final audit |

The final source byte hashes match between host and VM:

| File | SHA-256 |
|---|---|
| udhcpc.script | `14bb8751186ddc501656e21877fff149ba52b6e3e55fb994ca7b46a948667ae0` |
| wifi_manager.py, unchanged | `0d5715aa1f3dc926e444f98204a055a4658844aa7f03b65e358123a82fc67b25` |
| test_wifi_manager.py | `f6e1baa051ed57e11ebbcc4e8337d47930bb7882187eba16bb77b798d67fc72b` |

Machine-readable source state and bundle hash: `source-manifest.json`.

## Harness and extended checks

Harness ownership is limited to `wifi_e2e.py` and `test_wifi_e2e.py` in `/Volumes/Stuff/openpilot-extra/openpilot-wifi-validation`, branch `wifi-v3`, starting HEAD `185c5e216d6f53bdc027d30f3db7cde20d906d8b`. Initial state was only pre-existing untracked `vm/`; that directory was not edited or staged. No harness file enters the source branch.

Permanent cases `test_route_priority_during_dhcp[no-nm]` and `[nm]` retain the established real same-L2 lab, transient unicast route checks, wired UDP and ARP checks, NM ownership, DNS and cleanup. They additionally exercise /32, lease renumbering, changed subnet, absent router, resolver fallback, MTU/broadcast, and leasefail/nak preserving routes. They require a private mount namespace in the disposable VM. No end-to-end network behavior is mocked; DNS destinations are isolated to avoid host writes.

The permanent tests were also exercised against a private bind mount of the unchanged base hook. `evidence/red-permanent-3.log` records 2 expected failures, 53 deselected, both due to observed unicast metric-0 route installs. The earlier permanent red attempts are retained but are not counted as clean bug evidence: one had an accidental test-local action reference, and one NM setup used an overlong filesystem D-Bus socket path. The final helper uses a process-specific Linux abstract D-Bus address in the DUT namespace.

Extended lab development exposed three independent test setup/classification defects, preserved in `edge-no-nm.log`, `edge-no-nm-2.log`, and `edge-no-nm-3.log`: `ip -j -4 addr show` returns an empty list when no IPv4 address remains; mounting /run after the resolver bind hides its target; and local broadcast routes were incorrectly included in the metric assertion. The resolver is now bound after private /run setup, and only unicast connected/default routes are classified. The actual fallback bytes and expected DNS assertion were preserved. Firstmate explicitly confirmed the local/broadcast classifier correction. These were not production failures and were not counted as green runs.

Full hwsim results and the concrete remaining blocker are recorded below. Harness edits remain uncommitted because the NM gate is not green. The first full-suite attempt stopped during collection with missing opendbc because the archived source contains empty submodule entries. The corrected launch privately mounts the approved VM venv and declared submodules read-only, then exposes the isolated snapshot at `/workspace/openpilot` and the copied harness at `/workspace/openpilot-wifi-validation`. This keeps the isolated source visible outside /tmp while the standard runner masks /tmp, without changing shared checkout bytes; the complete wrapper is `full-hwsim.sh`. No `--allow-dirty` or misleading candidate `--sha` claim is used.

## Authorized departures and limitations

- The explicit two-configuration requirement supersedes the old stock-first/post-hoc metric amendment. Bound/renew therefore own address and route installation and retain stock-equivalent resolver integration; the other events still delegate to stock. The old post-stock command-sequence test was updated for this intentional behavior change, retaining final metric, /32 and cleanup checks and adding direct-install/DNS coverage.
- The approved feature-base exception is used exactly: local branch at the exact base, no master rebase, promotion or landing. Existing base history is preserved with one incremental source commit.
- The current brief narrows source edits to three files; only two were needed. No new production module, dependency, public API, UI/hardware edit, profile format change, ARP sysctl, README, spec or plan edit was made.
- Native unit execution moved to the approved Linux VM after the explicit macOS native-library limitation. Source bytes and executed cwd are recorded, with hashes rather than a dirty-tree SHA claim.
- No-NM package removal is simulated by mount masks and absence of service. The image does not prove a distribution that physically omits the package.
- Kernel 6.8 VM and virtual links/radios do not prove AGNOS 4.9 behavior on comma hardware. The physical control was one older sequence with temporary announce=2 and incomplete initial-enable capture. No physical acceptance of this source exists.
- No independent reviewer was invoked, as directed. Firstmate retains review and all device decisions.

## Preserved state and parent procedure

The primary source checkout was never written. Its pre-existing deleted `big_driving_supercombo.onnx` remains absent, and `REVIEW.md` remains present with SHA-256 `d7fa86c89b57b6fc373a55feb8657cb96e22c2e80c7951bade5b8422e88f0198`. The source task worktree had no pre-existing edits; it is clean after the local commit. The validation harness's pre-existing untracked `vm/` is untouched. VM host routes/resolver checks accompany each completed lab trial. Existing source checkout and dependency directories were only read or privately bind-mounted.

Proposed parent-only deployment/reboot/acceptance/rollback steps are in `device-procedure.md`. They require `/data/params/d/IsOffroad == 1`, strict wired access, preflight/recovery evidence, exact bundle/readback hashes, reboot to remove the temporary announce=2 control, and fresh route/ARP capture through hotspot enable, active password change, and hotspot off/station DHCP. Firstmate will prepare/review the bounded ETH_P_ALL collector, which filters and logs ARP only without promiscuous mode; the old ETH_P_ARP-only receiver does not establish full outgoing coverage. No device action has been executed.

Local bundle `fix-wifi-route-priority.bundle` was verified with `git bundle verify`; it contains `fix/wifi-route-priority` at the source commit, requires the exact base commit, and has SHA-256 `011c32dc2ff08d4a0a65c6bb18a0baf48751dd065a7fde497f2bc0e52f277f11`.


## Final validation outcome and blocker

The exact source commit remains `c47761b0b51e8965a067aed71001fd09471579c0`, with a clean source worktree. The harness remains at base `185c5e216d6f53bdc027d30f3db7cde20d906d8b` with only the two authorized tracked files modified (+401/-0) and the original untracked `vm/`. No harness commit has been created; no failing test or production assertion was removed. `source.diff` and `harness.diff` preserve the complete current diffs. Current harness hashes are in `evidence/current-harness.sha256`; host lint, syntax compilation, and diff checks pass.

The full hwsim command, executed from the isolated source snapshot root over strict SSH, was:

```sh
cd /tmp/wifi-route-priority-20261016-1620/source
bash ../full-hwsim.sh
```

The wrapper exposes the isolated snapshot and dependencies through private mounts, then executes:

```sh
env WIFI_E2E_VM=1 OPENPILOT_ROOT=/workspace/openpilot \
  WIFI_E2E_LOG_DIR=/workspace/openpilot-wifi-validation/task-results \
  bash /workspace/openpilot-wifi-validation/run_wifi_e2e.sh \
  --junitxml=/workspace/openpilot-wifi-validation/task-results/full-hwsim.xml
```

Result: **53 passed, 2 failed**, exit 1, 418.92 s. All 53 existing virtual-radio cases passed, including shared-subnet routing, station DHCP, profile persistence, DNS/HTTP, service recovery, hotspot transitions, and forwarding. The two added routing cases failed in harness setup. Raw log `evidence/full-hwsim-2.log` and `evidence/full-hwsim.xml` retain the result. This is not an all-green full run.

As firstmate observed, that suite had staged older harness bytes before later local safety/DNS fixture edits. Hash comparison is retained in `evidence/full-run-harness-previous.sha256` and `evidence/final-harness-host.sha256`. The completed full run was not mutated while active. The two affected cases were rerun with matching current host/VM hashes and child stdout/stderr included in assertions:

```sh
cd /tmp/wifi-route-priority-20261016-1620/source
bash ../harness/full-hwsim.sh -k route_priority_during_dhcp \
  --junitxml=/workspace/openpilot-wifi-validation/task-results/route-final.xml
```

Result: **1 passed (no-NM), 1 failed (NM), 53 deselected**, exit 1, 6.28 s; `evidence/route-final.log`. The no-NM case proves all/eth0/wlan0 announce=0, /32, renumbering, subnet change, no-router cleanup, real file fallback, MTU/broadcast, same-subnet classless-route preservation, wired and WLAN traffic, no wired-source WLAN frames, and no Ethernet prefix deletion. A subsequent harness-only edit retains case directories under the existing external log directory; it does not change those behavioral assertions. The final current NM case still fails before DHCP hook behavior can run.

### NM is enumerated but never becomes initialized in the runner view

At firstmate's direction, one NM-only diagnostic retained the private logs and another inserted a bounded 5-second pause after GENERAL.RUNNING before device inspection. This was a temporary task-data diagnostic copy, not a production change or a weakening of the test. No further NM execution followed that diagnostic.

- `evidence/nm-readiness.log`: 1 failed setup, 54 deselected, 1.29 s.
- `evidence/nm-bounded-wait.log`: 1 failed setup, 54 deselected, 6.22 s.
- `evidence/nm-bounded-wait-extract.log`: exact device and udev facts.
- `evidence/standalone-udev-extract.log`: comparison from the passing standalone NM trial.
- `evidence/harness-diagnostics.tar.gz`: private NM logs, strace, generated scripts, command/device output, and JUnit files; copied udev database excluded. SHA-256 `f05e90a1f01a05071b21ae3a1ebd1a29e9bbb802f1ef1ae9b57a7e75cbdf1d96`.

NM enumerates the failing interface as a real `NMDeviceVeth`, ifindex 439, and logs:

```text
[1792167755.1338] ... 439: eth0@other-netns ... veth* not-init ...
[1792167755.4126] ... (eth0): unmanaged: flags set to [platform-init,!sleeping=0x4/0x5/unmanaged/unrealized] ...
[1792167755.4129] manager: (eth0): new Veth device ...
[1792167755.4350] manager: startup complete is waiting for device 'eth0' (link-init)
[1792167760.7607] manager: startup complete is waiting for device 'eth0' (link-init)
```

The device query **5.0138 seconds after GENERAL.RUNNING** still reports state `10 (unmanaged)`, `GENERAL.NM-MANAGED: no`, and `/virtual/device/placeholder/1`. The copied udev view has `n1,n2,n433,n434,n435,n436,n437` and **no n439**. Activation exits 4 with `No suitable device found for this connection`. This is not solved by waiting for daemon RUNNING or by merely enumerating eth0.

The passing standalone NM run logs `udev-add[eth0,36]: device added` followed by clearing `platform-init`. It creates each veth, runs udevadm settle against the real host view, and copies initialized udev data before moving that link. In contrast, `run_wifi_e2e.sh:48-59` freezes /run/udev/data before the new route-test veths exist, then bind-mounts that snapshot read-only. The later routing fixture copies the already-frozen view, so it cannot obtain the new per-ifindex record.

### The proposed /proc/1/root live source is unavailable inside this runner

Firstmate authorized a read-only comparison of `/proc/1/root/run/udev/data`. A separate frozen `harness-probe/` directory ran a bounded link-only diagnostic, with an intentional stop **before NM execution**. Canonical source and harness assertions were unchanged. The test created its own veth, compared views for 50 samples, and retained the probe output. From an independent SSH session in the VM host namespace, the real host record was also read while that veth existed.

- Probe ifindex 448: host `/run/udev/data/n448` exists and contains a real initialization timestamp (`I:`).
- Inside the runner, all 50 samples lacked n448 in both `/run/udev/data` and `/proc/1/root/run/udev/data`.
- Inside, `/proc/1/cmdline` is `bash ...run_wifi_e2e.sh --isolated ...`; outside, it is `/usr/lib/systemd/systemd --system ...`. The runner's private PID/proc namespace makes `/proc/1/root` refer to its own frozen mount view, not the VM host view.
- `evidence/udev-probe-host.log`, `udev-probe-summary.log`, `udev-probe.log`, and `udev-probe.tar.gz` retain this comparison. The diagnostic's intentional early stop occurred before moving its first veth, so its own root-namespace veth pair was explicitly removed after verifying ifindex 448. No other link was removed.

### Decision required before another run

Block key: `udev-runner-scope`.

The smallest complete setup correction is to preserve a **separate read-only live host udev view** in `run_wifi_e2e.sh` before it hides /run, while retaining the existing frozen radio snapshot for all old cases. The routing fixture can then wait boundedly for the real per-ifindex record and its initialization timestamp in that live view, copy those actual initialized records before moving each link, and retain its existing private read-only NM mount. Do not fabricate properties, force away platform-init, substitute manual Ethernet for the NM case, weaken the guard, or make NM optional.

This requires adding `run_wifi_e2e.sh` to authorized harness ownership; the current brief allows only `wifi_e2e.py` and `test_wifi_e2e.py`. That file has **not** been edited. Replacing the existing radio snapshot wholesale with a live view is not proposed, since moving radios can remove their host records and affect the 53 existing cases. Alternatively, firstmate could authorize a separate standalone routing invocation outside the outer hwsim snapshot, retaining the 53-case radio result as a separate phase. No choice was made on firstmate's behalf.

After approval, freeze a distinct staged harness directory per run, establish a focused green NM routing result with exact bytes, then run the full final suite on those same frozen bytes. The task is not done until that gate and a green harness commit are complete. No further NM execution or source change is authorized by this handoff alone.

`evidence/final-vm-state.log` confirms the original uplink routes/resolver hash, no task namespaces, no leftover own probe veth, and unloaded hwsim. Parent QEMU remains running. First-matrix archive SHA-256: `568aeb13cbb724010ff58e62c062ee465ca99c17ea0e0519fe5be6f64460cc3d`.

## Final blocked evidence package

Firstmate confirmed that this is a one-file scope expansion requiring an explicit answer. The existing decision key remains `udev-runner-scope`; no second key was created. The task remains BLOCKED and is not done.

- Exact proposal: `runner-proposal.patch`, four added lines in `run_wifi_e2e.sh`, SHA-256 `05df4caf84a03c0f9ad68c8d1a6797d81a407914b339f51ad922cb8f23d4587d`. It preserves a separate read-only live udev bind before /run isolation and leaves the existing frozen view unchanged.
- Accompanying helper change is described in `runner-proposal.md`: bounded waiting for real initialized per-ifindex records, snapshot before moving links, private read-only NM mount and all real-NM/traffic assertions retained. It has not been implemented.
- `git -C /Volumes/Stuff/openpilot-extra/openpilot-wifi-validation apply --check /Users/andiradulescu/Projects/firstmate/data/wifi-route-priority/runner-proposal.patch` passed without applying it. `bash -n` passed on a task-private candidate copy. The project runner still has its original SHA-256 `a9d88f62b3e266e61508bf09548fcceb40b9e883ba01795b409610e71aa132e8` and no diff.
- `validation-manifest.json` preserves the 95-unit pass, both 10-cycle standalone green trials, full hwsim 53 passed/2 failed, focused routing 1 passed/1 failed with 53 deselected, expected reds, and separate setup diagnostics. No diagnostic failure is reported as behavior green.
- The report, manifests, proposal, full diffs, deployment bundle/procedure, runnable lab material and raw evidence are mirrored to `/Volumes/Stuff/openpilot-extra/openpilot-wifi-validation/results/task9-route-priority-20261016/`. `inventory.json` there lists every delivered file hash and excludes itself; every copied file was read back and SHA-256 checked.
- The source branch remains clean at `c47761b0b51e8965a067aed71001fd09471579c0`. Failing harness edits and these blocked result artifacts remain uncommitted. The pre-existing untracked `vm/` was not touched. No runner edit, further NM execution, physical action, or remote publication occurred during this finalization.
