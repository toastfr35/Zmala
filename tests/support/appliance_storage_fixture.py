"""Synthetic roots/state for storage verification; never copied from a live Pi."""
import json
from pathlib import Path

from zmala_system import host_layout as layout

MACHINE_ID = b'00112233445566778899aabbccddee01\n'
HOSTNAME = b'zmala-storage-test\n'


def file(path, content, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    path.chmod(mode)


def image(root, role, generation='A'):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o755)
    for name in ('etc', 'var', 'tmp', 'data', 'usr/lib/zmala', layout.PACKAGE_DB,
                 layout.VAR_SEED+'/lib', layout.VAR_SEED+'/log', layout.VAR_SEED+'/tmp'):
        (root/name).mkdir(parents=True, exist_ok=True)
        (root/name).chmod(0o1777 if name in ('tmp', layout.VAR_SEED+'/tmp') else 0o755)
    file(root/layout.PROFILE, json.dumps(layout.profile(role)).encode())
    file(root/'etc/machine-id', b'')
    file(root/'etc/hostname', b'unconfigured\n')
    file(root/'etc/vendor.conf', ('factory-'+generation).encode())
    file(root/'etc/zmalacall/vendor.conf', ('product-default-'+generation).encode())
    file(root/layout.PACKAGE_DB/'status', ('slot-package-'+generation).encode())
    (root/layout.PACKAGE_DB/'alternatives').mkdir()
    file(root/layout.PACKAGE_DB/'alternatives/tool', ('alternative-'+generation).encode())
    (root/layout.VAR_SEED/'lib/dpkg').symlink_to('/'+layout.PACKAGE_DB)
    file(root/layout.VAR_SEED/'lib/vendor-state', ('seed-'+generation).encode(), 0o640)
    return root


def data(root, role):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)
    (root/'identity').mkdir(mode=0o700)
    file(root/layout.DATA_MARKER, json.dumps({'schema': 1, 'role': role}).encode(), 0o600)
    file(root/'identity/machine-id', MACHINE_ID)
    file(root/'identity/hostname', HOSTNAME)
    return root
