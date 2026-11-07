#!/usr/bin/env python3
"""Build-only cleanup hook for disposable locked-root experiments.

Never installed on a Pi. A marker from the current bootstrap setup hook is
required; this is deliberately not an in-place migration or repair tool.
"""
from pathlib import Path
import re
import sys

MARKER = 'run/zmala-root-build.marker'
TOKEN = b'zmala-unqualified-locked-root-v1\n'


def contained(root, name):
    path = root/name
    if any((root/p).is_symlink() for p in Path(name).parents if str(p) != '.'):
        raise ValueError('Linked cleanup parent: '+name)
    return path


def setup(root):
    root = Path(root)
    if root.is_symlink() or not root.is_dir() or root.resolve() == Path(root.anchor):
        raise ValueError('Expected a disposable offline bootstrap root')
    marker = contained(root.resolve(), MARKER)
    marker.parent.mkdir(parents=True, exist_ok=True)
    with marker.open('xb') as stream:
        stream.write(TOKEN)


def prepare(root):
    root = Path(root)
    if root.is_symlink() or not root.is_dir() or root.resolve() == Path(root.anchor):
        raise ValueError('Expected a disposable offline bootstrap root')
    root = root.resolve()
    marker = contained(root, MARKER)
    if (marker.is_symlink() or not marker.is_file() or marker.stat().st_size != len(TOKEN)
            or marker.read_bytes() != TOKEN):
        raise ValueError('Missing disposable root-build marker')
    status = contained(root, 'var/lib/dpkg/status')
    if status.is_symlink() or not status.is_file():
        raise ValueError('Missing slot-local package ledger')
    # Package maintainer scripts can create host keys even when service starts
    # are blocked. No factory image may share those keys or a build-machine ID.
    ssh = contained(root, 'etc/ssh')
    if ssh.is_symlink():
        raise ValueError('Linked SSH cleanup directory')
    if ssh.is_dir():
        for path in ssh.glob('ssh_host_*'):
            if re.fullmatch(r'ssh_host_[A-Za-z0-9_-]+_key(?:\.pub)?', path.name):
                if path.is_dir() and not path.is_symlink():
                    raise ValueError('Unexpected SSH key directory')
                path.unlink()
    for name, value in (('etc/machine-id', b''), ('etc/hostname', b'zmala-unconfigured\n'),
                        ('etc/hosts', b'127.0.0.1 localhost\n::1 localhost ip6-localhost ip6-loopback\n')):
        path = contained(root, name)
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError('Unexpected factory identity path: '+name)
        path.write_bytes(value)
    for name in ('etc/resolv.conf', 'var/lib/dbus/machine-id', 'var/lib/systemd/random-seed',
                 'var/lib/urandom/random-seed', 'var/lib/NetworkManager/secret_key'):
        path = contained(root, name)
        if path.exists() or path.is_symlink():
            if path.is_dir() and not path.is_symlink():
                raise ValueError('Unexpected temporary identity directory')
            path.unlink()
    shadow = contained(root, 'etc/shadow')
    if shadow.is_symlink() or not shadow.is_file() or shadow.stat().st_size > 1024**2:
        raise ValueError('Missing or unexpected factory account ledger')
    for line in shadow.read_text().splitlines():
        fields = line.split(':')
        if len(fields) != 9 or not fields[1].startswith(('!', '*')):
            raise ValueError('Factory account is not password-locked')
    apt = contained(root, 'etc/apt/sources.list.d')
    if apt.is_symlink():
        raise ValueError('Linked build-source directory')
    for path in ([contained(root, 'etc/apt/sources.list')]
                 + (list(apt.iterdir()) if apt.is_dir() else [])):
        if path.exists() or path.is_symlink():
            if not path.is_file() or path.is_symlink():
                raise ValueError('Unexpected build-source entry')
            path.unlink()
    options = contained(root, 'etc/apt/apt.conf.d/99mmdebstrap')
    if options.exists() or options.is_symlink():
        if options.is_symlink() or not options.is_file():
            raise ValueError('Unexpected bootstrap APT options')
        options.unlink()
    # These experimental roots have no updater yet. Do not let a first boot
    # mutate packages or EEPROM while their production policies are unfinished.
    for unit in ('rpi-eeprom-update.service', 'apt-daily.timer', 'apt-daily-upgrade.timer'):
        vendor = contained(root, 'usr/lib/systemd/system/'+unit)
        if vendor.is_symlink() or not vendor.is_file():
            raise ValueError('Missing expected vendor unit: '+unit)
        mask = contained(root, 'etc/systemd/system/'+unit)
        mask.parent.mkdir(parents=True, exist_ok=True)
        if mask.is_symlink() and mask.readlink().as_posix() == '/dev/null':
            continue
        if mask.exists() or mask.is_symlink():
            raise ValueError('Refusing an existing unit override: '+unit)
        mask.symlink_to('/dev/null')


if __name__ == '__main__':
    {'setup': setup, 'clean': prepare}[sys.argv[1]](sys.argv[2])
