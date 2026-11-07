#!/usr/bin/python3
"""Privileged, fixed-purpose developer tunnel lifecycle. Never log credentials."""
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys

SETTINGS = Path('/etc/zmalacall/developer-access.json')
STATE = Path('/var/lib/zmalacall-developer/session.json')
RUNTIME = Path('/run/zmalacall-developer')
UNIT = 'zmalacall-developer'
HOST_KEY = Path('/etc/ssh/ssh_host_ed25519_key')




def image_settings(settings, action, caller):
    """Use fixed persistent paths and separate service callers on appliance hosts."""
    global STATE, HOST_KEY
    if not settings.get('image'):
        return settings
    STATE = Path('/etc/ssh/keys/developer-session.json')
    HOST_KEY = Path('/etc/ssh/keys/ssh_host_ed25519_key')
    role = settings['role']
    if action == 'prepare':
        return settings
    allowed = {'zmalaterminal': 'terminal', 'zmalaserver': 'server'}
    selected = allowed.get(caller)
    if selected is None or role not in (selected, 'combined'):
        raise PermissionError('Invalid appliance service caller')
    return dict(settings, role=selected)




def prepare(settings):
    """Create a unique host key after persistent storage is mounted, never at build."""
    if not settings.get('image'):
        raise ValueError('Appliance preparation required')
    HOST_KEY.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not HOST_KEY.exists():
        run('ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(HOST_KEY))
    # Image /etc/shadow is volatile. Rehydrate only an explicitly retained
    # server activation, before the isolated listener can accept connections.
    if settings['role'] in ('server', 'combined'):
        state = read(STATE)
        if state:
            validate({k: v for k, v in state.items() if k != 'account_id'})
            run('chpasswd', data='terminal:' + state['password'] + '\n')
    return {'prepared': True}


def run(*args, data=None, check=True):
    return subprocess.run(args, input=data, text=True, capture_output=True, check=check, timeout=20)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix('.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream)
    temporary.replace(path)


def read(path):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}



def server(action, request, settings):
    state = read(STATE)
    if action == 'status':
        return {'supported': True, 'terminal_id': state.get('account_id'),
                'connected': bool(state) and connected(), 'port': 22001}
    if action == 'config':
        return {k: v for k, v in state.items() if k != 'account_id'} if state and state['account_id'] == request.get('terminal_id') and state['terminal_id'] == request.get('device_id') else None
    if action == 'off':
        # Stop the entire sshd cgroup: locking a password alone does not revoke
        # established tunnels. Kill first, remove credentials only after success.
        run('systemctl', 'disable', '--now', UNIT + '.service')
        run('usermod', '-L', 'terminal')
        STATE.unlink(missing_ok=True)
        return {'supported': True, 'terminal_id': None, 'connected': False, 'port': 22001}
    if action != 'on':
        raise ValueError('Unsupported action')
    identity = request.get('terminal_id', '')
    if not re.fullmatch(r'[a-z][a-z0-9_-]{0,30}', identity):
        raise ValueError('Invalid terminal')
    if state:
        if state['account_id'] != identity or state['terminal_id'] != request.get('device_id'):
            raise ValueError('Deactivate the existing developer session first')
        return server('status', {}, settings)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', request.get('host', '')):
        raise ValueError('Invalid host')
    password = secrets.token_urlsafe(36)
    key = HOST_KEY.with_suffix('.pub').read_text().split()
    device = request.get('device_id', '')
    if not isinstance(device, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', device):
        raise ValueError('Invalid device identity')
    state = {'account_id': identity, 'terminal_id': device, 'session_id': secrets.token_hex(16),
             'host': request['host'], 'port': 2222, 'remote_port': 22001,
             'host_key': ' '.join(key[:2]), 'password': password}
    try:
        run('chpasswd', data='terminal:' + password + '\n')
        save(STATE, state)
        run('systemctl', 'enable', '--now', UNIT + '.service')
    except Exception:
        run('systemctl', 'disable', '--now', UNIT + '.service', check=False)
        run('usermod', '-L', 'terminal', check=False)
        STATE.unlink(missing_ok=True)
        raise
    return server('status', {}, settings)


def connected():
    try:
        with socket.create_connection(('127.0.0.1', 22001), timeout=.2):
            return True
    except OSError:
        return False



def validate(config):
    if not isinstance(config, dict) or set(config) != {
            'terminal_id', 'session_id', 'host', 'port', 'remote_port', 'host_key', 'password'}:
        raise ValueError('Invalid developer configuration')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', config['host']):
        raise ValueError('Invalid tunnel host')
    if config['port'] != 2222 or config['remote_port'] != 22001:
        raise ValueError('Invalid tunnel ports')
    if not re.fullmatch(r'[a-f0-9]{32}', config['session_id']):
        raise ValueError('Invalid session')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', config['terminal_id']):
        raise ValueError('Invalid terminal')
    if not re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/=]{40,100}', config['host_key']):
        raise ValueError('Invalid pinned host key')
    if not re.fullmatch(r'[A-Za-z0-9_-]{40,100}', config['password']):
        raise ValueError('Invalid tunnel password')
    return config



def terminal(action, config):
    if action == 'off' or action == 'apply' and config is None:
        run('systemctl', 'stop', UNIT + '-tunnel.service', UNIT + '-shell.service')
        for name in ('client.json', 'known_hosts'):
            (RUNTIME / name).unlink(missing_ok=True)
        return {'enabled': False}
    if action != 'apply':
        raise ValueError('Unsupported action')
    validate(config)
    if read(RUNTIME / 'client.json') != config:
        run('systemctl', 'stop', UNIT + '-tunnel.service')
        save(RUNTIME / 'client.json', config)
        pin = f"[{config['host']}]:2222 {config['host_key']}\n"
        (RUNTIME / 'known_hosts').write_text(pin)
        (RUNTIME / 'known_hosts').chmod(0o600)
    run('systemctl', 'start', UNIT + '-shell.service', UNIT + '-tunnel.service')
    return {'enabled': True}


def tunnel():
    config = validate(read(RUNTIME / 'client.json'))
    environment = dict(os.environ, SSH_ASKPASS='/usr/local/libexec/zmala-developer-askpass',
                       SSH_ASKPASS_REQUIRE='force', DISPLAY='developer-tunnel')
    args = ['/usr/bin/ssh', '-F', '/dev/null', '-N', '-T', '-p', '2222',
            '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + str(RUNTIME / 'known_hosts'),
            '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'PreferredAuthentications=password',
            '-o', 'PubkeyAuthentication=no', '-o', 'NumberOfPasswordPrompts=1',
            '-o', 'ExitOnForwardFailure=yes', '-o', 'ServerAliveInterval=15',
            '-o', 'ServerAliveCountMax=2', '-o', 'ConnectTimeout=10',
            '-R', '127.0.0.1:22001:127.0.0.1:2223', 'terminal@' + config['host']]
    os.execve(args[0], args, environment)


def main():
    if os.geteuid() != 0:
        raise PermissionError('Root helper required')
    action = sys.argv[1]
    if action == 'askpass':
        print(read(RUNTIME / 'client.json')['password'])
        return
    if action == 'run':
        tunnel()
        return
    settings = image_settings(read(SETTINGS), action, os.environ.get('SUDO_USER'))
    if action == 'prepare':
        print(json.dumps(prepare(settings)))
        return
    request = json.loads(sys.stdin.read(4096) or '{}')
    with open('/run/lock/zmalacall-developer.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        result = server(action, request, settings) if settings['role'] == 'server' else terminal(action, request)
    print(json.dumps(result))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # subprocess errors can include sensitive input; expose only the type.
        print(json.dumps({'error': type(error).__name__}), file=sys.stderr)
        sys.exit(1)
