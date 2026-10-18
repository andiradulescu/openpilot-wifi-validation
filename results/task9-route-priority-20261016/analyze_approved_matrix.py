import io
import json
import struct
import tarfile
from pathlib import Path

root = Path('/Users/andiradulescu/Projects/firstmate/data/wifi-route-priority')
summary = {}
with tarfile.open(root / 'evidence/approved-hwsim-artifacts.tar.gz') as archive:
  for member in archive.getmembers():
    if not member.name.endswith('/trial/manifest.json'):
      continue
    prefix = member.name.removesuffix('/manifest.json')
    manifest = json.load(archive.extractfile(member))
    assert manifest['passed'] and manifest['announce'] == 0 and manifest['cycles'] == 10, manifest
    assert manifest['lookups'] == 30 and not manifest['route_loss'], manifest
    assert not manifest['bad_metrics'] and not manifest['eth_deletions'] and manifest['wlan_events'] == 35, manifest
    commands = [json.loads(line) for line in archive.extractfile(prefix + '/commands.jsonl')]
    udev = [row for row in commands if 'udev_source' in row]
    assert len(udev) == 2 and all(all(row['initialized'].values()) for row in udev), udev
    pcap = io.BytesIO(archive.extractfile(prefix + '/arp.pcap').read())
    endian = {b'\xd4\xc3\xb2\xa1': '<', b'\xa1\xb2\xc3\xd4': '>'}[pcap.read(4)]
    pcap.read(20)
    counts = dict(wired_udp=0, wlan_udp=0, wlan_wired_udp=0, wlan_wired_arp=0, wlan_arp=0)
    while header := pcap.read(16):
      _, _, length, _ = struct.unpack(endian + 'IIII', header)
      frame = pcap.read(length)
      if len(frame) < 42:
        continue
      wlan = frame[6:12] == bytes.fromhex('021122334402')
      if frame[12:14] == b'\x08\x00' and frame[23] == 17:
        offset = 14 + (frame[14] & 15) * 4
        if int.from_bytes(frame[offset + 2:offset + 4], 'big') == 9999:
          if frame[26:30] == bytes([192, 168, 1, 199]):
            counts['wlan_wired_udp' if wlan else 'wired_udp'] += 1
          if wlan and frame[26:30] == bytes([192, 168, 1, 108]):
            counts['wlan_udp'] += 1
      if frame[12:14] == b'\x08\x06' and wlan:
        counts['wlan_arp'] += 1
        if frame[28:32] == bytes([192, 168, 1, 199]):
          counts['wlan_wired_arp'] += 1
    assert counts['wired_udp'] > 0 and counts['wlan_udp'] > 0, counts
    assert counts['wlan_wired_udp'] == counts['wlan_wired_arp'] == 0, counts
    deconfigs = []
    for cycle in range(10):
      snap = json.load(archive.extractfile(prefix + f'/cycle-{cycle}-deconfig-after.json'))
      deconfigs.append(not any('wlan0' in line for line in snap['routes'].splitlines()) and
                       not any('wlan0' in line for line in snap['address'].splitlines()))
    assert all(deconfigs), deconfigs
    before = json.load(archive.extractfile(prefix + '/host-routes-before.json'))
    after = json.load(archive.extractfile(prefix + '/host-routes-after.json'))
    assert before == after
    manifest.update(packets=counts, udev=udev, deconfig_clean=True, host_routes_unchanged=True)
    summary[prefix] = manifest
assert len(summary) == 4, summary
(root / 'evidence/approved-matrix-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
print(json.dumps(summary, indent=2))
