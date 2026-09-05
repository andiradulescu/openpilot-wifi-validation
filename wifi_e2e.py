import configparser
import hashlib
import json
import os
import re
import select
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


PROFILE_DIR = Path('/data/etc/NetworkManager/system-connections')
RUNTIME_PROFILE_DIR = Path('/run/NetworkManager/system-connections')
SERVER = '198.18.0.1'
CELLULAR_DNS = '198.18.0.2'
PROBE = 'openpilot-wifi-e2e\n'
UI_MUTATIONS = {
  'set_active', 'connect_to_network', 'activate_connection', 'forget_connection',
  'set_current_network_metered', 'set_tethering_active', 'set_tethering_password', 'set_ipv4_forward',
}


def run(*args, ns=None, check=True):
  command = ['ip', 'netns', 'exec', ns, *args] if ns else list(args)
  return subprocess.run(command, check=check, capture_output=True, text=True, timeout=30)


def keyfile_profiles():
  profiles = {}
  for directory in (PROFILE_DIR, RUNTIME_PROFILE_DIR):
    for path in directory.glob('*.nmconnection'):
      cp = configparser.ConfigParser(interpolation=None)
      cp.read(path)
      wifi = next((name for name in ('wifi', '802-11-wireless') if cp.has_section(name)), None)
      if wifi is None or cp.get(wifi, 'mode', fallback='infrastructure') != 'infrastructure':
        continue
      value = cp.get(wifi, 'ssid')
      ssid = bytes(map(int, value.rstrip(';').split(';'))).decode() if re.fullmatch(r'(\d+;)+', value) else value
      profiles[str(path)] = (cp.get('connection', 'uuid'), ssid, cp)
  return profiles


def worker(path):
  from dataclasses import asdict
  from openpilot.system.ui.lib.wifi_manager import WifiManager

  events = []
  manager = WifiManager()
  manager.add_callbacks(
    need_auth=lambda ssid: events.append(['need_auth', ssid]),
    activated=lambda: events.append(['activated']),
    forgotten=lambda ssid: events.append(['forgotten', ssid]),
    disconnected=lambda: events.append(['disconnected']),
    networks_updated=lambda _: events.append(['networks_updated']),
  )
  import inspect
  if 'forget_failed' in inspect.signature(manager.add_callbacks).parameters:
    manager.add_callbacks(forget_failed=lambda ssid: events.append(['forget_failed', ssid]))
  with socket.socket(socket.AF_UNIX) as server:
    server.bind(path)
    os.chmod(path, 0o600)
    server.listen(1)
    conn, _ = server.accept()
    with conn, conn.makefile('rwb') as stream:
      while True:
        manager.process_callbacks()
        if not select.select([conn], [], [], 0.02)[0]:
          continue
        line = stream.readline()
        if not line:
          break
        request = json.loads(line)
        method = request['method']
        if method in UI_MUTATIONS:
          getattr(manager, method)(*request.get('args', []), **request.get('kwargs', {}))
        elif method == 'stop':
          manager.stop()
        elif method != 'snapshot':
          raise ValueError(method)
        manager.process_callbacks()
        response = {
          'connected': manager.connected_ssid,
          'connecting': manager.connecting_to_ssid,
          'status': int(manager.wifi_state.status),
          'ip': manager.ipv4_address,
          'metered': int(manager.current_network_metered),
          'tethering': manager.is_tethering_active(),
          'password': manager.tethering_password,
          'networks': [asdict(network) for network in manager.networks],
          'saved': {ssid: manager.is_connection_saved(ssid) for ssid in request.get('ssids', [])},
          'events': events,
        }
        stream.write(json.dumps(response).encode() + b'\n')
        stream.flush()
        events.clear()
        if method == 'stop':
          break
    manager.stop()


class WifiLab:
  def __init__(self):
    if os.geteuid() != 0 or not Path('/run/wifi-e2e-isolated').exists():
      raise RuntimeError('Use run_wifi_e2e.sh in a disposable VM')
    log_dir = os.environ.get('WIFI_E2E_LOG_DIR')
    if log_dir:
      Path(log_dir).mkdir(parents=True, exist_ok=True)
    self.directory = Path(tempfile.mkdtemp(prefix='wifi-e2e-', dir=log_dir))
    self.directory.chmod(0o755)
    self.names = {role: f'wifi-e2e-{role}' for role in ('dut', 'ap0', 'ap1', 'client', 'wan')}
    self.radios = {}
    self.namespaces = []
    self.processes = []
    self.access_points = {}
    self.ssids = set()
    self.events = []
    self.snapshot = {}
    self.manager = None
    self.conn = None
    self.stream = None

  def spawn(self, role, *command):
    log = (self.directory / f'{len(self.processes)}-{role}.log').open('w')
    try:
      proc = subprocess.Popen(['ip', 'netns', 'exec', self.names[role], *command], stdout=log, stderr=log, start_new_session=True)
    finally:
      log.close()
    self.processes.append(proc)
    return proc

  def setup(self):
    for path in (PROFILE_DIR, RUNTIME_PROFILE_DIR, Path('/run/openpilot-wpa'), Path('/run/openpilot-wifi'),
                 Path('/etc/netplan'), Path('/var/lib/NetworkManager')):
      path.mkdir(parents=True, exist_ok=True)
      for child in path.iterdir():
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    for path in (Path('/run/dbus/system_bus_socket'), Path('/run/dbus/pid')):
      path.unlink(missing_ok=True)
    radios = []
    for number, block in re.findall(r'phy#(\d+)\n(.*?)(?=\nphy#|\Z)', run('iw', 'dev').stdout, re.S):
      interfaces = re.findall(r'^\s+Interface (\S+)$', block, re.M)
      if interfaces:
        radios.append((number, interfaces[0]))
    if len(radios) != 4:
      raise RuntimeError(f'Expected four hwsim radios, got {radios}')
    for role, name in self.names.items():
      run('ip', 'netns', 'add', name)
      self.namespaces.append(name)
      run('ip', '-n', name, 'link', 'set', 'lo', 'up')
      resolver = Path('/etc/netns') / name / 'resolv.conf'
      resolver.parent.mkdir(parents=True, exist_ok=True)
      resolver.write_text('' if role == 'client' else f'nameserver {CELLULAR_DNS}\n')
    for role, (number, interface) in zip(('dut', 'ap0', 'ap1', 'client'), radios, strict=True):
      phy = f'phy{number}'
      run('iw', 'phy', phy, 'set', 'netns', 'name', self.names[role])
      self.radios[role] = phy
      run('ip', 'link', 'set', interface, 'down', ns=self.names[role])
      if interface != 'wlan0':
        run('ip', 'link', 'set', interface, 'name', 'wlan0', ns=self.names[role])
    for index, role in enumerate(('dut', 'ap0', 'ap1'), 1):
      local, remote = f'e2e{index}', f'wan{index}'
      run('ip', 'link', 'add', local, 'type', 'veth', 'peer', 'name', remote)
      run('ip', 'link', 'set', local, 'netns', self.names[role])
      run('ip', 'link', 'set', remote, 'netns', self.names['wan'])
      interface = 'wwan0' if role == 'dut' else 'uplink'
      run('ip', 'link', 'set', local, 'name', interface, ns=self.names[role])
      run('ip', 'addr', 'add', f'10.200.{index}.2/24', 'dev', interface, ns=self.names[role])
      run('ip', 'link', 'set', interface, 'up', ns=self.names[role])
      run('ip', 'addr', 'add', f'10.200.{index}.1/24', 'dev', remote, ns=self.names['wan'])
      run('ip', 'link', 'set', remote, 'up', ns=self.names['wan'])
      run('ip', 'route', 'add', 'default', 'via', f'10.200.{index}.1', 'dev', interface, 'metric', '700', ns=self.names[role])
      if role != 'dut':
        subnet = 10 if role == 'ap0' else 20
        run('ip', 'addr', 'add', f'10.{subnet}.0.1/24', 'dev', 'wlan0', ns=self.names[role])
        run('sysctl', '-w', 'net.ipv4.ip_forward=1', ns=self.names[role])
        run('ip', 'route', 'add', f'10.{subnet}.0.0/24', 'via', f'10.200.{index}.2', ns=self.names['wan'])
    for address in (SERVER, CELLULAR_DNS):
      run('ip', 'addr', 'add', f'{address}/32', 'dev', 'lo', ns=self.names['wan'])
    run('sysctl', '-w', 'net.ipv4.ip_forward=1', ns=self.names['wan'])
    (self.directory / 'probe').write_text(PROBE)
    self.spawn('wan', sys.executable, '-m', 'http.server', '8000', '--bind', SERVER, '--directory', str(self.directory))
    self.spawn('wan', 'dnsmasq', '--conf-file=/dev/null', '--keep-in-foreground', '--no-resolv', '--bind-interfaces',
               f'--listen-address={SERVER},{CELLULAR_DNS}', f'--address=/wifi.test/{SERVER}')
    self.spawn('dut', 'dbus-daemon', '--system', '--nofork', '--nopidfile')
    self.wait_external(lambda: Path('/run/dbus/system_bus_socket').exists())
    config = self.directory / 'NetworkManager.conf'
    config.write_text('[main]\nplugins=keyfile\ndhcp=internal\ndns=default\nrc-manager=file\nauth-polkit=false\n'
                      + 'no-auto-default=*\n[device-lte]\nmatch-device=interface-name:wwan0\nmanaged=0\n'
                      + f'[global-dns-domain-*]\nservers={CELLULAR_DNS}\n')
    empty = self.directory / 'empty'
    empty.mkdir()
    self.spawn('dut', 'NetworkManager', '--no-daemon', f'--config={config}', f'--config-dir={empty}', f'--system-config-dir={empty}')
    self.wait_external(lambda: run('nmcli', '-t', '-f', 'RUNNING', 'general', ns=self.names['dut'], check=False).stdout.strip() == 'running')
    self.wait_external(lambda: run('curl', '--noproxy', '*', '--silent', '--max-time', '1',
                                  f'http://{SERVER}:8000/probe', ns=self.names['wan'], check=False).stdout == PROBE)

  def ap(self, ssid='Test A', password='password123', index=0, hidden=False, dhcp=True):
    self.ssids.add(ssid)
    role = f'ap{index}'
    for proc in self.access_points.get(index, ()):
      if proc.poll() is None:
        proc.terminate()
        proc.wait(timeout=5)
    config = self.directory / f'hostapd-{index}.conf'
    lines = ['interface=wlan0', 'driver=nl80211', 'hw_mode=g', 'channel=1',
             f'ctrl_interface={self.directory}/ap{index}-ctrl', f'ssid2={ssid.encode().hex()}', f'ignore_broadcast_ssid={int(hidden)}']
    if password:
      psk = password if re.fullmatch(r'[0-9a-fA-F]{64}', password) else hashlib.pbkdf2_hmac('sha1', password.encode(), ssid.encode(), 4096).hex()
      lines += ['wpa=2', 'wpa_key_mgmt=WPA-PSK', 'rsn_pairwise=CCMP', f'wpa_psk={psk}']
    config.write_text('\n'.join(lines) + '\n')
    config.chmod(0o600)
    processes = [self.spawn(role, 'hostapd', str(config))]
    if dhcp:
      subnet = 10 if index == 0 else 20
      processes.append(self.spawn(role, 'dnsmasq', '--conf-file=/dev/null', '--keep-in-foreground', '--port=0', '--bind-interfaces',
                                  '--interface=wlan0', '--leasefile-ro', f'--dhcp-range=10.{subnet}.0.10,10.{subnet}.0.100,255.255.255.0,2m',
                                  f'--dhcp-option=3,10.{subnet}.0.1', f'--dhcp-option=6,{SERVER}'))
    self.access_points[index] = processes
    self.wait_external(lambda: (self.directory / f'ap{index}-ctrl/wlan0').exists() and processes[0].poll() is None)

  def seed(self, ssid='Test A', password='password123', source='keyfile', priority=100):
    self.ssids.add(ssid)
    identifier = str(uuid.uuid4())
    if source == 'netplan':
      document = {'network': {'version': 2, 'renderer': 'NetworkManager', 'wifis': {'wlan0': {
        'dhcp4': True, 'access-points': {ssid: {'password': password, 'networkmanager': {
          'uuid': identifier, 'name': f'openpilot connection {ssid}', 'passthrough': {
            'connection.autoconnect-retries': '0', 'connection.autoconnect-priority': str(priority),
            'ipv4.dns-priority': '600', 'ipv6.method': 'ignore',
          },
        }}},
      }}}}
      # JSON is valid YAML and avoids quoting test credentials by hand.
      path = Path('/etc/netplan') / f'90-NM-{identifier}.yaml'
      path.write_text(json.dumps(document))
      path.chmod(0o600)
      run('netplan', 'generate')
    else:
      path = PROFILE_DIR / f'{identifier}.nmconnection'
      path.write_text(f'[connection]\nid=openpilot connection {ssid}\nuuid={identifier}\ntype=wifi\nautoconnect=true\n'
                      + f'autoconnect-retries=0\nautoconnect-priority={priority}\n'
                      + f'[wifi]\nmode=infrastructure\nssid={ssid}\n[wifi-security]\nkey-mgmt=wpa-psk\npsk={password}\n'
                      + '[ipv4]\nmethod=auto\ndns-priority=600\n[ipv6]\nmethod=ignore\n')
      path.chmod(0o600)
      if source == 'shadow':
        RUNTIME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, RUNTIME_PROFILE_DIR / path.name)
    run('nmcli', 'connection', 'reload', ns=self.names['dut'])
    # NetworkManager is an independent reader, not the branch's parser.
    assert identifier in run('nmcli', '-g', 'UUID', 'connection', 'show', ns=self.names['dut']).stdout.splitlines()
    return identifier

  def start_manager(self):
    path = self.directory / 'manager.sock'
    path.unlink(missing_ok=True)
    self.manager = self.spawn('dut', sys.executable, str(Path(__file__).resolve()), '--worker', str(path))
    self.wait_external(lambda: path.exists())
    self.conn = socket.socket(socket.AF_UNIX)
    self.conn.settimeout(15)
    self.conn.connect(str(path))
    self.stream = self.conn.makefile('rwb')
    return self.call('snapshot')

  def call(self, method, *args, **kwargs):
    if method == 'connect_to_network':
      self.ssids.add(args[0])
    request = {'method': method, 'args': args, 'kwargs': kwargs, 'ssids': sorted(self.ssids)}
    self.stream.write(json.dumps(request).encode() + b'\n')
    self.stream.flush()
    line = self.stream.readline()
    if not line:
      raise RuntimeError(f'Wi-Fi manager exited; logs: {self.directory}')
    self.snapshot = json.loads(line)
    self.events.extend(self.snapshot.pop('events'))
    return self.snapshot

  def wait(self, predicate, timeout=35):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
      state = self.call('snapshot')
      if predicate(state):
        return state
      time.sleep(0.05)
    raise AssertionError(f'Wi-Fi operation did not complete: {self.snapshot}; events={self.events}; logs={self.directory}')

  @staticmethod
  def wait_external(predicate, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
      if predicate():
        return
      time.sleep(0.05)
    raise AssertionError('Wi-Fi test fixture did not become ready')

  def connected(self, ssid):
    state = self.wait(lambda s: s['connected'] == ssid and bool(s['ip']))
    assert 'wpa_state=COMPLETED' in run('wpa_cli', '-p', '/run/openpilot-wpa', '-i', 'wlan0', 'status', ns=self.names['dut']).stdout
    assert 'metric 600' in run('ip', '-4', 'route', 'show', 'default', 'dev', 'wlan0', ns=self.names['dut']).stdout
    resolver = run('cat', '/etc/resolv.conf', ns=self.names['dut']).stdout
    assert f'nameserver {SERVER}' in resolver, 'The Wi-Fi DHCP DNS server was not installed'
    self.http('dut', 'wlan0')
    return state

  def http(self, role='dut', interface=None, success=True):
    args = ['curl', '--noproxy', '*', '--silent', '--show-error', '--fail', '--max-time', '3']
    if interface:
      args += ['--interface', interface]
    result = run(*args, 'http://wifi.test:8000/probe', ns=self.names[role], check=False)
    assert (result.returncode == 0 and result.stdout == PROBE) == success, (result.returncode, result.stdout, result.stderr)

  def stop_manager(self, crash=False):
    if self.manager is not None and self.manager.poll() is None:
      if crash:
        self.manager.kill()
      else:
        self.call('stop')
      self.manager.wait(timeout=15)
    if self.stream is not None:
      self.stream.close()
      self.conn.close()
    self.manager = self.stream = self.conn = None

  def client(self, ssid, password):
    config = self.directory / 'client.conf'
    psk = password if re.fullmatch(r'[0-9a-fA-F]{64}', password) else hashlib.pbkdf2_hmac('sha1', password.encode(), ssid.encode(), 4096).hex()
    config.write_text(f'ctrl_interface={self.directory}/client-ctrl\nnetwork={{\nssid={ssid.encode().hex()}\npsk={psk}\n}}\n')
    config.chmod(0o600)
    self.spawn('client', 'wpa_supplicant', '-i', 'wlan0', '-c', str(config))
    self.wait_external(lambda: 'wpa_state=COMPLETED' in run('wpa_cli', '-p', str(self.directory / 'client-ctrl'), '-i', 'wlan0',
                                                          'status', ns=self.names['client'], check=False).stdout)
    self.spawn('client', 'udhcpc', '-i', 'wlan0', '-f', '-s', '/etc/udhcpc/default.script')
    self.wait_external(lambda: '192.168.43.' in run('ip', '-4', '-o', 'addr', 'show', 'dev', 'wlan0', ns=self.names['client']).stdout)
    assert 'nameserver 192.168.43.1' in run('cat', '/etc/resolv.conf', ns=self.names['client']).stdout

  @contextmanager
  def readonly_profiles(self):
    run('mount', '--bind', str(PROFILE_DIR), str(PROFILE_DIR))
    try:
      run('mount', '-o', 'remount,bind,ro', str(PROFILE_DIR))
      yield
    finally:
      run('umount', str(PROFILE_DIR))

  def diagnostics(self):
    for role, name in self.names.items():
      if name not in self.namespaces:
        continue
      commands = [('ip', '-br', 'addr'), ('ip', 'route'), ('iw', 'dev')]
      if role == 'dut':
        commands += [('nmcli', 'device'), ('wpa_cli', '-p', '/run/openpilot-wpa', '-i', 'wlan0', 'status')]
      with (self.directory / f'{role}-state.log').open('w') as log:
        for command in commands:
          try:
            result = run(*command, ns=name, check=False)
            log.write(f'{command!r}\n{result.stdout}{result.stderr}\n')
          except (OSError, subprocess.SubprocessError) as e:
            log.write(f'{command!r}: {e}\n')

  def cleanup(self):
    if self.manager is not None and self.manager.poll() is None:
      self.manager.kill()
      self.manager.wait(timeout=5)
    if self.stream is not None:
      self.stream.close()
      self.conn.close()
    for name in reversed(self.namespaces):
      for pid in run('ip', 'netns', 'pids', name, check=False).stdout.split():
        try:
          os.kill(int(pid), signal.SIGKILL)
        except ProcessLookupError:
          pass
    for proc in self.processes:
      proc.wait(timeout=5)
    for index, (role, phy) in enumerate(self.radios.items()):
      run('ip', 'link', 'set', 'wlan0', 'down', ns=self.names[role], check=False)
      run('ip', 'link', 'set', 'wlan0', 'name', f'e2e-radio{index}', ns=self.names[role])
      run('iw', 'phy', phy, 'set', 'netns', str(os.getpid()), ns=self.names[role])
    for name in reversed(self.namespaces):
      run('ip', 'netns', 'del', name)


if __name__ == '__main__':
  if len(sys.argv) != 3 or sys.argv[1] != '--worker':
    raise SystemExit('This module is the Wi-Fi test worker; use run_wifi_e2e.sh')
  worker(sys.argv[2])
