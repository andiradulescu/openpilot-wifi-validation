#!/bin/sh
# Disposable Ubuntu 24.04 arm64 VM for the hwsim suite. First run downloads the cloud image; state lives in ~/vms/wifi-e2e.
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
key_file="${SSH_PUBLIC_KEY_FILE:-$HOME/.ssh/id_ed25519.pub}"
if [ ! -r "$key_file" ]; then
  printf 'Set SSH_PUBLIC_KEY_FILE to a readable SSH public key file (current: %s).\n' "$key_file" >&2
  exit 1
fi
public_key=$(awk 'NR == 1 && /^(ssh-|ecdsa-|sk-)/ { print $1 " " $2 }' "$key_file")
if [ -z "$public_key" ]; then
  printf 'Expected an SSH public key in %s.\n' "$key_file" >&2
  exit 1
fi
printf '%s\n' "$public_key" | ssh-keygen -l -f - >/dev/null
dir="$HOME/vms/wifi-e2e"
mkdir -p "$dir"
cd "$dir"
[ -f noble.img ] || { curl -Lo noble.img https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-arm64.img; qemu-img resize noble.img 40G; }
[ -f code.fd ] || cp "$(brew --prefix qemu)/share/qemu/edk2-aarch64-code.fd" code.fd
[ -f vars.fd ] || truncate -s 64m vars.fd
rm -rf seed && mkdir seed && cp "$here/meta-data" seed/
awk -v key="$public_key" '{ gsub(/__SSH_PUBLIC_KEY__/, key); print }' "$here/user-data" > seed/user-data
hdiutil makehybrid -quiet -o seed.iso -joliet -iso -default-volume-name cidata seed/
exec qemu-system-aarch64 -M virt -accel hvf -cpu host -smp 4 -m 6144 -smbios type=1,serial=ds=nocloud \
  -drive if=pflash,format=raw,file=code.fd,readonly=on -drive if=pflash,format=raw,file=vars.fd \
  -drive file=noble.img,if=virtio,format=qcow2 -drive file=seed.iso,if=virtio,format=raw,readonly=on \
  -netdev user,id=n0,hostfwd=tcp::2222-:22 -device virtio-net-pci,netdev=n0 -nographic
