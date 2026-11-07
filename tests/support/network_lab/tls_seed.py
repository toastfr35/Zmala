"""Disposable CA, endpoint certificate and TURN credentials. Never print secrets."""
import json
from pathlib import Path
import secrets
import subprocess


def seed():
    root = Path('/lab')
    if (root/'tls-ready').exists():
        return
    def openssl(*args):
        subprocess.run(['openssl', *args], cwd=root, check=True, capture_output=True)
    openssl('req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '2',
            '-addext', 'basicConstraints=critical,CA:TRUE',
            '-addext', 'keyUsage=critical,keyCertSign,cRLSign',
            '-subj', '/CN=Zmala disposable lab CA', '-keyout', 'ca.key', '-out', 'ca.pem')
    openssl('req', '-newkey', 'rsa:2048', '-nodes', '-subj', '/CN=10.231.100.13',
            '-keyout', 'server.key', '-out', 'server.csr')
    (root/'extensions').write_text('subjectAltName=IP:10.231.100.13,IP:10.231.100.14,IP:10.231.100.15\nextendedKeyUsage=serverAuth\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n')
    openssl('x509', '-req', '-in', 'server.csr', '-CA', 'ca.pem', '-CAkey', 'ca.key',
            '-CAcreateserial', '-days', '2', '-extfile', 'extensions', '-out', 'server.pem')
    secret = secrets.token_hex(32)
    (root/'turn-secret').write_text(secret)
    (root/'secure-calls.json').write_text(json.dumps({'https_url':'https://10.231.100.15:443', 'sip_host':'10.231.100.13', 'sip_listen_port':5061, 'sip_cert':'/lab/server.pem', 'sip_key':'/lab/server.key', 'turn_host':'10.231.100.14', 'turn_realm':'zmala.lab', 'turn_secret_file':'/lab/turn-secret'}))
    (root/'turn.conf').write_text('''listening-ip=10.231.100.14
relay-ip=10.231.100.14
tls-listening-port=443
listening-port=3478
min-port=30000
max-port=30199
realm=zmala.lab
server-name=zmala.lab
use-auth-secret
fingerprint
no-udp
no-tcp
no-dtls
no-tlsv1
no-tlsv1_1
no-cli
no-multicast-peers
cert=/lab/server.pem
pkey=/lab/server.key
log-file=stdout
simple-log
''' + 'static-auth-secret='+secret+'\n')
    for name in ('ca.key', 'server.key', 'turn-secret', 'secure-calls.json', 'turn.conf'):
        (root/name).chmod(0o600)
    (root/'tls-ready').touch()


if __name__ == '__main__':
    seed()
