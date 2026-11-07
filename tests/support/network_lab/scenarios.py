"""Shared requirement-based network exercise and explicitly exploratory fault probes."""
from datetime import datetime, timezone
from html import escape
import json
import time

from .lab import REPORTS, compose, execute, rpc, up


def wait_for(predicate, description, timeout=45):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            value = predicate()
            if value:
                return value
        except Exception as error:
            last = str(error)
        time.sleep(1)
    raise AssertionError(f'{description}: timed out; {last}')


def states():
    return {peer: rpc(peer, 'status') for peer in ('a', 'b')}


def end_call():
    for peer in ('a', 'b'):
        rpc(peer, 'end')
    wait_for(lambda: all(s['state'] == 0 for s in states().values()), 'Call resources released', 20)


def media_ready():
    snapshot = states()
    for status in snapshot.values():
        if status['state'] != 8:
            return False
        media = status['media']
        for kind, minimum in (('audio', 1), ('video', .05)):
            # A static encoded picture can legitimately use far less than 1 kbps.
            # Require decoder frame progress below; bandwidth alone is not proof.
            if min(media.get(kind, {}).get(direction, 0) for direction in ('upload_kbps', 'download_kbps')) <= minimum:
                return False
        if not status['video_active']:
            return False
    return snapshot


def check_audio(peer, record):
    source = '''import json,sys,wave,numpy as np
with wave.open(sys.argv[1],'rb') as w:
 rate=w.getframerate(); channels=w.getnchannels(); width=w.getsampwidth()
 assert width==2,width
 x=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2')[::channels].astype(float)
 assert len(x)>rate, 'Less than one second of decoded audio'
 x=x[-min(len(x),rate*3):]; rms=float(np.sqrt(np.mean(x*x)))
 spectrum=abs(np.fft.rfft(x*np.hanning(len(x))))
 frequency=float(np.argmax(spectrum)*rate/len(x))
 expected=float(sys.argv[2]); assert rms>100, rms
 assert abs(frequency-expected)<15,(frequency,expected)
 print(json.dumps({'received_tone_hz':frequency,'rms':rms,'sample_rate':rate}))'''
    result = execute('terminal-'+peer, 'python3', '-c', source,
                     f'/tmp/received-{record}.wav', '880' if peer == 'a' else '440')
    return json.loads(result.stdout)


def call(caller):
    recordings = {peer: rpc(peer, 'record')['record'] for peer in ('a', 'b')}
    rpc(caller, 'dial', peer='b' if caller == 'a' else 'a')
    try:
        snapshot = wait_for(media_ready, 'Bidirectional decoded audio/video', 40)
        time.sleep(4)
    finally:
        end_call()
    return {'media': snapshot, 'decoded_audio': {peer: check_audio(peer, record) for peer, record in recordings.items()}}


def run(udp_blocked=False):
    # One process owns calls and firewall faults at a time, across both HLT entry points.
    import fcntl
    with open('/tmp/zmala-network-lab.lock', 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another network-lab test is running') from None
        run_locked(udp_blocked)


def run_locked(udp_blocked=False):
    output = REPORTS/'udp-blocked' if udp_blocked else REPORTS
    output.mkdir(parents=True, exist_ok=True)
    report = {'started': datetime.now(timezone.utc).isoformat(), 'plans': ['S-HLT-029', 'T-HLT-032'],
              'scope': 'Actual server and shared terminal Engine, Liblinphone and production H.264 decoder; OpenH264 software encoder and synthetic camera/audio replace Pi hardware. No TV UI.',
              'checks': [], 'status': 'running'}
    def check(name, operation):
        print(name, flush=True)
        try:
            result = operation()
        except Exception as error:
            report['checks'].append({'name': name, 'status': 'failed', 'error': str(error)})
            raise
        report['checks'].append({'name': name, 'status': 'passed', 'evidence': result})
        (output/'results.json').write_text(json.dumps(report, indent=2)+'\n')
        return result
    try:
        up()
        if udp_blocked:
            from .udp_blocked import exercise
            exercise(check)
            report['status'] = 'passed'
            return
        check('Both terminals register through distinct NAT gateways', lambda: wait_for(
            lambda: all(s['registered'] for s in states().values()), 'Registration', 90))
        def translations():
            evidence = {}
            for router, address in (('router-a', '10.231.100.11'), ('router-b', '10.231.100.12')):
                entries = execute(router, 'conntrack', '-L', '-p', 'udp').stdout.splitlines()
                matches = [line for line in entries if 'dport=5060 ' in line and f'dst={address} ' in line]
                assert matches, (router, entries)
                assert any(40000 <= int(line.split('dport=')[-1].split()[0]) <= 49999 for line in matches)
                evidence[router] = matches
            return evidence
        check('SIP source addresses and ports are translated', translations)
        check('Authenticated HTTP configuration through server port forwarding',
              lambda: {peer: rpc(peer, 'fetch') for peer in ('a', 'b')})
        def isolation():
            source = '''import urllib.request
try: urllib.request.urlopen('http://10.231.30.10:8080/health',timeout=2)
except OSError: print('Private server address inaccessible as required')
else: raise SystemExit('Unexpected direct path to private server')'''
            return {peer: execute('terminal-'+peer, 'python3', '-c', source).stdout for peer in ('a', 'b')}
        check('No direct path bypasses server NAT', isolation)
        check('A calls B: H.264 decode and opposite microphone tone', lambda: call('a'))
        check('B calls A: H.264 decode and opposite microphone tone', lambda: call('b'))
        print('Waiting 65 seconds with no call before the next incoming-call check.', flush=True)
        time.sleep(65)
        check('Incoming call after 65 seconds idle', lambda: call('a'))
        def impaired():
            interface = execute('router-a', 'cat', '/run/lab-wan').stdout.strip()
            execute('router-a', 'tc', 'qdisc', 'replace', 'dev', interface, 'root', 'netem',
                    'delay', '80ms', '20ms', 'loss', '1%', 'rate', '3mbit')
            try:
                return call('b')
            finally:
                execute('router-a', 'tc', 'qdisc', 'del', 'dev', interface, 'root')
        check('Call with added delay, jitter, loss and bandwidth limit', impaired)
        def blocked():
            execute('router-a', 'nft', 'add', 'rule', 'ip', 'lab', 'faults',
                    'udp', 'dport', '20000-20199', 'counter', 'drop')
            try:
                rpc('a', 'dial', peer='b')
                wait_for(lambda: all(s['state'] == 8 for s in states().values()), 'Signalling while media blocked')
                time.sleep(7)
                snapshot = states()
                assert all(not s['video_active'] for s in snapshot.values()), snapshot
                return snapshot
            finally:
                end_call()
                execute('router-a', 'nft', 'flush', 'chain', 'ip', 'lab', 'faults')
        check('Blocked media: signalling alone does not prove a working call', blocked)
        check('Next call works after firewall recovery', lambda: call('a'))
        for router in ('router-a', 'router-b', 'router-server'):
            (output/(router+'-nat.txt')).write_text(execute(router, 'nft', 'list', 'table', 'ip', 'lab').stdout)
            (output/(router+'-connections.txt')).write_text(execute(router, 'conntrack', '-L', check=False).stdout)
        report['status'] = 'passed'
    except Exception as error:
        report['status'], report['error'] = 'failed', str(error)
        raise
    finally:
        report['finished'] = datetime.now(timezone.utc).isoformat()
        (output/'results.json').write_text(json.dumps(report, indent=2)+'\n')
        (output/'containers.log').write_text(compose('logs', '--no-color', check=False).stdout)
        rows = ''.join('<tr><td>'+escape(item['name'])+'</td><td>'+item['status']+'</td></tr>'
                       for item in report['checks'])
        (output/'index.html').write_text('''<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ZmalaCall network lab</title><style>body{font:17px system-ui;max-width:1000px;margin:3em auto;padding:0 1em;color:#172c43;background:#f4f7fb}table{border-collapse:collapse;width:100%;background:white}td{padding:1em;border-bottom:1px solid #cdd8e5}pre{white-space:pre-wrap}a{color:#1462a8}</style>
<h1>ZmalaCall · Three-network test</h1><p>'''+escape(report['scope'])+
            '</p><p>'+escape(report['started'])+' · <strong>'+report['status']+
            '</strong></p><table>'+rows+'</table><pre>'+escape(report.get('error', ''))+
            '</pre><p><a href="results.json">Detailed measurements</a> · <a href="containers.log">Container logs</a></p>')
        print('Report:', output/'results.json', flush=True)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--udp-blocked', action='store_true')
    run(udp_blocked=parser.parse_args().udp_blocked)
