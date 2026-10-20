On Apple Silicon macOS, install QEMU with `brew install qemu`.

Run `vm/run-vm.sh` in a spare terminal. It installs `~/.ssh/id_ed25519.pub` in the VM by default. To use another public key:

```sh
SSH_PUBLIC_KEY_FILE="$HOME/.ssh/another-key.pub" vm/run-vm.sh
```

Connect with `ssh -p 2222 ubuntu@localhost`.
The key is installed on first boot; changing it requires recreating the disposable VM.

Generated images, firmware state, and the cloud-init seed stay in `~/vms/wifi-e2e`. The VM is throwaway: `rm -rf ~/vms/wifi-e2e` resets it.
