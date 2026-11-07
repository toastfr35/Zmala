"""Container startup; network changes apply only to this container's namespace."""
import json
import os
from pathlib import Path
import subprocess
import sys


def interface(address):
    for link in json.loads(subprocess.check_output(['ip', '-j', 'addr'], text=True)):
        if any(info['local'] == address for info in link.get('addr_info', [])):
            return link['ifname']
    raise RuntimeError('Missing lab interface: ' + address)


def router(lan, wan, server=False):
    inside, outside = interface(lan), interface(wan)
    # Each gateway performs its own translation. Docker's bridge is never the endpoint gateway.
    forward = 'ip daddr 10.231.30.10 accept' if server else f'iifname "{inside}" accept'
    dnat = '''ip daddr 10.231.100.13 tcp dport 8080 counter dnat to 10.231.30.10
        ip daddr 10.231.100.13 udp dport { 5060, 20000-20199 } counter dnat to 10.231.30.10''' if server else ''
    if server and os.environ.get('ZMALA_LAB_TLS') == '1':
        subprocess.run(['ip', 'addr', 'add', '10.231.100.15/24', 'dev', outside], check=True)
        dnat += '''
        ip daddr 10.231.100.13 tcp dport 443 counter dnat to 10.231.30.10:5061
        ip daddr 10.231.100.15 tcp dport 443 counter dnat to 10.231.30.10:443'''
    rules = f'''table ip lab {{
      chain prerouting {{ type nat hook prerouting priority dstnat; policy accept;
        {dnat}
      }}
      chain postrouting {{ type nat hook postrouting priority srcnat; policy accept;
        oifname "{outside}" meta l4proto udp counter snat to {wan}:40000-49999
        oifname "{outside}" counter snat to {wan}
      }}
      chain faults {{ }}
      chain forward {{ type filter hook forward priority filter; policy drop;
        jump faults
        ct state established,related counter accept
        {forward}
      }}
    }}'''
    subprocess.run(['nft', '-f', '-'], input=rules, text=True, check=True)
    Path('/run/lab-wan').write_text(outside)
    print('Router ready', lan, wan, flush=True)
    os.execvp('sleep', ['sleep', 'infinity'])


def main():
    role, *args = sys.argv[1:]
    if role == 'router':
        router(args[0], args[1], len(args) > 2)
    elif role == 'seed':
        if os.environ.get('ZMALA_LAB_TLS') == '1':
            from tls_seed import seed
            seed()
        os.execvp('node', ['node', '/app/tests/support/network_lab/seed.cjs'])
    elif role == 'turn':
        # Model an Internet host with a default route. Private ICE candidates
        # are dropped by Docker isolation, not rejected locally with ENETUNREACH.
        subprocess.run(['ip', 'route', 'replace', 'default', 'via', '10.231.100.1'], check=True)
        os.execvp('turnserver', ['turnserver', '-c', '/lab/turn.conf'])
    else:
        subprocess.run(['ip', 'route', 'replace', 'default', 'via', args[0]], check=True)
        if role == 'server':
            import shutil
            shutil.copytree('/lab/server', '/app/zmala_server/data', dirs_exist_ok=True)
            os.environ['VIDEOCALL_HOST'] = '10.231.100.13'
            script = '/app/zmala_server/main.js'
            os.execvp('node', ['node', script])
        elif role == 'terminal':
            if os.environ.get('ZMALA_LAB_TLS') == '1':
                os.environ['LD_PRELOAD'] = '/app/zmala_terminal/linux/turn-runtime/turn-fix.so'
            os.execvp('xvfb-run', ['xvfb-run', '-a', 'python3', '/app/tests/support/network_lab/terminal.py', args[1]])
        else:
            raise ValueError('Unknown lab role')


if __name__ == '__main__':
    main()
