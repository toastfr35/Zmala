"""Disposable target-sshd packaging check inside the worker's private namespace."""
import subprocess
import time

from .initramfs_worker import command


def check(root, role):
    """No systemd or hardware claim: execute installed SSH configuration and keys."""
    keys = root/'etc/ssh/keys'
    keys.mkdir(mode=0o700, exist_ok=True)
    command(['mount', '-t', 'tmpfs', '-o', 'mode=0700,size=8M', 'tmpfs', keys])
    process = None
    try:
        command(['ip', 'link', 'set', 'lo', 'up'])
        command(['chroot', root, '/usr/local/libexec/zmala-developer-access', 'prepare'])
        command(['chroot', root, '/usr/sbin/visudo', '-cf', '/etc/sudoers.d/zmalacall-developer'])
        if role in ('terminal', 'combined'):
            # QEMU user emulation cannot exercise setuid elevation. Check the
            # target binary mode and resolved policy here; run sudo over the
            # server-controlled tunnel in the physical acceptance test.
            if (root/'usr/bin/sudo').stat().st_mode & 0o7777 != 0o4755:
                raise ValueError('Target sudo is not installed setuid')
            command(['chroot', root, '/usr/bin/sudo', '-l', '-U', 'zmala'])
        (root/'run/sshd').mkdir(exist_ok=True)
        for side in ('terminal', 'server'):
            if role in (side, 'combined'):
                command(['chroot', root, '/usr/sbin/sshd', '-t', '-f', '/etc/ssh/zmala-developer-'+side+'.conf'])
        if role not in ('terminal', 'combined'):
            return
        command(['chroot', root, '/usr/bin/ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', '/tmp/operator'])
        (keys/'authorized_keys').write_bytes((root/'tmp/operator.pub').read_bytes())
        (keys/'authorized_keys').chmod(0o600)
        pin = root/'tmp/pinned-host'
        pin.write_text('[127.0.0.1]:2223 '+(keys/'ssh_host_ed25519_key.pub').read_text())
        args = ['/usr/bin/ssh', '-F', '/dev/null', '-i', str(root/'tmp/operator'), '-p', '2223',
                '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes',
                '-o', 'UserKnownHostsFile='+str(pin), '-o', 'GlobalKnownHostsFile=/dev/null',
                '-o', 'ConnectTimeout=2', 'zmala@127.0.0.1', 'id -un']
        with (root/'tmp/sshd-check.log').open('w+') as log:
            process = subprocess.Popen(['chroot', str(root), '/usr/sbin/sshd', '-D', '-e', '-f',
                                        '/etc/ssh/zmala-developer-terminal.conf'], stdout=log, stderr=log)
            for _ in range(30):
                result = subprocess.run(args, capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    break
                if process.poll() is not None:
                    break
                time.sleep(.2)
            if result.returncode or result.stdout.splitlines() != ['zmala']:
                log.seek(0)
                raise ValueError('Target developer shell failed: '+result.stderr+log.read())
            (keys/'authorized_keys').unlink()
            if subprocess.run(args, capture_output=True, timeout=10).returncode == 0:
                raise ValueError('Developer shell accepted a removed operator key')
            process.terminate()
            process.wait(timeout=10)
            process = None
            if subprocess.run(args, capture_output=True, timeout=10).returncode == 0:
                raise ValueError('Developer shell remains reachable after shutdown')
    finally:
        if process is not None:
            process.terminate()
            process.wait(timeout=10)
        command(['umount', keys])
        if any(keys.iterdir()):
            raise ValueError('Target SSH check retained factory credentials')
        keys.rmdir()
