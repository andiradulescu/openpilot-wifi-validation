import io,json,struct,tarfile
from pathlib import Path
root=Path('/Users/andiradulescu/Projects/firstmate/data/wifi-route-priority')
summary={}
with tarfile.open(root/'evidence/first-matrix.tar.gz') as archive:
  for trial in ('red-no-nm','red-nm','green-no-nm','green-nm'):
    result=json.load(archive.extractfile(f'{trial}/result.json'))
    pcap=io.BytesIO(archive.extractfile(f'{trial}/arp.pcap').read())
    magic=pcap.read(4)
    endian={b'\xd4\xc3\xb2\xa1':'<',b'\xa1\xb2\xc3\xd4':'>'}[magic]
    pcap.read(20)
    counts=dict(wired_udp=0,wlan_wired_udp=0,wlan_wired_arp=0,wlan_arp=0)
    while header:=pcap.read(16):
      _,_,length,_=struct.unpack(endian+'IIII',header)
      frame=pcap.read(length)
      if len(frame)<42:continue
      wlan=frame[6:12]==bytes.fromhex('021122334402')
      if frame[12:14]==b'\x08\x00' and frame[23]==17 and frame[26:30]==bytes([192,168,1,199]):
        offset=14+(frame[14]&15)*4
        if int.from_bytes(frame[offset+2:offset+4],'big')==9999:
          counts['wlan_wired_udp' if wlan else 'wired_udp']+=1
      if frame[12:14]==b'\x08\x06' and wlan:
        counts['wlan_arp']+=1
        if frame[28:32]==bytes([192,168,1,199]):counts['wlan_wired_arp']+=1
    result['packets']=counts
    result['tcpdump']=archive.extractfile(f'{trial}/tcpdump.log').read().decode()
    deconfigs=[]
    for cycle in range(10):
      snap=json.load(archive.extractfile(f'{trial}/cycle-{cycle}-deconfig-after.json'))
      deconfigs.append(not any('wlan0' in line for line in snap['routes'].splitlines()) and not any('wlan0' in line for line in snap['address'].splitlines()))
    result['deconfig_clean']=all(deconfigs)
    if trial.startswith('green'):
      assert result['deconfig_clean'] and counts['wired_udp']>0 and counts['wlan_wired_udp']==0 and counts['wlan_wired_arp']==0, result
      assert not result['bad_metrics'] and not result['eth_deletions'] and not result['route_loss'], result
    summary[trial]=result
(root/'evidence/matrix-summary.json').write_text(json.dumps(summary,indent=2))
print(json.dumps({trial:{k:v for k,v in row.items() if k not in ('bad_metrics','tcpdump','eth_deletions')} for trial,row in summary.items()},indent=2))
