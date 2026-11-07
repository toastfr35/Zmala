"""Root-only nftables integration in isolated network namespaces, never the host.

Run: sudo python3 -m unittest tests.server.HLT.test_ssh_guard_linux
"""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('guard', ROOT / 'build_tools/linux/ssh-guard.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


@unittest.skipUnless(sys.platform == 'linux' and os.geteuid() == 0 if hasattr(os, 'geteuid') else False,
                     'requires Linux root and network namespaces')
class GuardScenario(unittest.TestCase):
    developer_subnets = False

    def test_real_tcp_ingress_ipv4_ipv6_and_repeat_install(self):
        ip, nft = shutil.which('ip'), shutil.which('nft')
        if not ip or not nft:
            self.skipTest('iproute2 and nftables required')
        prefix = 'ztest' + str(os.getpid())
        server_ns, client_ns = prefix + 's', prefix + 'c'
        created, process = [], None
        def run(*args, **kwargs):
            return subprocess.run(args, check=True, capture_output=True, text=True, timeout=10, **kwargs)
        try:
            for ns in (server_ns, client_ns):
                run(ip, 'netns', 'add', ns)
                created.append(ns)
                run(ip, '-n', ns, 'link', 'set', 'lo', 'up')
            for index, name, subnet in [(1, 'eth0', '192.0.2'), (2, 'wlan0', '198.51.100')]:
                left, right = prefix + str(index) + 'a', prefix + str(index) + 'b'
                run(ip, 'link', 'add', left, 'netns', server_ns, 'type', 'veth', 'peer', 'name', right, 'netns', client_ns)
                for ns, interface, host in [(server_ns, left, 1), (client_ns, right, 2)]:
                    run(ip, '-n', ns, 'link', 'set', interface, 'name', name)
                    run(ip, '-n', ns, 'addr', 'add', f'{subnet}.{host}/24', 'dev', name)
                    run(ip, '-n', ns, '-6', 'addr', 'add', f'fd00:{index}::{host}/64', 'dev', name, 'nodad')
                    run(ip, '-n', ns, 'link', 'set', name, 'up')
            if self.developer_subnets:
                from tests.support.developer_access import module
                policy = module('developer-lan-guard').rules('eth0', [
                    {'local': '192.0.2.1', 'prefixlen': 24},
                    {'local': 'fd00:1::1', 'prefixlen': 64}], [22])
                # Non-local source addresses arriving on the correct physical
                # interface must still be rejected. No host firewall is touched.
                run(ip, '-n', client_ns, 'addr', 'add', '203.0.113.2/24', 'dev', 'eth0')
                run(ip, '-n', client_ns, '-6', 'addr', 'add', 'fd00:3::2/64', 'dev', 'eth0', 'nodad')
                run(ip, '-n', server_ns, 'route', 'add', '203.0.113.0/24', 'dev', 'eth0')
                run(ip, '-n', server_ns, '-6', 'route', 'add', 'fd00:3::/64', 'dev', 'eth0')
            else:
                policy = guard.rules('eth0', [2222])
            for _ in range(2):
                run(ip, 'netns', 'exec', server_ns, nft, '-f', '-', input=policy)
            server = '''import socket,select
sockets=[]
for family,host in [(socket.AF_INET,'0.0.0.0'),(socket.AF_INET6,'::')]:
 for port in (22,2222,8080):
  s=socket.socket(family)
  if family==socket.AF_INET6:s.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,1)
  s.bind((host,port));s.listen(10);sockets.append(s)
while True:
 for s in select.select(sockets,[],[])[0]:
  c,a=s.accept();c.sendall(b'OK');c.close()
'''
            process = subprocess.Popen([ip, 'netns', 'exec', server_ns, sys.executable, '-c', server])
            time.sleep(.3)
            self.assertIsNone(process.poll())
            client = '''import socket,sys
try:
 source=(sys.argv[3],0) if len(sys.argv)>3 else None
 s=socket.create_connection((sys.argv[1],int(sys.argv[2])),.6,source_address=source)
 assert s.recv(2)==b'OK'
except (OSError,AssertionError):sys.exit(3)
'''
            for host, wired in [('192.0.2.1', True), ('fd00:1::1', True),
                                ('198.51.100.1', False), ('fd00:2::1', False)]:
                for port in (22, 2222, 8080):
                    result = subprocess.run([ip, 'netns', 'exec', client_ns, sys.executable, '-c', client, host, str(port)], timeout=3)
                    public = port == 8080 or self.developer_subnets and port == 2222
                    self.assertEqual(result.returncode, 0 if wired or public else 3, (host, port))
            if self.developer_subnets:
                for host, source in [('192.0.2.1', '203.0.113.2'), ('fd00:1::1', 'fd00:3::2')]:
                    for port in (22, 2222, 8080):
                        result = subprocess.run([ip, 'netns', 'exec', client_ns, sys.executable,
                            '-c', client, host, str(port), source], timeout=3)
                        self.assertEqual(result.returncode, 3 if port == 22 else 0, ('routed-source', source, port))
            # Linux accepts packets addressed to another interface locally. Force
            # the client route for the Ethernet address through the Wi-Fi veth.
            # This catches a ListenAddress-only restriction which is not ingress isolation.
            run(ip, 'netns', 'exec', server_ns, 'sysctl', '-qw', 'net.ipv4.conf.all.rp_filter=0',
                'net.ipv4.conf.wlan0.rp_filter=0')
            run(ip, '-n', client_ns, 'route', 'add', '192.0.2.1/32', 'via', '198.51.100.1', 'dev', 'wlan0')
            run(ip, '-n', client_ns, '-6', 'route', 'add', 'fd00:1::1/128', 'via', 'fd00:2::1', 'dev', 'wlan0')
            for host in ('192.0.2.1', 'fd00:1::1'):
                for port in (22, 2222, 8080):
                    result = subprocess.run([ip, 'netns', 'exec', client_ns, sys.executable,
                        '-c', client, host, str(port)], timeout=3)
                    public = port == 8080 or self.developer_subnets and port == 2222
                    self.assertEqual(result.returncode, 0 if public else 3, ('weak-host', host, port))
        finally:
            if process:
                process.terminate()
                process.wait(timeout=5)
            for ns in reversed(created):
                subprocess.run([ip, 'netns', 'del', ns], check=True, timeout=5)
