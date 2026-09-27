import datetime
import json
import os
import pathlib
import subprocess
import time

base = pathlib.Path('/tmp/wifi-failover-20260927-1328')
assert pathlib.Path('/data/params/d/IsOffroad').read_text() == '1'
assert not base.with_suffix('.pid').exists(), 'Recorder already exists'

def run(args):
  try:
    p = subprocess.run(args, capture_output=True, text=True, timeout=4)
    return {'rc': p.returncode, 'stdout': p.stdout.strip(), 'stderr': p.stderr.strip()}
  except subprocess.TimeoutExpired:
    return {'timeout': True}

pid = os.fork()
if pid:
  print('recorder_launcher_pid=', pid, 'log=', str(base.with_suffix('.jsonl')), flush=True)
  raise SystemExit(0)
os.setsid()
if os.fork():
  os._exit(0)
os.chdir('/tmp')
os.umask(0o077)
fd = os.open('/dev/null', os.O_RDWR)
for target in (0, 1, 2):
  os.dup2(fd, target)
if fd > 2:
  os.close(fd)
base.with_suffix('.pid').write_text(str(os.getpid()))
start = time.monotonic()
with base.with_suffix('.jsonl').open('x', buffering=1) as log:
  while time.monotonic() - start < 1800 and not base.with_suffix('.stop').exists():
    row = {'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'elapsed': round(time.monotonic()-start, 3)}
    row['route_before'] = run(['ip', '-4', 'route', 'get', '1.1.1.1'])
    row['defaults'] = run(['ip', '-4', 'route', 'show', 'default'])
    row['ping'] = run(['ping', '-n', '-c', '1', '-W', '1', '1.1.1.1'])
    row['route_after'] = run(['ip', '-4', 'route', 'get', '1.1.1.1'])
    row['wifi'] = run(['sudo', '-n', 'wpa_cli', '-i', 'wlan0', 'status'])
    row['eth_carrier'] = pathlib.Path('/sys/class/net/eth0/carrier').read_text().strip() if pathlib.Path('/sys/class/net/eth0/carrier').exists() else 'absent'
    log.write(json.dumps(row) + '\n')
    time.sleep(2)
  log.write(json.dumps({'event': 'stopped', 'elapsed': round(time.monotonic()-start,3)}) + '\n')
