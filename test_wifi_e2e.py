import os
import signal
import sys
from pathlib import Path

import pytest

from wifi_e2e import PROFILE_DIR, SERVER, WifiLab, keyfile_profiles, run


pytestmark = pytest.mark.skipif(os.environ.get('WIFI_E2E') != '1', reason='requires run_wifi_e2e.sh in a disposable Linux VM')


@pytest.fixture
def lab():
  value = WifiLab()
  try:
    value.setup()
    yield value
  finally:
    try:
      value.diagnostics()
    finally:
      value.cleanup()


def start_connected(lab):
  lab.ap()
  identifier = lab.seed()
  lab.start_manager()
  lab.connected('Test A')
  return identifier


def assert_forgotten(lab, ssid):
  state = lab.wait(lambda _: ['forgotten', ssid] in lab.events)
  assert not state['saved'][ssid], 'UI received forgotten, but the manager still considers the network saved'
  assert ssid not in [profile[1] for profile in keyfile_profiles().values()], 'A persistent/runtime keyfile survived Forget'
  assert ssid not in run('wpa_cli', '-p', '/run/openpilot-wpa', '-i', 'wlan0', 'list_networks', ns=lab.names['dut']).stdout


def test_empty_scan(lab):
  lab.start_manager()
  lab.call('set_active', True)
  state = lab.wait(lambda _: ['networks_updated'] in lab.events)
  assert state['networks'] == []
  assert state['connected'] is None and not state['ip']


@pytest.mark.parametrize('ssid,password,hidden', [
  ('Open', '', False),
  ('Test A', 'password123', False),
  ('Hidden', 'password123', True),
  ('Hidden open', '', True),
  ('București', 'parolă-123', False),
  ('S' * 32, 'password123', False),
  ('Test A', '12345678', False),
  ('Test A', 'p' * 63, False),
  ('Test A', 'ab' * 32, False),
  ('Test A', ' pass\\word" ', False),
])
def test_connect_persist_and_reopen(lab, ssid, password, hidden):
  lab.ap(ssid, password, hidden=hidden)
  lab.start_manager()
  lab.call('connect_to_network', ssid, password, hidden=hidden)
  state = lab.connected(ssid)
  assert state['saved'][ssid]
  profiles = [(identifier, cp) for identifier, name, cp in keyfile_profiles().values() if name == ssid]
  assert len(profiles) == 1
  identifier, _ = profiles[0]
  run('nmcli', 'connection', 'reload', ns=lab.names['dut'])
  assert identifier in run('nmcli', '-g', 'UUID', 'connection', 'show', ns=lab.names['dut']).stdout.splitlines()
  if password:
    result = run('nmcli', '--escape', 'no', '--show-secrets', '-g', '802-11-wireless-security.psk', 'connection', 'show', identifier, ns=lab.names['dut'])
    assert result.stdout.rstrip('\n') == password
  lab.stop_manager()
  lab.start_manager()
  assert lab.connected(ssid)['saved'][ssid]
  assert identifier in [entry[0] for entry in keyfile_profiles().values()]


def test_wrong_password_then_retry(lab):
  lab.ap()
  lab.start_manager()
  lab.call('connect_to_network', 'Test A', 'incorrect123')
  state = lab.wait(lambda _: ['need_auth', 'Test A'] in lab.events)
  assert not state['saved']['Test A']
  assert 'Test A' not in [entry[1] for entry in keyfile_profiles().values()]
  lab.call('connect_to_network', 'Test A', 'password123')
  lab.connected('Test A')


def test_forget_cancels_pending_hidden_connection(lab):
  lab.start_manager()
  lab.call('connect_to_network', 'Missing', 'password123', hidden=True)
  lab.wait(lambda s: s['connecting'] == 'Missing')
  lab.events.clear()
  lab.call('forget_connection', 'Missing')
  assert_forgotten(lab, 'Missing')
  lab.stop_manager()
  assert not lab.start_manager()['saved']['Missing']


def test_switch_saved_networks_replaces_lease(lab):
  start_connected(lab)
  lab.ap('Test B', index=1)
  lab.call('connect_to_network', 'Test B', 'password123')
  assert lab.connected('Test B')['ip'].startswith('10.20.0.')
  lab.call('activate_connection', 'Test A')
  assert lab.connected('Test A')['ip'].startswith('10.10.0.')
  lab.call('activate_connection', 'Test B')
  assert lab.connected('Test B')['ip'].startswith('10.20.0.')


@pytest.mark.parametrize('source', ['keyfile', 'shadow', 'netplan'])
@pytest.mark.parametrize('active', [False, True])
def test_forget_removes_every_persistent_source(lab, source, active):
  lab.ap()
  lab.ap('Test B', index=1)
  identifier = lab.seed(source=source)
  other = lab.seed('Test B', priority=0)
  lab.start_manager()
  lab.connected('Test A')
  if not active:
    lab.call('activate_connection', 'Test B')
    lab.connected('Test B')
  lab.events.clear()
  lab.call('forget_connection', 'Test A')
  assert_forgotten(lab, 'Test A')
  lab.connected('Test B')
  assert other in [entry[0] for entry in keyfile_profiles().values()]
  lab.stop_manager()
  # Recreating generated profiles must not resurrect the forgotten network.
  run('netplan', 'generate')
  run('nmcli', 'connection', 'reload', ns=lab.names['dut'])
  assert identifier not in run('nmcli', '-g', 'UUID', 'connection', 'show', ns=lab.names['dut']).stdout.splitlines()
  lab.start_manager()
  assert not lab.connected('Test B')['saved']['Test A']


def test_forget_duplicate_profiles_for_one_ui_entry(lab):
  lab.ap()
  identifiers = {lab.seed(), lab.seed(priority=0)}
  lab.start_manager()
  lab.connected('Test A')
  lab.events.clear()
  lab.call('forget_connection', 'Test A')
  assert_forgotten(lab, 'Test A')
  assert not identifiers.intersection(entry[0] for entry in keyfile_profiles().values())
  lab.events.clear()
  lab.call('forget_connection', 'Test A')
  assert_forgotten(lab, 'Test A')


def test_failed_forget_cannot_look_successful(lab):
  start_connected(lab)
  lab.call('set_active', False)
  before = {str(path): path.read_bytes() for path in PROFILE_DIR.glob('*.nmconnection')}
  lab.events.clear()
  with lab.readonly_profiles():
    lab.call('forget_connection', 'Test A')
    state = lab.wait(lambda _: any([event, 'Test A'] in lab.events for event in ('forgotten', 'forget_failed')))
    assert ['forgotten', 'Test A'] not in lab.events, 'Persistence failed but the UI received a success callback'
    assert state['saved']['Test A']
    assert {str(path): path.read_bytes() for path in PROFILE_DIR.glob('*.nmconnection')} == before


@pytest.mark.parametrize('metered', [0, 1, 2])
def test_metering_persists_and_matches_runtime_identity(lab, metered):
  identifier = start_connected(lab)
  lab.call('set_current_network_metered', metered)
  lab.wait(lambda s: s['metered'] == metered)
  active = Path('/run/openpilot-wifi/active_profile')
  lab.wait_external(lambda: active.exists() and active.read_text().split() == [identifier, str(metered)])
  run('nmcli', 'connection', 'reload', ns=lab.names['dut'])
  value = run('nmcli', '-g', 'connection.metered', 'connection', 'show', identifier, ns=lab.names['dut']).stdout.strip()
  assert value in ({'unknown', '0'}, {'yes', '1'}, {'no', '2'})[metered]
  lab.stop_manager()
  lab.start_manager()
  assert lab.connected('Test A')['metered'] == metered


def test_failed_metering_preserves_saved_policy(lab):
  start_connected(lab)
  lab.call('set_active', False)
  lab.events.clear()
  with lab.readonly_profiles():
    lab.call('set_current_network_metered', 1)
    state = lab.wait(lambda _: ['networks_updated'] in lab.events)
    assert state['metered'] == 0
  lab.stop_manager()
  lab.start_manager()
  assert lab.connected('Test A')['metered'] == 0


def test_navigation_does_not_disconnect(lab):
  start_connected(lab)
  pid_file = Path('/run/openpilot-wpa/wpa_supplicant.pid')
  pid = pid_file.read_text()
  for active in (False, True, False, True):
    lab.call('set_active', active)
    lab.connected('Test A')
    assert pid_file.read_text() == pid


def test_dhcp_timeout_then_another_selection(lab):
  lab.ap(dhcp=False)
  lab.start_manager()
  lab.call('connect_to_network', 'Test A', 'password123')
  state = lab.wait(lambda _: ['disconnected'] in lab.events)
  assert state['connected'] is None and not state['ip']
  lab.ap('Test B', index=1)
  lab.call('connect_to_network', 'Test B', 'password123')
  lab.connected('Test B')


@pytest.mark.parametrize('crash', [False, True])
def test_manager_restart_preserves_working_station(lab, crash):
  start_connected(lab)
  files = [Path('/run/openpilot-wpa/wpa_supplicant.pid'), Path('/run/openpilot-wifi/udhcpc-wlan0.pid')]
  pids = [path.read_text() for path in files]
  lab.stop_manager(crash=crash)
  lab.http('dut', 'wlan0')
  lab.start_manager()
  lab.connected('Test A')
  assert [path.read_text() for path in files] == pids


def test_wifi_lte_priority_and_ap_loss(lab):
  start_connected(lab)
  assert 'dev wlan0' in run('ip', 'route', 'get', SERVER, ns=lab.names['dut']).stdout
  ap = lab.access_points[0][0]
  ap.terminate()
  ap.wait(timeout=5)
  lab.wait_external(lambda: 'dev wwan0' in run('ip', 'route', 'get', SERVER, ns=lab.names['dut']).stdout, timeout=35)
  lab.http('dut', 'wwan0')
  lab.ap()
  lab.connected('Test A')
  assert 'dev wlan0' in run('ip', 'route', 'get', SERVER, ns=lab.names['dut']).stdout


@pytest.mark.parametrize('pid_path', ['/run/openpilot-wpa/wpa_supplicant.pid', '/run/openpilot-wifi/udhcpc-wlan0.pid'])
def test_connected_service_failure_recovers(lab, pid_path):
  start_connected(lab)
  path = Path(pid_path)
  old_pid = path.read_text()
  os.kill(int(old_pid), signal.SIGKILL)
  lab.wait_external(lambda: path.exists() and path.read_text() != old_pid, timeout=35)
  lab.connected('Test A')


def test_station_tethering_station_and_forwarding(lab):
  start_connected(lab)
  lab.call('set_ipv4_forward', True)
  lab.call('set_tethering_active', True)
  state = lab.wait(lambda s: s['tethering'] and s['ip'] == '192.168.43.1')
  lab.client(state['connected'], state['password'])
  lab.http('client', 'wlan0')
  lab.call('set_ipv4_forward', False)
  lab.wait_external(lambda: run('sysctl', '-n', 'net.ipv4.ip_forward', ns=lab.names['dut']).stdout.strip() == '0')
  lab.http('client', 'wlan0', success=False)
  lab.call('set_ipv4_forward', True)
  lab.wait_external(lambda: run('sysctl', '-n', 'net.ipv4.ip_forward', ns=lab.names['dut']).stdout.strip() == '1')
  lab.http('client', 'wlan0')
  lab.stop_manager(crash=True)
  lab.http('client', 'wlan0')
  lab.start_manager()
  lab.wait(lambda s: s['tethering'])
  lab.call('set_tethering_active', False)
  lab.connected('Test A')
  assert not Path('/run/openpilot-wifi/dnsmasq.pid').exists()
  assert 'OPENPILOT_TETHERING' not in run('iptables-legacy-save', ns=lab.names['dut']).stdout


@pytest.mark.parametrize('active', [False, True])
@pytest.mark.parametrize('password', ['z' * 64, '🙂' * 16])
def test_rejected_tethering_password_completes_ui(lab, active, password):
  start_connected(lab)
  lab.call('set_active', False)
  if active:
    lab.call('set_tethering_active', True)
    lab.wait(lambda s: s['tethering'])
  old = lab.call('snapshot')['password']
  lab.events.clear()
  lab.call('set_tethering_password', password)
  state = lab.wait(lambda _: ['networks_updated'] in lab.events)
  assert state['password'] == old
  assert state['tethering'] == active


@pytest.mark.parametrize('active', [False, True])
def test_tethering_password_change_and_noop(lab, active):
  start_connected(lab)
  lab.call('set_active', False)
  if active:
    lab.call('set_tethering_active', True)
    lab.wait(lambda s: s['tethering'])
  password = 'new-password123'
  lab.call('set_tethering_password', password)
  lab.wait(lambda s: s['password'] == password)
  lab.events.clear()
  lab.call('set_tethering_password', password)
  lab.wait(lambda _: ['networks_updated'] in lab.events)
  lab.stop_manager()
  lab.start_manager()
  lab.wait(lambda s: s['password'] == password)
  if not active:
    lab.call('set_tethering_active', True)
  state = lab.wait(lambda s: s['tethering'])
  lab.client(state['connected'], password)


def test_hidden_connection_requested_while_tethering_completes(lab):
  start_connected(lab)
  lab.call('set_tethering_active', True)
  lab.wait(lambda s: s['tethering'])
  lab.events.clear()
  lab.call('connect_to_network', 'Missing', 'password123', hidden=True)
  state = lab.wait(lambda _: ['disconnected'] in lab.events)
  assert state['tethering'] and not state['saved']['Missing']


@pytest.mark.parametrize('password', ['z' * 64, '🙂' * 16])
def test_rejected_station_password_completes_ui(lab, password):
  lab.ap()
  lab.start_manager()
  lab.call('connect_to_network', 'Test A', password)
  state = lab.wait(lambda _: ['need_auth', 'Test A'] in lab.events)
  assert not state['saved']['Test A'] and state['connected'] is None
  assert 'Test A' not in [entry[1] for entry in keyfile_profiles().values()]


def test_password_replacement_failure_preserves_working_profile(lab):
  start_connected(lab)
  before = {str(path): path.read_bytes() for path in PROFILE_DIR.glob('*.nmconnection')}
  lab.events.clear()
  lab.call('connect_to_network', 'Test A', 'incorrect123', hidden=True)
  lab.wait(lambda _: ['need_auth', 'Test A'] in lab.events)
  assert {str(path): path.read_bytes() for path in PROFILE_DIR.glob('*.nmconnection')} == before
  lab.call('activate_connection', 'Test A')
  lab.connected('Test A')


def test_new_profile_write_failure_does_not_report_connected(lab):
  lab.ap()
  lab.start_manager()
  with lab.readonly_profiles():
    lab.call('connect_to_network', 'Test A', 'password123')
    state = lab.wait(lambda _: ['disconnected'] in lab.events)
    assert not state['saved']['Test A'] and state['connected'] is None
    assert ['activated'] not in lab.events
    assert 'Test A' not in [entry[1] for entry in keyfile_profiles().values()]


def test_new_selection_supersedes_pending_connection(lab):
  lab.ap()
  lab.seed()
  lab.start_manager()
  lab.connected('Test A')
  lab.call('connect_to_network', 'Missing', 'password123', hidden=True)
  lab.wait(lambda s: s['connecting'] == 'Missing')
  lab.call('activate_connection', 'Test A')
  state = lab.connected('Test A')
  assert not state['saved']['Missing']
  assert 'Missing' not in [entry[1] for entry in keyfile_profiles().values()]


@pytest.mark.parametrize('connecting', [False, True])
def test_tethering_without_an_active_station(lab, connecting):
  lab.start_manager()
  if connecting:
    lab.call('connect_to_network', 'Missing', 'password123', hidden=True)
    lab.wait(lambda s: s['connecting'] == 'Missing')
  lab.call('set_ipv4_forward', True)
  lab.call('set_tethering_active', True)
  state = lab.wait(lambda s: s['tethering'] and bool(s['ip']))
  lab.client(state['connected'], state['password'])
  lab.http('client', 'wlan0')
  lab.call('set_tethering_active', False)
  state = lab.wait(lambda s: not s['tethering'])
  assert not state['connected']


@pytest.mark.parametrize('active', [False, True])
def test_failed_tethering_password_write_keeps_previous_password(lab, active):
  start_connected(lab)
  lab.call('set_active', False)
  if active:
    lab.call('set_tethering_active', True)
    lab.wait(lambda s: s['tethering'])
  old = lab.call('snapshot')['password']
  lab.events.clear()
  with lab.readonly_profiles():
    lab.call('set_tethering_password', 'new-password123')
    state = lab.wait(lambda _: ['networks_updated'] in lab.events)
    assert state['password'] == old and state['tethering'] == active
  lab.stop_manager()
  lab.start_manager()
  lab.wait(lambda s: s['password'] == old)
  if active:
    state = lab.wait(lambda s: s['tethering'])
    lab.client(state['connected'], old)
  else:
    lab.connected('Test A')


def test_networkmanager_works_before_ui_and_after_explicit_handoff(lab):
  lab.ap()
  identifier = lab.seed()
  run('nmcli', '--wait', '20', 'connection', 'up', identifier, ns=lab.names['dut'])
  lab.http('dut', 'wlan0')
  lab.start_manager()
  lab.connected('Test A')
  lab.call('set_current_network_metered', 1)
  lab.wait(lambda s: s['metered'] == 1)
  lab.stop_manager()
  # Exercise the real handoff primitives, not a checkout/reboot of the old UI.
  run(sys.executable, '-c',
      'from openpilot.system.ui.lib import wpa_supplicant as w; '
      + 'from openpilot.system.ui.lib.dhcp_client import DhcpClient; '
      + 'assert DhcpClient().stop(); assert w.stop(w.WPA_SUPPLICANT_CONF); assert w.restore_networkmanager()',
      ns=lab.names['dut'])
  run('nmcli', '--wait', '20', 'connection', 'up', identifier, ns=lab.names['dut'])
  lab.http('dut', 'wlan0')
  value = run('nmcli', '-g', 'connection.metered', 'connection', 'show', identifier, ns=lab.names['dut']).stdout.strip()
  assert value in ('yes', '1')
