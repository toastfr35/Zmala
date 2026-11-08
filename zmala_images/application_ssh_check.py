"""Disposable target-sshd packaging check inside the worker's private namespace."""
import os
import secrets
import socket
import subprocess
import time

from .initramfs_worker import command


def check_password(root, pin):
    shadow = root/'etc/shadow'
    original_shadow = shadow.read_bytes()
    askpass = root/'tmp/developer-password-check'
    askpass.write_text('#!/bin/sh\nprintf "%s\\n" "$ZMALA_TEST_OPERATOR_PASSWORD"\n')
    askpass.chmod(0o700)
    args = ['/usr/bin/ssh', '-F', '/dev/null', '-p', '2223',
            '-o', 'PubkeyAuthentication=no', '-o', 'PreferredAuthentications=password',
            '-o', 'NumberOfPasswordPrompts=1', '-o', 'StrictHostKeyChecking=yes',
            '-o', 'UserKnownHostsFile='+str(pin), '-o', 'GlobalKnownHostsFile=/dev/null',
            '-o', 'ConnectTimeout=2', 'zmala@127.0.0.1', 'id -un']

    def login(password):
        env = dict(os.environ, SSH_ASKPASS=str(askpass), SSH_ASKPASS_REQUIRE='force',
                   DISPLAY='developer-check', ZMALA_TEST_OPERATOR_PASSWORD=password)
        return subprocess.run(args, env=env, capture_output=True, text=True, timeout=10)

    def set_password(password):
        password_hash = subprocess.check_output(['/usr/bin/openssl', 'passwd', '-6', '-stdin'],
                                                input=password+'\n', text=True, timeout=10)
        subprocess.run(['chroot', root, '/usr/sbin/chpasswd', '-e'],
                       input='zmala:'+password_hash, text=True, capture_output=True,
                       check=True, timeout=15)

    try:
        first, second = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
        set_password(first)
        for _ in range(30):
            result = login(first)
            if result.returncode == 0 and result.stdout.splitlines() == ['zmala']:
                break
            time.sleep(.2)
        else:
            raise ValueError('Target developer shell did not accept its activation password')
        set_password(second)
        if login(first).returncode == 0 or login(second).stdout.splitlines() != ['zmala']:
            raise ValueError('Target developer shell failed password rotation')
        command(['chroot', root, '/usr/sbin/usermod', '-p', '*', 'zmala'])
        if login(second).returncode == 0:
            raise ValueError('Target developer shell accepted a revoked operator password')
    finally:
        askpass.unlink()
        shadow.write_bytes(original_shadow)
        (root/'etc/shadow-').unlink(missing_ok=True)


def check(root, role):
    """Execute the installed SSH configuration in an isolated network."""
    keys = root/'etc/ssh/keys'
    keys.mkdir(mode=0o700, exist_ok=True)
    command(['mount', '-t', 'tmpfs', '-o', 'mode=0700,size=8M', 'tmpfs', keys])
    process = None
    try:
        command(['ip', 'link', 'set', 'lo', 'up'])
        command(['chroot', root, '/usr/local/libexec/zmala-developer-access', 'prepare'])
        command(['chroot', root, '/usr/sbin/visudo', '-cf', '/etc/sudoers.d/zmalacall-developer'])
        if role in ('terminal', 'combined'):
            # QEMU user emulation cannot exercise setuid elevation.
            if (root/'usr/bin/sudo').stat().st_mode & 0o7777 != 0o4755:
                raise ValueError('Target sudo is not installed setuid')
            command(['chroot', root, '/usr/bin/sudo', '-l', '-U', 'zmala'])
        (root/'run/sshd').mkdir(exist_ok=True)
        for side in ('terminal', 'server'):
            if role in (side, 'combined'):
                command(['chroot', root, '/usr/sbin/sshd', '-t', '-f', '/etc/ssh/zmala-developer-'+side+'.conf'])
        if role in ('server', 'combined'):
            settings = subprocess.check_output([
                'chroot', root, '/usr/sbin/sshd', '-T', '-f', '/etc/ssh/zmala-developer-server.conf',
            ], text=True, timeout=10).splitlines()
            if not {'allowusers terminal', 'maxsessions 0', 'forcecommand /bin/false',
                    'allowtcpforwarding remote', 'permitlisten 127.0.0.1:22001',
                    'permitopen none', 'gatewayports no'} <= set(settings):
                raise ValueError('Server developer listener is not restricted to the fixed reverse forward')
        if role not in ('terminal', 'combined'):
            return
        pin = root/'tmp/pinned-host'
        pin.write_text('[127.0.0.1]:2223 '+(keys/'ssh_host_ed25519_key.pub').read_text())
        with (root/'tmp/sshd-check.log').open('w+') as log:
            process = subprocess.Popen(['chroot', str(root), '/usr/sbin/sshd', '-D', '-e', '-f',
                                        '/etc/ssh/zmala-developer-terminal.conf'], stdout=log, stderr=log)
            check_password(root, pin)
            process.terminate()
            process.wait(timeout=10)
            process = None
            try:
                with socket.create_connection(('127.0.0.1', 2223), timeout=2):
                    raise ValueError('Developer shell remains reachable after shutdown')
            except ConnectionRefusedError:
                pass
    finally:
        if process is not None:
            process.terminate()
            process.wait(timeout=10)
        command(['umount', keys])
        if any(keys.iterdir()):
            raise ValueError('Target SSH check retained factory credentials')
        keys.rmdir()
