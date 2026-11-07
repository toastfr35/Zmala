#!/usr/bin/python3
"""Restrict ordinary server SSH to directly connected wired subnets, IPv4/IPv6."""
import ipaddress
import json
from pathlib import Path
import re
import subprocess



def rules(interface, addresses, ports):
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,15}', interface):
        raise ValueError('Invalid interface')
    ports = sorted({22, *(int(p) for p in ports)})
    if any(not 1 <= p <= 65535 or p == 2222 for p in ports):
        raise ValueError('Tunnel port must be separate from developer SSH')
    match = 'tcp dport { ' + ', '.join(map(str, ports)) + ' }'
    lines = ['add table inet zmala_developer_lan', 'delete table inet zmala_developer_lan',
             'table inet zmala_developer_lan { chain ingress {',
             'type filter hook input priority -11; policy accept;']
    # No broad established-connection exception: a non-local existing login must
    # not survive tightening this policy. Other ports, including 2222, are untouched.
    for address in addresses:
        network = ipaddress.ip_network(f"{address['local']}/{address['prefixlen']}", strict=False)
        if network.is_loopback or network.is_multicast or network.prefixlen == 0:
            continue
        family = 'ip' if network.version == 4 else 'ip6'
        lines.append(f'iifname "{interface}" {family} saddr {network} {match} accept')
    lines += [match + ' counter drop', '}', '}']
    return '\n'.join(lines) + '\n'


def main():
    interface = Path('/etc/zmalacall/ssh-interface').read_text().strip()
    addresses = json.loads(subprocess.check_output(['ip', '-j', 'address', 'show', 'dev', interface], text=True))[0]['addr_info']
    output = subprocess.check_output(['/usr/sbin/sshd', '-T'], text=True)
    content = rules(interface, addresses, re.findall(r'^port (\d+)$', output, re.M))
    for arguments in (['nft', '-c', '-f', '-'], ['nft', '-f', '-']):
        subprocess.run(arguments, input=content, text=True, check=True, timeout=10)
    Path('/etc/nftables.d/zmala-developer-lan.nft').write_text(content)


if __name__ == '__main__':
    main()
