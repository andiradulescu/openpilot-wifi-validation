import os,sys,time,subprocess,json,signal,shutil,hashlib
from pathlib import Path
root=Path(sys.argv[1]).resolve()
trial=sys.argv[2]; mode=sys.argv[3]; announce=0
candidate=Path(sys.argv[4]).resolve()
p=root/trial; p.mkdir()
dut='c4-'+trial+'d'; lan='c4-'+trial+'l'
procs=[]; files=[]; created=[]
log=(p/'commands.jsonl').open('w',buffering=1)
def run(args,check=True,ns=None,env=None,timeout=15):
    cmd=(['ip','netns','exec',ns] if ns else [])+list(args)
    t=time.time()
    cp=subprocess.run(cmd,text=True,capture_output=True,env=env,timeout=timeout)
    log.write(json.dumps(dict(time=t,cmd=cmd,rc=cp.returncode,stdout=cp.stdout,stderr=cp.stderr))+'\n')
    if check and cp.returncode: raise RuntimeError(f'{cmd}: {cp.returncode}: {cp.stderr}')
    return cp
def spawn(args,name,ns=None,env=None):
    cmd=(['ip','netns','exec',ns] if ns else [])+list(args)
    f=(p/name).open('w'); files.append(f)
    pr=subprocess.Popen(cmd,stdout=f,stderr=subprocess.STDOUT,text=True,env=env,start_new_session=True)
    procs.append(pr);log.write(json.dumps(dict(time=time.time(),spawn=cmd,pid=pr.pid))+'\n')
    return pr
def stamp(label):
    print(label, time.time(),flush=True)
    log.write(json.dumps(dict(time=time.time(),label=label))+'\n')
def snapshot(label):
    stamp(label)
    result={}
    for name,args in [('routes',['ip','-4','route','show']),('address',['ip','-4','-o','addr']),('lookup',['ip','-4','route','get','192.168.1.171','from','192.168.1.199'])]:
        result[name]=run(args,ns=dut).stdout
    (p/(label+'.json')).write_text(json.dumps(result,indent=2))
    print(json.dumps(result),flush=True)
    return result
try:
    resolver_before=hashlib.sha256(Path('/etc/resolv.conf').read_bytes()).hexdigest()
    before=run(['ip','-j','-4','route','show']).stdout;(p/'host-routes-before.json').write_text(before)
    for n in (dut,lan):
        run(['ip','netns','add',n]);created.append(n)
        run(['ip','link','set','lo','up'],ns=n)
    run(['ip','link','add','br0','type','bridge'],ns=lan)
    run(['ip','link','set','br0','address','02:11:22:33:44:ff'],ns=lan)
    run(['ip','link','set','br0','up'],ns=lan)
    run(['ip','addr','add','192.168.1.1/24','dev','br0'],ns=lan)
    run(['ip','addr','add','192.168.1.171/24','dev','br0'],ns=lan)
    for short,iface,mac in [('e','eth0','02:11:22:33:44:01'),('w','wlan0','02:11:22:33:44:02')]:
        a='c4'+trial+short;b=a+'p'
        run(['ip','link','add',a,'type','veth','peer','name',b])
        run(['udevadm','settle','--timeout=5'])
        shutil.copytree('/run/udev/data',p/'udev-data',dirs_exist_ok=True)
        run(['ip','link','set',a,'netns',dut]);run(['ip','link','set',b,'netns',lan])
        run(['ip','link','set',a,'name',iface],ns=dut)
        run(['ip','link','set',iface,'address',mac],ns=dut)
        run(['ip','link','set',b,'master','br0'],ns=lan);run(['ip','link','set',b,'up'],ns=lan)
    for d in ['etcNM/system-connections','varlib','empty','bin']: (p/d).mkdir(parents=True,exist_ok=True)
    (p/'nm.conf').write_text('[main]\nplugins=keyfile\ndhcp=internal\ndns=none\nrc-manager=unmanaged\nauth-polkit=false\nno-auto-default=*\n[device-wlan]\nmatch-device=interface-name:wlan0\nmanaged=0\n')
    (p/'bin/logger').write_text('#!/bin/sh\nprintf "%s %s\\n" "$(date +%s.%N)" "$*" >> "'+str(p/'hook-syslog.log')+'"\n')
    (p/'bin/resolvconf').write_text('#!/bin/sh\necho \"$@\" >> \"'+str(p/'hook-dns.log')+'\"\ncat >> "'+str(p/'hook-dns.log')+'"\n')
    for f in (p/'bin').iterdir():f.chmod(0o755)
    for src,name in [('/etc/udhcpc/default.script','default.script'),(str(candidate),'udhcpc.script')]:
        shutil.copyfile(src,p/name);(p/name).chmod(0o755)
    spawn(['tcpdump','-U','-n','-i','br0','-w',str(p/'arp.pcap'),'arp or udp port 9999'],'tcpdump.log',ns=lan)
    spawn(['ip','-ts','monitor','route','address','link'],'route-monitor.log',ns=dut)
    spawn(['dnsmasq','--keep-in-foreground','--conf-file=/dev/null','--port=0','--interface=br0','--bind-interfaces','--dhcp-authoritative',
           '--dhcp-range=192.168.1.100,192.168.1.220,255.255.255.0,1h','--dhcp-host=02:11:22:33:44:01,192.168.1.199',
           '--dhcp-leasefile='+str(p/'leases'),'--log-dhcp','--log-facility=-'],'dhcp-server.log',ns=lan)
    env=os.environ.copy()
    if mode == 'nm':
        bus='unix:path='+str(p/'bus.sock')
        setup=f'''set -eu
    mount -t tmpfs tmpfs /run
    mkdir -p /run/udev/data
    mount --bind {p}/udev-data /run/udev/data
    mount -o remount,bind,ro /run/udev/data
    mount --bind {p}/etcNM /etc/NetworkManager
    mount --bind {p}/varlib /var/lib/NetworkManager
    mount --bind {p}/empty /etc/netplan
    dbus-daemon --system --nofork --nopidfile --address={bus} > {p}/dbus.log 2>&1 &
    export DBUS_SYSTEM_BUS_ADDRESS={bus}
    exec strace -f -ttt -s 512 -e trace=sendmsg,recvmsg,ioctl -o {p}/nm.strace NetworkManager --no-daemon --debug --config={p}/nm.conf --config-dir={p}/empty --system-config-dir={p}/empty --pid-file={p}/nm.pid --log-level=TRACE --log-domains=PLATFORM,IP4,DEVICE,DHCP4,CORE
    '''
        (p/'nm-start.sh').write_text(setup)
        nm=spawn(['unshare','-m','--propagation','private','bash',str(p/'nm-start.sh')],'nm.log',ns=dut)
        env=os.environ.copy();env['DBUS_SYSTEM_BUS_ADDRESS']=bus
        for i in range(50):
            cp=run(['nmcli','-t','-f','RUNNING','general'],check=False,ns=dut,env=env,timeout=3)
            if cp.returncode==0 and cp.stdout.strip()=='running':break
            if nm.poll() is not None:raise RuntimeError('private NM exited; inspect nm.log')
            if action != 'deconfig':
                run(['python3','-c',"import socket;s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.setsockopt(socket.SOL_SOCKET,socket.SO_BINDTODEVICE,b'wlan0\\0');s.bind(('192.168.1.108',0));s.sendto(b'wlanprobe',('192.168.1.171',9999))"],ns=dut)
            time.sleep(.1)
        else:raise RuntimeError('private NM readiness failed')
        run(['nmcli','-f','GENERAL','device','show'],ns=dut,env=env)
        run(['nmcli','connection','add','type','ethernet','ifname','eth0','con-name','wired-test','ipv4.method','auto','ipv4.route-metric','100','ipv6.method','disabled','connection.autoconnect','no'],ns=dut,env=env)
        run(['nmcli','--wait','10','connection','up','wired-test'],ns=dut,env=env)
    else:
        run(['ip','link','set','eth0','up'],ns=dut)
        run(['ip','addr','add','192.168.1.199/24','dev','eth0','noprefixroute'],ns=dut)
        run(['ip','route','add','192.168.1.0/24','dev','eth0','src','192.168.1.199','metric','100'],ns=dut)
        run(['ip','route','add','default','via','192.168.1.1','dev','eth0','metric','100'],ns=dut)
    snapshot('wired-baseline')
    run(['ip','link','set','wlan0','up'],ns=dut)
    run(['sysctl','-w',f'net.ipv4.conf.wlan0.arp_announce={announce}'],ns=dut)
    run(['ip','addr','add','192.168.43.1/24','dev','wlan0'],ns=dut)
    snapshot('ap-address-baseline')
    traffic='''import socket,time
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.bind(('192.168.1.199',0))
end=time.monotonic()+20;n=0;errors=0
while time.monotonic()<end:
 try:s.sendto(b'routeprobe',('192.168.1.171',9999));n+=1
 except OSError:errors+=1
 time.sleep(.002)
print('sent',n,'errors',errors,flush=True)
'''
    (p/'traffic.py').write_text(traffic)
    sender=spawn(['python3',str(p/'traffic.py')],'traffic.log',ns=dut)
    henv=os.environ.copy();henv.update(PATH=str(p/'bin')+':'+henv['PATH'],UDHCPC_DEFAULT_SCRIPT=str(p/'default.script'),interface='wlan0',ip='192.168.1.108',subnet='255.255.255.0',router='192.168.1.1',mtu='1400',broadcast='192.168.1.255',dns='192.168.1.1',lease='43200',domain='lab')
    (p/'resolv.conf').write_text('')
    (p/'absent').write_text('')
    (p/'absent').chmod(0o644)
    resolver_target=str(Path('/etc/resolv.conf').resolve())
    (p/'hook-isolate.sh').write_text(f'#!/bin/sh\nset -eu\nif [ \"{mode}\" = no-nm ]; then\n mount -t tmpfs tmpfs /run\n mount --bind {p}/absent /usr/bin/nmcli\n mount --bind {p}/absent /usr/sbin/NetworkManager\n test ! -x /usr/bin/nmcli\n test ! -x /usr/sbin/NetworkManager\n test ! -S /run/dbus/system_bus_socket\nfi\nif [ \"${{DNS_FALLBACK:-0}}\" = 1 ]; then\n mount --bind {p}/absent /usr/bin/resolvectl\nfi\nif [ ! -e {resolver_target} ]; then\n mkdir -p $(dirname {resolver_target})\n touch {resolver_target}\nfi\nmount --bind {p}/resolv.conf {resolver_target}\nexec {p}/udhcpc.script "$1"\n')
    hook=['unshare','-m','--propagation','private','sh',str(p/'hook-isolate.sh')]
    outcomes=[]
    for i in range(10):
        for action in ('deconfig','bound','renew'):
            stamp('cycle-'+str(i)+'-'+action)
            run(hook+[action],ns=dut,env=henv)
            if action == 'deconfig':
                assert json.loads(run(['ip','-j','-4','route','show','dev','wlan0'],ns=dut).stdout)==[]
                assert all(not row['addr_info'] for row in json.loads(run(['ip','-j','-4','addr','show','dev','wlan0'],ns=dut).stdout))
            if action == 'bound':
                run(['ip','route','replace','203.0.113.0/24','dev','wlan0'],ns=dut)
            if action != 'deconfig':
                routes=json.loads(run(['ip','-j','-4','route','show','dev','wlan0'],ns=dut).stdout)
                assert len([r for r in routes if r.get('dst')=='192.168.1.0/24' and r.get('metric')==600])==1, routes
                assert len([r for r in routes if r.get('dst')=='default' and r.get('metric')==600])==1, routes
                assert any(r.get('dst')=='203.0.113.0/24' for r in routes), routes
            if action != 'deconfig':
                run(['python3','-c',"import socket;s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.setsockopt(socket.SOL_SOCKET,socket.SO_BINDTODEVICE,b'wlan0\\0');s.bind(('192.168.1.108',0));s.sendto(b'wlanprobe',('192.168.1.171',9999))"],ns=dut)
            time.sleep(.1)
            r=snapshot('cycle-'+str(i)+'-'+action+'-after')
            outcomes.append('dev eth0' not in r['lookup'])
    run(['ip','addr','add','10.9.0.1/24','dev','br0'],ns=lan)
    edges=[]
    for label,updates in [('host-route',dict(ip='192.168.1.109',subnet='255.255.255.255',broadcast='192.168.1.109')),
                          ('renumber',dict(ip='192.168.1.110',subnet='255.255.255.0',broadcast='192.168.1.255')),
                          ('new-subnet',dict(ip='10.9.0.110',subnet='255.255.255.0',broadcast='10.9.0.255',router='10.9.0.1')),
                          ('no-router',dict(router='')),
                          ('file-dns',dict(DNS_FALLBACK='1',dns='192.168.1.9',domain='fallback'))]:
        henv.update(updates)
        run(hook+['renew'],ns=dut,env=henv)
        rows=json.loads(run(['ip','-j','-4','route','show','dev','wlan0'],ns=dut).stdout)
        addresses=json.loads(run(['ip','-j','-4','addr','show','dev','wlan0'],ns=dut).stdout)[0]
        assert addresses['mtu']==1400 and len(addresses['addr_info'])==1,addresses
        assert addresses['addr_info'][0]['local']==henv['ip'],addresses
        defaults=[r for r in rows if r.get('dst')=='default']
        assert len(defaults)==bool(henv['router']),rows
        if henv['subnet']=='255.255.255.255':
            assert not any(r.get('dst')=='192.168.1.0/24' for r in rows),rows
            assert defaults[0]['metric']==600 and 'onlink' in defaults[0].get('flags',[]),rows
        else:
            assert len([r for r in rows if r.get('dst')==('10.9.0.0/24' if henv['ip'].startswith('10.9.') else '192.168.1.0/24') and r.get('prefsrc')==henv['ip'] and r.get('metric')==600])==1,rows
        if label=='file-dns':assert (p/'resolv.conf').read_text()=='domain fallback\nnameserver 192.168.1.9\n'
        snapshot(label)
        edges.append(label)
    routes=run(['ip','-4','route','show'],ns=dut).stdout
    for action in ('nak','leasefail'):
        run(hook+[action],ns=dut,env=henv)
        assert run(['ip','-4','route','show'],ns=dut).stdout==routes
    run(hook+['deconfig'],ns=dut,env=henv)
    assert json.loads(run(['ip','-j','-4','route','show','dev','wlan0'],ns=dut).stdout)==[]
    sender.terminate();sender.wait(timeout=3)
    time.sleep(.2)
    snapshot('final')
    if mode=='nm':
        run(['nmcli','-f','GENERAL.STATE,IP4.ADDRESS,IP4.ROUTE','device','show','eth0'],ns=dut,env=env)
        assert 'unmanaged' in run(['nmcli','-g','GENERAL.STATE','device','show','wlan0'],ns=dut,env=env).stdout
    monitor=(p/'route-monitor.log').read_text().splitlines()
    wlan_events=[line for line in monitor if 'dev wlan0' in line and (('proto kernel scope link' in line and '192.168.43.0/24' not in line) or 'default via' in line) and 'Deleted' not in line and 'table local' not in line]
    bad_metrics=[line for line in wlan_events if 'metric 600' not in line]
    deleted=[line for line in monitor if 'Deleted' in line and '192.168.1.0/24 dev eth0' in line]
    dns=(p/'hook-dns.log').read_text()
    assert 'nameserver 192.168.1.1' in dns and 'domain lab' in dns and '-d wlan0.udhcpc' in dns, dns
    result=dict(mode=mode,announce=announce,cycles=10,lookups=len(outcomes),edge_cases=edges,route_loss=any(outcomes),wlan_events=len(wlan_events),bad_metrics=bad_metrics,eth_deletions=deleted,
                coverage_limit='NM package absence simulated with non-executable bind masks, isolated /run, no NM service' if mode=='no-nm' else 'real NM owns DHCP Ethernet, WLAN unmanaged')
    (p/'result.json').write_text(json.dumps(result,indent=2))
    print('RESULT',json.dumps(result),flush=True)
    assert wlan_events and not bad_metrics, result
    assert not any(outcomes) and not deleted, result
finally:
    for n in created:
        ids=run(['ip','netns','pids',n],check=False).stdout.split()
        for pid in ids:
            try:os.kill(int(pid),signal.SIGTERM)
            except ProcessLookupError:pass
    time.sleep(.3)
    for n in created:
        ids=run(['ip','netns','pids',n],check=False).stdout.split()
        for pid in ids:
            try:os.kill(int(pid),signal.SIGKILL)
            except ProcessLookupError:pass
    for pr in procs:
        try:pr.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(pr.pid,signal.SIGKILL);pr.wait()
    for n in reversed(created):run(['ip','netns','del',n],check=False)
    for f in files:f.close()
    after=run(['ip','-j','-4','route','show']).stdout;(p/'host-routes-after.json').write_text(after)
    print('CLEANUP host_routes_unchanged',json.loads(before)==json.loads(after),flush=True)
    print('CLEANUP host_resolver_unchanged',resolver_before==hashlib.sha256(Path('/etc/resolv.conf').read_bytes()).hexdigest(),flush=True)
    print('NAMESPACES',run(['ip','netns','list']).stdout,flush=True)
    log.close()
