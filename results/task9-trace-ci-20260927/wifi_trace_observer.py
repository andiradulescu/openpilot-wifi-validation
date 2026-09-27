import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

out = Path(tempfile.mkdtemp(prefix="wifi-trace-"))
events = (out / "observer.jsonl").open("w")
handles = []
observers = {}

def record(kind, **values):
  events.write(json.dumps({"time": time.time(), "kind": kind, **values}) + "\n")
  events.flush()

def launch(name, args, binary=False):
  stdout = (out / (name + (".pcap" if binary else ".log"))).open("wb")
  stderr = (out / (name + ".stderr")).open("wb")
  handles.extend((stdout, stderr))
  proc = subprocess.Popen(args, stdout=stdout, stderr=stderr, start_new_session=True)
  observers[name] = proc
  record("observer-start", name=name, pid=proc.pid, argv=args)
  return proc

env = dict(os.environ, WIFI_E2E_VM="1")
sha = subprocess.check_output(["git", "-C", "/workspace/openpilot", "rev-parse", "HEAD"], text=True).strip()
limit_scan = len(sys.argv) > 1 and sys.argv[1] == "limited"
scan_limited = False
argv = ["python3", "run.py", "--checkout", "/workspace/openpilot", "--sha", sha,
        "--suite", "hwsim", "--filter", "password123-False and not SSSS"]
runner_log = (out / "runner.log").open("wb")
runner = subprocess.Popen(argv, cwd="/workspace/openpilot-wifi-validation", env=env,
                          stdout=runner_log, stderr=subprocess.STDOUT, start_new_session=True)
record("runner-start", pid=runner.pid, argv=argv, output=str(out))
pytest_pid = None
dhcp_pid = None
last_sample = 0.0
started = time.monotonic()
try:
  while runner.poll() is None:
    if time.monotonic() - started > 110:
      record("runner-timeout")
      os.killpg(runner.pid, signal.SIGINT)
      break
    for entry in Path("/proc").iterdir():
      if not entry.name.isdigit():
        continue
      try:
        command = (entry / "cmdline").read_bytes().split(b"\0")[:-1]
        comm = (entry / "comm").read_text().strip()
      except (FileNotFoundError, ProcessLookupError, PermissionError):
        continue
      if pytest_pid is None and b"pytest" in command and any(x.endswith(b"/test_wifi_e2e.py") for x in command):
        pytest_pid = int(entry.name)
        record("pytest-found", pid=pytest_pid, argv=[x.decode(errors="replace") for x in command])
      if dhcp_pid is None and comm == "udhcpc" and b"/run/udhcpc.wlan0.pid" in command:
        dhcp_pid = int(entry.name)
        status = (entry / "status").read_text()
        record("dhcp-found", pid=dhcp_pid, comm=comm,
               nspid=[x for x in status.splitlines() if x.startswith("NSpid:")],
               argv=[x.decode(errors="replace") for x in command])
        launch("strace", ["strace", "-ff", "-ttt", "-s", "256", "-o", str(out / "dhcp.strace"),
                          "-e", "trace=%signal,%process,read,write,sendto,recvfrom", "-p", str(dhcp_pid)])
    if pytest_pid is not None:
      enter = ["nsenter", "-t", str(pytest_pid), "-m", "--"]
      listing = subprocess.run(enter + ["ip", "netns", "list"], capture_output=True, text=True, timeout=2)
      names = {line.split()[0] for line in listing.stdout.splitlines() if line}
      for role in ("dut", "wan"):
        name = "wifi-e2e-" + role
        if name in names and role not in observers:
          launch(role, enter + ["ip", "netns", "exec", name, "tcpdump", "-U", "--immediate-mode", "-nn", "-i", "any",
                               "-w", "-", "arp or udp port 53 or udp port 67 or udp port 68"], binary=True)
      if "wifi-e2e-dut" in names and "ip-monitor" not in observers:
        launch("ip-monitor", enter + ["ip", "netns", "exec", "wifi-e2e-dut", "ip", "-ts", "monitor", "address", "route"])
        launch("iw-events", enter + ["ip", "netns", "exec", "wifi-e2e-dut", "iw", "event", "-t"])
      if "wifi-e2e-dut" in names and time.monotonic() - last_sample >= 0.15:
        sample = subprocess.run(enter + ["ip", "netns", "exec", "wifi-e2e-dut", "sh", "-c",
            "wpa_cli -p /run/wpa_supplicant -i wlan0 status; cat /etc/resolv.conf; ip -4 route; cat /run/udhcpc.wlan0.pid"],
            capture_output=True, text=True, timeout=2)
        record("dut-sample", returncode=sample.returncode, stdout=sample.stdout, stderr=sample.stderr)
        if limit_scan and not scan_limited and "wpa_state=" in sample.stdout:
          setting = subprocess.run(enter + ["ip", "netns", "exec", "wifi-e2e-dut", "wpa_cli", "-p",
              "/run/wpa_supplicant", "-i", "wlan0", "set", "freq_list", "2412"], capture_output=True, text=True, timeout=2)
          record("scan-limit", returncode=setting.returncode, stdout=setting.stdout, stderr=setting.stderr)
          if setting.returncode != 0 or setting.stdout.strip() != "OK":
            raise RuntimeError("Diagnostic frequency setting failed")
          scan_limited = True
        last_sample = time.monotonic()
    for name, proc in list(observers.items()):
      if proc.poll() is not None:
        record("observer-exit", name=name, returncode=proc.returncode)
        # Keep the entry so an unexpected failure is visible instead of silently retried.
    time.sleep(0.04)
  runner.wait(timeout=15)
finally:
  if runner.poll() is None:
    os.killpg(runner.pid, signal.SIGINT)
    runner.wait(timeout=15)
  for name, proc in observers.items():
    if proc.poll() is None:
      os.killpg(proc.pid, signal.SIGINT)
    try:
      proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
      os.killpg(proc.pid, signal.SIGTERM)
      proc.wait(timeout=3)
    record("observer-final", name=name, returncode=proc.returncode)
  runner_log.close()
  for handle in handles:
    handle.close()
  record("runner-final", returncode=runner.returncode)
  events.close()
print(json.dumps({"trace_dir": str(out), "returncode": runner.returncode,
                  "observers": list(observers), "dhcp_pid": dhcp_pid}))
print((out / "runner.log").read_text()[-4500:])
