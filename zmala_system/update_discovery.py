"""Read-only discovery of signed system releases for a Terminal appliance.

This service cannot install a bundle, select a slot or reboot. Installation
requires a separate qualified admission, health and rollback coordinator.
"""
from datetime import date
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from . import boot_capacity, boot_devices, boot_layout, host_layout, host_storage

IDENTITY = 'usr/lib/zmala/system-release.json'
KEYRING = 'usr/lib/zmala/system-update-keyring.pem'
FEED = 'https://github.com/toastfr35/Zmala/releases/latest/download'


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'(0|[1-9][0-9]{0,7})(\.(0|[1-9][0-9]{0,7})){2}', value):
        raise ValueError('Invalid system version')
    return tuple(map(int, value.split('.')))


def compatible(slot):
    if slot not in ('A', 'B'):
        raise ValueError('Invalid release slot')
    return 'zmala-pi4-terminal-v1-'+slot.lower()


# @llr LLR-TERM-MAINT-060
def release(body, target, installed):
    """Interpret only metadata already authenticated by RAUC 1.13."""
    result = json.loads(body, object_pairs_hook=host_layout.unique_fields)
    update = result['update']
    if (update['compatible'] != compatible(target) or result['bundle']['format'] != 'verity'
            or result.get('hooks') or result.get('handler') or result.get('artifacts')):
        raise ValueError('Unsupported system bundle')
    identity = result['manifest-hash']
    if not re.fullmatch('[0-9a-f]{64}', identity):
        raise ValueError('Invalid authenticated manifest identity')
    expected = {'boot': ('boot.vfat', boot_capacity.SIZES[1]),
                'rootfs': ('root.ext4', boot_capacity.SIZES[3])}
    for image in result['images']:
        name, size = expected.pop(image['slot-class'])
        if (image['filename'] != name or type(image['size']) is not int or image['size'] != size
                or not re.fullmatch('[0-9a-f]{64}', image['checksum'])
                or any(image.get(field) for field in ('hooks', 'variant', 'artifact', 'convert', 'converted', 'adaptive'))):
            raise ValueError('Unsupported system bundle image')
    if expected:
        raise ValueError('System release must contain a complete boot and root pair')
    candidate = update['version']
    terminal = result['meta']['zmala']['terminal-version']
    version(terminal)
    if version(candidate) <= version(installed):
        return None
    return {'system_version': candidate, 'terminal_version': terminal, 'release': identity, 'target': target}


def inspect_release(target, installed, probe=boot_devices.bounded_probe):
    # A bounded read validates root ownership before RAUC opens the same
    # keyring on the read-only system root. No --no-verify path is supported.
    host_storage.read_record(Path('/'), KEYRING, 0o644, 65536)
    url = f'{FEED}/ZmalaTerminal-System-{target}.raucb'
    body = probe(['/usr/bin/rauc', '--keyring=/'+KEYRING, 'info', '--output-format=json-2', url], timeout=25)
    return release(body, target, installed)


def save(path, value):
    with tempfile.NamedTemporaryFile(dir=path.parent, mode='w', delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(temporary, path)
            descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            temporary.unlink(missing_ok=True)


# @llr LLR-TERM-MAINT-060
def check_day(status, today, inspect):
    try:
        previous = json.loads(host_storage.read_record(status.parent, status.name, 0o600, 4096))
    except FileNotFoundError:
        previous = {}
    if previous.get('date', '') >= today:
        return
    save(status, {'schema': 1, 'date': today, 'state': 'checking'})
    try:
        candidate = inspect()
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        save(status, {'schema': 1, 'date': today, 'state': 'error'})
        return
    save(status, {'schema': 1, 'date': today, 'state': 'verified' if candidate else 'current',
                  'candidate': candidate})


def main():
    root = Path('/')
    identity = json.loads(host_storage.read_record(root, IDENTITY, 0o644, 4096))
    if identity['role'] != 'terminal' or identity['schema'] != 1:
        raise ValueError('Expected a standalone Terminal appliance')
    installed = identity['version']
    version(installed)
    current, _ = boot_layout.command_line(boot_devices.read('/proc/cmdline', boot_layout.MAX_RECORD_BYTES))
    target = 'B' if current == 'A' else 'A'
    directory = host_storage.safe(Path('/data'), 'host/update-discovery')
    directory.mkdir(mode=0o700, exist_ok=True)
    host_layout.metadata(directory.lstat(), mode=0o700, directory=True)
    check_day(directory/'status.json', date.today().isoformat(), lambda: inspect_release(target, installed))


if __name__ == '__main__':
    main()
