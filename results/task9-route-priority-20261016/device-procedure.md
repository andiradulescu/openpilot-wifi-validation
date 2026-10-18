# Proposed device verification, for firstmate approval and execution

No device action has been performed by this worker. This procedure is a proposal, not deployment authorization. Execute only after the final software evidence is accepted and the device is confirmed offroad with wired access and a recovery path. The previous successful physical run used a temporary `wlan0.arp_announce=2`; it does not validate this source change.

## Candidate and recovery

- Target: comma-12462a9b, wired IPv4 192.168.1.199. Use the existing verified SSH identity and host-key alias, never the WLAN address and never accept a new key automatically.
- Candidate: local branch `fix/wifi-route-priority`, commit `c47761b0b51e8965a067aed71001fd09471579c0`, based on `510f9b76b63800756c0258acad794cfa9623d08f`.
- Only the DHCP hook changes at runtime. `wifi_manager.py` SHA-256 remains `0d5715aa1f3dc926e444f98204a055a4658844aa7f03b65e358123a82fc67b25`.
- New hook SHA-256: `14bb8751186ddc501656e21877fff149ba52b6e3e55fb994ca7b46a948667ae0`, mode 755.
- Recovery is the retained exact device base commit, checked out over wired access and rebooted after approval. Keep local copies of the previous hook and its hash. Do not discard any dirty device work.

## Parent preflight

Use the established wired-only SSH command:

```sh
ssh -4 -o BatchMode=yes -o ConnectTimeout=8 -o HostKeyAlias=comma-12462a9b -o StrictHostKeyChecking=yes comma@192.168.1.199
```

In that device session, activate `/usr/local/venv/bin/activate`, `cd /data/openpilot`, and export `PYTHONPATH=/data/openpilot`. Before changing anything, record `hostname`, `git rev-parse HEAD`, `git status --short`, hook/manager SHA-256 and modes, `ip -4 addr show eth0`, `ip -4 route`, `nmcli -f GENERAL.STATE,IP4.ADDRESS,IP4.ROUTE device show eth0`, and:

```sh
sysctl net.ipv4.conf.all.arp_announce net.ipv4.conf.eth0.arp_announce net.ipv4.conf.wlan0.arp_announce
peer=${SSH_CONNECTION%% *}
ip -4 route get "$peer" from 192.168.1.199
```

Confirm the Ethernet connected prefix and default both have metric 100 and the source-bound return route selects eth0. If Ethernet's prefix is already missing, stop and arrange a separately approved restoration before deploying. Require `cat /data/params/d/IsOffroad` to return `1`. Do not infer this from `IsOnroad`, which was absent during the verified device preflight. Confirm `ip`, `busybox ipcalc -p -n`, the stock hook and the existing route/ARP collection tooling are available. Save the original hook bytes and hashes to the parent's task evidence without collecting profiles or passphrases.

## Install and reboot, only after explicit approval

The worker prepares a local incremental Git bundle under the task data directory. Parent verifies its SHA-256 locally and after copying it over verified Ethernet to `/data/wifi-route-priority.bundle`. On device:

```sh
cd /data/openpilot
git bundle verify /data/wifi-route-priority.bundle
git fetch /data/wifi-route-priority.bundle fix/wifi-route-priority
git checkout --detach c47761b0b51e8965a067aed71001fd09471579c0
sha256sum openpilot/system/ui/lib/udhcpc.script openpilot/system/ui/lib/wifi_manager.py
stat -c '%a %n' openpilot/system/ui/lib/udhcpc.script
git status --short
sudo reboot
```

Stop on any unexpected HEAD, dirty overlap, hash, mode or bundle prerequisite. Do not fetch from GitHub or alter the public branch. After reconnecting over wired Ethernet, repeat the preflight route checks and confirm all/eth0/wlan0 `arp_announce` values are 0. A retained value of 2 would confound this test; investigate its persistence before continuing. Do not add an ARP sysctl as part of this candidate.

## Capture and exercise

Start fresh, bounded route/address netlink capture and the parent's prepared ETH_P_ALL socket collector on Ethernet and WLAN after reboot. The parent collector filters and logs only ARP frames without promiscuous mode, covering outgoing ARP. Require the parent to review its exact invocation before execution; the previous ETH_P_ARP-only receiver does not establish complete outgoing coverage. Capture the initial hotspot enable from before the UI action, rather than reusing the incomplete initial-enable capture from the earlier control. Record a source-bound wired peer probe throughout every transition. Record the WLAN MAC locally so any ARP sender claiming the wired IPv4 address can be identified without exposing network credentials.

1. Station baseline: verify WLAN address uses `noprefixroute`, connected prefix and default are metric 600, Ethernet prefix/default remain metric 100, and DNS appears in `resolvectl status wlan0`. Verify WLAN-bound HTTPS using the parent's previously used URL and require HTTP 200. Record only state and IPv4 from supplicant output, no passphrase or profile contents.
2. Enable hotspot through the UI. A phone with mobile data off must join, obtain a 192.168.43.x lease, and browse HTTPS when the existing forwarding policy permits it. Verify the wired return route still selects eth0.
3. Change the active hotspot password through the UI with private input. Rejoin the phone and repeat browsing and wired checks. Do not put the password in logs or shell history.
4. Disable hotspot and wait for station association plus DHCP. Require the wired source-bound return route to remain eth0 at every checkpoint. Require station prefix/default at metric 600 from their first unicast netlink installation, DNS restored, and WLAN-bound HTTPS 200.
5. Repeat the on/password/off sequence with capture covering each transition. Record the actual number of completed sequences and any lost probes; do not infer more runs than were executed.

Acceptance: no unicast metric-0 WLAN route install, no Ethernet connected-prefix deletion, no WLAN-MAC ARP claiming Ethernet's IPv4 address, wired return path stays eth0, correct WLAN lease/routes/DNS, and successful physical client/station HTTPS. Local/broadcast table routes normally lack metric 600 and are outside this route-priority assertion. If any criterion fails, preserve evidence and stop; do not add speculative knobs or claim success from final routes alone.

## Rollback proposal

After separate approval, check out the recorded prior device commit `510f9b76b63800756c0258acad794cfa9623d08f` and reboot over the verified wired/recovery path. Verify its original hook hash `48707532e8b313597432b4989c7bb97e0f75bc358adc43a68d409b0091f93240`. Reboot also clears the temporary ARP setting; this old source retains the known route race, so do not repeat the risky sequence as a recovery test.
