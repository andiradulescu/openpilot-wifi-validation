# DHCP route-priority implementation handoff

For firstmate. Software validation is complete: 95 Wi-Fi unit tests, both routing configurations, and the final full 55-case hwsim suite passed. Source is committed and clean. Physical verification remains a parent-owned proposed procedure.

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

## Final harness validation

Harness branch `wifi-v3` started at `185c5e216d6f53bdc027d30f3db7cde20d906d8b`. Its implementation commit is `8fbb0f73e2b04772eeb7c3c516a3f232ff446482`, author Andrei Radulescu <andi.radulescu@gmail.com>. Exactly three runtime/test files changed, +422/-0: `wifi_e2e.py` (+405), `test_wifi_e2e.py` (+13), and `run_wifi_e2e.sh` (+4). Source and harness diffs are `source.diff` and `harness.diff`. No harness material enters the source branch; the pre-existing untracked `vm/` remains untouched. Results are committed separately under the authorized results path; the containing evidence commit is recorded after creation in the task report.

The permanent routing cases use real same-L2 links and continuous wired-source UDP. Both configurations require all/eth0/wlan0 arp_announce=0. They check intermediate unicast netlink installations, 30 source-bound wired lookups, absence of Ethernet prefix deletion, WLAN-bound traffic, ARP and DNS, deconfig, same-subnet renew, /32, lease renumbering, changed subnet, no router, file resolver fallback, MTU/broadcast, and nak/leasefail semantics. No routing assertion was removed or weakened.

The unchanged-hook permanent regression previously failed in both configurations: 2 failed, 53 deselected, exit 1 (`evidence/red-permanent-3.log`), due to observed metric-0 unicast installs. The raw earlier fixture failures are retained separately. Initial standalone red/green and unit red evidence above predate the source fix.

On Oct 18 firstmate explicitly approved the exact four-line `runner-proposal.patch` and companion helper change in inbox 015, resolving `udev-runner-scope`. The runner now preserves a separate live read-only udev bind before hiding /run. The helper reads genuine ifindexes before moving each veth pair and waits at most five monotonic seconds for their real nonzero `I:` initialization timestamps. It copies actual initialized records into the existing private read-only NM snapshot. Missing input fails setup; no metadata is fabricated and NM still owns DHCP Ethernet while WLAN remains unmanaged. The 53 existing radio cases keep the original frozen udev view.

Frozen harness directory: `/tmp/wifi-route-priority-20261016-1620/harness-approved-20261018-1540`. The five-file input manifest matched host and VM before the focused run and after the full run; runtime scripts were also rechecked between runs. Files were never edited during either run. The source snapshot is exact committed source; the wrapper privately exposes it at `/workspace/openpilot`, with the existing venv and six declared submodules mounted read-only. Actual pytest cwd is `/workspace/openpilot`; SSH launch cwd is `/tmp/wifi-route-priority-20261016-1620/source`.

Refreshed VM environment: Ubuntu arm64 kernel 6.8.0-142-generic, Python 3.12.13, pytest 9.1.1, Ruff 0.16.3, ty 0.0.72, NetworkManager 1.46.0. `evidence/approved-preflight.log` and `approved-final-vm-state.log` retain environment, input/source hashes and management state.

```sh
timeout 180 bash ../full-hwsim-approved.sh focused -k route_priority
timeout 900 bash ../full-hwsim-approved.sh full
```

Both are invoked over the strict SSH command above. `full-hwsim-approved.sh` contains the exact private mounts and runner invocation. The first run adds `-k route_priority`; both use `WIFI_E2E_VM=1 OPENPILOT_ROOT=/workspace/openpilot`, the standard runner, a phase-specific external log directory and JUnit path. No `--allow-dirty` or candidate SHA claim is used.

| Check | Result | Raw evidence |
|---|---|---|
| Approved focused routing | 2 passed, 53 deselected, 0 failed/errors/skips, exit 0; 9.845 s by JUnit | evidence/approved-focused.log and .xml |
| Final complete hwsim | 55 passed, 0 failed/errors/skips, exit 0; 430.341 s by JUnit | evidence/approved-full-hwsim.log and .xml |
| Harness Ruff E/F/W, Python syntax, bash -n, source/harness diff checks | exit 0 | evidence/approved-local-audit.log |

The exact harness static commands from the isolated source root were `.venv/bin/ruff check --config 'lint.select=["E","F","W"]' /Volumes/Stuff/openpilot-extra/openpilot-wifi-validation/wifi_e2e.py /Volumes/Stuff/openpilot-extra/openpilot-wifi-validation/test_wifi_e2e.py`, `bash -n /Volumes/Stuff/openpilot-extra/openpilot-wifi-validation/run_wifi_e2e.sh`, Python `compile()` on both changed Python files without writing caches, `git diff --check`, and `git -C /Volumes/Stuff/openpilot-extra/openpilot-wifi-validation diff --check`.

The final full run includes all 53 existing station, hotspot, DHCP/DNS/HTTP, persistence, recovery and forwarding cases plus both routing cases. Prior `53 passed / 2 setup failed` and `1 passed / 1 setup failed` results are retained as history, not counted as final green.

Offline packet and snapshot read-back for the four final routing trials:

| Trial | Cycles | WLAN unicast installs, all metric 600 | Wired UDP | WLAN UDP | Wired UDP over WLAN | WLAN ARP claiming wired IP |
|---|---:|---:|---:|---:|---:|---:|
| focused/nm | 10 | 35 | 1371 | 18 | 0 | 0 |
| focused/no-nm | 10 | 35 | 1309 | 16 | 0 | 0 |
| full/nm | 10 | 35 | 1345 | 18 | 0 | 0 |
| full/no-nm | 10 | 35 | 1312 | 17 | 0 | 0 |

All four trials preserved 30/30 wired lookups, observed zero Ethernet prefix deletions, had clean deconfig snapshots and unchanged host routes. `evidence/approved-matrix-summary.json` records genuine initialized ifindexes and packet counts; `analyze_approved_matrix.py` reproduces the offline assertions. `evidence/approved-hwsim-artifacts.tar.gz` contains both phase results, commands, packet captures, private service logs/strace, generated hook scripts and snapshots. Copied host udev databases and sockets are excluded. Pre/post VM state logs verify unchanged management routes/resolver, no task namespaces/veths, and unloaded hwsim. Parent QEMU lifecycle was never touched.

## Resolved harness failure history

Earlier full hwsim had 53 passes and two fixture setup failures. A matching focused rerun had one no-NM pass and one NM setup failure. NM-only readiness and bounded-wait diagnostics each had one setup failure, 54 deselected. The runner froze udev data before new veth creation: NM enumerated eth0 but could not clear platform-init without its genuine initialized per-ifindex record. A five-second daemon wait did not help. A link-only 50-sample probe proved /proc/1/root also sees the runner's private PID/mount view, while the host independently had the initialized record. No NM hook behavior was claimed for those failed setups.

The exact proposal and causal evidence were reviewed before expansion to run_wifi_e2e.sh. Prior reports/manifests are preserved under `evidence/blocked-handoff-20261016/`; raw failures, diagnostics and archives retain their original paths. `runner-proposal.md` is the historical proposal, not a current gate. The explicit approval and resolved status supersede its hold. No production change followed source commit c47761b0b.

## Authorized departures and limitations


- The explicit two-configuration requirement supersedes the old stock-first/post-hoc metric amendment. Bound/renew therefore own address and route installation and retain stock-equivalent resolver integration; the other events still delegate to stock. The old post-stock command-sequence test was updated for this intentional behavior change, retaining final metric, /32 and cleanup checks and adding direct-install/DNS coverage.
- The approved feature-base exception is used exactly: local branch at the exact base, no master rebase, promotion or landing. Existing base history is preserved with one incremental source commit.
- The current brief narrows source edits to three files; only two were needed. No new production module, dependency, public API, UI/hardware edit, profile format change, ARP sysctl, README, spec or plan edit was made.
- Native unit execution moved to the approved Linux VM after the explicit macOS native-library limitation. Source bytes and executed cwd are recorded, with hashes rather than a dirty-tree SHA claim.
- No-NM package removal is simulated by mount masks and absence of service. The image does not prove a distribution that physically omits the package.
- Kernel 6.8 VM and virtual links/radios do not prove AGNOS 4.9 behavior on comma hardware. The physical control was one older sequence with temporary announce=2 and incomplete initial-enable capture. No physical acceptance of this source exists.
- No independent reviewer was invoked, as directed. Firstmate retains review and all device decisions.

- Additional harness ownership of `run_wifi_e2e.sh` and the bounded live-udev helper was explicitly approved Oct 18. This is test setup only; no production scope expanded.
- Harness and results commits are permitted by inbox 015 after green.

## Preserved state and parent procedure

The primary source checkout was never written. Its pre-existing deleted `big_driving_supercombo.onnx` remains absent, and `REVIEW.md` remains present with SHA-256 `d7fa86c89b57b6fc373a55feb8657cb96e22c2e80c7951bade5b8422e88f0198`. The source task worktree had no pre-existing edits; it is clean after the local commit. The validation harness's pre-existing untracked `vm/` is untouched. VM host routes/resolver checks accompany each completed lab trial. Existing source checkout and dependency directories were only read or privately bind-mounted.

Proposed parent-only deployment/reboot/acceptance/rollback steps are in `device-procedure.md`. They require `/data/params/d/IsOffroad == 1`, strict wired access, preflight/recovery evidence, exact bundle/readback hashes, reboot to remove the temporary announce=2 control, and fresh route/ARP capture through hotspot enable, active password change, and hotspot off/station DHCP. Firstmate will prepare/review the bounded ETH_P_ALL collector, which filters and logs ARP only without promiscuous mode; the old ETH_P_ARP-only receiver does not establish full outgoing coverage. No device action has been executed.

Local bundle `fix-wifi-route-priority.bundle` was verified with `git bundle verify`; it contains `fix/wifi-route-priority` at the source commit, requires the exact base commit, and has SHA-256 `011c32dc2ff08d4a0a65c6bb18a0baf48751dd065a7fde497f2bc0e52f277f11`.



## Evidence inventory

The final report, manifests, diffs, runnable lab/analysis/wrapper, incremental source bundle, proposed device procedure, and all raw red/green evidence are mirrored under `/Volumes/Stuff/openpilot-extra/openpilot-wifi-validation/results/task9-route-priority-20261016/`. Its `inventory.json` records SHA-256 and size of every delivered file, excluding itself; every copy is read back and hashed. `source-manifest.json`, `validation-manifest.json`, and `evidence/approved-execution.json` record the exact revisions, commands, environments, counts and coverage boundaries. No push, forge write, merge, promotion, deployment or physical-device command occurred.
