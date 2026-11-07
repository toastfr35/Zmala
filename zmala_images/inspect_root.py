"""Read an offline candidate root without modifying or mounting it.

This checks a bounded set of public-image privacy/build invariants. It does not
qualify boot behavior, signatures, arbitrary unknown secrets, or the data layout.
"""
import fnmatch
import os
from pathlib import Path
import stat

from . import eeprom_policy

FORBIDDEN = (
    'etc/ssh/ssh_host_*_key*', 'etc/NetworkManager/system-connections/*',
    'var/lib/bluetooth/*', 'etc/letsencrypt/accounts/*', 'etc/letsencrypt/live/*',
    'root/.ssh/*', 'home/*/.ssh/*', 'var/lib/zmalacall/*',
    'var/lib/zmalacall-server/*', 'opt/zmalacall-updates/*',
    'var/lib/systemd/random-seed', 'var/lib/urandom/random-seed', 'var/lib/NetworkManager/secret_key',
    '**/google-services.json', '**/*service-account*.json', '**/*.keystore',
    '**/*.jks', '**/.git', '**/.env',
)


def audit(root):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Expected an offline real root directory')
    # Resolve once, then never read a linked path: even /etc may be replaced.
    root = root.resolve()
    violations = []
    pending = [root]
    count = 0
    while pending:
        path = pending.pop()
        count += 1
        if count > 200000:
            raise ValueError('Root tree exceeds inspection budget')
        relative = path.relative_to(root).as_posix()
        if any(fnmatch.fnmatchcase(relative, pattern)
               or (pattern.startswith('**/') and fnmatch.fnmatchcase(relative, pattern[3:]))
               for pattern in FORBIDDEN):
            violations.append('private-state:'+relative)
        if path.is_symlink():
            # Image roots can legitimately contain absolute links. Never follow
            # them into the inspecting host; contents are checked separately.
            continue
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            with os.scandir(path) as children:
                for child in children:
                    if count+len(pending) >= 200000:
                        raise ValueError('Root tree exceeds inspection budget')
                    pending.append(Path(child.path))
        elif not stat.S_ISREG(mode):
            violations.append('special-file:'+relative)

    def linked_parent(name):
        return any((root/parent).is_symlink() for parent in Path(name).parents if str(parent) != '.')

    for name in ('etc/machine-id', 'var/lib/dbus/machine-id'):
        path = root/name
        if linked_parent(name):
            violations.append('uninspectable-identity:'+name)
        elif path.is_symlink():
            # A standard /var/lib/dbus/machine-id -> /etc/machine-id link is safe
            # only when the actual identity file is checked separately.
            if name != 'var/lib/dbus/machine-id' or path.readlink().as_posix() != '/etc/machine-id':
                violations.append('uninspectable-identity:'+name)
        elif path.exists():
            if not path.is_file() or path.stat().st_size > 128 or path.read_bytes().strip():
                violations.append('factory-machine-id:'+name)
    shadow = root/'etc/shadow'
    if linked_parent('etc/shadow') or shadow.is_symlink():
        violations.append('uninspectable-passwords:etc/shadow')
    elif shadow.exists():
        if not shadow.is_file() or shadow.stat().st_size > 1024*1024:
            raise ValueError('Invalid shadow file')
        for line in shadow.read_text().splitlines():
            fields = line.split(':')
            if len(fields) != 9 or not fields[1].startswith(('!', '*')):
                # Report a category; never print a hash or account identity.
                violations.append('enabled-or-invalid-factory-password')
    package_db = root/'var/lib/dpkg/status'
    if linked_parent('var/lib/dpkg/status') or package_db.is_symlink() or not package_db.is_file():
        violations.append('missing-slot-package-database')
    violations.extend(eeprom_policy.violations(root))
    return {'schema': 1, 'checks': 'offline-privacy-and-eeprom-subset',
            'violations': sorted(set(violations)), 'production_qualified': False}
