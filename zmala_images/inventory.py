"""Read-only Linux inventory for image sizing; output omits host identities/secrets.

Run directly with Python 3 on the target; no checkout or third-party packages are
needed. No sudo, device opens, service transitions, network calls or USB probes.
Missing facts are errors/unknowns, never successful hardware qualification.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import subprocess
import time

PATHS = ('/', '/boot/firmware', '/var/lib/zmalacall', '/var/lib/zmalacall-server',
         '/opt/zmalacall', '/opt/zmalacall-updates', '/var/lib/zmalacall-update-data',
         '/opt/zmalacall-server')
UNITS = ('zmalacall-terminal', 'zmalacall-server', 'zmalacall-updater',
         'zmalacall-ssh-guard', 'NetworkManager', 'bluetooth', 'coturn', 'nginx',
         'caddy', 'certbot.timer', 'apt-daily.timer', 'apt-daily-upgrade.timer')


def command(args, runner=subprocess.run):
    """Only fixed read-only commands call this helper; retain no stderr contents."""
    try:
        result = runner(args, capture_output=True, text=True, timeout=20,
                        env={**os.environ, 'LC_ALL': 'C'})
    except (OSError, subprocess.TimeoutExpired) as error:
        return {'error': type(error).__name__}
    return {'output': result.stdout} if result.returncode == 0 else {'error': 'command-failed'}


def footprint(path, limit=100000, seconds=10):
    """Count allocated bytes without following links or crossing mount points.

    This is an estimate of selected trees, not a whole-card minimum. Hard links
    are counted once. Bound traversal and expose incomplete totals explicitly.
    """
    root = Path(path)
    try:
        initial = root.lstat()
    except FileNotFoundError:
        return {'present': False}
    except OSError:
        return {'error': 'unreadable'}
    if root.is_symlink():
        return {'present': True, 'complete': False, 'reason': 'symlink-not-followed'}
    seen, pending = set(), [root]
    total = count = errors = 0
    deadline = time.monotonic()+seconds
    while pending and count < limit and time.monotonic() < deadline:
        item = pending.pop()
        try:
            info = item.lstat()
            identity = (info.st_dev, info.st_ino)
            if identity in seen or info.st_dev != initial.st_dev:
                continue
            seen.add(identity)
            count += 1
            total += info.st_blocks*512
            if item.is_dir() and not item.is_symlink():
                with os.scandir(item) as entries:
                    for entry in entries:
                        # Bound even a single unusually large directory.
                        if len(pending)+count >= limit:
                            return {'present': True, 'allocated_bytes': total, 'entries': count,
                                    'complete': False, 'errors': errors}
                        pending.append(Path(entry.path))
        except OSError:
            errors += 1
    return {'present': True, 'allocated_bytes': total, 'entries': count,
            'complete': not pending and errors == 0, 'errors': errors}


def collect(role, runner=subprocess.run):
    if role not in ('terminal', 'server'):
        raise ValueError('Unknown appliance role')
    release = {}
    try:
        for line in Path('/etc/os-release').read_text().splitlines():
            key, _, value = line.partition('=')
            if key in ('ID', 'VERSION_ID', 'VERSION_CODENAME'):
                release[key] = value.strip('"')
    except OSError:
        pass
    model = Path('/proc/device-tree/model')
    board = model.read_bytes().rstrip(b'\0').decode(errors='replace') if model.exists() else 'unknown'
    mounts = command(['findmnt', '--json', '--output', 'TARGET,FSTYPE,OPTIONS'], runner)
    packages = command(['dpkg-query', '-W', '-f=${binary:Package}\t${Version}\t${Architecture}\t${db:Status-Status}\n'], runner)
    units = command(['systemctl', 'show', *[u if '.' in u else u+'.service' for u in UNITS],
                     '--property=Id,LoadState,ActiveState,UnitFileState'], runner)
    filesystems = {}
    for name in PATHS:
        try:
            stat = os.statvfs(name)
            filesystems[name] = {'capacity_bytes': stat.f_blocks*stat.f_frsize,
                                 'available_bytes': stat.f_bavail*stat.f_frsize}
        except OSError:
            filesystems[name] = {'error': 'unavailable'}
    return {'schema': 1, 'role': role, 'collected_at': datetime.now(timezone.utc).isoformat(),
            'os': release, 'architecture': platform.machine(), 'board_model': board,
            'kernel': platform.release(), 'mounts': mounts, 'packages': packages,
            'units': units, 'filesystems': filesystems,
            'trees': {p: footprint(p) for p in PATHS if p not in ('/', '/boot/firmware')},
            'qualification': 'inventory-only'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--role', choices=('terminal', 'server'), required=True)
    args = parser.parse_args()
    if platform.system() != 'Linux':
        parser.error('Run this read-only collector on the Linux target')
    print(json.dumps(collect(args.role), sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
