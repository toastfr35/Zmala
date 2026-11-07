"""Requirement-based secure transport matrix using actual application policy.

Plan: fetch HTTPS configuration and register with SIP TLS, require SRTP and
TURN relay ICE for audio/video, decode opposite tones and fresh H.264 frames.
Repeat calls both ways with UDP blocked at A, B, and both gateways. Verify
drop counters and restore the lab in finally. Synthetic static cameras need
an explicit keyframe after ICE; this does not qualify moving video or Pi load.
"""
import fcntl
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
os.environ['ZMALA_LAB_TLS'] = '1'
from tests.support.network_lab.lab import REPORTS, execute, rpc, up
from tests.support.network_lab.scenarios import check_audio, end_call, media_ready, wait_for
from tests.support.network_lab.udp_blocked import drops, flush, registered, reset_clients


def call(caller, blocked):
    recordings = {p: rpc(p, 'record')['record'] for p in ('a', 'b')}
    rpc(caller, 'dial', peer='b' if caller == 'a' else 'a')
    last_keyframe = 0
    def ready():
        nonlocal last_keyframe
        snapshot = media_ready()
        if time.monotonic() - last_keyframe > 3:
            for p in ('a', 'b'):
                rpc(p, 'keyframe')
            last_keyframe = time.monotonic()
        return snapshot
    try:
        snapshot = wait_for(ready, 'Decoded TLS relay media', 60)
        for s in snapshot.values():
            assert s['security'] == {'media_encryption': 1, 'audio_ice_state': 5, 'video_ice_state': 5}, s
        # Do not count a transient first frame as a successful sustained call.
        for _ in range(5):
            time.sleep(3)
            snapshot = wait_for(ready, 'Sustained decoded relay media', 10)
        sockets = execute('turn', 'ss', '-tn').stdout
        for p in blocked:
            assert ('10.231.100.11:' if p == 'a' else '10.231.100.12:') in sockets, sockets
            drops('router-'+p)
    finally:
        end_call()
    return {'media': snapshot, 'turn_connections': sockets,
            'audio': {p: check_audio(p, n) for p, n in recordings.items()}}


def certificate_probe():
    # Separate endpoint probes complement the native SIP trust rejection below.
    probe = '''import ssl,socket,json
results=[]
for address in ('10.231.100.13','10.231.100.14','10.231.100.15'):
 for trusted in (True,False):
  context=ssl.create_default_context(cafile='/lab/ca.pem' if trusted else '/etc/ssl/certs/ca-certificates.crt')
  try:
   with socket.create_connection((address,443),timeout=5) as raw:
    with context.wrap_socket(raw,server_hostname=address): pass
  except ssl.SSLCertVerificationError:
   assert not trusted
  else:
   assert trusted, 'Untrusted certificate was accepted'
  results.append({'address':address,'trusted':trusted,'expected_result':True})
print(json.dumps(results))'''
    return json.loads(execute('terminal-a', 'python3', '-c', probe).stdout)


def native_trust_probe():
    execute('terminal-a', 'python3', '-c',
            "from pathlib import Path; p=Path('/etc/hosts'); s=p.read_text(); "
            "p.write_text(s if 'wrong.lab' in s else s+'\\n10.231.100.13 wrong.lab\\n')")
    results = []
    for failure in ('ca', 'name'):
        result = execute('terminal-a', 'env',
                         'LD_PRELOAD=/app/zmala_terminal/linux/turn-runtime/turn-fix.so',
                         'xvfb-run', '-a', 'python3', '/app/tests/support/network_lab/trust_probe.py',
                         'a', failure, timeout=30)
        evidence = [line.removeprefix('ZMALA_TRUST_RESULT=') for line in result.stdout.splitlines()
                    if line.startswith('ZMALA_TRUST_RESULT=')]
        assert len(evidence) == 1, 'Native trust probe did not return one result'
        results.append(json.loads(evidence[0]))
    return results


def main():
    output = REPORTS/'tls'
    output.mkdir(parents=True, exist_ok=True)
    report = {'scope': __doc__, 'status': 'running', 'checks': []}
    with open('/tmp/zmala-network-lab.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        (output/'results.json').write_text(json.dumps(report, indent=2)+'\n')
        try:
            up()
            report['parser'] = json.loads(execute('turn', 'cat', '/app/zmala_terminal/linux/turn-runtime/parser-results.json').stdout)
            reset_clients()
            wait_for(registered, 'Initial TLS registration', 60)
            report['checks'].append({'name': 'Endpoint certificate validation probes',
                                     'evidence': certificate_probe()})
            report['checks'].append({'name': 'Native SIP certificate rejection',
                                     'evidence': native_trust_probe()})
            for blocked in (('a', 'b'), ('a',), ('b',), ()):
                for p in ('a', 'b'):
                    flush('router-'+p)
                for p in blocked:
                    execute('router-'+p, 'nft', 'add', 'rule', 'ip', 'lab', 'faults',
                            'meta', 'l4proto', 'udp', 'counter', 'drop')
                reset_clients()
                wait_for(registered, 'TLS registration', 60)
                for p in ('a', 'b'):
                    assert rpc(p, 'fetch')['device_id'] == p
                for caller in ('a', 'b'):
                    name = f'UDP blocked {blocked}; caller {caller}'
                    print(name, flush=True)
                    report['checks'].append({'name': name, 'evidence': call(caller, blocked)})
                    (output/'results.json').write_text(json.dumps(report, indent=2))
                for p in blocked:
                    report['checks'].append({'name': 'Firewall '+p, 'evidence': drops('router-'+p)})
            report['status'] = 'passed'
        except Exception as error:
            report.update(status='failed', error=str(error))
            raise
        finally:
            try:
                for p in ('a', 'b'):
                    flush('router-'+p)
            except Exception as error:
                report.update(status='failed', cleanup_error=str(error))
                raise
            finally:
                (output/'results.json').write_text(json.dumps(report, indent=2)+'\n')
    print('TLS relay matrix passed', flush=True)


if __name__ == '__main__':
    main()
