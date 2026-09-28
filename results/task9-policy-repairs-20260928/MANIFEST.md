# Task 9 approved-policy continuation evidence

## Scope and provenance

This folder records the 2026-09-28 continuation after Andi approved two previously open policies:

- an explicitly selected station has runtime preference while saved stations remain enabled as fallbacks; and
- a hotspot password accepts 8 through 63 UTF-8 bytes or a 64-hex-character raw PSK, while rejection preserves the
  previous password and an active hotspot.

The prior fixture, failure, and final 44-of-53 narrowed-mount evidence remains historical at
[`../task9-matrix-repairs-20260927/MANIFEST.md`](../task9-matrix-repairs-20260927/MANIFEST.md). This continuation does
not revise its recorded pending-decision state.

The approved implementation scope sets runtime priority 1 for the chosen station and 0 for other saved stations before
either explicit station `SELECT_NETWORK`; the existing `ENABLE_NETWORK all` keeps every saved station eligible as a
fallback after association. It adds no lifecycle reset or ASCII-only restriction.

## Source TDD evidence

- A preliminary test-model run finished **89 passed, 1 error** with a KeyError. It was superseded and is not behavior
  evidence.
- The faithful adjusted red finished **87 passed, 3 failed** for missing priority handling and restored
  `ENABLE_NETWORK all` expectations. The final two-path red repeated **87 passed, 3 failed in 24.67 seconds**.
- The ordering red finished **89 passed, 2 failed in 24.55 seconds**, covering intended lower-id promotion and the
  corrected exact-network-dictionary expectation. That assertion correction is test setup, not behavior evidence.
- The initial ordered candidate source suite finished **91 passed in 24.46 seconds**, but Ruff reported B023 while ty
  passed. The test-only binding correction is not behavior evidence.
- Runtime-priority repair commit `cbbdc4f17cda0c5ba76524c9e063832cc76023f9`, tree
  `944e3dda3f62ed7cd95c7404f12654864ecdbcf6`, finished **91 passed, 0 failed in 25.46 seconds**; Ruff and ty both
  exited 0. Its manager file SHA-256 begins `219b4f38` and test file SHA-256 begins `48c13531`. Those historical raw
  logs were not recoverable after the VM restart: the exact `runtime-priority-*-17c5a1b3.log` glob and a bounded
  priority-log search both returned zero matches. The recorded result counts remain historical evidence only; they are
  not archived raw-log evidence. The later final 93-case source rerun is separately recorded below.
- The repair gives the chosen station priority 1 and saved fallbacks priority 0 before both explicit selection paths,
  then retains `ENABLE_NETWORK all` after association. It removes the insufficient numeric `ENABLE_NETWORK <id>
  no-connect` workaround that was unit-green but hwsim-red.

- The password-boundary red collected 93 cases and finished **92 passed, 1 failed**. The failing parameterized
  assertion established that three invalid values had been persisted, so it is behavior-red evidence.
- Password validation commit `cc1e0d0d74095dc4b37e6a30950a62602e11d385`, tree
  `c27afcd4dca942fa15a881306d1cedeb3c239d3c`, finished **93 passed, 0 failed in 25.09 seconds**. Ruff and ty
  both exited 0. The manager SHA-256 is
  `0d5715aa1f3dc926e444f98204a055a4658844aa7f03b65e358123a82fc67b25`; the test SHA-256 is
  `8d6a505e5cf952b7f8cb2453d224e6015733cc7c348577b780651b94a2c19c74`.
- A B023 correction bound the per-case lambda value in the test. It corrected test binding only, did not weaken an
  assertion, and is not behavior evidence. The source review found no blockers.
- The raw password red, green, Ruff, and ty logs are preserved in the v4 archive under `logs/` as
  `wifi-password-red-20260928.log`, `wifi-password-green-final-20260928.log`,
  `wifi-password-ruff-final-20260928.log`, and `wifi-password-ty-final-20260928.log`.
- The initial Task 7 squash history has exactly two commits: implementation
  `d92b0a5727a1ae995154521a1e8bb312324032fd` and tests HEAD
  `f8249da3736640b1af52c6cc703bd7810f94602f`. The pre- and post-squash trees are both
  `c27afcd4dca942fa15a881306d1cedeb3c239d3c`; author and committer identity were verified. The host source checkout
  had only untracked `REVIEW.md`. The f824 source was aligned for the complete matrix; the later test-only 510 amend is
  described below.
- After a fresh remote read confirmed expected head `8869c2f5639eaab178954d60c23e939a6c050ceb`, the parent completed
  the approved source-only publication:

  ```text
  git push --force-with-lease=refs/heads/wifi-wpa-supplicant:8869c2f5639eaab178954d60c23e939a6c050ceb andiradulescu HEAD:refs/heads/wifi-wpa-supplicant
  ```

  It exited 0 and the remote readback is `f8249da3736640b1af52c6cc703bd7810f94602f`.
- An independent cumulative review of `8869c2f..f8249da` found no concrete blockers and `git diff --check` was clean.
  The reviewer did not run tests or use a device. The parent also inspected the manager repair delta and agreed with
  that review. The final full-matrix result directory is
  `results/20260928T083536644154Z-f8249da37366-hwsim`; it contains `junit.xml` and `manifest.json`, and completed
  with exit code 0: **53 passed, 0 failed in 413.69 seconds**. Its guest log is
  `/tmp/wifi-final-full53-hwsim-20260928.log`. Relative to base
  `0cf`, the source diff is eight files, 3,258 insertions, and 1,725 deletions; `wifi_manager.py` is 1,119 lines and
  `test_wifi_manager.py` is 2,329 lines.
- Final source unit validation completed with **93 passed, 0 failed in 25.11 seconds** at the final source tree; its
  guest log is `/tmp/wifi-final-unit-20260928.log`. Final Ruff and ty both exited 0, with guest logs at
  `/tmp/wifi-final-ruff-20260928.log` and `/tmp/wifi-final-ty-20260928.log`.

The exact final source and full-matrix commands were:

```text
cd /workspace/openpilot && .venv/bin/python tools/test_runner.py openpilot/system/ui/lib/tests/test_wifi_manager.py -v
cd /workspace/openpilot && .venv/bin/ruff check openpilot/system/ui/lib
cd /workspace/openpilot && .venv/bin/ty check openpilot/system/ui/lib/wifi_manager.py
sudo env PATH="$PATH" WIFI_E2E_VM=1 /workspace/openpilot/.venv/bin/python /workspace/openpilot-wifi-validation/run.py --checkout /workspace/openpilot --sha f8249da3736640b1af52c6cc703bd7810f94602f --suite hwsim
```

## Focused hwsim availability

The approved focused expression collected **9 of 53** cases with **44 deselected** at source
`cc1e0d0d74095dc4b37e6a30950a62602e11d385`, tree `c27afcd4dca942fa15a881306d1cedeb3c239d3c`:

```text
rejected_tethering_password_completes_ui or switch_saved_networks or dhcp_timeout_then_another_selection or (forget_removes_every_persistent_source and False)
```

The collection log remains in the QEMU guest at `/tmp/wifi-focused9-collect-20260928.log`. Execution used:

```text
sudo env PATH="$PATH" WIFI_E2E_VM=1 /workspace/openpilot/.venv/bin/python run.py --checkout /workspace/openpilot --sha cc1e0d0d74095dc4b37e6a30950a62602e11d385 --suite hwsim --filter 'rejected_tethering_password_completes_ui or switch_saved_networks or dhcp_timeout_then_another_selection or (forget_removes_every_persistent_source and False)'
```

The first execution exited **77 before any case ran** because kernel `6.8.0-142-generic` lacked
`mac80211_hwsim`. Its guest result directory is
`/workspace/openpilot-wifi-validation/results/20260928T082809520443Z-cc1e0d0d7409-hwsim` and its log is
`/tmp/wifi-focused9-hwsim-20260928.log`. This was an infrastructure prerequisite failure, not hwsim behavior
evidence.

Under the existing VM prerequisite-install approval, the worker installed
`linux-modules-extra-6.8.0-142-generic:arm64` version `6.8.0-142.142`, verified its module path, and loaded
`mac80211_hwsim radios=0`; no reboot occurred. The recovery log remains in the guest at
`/tmp/wifi-hwsim-prereq-20260928.log`. A second attempt at
`results/20260928T083019178476Z-cc1e0d0d7409-hwsim` also exited 77 because the module was already loaded and did not
run cases. After unloading it, the runner loaded the module itself and the final focused run at
`results/20260928T083046788546Z-cc1e0d0d7409-hwsim` passed **9 passed, 44 deselected in 113.33 seconds**. Its log is
`/tmp/wifi-focused9-hwsim-final-20260928.log` and the result directory contains `junit.xml`. This validates the
strengthened saved-network switch and all four invalid-password cases in the approved focused group.

The local UI replay completed at final source `f8249da3736640b1af52c6cc703bd7810f94602f`, tree
`c27afcd4dca942fa15a881306d1cedeb3c239d3c`, with exit code 0 in both normal and `--big` modes. Its commands were:

```text
env PATH=/workspace/openpilot/.venv/bin:$PATH CI=1 PYTHONPATH=/workspace/openpilot RAYLIB_BACKEND=headless python3 openpilot/selfdrive/ui/tests/diff/replay.py
env PATH=/workspace/openpilot/.venv/bin:$PATH CI=1 PYTHONPATH=/workspace/openpilot RAYLIB_BACKEND=headless python3 openpilot/selfdrive/ui/tests/diff/replay.py --big
```

The guest logs are `/tmp/wifi-final-ui-replay-normal-20260928.log` and
`/tmp/wifi-final-ui-replay-big-20260928.log`. Expected headless startup warnings about no wlan0 and FPS appeared, while
the reports and videos completed.

This continuation did not rerun physical comma-device validation; its evidence is VM hwsim and source checks only.

## VM recovery provenance

The preserved VM's `vm/run-vm.sh` restart attempt failed before QEMU launch because `hdiutil makehybrid` refused its
existing `seed.iso`; that stderr was confirmed. To avoid overwriting the preserved VM inputs, the parent launched the
same script's `qemu-system-aarch64` invocation directly with the existing disk, seed, and firmware, HVF, four CPUs,
6 GiB RAM, and SSH forwarded on local port 2222. That direct launch did not recreate or replace the preserved disk,
seed, or firmware inputs, and no script fix is claimed. The later approved guest prerequisite installation changed the
guest environment but did not require a reboot. SSH then confirmed kernel `6.8.0-142-generic` and the existing virtual
environment. The running QEMU process is held by exec session `23549`.

## CI and archived evidence

The harness keeps all four invalid-hotspot-password cases and uses the existing setter-completion barrier to assert the
prior password and active-state preservation. The saved-network switch case requires Test B, its IPv4 lease, the wlan0
route, and HTTP to remain correct after one elapsed scan period and scan refreshes.

Focused-nine and full-53 hwsim, the final source revision/tree, and both local UI replay modes are recorded above.
Remote static analysis at `f8249da3736640b1af52c6cc703bd7810f94602f` failed solely in codespell: its log at
`/private/tmp/wifi-ci-static-analysis-f8249da.log` has SHA-256
`8e0de74cd0200e61cfdb3b68c631cc471700e1e07200890c79d8adf8e394fa92` and reports
`openpilot/system/ui/lib/tests/test_wifi_manager.py:310: assertIn`. Ruff, shell, dependency, indentation, large-file,
shebang, no-merge-comment, and ty checks in that job passed. The source worker amended the test-only equivalent
assertion locally as top commit `510f9b76b63800756c0258acad794cfa9623d08f`, tree
`d84ec72dcd5d598d77e3ddb55e49d245fb7f0e99`, with implementation parent
`d92b0a5727a1ae995154521a1e8bb312324032fd`: `self.assertIn(expected, f.read())` became
`assert expected in f.read()` and preserves the expected literal byte-for-byte. Targeted codespell 2.4.3 went red
with exit 65, then green with exit 0; 93 source tests passed in 25.09 seconds and Ruff and ty passed. After a fresh
remote read confirmed f824, the parent force-pushed the amended source with a lease pinned to f824; it exited 0 and
remote readback was `510f9b76b63800756c0258acad794cfa9623d08f`. At that corrected head, static analysis workflow run
`36401143236`, job `108859078206`, succeeded. The final remote check at
[`commaai/openpilot#38968`](https://github.com/commaai/openpilot/pull/38968) completed with **9 passed, 2 skipped, 0
failed**. In test run `36401143236`, Create UI Report passed in 7m24s (job `108859078108`), unit in 6m52s
(`108859078187`), process in 5m54s (`108859078091`), static analysis in 34s (`108859078206`), build-release in 2m39s
(`108859078024`), and macOS build in 4m28s (`108859078228`); simulator was skipped. Docs passed in 32s (run
`36401143319`, job `108859042607`), diff comment in 6m20s (run `36401139453`, job `108859031263`), and review in 8s
(run `36401139637`, job `108859032210`); preview was skipped. In guest cwd `/workspace/openpilot`, its exact repair commands
were:

```text
./.venv/bin/python -m ensurepip --upgrade
./.venv/bin/python -m pip install codespell==2.4.3
./.venv/bin/codespell openpilot/system/ui/lib/tests/test_wifi_manager.py
./.venv/bin/python tools/test_runner.py openpilot/system/ui/lib/tests/test_wifi_manager.py -v
./.venv/bin/ruff check openpilot/system/ui/lib
./.venv/bin/ty check openpilot/system/ui/lib/wifi_manager.py
```

The codespell command produced the red and green runs. Its guest logs are preserved in the supplemental archive under
the same basenames: `wifi-codespell-ensurepip-20260928.log`, `wifi-codespell-install-20260928.log`,
`wifi-codespell-red-20260928.log`, `wifi-codespell-containment-green-20260928.log`,
`wifi-codespell-containment-unit-20260928.log`, `wifi-codespell-containment-ruff-20260928.log`, and
`wifi-codespell-containment-ty-20260928.log`. At the earlier f824 head, Create UI Report workflow run `36400150138`, job
`108855818641`, succeeded with all steps including upload; remote unit, build-release, build-macOS, docs, and review
also passed. Those successful jobs do not cover the later test-only correction. The v4 archive is preserved beside this manifest at
`wifi-final-evidence-20260928-v4.tar.gz`, copied from
`/private/tmp/wifi-final-evidence-20260928-v4.tar.gz`, and is SHA-256
`2c7a21d0e54365ab4ba5a5efeea75316bb78dca23218043fdc1d6561ca245590` with 57 members; the host member list is
`/private/tmp/wifi-final-evidence-20260928-v4.members.txt`. Host inspection found 44 regular files and 13 directories,
with no unsafe or special entries and no common credential markers. It contains copied logs, JUnit, manifests, and
provenance/status files; the final JUnit records 53 tests with zero errors, failures, or skips. It includes
`wifi-priority-tdd-log-status-20260928.txt`, which records that the exact guest `runtime-priority-*-17c5a1b3.log`
search and the bounded priority search both found zero files after the VM restart. The archive does not preserve or
substitute those raw priority TDD logs, so it is not complete raw-log preservation.

The final-510 supplemental archive is preserved beside this manifest as
`wifi-codespell-supplement-20260928.tar.gz`, copied from
`/private/tmp/wifi-codespell-supplement-20260928.tar.gz`, SHA-256
`c34612758f85cb5a4bdffb4bf8425cfb33f915933034e691baa7b50b38a43698`. Its 14 members are regular files with no
unsafe entries or common credential markers; it preserves the codespell install, red, directive, containment-green,
unit, Ruff, ty, and provenance evidence for source `510f9b76b63800756c0258acad794cfa9623d08f`, tree
`d84ec72dcd5d598d77e3ddb55e49d245fb7f0e99`. Its provenance deliberately binds the f824 hwsim and UI evidence to
that earlier manager-identical source and does not claim a rerun.

The historical f824 remote static-analysis failure log is also preserved as deterministic gzip
`wifi-ci-static-analysis-f8249da.log.gz`, made with `gzip -n` from
`/private/tmp/wifi-ci-static-analysis-f8249da.log`. The compressed SHA-256 is
`4b4ecae4f697fa5a8acfebdc8d52fe5cb3d7d0e37ce8d8edadfddb29f3164b24`; its decompressed bytes have the original
SHA-256 `8e0de74cd0200e61cfdb3b68c631cc471700e1e07200890c79d8adf8e394fa92`. A marker scan of the raw content found no
common credential values. It remains separate from the supplemental archive and does not alter the final-510
static-analysis success.
