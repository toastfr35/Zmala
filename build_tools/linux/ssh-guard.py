"""Restrict SSH ingress to the configured physical Ethernet interface, IPv4/6.

Only our own nftables table is replaced. Keep the include in nftables.conf so
an administrator's normal firewall reload also preserves this restriction.
"""
import os
from pathlib import Path
import re
import subprocess



def rules(interface, ports):
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,15}', interface):
        raise ValueError('Invalid Ethernet interface')
    ports = sorted(set(int(port) for port in ports) | {22})  # also ssh.socket
    if any(not 1 <= port <= 65535 for port in ports):
        raise ValueError('Invalid SSH port')
    return ('add table inet zmala_ssh\ndelete table inet zmala_ssh\n'
            'table inet zmala_ssh {\n chain ingress {\n'
            '  type filter hook input priority -10; policy accept;\n'
            f'  iifname != "{interface}" tcp dport {{ ' + ', '.join(map(str, ports)) +
            ' } counter drop\n }\n}\n')


def main():
    interface = Path('/etc/zmalacall/ssh-interface').read_text().strip()
    # sshd -T validates its privilege-separation directory even when the
    # daemon has not started yet. SSH's RuntimeDirectory does not exist then.
    Path('/run/sshd').mkdir(mode=0o755, exist_ok=True)
    result = subprocess.run(['/usr/sbin/sshd', '-T'], capture_output=True, text=True, check=True)
    ports = re.findall(r'^port (\d+)$', result.stdout, re.M)
    if not ports:
        raise RuntimeError('Cannot determine SSH ports')
    content = rules(interface, ports)
    subprocess.run(['/usr/sbin/nft', '-c', '-f', '-'], input=content, text=True, check=True)
    subprocess.run(['/usr/sbin/nft', '-f', '-'], input=content, text=True, check=True)
    path = Path('/etc/nftables.d/zmala-ssh.nft')
    temp = path.with_suffix('.tmp')
    temp.write_text(content)
    os.replace(temp, path)


if __name__ == '__main__':
    main()
