"""Negative transport scenarios shared by S-HLT-029 and T-HLT-032.

Faults live on a simulated home's FORWARD chain, before established-flow accepts.
They cover transit traffic in both directions and do not affect HTTP or lab control.
"""
import json
import time

from .lab import compose, execute, rpc
from .scenarios import call, end_call, states, wait_for


def reset_clients():
    # Remove saved registration/call state from the running server and SDKs.
    compose('stop', 'terminal-a', 'terminal-b')
    compose('restart', 'server')
    compose('start', 'terminal-a', 'terminal-b')
    return wait_for(states, 'Fresh terminal control endpoints', 60)


def registered():
    return all(status['registered'] for status in states().values())


def flush(router):
    execute(router, 'nft', 'flush', 'chain', 'ip', 'lab', 'faults')


def drops(router):
    data = json.loads(execute(router, 'nft', '-j', 'list', 'chain', 'ip', 'lab', 'faults').stdout)
    packets = sum(expr['counter']['packets'] for item in data['nftables']
                  for expr in item.get('rule', {}).get('expr', []) if 'counter' in expr)
    assert packets > 0, 'The firewall rule did not intercept packets'
    return {'dropped_packets': packets, 'rules': data}


def observe_no_connection(seconds=6):
    samples = []
    deadline = time.monotonic()+seconds
    while time.monotonic() < deadline:
        snapshot = states()
        for status in snapshot.values():
            assert not status['video_active'], snapshot
            assert all(event['state'] not in (7, 8) for event in status['events']), snapshot
        samples.append(snapshot)
        time.sleep(1)
    return samples


def all_udp(peer):
    router = 'router-'+peer
    execute(router, 'nft', 'add', 'rule', 'ip', 'lab', 'faults',
            'meta', 'l4proto', 'udp', 'counter', 'drop')
    try:
        reset_clients()
        other = 'b' if peer == 'a' else 'a'
        wait_for(lambda: rpc(other, 'status')['registered'], 'Unblocked peer registration')
        configuration = {side: rpc(side, 'fetch') for side in ('a', 'b')}
        samples = observe_no_connection(15)
        assert all(not snapshot[peer]['registered'] for snapshot in samples)
        attempts = {}
        for caller in (peer, other):
            rpc(caller, 'dial', peer='b' if caller == 'a' else 'a')
            try:
                # Give the blocked caller longer than the usual 32-second SIP
                # transaction timeout; do not mistake a short setup delay for failure.
                attempts[caller] = observe_no_connection(40 if caller == peer else 6)
            finally:
                end_call()
        return {'blocked_home': peer, 'http_configuration': configuration,
                'registration_samples': samples, 'call_attempts': attempts, 'firewall': drops(router)}
    finally:
        flush(router)


def silent_audio(peer, record):
    source = '''import json,sys,wave,numpy as np
from pathlib import Path
p=Path(sys.argv[1]); result={'file_present':p.exists(),'rms':0.0,'samples':0}
if p.exists() and p.stat().st_size>44:
 with wave.open(str(p),'rb') as w:
  assert w.getsampwidth()==2
  x=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2').astype(float)
  result.update(samples=len(x),rms=float(np.sqrt(np.mean(x*x))) if len(x) else 0.0)
assert result['rms']<100,result
print(json.dumps(result))'''
    return json.loads(execute('terminal-'+peer, 'python3', '-c', source,
                              f'/tmp/received-{record}.wav').stdout)


def media_udp(peer, caller):
    router = 'router-'+peer
    # Match server destination ports outbound and server source ports inbound,
    # before client SNAT / after reverse SNAT. Also block RTCP, not just RTP.
    for field in ('dport', 'sport'):
        execute(router, 'nft', 'add', 'rule', 'ip', 'lab', 'faults',
                'udp', field, '20000-20199', 'counter', 'drop')
    try:
        records = {side: rpc(side, 'record')['record'] for side in ('a', 'b')}
        rpc(caller, 'dial', peer='b' if caller == 'a' else 'a')
        try:
            wait_for(lambda: all(s['state'] == 8 for s in states().values()), 'SIP connects with media blocked')
            samples = []
            for _ in range(6):
                snapshot = states()
                for status in snapshot.values():
                    assert status['state'] == 8 and status['registered'], snapshot
                    assert not status['video_active'], snapshot
                    assert status['media'].get('audio', {}).get('download_kbps', 0) < .01, snapshot
                samples.append(snapshot)
                time.sleep(1)
        finally:
            end_call()
        return {'blocked_home': peer, 'caller': caller, 'samples': samples,
                'recorded_audio': {side: silent_audio(side, record) for side, record in records.items()},
                'firewall': drops(router)}
    finally:
        flush(router)


def exercise(check):
    try:
        for peer in ('a', 'b'):
            flush('router-'+peer)
        reset_clients()
        wait_for(registered, 'Baseline registrations')
        for caller in ('a', 'b'):
            check(f'Baseline {caller.upper()} calls: decoded audio and video', lambda c=caller: call(c))
        for peer in ('a', 'b'):
            check(f'All UDP blocked at home {peer.upper()}: registration and both call directions fail',
                  lambda p=peer: all_udp(p))
            reset_clients()
            wait_for(registered, 'Registration recovers after UDP unblock')
            check(f'Home {peer.upper()} all-UDP unblock: call recovers', lambda p=peer: call(p))
        for peer in ('a', 'b'):
            for caller in ('a', 'b'):
                check(f'Media UDP blocked at home {peer.upper()}, caller {caller.upper()}: SIP connects but audio/video fail',
                      lambda p=peer, c=caller: media_udp(p, c))
            check(f'Home {peer.upper()} media unblock: call recovers', lambda p=peer: call(p))
    finally:
        for peer in ('a', 'b'):
            flush('router-'+peer)
