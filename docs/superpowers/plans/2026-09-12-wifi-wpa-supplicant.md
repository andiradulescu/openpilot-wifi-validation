# Wi-Fi without NetworkManager (v3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite `openpilot/system/ui/lib/wifi_manager.py` to drive `wpa_supplicant`, `udhcpc` and `dnsmasq` directly, with the public `WifiManager` contract unchanged, then prove it with the in-tree tests, the external hwsim harness, and comma hardware.

**Architecture:** One module owns Wi-Fi: a tiny control-socket client, keyfile profile storage, and a `WifiManager` with one lock, a monitor thread for supplicant events and health, and a scan thread. Root daemons are spawned detached with `sudo` and adopted on restart by pidfile. NetworkManager releases `wlan0` once per boot via `nmcli`.

**Tech Stack:** Python 3 (2-space indent, 160 cols), `unittest` via `tools/test_runner.py`, `OpenpilotTestCase`/`Mocker` from `openpilot/common/test.py`, wpa_supplicant 2.10 control interface, BusyBox udhcpc, dnsmasq, iptables-legacy.

**Spec:** `docs/superpowers/specs/2026-09-12-wifi-wpa-supplicant-design.md` (this repository, branch `wifi-v3`).

## Global Constraints

- openpilot worktree: `/Volumes/Stuff/openpilot-wifi-v3`, branch `wifi-wpa-supplicant`, base comma/master `0cf294d85`. All openpilot paths below are relative to that worktree; the tree is nested, so source lives under `openpilot/`.
- Only `openpilot/system/ui/lib/wifi_manager.py`, `openpilot/system/ui/lib/wpa_supplicant.conf`, `openpilot/system/ui/lib/udhcpc.script`, `openpilot/system/ui/lib/tests/test_wifi_manager.py`, `pyproject.toml` and `uv.lock` change; `openpilot/system/ui/lib/networkmanager.py` and `openpilot/system/ui/lib/tests/test_handle_state_change.py` are deleted. No UI, setup, updater or hardware.py edits.
- Public surface of `WifiManager` stays byte-for-byte identical to comma/master (methods, properties, callbacks, `Network`, `WifiState`, `ConnectStatus`, `SecurityType`, `MeteredType`, `normalize_ssid`).
- Control socket `/run/wpa_supplicant/wlan0`; pidfiles `/run/wpa_supplicant/wlan0.pid`, `/run/udhcpc.wlan0.pid`, `/run/dnsmasq.wlan0.pid`.
- Profile dirs: persistent `/data/etc/NetworkManager/system-connections` (write target), runtime `/run/NetworkManager/system-connections` (read only), netplan YAML `/data/etc/netplan/90-NM-<uuid>.yaml`.
- Constants with sources: Wi-Fi route metric 600 (NetworkManager default Wi-Fi metric; eth 100, ppp0 1000 in modem.py), `DHCP_TIMEOUT_SECONDS = 45` (NetworkManager `ipv4.dhcp-timeout` default), tethering `192.168.43.1/24`, DHCP range `192.168.43.2,192.168.43.254,24h`, frequency 2437 (channel 6, NetworkManager `band=bg` default), default hotspot password `swagswagcomma`, dBm to percent `-40 dBm = 100 %`, `-100 dBm = 0 %` (NetworkManager `nm-wifi-utils.c`).
- Firewall: `iptables-legacy` only (nf_tables iptables fails on the 4.9 kernel).
- Run tests with `python tools/test_runner.py openpilot/system/ui/lib/tests/test_wifi_manager.py -v` from the worktree root inside its venv (`uv run` or `.venv/bin/python`). Lint with `ruff check openpilot/system/ui/lib` and `ty check openpilot/system/ui/lib/wifi_manager.py`.
- Commits: single-line messages, author `Andrei Radulescu <andi.radulescu@gmail.com>`. Commit after every green step. No TODO/FIXME, no history comments, no agent notices.
- Analysis files, this plan, benchmark scripts and harness changes live in this validation repository, never in the openpilot branch.

---

## File map

| File | Responsibility |
| --- | --- |
| `openpilot/system/ui/lib/wifi_manager.py` | Everything Wi-Fi: constants, enums and dataclasses (unchanged names), `WpaCtrl` client, parsers, `Profile` storage helpers, `WifiManager`. |
| `openpilot/system/ui/lib/wpa_supplicant.conf` | Static two-line supplicant config, no secrets. |
| `openpilot/system/ui/lib/udhcpc.script` | Runs the stock script then re-adds the wlan0 default route at metric 600. |
| `openpilot/system/ui/lib/tests/test_wifi_manager.py` | `FakeSupplicant` unix-socket server, fixtures patching paths and `sudo`, one test per UI-reachable flow. |

The tests build up in the same file across tasks. Every task below adds to `test_wifi_manager.py` and `wifi_manager.py`; only Task 1 creates them.

---

### Task 1: Module skeleton, control client and parsers

**Files:**
- Create: `openpilot/system/ui/lib/wifi_manager.py`
- Create: `openpilot/system/ui/lib/tests/test_wifi_manager.py`
- Delete: `openpilot/system/ui/lib/tests/test_handle_state_change.py`

**Interfaces:**
- Produces: `WpaCtrl(path)` with `request(cmd) -> str`, `ok(cmd) -> bool`, `attach() -> socket.socket`, `close()`; `decode_ssid(s) -> str`; `parse_status(raw) -> dict[str, str]`; `parse_scan_results(raw) -> list[tuple[str, int, str]]` (ssid, dBm, flags); `dbm_to_percent(dbm) -> int`; `security_type_from_flags(flags) -> SecurityType`; `wpa_psk(ssid, passphrase) -> str`; module constants listed in Global Constraints; `FakeSupplicant` test helper.

- [ ] **Step 1: Delete the NetworkManager state-machine test and start the new module with the unchanged public types**

Run: `git rm openpilot/system/ui/lib/tests/test_handle_state_change.py`

Write `openpilot/system/ui/lib/wifi_manager.py` with this content (the `WifiManager` class is added in Task 3; the file must import cleanly now):

```python
import atexit
import configparser
import hashlib
import os
import re
import socket
import subprocess
import tempfile
import threading
import time
import urllib.parse
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import IntEnum
from pathlib import Path
from typing import TYPE_CHECKING

from openpilot.common.swaglog import cloudlog
from openpilot.common.utils import sudo_read

if TYPE_CHECKING:
  from openpilot.common.params import Params
else:
  try:
    from openpilot.common.params import Params
  except (ImportError, OSError):
    Params = None

WLAN = "wlan0"
WPA_CTRL_DIR = "/run/wpa_supplicant"
WPA_CTRL_PATH = f"{WPA_CTRL_DIR}/{WLAN}"
WPA_PID_PATH = f"{WPA_CTRL_DIR}/{WLAN}.pid"
WPA_CONF_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wpa_supplicant.conf")
UDHCPC_PID_PATH = f"/run/udhcpc.{WLAN}.pid"
UDHCPC_SCRIPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "udhcpc.script")
DNSMASQ_PID_PATH = f"/run/dnsmasq.{WLAN}.pid"
PROFILE_DIRS = ("/data/etc/NetworkManager/system-connections", "/run/NetworkManager/system-connections")  # persistent first, netplan-generated second
NETPLAN_DIR = "/data/etc/netplan"

TETHERING_IP_ADDRESS = "192.168.43.1"
TETHERING_SUBNET = "192.168.43.0/24"
TETHERING_DHCP_RANGE = "192.168.43.2,192.168.43.254,24h"
TETHERING_FREQUENCY = 2437  # channel 6, NetworkManager's band=bg default
TETHERING_NAT_RULE = ["POSTROUTING", "-s", TETHERING_SUBNET, "!", "-d", TETHERING_SUBNET, "-j", "MASQUERADE", "-m", "comment", "--comment", "openpilot-tethering"]
DEFAULT_TETHERING_PASSWORD = "swagswagcomma"
SCAN_PERIOD_SECONDS = 5
DHCP_TIMEOUT_SECONDS = 45  # NetworkManager ipv4.dhcp-timeout default
HANDOFF_TIMEOUT_SECONDS = 5
CTRL_TIMEOUT_SECONDS = 2


def normalize_ssid(ssid: str) -> str:
  return ssid.replace("’", "'")  # for iPhone hotspots


class SecurityType(IntEnum):
  OPEN = 0
  WPA = 1
  WPA2 = 2
  WPA3 = 3
  UNSUPPORTED = 4


class MeteredType(IntEnum):
  UNKNOWN = 0
  YES = 1
  NO = 2


@dataclass(frozen=True)
class Network:
  ssid: str
  strength: int
  security_type: SecurityType
  is_tethering: bool


class ConnectStatus(IntEnum):
  DISCONNECTED = 0
  CONNECTING = 1
  CONNECTED = 2


@dataclass(frozen=True)
class WifiState:
  ssid: str | None = None
  status: ConnectStatus = ConnectStatus.DISCONNECTED


class WpaCtrl:
  # wpa_supplicant control interface over unix datagram sockets
  def __init__(self, path: str):
    self._path = path
    self._lock = threading.Lock()
    self._sock = self._open()

  def _open(self) -> socket.socket:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.bind(f"\0openpilot-wpa-{os.getpid()}-{time.monotonic_ns()}")
    sock.connect(self._path)
    sock.settimeout(CTRL_TIMEOUT_SECONDS)
    return sock

  def request(self, cmd: str) -> str:
    with self._lock:
      self._sock.send(cmd.encode())
      while True:
        reply = self._sock.recv(65536).decode("utf-8", "replace")
        if not reply.startswith("<"):
          return reply.rstrip("\n")

  def ok(self, cmd: str) -> bool:
    return self.request(cmd) == "OK"

  def attach(self) -> socket.socket:
    sock = self._open()
    sock.send(b"ATTACH")
    if sock.recv(64).rstrip(b"\n") != b"OK":
      sock.close()
      raise OSError("wpa_supplicant ATTACH failed")
    sock.settimeout(1)
    return sock

  def close(self):
    self._sock.close()


def decode_ssid(value: str) -> str:
  # wpa_supplicant printf_encode: printable ASCII as is, \\ \" \e \n \r \t, everything else as \xNN
  out = bytearray()
  i = 0
  while i < len(value):
    if value[i] == "\\" and i + 1 < len(value):
      esc = value[i + 1]
      if esc == "x" and i + 3 < len(value):
        out.append(int(value[i + 2:i + 4], 16))
        i += 4
        continue
      out.extend({"n": b"\n", "r": b"\r", "t": b"\t", "e": b"\x1b"}.get(esc, esc.encode()))
      i += 2
      continue
    out.extend(value[i].encode())
    i += 1
  return out.decode("utf-8", "replace")


def parse_status(raw: str) -> dict[str, str]:
  return dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)


def parse_scan_results(raw: str) -> list[tuple[str, int, str]]:
  # bssid / frequency / signal level / flags / ssid
  results = []
  for line in raw.splitlines()[1:]:
    fields = line.split("\t")
    if len(fields) < 5:
      continue
    results.append((decode_ssid(fields[4]), int(fields[2]), fields[3]))
  return results


def dbm_to_percent(dbm: int) -> int:
  # NetworkManager nm-wifi-utils.c: -40 dBm is 100%, -100 dBm is 0%
  return 100 - int(100 * (-40 - max(-100, min(-40, dbm))) / 60)


def security_type_from_flags(flags: str) -> SecurityType:
  if "-PSK" in flags:
    return SecurityType.WPA
  if "WPA" not in flags and "WEP" not in flags:
    return SecurityType.OPEN
  return SecurityType.UNSUPPORTED


def wpa_psk(ssid: str, passphrase: str) -> str:
  # IEEE 802.11i PSK derivation; a keyfile may already hold the 64 hex character raw key
  if len(passphrase) == 64 and all(c in "0123456789abcdefABCDEF" for c in passphrase):
    return passphrase.lower()
  return hashlib.pbkdf2_hmac("sha1", passphrase.encode(), ssid.encode(), 4096, 32).hex()
```

- [ ] **Step 2: Write the fake supplicant and the parser tests**

Write `openpilot/system/ui/lib/tests/test_wifi_manager.py`:

```python
import os
import re
import socket
import tempfile
import threading
import time
import unittest
from collections.abc import Callable

from openpilot.common.test import OpenpilotTestCase, Mocker
from openpilot.system.ui.lib import wifi_manager
from openpilot.system.ui.lib.wifi_manager import (WpaCtrl, SecurityType, decode_ssid, parse_scan_results, dbm_to_percent,
                                                  security_type_from_flags, wpa_psk)

SCAN_HEADER = "bssid / frequency / signal level / flags / ssid\n"


class FakeSupplicant:
  # unix datagram server speaking the wpa_supplicant control protocol from a scripted reply table
  def __init__(self, path: str):
    self.path = path
    self.requests: list[str] = []
    self.replies: dict[str, str | Callable[[str], str]] = {"PING": "PONG"}
    self.status: dict[str, str] = {"wpa_state": "DISCONNECTED"}
    self.networks: dict[int, dict[str, str]] = {}
    self._attached: list[bytes] = []
    self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    self._sock.bind(path)
    self._sock.settimeout(0.1)
    self._exit = False
    self._thread = threading.Thread(target=self._serve, daemon=True)
    self._thread.start()

  def _reply(self, cmd: str) -> str:
    if cmd == "STATUS":
      return "".join(f"{k}={v}\n" for k, v in self.status.items())
    if cmd == "ADD_NETWORK":
      nid = max(self.networks, default=-1) + 1
      self.networks[nid] = {}
      return f"{nid}\n"
    if cmd.startswith("SET_NETWORK "):
      _, nid, key, value = cmd.split(" ", 3)
      self.networks[int(nid)][key] = value
      return "OK\n"
    if cmd.startswith("REMOVE_NETWORK "):
      self.networks.pop(int(cmd.split()[1]), None)
      return "OK\n"
    if cmd == "LIST_NETWORKS":
      lines = ["network id / ssid / bssid / flags"]
      for nid, net in self.networks.items():
        lines.append(f"{nid}\t{bytes.fromhex(net.get('ssid', '')).decode()}\tany\t")
      return "\n".join(lines) + "\n"
    reply = self.replies.get(cmd, self.replies.get(cmd.split(" ")[0], "OK\n"))
    return reply(cmd) if callable(reply) else reply

  def _serve(self):
    while not self._exit:
      try:
        data, addr = self._sock.recvfrom(65536)
      except TimeoutError:
        continue
      cmd = data.decode()
      if cmd == "ATTACH":
        self._attached.append(addr)
        self._sock.sendto(b"OK\n", addr)
        continue
      self.requests.append(cmd)
      reply = self._reply(cmd)
      self._sock.sendto(reply.encode() if reply.endswith("\n") else (reply + "\n").encode(), addr)

  def emit(self, event: str):
    for addr in list(self._attached):
      self._sock.sendto(f"<3>{event}".encode(), addr)

  def close(self):
    self._exit = True
    self._thread.join()
    self._sock.close()


def wait_for(cond: Callable[[], bool], timeout: float = 5.0):
  deadline = time.monotonic() + timeout
  while time.monotonic() < deadline:
    if cond():
      return
    time.sleep(0.02)
  raise AssertionError("condition not met in time")


class TestParsers(OpenpilotTestCase):
  def test_decode_ssid(self):
    self.assertEqual(decode_ssid("plain"), "plain")
    self.assertEqual(decode_ssid("caf\\xc3\\xa9"), "café")
    self.assertEqual(decode_ssid("a\\\\b\\\"c\\tq"), 'a\\b"c\tq')

  def test_parse_scan_results_keeps_dbm_and_flags(self):
    raw = SCAN_HEADER + "aa:bb\t2412\t-45\t[WPA2-PSK-CCMP][ESS]\tHome\n" + "cc:dd\t5180\t-80\t[ESS]\tCaf\\xc3\\xa9\n" + "ee:ff\t2437\t-60\t[ESS]\t\n"
    self.assertEqual(parse_scan_results(raw), [("Home", -45, "[WPA2-PSK-CCMP][ESS]"), ("Café", -80, "[ESS]"), ("", -60, "[ESS]")])

  def test_dbm_to_percent_matches_networkmanager_scale(self):
    self.assertEqual([dbm_to_percent(d) for d in (-30, -40, -70, -100, -110)], [100, 100, 50, 0, 0])

  def test_security_type_from_flags(self):
    cases = {"[ESS]": SecurityType.OPEN, "[WPS][ESS]": SecurityType.OPEN, "[WPA2-PSK-CCMP][ESS]": SecurityType.WPA,
             "[WPA2-PSK+SAE-CCMP][ESS]": SecurityType.WPA, "[WPA-PSK-TKIP][WPA2-PSK-CCMP][ESS]": SecurityType.WPA,
             "[WPA2-SAE-CCMP][ESS]": SecurityType.UNSUPPORTED, "[WPA2-EAP-CCMP][ESS]": SecurityType.UNSUPPORTED, "[WEP][ESS]": SecurityType.UNSUPPORTED}
    for flags, expected in cases.items():
      with self.subTest(flags=flags):
        self.assertEqual(security_type_from_flags(flags), expected)

  def test_wpa_psk(self):
    # reference vector from IEEE 802.11-2020 Annex J
    self.assertEqual(wpa_psk("IEEE", "password"), "f42c6fc52df0ebef9ebb4b90b38a5f902e83fe1b135a70e23aed762e9710a12e")
    self.assertEqual(wpa_psk("x", "F" * 64), "f" * 64)


class TestWpaCtrl(OpenpilotTestCase):
  def test_request_and_attach(self):
    with tempfile.TemporaryDirectory() as d:
      fake = FakeSupplicant(os.path.join(d, "wlan0"))
      self.addCleanup(fake.close)
      ctrl = WpaCtrl(fake.path)
      self.addCleanup(ctrl.close)
      self.assertEqual(ctrl.request("PING"), "PONG")
      self.assertTrue(ctrl.ok("SCAN"))
      events = ctrl.attach()
      fake.emit("CTRL-EVENT-SCAN-RESULTS")
      self.assertEqual(events.recv(1024), b"<3>CTRL-EVENT-SCAN-RESULTS")
      self.assertEqual(fake.requests, ["PING", "SCAN"])
```

- [ ] **Step 3: Run the tests, expect them to pass**

Run: `python tools/test_runner.py openpilot/system/ui/lib/tests/test_wifi_manager.py -v`
Expected: 6 passed. If `test_wpa_psk` fails on the reference vector, the vector is wrong, not the code: compare against `wpa_passphrase IEEE password` on the comma three and fix the expected string.

- [ ] **Step 4: Confirm the UI modules still import against the new module**

Run: `python -c "import openpilot.system.ui.lib.wifi_manager as w; print(w.WifiState(), w.SecurityType.WPA)"`
Expected: `WifiState(ssid=None, status=<ConnectStatus.DISCONNECTED: 0>) SecurityType.WPA`. (The UI files also import `WifiManager`, which arrives in Task 3, so do not import them yet.)

- [ ] **Step 5: Commit**

```bash
git add openpilot/system/ui/lib/wifi_manager.py openpilot/system/ui/lib/tests/test_wifi_manager.py
git commit -m "wifi: add wpa_supplicant control client and parsers"
```

---

### Task 2: Keyfile profile storage

**Files:**
- Modify: `openpilot/system/ui/lib/wifi_manager.py` (append after `wpa_psk`)
- Modify: `openpilot/system/ui/lib/tests/test_wifi_manager.py` (append)

**Interfaces:**
- Produces: `Profile(path, uuid, ssid, psk, hidden, metered, is_ap)` frozen dataclass; `read_profiles() -> list[Profile]`; `write_profile(profile) -> Profile` (returns the profile with its persistent path, removes other sources of the same uuid); `remove_profile(profile)`; `_sudo(*cmd, check=True) -> subprocess.CompletedProcess`; `_pid_alive(path) -> bool`. Tests get a `profile_dirs` fixture that patches `PROFILE_DIRS`, `NETPLAN_DIR`, `sudo_read` and `_sudo`.

- [ ] **Step 1: Write the failing storage tests**

Append to `test_wifi_manager.py`:

```python
KEYFILE_A = """[connection]
id=openpilot connection Home
uuid=11111111-1111-1111-1111-111111111111
type=wifi

[wifi]
mode=infrastructure
ssid=Home

[wifi-security]
key-mgmt=wpa-psk
psk=password123

[ipv4]
method=auto
"""

NETPLAN_KEYFILE = """[connection]
id=openpilot connection Café
type=wifi
uuid=22222222-2222-2222-2222-222222222222
interface-name=wlan0

[wifi]
ssid=67;97;102;195;169;
hidden=true

[wifi-security]
key-mgmt=wpa-psk
psk=cafepass1

[connection]
metered=1
"""

OPEN_KEYFILE = """[connection]
id=Open
uuid=33333333-3333-3333-3333-333333333333
type=wifi
metered=2

[wifi]
ssid=Open
"""

HOTSPOT_KEYFILE = """[connection]
id=Hotspot
uuid=44444444-4444-4444-4444-444444444444
type=wifi
interface-name=wlan0
autoconnect=false

[wifi]
band=bg
mode=ap
ssid=weedle

[wifi-security]
key-mgmt=wpa-psk
psk=swagswagcomma

[ipv4]
method=shared
address1=192.168.43.1/24,192.168.43.1
never-default=true
"""


def fake_sudo(record: list[list[str]]):
  # run install/rm/kill locally without sudo, record everything else without running it
  def _sudo(*cmd: str, check: bool = True):
    record.append(list(cmd))
    if cmd[0] in ("install", "rm"):
      return subprocess.run(cmd, check=check, capture_output=True, text=True)
    return subprocess.CompletedProcess(cmd, 0, "", "")
  return _sudo


def profile_dirs(mocker: Mocker):
  d = tempfile.mkdtemp()
  persistent, runtime, netplan = (os.path.join(d, n) for n in ("persistent", "runtime", "netplan"))
  for p in (persistent, runtime, netplan):
    os.makedirs(p)
  mocker.patch.object(wifi_manager, "PROFILE_DIRS", (persistent, runtime))
  mocker.patch.object(wifi_manager, "NETPLAN_DIR", netplan)
  mocker.patch.object(wifi_manager, "sudo_read", lambda path: open(path).read())
  sudo_calls: list[list[str]] = []
  mocker.patch.object(wifi_manager, "_sudo", fake_sudo(sudo_calls))
  yield {"persistent": persistent, "runtime": runtime, "netplan": netplan, "sudo": sudo_calls}
  shutil.rmtree(d)


def write(path: str, content: str):
  with open(path, "w") as f:
    f.write(content)


class TestProfiles(OpenpilotTestCase):
  def test_read_profiles_from_both_dirs(self, profile_dirs):
    write(os.path.join(profile_dirs["persistent"], "Home.nmconnection"), KEYFILE_A)
    write(os.path.join(profile_dirs["persistent"], "Hotspot.nmconnection"), HOTSPOT_KEYFILE)
    write(os.path.join(profile_dirs["runtime"], "netplan-NM-22222222-2222-2222-2222-222222222222-Caf.nmconnection"), NETPLAN_KEYFILE.replace("[connection]\nmetered=1\n", "").replace("type=wifi\n", "type=wifi\nmetered=1\n"))
    write(os.path.join(profile_dirs["runtime"], "lo.nmconnection"), "[connection]\nid=lo\nuuid=5\ntype=loopback\n")
    write(os.path.join(profile_dirs["runtime"], "broken.nmconnection"), "[connection\nid=x")
    profiles = {p.ssid: p for p in wifi_manager.read_profiles()}
    self.assertEqual(set(profiles), {"Home", "Café", "weedle"})
    self.assertEqual(profiles["Home"].psk, "password123")
    self.assertFalse(profiles["Home"].hidden)
    self.assertEqual(profiles["Home"].metered, wifi_manager.MeteredType.UNKNOWN)
    self.assertTrue(profiles["Café"].hidden)
    self.assertEqual(profiles["Café"].metered, wifi_manager.MeteredType.YES)
    self.assertTrue(profiles["weedle"].is_ap)
    self.assertEqual(profiles["weedle"].psk, "swagswagcomma")

  def test_write_profile_creates_networkmanager_keyfile(self, profile_dirs):
    profile = wifi_manager.Profile(path="", uuid="55555555-5555-5555-5555-555555555555", ssid="My Café/2", psk="secret99", hidden=True,
                                   metered=wifi_manager.MeteredType.NO, is_ap=False)
    saved = wifi_manager.write_profile(profile)
    self.assertEqual(saved.path, os.path.join(profile_dirs["persistent"], "My%20Caf%C3%A9%2F2.nmconnection"))
    self.assertEqual(profile_dirs["sudo"][-1][:3], ["install", "-m", "600"])
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(saved.path)
    self.assertEqual(cp["connection"]["type"], "wifi")
    self.assertEqual(cp["connection"]["uuid"], profile.uuid)
    self.assertEqual(cp["connection"]["metered"], "2")
    self.assertEqual(cp["wifi"]["ssid"], "77;121;32;67;97;102;195;169;47;50;")
    self.assertEqual(cp["wifi"]["hidden"], "true")
    self.assertEqual(cp["wifi-security"]["psk"], "secret99")
    self.assertEqual(cp["ipv4"]["method"], "auto")
    self.assertEqual([p.ssid for p in wifi_manager.read_profiles()], ["My Café/2"])

  def test_write_hotspot_profile_matches_upstream_shape(self, profile_dirs):
    saved = wifi_manager.write_profile(wifi_manager.Profile("", "6666", "weedle-abcd", "swagswagcomma", False, wifi_manager.MeteredType.UNKNOWN, True))
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(saved.path)
    self.assertEqual(cp["wifi"]["mode"], "ap")
    self.assertEqual(cp["wifi"]["ssid"], "weedle-abcd")
    self.assertEqual(cp["ipv4"]["method"], "shared")
    self.assertEqual(cp["ipv4"]["address1"], "192.168.43.1/24,192.168.43.1")
    self.assertEqual(cp["connection"]["autoconnect"], "false")
    self.assertNotIn("metered", cp["connection"])

  def test_write_profile_replaces_netplan_sources(self, profile_dirs):
    runtime = os.path.join(profile_dirs["runtime"], "netplan-NM-22222222-2222-2222-2222-222222222222-Caf.nmconnection")
    write(runtime, NETPLAN_KEYFILE)
    yaml = os.path.join(profile_dirs["netplan"], "90-NM-22222222-2222-2222-2222-222222222222.yaml")
    write(yaml, "network: {}\n")
    (profile,) = wifi_manager.read_profiles()
    saved = wifi_manager.write_profile(replace(profile, metered=wifi_manager.MeteredType.NO))
    self.assertFalse(os.path.exists(runtime))
    self.assertFalse(os.path.exists(yaml))
    self.assertEqual([(p.path, p.metered) for p in wifi_manager.read_profiles()], [(saved.path, wifi_manager.MeteredType.NO)])

  def test_remove_profile_removes_netplan_yaml(self, profile_dirs):
    runtime = os.path.join(profile_dirs["runtime"], "netplan-NM-22222222-2222-2222-2222-222222222222-Caf.nmconnection")
    write(runtime, NETPLAN_KEYFILE)
    yaml = os.path.join(profile_dirs["netplan"], "90-NM-22222222-2222-2222-2222-222222222222.yaml")
    write(yaml, "network: {}\n")
    wifi_manager.remove_profile(wifi_manager.read_profiles()[0])
    self.assertEqual(os.listdir(profile_dirs["runtime"]) + os.listdir(profile_dirs["netplan"]), [])

  def test_pid_alive(self):
    with tempfile.NamedTemporaryFile("w", suffix=".pid") as f:
      f.write(f"{os.getpid()}\n")
      f.flush()
      self.assertTrue(wifi_manager._pid_alive(f.name))
      f.seek(0)
      f.write("999999\n")
      f.flush()
      self.assertFalse(wifi_manager._pid_alive(f.name))
    self.assertFalse(wifi_manager._pid_alive("/nonexistent.pid"))
```

Add `import configparser`, `import shutil`, `import subprocess` and `from dataclasses import replace` to the test imports.

- [ ] **Step 2: Run the tests, expect failures**

Run: `python tools/test_runner.py openpilot/system/ui/lib/tests/test_wifi_manager.py -k TestProfiles -v`
Expected: every `TestProfiles` test fails with `AttributeError: module ... has no attribute 'read_profiles'` (or `Profile`).

- [ ] **Step 3: Implement storage**

Append to `wifi_manager.py`:

```python
def _sudo(*cmd: str, check: bool = True) -> subprocess.CompletedProcess:
  return subprocess.run(["sudo", *cmd], check=check, capture_output=True, text=True)


def _pid_alive(pid_path: str) -> bool:
  try:
    with open(pid_path) as f:
      pid = int(f.read().strip())
    os.kill(pid, 0)
  except (OSError, ValueError):
    return False
  except PermissionError:
    return True  # root-owned daemon
  return True


@dataclass(frozen=True)
class Profile:
  path: str
  uuid: str
  ssid: str
  psk: str | None
  hidden: bool
  metered: MeteredType
  is_ap: bool


def _keyfile_ssid(value: str) -> str:
  # NetworkManager stores non-ASCII SSIDs as a byte;byte; list
  parts = value.split(";")
  if value.endswith(";") and len(parts) > 1 and all(p.isdigit() for p in parts[:-1]):
    return bytes(int(p) for p in parts[:-1]).decode("utf-8", "replace")
  return value


def _ssid_keyfile(ssid: str) -> str:
  if ssid.isascii() and ssid.isprintable():
    return ssid
  return "".join(f"{b};" for b in ssid.encode())


def read_profiles() -> list[Profile]:
  profiles = []
  for directory in PROFILE_DIRS:
    for path in sorted(Path(directory).glob("*.nmconnection")):
      cp = configparser.ConfigParser(interpolation=None, strict=False)
      try:
        cp.read_string(sudo_read(str(path)))
      except configparser.Error:
        cloudlog.warning(f"Unreadable connection profile {path}")
        continue
      if cp.get("connection", "type", fallback="") != "wifi":
        continue
      ssid = _keyfile_ssid(cp.get("wifi", "ssid", fallback=""))
      profile_uuid = cp.get("connection", "uuid", fallback="")
      if not ssid or not profile_uuid:
        cloudlog.warning(f"Wi-Fi profile without ssid or uuid {path}")
        continue
      metered = cp.getint("connection", "metered", fallback=0)
      profiles.append(Profile(path=str(path), uuid=profile_uuid, ssid=ssid, psk=cp.get("wifi-security", "psk", fallback=None),
                              hidden=cp.getboolean("wifi", "hidden", fallback=False),
                              metered=MeteredType(metered) if metered in (MeteredType.YES, MeteredType.NO) else MeteredType.UNKNOWN,
                              is_ap=cp.get("wifi", "mode", fallback="") == "ap"))
  return profiles


def remove_profile(profile: Profile) -> None:
  _sudo("rm", "-f", profile.path)
  if os.path.basename(profile.path).startswith("netplan-NM-"):
    _sudo("rm", "-f", os.path.join(NETPLAN_DIR, f"90-NM-{profile.uuid}.yaml"))


def write_profile(profile: Profile) -> Profile:
  # persistent keyfile in the shape NetworkManager wrote for openpilot, so a rollback keeps the network
  cp = configparser.ConfigParser(interpolation=None)
  cp["connection"] = {"id": "Hotspot" if profile.is_ap else f"openpilot connection {profile.ssid}", "uuid": profile.uuid, "type": "wifi",
                      "autoconnect-retries": "0"}
  cp["wifi"] = {"ssid": _ssid_keyfile(profile.ssid)}
  if profile.is_ap:
    cp["connection"].update({"interface-name": WLAN, "autoconnect": "false"})
    cp["wifi"].update({"band": "bg", "mode": "ap"})
    cp["wifi-security"] = {"group": "ccmp;", "key-mgmt": "wpa-psk", "pairwise": "ccmp;", "proto": "rsn;", "psk": profile.psk or ""}
    cp["ipv4"] = {"method": "shared", "address1": f"{TETHERING_IP_ADDRESS}/24,{TETHERING_IP_ADDRESS}", "never-default": "true"}
  else:
    if profile.metered != MeteredType.UNKNOWN:
      cp["connection"]["metered"] = str(int(profile.metered))
    cp["wifi"].update({"mode": "infrastructure", "hidden": "true" if profile.hidden else "false"})
    if profile.psk:
      cp["wifi-security"] = {"key-mgmt": "wpa-psk", "auth-alg": "open", "psk": profile.psk}
    cp["ipv4"] = {"method": "auto", "dns-priority": "600"}
  cp["ipv6"] = {"method": "ignore"}

  path = os.path.join(PROFILE_DIRS[0], f"{urllib.parse.quote(profile.ssid, safe='')}.nmconnection")
  with tempfile.NamedTemporaryFile("w", delete=False) as f:
    cp.write(f, space_around_delimiters=False)
  try:
    _sudo("install", "-m", "600", f.name, path)
  finally:
    os.unlink(f.name)
  for other in read_profiles():
    if other.uuid == profile.uuid and other.path != path:
      remove_profile(other)
  return replace(profile, path=path)
```

- [ ] **Step 4: Run the tests, expect them to pass**

Run: `python tools/test_runner.py openpilot/system/ui/lib/tests/test_wifi_manager.py -v`
Expected: all `TestParsers`, `TestWpaCtrl`, `TestProfiles` pass. `test_read_profiles_from_both_dirs` writes the netplan keyfile with `metered=1` moved into the first `[connection]` section because `configparser` rejects duplicate sections; that mirrors real files, which have one section.

- [ ] **Step 5: Commit**

```bash
git add openpilot/system/ui/lib/wifi_manager.py openpilot/system/ui/lib/tests/test_wifi_manager.py
git commit -m "wifi: read and write NetworkManager keyfile profiles"
```

---

### Task 3: WifiManager lifecycle, status and scanning

**Files:**
- Modify: `openpilot/system/ui/lib/wifi_manager.py` (replace `_pid_alive`, append `WifiManager`)
- Modify: `openpilot/system/ui/lib/tests/test_wifi_manager.py` (append)

**Interfaces:**
- Consumes: Task 1 client and parsers, Task 2 storage.
- Produces: `WifiManager` with the upstream public surface (`add_callbacks`, `networks`, `wifi_state`, `ipv4_address`, `current_network_metered`, `connecting_to_ssid`, `connected_ssid`, `tethering_password`, `process_callbacks`, `set_active`, `is_tethering_active`, `is_connection_saved`, `stop`) plus internals used by later tasks: `_lock` (RLock), `_exit` (Event), `_ctrl`, `_events`, `_network_ids: dict[int, str]`, `_profiles`, `_selected`, `_pending`, `_status()`, `_refresh_status()`, `_add_network(ssid, psk, hidden) -> int`, `_list_networks()`, `_start_dhcp()`, `_stop_dhcp()`, `_enqueue_callbacks(cbs, *args)`, `_handle_event(event)`, `_on_disconnected()`, `_update_networks()`. Test fixture `manager_env` and helper `start_manager(env)`.

- [ ] **Step 1: Write the failing lifecycle tests**

Append to `test_wifi_manager.py`:

```python
def manager_env(mocker: Mocker, profile_dirs):
  d = tempfile.mkdtemp()
  env = types.SimpleNamespace(dirs=profile_dirs, sudo=profile_dirs["sudo"], fake=None, popen=[], ctrl_path=os.path.join(d, "wlan0"),
                              wpa_pid=os.path.join(d, "wlan0.pid"), udhcpc_pid=os.path.join(d, "udhcpc.pid"), dnsmasq_pid=os.path.join(d, "dnsmasq.pid"),
                              spawn_status={"wpa_state": "DISCONNECTED"}, managers=[])
  mocker.patch.object(wifi_manager, "WPA_CTRL_PATH", env.ctrl_path)
  mocker.patch.object(wifi_manager, "WPA_PID_PATH", env.wpa_pid)
  mocker.patch.object(wifi_manager, "UDHCPC_PID_PATH", env.udhcpc_pid)
  mocker.patch.object(wifi_manager, "DNSMASQ_PID_PATH", env.dnsmasq_pid)
  mocker.patch.object(wifi_manager, "Params", None)
  mocker.patch.object(wifi_manager, "SCAN_PERIOD_SECONDS", 0.1)
  mocker.patch.object(wifi_manager, "HANDOFF_TIMEOUT_SECONDS", 1)

  def alive(path):
    write(path, f"{os.getpid()}\n")

  def spawn_fake():
    env.fake = FakeSupplicant(env.ctrl_path)
    env.fake.status = dict(env.spawn_status)
    alive(env.wpa_pid)

  env.alive = alive
  env.spawn_fake = spawn_fake

  inner = fake_sudo(env.sudo)

  def _sudo(*cmd, check=True):
    if cmd[0] == "wpa_supplicant":
      spawn_fake()
    return inner(*cmd, check=check)

  mocker.patch.object(wifi_manager, "_sudo", _sudo)

  def popen(cmd, **kwargs):
    env.popen.append(cmd)
    return unittest.mock.MagicMock()

  mocker.patch.object(wifi_manager.subprocess, "Popen", popen)
  yield env
  for wm in env.managers:
    wm.stop()
  if env.fake is not None:
    env.fake.close()
  shutil.rmtree(d)


def start_manager(env):
  wm = wifi_manager.WifiManager()
  env.managers.append(wm)
  wait_for(lambda: wm._ready)
  return wm


def drain(wm, events: list):
  wm.process_callbacks()
  return events


class TestLifecycle(OpenpilotTestCase):
  def test_fresh_start_hands_off_and_loads_saved_networks(self, manager_env):
    write(os.path.join(manager_env.dirs["persistent"], "Home.nmconnection"), KEYFILE_A)
    write(os.path.join(manager_env.dirs["persistent"], "Open.nmconnection"), OPEN_KEYFILE)
    write(os.path.join(manager_env.dirs["persistent"], "Hotspot.nmconnection"), HOTSPOT_KEYFILE)
    write(os.path.join(manager_env.dirs["runtime"], "netplan-NM-2222-Caf.nmconnection"), NETPLAN_KEYFILE.replace("[connection]\nmetered=1\n", ""))
    wm = start_manager(manager_env)
    self.assertEqual(manager_env.sudo[:2], [["nmcli", "dev", "set", "wlan0", "managed", "no"],
                                             ["wpa_supplicant", "-B", "-i", "wlan0", "-D", "nl80211", "-c", wifi_manager.WPA_CONF_PATH, "-P", manager_env.wpa_pid]])
    nets = {bytes.fromhex(n["ssid"]).decode(): n for n in manager_env.fake.networks.values()}
    self.assertEqual(set(nets), {"Home", "Open", "Café"})
    self.assertEqual(nets["Home"]["psk"], wpa_psk("Home", "password123"))
    self.assertEqual(nets["Open"]["key_mgmt"], "NONE")
    self.assertEqual(nets["Café"]["scan_ssid"], "1")
    self.assertIn("ENABLE_NETWORK all", manager_env.fake.requests)
    self.assertEqual(manager_env.popen, [["sudo", "udhcpc", "-i", "wlan0", "-f", "-R", "-s", wifi_manager.UDHCPC_SCRIPT_PATH, "-p", manager_env.udhcpc_pid]])
    self.assertEqual(wm.wifi_state, wifi_manager.WifiState())
    self.assertTrue(wm.is_connection_saved("Home"))
    self.assertTrue(wm.is_connection_saved("weedle"))
    self.assertFalse(wm.is_connection_saved("Elsewhere"))
    self.assertFalse(wm.is_tethering_active())

  def test_adopts_connected_station_without_respawning(self, manager_env):
    write(os.path.join(manager_env.dirs["persistent"], "Home.nmconnection"), KEYFILE_A.replace("type=wifi\n", "type=wifi\nmetered=2\n"))
    manager_env.spawn_status = {"wpa_state": "COMPLETED", "ssid": "Home", "mode": "station", "ip_address": "10.0.0.5", "id": "0"}
    manager_env.spawn_fake()
    manager_env.fake.networks = {0: {"ssid": "Home".encode().hex()}}
    manager_env.alive(manager_env.udhcpc_pid)
    wm = start_manager(manager_env)
    self.assertEqual([c[0] for c in manager_env.sudo], ["kill"])
    self.assertEqual(manager_env.sudo[0][:2], ["kill", "-USR1"])
    self.assertEqual(manager_env.popen, [])
    self.assertEqual(wm.wifi_state, wifi_manager.WifiState("Home", wifi_manager.ConnectStatus.CONNECTED))
    self.assertEqual(wm.connected_ssid, "Home")
    self.assertEqual(wm.ipv4_address, "10.0.0.5")
    self.assertEqual(wm.current_network_metered, wifi_manager.MeteredType.NO)
    self.assertEqual(wm._network_ids, {0: "Home"})

  def test_adopts_associating_station_as_connecting(self, manager_env):
    manager_env.spawn_status = {"wpa_state": "4WAY_HANDSHAKE", "ssid": "Home", "mode": "station"}
    manager_env.spawn_fake()
    wm = start_manager(manager_env)
    self.assertEqual(wm.connecting_to_ssid, "Home")
    self.assertEqual(wm.ipv4_address, "")

  def test_scan_results_update_sorted_networks(self, manager_env):
    write(os.path.join(manager_env.dirs["persistent"], "Home.nmconnection"), KEYFILE_A)
    wm = start_manager(manager_env)
    updates = []
    wm.add_callbacks(networks_updated=updates.append)
    manager_env.fake.replies["SCAN_RESULTS"] = (SCAN_HEADER + "aa\t2412\t-75\t[WPA2-PSK-CCMP][ESS]\tHome\n" + "ab\t5180\t-50\t[WPA2-PSK-CCMP][ESS]\tHome\n"
                                                + "cc\t2437\t-40\t[ESS]\tCoffee\n" + "dd\t2437\t-90\t[WPA2-PSK-CCMP][ESS]\tweedle\n"
                                                + "ee\t2437\t-60\t[WPA2-EAP-CCMP][ESS]\tOffice\n" + "ff\t2437\t-30\t[ESS]\t\n")
    wait_for(lambda: "SCAN" in manager_env.fake.requests)
    manager_env.fake.emit("CTRL-EVENT-SCAN-RESULTS")
    wait_for(lambda: drain(wm, updates))
    self.assertEqual(updates[-1], [wifi_manager.Network("Home", 83, SecurityType.WPA, False), wifi_manager.Network("weedle", 100, SecurityType.WPA, True),
                                   wifi_manager.Network("Coffee", 100, SecurityType.OPEN, False), wifi_manager.Network("Office", 66, SecurityType.UNSUPPORTED, False)])
    self.assertEqual(updates[-1], wm.networks)

  def test_stop_leaves_daemons_running(self, manager_env):
    manager_env.spawn_status = {"wpa_state": "COMPLETED", "ssid": "Home", "mode": "station", "ip_address": "10.0.0.5", "id": "0"}
    manager_env.spawn_fake()
    manager_env.alive(manager_env.udhcpc_pid)
    wm = start_manager(manager_env)
    wm.stop()
    self.assertNotIn(["kill", str(os.getpid())], manager_env.sudo)
    self.assertFalse(wm._scan_thread.is_alive())
    self.assertFalse(wm._monitor_thread.is_alive())
    self.assertEqual(WpaCtrl(manager_env.ctrl_path).request("PING"), "PONG")
```

Add `import types` and `import unittest.mock` to the test imports.

- [ ] **Step 2: Run the tests, expect failures**

Run: `python tools/test_runner.py openpilot/system/ui/lib/tests/test_wifi_manager.py -k TestLifecycle -v`
Expected: 5 failures with `AttributeError: module ... has no attribute 'WifiManager'`.

- [ ] **Step 3: Implement the manager**

In `wifi_manager.py`, replace `_pid_alive` with:

```python
def _read_pid(pid_path: str) -> int | None:
  try:
    with open(pid_path) as f:
      return int(f.read().strip())
  except (OSError, ValueError):
    return None


def _pid_alive(pid_path: str) -> bool:
  pid = _read_pid(pid_path)
  if pid is None:
    return False
  try:
    os.kill(pid, 0)
  except ProcessLookupError:
    return False
  except PermissionError:
    pass  # root-owned daemon
  return True
```

Append the manager:

```python
ASSOCIATING_STATES = ("AUTHENTICATING", "ASSOCIATING", "ASSOCIATED", "4WAY_HANDSHAKE", "GROUP_HANDSHAKE")


class WifiManager:
  def __init__(self):
    self._networks: list[Network] = []  # an unsorted list of available Networks. a Network can be comprised of multiple APs
    self._active = True  # used to not run when not in settings
    self._exit = threading.Event()
    self._ready = False
    self._lock = threading.RLock()

    self._ctrl: WpaCtrl | None = None
    self._events: socket.socket | None = None
    self._network_ids: dict[int, str] = {}  # wpa_supplicant network id -> ssid
    self._profiles: list[Profile] = []

    # State
    self._wifi_state = WifiState()
    self._selected: str | None = None  # ssid the user asked for, kept until the attempt ends
    self._pending: Profile | None = None  # new network, persisted once it has an address
    self._ipv4_address = ""
    self._current_network_metered = MeteredType.UNKNOWN
    self._ipv4_forward = False
    self._callback_queue: list[Callable] = []

    self._tethering_ssid = "weedle"
    if Params is not None:
      dongle_id = Params().get("DongleId")
      if dongle_id:
        self._tethering_ssid += "-" + dongle_id[:4]

    # Callbacks
    self._need_auth: list[Callable[[str], None]] = []
    self._activated: list[Callable[[], None]] = []
    self._forgotten: list[Callable[[str | None], None]] = []
    self._networks_updated: list[Callable[[list[Network]], None]] = []
    self._disconnected: list[Callable[[], None]] = []

    self._scan_thread = threading.Thread(target=self._network_scanner, daemon=True)
    self._monitor_thread = threading.Thread(target=self._monitor, daemon=True)
    threading.Thread(target=self._initialize, daemon=True).start()
    atexit.register(self.stop)

  def _initialize(self):
    try:
      self._start_supplicant()
    except Exception:
      cloudlog.exception("WifiManager failed to start wpa_supplicant")
    self._ready = True
    self._scan_thread.start()
    self._monitor_thread.start()
    cloudlog.debug("WifiManager initialized")

  def _start_supplicant(self):
    adopt = _pid_alive(WPA_PID_PATH)
    if not adopt:
      _sudo("nmcli", "dev", "set", WLAN, "managed", "no", check=False)
      self._wait_for_handoff()
      _sudo("wpa_supplicant", "-B", "-i", WLAN, "-D", "nl80211", "-c", WPA_CONF_PATH, "-P", WPA_PID_PATH)
    ctrl = self._connect_ctrl()
    events = ctrl.attach()
    with self._lock:
      self._ctrl, self._events = ctrl, events
      self._profiles = read_profiles()
      self._network_ids = self._list_networks() if adopt else {}
      if not adopt:
        for profile in self._profiles:
          if not profile.is_ap:
            self._add_network(profile.ssid, profile.psk, profile.hidden)
        ctrl.ok("ENABLE_NETWORK all")
    self._refresh_status()
    if not self.is_tethering_active():
      self._start_dhcp()

  def _wait_for_handoff(self):
    # NetworkManager tears wlan0 down asynchronously; its supplicant socket stops answering when done
    deadline = time.monotonic() + HANDOFF_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
      try:
        ctrl = WpaCtrl(WPA_CTRL_PATH)
      except OSError:
        return
      try:
        ctrl.request("PING")
      except OSError:
        return
      finally:
        ctrl.close()
      time.sleep(0.2)
    cloudlog.warning(f"{WLAN} was not released by NetworkManager")

  def _connect_ctrl(self) -> WpaCtrl:
    deadline = time.monotonic() + HANDOFF_TIMEOUT_SECONDS
    while True:
      try:
        ctrl = WpaCtrl(WPA_CTRL_PATH)
        if ctrl.request("PING") == "PONG":
          return ctrl
        ctrl.close()
      except OSError:
        pass
      if time.monotonic() > deadline:
        raise OSError(f"wpa_supplicant control socket {WPA_CTRL_PATH} not available")
      time.sleep(0.2)

  def _list_networks(self) -> dict[int, str]:
    ids = {}
    for line in self._ctrl.request("LIST_NETWORKS").splitlines()[1:]:
      fields = line.split("\t")
      if len(fields) >= 2 and fields[0].isdigit():
        ids[int(fields[0])] = decode_ssid(fields[1])
    return ids

  def _add_network(self, ssid: str, psk: str | None, hidden: bool) -> int:
    nid = int(self._ctrl.request("ADD_NETWORK"))
    settings = [f"ssid {ssid.encode().hex()}", f"psk {wpa_psk(ssid, psk)}" if psk else "key_mgmt NONE"]
    if hidden:
      settings.append("scan_ssid 1")
    for setting in settings:
      if not self._ctrl.ok(f"SET_NETWORK {nid} {setting}"):
        self._ctrl.ok(f"REMOVE_NETWORK {nid}")
        raise ValueError(f"wpa_supplicant rejected {setting.split()[0]} for {ssid}")
    self._network_ids[nid] = ssid
    return nid

  def _status(self) -> dict[str, str]:
    if self._ctrl is None:
      return {}
    try:
      return parse_status(self._ctrl.request("STATUS"))
    except OSError:
      cloudlog.warning("wpa_supplicant STATUS failed")
      return {}

  def _refresh_status(self):
    status = self._status()
    with self._lock:
      ssid = decode_ssid(status.get("ssid", ""))
      wpa_state = status.get("wpa_state", "")
      ipv4_address, metered = "", MeteredType.UNKNOWN
      if wpa_state == "COMPLETED" and status.get("mode") == "AP":
        wifi_state, ipv4_address = WifiState(ssid, ConnectStatus.CONNECTED), TETHERING_IP_ADDRESS
      elif wpa_state == "COMPLETED" and status.get("ip_address"):
        wifi_state, ipv4_address = WifiState(ssid, ConnectStatus.CONNECTED), status["ip_address"]
        metered = next((p.metered for p in self._profiles if p.ssid == ssid), MeteredType.UNKNOWN)
      elif wpa_state == "COMPLETED" or wpa_state in ASSOCIATING_STATES:
        wifi_state = WifiState(ssid or self._selected, ConnectStatus.CONNECTING)
      elif self._selected is not None:
        wifi_state = WifiState(self._selected, ConnectStatus.CONNECTING)
      else:
        wifi_state = WifiState()
      if wifi_state.status == ConnectStatus.CONNECTED and wifi_state.ssid == self._selected:
        self._selected = None
      self._wifi_state, self._ipv4_address, self._current_network_metered = wifi_state, ipv4_address, metered

  def _start_dhcp(self):
    # one udhcpc for the life of the supplicant; a renew after each association fetches a lease for the new network
    pid = _read_pid(UDHCPC_PID_PATH)
    if pid is not None and _pid_alive(UDHCPC_PID_PATH):
      _sudo("kill", "-USR1", str(pid), check=False)
    else:
      subprocess.Popen(["sudo", "udhcpc", "-i", WLAN, "-f", "-R", "-s", UDHCPC_SCRIPT_PATH, "-p", UDHCPC_PID_PATH],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

  def _stop_dhcp(self):
    pid = _read_pid(UDHCPC_PID_PATH)
    if pid is not None and _pid_alive(UDHCPC_PID_PATH):
      _sudo("kill", str(pid), check=False)

  def add_callbacks(self, need_auth: Callable[[str], None] | None = None,
                    activated: Callable[[], None] | None = None,
                    forgotten: Callable[[str | None], None] | None = None,
                    networks_updated: Callable[[list[Network]], None] | None = None,
                    disconnected: Callable[[], None] | None = None):
    if need_auth is not None:
      self._need_auth.append(need_auth)
    if activated is not None:
      self._activated.append(activated)
    if forgotten is not None:
      self._forgotten.append(forgotten)
    if networks_updated is not None:
      self._networks_updated.append(networks_updated)
    if disconnected is not None:
      self._disconnected.append(disconnected)

  @property
  def networks(self) -> list[Network]:
    # Sort by connected/connecting, then known, then strength, then alphabetically. This is a pure UI ordering and should not affect underlying state.
    return sorted(self._networks, key=lambda n: (n.ssid != self._wifi_state.ssid, not self.is_connection_saved(n.ssid), -n.strength, n.ssid.lower()))

  @property
  def wifi_state(self) -> WifiState:
    return self._wifi_state

  @property
  def ipv4_address(self) -> str:
    return self._ipv4_address

  @property
  def current_network_metered(self) -> MeteredType:
    return self._current_network_metered

  @property
  def connecting_to_ssid(self) -> str | None:
    wifi_state = self._wifi_state
    return wifi_state.ssid if wifi_state.status == ConnectStatus.CONNECTING else None

  @property
  def connected_ssid(self) -> str | None:
    wifi_state = self._wifi_state
    return wifi_state.ssid if wifi_state.status == ConnectStatus.CONNECTED else None

  def is_tethering_active(self) -> bool:
    # Check ssid, not connected_ssid, to also catch connecting state
    return self._wifi_state.ssid == self._tethering_ssid

  def is_connection_saved(self, ssid: str) -> bool:
    return any(p.ssid == ssid for p in self._profiles)

  def _enqueue_callbacks(self, cbs: list[Callable], *args):
    for cb in cbs:
      self._callback_queue.append(lambda _cb=cb: _cb(*args))

  def process_callbacks(self):
    # Call from UI thread to run any pending callbacks
    to_run, self._callback_queue = self._callback_queue, []
    for cb in to_run:
      cb()

  def set_active(self, active: bool):
    self._active = active

    # Update networks and WiFi state (to self-heal) immediately when activating for UI
    if active:
      threading.Thread(target=self._update_networks, daemon=True).start()

  def _network_scanner(self):
    while not self._exit.is_set():
      if self._active and self._ctrl is not None:
        try:
          self._ctrl.request("SCAN")
        except OSError:
          cloudlog.warning("wpa_supplicant SCAN failed")
      self._exit.wait(SCAN_PERIOD_SECONDS)

  def _update_networks(self):
    if not self._active or self._ctrl is None:
      return
    try:
      results = parse_scan_results(self._ctrl.request("SCAN_RESULTS"))
    except OSError:
      cloudlog.warning("wpa_supplicant SCAN_RESULTS failed")
      return

    best: dict[str, tuple[int, str]] = {}  # ssid -> strongest (dBm, flags)
    for ssid, dbm, flags in results:
      if ssid and (ssid not in best or dbm > best[ssid][0]):
        best[ssid] = (dbm, flags)

    self._refresh_status()
    with self._lock:
      self._networks = [Network(ssid, 100 if ssid == self._tethering_ssid else dbm_to_percent(dbm), security_type_from_flags(flags), ssid == self._tethering_ssid)
                        for ssid, (dbm, flags) in best.items()]
    self._enqueue_callbacks(self._networks_updated, self.networks)  # sorted

  def _monitor(self):
    while not self._exit.is_set():
      events = self._events
      if events is None:
        time.sleep(0.5)
        continue
      try:
        data = events.recv(4096).decode("utf-8", "replace")
      except TimeoutError:
        continue
      except OSError:
        cloudlog.exception("wpa_supplicant event socket failed")
        self._events = None
        continue
      event = re.sub(r"^<\d>", "", data).strip()
      try:
        self._handle_event(event)
      except Exception:
        cloudlog.exception(f"Failed to handle wpa_supplicant event: {event}")

  def _handle_event(self, event: str):
    if event.startswith("CTRL-EVENT-SCAN-RESULTS"):
      self._update_networks()
    elif event.startswith("CTRL-EVENT-DISCONNECTED"):
      self._on_disconnected()

  def _on_disconnected(self):
    was_connected = self._wifi_state.status == ConnectStatus.CONNECTED
    self._refresh_status()
    if was_connected and self._wifi_state.status == ConnectStatus.DISCONNECTED:
      self._enqueue_callbacks(self._disconnected)

  def __del__(self):
    self.stop()

  def stop(self):
    if not self._exit.is_set():
      self._exit.set()
      for thread in (self._scan_thread, self._monitor_thread):
        if thread.is_alive():
          thread.join()
      for sock in (self._events, self._ctrl):
        if sock is not None:
          sock.close()
```

- [ ] **Step 4: Run the tests, expect them to pass**

Run: `python tools/test_runner.py openpilot/system/ui/lib/tests/test_wifi_manager.py -v`
Expected: all pass. In `test_scan_results_update_sorted_networks` the strengths are `dbm_to_percent(-50) = 83`, `-60 = 66`, the tethering SSID is forced to 100, the empty SSID is dropped, and the saved `Home` sorts first because nothing is connected and it is the only saved network.

- [ ] **Step 5: Commit**

```bash
git add openpilot/system/ui/lib/wifi_manager.py openpilot/system/ui/lib/tests/test_wifi_manager.py
git commit -m "wifi: manage wpa_supplicant and udhcpc directly"
```

---

### Task 4: Station flow: connect, activate, forget, wrong password, DHCP

**Files:**
- Modify: `openpilot/system/ui/lib/wifi_manager.py` (extend `_handle_event`, add methods to `WifiManager`)
- Modify: `openpilot/system/ui/lib/tests/test_wifi_manager.py` (append)

**Interfaces:**
- Consumes: Task 3 internals.
- Produces: `connect_to_network(ssid, password, hidden=False)`, `activate_connection(ssid, block=False)`, `forget_connection(ssid, block=False)`, `_network_id(ssid) -> int | None`, `_on_associated()`, `_on_wrong_key(nid)`, `_abandon(ssid)`.

- [ ] **Step 1: Write the failing station tests**

Append to `test_wifi_manager.py`:

```python
def profile_files(env):
  return sorted(os.listdir(env.dirs["persistent"]))


class TestStation(OpenpilotTestCase):
  def test_connect_persists_after_first_address(self, manager_env):
    wm = start_manager(manager_env)
    activated, forgotten = [], []
    wm.add_callbacks(activated=lambda: activated.append(True), forgotten=forgotten.append)
    manager_env.alive(manager_env.udhcpc_pid)
    wm.connect_to_network("Home", "password123")
    wait_for(lambda: any(r.startswith("SELECT_NETWORK") for r in manager_env.fake.requests))
    (nid,) = manager_env.fake.networks
    self.assertEqual(manager_env.fake.networks[nid], {"ssid": "Home".encode().hex(), "psk": wpa_psk("Home", "password123")})
    self.assertEqual(wm.connecting_to_ssid, "Home")
    self.assertEqual(profile_files(manager_env), [])

    manager_env.fake.status = {"wpa_state": "COMPLETED", "ssid": "Home", "mode": "station", "id": str(nid)}
    manager_env.fake.emit(f"CTRL-EVENT-CONNECTED - Connection to aa:bb completed [id={nid} id_str=]")
    wait_for(lambda: ["kill", "-USR1", str(os.getpid())] in manager_env.sudo)
    self.assertEqual(wm.connecting_to_ssid, "Home")
    self.assertEqual(profile_files(manager_env), [])
    wait_for(lambda: manager_env.fake.requests.count("ENABLE_NETWORK all") >= 2)

    manager_env.fake.status["ip_address"] = "10.0.0.9"
    wait_for(lambda: wm.connected_ssid == "Home")
    wait_for(lambda: drain(wm, activated))
    self.assertEqual(wm.ipv4_address, "10.0.0.9")
    self.assertEqual(profile_files(manager_env), ["Home.nmconnection"])
    self.assertTrue(wm.is_connection_saved("Home"))
    self.assertEqual(wifi_manager.read_profiles()[0].psk, "password123")
    self.assertEqual(forgotten, ["Home"])  # connect clears any previous profile first, as upstream did

  def test_wrong_password_asks_once_and_saves_nothing(self, manager_env):
    wm = start_manager(manager_env)
    need_auth = []
    wm.add_callbacks(need_auth=need_auth.append)
    wm.connect_to_network("Home", "wrongpass")
    wait_for(lambda: any(r.startswith("SELECT_NETWORK") for r in manager_env.fake.requests))
    (nid,) = manager_env.fake.networks
    manager_env.fake.emit(f'CTRL-EVENT-SSID-TEMP-DISABLED id={nid} ssid="Home" auth_failures=1 duration=10 reason=WRONG_KEY')
    wait_for(lambda: drain(wm, need_auth) == ["Home"])
    self.assertEqual(wm.wifi_state, wifi_manager.WifiState())
    self.assertEqual(manager_env.fake.networks, {})
    self.assertEqual(profile_files(manager_env), [])
    self.assertIn("ENABLE_NETWORK all", manager_env.fake.requests[-2:])

  def test_activate_saved_network_selects_it(self, manager_env):
    write(os.path.join(manager_env.dirs["persistent"], "Home.nmconnection"), KEYFILE_A)
    wm = start_manager(manager_env)
    wm.activate_connection("Home")
    wait_for(lambda: "SELECT_NETWORK 0" in manager_env.fake.requests)
    self.assertEqual(wm.connecting_to_ssid, "Home")

    wm.activate_connection("Unknown", block=True)
    self.assertEqual(wm.wifi_state, wifi_manager.WifiState())
    self.assertEqual([r for r in manager_env.fake.requests if r.startswith("SELECT")], ["SELECT_NETWORK 0"])

  def test_forget_removes_every_source(self, manager_env):
    write(os.path.join(manager_env.dirs["persistent"], "Home.nmconnection"), KEYFILE_A)
    write(os.path.join(manager_env.dirs["runtime"], "netplan-NM-22222222-2222-2222-2222-222222222222-Caf.nmconnection"), NETPLAN_KEYFILE.replace("[connection]\nmetered=1\n", ""))
    yaml = os.path.join(manager_env.dirs["netplan"], "90-NM-22222222-2222-2222-2222-222222222222.yaml")
    write(yaml, "network: {}\n")
    wm = start_manager(manager_env)
    forgotten = []
    wm.add_callbacks(forgotten=forgotten.append)
    for ssid in ("Café", "Home"):
      with self.subTest(ssid=ssid):
        nid = next(i for i, s in wm._network_ids.items() if s == ssid)
        wm.forget_connection(ssid, block=True)
        self.assertIn(f"REMOVE_NETWORK {nid}", manager_env.fake.requests)
        self.assertFalse(wm.is_connection_saved(ssid))
        self.assertEqual(drain(wm, forgotten)[-1], ssid)
    self.assertFalse(os.path.exists(yaml))
    self.assertEqual(os.listdir(manager_env.dirs["runtime"]) + profile_files(manager_env), [])

  def test_forget_connected_network_disconnects(self, manager_env):
    write(os.path.join(manager_env.dirs["persistent"], "Home.nmconnection"), KEYFILE_A)
    manager_env.spawn_status = {"wpa_state": "COMPLETED", "ssid": "Home", "mode": "station", "ip_address": "10.0.0.5", "id": "0"}
    manager_env.spawn_fake()
    manager_env.fake.networks = {0: {"ssid": "Home".encode().hex()}}
    wm = start_manager(manager_env)
    disconnected = []
    wm.add_callbacks(disconnected=lambda: disconnected.append(True))
    wm.forget_connection("Home", block=True)
    manager_env.fake.status = {"wpa_state": "DISCONNECTED"}
    manager_env.fake.emit("CTRL-EVENT-DISCONNECTED bssid=aa:bb reason=3 locally_generated=1")
    wait_for(lambda: drain(wm, disconnected))
    self.assertEqual(wm.wifi_state, wifi_manager.WifiState())
    self.assertEqual(wm.ipv4_address, "")
    self.assertEqual(profile_files(manager_env), [])

  def test_dhcp_timeout_reports_disconnected(self, manager_env, mocker):
    mocker.patch.object(wifi_manager, "DHCP_TIMEOUT_SECONDS", 0.5)
    wm = start_manager(manager_env)
    disconnected = []
    wm.add_callbacks(disconnected=lambda: disconnected.append(True))
    wm.connect_to_network("Home", "password123")
    wait_for(lambda: any(r.startswith("SELECT_NETWORK") for r in manager_env.fake.requests))
    (nid,) = manager_env.fake.networks
    manager_env.fake.status = {"wpa_state": "COMPLETED", "ssid": "Home", "mode": "station", "id": str(nid)}
    manager_env.fake.emit(f"CTRL-EVENT-CONNECTED - Connection to aa:bb completed [id={nid} id_str=]")
    wait_for(lambda: drain(wm, disconnected))
    self.assertIn(f"DISABLE_NETWORK {nid}", manager_env.fake.requests)
    self.assertEqual(wm.wifi_state, wifi_manager.WifiState())
    self.assertEqual(profile_files(manager_env), [])

  def test_link_loss_reports_disconnected(self, manager_env):
    manager_env.spawn_status = {"wpa_state": "COMPLETED", "ssid": "Home", "mode": "station", "ip_address": "10.0.0.5", "id": "0"}
    manager_env.spawn_fake()
    wm = start_manager(manager_env)
    disconnected = []
    wm.add_callbacks(disconnected=lambda: disconnected.append(True))
    manager_env.fake.status = {"wpa_state": "SCANNING"}
    manager_env.fake.emit("CTRL-EVENT-DISCONNECTED bssid=aa:bb reason=4")
    wait_for(lambda: drain(wm, disconnected))
    self.assertEqual(wm.wifi_state, wifi_manager.WifiState())
    self.assertEqual(wm.ipv4_address, "")
```

- [ ] **Step 2: Run the tests, expect failures**

Run: `python tools/test_runner.py openpilot/system/ui/lib/tests/test_wifi_manager.py -k TestStation -v`
Expected: `AttributeError: 'WifiManager' object has no attribute 'connect_to_network'` and friends.

- [ ] **Step 3: Implement the station flow**

In `_handle_event`, add two branches before the DISCONNECTED one:

```python
  def _handle_event(self, event: str):
    if event.startswith("CTRL-EVENT-SCAN-RESULTS"):
      self._update_networks()
    elif event.startswith("CTRL-EVENT-CONNECTED"):
      self._on_associated()
    elif event.startswith("CTRL-EVENT-SSID-TEMP-DISABLED") and "reason=WRONG_KEY" in event.split():
      match = re.search(r"\bid=(\d+)", event)
      if match:
        self._on_wrong_key(int(match.group(1)))
    elif event.startswith("CTRL-EVENT-DISCONNECTED"):
      self._on_disconnected()
```

Add these methods to `WifiManager` (after `_on_disconnected`):

```python
  def _on_associated(self):
    status = self._status()
    if status.get("mode") == "AP":
      return  # the hotspot is brought up by set_tethering_active
    ssid = decode_ssid(status.get("ssid", ""))
    self._start_dhcp()
    self._ctrl.ok("ENABLE_NETWORK all")  # SELECT_NETWORK disabled the other saved networks

    deadline = time.monotonic() + DHCP_TIMEOUT_SECONDS
    while not self._exit.is_set() and time.monotonic() < deadline:
      status = self._status()
      if status.get("wpa_state") != "COMPLETED" or decode_ssid(status.get("ssid", "")) != ssid:
        return  # association changed, the next event decides
      if status.get("ip_address"):
        with self._lock:
          pending, self._pending = self._pending, None
          if pending is not None and pending.ssid == ssid:
            write_profile(pending)
            self._profiles = read_profiles()
        self._refresh_status()
        self._enqueue_callbacks(self._activated)
        return
      self._exit.wait(0.5)

    cloudlog.warning(f"No DHCP lease on {ssid}")
    with self._lock:
      if "id" in status:
        self._ctrl.ok(f"DISABLE_NETWORK {status['id']}")
      self._selected, self._pending = None, None
      self._wifi_state, self._ipv4_address, self._current_network_metered = WifiState(), "", MeteredType.UNKNOWN
    self._enqueue_callbacks(self._disconnected)

  def _on_wrong_key(self, nid: int):
    with self._lock:
      ssid = self._network_ids.get(nid)
      if ssid is None or ssid != self._wifi_state.ssid:
        return
      # drop the network so the supplicant stops retrying and the UI is asked once; a saved profile is re-added on activation
      self._ctrl.ok(f"REMOVE_NETWORK {nid}")
      del self._network_ids[nid]
      self._selected, self._pending = None, None
      self._wifi_state, self._ipv4_address, self._current_network_metered = WifiState(), "", MeteredType.UNKNOWN
      self._ctrl.ok("ENABLE_NETWORK all")
    self._enqueue_callbacks(self._need_auth, ssid)

  def _abandon(self, ssid: str):
    with self._lock:
      if self._selected == ssid:
        self._selected, self._pending = None, None
    self._refresh_status()

  def _network_id(self, ssid: str) -> int | None:
    for nid, known in self._network_ids.items():
      if known == ssid:
        return nid
    profile = next((p for p in self._profiles if p.ssid == ssid and not p.is_ap), None)
    if profile is None:
      return None
    return self._add_network(profile.ssid, profile.psk, profile.hidden)

  def connect_to_network(self, ssid: str, password: str, hidden: bool = False):
    with self._lock:
      self._selected = ssid
      self._pending = Profile(path="", uuid=str(uuid.uuid4()), ssid=ssid, psk=password or None, hidden=hidden, metered=MeteredType.UNKNOWN, is_ap=False)
      self._wifi_state = WifiState(ssid, ConnectStatus.CONNECTING)

    def worker():
      try:
        # Clear all connections that may already exist to the network we are connecting to
        self.forget_connection(ssid, block=True)
        with self._lock:
          nid = self._add_network(ssid, password or None, hidden)
          self._ctrl.ok(f"SELECT_NETWORK {nid}")
      except Exception:
        cloudlog.exception(f"Failed to connect to {ssid}")
        self._abandon(ssid)

    threading.Thread(target=worker, daemon=True).start()

  def activate_connection(self, ssid: str, block: bool = False):
    with self._lock:
      self._selected, self._pending = ssid, None
      self._wifi_state = WifiState(ssid, ConnectStatus.CONNECTING)

    def worker():
      try:
        with self._lock:
          nid = self._network_id(ssid)
          if nid is None:
            cloudlog.warning(f"Failed to activate connection for {ssid}: not saved")
            self._abandon(ssid)
            return
          self._ctrl.ok(f"SELECT_NETWORK {nid}")
      except Exception:
        cloudlog.exception(f"Failed to activate {ssid}")
        self._abandon(ssid)

    if block:
      worker()
    else:
      threading.Thread(target=worker, daemon=True).start()

  def forget_connection(self, ssid: str, block: bool = False):
    def worker():
      try:
        with self._lock:
          for nid, known in list(self._network_ids.items()):
            if known == ssid:
              self._ctrl.ok(f"REMOVE_NETWORK {nid}")
              del self._network_ids[nid]
          for profile in self._profiles:
            if profile.ssid == ssid:
              remove_profile(profile)
          self._profiles = read_profiles()
      except Exception:
        cloudlog.exception(f"Failed to forget {ssid}")
      self._enqueue_callbacks(self._forgotten, ssid)

    if block:
      worker()
    else:
      threading.Thread(target=worker, daemon=True).start()
```

- [ ] **Step 4: Run the tests, expect them to pass**

Run: `python tools/test_runner.py openpilot/system/ui/lib/tests/test_wifi_manager.py -v`
Expected: all pass. If `test_connect_persists_after_first_address` is flaky on the `ENABLE_NETWORK all` count, the first count comes from the fresh-start load and the second from `_on_associated`; both must be present before the address appears.

- [ ] **Step 5: Commit**

```bash
git add openpilot/system/ui/lib/wifi_manager.py openpilot/system/ui/lib/tests/test_wifi_manager.py
git commit -m "wifi: connect, activate and forget networks through wpa_supplicant"
```

---

### Task 5: Metering, hotspot profile and tethering

**Files:**
- Modify: `openpilot/system/ui/lib/wifi_manager.py` (add `AP_TIMEOUT_SECONDS`, extend `_initialize`, `_start_supplicant`, `_stop_dhcp`; add methods)
- Modify: `openpilot/system/ui/lib/tests/test_wifi_manager.py` (edit `fake_sudo`, append)

**Interfaces:**
- Consumes: Tasks 3 and 4.
- Produces: `tethering_password` property, `set_tethering_password(password)`, `set_ipv4_forward(enabled)`, `set_tethering_active(active)`, `set_current_network_metered(metered)`, `_hotspot_profile() -> Profile`, `_start_tethering()`, `_stop_tethering()`, `_ensure_tethering_services()`.

- [ ] **Step 1: Teach the fake sudo that the NAT rule is absent, then write the failing tests**

In `fake_sudo` (Task 2) add, before the `install`/`rm` branch:

```python
    if cmd[0] == "iptables-legacy" and "-C" in cmd:
      return subprocess.CompletedProcess(cmd, 1, "", "")
```

Append to `test_wifi_manager.py`:

```python
AP_STATUS = {"wpa_state": "COMPLETED", "ssid": "weedle", "mode": "AP", "id": "5"}
STATION_STATUS = {"wpa_state": "COMPLETED", "ssid": "Home", "mode": "station", "ip_address": "10.0.0.5", "id": "0"}


def ap_on_select(fake):
  def reply(cmd):
    fake.status = dict(AP_STATUS)
    return "OK\n"
  fake.replies["SELECT_NETWORK"] = reply


class TestTethering(OpenpilotTestCase):
  def test_hotspot_profile_is_created_on_first_start(self, manager_env):
    wm = start_manager(manager_env)
    self.assertEqual(profile_files(manager_env), ["weedle.nmconnection"])
    self.assertEqual(wm.tethering_password, "swagswagcomma")
    self.assertTrue(wifi_manager.read_profiles()[0].is_ap)
    self.assertEqual(manager_env.fake.networks, {})  # the hotspot is not a station network

  def test_tethering_on_then_off(self, manager_env):
    write(os.path.join(manager_env.dirs["persistent"], "Home.nmconnection"), KEYFILE_A)
    manager_env.spawn_status = dict(STATION_STATUS)
    manager_env.spawn_fake()
    manager_env.fake.networks = {0: {"ssid": "Home".encode().hex()}}
    manager_env.alive(manager_env.udhcpc_pid)
    wm = start_manager(manager_env)
    activated, disconnected = [], []
    wm.add_callbacks(activated=lambda: activated.append(True), disconnected=lambda: disconnected.append(True))
    ap_on_select(manager_env.fake)
    del manager_env.sudo[:]

    wm.set_tethering_active(True)
    wait_for(lambda: wm.connected_ssid == "weedle", timeout=10)
    wait_for(lambda: drain(wm, activated))
    self.assertTrue(wm.is_tethering_active())
    self.assertEqual(wm.ipv4_address, "192.168.43.1")
    ap = next(n for n in manager_env.fake.networks.values() if n.get("mode") == "2")
    self.assertEqual(ap, {"ssid": "weedle".encode().hex(), "mode": "2", "frequency": "2437", "key_mgmt": "WPA-PSK", "proto": "RSN", "pairwise": "CCMP",
                          "psk": wpa_psk("weedle", "swagswagcomma")})
    self.assertEqual(manager_env.sudo[0], ["kill", str(os.getpid())])  # udhcpc stopped before the mode switch
    self.assertIn(["ip", "addr", "replace", "192.168.43.1/24", "dev", "wlan0"], manager_env.sudo)
    self.assertIn(["dnsmasq", "--interface=wlan0", "--bind-interfaces", "--except-interface=lo", "--dhcp-range=192.168.43.2,192.168.43.254,24h",
                   f"--pid-file={manager_env.dnsmasq_pid}"], manager_env.sudo)
    self.assertIn(["iptables-legacy", "-t", "nat", "-A", *wifi_manager.TETHERING_NAT_RULE], manager_env.sudo)
    self.assertEqual(manager_env.sudo[-1], ["sysctl", "net.ipv4.ip_forward=0"])

    wm.set_ipv4_forward(True)
    self.assertEqual(manager_env.sudo[-1], ["sysctl", "net.ipv4.ip_forward=1"])

    manager_env.alive(manager_env.dnsmasq_pid)
    del manager_env.sudo[:]
    manager_env.fake.replies.pop("SELECT_NETWORK")
    wm.set_tethering_active(False)
    wait_for(lambda: drain(wm, disconnected), timeout=10)
    self.assertEqual(wm.wifi_state, wifi_manager.WifiState())
    self.assertFalse(wm.is_tethering_active())
    self.assertEqual(manager_env.sudo[0], ["kill", str(os.getpid())])  # dnsmasq
    self.assertIn(["iptables-legacy", "-t", "nat", "-D", *wifi_manager.TETHERING_NAT_RULE], manager_env.sudo)
    self.assertIn(["ip", "addr", "flush", "dev", "wlan0"], manager_env.sudo)
    self.assertNotIn("2", [n.get("mode") for n in manager_env.fake.networks.values()])
    self.assertEqual(manager_env.fake.requests[-1], "ENABLE_NETWORK all") if not manager_env.popen else None
    self.assertTrue(["kill", "-USR1", str(os.getpid())] in manager_env.sudo or manager_env.popen)

  def test_adopts_running_hotspot(self, manager_env):
    write(os.path.join(manager_env.dirs["persistent"], "Hotspot.nmconnection"), HOTSPOT_KEYFILE)
    manager_env.spawn_status = dict(AP_STATUS)
    manager_env.spawn_fake()
    manager_env.fake.networks = {5: {"ssid": "weedle".encode().hex(), "mode": "2"}}
    wm = start_manager(manager_env)
    self.assertTrue(wm.is_tethering_active())
    self.assertEqual(wm.ipv4_address, "192.168.43.1")
    self.assertEqual(manager_env.popen, [])
    self.assertEqual([c[0] for c in manager_env.sudo], ["ip", "dnsmasq", "iptables-legacy", "iptables-legacy", "sysctl"])

  def test_tethering_password_change_restarts_hotspot(self, manager_env):
    write(os.path.join(manager_env.dirs["persistent"], "Hotspot.nmconnection"), HOTSPOT_KEYFILE)
    manager_env.spawn_status = dict(AP_STATUS)
    manager_env.spawn_fake()
    manager_env.fake.networks = {5: {"ssid": "weedle".encode().hex(), "mode": "2"}}
    wm = start_manager(manager_env)
    ap_on_select(manager_env.fake)
    wm.set_tethering_password("newpass123")
    wait_for(lambda: wm.tethering_password == "newpass123")
    wait_for(lambda: any(n.get("psk") == wpa_psk("weedle", "newpass123") for n in manager_env.fake.networks.values()), timeout=10)
    self.assertIn("REMOVE_NETWORK 5", manager_env.fake.requests)
    self.assertEqual(wifi_manager.read_profiles()[0].psk, "newpass123")
    wait_for(lambda: wm.connected_ssid == "weedle")

  def test_tethering_start_failure_resets_state(self, manager_env, mocker):
    mocker.patch.object(wifi_manager, "AP_TIMEOUT_SECONDS", 0.3)
    manager_env.spawn_status = dict(STATION_STATUS)
    manager_env.spawn_fake()
    wm = start_manager(manager_env)
    wm.set_tethering_active(True)  # the fake never switches to AP mode
    wait_for(lambda: wm.connecting_to_ssid == "weedle")
    wait_for(lambda: wm.connected_ssid == "Home", timeout=10)
    self.assertFalse(wm.is_tethering_active())


class TestMetering(OpenpilotTestCase):
  def test_metered_rewrites_connected_profile(self, manager_env):
    write(os.path.join(manager_env.dirs["persistent"], "Home.nmconnection"), KEYFILE_A)
    manager_env.spawn_status = dict(STATION_STATUS)
    manager_env.spawn_fake()
    wm = start_manager(manager_env)
    self.assertEqual(wm.current_network_metered, wifi_manager.MeteredType.UNKNOWN)
    wm.set_current_network_metered(wifi_manager.MeteredType.YES)
    wait_for(lambda: wm.current_network_metered == wifi_manager.MeteredType.YES)
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(os.path.join(manager_env.dirs["persistent"], "Home.nmconnection"))
    self.assertEqual(cp["connection"]["metered"], "1")
    self.assertEqual(cp["wifi-security"]["psk"], "password123")

  def test_metered_migrates_netplan_profile(self, manager_env):
    runtime = os.path.join(manager_env.dirs["runtime"], "netplan-NM-22222222-2222-2222-2222-222222222222-Caf.nmconnection")
    write(runtime, NETPLAN_KEYFILE.replace("[connection]\nmetered=1\n", ""))
    yaml = os.path.join(manager_env.dirs["netplan"], "90-NM-22222222-2222-2222-2222-222222222222.yaml")
    write(yaml, "network: {}\n")
    manager_env.spawn_status = {"wpa_state": "COMPLETED", "ssid": "Caf\\xc3\\xa9", "mode": "station", "ip_address": "10.0.0.7", "id": "0"}
    manager_env.spawn_fake()
    wm = start_manager(manager_env)
    self.assertEqual(wm.connected_ssid, "Café")
    wm.set_current_network_metered(wifi_manager.MeteredType.NO)
    wait_for(lambda: wm.current_network_metered == wifi_manager.MeteredType.NO)
    self.assertFalse(os.path.exists(runtime))
    self.assertFalse(os.path.exists(yaml))
    (profile,) = wifi_manager.read_profiles()
    self.assertEqual((profile.ssid, profile.psk, profile.hidden, profile.metered, profile.uuid),
                     ("Café", "cafepass1", True, wifi_manager.MeteredType.NO, "22222222-2222-2222-2222-222222222222"))

  def test_metered_ignored_while_tethering(self, manager_env):
    write(os.path.join(manager_env.dirs["persistent"], "Hotspot.nmconnection"), HOTSPOT_KEYFILE)
    manager_env.spawn_status = dict(AP_STATUS)
    manager_env.spawn_fake()
    wm = start_manager(manager_env)
    before = manager_env.sudo[:]
    wm.set_current_network_metered(wifi_manager.MeteredType.YES)
    time.sleep(0.3)
    self.assertEqual(manager_env.sudo, before)
    self.assertEqual(wm.current_network_metered, wifi_manager.MeteredType.UNKNOWN)
```

- [ ] **Step 2: Run the tests, expect failures**

Run: `python tools/test_runner.py openpilot/system/ui/lib/tests/test_wifi_manager.py -k "TestTethering or TestMetering" -v`
Expected: `AttributeError` for `tethering_password`, `set_tethering_active`, `set_current_network_metered`; `test_hotspot_profile_is_created_on_first_start` fails on the empty profile list.

- [ ] **Step 3: Implement**

Add the constant next to `HANDOFF_TIMEOUT_SECONDS`:

```python
AP_TIMEOUT_SECONDS = 10
```

In `_initialize`, after `self._start_supplicant()` inside the same `try`, add `self._hotspot_profile()`.

In `_start_supplicant`, replace the last two lines with:

```python
    if self.is_tethering_active():
      self._ensure_tethering_services()
    else:
      self._start_dhcp()
```

Replace `_stop_dhcp` with a version that waits for the release so a later `_start_dhcp` spawns instead of signalling a dying process:

```python
  def _stop_dhcp(self):
    pid = _read_pid(UDHCPC_PID_PATH)
    if pid is None or not _pid_alive(UDHCPC_PID_PATH):
      return
    _sudo("kill", str(pid), check=False)
    deadline = time.monotonic() + CTRL_TIMEOUT_SECONDS
    while _pid_alive(UDHCPC_PID_PATH) and time.monotonic() < deadline:
      time.sleep(0.1)
```

Add to `WifiManager`:

```python
  def _hotspot_profile(self) -> Profile:
    with self._lock:
      profile = next((p for p in self._profiles if p.is_ap and p.ssid == self._tethering_ssid), None)
      if profile is None:
        profile = write_profile(Profile(path="", uuid=str(uuid.uuid4()), ssid=self._tethering_ssid, psk=DEFAULT_TETHERING_PASSWORD, hidden=False,
                                        metered=MeteredType.UNKNOWN, is_ap=True))
        self._profiles = read_profiles()
      return profile

  @property
  def tethering_password(self) -> str:
    return self._hotspot_profile().psk or ""

  def set_tethering_password(self, password: str):
    def worker():
      try:
        with self._lock:
          write_profile(replace(self._hotspot_profile(), psk=password))
          self._profiles = read_profiles()
        if self.is_tethering_active():
          self._stop_tethering()
          self._start_tethering()
      except Exception:
        cloudlog.exception("Failed to set tethering password")
        self._abandon(self._tethering_ssid)

    threading.Thread(target=worker, daemon=True).start()

  def set_ipv4_forward(self, enabled: bool):
    self._ipv4_forward = enabled
    if self.is_tethering_active():
      _sudo("sysctl", f"net.ipv4.ip_forward={int(enabled)}", check=False)

  def set_tethering_active(self, active: bool):
    def worker():
      try:
        if active:
          self._start_tethering()
        else:
          self._stop_tethering()
      except Exception:
        cloudlog.exception(f"Failed to set tethering active={active}")
        self._stop_tethering()

    threading.Thread(target=worker, daemon=True).start()

  def _start_tethering(self):
    hotspot = self._hotspot_profile()
    with self._lock:
      self._selected, self._pending = hotspot.ssid, None
      self._wifi_state = WifiState(hotspot.ssid, ConnectStatus.CONNECTING)
      self._stop_dhcp()
      nid = int(self._ctrl.request("ADD_NETWORK"))
      for setting in (f"ssid {hotspot.ssid.encode().hex()}", "mode 2", f"frequency {TETHERING_FREQUENCY}", "key_mgmt WPA-PSK", "proto RSN", "pairwise CCMP",
                      f"psk {wpa_psk(hotspot.ssid, hotspot.psk or '')}"):
        if not self._ctrl.ok(f"SET_NETWORK {nid} {setting}"):
          self._ctrl.ok(f"REMOVE_NETWORK {nid}")
          raise ValueError(f"wpa_supplicant rejected hotspot {setting.split()[0]}")
      self._network_ids[nid] = hotspot.ssid
      self._ctrl.ok(f"SELECT_NETWORK {nid}")

    deadline = time.monotonic() + AP_TIMEOUT_SECONDS
    while True:
      status = self._status()
      if status.get("mode") == "AP" and status.get("wpa_state") == "COMPLETED":
        break
      if time.monotonic() > deadline:
        raise TimeoutError("hotspot did not come up")
      self._exit.wait(0.2)

    self._ensure_tethering_services()
    with self._lock:
      self._selected = None
      self._wifi_state, self._ipv4_address, self._current_network_metered = WifiState(hotspot.ssid, ConnectStatus.CONNECTED), TETHERING_IP_ADDRESS, MeteredType.UNKNOWN
    self._enqueue_callbacks(self._activated)

  def _ensure_tethering_services(self):
    _sudo("ip", "addr", "replace", f"{TETHERING_IP_ADDRESS}/24", "dev", WLAN)
    if not _pid_alive(DNSMASQ_PID_PATH):
      _sudo("dnsmasq", f"--interface={WLAN}", "--bind-interfaces", "--except-interface=lo", f"--dhcp-range={TETHERING_DHCP_RANGE}", f"--pid-file={DNSMASQ_PID_PATH}")
    # source-subnet NAT as in NetworkManager's shared mode, so the uplink may change between eth0 and ppp0
    if _sudo("iptables-legacy", "-t", "nat", "-C", *TETHERING_NAT_RULE, check=False).returncode != 0:
      _sudo("iptables-legacy", "-t", "nat", "-A", *TETHERING_NAT_RULE)
    _sudo("sysctl", f"net.ipv4.ip_forward={int(self._ipv4_forward)}")

  def _stop_tethering(self):
    with self._lock:
      pid = _read_pid(DNSMASQ_PID_PATH)
      if pid is not None and _pid_alive(DNSMASQ_PID_PATH):
        _sudo("kill", str(pid), check=False)
      _sudo("iptables-legacy", "-t", "nat", "-D", *TETHERING_NAT_RULE, check=False)
      for nid, known in list(self._network_ids.items()):
        if known == self._tethering_ssid:
          self._ctrl.ok(f"REMOVE_NETWORK {nid}")
          del self._network_ids[nid]
      _sudo("ip", "addr", "flush", "dev", WLAN, check=False)
      self._ctrl.ok("ENABLE_NETWORK all")
      self._selected, self._pending = None, None
      self._wifi_state, self._ipv4_address, self._current_network_metered = WifiState(), "", MeteredType.UNKNOWN
    self._start_dhcp()
    self._enqueue_callbacks(self._disconnected)

  def set_current_network_metered(self, metered: MeteredType):
    def worker():
      try:
        with self._lock:
          ssid = None if self.is_tethering_active() else self.connected_ssid
          profile = next((p for p in self._profiles if p.ssid == ssid and not p.is_ap), None)
          if profile is None:
            cloudlog.warning("No active WiFi connection found")
            return
          write_profile(replace(profile, metered=metered))
          self._profiles = read_profiles()
          self._current_network_metered = metered
      except Exception:
        cloudlog.exception("Failed to update metered setting")

    threading.Thread(target=worker, daemon=True).start()
```

- [ ] **Step 4: Run the tests, expect them to pass**

Run: `python tools/test_runner.py openpilot/system/ui/lib/tests/test_wifi_manager.py -v`
Expected: all pass. `test_tethering_on_then_off` and the password test take a few seconds because `_stop_dhcp` waits for a pid that is the test process itself; that is the 2 s `CTRL_TIMEOUT_SECONDS` wait, not a hang. In `test_tethering_start_failure_resets_state` the `except` in `set_tethering_active` runs `_stop_tethering`, which returns the manager to the still-associated station and the next status refresh (scan tick) reports `Home` connected again.

- [ ] **Step 5: Commit**

```bash
git add openpilot/system/ui/lib/wifi_manager.py openpilot/system/ui/lib/tests/test_wifi_manager.py
git commit -m "wifi: tethering and metering without NetworkManager"
```

---

### Task 6: Daemon health check

**Files:**
- Modify: `openpilot/system/ui/lib/wifi_manager.py` (`_monitor` timeout branch, add `_check_daemons`)
- Modify: `openpilot/system/ui/lib/tests/test_wifi_manager.py` (append)

**Interfaces:**
- Consumes: Task 3 `_monitor`, `_start_supplicant`, `_start_dhcp`.
- Produces: `_check_daemons()`.

- [ ] **Step 1: Write the failing tests**

Append to `test_wifi_manager.py`:

```python
class TestHealth(OpenpilotTestCase):
  def test_crashed_supplicant_is_respawned_with_saved_networks(self, manager_env):
    write(os.path.join(manager_env.dirs["persistent"], "Home.nmconnection"), KEYFILE_A)
    wm = start_manager(manager_env)
    first = manager_env.fake
    first.close()
    os.unlink(first.path)
    os.unlink(manager_env.wpa_pid)
    wait_for(lambda: manager_env.fake is not first, timeout=10)
    wait_for(lambda: len(manager_env.fake.networks) == 1 and "ENABLE_NETWORK all" in manager_env.fake.requests, timeout=10)
    self.assertEqual(bytes.fromhex(manager_env.fake.networks[0]["ssid"]).decode(), "Home")
    self.assertEqual([c[0] for c in manager_env.sudo].count("wpa_supplicant"), 2)
    self.assertEqual(wm.wifi_state, wifi_manager.WifiState())

  def test_dead_udhcpc_is_restarted_while_connected(self, manager_env):
    manager_env.spawn_status = dict(STATION_STATUS)
    manager_env.spawn_fake()
    manager_env.alive(manager_env.udhcpc_pid)
    wm = start_manager(manager_env)
    self.assertEqual(manager_env.popen, [])
    os.unlink(manager_env.udhcpc_pid)
    wait_for(lambda: manager_env.popen, timeout=10)
    self.assertEqual(manager_env.popen[0][:2], ["sudo", "udhcpc"])
    self.assertEqual(wm.connected_ssid, "Home")
```

- [ ] **Step 2: Run the tests, expect failures**

Run: `python tools/test_runner.py openpilot/system/ui/lib/tests/test_wifi_manager.py -k TestHealth -v`
Expected: both fail on the `wait_for` timeout (nothing respawns).

- [ ] **Step 3: Implement**

In `_monitor`, change the timeout branch:

```python
      except TimeoutError:
        self._check_daemons()
        continue
```

Add to `WifiManager`:

```python
  def _check_daemons(self):
    # runs once a second between events; a crashed supplicant or DHCP client is brought back without user action
    try:
      alive = self._ctrl is not None and self._ctrl.request("PING") == "PONG"
    except OSError:
      alive = False
    if not alive:
      cloudlog.warning("wpa_supplicant is not responding, restarting")
      try:
        self._start_supplicant()
      except Exception:
        cloudlog.exception("Failed to restart wpa_supplicant")
      return
    if self._wifi_state.status != ConnectStatus.DISCONNECTED and not self.is_tethering_active() and not _pid_alive(UDHCPC_PID_PATH):
      cloudlog.warning("udhcpc is not running, restarting")
      self._start_dhcp()
```

`_start_supplicant` already handles a dead pidfile by re-running the handoff sequence and reloading the saved networks; the `nmcli` call is a no-op when `wlan0` is already unmanaged.

- [ ] **Step 4: Run the tests, expect them to pass**

Run: `python tools/test_runner.py openpilot/system/ui/lib/tests/test_wifi_manager.py -v`
Expected: all pass. The respawn test takes up to three seconds: one recv timeout, one failed `PING` (2 s socket timeout), then the restart.

- [ ] **Step 5: Commit**

```bash
git add openpilot/system/ui/lib/wifi_manager.py openpilot/system/ui/lib/tests/test_wifi_manager.py
git commit -m "wifi: restart crashed wpa_supplicant and udhcpc"
```

---

### Task 7: Supplicant config, udhcpc script, deletions, dependency removal, lint

**Files:**
- Create: `openpilot/system/ui/lib/wpa_supplicant.conf`
- Create: `openpilot/system/ui/lib/udhcpc.script` (mode 755)
- Delete: `openpilot/system/ui/lib/networkmanager.py`
- Modify: `pyproject.toml` (remove `"jeepney",`), `uv.lock` (regenerate)
- Modify: `openpilot/system/ui/lib/tests/test_wifi_manager.py` (append)

- [ ] **Step 1: Write the failing file tests**

Append to `test_wifi_manager.py`:

```python
class TestShippedFiles(OpenpilotTestCase):
  def test_supplicant_conf_has_no_secrets(self):
    with open(wifi_manager.WPA_CONF_PATH) as f:
      lines = [line.strip() for line in f if line.strip()]
    self.assertEqual(lines, ["ctrl_interface=DIR=/run/wpa_supplicant GROUP=netdev", "update_config=0"])

  def test_udhcpc_script_sets_wifi_metric(self):
    self.assertTrue(os.access(wifi_manager.UDHCPC_SCRIPT_PATH, os.X_OK))
    with tempfile.TemporaryDirectory() as d:
      fake_bin = os.path.join(d, "bin")
      os.makedirs(fake_bin)
      log = os.path.join(d, "calls")
      write(os.path.join(fake_bin, "busybox"), f'#!/bin/sh\necho "$@" >> {log}\n')
      os.chmod(os.path.join(fake_bin, "busybox"), 0o755)
      write(os.path.join(d, "default.script"), f'#!/bin/sh\necho "default $1" >> {log}\n')
      os.chmod(os.path.join(d, "default.script"), 0o755)
      env = {"PATH": f"{fake_bin}:/usr/bin:/bin", "UDHCPC_DEFAULT_SCRIPT": os.path.join(d, "default.script"),
             "interface": "wlan0", "router": "10.0.0.1 10.0.0.2", "subnet": "255.255.255.0"}
      subprocess.run([wifi_manager.UDHCPC_SCRIPT_PATH, "bound"], check=True, env=env)
      subprocess.run([wifi_manager.UDHCPC_SCRIPT_PATH, "deconfig"], check=True, env=env)
      with open(log) as f:
        self.assertEqual(f.read().splitlines(), ["default bound", "ip -4 route flush exact 0.0.0.0/0 dev wlan0",
                                                 "ip -4 route add default via 10.0.0.1 dev wlan0 metric 600", "default deconfig"])
      env["subnet"] = "255.255.255.255"
      subprocess.run([wifi_manager.UDHCPC_SCRIPT_PATH, "renew"], check=True, env=env)
      with open(log) as f:
        self.assertEqual(f.read().splitlines()[-1], "ip -4 route add default via 10.0.0.1 dev wlan0 onlink metric 600")
```

- [ ] **Step 2: Run the tests, expect failures**

Run: `python tools/test_runner.py openpilot/system/ui/lib/tests/test_wifi_manager.py -k TestShippedFiles -v`
Expected: `FileNotFoundError` for both files.

- [ ] **Step 3: Create the files**

`openpilot/system/ui/lib/wpa_supplicant.conf`:

```
ctrl_interface=DIR=/run/wpa_supplicant GROUP=netdev
update_config=0
```

`openpilot/system/ui/lib/udhcpc.script`:

```sh
#!/bin/sh
# Wi-Fi must lose to ethernet (metric 100) and beat cellular (metric 1000), matching NetworkManager's default Wi-Fi metric
"${UDHCPC_DEFAULT_SCRIPT:-/etc/udhcpc/default.script}" "$1" || exit $?

case "$1" in
  bound|renew)
    if [ -n "$router" ]; then
      [ ".$subnet" = .255.255.255.255 ] && onlink=onlink || onlink=
      busybox ip -4 route flush exact 0.0.0.0/0 dev "$interface"
      busybox ip -4 route add default via "${router%% *}" dev "$interface" $onlink metric 600
    fi
    ;;
esac
```

Run: `chmod 755 openpilot/system/ui/lib/udhcpc.script && git add openpilot/system/ui/lib/udhcpc.script && git ls-files -s openpilot/system/ui/lib/udhcpc.script`
Expected: mode `100755`.

- [ ] **Step 4: Delete the NetworkManager constants module and the jeepney dependency**

```bash
git rm openpilot/system/ui/lib/networkmanager.py
grep -rn "networkmanager\|jeepney" openpilot --include=*.py   # expected: no output
sed -i '' '/^  "jeepney",$/d' pyproject.toml
uv lock
git diff --stat uv.lock
```

Expected: the `uv.lock` diff removes only the `jeepney` package entry and its reference from the openpilot package block. If anything else changes, revert `uv.lock` and run `uv lock` again from a clean venv; unrelated churn is not acceptable in the PR.

- [ ] **Step 5: Run the whole suite, lint and the UI import smoke test**

```bash
python tools/test_runner.py openpilot/system/ui/lib/tests/test_wifi_manager.py -v
ruff check openpilot/system/ui/lib openpilot/system/ui/widgets openpilot/selfdrive/ui
ty check openpilot/system/ui/lib/wifi_manager.py openpilot/system/ui/lib/tests/test_wifi_manager.py
python -c "import openpilot.system.ui.widgets.network, openpilot.selfdrive.ui.mici.layouts.settings.network.wifi_ui, openpilot.system.ui.tici_setup, openpilot.system.ui.mici_setup, openpilot.system.ui.tici_updater"
scripts/lint/lint.sh
wc -l openpilot/system/ui/lib/wifi_manager.py openpilot/system/ui/lib/tests/test_wifi_manager.py
git diff --shortstat 0cf294d85
```

Expected: tests pass, no ruff or ty findings, imports succeed (the import smoke test needs the raylib wheel from the venv; if it is missing on macOS, run it on the comma three in Task 10 instead and note that here), lint passes. Record the line counts and the shortstat; the target is roughly +1200/-1700.

- [ ] **Step 6: Commit and squash into the PR shape**

```bash
git add openpilot/system/ui/lib/wpa_supplicant.conf pyproject.toml uv.lock
git commit -m "wifi: ship supplicant config and udhcpc route hook, drop jeepney"
git reset --soft 0cf294d85
git restore --staged openpilot/system/ui/lib/tests/test_wifi_manager.py
git commit -m "wifi: replace NetworkManager with wpa_supplicant"
git add openpilot/system/ui/lib/tests/test_wifi_manager.py
git commit -m "wifi: test WifiManager against a fake wpa_supplicant"
git log --oneline 0cf294d85..HEAD
```

Expected: exactly two commits. Re-run the test command once more on the squashed tree.

---

### Task 8: Adapt the validation harness to the v3 layout

**Files (this repository, branch `wifi-v3`):**
- Modify: `wifi_e2e.py`, `test_wifi_e2e.py`, `README.md`

- [ ] **Step 1: Replace the PR #26 paths**

Run `grep -n "openpilot-wpa\|openpilot-wifi\|OPENPILOT_TETHERING\|restore_networkmanager\|dhcp_client\|wpa_supplicant as w" wifi_e2e.py test_wifi_e2e.py` and apply, for every hit:

| Old | New |
| --- | --- |
| `'-p', '/run/openpilot-wpa'` | `'-p', '/run/wpa_supplicant'` |
| `/run/openpilot-wpa/wpa_supplicant.pid` | `/run/wpa_supplicant/wlan0.pid` |
| `/run/openpilot-wifi/udhcpc-wlan0.pid` | `/run/udhcpc.wlan0.pid` |
| `/run/openpilot-wifi/dnsmasq.pid` | `/run/dnsmasq.wlan0.pid` |
| `'OPENPILOT_TETHERING' not in` | `'openpilot-tethering' not in` |
| `Path('/run/openpilot-wpa'), Path('/run/openpilot-wifi')` in the isolation list | `Path('/run/wpa_supplicant')` |

In `test_metering_persists_and_matches_runtime_identity` delete the two lines that read `/run/openpilot-wifi/active_profile`; the `nmcli connection show` assertion that follows is the metering oracle.

- [ ] **Step 2: Rewrite the hand-back in `test_networkmanager_works_before_ui_and_after_explicit_handoff`**

Replace the `run(sys.executable, '-c', ...)` block with:

```python
  # v3 never hands wlan0 back by itself; this is the documented rollback: stop the daemons, let NetworkManager manage wlan0 again
  for pid_file in ('/run/dnsmasq.wlan0.pid', '/run/udhcpc.wlan0.pid', '/run/wpa_supplicant/wlan0.pid'):
    path = Path(pid_file)
    if path.exists():
      os.kill(int(path.read_text()), signal.SIGTERM)
  lab.wait_external(lambda: not Path('/run/wpa_supplicant/wlan0').exists())
  run('nmcli', 'device', 'set', 'wlan0', 'managed', 'yes', ns=lab.names['dut'])
```

- [ ] **Step 3: Update the README**

Replace the sentence "External qualification for `andiradulescu/openpilot` PR #26." with "External qualification for the `wifi-wpa-supplicant` branch of `andiradulescu/openpilot`." and add under Acceptance boundaries: "v3 hands `wlan0` to `wpa_supplicant` once per boot and never hands it back; the hand-back test performs the rollback procedure itself."

- [ ] **Step 4: Collect only**

Run: `python -m pytest --collect-only -q test_wifi_e2e.py`
Expected: 51 cases collected, no import errors. (Execution needs the VM from Task 9.)

- [ ] **Step 5: Commit**

```bash
git add wifi_e2e.py test_wifi_e2e.py README.md
git commit -m "Adapt harness paths to the v3 wpa_supplicant layout"
```

---

### Task 9: hwsim virtual-radio run in a disposable QEMU VM

**Files (this repository):**
- Create: `vm/README.md`, `vm/user-data`, `vm/meta-data`, `vm/run-vm.sh`
- Results land in `results/<run>/` as the runner writes them.

OrbStack's kernel has no `mac80211_hwsim`; QEMU with HVF is installed (`/opt/homebrew/bin/qemu-system-aarch64`).

- [ ] **Step 1: Write the VM files**

`vm/meta-data`:

```
instance-id: wifi-e2e
local-hostname: wifi-e2e
```

`vm/user-data` (replace the key with `cat ~/.ssh/id_ed25519.pub`):

```yaml
#cloud-config
users:
  - name: ubuntu
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    groups: [netdev]
    ssh_authorized_keys:
      - ssh-ed25519 AAAA... andi
package_update: true
packages: [iproute2, iw, kmod, util-linux, hostapd, wpasupplicant, udhcpc, dnsmasq-base, network-manager, netplan.io, dbus, iptables, curl, git, git-lfs, python3-venv, build-essential, pkg-config, libzmq3-dev, ocl-icd-opencl-dev, libssl-dev, clang]
runcmd:
  - apt-get install -y linux-modules-extra-$(uname -r)
  - modprobe mac80211_hwsim radios=0 && rmmod mac80211_hwsim
  - curl -LsSf https://astral.sh/uv/install.sh | sudo -u ubuntu sh
  - systemctl unmask hostapd
```

`vm/run-vm.sh`:

```sh
#!/bin/sh
# Disposable Ubuntu 24.04 arm64 VM for the hwsim suite. First run downloads the cloud image; state lives in ~/vms/wifi-e2e.
set -eu
dir="$HOME/vms/wifi-e2e"
mkdir -p "$dir"
cd "$dir"
[ -f noble.img ] || { curl -Lo noble.img https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-arm64.img; qemu-img resize noble.img 40G; }
[ -f code.fd ] || cp "$(brew --prefix qemu)/share/qemu/edk2-aarch64-code.fd" code.fd
[ -f vars.fd ] || truncate -s 64m vars.fd
here="$(cd "$(dirname "$0")" && pwd)"
rm -rf seed && mkdir seed && cp "$here/user-data" "$here/meta-data" seed/
hdiutil makehybrid -quiet -o seed.iso -hfs -joliet -iso -default-volume-name cidata seed/
exec qemu-system-aarch64 -M virt -accel hvf -cpu host -smp 4 -m 6144 \
  -drive if=pflash,format=raw,file=code.fd,readonly=on -drive if=pflash,format=raw,file=vars.fd \
  -drive file=noble.img,if=virtio,format=qcow2 -drive file=seed.iso,if=virtio,format=raw,readonly=on \
  -netdev user,id=n0,hostfwd=tcp::2222-:22 -device virtio-net-pci,netdev=n0 -nographic
```

`vm/README.md`: three lines saying run `vm/run-vm.sh` in a spare terminal, connect with `ssh -p 2222 ubuntu@localhost`, and that the VM is throwaway (`rm -rf ~/vms/wifi-e2e` resets it).

- [ ] **Step 2: Boot and verify the prerequisites**

Run `sh vm/run-vm.sh` in a background terminal, wait for the login prompt, then:

```bash
ssh -p 2222 ubuntu@localhost 'cloud-init status --wait; uname -r; modinfo mac80211_hwsim | head -2; which hostapd wpa_supplicant udhcpc dnsmasq nmcli iptables iptables-legacy-save; ls -l /etc/udhcpc/default.script; getent group netdev'
```

Expected: `status: done`, a `-generic` kernel, `mac80211_hwsim` found, all binaries present, the default script executable, group `netdev` present. If the kernel is `-kvm` (no extra modules), run `sudo apt-get install -y linux-generic && sudo reboot` and re-check.

- [ ] **Step 3: Install openpilot and the harness in the VM**

```bash
ssh -p 2222 ubuntu@localhost 'sudo mkdir -p /workspace && sudo chown ubuntu /workspace && cd /workspace \
  && git clone -b wifi-wpa-supplicant https://github.com/andiradulescu/openpilot.git && cd openpilot && git submodule update --init --depth 1 opendbc_repo msgq_repo \
  && ~/.local/bin/uv sync --frozen && .venv/bin/python -c "import openpilot.system.ui.lib.wifi_manager as w; print(w.WPA_CTRL_PATH)" \
  && git clone -b wifi-v3 https://github.com/andiradulescu/openpilot-wifi-validation.git /workspace/openpilot-wifi-validation \
  && ~/.local/bin/uv pip install --python /workspace/openpilot/.venv/bin/python -r /workspace/openpilot-wifi-validation/requirements.txt'
```

Push both branches to GitHub first (`git push -u dorapilot wifi-wpa-supplicant` is wrong; the fork remote for openpilot is `andiradulescu`, add it if missing: `git remote add andiradulescu git@github.com:andiradulescu/openpilot.git`). Pushing a branch to your own fork is not the PR; that step stays gated in Task 11.

Expected: the import prints `/run/wpa_supplicant/wlan0`. If `uv sync` fails on a native dependency, install the named `-dev` package and retry; do not edit `pyproject.toml`.

- [ ] **Step 4: Run the unit suite through the runner**

```bash
ssh -p 2222 ubuntu@localhost 'cd /workspace/openpilot-wifi-validation && SHA=$(git -C /workspace/openpilot rev-parse HEAD) && python3 run.py --checkout /workspace/openpilot --sha $SHA --suite unit'
```

Expected: `passed` in `results/<run>/manifest.json`.

- [ ] **Step 5: Run the hwsim matrix**

```bash
ssh -p 2222 ubuntu@localhost 'cd /workspace/openpilot-wifi-validation && SHA=$(git -C /workspace/openpilot rev-parse HEAD) && sudo env PATH="$PATH" WIFI_E2E_VM=1 python3 run.py --checkout /workspace/openpilot --sha $SHA --suite hwsim'
```

Expected: 51 cases, none `blocked`. Every failure is a defect in either v3 or the harness. For each: reproduce, decide which side is wrong against the spec, put the smallest regression next to the fix (openpilot test file for v3 defects, harness for harness defects), re-run the failing case with `--filter <name>`, then the whole matrix. Copy `results/<run>/manifest.json` and the JUnit file back with `scp -P 2222 -r ubuntu@localhost:/workspace/openpilot-wifi-validation/results results/` and commit them.

- [ ] **Step 6: Commit**

```bash
git add vm results
git commit -m "Add hwsim VM setup and v3 virtual-radio results"
```

---

### Task 10: Device validation on comma hardware

**Devices:** comma three at `ssh comma@192.168.1.199` (eth0; the same device is `192.168.1.105` on wlan0, never use the wlan0 address during Wi-Fi tests). It runs AGNOS 19.6 with PR #26 code installed. A comma four is required for LTE/ppp0 priority and tethering over cellular; Andi names the host before this task starts.

Device notes from `/Volumes/Stuff/CLAUDE.md`: activate `/usr/local/venv/bin/activate`, `cd /data/openpilot`, `export PYTHONPATH=/data/openpilot`; rebootless restart is `tmux kill-session -t comma; rm -f /tmp/safe_staging_overlay.lock; tmux new -s comma -d "/data/openpilot/launch_openpilot.sh"`.

- [ ] **Step 1: Install v3 and reboot to clear PR #26 state**

```bash
ssh comma@192.168.1.199 'cd /data/openpilot && git fetch https://github.com/andiradulescu/openpilot.git wifi-wpa-supplicant && git checkout FETCH_HEAD && git log --oneline -1 && sudo reboot'
```

Wait for the device, then confirm the clean state before the UI has touched Wi-Fi is NetworkManager's: `nmcli -g GENERAL.STATE dev show wlan0` shows `100 (connected)` or `30 (disconnected)`, and `ls /run/wpa_supplicant` shows only NetworkManager's socket.

- [ ] **Step 2: Verify the handoff after the UI starts**

```bash
ssh comma@192.168.1.199 'sleep 60; nmcli -g GENERAL.STATE dev show wlan0; cat /run/wpa_supplicant/wlan0.pid; ps -o pid,args -p $(cat /run/wpa_supplicant/wlan0.pid) $(cat /run/udhcpc.wlan0.pid); ip -4 route; wpa_cli -i wlan0 status | grep -E "wpa_state|ssid|ip_address"; resolvectl status wlan0 | grep "DNS Servers"'
```

Expected: `10 (unmanaged)`, our supplicant with `-c .../wpa_supplicant.conf`, udhcpc with the repo script, wlan0 default route at metric 600 below eth0 at 100, `COMPLETED` on the saved network, DNS servers set.

- [ ] **Step 3: UI flows on the touchscreen (Andi drives, agent verifies over SSH)**

For each, check `journalctl`-free evidence via `wpa_cli -i wlan0 status`, `ip -4 addr show wlan0`, `sudo ls -la /data/etc/NetworkManager/system-connections /data/etc/netplan` before and after:

1. Forget a network saved by the old openpilot (netplan origin): YAML and runtime keyfile gone, list shows it unsaved.
2. Connect to it again with the password: new keyfile in the persistent dir, IP obtained, `deviceState.networkType` is wifi (`cd /data/openpilot && .venv/bin/python -c "..."` is not available on device; use `python -c "from openpilot.common.hardware import HARDWARE; print(HARDWARE.get_network_type(), HARDWARE.get_network_metered(HARDWARE.get_network_type()))"` inside the openpilot venv).
3. Wrong password: dialog appears once, nothing saved.
4. Metered toggle: `metered=` changes in the keyfile, hardware.py reports it.
5. Hotspot on: phone joins `weedle-xxxx`, gets a 192.168.43.x lease, browses (with prime forwarding on) or does not (off). `sudo iptables-legacy -t nat -S POSTROUTING` shows the tagged rule. Hotspot off: rule gone, station reconnects.
6. Hotspot password change while on: phone must re-join with the new password.

- [ ] **Step 4: UI death and restart**

```bash
ssh comma@192.168.1.199 'tmux kill-session -t comma; for i in $(seq 40); do ping -c1 -W1 -I wlan0 1.1.1.1 >/dev/null && echo ok || echo LOST; sleep 0.5; done | sort | uniq -c; rm -f /tmp/safe_staging_overlay.lock; tmux new -s comma -d "/data/openpilot/launch_openpilot.sh"; sleep 45; cat /run/wpa_supplicant/wlan0.pid /run/udhcpc.wlan0.pid'
```

Expected: 40 `ok`, zero `LOST`, same pids as in Step 2. Repeat once with the hotspot active and a phone attached.

- [ ] **Step 5: Reboot autoconnect and crash recovery**

Reboot; after the UI starts the device must be on the saved network without input. Then `sudo kill -9 $(cat /run/wpa_supplicant/wlan0.pid)` and confirm a new pid and reconnection within 35 s; same for udhcpc.

- [ ] **Step 6: Rollback**

```bash
ssh comma@192.168.1.199 'cd /data/openpilot && git checkout 0cf294d85 && sudo reboot'
```

After reboot NetworkManager connects to the network saved by v3 (it reads the persistent keyfile) and the hotspot toggle works in the old UI. Then reinstall v3 (`git checkout FETCH_HEAD` again) for the benchmark.

- [ ] **Step 7: Connect-time benchmark (bonus target)**

Create `tools/bench_connect.py` in this repository (uncommitted, per Andi's rule for temporary scripts) that, inside the device venv, creates `WifiManager()`, waits for ready, then five times: `forget_connection(ssid, block=True)`, `connect_to_network(ssid, password)`, and measures until `connected_ssid == ssid` with a non-empty `ipv4_address`. Run it on v3 and on `0cf294d85` (on master the same script works because the public surface is identical). Record mean and spread for both in `results/bench-<date>.md` and commit that file.

- [ ] **Step 8: comma four**

Repeat Steps 1 to 5 on the comma four, plus: with a SIM active, `ip -4 route` shows ppp0 at 1000 below wlan0 at 600; pull Wi-Fi (walk away or power the AP off) and confirm traffic moves to ppp0 and back; hotspot with the uplink on ppp0 works with the tagged NAT rule.

---

### Task 11: PR submission

Outward-facing steps. STOP and get Andi's explicit go-ahead before each `git push` to the fork, the `gh pr create`, and the comment on #38330.

- [ ] **Step 1: Rebase onto current comma/master and re-verify**

```bash
git fetch comma master && git rebase comma/master && python tools/test_runner.py openpilot/system/ui/lib/tests/test_wifi_manager.py && scripts/lint/lint.sh
```

- [ ] **Step 2: Push the branch**

```bash
git push -u andiradulescu wifi-wpa-supplicant
```

- [ ] **Step 3: Open the upstream PR**

Title: `wifi: replace NetworkManager with wpa_supplicant`. Body, filled with the real numbers from Tasks 7, 9 and 10:

```
Resolves #37752

WifiManager now drives wpa_supplicant over its control socket, udhcpc for DHCP and dnsmasq for the hotspot. No D-Bus, jeepney or NetworkManager in the Wi-Fi path; NetworkManager releases wlan0 once per boot via nmcli and keeps managing eth0. Saved networks stay `.nmconnection` keyfiles (netplan-origin profiles are read and removed on forget), so rolling back to master keeps every saved network.

- same public WifiManager surface, no UI changes
- daemons survive a UI restart or crash and are adopted on start
- Wi-Fi default route at metric 600 (eth0 100, ppp0 1000)
- hotspot: wpa_supplicant AP mode + dnsmasq + source-subnet MASQUERADE via iptables-legacy

Verification
- `tools/test_runner.py openpilot/system/ui/lib/tests/test_wifi_manager.py`: N passed
- hwsim matrix (51 cases) in a QEMU VM: <link to results manifest in andiradulescu/openpilot-wifi-validation>
- comma 3X and comma four: connect/forget/wrong password/metered/hotspot/password change, UI kill with 40 probes and zero loss, reboot autoconnect, supplicant and udhcpc kill recovery, rollback to master
- connect to IP, 5 runs on a WPA2 network: v3 X.XX s ± Y, master (NetworkManager) X.XX s ± Y

Rollback: check out master and reboot; NetworkManager reads the same keyfiles.
```

```bash
gh pr create -R commaai/openpilot --head andiradulescu:wifi-wpa-supplicant --title "wifi: replace NetworkManager with wpa_supplicant" --body-file /tmp/pr-body.md
```

- [ ] **Step 4: Close #38330 with a pointer**

```bash
gh pr comment 38330 -R commaai/openpilot --body "Superseded by #<new>, a from-scratch minimal implementation validated with the external hwsim harness and on both devices."
gh pr close 38330 -R commaai/openpilot
```

- [ ] **Step 5: Record**

Update the memory file `openpilot-wifi-v3-no-networkmanager.md` with the PR number, the validated SHAs and anything the device runs taught us.

---

## Self-review against the spec

- Public contract: Task 3 (reads, callbacks, `set_active`, `stop`), Task 4 (connect/activate/forget), Task 5 (tethering, metering, `set_ipv4_forward`, `tethering_password`). All names match upstream.
- Process ownership: adopt vs spawn, handoff wait, static conf, detached daemons, `stop()` leaves daemons (Task 3); udhcpc renew on associate (Task 4); health check (Task 6).
- Storage: read both dirs, byte-list SSIDs, write shape, forget with YAML, edit-as-rewrite (Task 2); save on first address (Task 4); hotspot creation lazily and on init (Task 5).
- Station flow, WRONG_KEY, DHCP timeout, disconnected, scan mapping and sort: Tasks 3 and 4.
- Tethering and live `ip_forward`: Task 5.
- Shipped files, deletions, jeepney: Task 7.
- External validation, VM, devices, rollback, benchmark, PR: Tasks 8 to 11.
- Known gap left open on purpose: `test_forget_removes_every_persistent_source[shadow]` in the harness seeds a persistent copy of a netplan profile; Task 2's `write_profile` and Task 4's forget remove every profile with that SSID, so it should pass, but confirm in Task 9 rather than assume.
