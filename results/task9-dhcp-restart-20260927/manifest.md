# DHCP association restart evidence

Final green source candidate: `be2ee045f138fe7d9c42753625bbf680ad78295edbc407b4fde8ddc32f34d066`
(`openpilot/system/ui/lib/wifi_manager.py`)

Final green test candidate: `e711cff7c09b58a8c98f0dc516e42e4b1423eb95f557681c500d6ab1642c19d3`
(`openpilot/system/ui/lib/tests/test_wifi_manager.py`)

The final hashes were verified in `/workspace/openpilot` on the local QEMU VM before the final checks.

## Regression runs

- Red: `.venv/bin/python tools/test_runner.py openpilot/system/ui/lib/tests/test_wifi_manager.py -v`
  with baseline manager `1a560f373932451d1373bb977f7d9ba1de542e6278df86669a97bbe7febdc77b` and regression test
  `282537af8ce9192840ca55b164af557fc183803a0624680193789f99636bb3f2` exited 1: 85 collected, 84 passed,
  1 failed in 23.72 s. Both delivery-order subtests timed out waiting for `Home`, and the baseline logged
  `No DHCP lease on Home`.
- The initial 0.6-second test timeout was corrected to 1.5 seconds before this final red run so the model can observe
  the retry on the second 0.5-second polling interval. The baseline still failed with the same count and reason.
- Green: the same command with both final candidates exited 0: 85 passed in 23.44 s.
- The first green Ruff run found B023 loop-closure warnings in the new table-driven test. Binding the per-subtest
  callback values changed no modeled behavior. The final Ruff and ty runs both exited 0.

## Preserved prior diagnostics

| File | SHA-256 | Interpretation |
| --- | --- | --- |
| `wifi-hwsim-exact.log` | `214fb6df0a345789b2785576203b2fd938b9a5850316dbbcf9f8d258dd507da7` | Baseline hwsim run with one failure and 51 deselected cases. |
| `wifi-hwsim-early-run.log` | `b88bd65aa937257b0c7564c6e6cc945bf3437b2f1e4193b8655931c17d72bec4` | Early baseline pass, retained as a flaky baseline observation. |
| `wifi-hwsim-release-counterfactual.log` | `dd5b41d93f5f3518838cffa3f0382a32129f418ed1300e18edbdf48b89ec3957` | Intervened counterfactual: manual release, delay, then renew. It does not establish acceptance. |
| `wifi-hwsim-client-strace.log` | `f8c82c2e5c789016317cbea578825f63b5c7a121ed6b4b3da978cf2ecb19fa34` | Supporting client signal and packet trace. |
| `wifi-hwsim-counterfactual-action.log` | `367e6761bd8886f1868f2337c171295cb63d0110f6ba6a44db2d03ffe4f39cee` | Recorded manual counterfactual action. |
| `wifi-hwsim-ap-packets.log` | `1dfaf3eb58b0a942633dd94c3c4afa18dbc30c5024cd6d73ee6bc418749c3092` | Supporting AP packet capture. |

No hwsim matrix or physical-device run was performed for this amendment.
