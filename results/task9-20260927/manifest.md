# QEMU validation attempt on 9f1e7ada0

Date: 2026-09-27. QEMU ARM Ubuntu kernel 6.8.0-139-generic. Source checkout /workspace/openpilot was clean at 9f1e7ada0990a703ce22424737396ad2fb22bd08. The existing VM harness was at e966eb74613b8a9507ba495c3a0ba8e8ba78d1ab with pre-existing edits to run_wifi_e2e.sh, test_wifi_e2e.py, and wifi_e2e.py. No edits were changed or discarded. The exact patch is preserved in harness.patch; generated manifests record file hashes and dirty state. These are not clean-harness qualification results.

## Unit runner

`python3 run.py --checkout /workspace/openpilot --sha 9f1e7ada0990a703ce22424737396ad2fb22bd08 --suite unit` from /workspace/openpilot-wifi-validation: 83 passed, 0 failed, 82.13 seconds. The manifest records status passed and the exact `.venv/bin/python tools/test_runner.py -j 1 openpilot/system/ui/lib/tests` command.

Manifest: 20260927T153127233726Z-9f1e7ada0990-unit/manifest.json.

## Virtual-radio matrix

`sudo env PATH="$PATH" WIFI_E2E_VM=1 python3 run.py --checkout /workspace/openpilot --sha 9f1e7ada0990a703ce22424737396ad2fb22bd08 --suite hwsim`: collected 52 cases, rather than the plan's original 51, because the pre-existing harness includes the shared-subnet connected-prefix regression. The run was interrupted with SIGINT to its verified pytest process after observing the first failure, preserving pytest teardown, traceback and JUnit. Final reported result: 3 passed, 1 failed in 120.83 seconds; 48 collected cases did not complete. This is an incomplete, failed matrix, not qualification. Virtual-radio module removal was verified afterward.

Failed case: test_connect_persist_and_reopen[Test A-password123-False]. At the deadline the manager reported connecting with no IP. Service evidence shows the WPA2 handshake completed, supplicant STATUS was COMPLETED, and wlan0 had no IPv4 address. No cause has yet been assigned to source or harness. Further work stopped under the requested failure rule; no implementation or assertion changes were made.

Manifest: 20260927T153310637241Z-9f1e7ada0990-hwsim/manifest.json. JUnit: 20260927T153310637241Z-9f1e7ada0990-hwsim/junit.xml. Failed-case service directory: services/wifi-e2e-ghmvqyrm under that run.

## Evidence handling and deviations

The first recursive scp could not read root-owned configuration files and could not copy Unix sockets. A sudo read-only tar of regular files preserved all regular result files without modifying VM permissions; transient sockets were intentionally excluded. No physical device was touched. The deviation from completing the full matrix is explicit: it was stopped after a failure for investigation. No GitHub push or PR action. Host harness edits remain untouched.
