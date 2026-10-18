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
  try:
    return subprocess.run(command, check=check, capture_output=True, text=True, timeout=30)
  except subprocess.CalledProcessError as error:
    print('subprocess stdout:\n', error.stdout, sep='')
    print('subprocess stderr:\n', error.stderr, sep='')
    raise


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
  from openpilot.system.ui.lib import wifi_manager
  from openpilot.system.ui.lib.wifi_manager import WifiManager

  config = Path('/run/wifi-e2e-wpa_supplicant.conf')
  shutil.copyfile(wifi_manager.WPA_CONF_PATH, config)
  # Hwsim station fixtures use channel 1.
  with config.open('a') as f:
    f.write('\nfreq_list=2412\n')
  wifi_manager.WPA_CONF_PATH = str(config)

  events = []
  write_profile = wifi_manager.write_profile

  def record_failed_profile_write(profile):
    try:
      return write_profile(profile)
    except Exception:
      events.append(['save_failed', profile.ssid])
      raise

  wifi_manager.write_profile = record_failed_profile_write
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
    WifiLab.wait_external(lambda: manager._ready)
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
          if request.get('wait_for_setter'):
            threads = []
            threading_module = wifi_manager.threading

            def create_thread(*args, **kwargs):
              thread = threading_module.Thread(*args, **kwargs)
              threads.append(thread)
              return thread

            wifi_manager.threading = type('ThreadFactory', (), {'Thread': staticmethod(create_thread)})
            try:
              getattr(manager, method)(*request.get('args', []), **request.get('kwargs', {}))
            finally:
              wifi_manager.threading = threading_module
            if len(threads) != 1:
              raise RuntimeError(f'{method} started {len(threads)} worker threads')
            threads[0].join(timeout=35)
            if threads[0].is_alive():
              raise TimeoutError(f'{method} worker thread did not finish')
          else:
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
    for path in (PROFILE_DIR, RUNTIME_PROFILE_DIR, Path('/run/NetworkManager/devices'), Path('/run/wpa_supplicant'),
                 Path('/etc/netplan'), Path('/var/lib/NetworkManager')):
      path.mkdir(parents=True, exist_ok=True)
      for child in path.iterdir():
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    for path in (Path('/run/udhcpc.wlan0.pid'), Path('/run/dnsmasq.wlan0.pid')):
      path.unlink(missing_ok=True)
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
               f'--listen-address={SERVER},{CELLULAR_DNS}', f'--address=/wifi.test/{SERVER}', '--local=/wifi.test/')
    self.spawn('dut', 'dbus-daemon', '--system', '--nofork', '--nopidfile')
    self.wait_external(lambda: Path('/run/dbus/system_bus_socket').exists())
    config = self.directory / 'NetworkManager.conf'
    config.write_text('[main]\nplugins=keyfile\ndhcp=internal\ndns=default\nrc-manager=file\nauth-polkit=false\n'
                      + 'no-auto-default=*\n[device-lte]\nmatch-device=interface-name:wwan0\nmanaged=0\n'
                      + f'[global-dns-domain-*]\nservers={CELLULAR_DNS}\n')
    empty = self.directory / 'empty'
    empty.mkdir()
    self.spawn('dut', 'NetworkManager', '--no-daemon', '--log-level=DEBUG', f'--config={config}', f'--config-dir={empty}', f'--system-config-dir={empty}')
    self.wait_external(lambda: run('nmcli', '-t', '-f', 'RUNNING', 'general', ns=self.names['dut'], check=False).stdout.strip() == 'running')
    self.wait_external(lambda: run('curl', '--noproxy', '*', '--silent', '--max-time', '1',
                                  f'http://{SERVER}:8000/probe', ns=self.names['wan'], check=False).stdout == PROBE)
    sudo = run('sudo', '-n', 'true', ns=self.names['dut'])
    assert 'unable to resolve host' not in sudo.stderr

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
      psk = password if re.fullmatch(r'[0-9a-fA-F]{64}', password) else hashlib.pbkdf2_hmac('sha1', password.encode(), ssid.encode(), 4096, 32).hex()
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
      document = {'network': {'version': 2, 'renderer': 'NetworkManager', 'wifis': {f'NM-{identifier}': {
        'match': {'name': 'wlan0'}, 'dhcp4': True, 'access-points': {ssid: {'password': password}}, 'networkmanager': {
          'uuid': identifier, 'name': f'openpilot connection {ssid}', 'passthrough': {
            'connection.autoconnect-retries': '0', 'connection.autoconnect-priority': str(priority),
            'ipv4.dns-priority': '600', 'ipv6.method': 'ignore',
          },
        },
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

  def _call(self, method, *args, wait_for_setter=False, **kwargs):
    if method == 'connect_to_network':
      self.ssids.add(args[0])
    self.conn.settimeout(40 if wait_for_setter else 15)
    request = {'method': method, 'args': args, 'kwargs': kwargs, 'ssids': sorted(self.ssids),
               'wait_for_setter': wait_for_setter}
    self.stream.write(json.dumps(request).encode() + b'\n')
    self.stream.flush()
    line = self.stream.readline()
    if not line:
      raise RuntimeError(f'Wi-Fi manager exited; logs: {self.directory}')
    self.snapshot = json.loads(line)
    self.events.extend(self.snapshot.pop('events'))
    return self.snapshot

  def call(self, method, *args, **kwargs):
    return self._call(method, *args, **kwargs)

  def call_setter(self, method, *args, **kwargs):
    return self._call(method, *args, wait_for_setter=True, **kwargs)

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
    assert 'wpa_state=COMPLETED' in run('wpa_cli', '-p', '/run/wpa_supplicant', '-i', 'wlan0', 'status', ns=self.names['dut']).stdout
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
    psk = password if re.fullmatch(r'[0-9a-fA-F]{64}', password) else hashlib.pbkdf2_hmac('sha1', password.encode(), ssid.encode(), 4096, 32).hex()
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
    if self.manager is None or self.manager.poll() is not None:
      raise RuntimeError('Profile write failure injection requires a live manager')
    namespace = ('nsenter', '-t', str(self.manager.pid), '-m', '--')
    run(*namespace, 'mount', '--bind', str(PROFILE_DIR), str(PROFILE_DIR))
    try:
      run(*namespace, 'mount', '-o', 'remount,bind,ro', str(PROFILE_DIR))
      probe = PROFILE_DIR / '.wifi-e2e-readonly-probe'
      result = run(*namespace, 'env', 'LC_ALL=C', 'touch', str(probe), check=False)
      if result.returncode == 0:
        run(*namespace, 'rm', '-f', str(probe))
        raise AssertionError('Profile write fault did not make the manager mount read-only')
      if 'Read-only file system' not in result.stderr:
        raise AssertionError(f'Profile write fault probe failed unexpectedly: {result.stderr.strip()}')
      yield
    finally:
      run(*namespace, 'umount', str(PROFILE_DIR))

  def diagnostics(self):
    for role, name in self.names.items():
      if name not in self.namespaces:
        continue
      commands = [('ip', '-br', 'addr'), ('ip', 'route'), ('iw', 'dev')]
      if role == 'dut':
        commands += [('nmcli', 'device'), ('nmcli', '-f', 'GENERAL', 'device', 'show', 'wlan0'),
                     ('wpa_cli', '-p', '/run/wpa_supplicant', '-i', 'wlan0', 'status')]
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




def check_route_priority(mode, script, directory):
  outer_mount = os.environ.get('WIFI_E2E_OUTER_MNT')
  if (os.geteuid() != 0 or os.environ.get('WIFI_E2E_VM') != '1' or Path('/AGNOS').exists() or
      not outer_mount or outer_mount == os.readlink('/proc/self/ns/mnt')):
    raise RuntimeError('Route tests require a private mount namespace in the disposable VM')
  p = Path(directory).resolve() / 'trial'
  p.mkdir()
  trial = 'route'
  announce = 0
  candidate = Path(script).resolve()
  udev_data = Path(os.environ.get('WIFI_E2E_UDEV_DATA', '/run/udev/data'))
  if not udev_data.is_dir():
    raise RuntimeError(f'Udev data source is unavailable: {udev_data}')
  dut = 'c4-' + trial + 'd'
  lan = 'c4-' + trial + 'l'
  procs = []
  files = []
  created = []
  log = (p / 'commands.jsonl').open('w', buffering=1)

  def run(args, check=True, ns=None, env=None, timeout=15):
    cmd = (['ip', 'netns', 'exec', ns] if ns else []) + list(args)
    t = time.time()
    cp = subprocess.run(cmd, text=True, capture_output=True, env=env, timeout=timeout)
    log.write(json.dumps(dict(time=t, cmd=cmd, rc=cp.returncode, stdout=cp.stdout, stderr=cp.stderr)) + '\n')
    if check and cp.returncode:
      raise RuntimeError(f'{cmd}: {cp.returncode}: {cp.stderr}')
    return cp

  def spawn(args, name, ns=None, env=None):
    cmd = (['ip', 'netns', 'exec', ns] if ns else []) + list(args)
    f = (p / name).open('w')
    files.append(f)
    pr = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT, text=True, env=env, start_new_session=True)
    procs.append(pr)
    log.write(json.dumps(dict(time=time.time(), spawn=cmd, pid=pr.pid)) + '\n')
    return pr

  def stamp(label):
    print(label, time.time(), flush=True)
    log.write(json.dumps(dict(time=time.time(), label=label)) + '\n')

  def snapshot(label):
    stamp(label)
    result = {}
    for name, args in [
      ('routes', ['ip', '-4', 'route', 'show']),
      ('address', ['ip', '-4', '-o', 'addr']),
      ('lookup', ['ip', '-4', 'route', 'get', '192.168.1.171', 'from', '192.168.1.199']),
    ]:
      result[name] = run(args, ns=dut).stdout
    (p / (label + '.json')).write_text(json.dumps(result, indent=2))
    print(json.dumps(result), flush=True)
    return result

  try:
    resolver_before = hashlib.sha256(Path('/etc/resolv.conf').read_bytes()).hexdigest()
    before = run(['ip', '-j', '-4', 'route', 'show']).stdout
    (p / 'host-routes-before.json').write_text(before)
    for n in (dut, lan):
      run(['ip', 'netns', 'add', n])
      created.append(n)
      run(['ip', 'link', 'set', 'lo', 'up'], ns=n)
    run(['ip', 'link', 'add', 'br0', 'type', 'bridge'], ns=lan)
    run(['ip', 'link', 'set', 'br0', 'address', '02:11:22:33:44:ff'], ns=lan)
    run(['ip', 'link', 'set', 'br0', 'up'], ns=lan)
    run(['ip', 'addr', 'add', '192.168.1.1/24', 'dev', 'br0'], ns=lan)
    run(['ip', 'addr', 'add', '192.168.1.171/24', 'dev', 'br0'], ns=lan)
    for short, iface, mac in [('e', 'eth0', '02:11:22:33:44:01'), ('w', 'wlan0', '02:11:22:33:44:02')]:
      a = 'c4' + trial + short
      b = a + 'p'
      run(['ip', 'link', 'add', a, 'type', 'veth', 'peer', 'name', b])
      indexes = {name: int((Path('/sys/class/net') / name / 'ifindex').read_text()) for name in (a, b)}
      run(['udevadm', 'settle', '--timeout=5'])
      deadline = time.monotonic() + 5
      while True:
        initialized = {}
        for name, index in indexes.items():
          record = udev_data / f'n{index}'
          value = record.read_text() if record.exists() else ''
          initialized[name] = re.search(r'^I:[1-9][0-9]*$', value, re.MULTILINE) is not None
        if all(initialized.values()):
          break
        if time.monotonic() >= deadline:
          raise RuntimeError(f'Udev initialization timed out: source={udev_data}, ifindexes={indexes}, initialized={initialized}')
        time.sleep(0.05)
      log.write(json.dumps(dict(time=time.time(), udev_source=str(udev_data), ifindexes=indexes, initialized=initialized)) + '\n')
      shutil.copytree(udev_data, p / 'udev-data', dirs_exist_ok=True)
      run(['ip', 'link', 'set', a, 'netns', dut])
      run(['ip', 'link', 'set', b, 'netns', lan])
      run(['ip', 'link', 'set', a, 'name', iface], ns=dut)
      run(['ip', 'link', 'set', iface, 'address', mac], ns=dut)
      run(['ip', 'link', 'set', b, 'master', 'br0'], ns=lan)
      run(['ip', 'link', 'set', b, 'up'], ns=lan)
    for d in ['etcNM/system-connections', 'varlib', 'empty', 'bin']:
      (p / d).mkdir(parents=True, exist_ok=True)
    (p / 'nm.conf').write_text(
      '[main]\nplugins=keyfile\ndhcp=internal\ndns=none\nrc-manager=unmanaged\nauth-polkit=false\nno-auto-default=*\n[device-wlan]\nmatch-device=interface-name:wlan0\nmanaged=0\n'
    )
    (p / 'bin/logger').write_text('#!/bin/sh\nprintf "%s %s\\n" "$(date +%s.%N)" "$*" >> "' + str(p / 'hook-syslog.log') + '"\n')
    (p / 'bin/resolvconf').write_text('#!/bin/sh\necho "$@" >> "' + str(p / 'hook-dns.log') + '"\ncat >> "' + str(p / 'hook-dns.log') + '"\n')
    for f in (p / 'bin').iterdir():
      f.chmod(0o755)
    run(['mount', '--bind', str(p / 'bin/resolvconf'), str(Path('/sbin/resolvconf').resolve())])
    for src, name in [('/etc/udhcpc/default.script', 'default.script'), (str(candidate), 'udhcpc.script')]:
      shutil.copyfile(src, p / name)
      (p / name).chmod(0o755)
    spawn(['tcpdump', '-U', '-n', '-i', 'br0', '-w', str(p / 'arp.pcap'), 'arp or udp port 9999'], 'tcpdump.log', ns=lan)
    spawn(['ip', '-ts', 'monitor', 'route', 'address', 'link'], 'route-monitor.log', ns=dut)
    spawn(
      [
        'dnsmasq',
        '--keep-in-foreground',
        '--conf-file=/dev/null',
        '--port=0',
        '--interface=br0',
        '--bind-interfaces',
        '--dhcp-authoritative',
        '--dhcp-range=192.168.1.100,192.168.1.220,255.255.255.0,1h',
        '--dhcp-host=02:11:22:33:44:01,192.168.1.199',
        '--dhcp-leasefile=' + str(p / 'leases'),
        '--log-dhcp',
        '--log-facility=-',
      ],
      'dhcp-server.log',
      ns=lan,
    )
    env = os.environ.copy()
    if mode == 'nm':
      bus = f'unix:abstract=wifi-route-{os.getpid()}'
      setup = f'''set -eu
    mount -t tmpfs tmpfs /run
    mkdir -p /run/udev/data
    mount --bind {p}/udev-data /run/udev/data
    mount -o remount,bind,ro /run/udev/data
    mount --bind {p}/etcNM /etc/NetworkManager
    mount --bind {p}/varlib /var/lib/NetworkManager
    mount --bind {p}/empty /etc/netplan
    dbus-daemon --system --nofork --nopidfile --address={bus} > {p}/dbus.log 2>&1 &
    export DBUS_SYSTEM_BUS_ADDRESS={bus}
    exec strace -f -ttt -s 512 -e trace=sendmsg,recvmsg,ioctl -o {p}/nm.strace \\
      NetworkManager --no-daemon --debug --config={p}/nm.conf --config-dir={p}/empty \\
      --system-config-dir={p}/empty --pid-file={p}/nm.pid --log-level=TRACE --log-domains=PLATFORM,IP4,DEVICE,DHCP4,CORE
    '''
      (p / 'nm-start.sh').write_text(setup)
      nm = spawn(['unshare', '-m', '--propagation', 'private', 'bash', str(p / 'nm-start.sh')], 'nm.log', ns=dut)
      env = os.environ.copy()
      env['DBUS_SYSTEM_BUS_ADDRESS'] = bus
      for i in range(50):
        cp = run(['nmcli', '-t', '-f', 'RUNNING', 'general'], check=False, ns=dut, env=env, timeout=3)
        if cp.returncode == 0 and cp.stdout.strip() == 'running':
          break
        if nm.poll() is not None:
          raise RuntimeError('private NM exited; inspect nm.log')
        time.sleep(0.1)
      else:
        raise RuntimeError('private NM readiness failed')
      run(['nmcli', '-f', 'GENERAL', 'device', 'show'], ns=dut, env=env)
      run(
        [
          'nmcli',
          'connection',
          'add',
          'type',
          'ethernet',
          'ifname',
          'eth0',
          'con-name',
          'wired-test',
          'ipv4.method',
          'auto',
          'ipv4.route-metric',
          '100',
          'ipv6.method',
          'disabled',
          'connection.autoconnect',
          'no',
        ],
        ns=dut,
        env=env,
      )
      run(['nmcli', '--wait', '10', 'connection', 'up', 'wired-test'], ns=dut, env=env)
    else:
      run(['ip', 'link', 'set', 'eth0', 'up'], ns=dut)
      run(['ip', 'addr', 'add', '192.168.1.199/24', 'dev', 'eth0', 'noprefixroute'], ns=dut)
      run(['ip', 'route', 'add', '192.168.1.0/24', 'dev', 'eth0', 'src', '192.168.1.199', 'metric', '100'], ns=dut)
      run(['ip', 'route', 'add', 'default', 'via', '192.168.1.1', 'dev', 'eth0', 'metric', '100'], ns=dut)
    snapshot('wired-baseline')
    run(['ip', 'link', 'set', 'wlan0', 'up'], ns=dut)
    run(['sysctl', '-w', f'net.ipv4.conf.wlan0.arp_announce={announce}'], ns=dut)
    assert run(['sysctl', '-n', 'net.ipv4.conf.all.arp_announce', 'net.ipv4.conf.eth0.arp_announce',
                'net.ipv4.conf.wlan0.arp_announce'], ns=dut).stdout.split() == ['0', '0', '0']
    run(['ip', 'addr', 'add', '192.168.43.1/24', 'dev', 'wlan0'], ns=dut)
    snapshot('ap-address-baseline')
    traffic = (
      'import socket,time\n'
      "s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.bind(('192.168.1.199',0))\n"
      'end=time.monotonic()+20;n=0;errors=0\n'
      'while time.monotonic()<end:\n'
      "  try:s.sendto(b'routeprobe',('192.168.1.171',9999));n+=1\n"
      '  except OSError:errors+=1\n'
      '  time.sleep(.002)\n'
      "print('sent',n,'errors',errors,flush=True)\n"
    )
    (p / 'traffic.py').write_text(traffic)
    sender = spawn(['python3', str(p / 'traffic.py')], 'traffic.log', ns=dut)
    henv = os.environ.copy()
    henv.update(
      PATH=str(p / 'bin') + ':' + henv['PATH'],
      UDHCPC_DEFAULT_SCRIPT=str(p / 'default.script'),
      interface='wlan0',
      ip='192.168.1.108',
      subnet='255.255.255.0',
      router='192.168.1.1',
      mtu='1400',
      broadcast='192.168.1.255',
      dns='192.168.1.1',
      lease='43200',
      domain='lab',
    )
    (p / 'resolv.conf').write_text('')
    (p / 'absent').write_text('')
    (p / 'absent').chmod(0o644)
    resolver_target = str(Path('/etc/resolv.conf').resolve())
    (p / 'hook-isolate.sh').write_text(f'''#!/bin/sh
set -eu
if [ "{mode}" = no-nm ]; then
  mount -t tmpfs tmpfs /run
  mount --bind {p}/absent /usr/bin/nmcli
  mount --bind {p}/absent /usr/sbin/NetworkManager
  test ! -x /usr/bin/nmcli
  test ! -x /usr/sbin/NetworkManager
  test ! -S /run/dbus/system_bus_socket
fi
if [ "${{DNS_FALLBACK:-0}}" = 1 ]; then
  mount --bind {p}/absent /usr/bin/resolvectl
fi
if [ ! -e {resolver_target} ]; then
  mkdir -p $(dirname {resolver_target})
  touch {resolver_target}
fi
mount --bind {p}/resolv.conf {resolver_target}
exec {p}/udhcpc.script "$1"
''')
    hook = ['unshare', '-m', '--propagation', 'private', 'sh', str(p / 'hook-isolate.sh')]
    outcomes = []
    for i in range(10):
      for action in ('deconfig', 'bound', 'renew'):
        stamp('cycle-' + str(i) + '-' + action)
        run(hook + [action], ns=dut, env=henv)
        if action == 'deconfig':
          assert json.loads(run(['ip', '-j', '-4', 'route', 'show', 'dev', 'wlan0'], ns=dut).stdout) == []
          assert all(not row['addr_info'] for row in json.loads(run(['ip', '-j', '-4', 'addr', 'show', 'dev', 'wlan0'], ns=dut).stdout))
        if action == 'bound':
          run(['ip', 'route', 'replace', '203.0.113.0/24', 'dev', 'wlan0'], ns=dut)
        if action != 'deconfig':
          routes = json.loads(run(['ip', '-j', '-4', 'route', 'show', 'dev', 'wlan0'], ns=dut).stdout)
          assert len([r for r in routes if r.get('dst') == '192.168.1.0/24' and r.get('metric') == 600]) == 1, routes
          assert len([r for r in routes if r.get('dst') == 'default' and r.get('metric') == 600]) == 1, routes
          assert any(r.get('dst') == '203.0.113.0/24' for r in routes), routes
        if action != 'deconfig':
          run(
            [
              'python3',
              '-c',
              "import socket;s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);"
              "s.setsockopt(socket.SOL_SOCKET,socket.SO_BINDTODEVICE,b'wlan0\\0');"
              "s.bind(('192.168.1.108',0));s.sendto(b'wlanprobe',('192.168.1.171',9999))",
            ],
            ns=dut,
          )
        time.sleep(0.1)
        r = snapshot('cycle-' + str(i) + '-' + action + '-after')
        outcomes.append('dev eth0' not in r['lookup'])
    installed = [line for line in (p / 'route-monitor.log').read_text().splitlines()
                 if 'dev wlan0' in line and ('192.168.1.0/24' in line or 'default via' in line) and 'Deleted' not in line]
    assert installed and all('metric 600' in line for line in installed), installed
    run(['ip', 'addr', 'add', '10.9.0.1/24', 'dev', 'br0'], ns=lan)
    edges = []
    for label, updates in [
      ('host-route', dict(ip='192.168.1.109', subnet='255.255.255.255', broadcast='192.168.1.109')),
      ('renumber', dict(ip='192.168.1.110', subnet='255.255.255.0', broadcast='192.168.1.255')),
      ('new-subnet', dict(ip='10.9.0.110', subnet='255.255.255.0', broadcast='10.9.0.255', router='10.9.0.1')),
      ('no-router', dict(router='')),
      ('file-dns', dict(DNS_FALLBACK='1', dns='192.168.1.9', domain='fallback')),
    ]:
      henv.update(updates)
      run(hook + ['renew'], ns=dut, env=henv)
      rows = json.loads(run(['ip', '-j', '-4', 'route', 'show', 'dev', 'wlan0'], ns=dut).stdout)
      addresses = json.loads(run(['ip', '-j', '-4', 'addr', 'show', 'dev', 'wlan0'], ns=dut).stdout)[0]
      assert addresses['mtu'] == 1400 and len(addresses['addr_info']) == 1, addresses
      assert addresses['addr_info'][0]['local'] == henv['ip'], addresses
      defaults = [r for r in rows if r.get('dst') == 'default']
      assert len(defaults) == bool(henv['router']), rows
      if henv['subnet'] == '255.255.255.255':
        assert not any(r.get('dst') == '192.168.1.0/24' for r in rows), rows
        assert defaults[0]['metric'] == 600 and 'onlink' in defaults[0].get('flags', []), rows
      else:
        assert (
          len(
            [
              r
              for r in rows
              if r.get('dst') == ('10.9.0.0/24' if henv['ip'].startswith('10.9.') else '192.168.1.0/24')
              and r.get('prefsrc') == henv['ip']
              and r.get('metric') == 600
            ]
          )
          == 1
        ), rows
      if label == 'file-dns':
        assert (p / 'resolv.conf').read_text() == 'domain fallback\nnameserver 192.168.1.9\n'
      snapshot(label)
      edges.append(label)
    routes = run(['ip', '-4', 'route', 'show'], ns=dut).stdout
    for action in ('nak', 'leasefail'):
      run(hook + [action], ns=dut, env=henv)
      assert run(['ip', '-4', 'route', 'show'], ns=dut).stdout == routes
    run(hook + ['deconfig'], ns=dut, env=henv)
    assert json.loads(run(['ip', '-j', '-4', 'route', 'show', 'dev', 'wlan0'], ns=dut).stdout) == []
    sender.terminate()
    sender.wait(timeout=3)
    time.sleep(0.2)
    snapshot('final')
    if mode == 'nm':
      run(['nmcli', '-f', 'GENERAL.STATE,IP4.ADDRESS,IP4.ROUTE', 'device', 'show', 'eth0'], ns=dut, env=env)
      assert 'unmanaged' in run(['nmcli', '-g', 'GENERAL.STATE', 'device', 'show', 'wlan0'], ns=dut, env=env).stdout
    monitor = (p / 'route-monitor.log').read_text().splitlines()
    wlan_events = [
      line
      for line in monitor
      if 'dev wlan0' in line
      and (('proto kernel scope link' in line and '192.168.43.0/24' not in line) or 'default via' in line)
      and 'Deleted' not in line
      and 'table local' not in line
    ]
    bad_metrics = [line for line in wlan_events if 'metric 600' not in line]
    deleted = [line for line in monitor if 'Deleted' in line and '192.168.1.0/24 dev eth0' in line]
    dns = (p / 'hook-dns.log').read_text()
    assert 'nameserver 192.168.1.1' in dns and 'domain lab' in dns and '-d wlan0.udhcpc' in dns, dns
    result = dict(
      mode=mode,
      announce=announce,
      cycles=10,
      lookups=len(outcomes),
      edge_cases=edges,
      route_loss=any(outcomes),
      wlan_events=len(wlan_events),
      bad_metrics=bad_metrics,
      eth_deletions=deleted,
      coverage_limit='NM package absence simulated with non-executable bind masks, isolated /run, no NM service'
      if mode == 'no-nm'
      else 'real NM owns DHCP Ethernet, WLAN unmanaged',
    )
    (p / 'result.json').write_text(json.dumps(result, indent=2))
    print('RESULT', json.dumps(result), flush=True)
    assert wlan_events and not bad_metrics, result
    assert not any(outcomes) and not deleted, result
    procs[0].send_signal(signal.SIGINT)
    procs[0].wait(timeout=3)
    wired = run(['tcpdump', '-n', '-e', '-r', str(p / 'arp.pcap'), 'ip and src host 192.168.1.199 and udp dst port 9999']).stdout
    diverted = run(['tcpdump', '-n', '-e', '-r', str(p / 'arp.pcap'), 'ether src 02:11:22:33:44:02 and src host 192.168.1.199']).stdout
    wlan = run(['tcpdump', '-n', '-e', '-r', str(p / 'arp.pcap'),
                'ether src 02:11:22:33:44:02 and ip and src host 192.168.1.108 and udp dst port 9999']).stdout
    assert wired and wlan and not diverted, (wired, wlan, diverted)
    (p / 'manifest.json').write_text(json.dumps(dict(result, hook_sha256=hashlib.sha256(candidate.read_bytes()).hexdigest(), passed=True), indent=2))
  finally:
    for n in created:
      ids = run(['ip', 'netns', 'pids', n], check=False).stdout.split()
      for pid in ids:
        try:
          os.kill(int(pid), signal.SIGTERM)
        except ProcessLookupError:
          pass
    time.sleep(0.3)
    for n in created:
      ids = run(['ip', 'netns', 'pids', n], check=False).stdout.split()
      for pid in ids:
        try:
          os.kill(int(pid), signal.SIGKILL)
        except ProcessLookupError:
          pass
    for pr in procs:
      try:
        pr.wait(timeout=3)
      except subprocess.TimeoutExpired:
        os.killpg(pr.pid, signal.SIGKILL)
        pr.wait()
    for n in reversed(created):
      run(['ip', 'netns', 'del', n], check=False)
    for f in files:
      f.close()
    after = run(['ip', '-j', '-4', 'route', 'show']).stdout
    (p / 'host-routes-after.json').write_text(after)
    print('CLEANUP host_routes_unchanged', json.loads(before) == json.loads(after), flush=True)
    print('CLEANUP host_resolver_unchanged', resolver_before == hashlib.sha256(Path('/etc/resolv.conf').read_bytes()).hexdigest(), flush=True)
    print('NAMESPACES', run(['ip', 'netns', 'list']).stdout, flush=True)
    log.close()


if __name__ == '__main__':
  if len(sys.argv) == 4 and sys.argv[1] == '--route-priority':
    check_route_priority(sys.argv[2], os.environ['UDHCPC_SCRIPT_PATH'], sys.argv[3])
    raise SystemExit(0)
  if len(sys.argv) != 3 or sys.argv[1] != '--worker':
    raise SystemExit('This module is the Wi-Fi test worker; use run_wifi_e2e.sh')
  worker(sys.argv[2])
