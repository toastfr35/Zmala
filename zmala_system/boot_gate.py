"""PID1 startup gate: a killed/missing initramfs helper cannot admit services."""
import json
from pathlib import Path
import sys

from . import boot_devices, boot_layout, boot_storage, device_identity, host_layout, host_storage


def record(area, name, expected):
    body = host_storage.read_record(area, name, 0o600, 8192)
    value = json.loads(body.decode('utf-8'), object_pairs_hook=host_layout.unique_fields)
    if (not isinstance(value, dict) or value != expected
            or any(type(value[key]) is not type(item) for key, item in expected.items())):
        raise ValueError('Invalid current-boot readiness record')


# @llr LLR-SRV-HOST-021, LLR-TERM-MAINT-048
def verify(root=Path('/'), area=Path('/run/zmala-host'), system=None):
    root, area = map(host_storage.canonical, (root, area))
    system = system or boot_devices.NativeBoot()
    role = boot_storage.configured_role(root)
    host_layout.decode_profile(host_storage.read_record(root, host_layout.PROFILE, 0o644, 8192), role)
    boot_layout.decode_profile(host_storage.read_record(root, boot_layout.PROFILE, 0o644, 8192), role)
    facts = system.facts()
    selected, data, ram = facts.get(root), facts.get(root/'data'), facts.get(area)
    if (not selected or selected.filesystem != 'ext4' or 'ro' not in selected.flags
            or not data or data.filesystem != 'ext4' or 'rw' not in data.flags
            or selected.device == data.device or not ram or ram.filesystem != 'tmpfs' or 'rw' not in ram.flags):
        raise ValueError('Image-managed storage mounts are incomplete')
    host_layout.metadata(area.lstat(), mode=0o700, directory=True)
    slot, _ = system.boot_arguments()
    record(area, boot_storage.READY, {'schema': 1, 'role': role, 'slot': slot, 'boot_storage_prepared': True})
    # The underlying storage helper's marker is also required. It is created
    # only after every declared binding has been established.
    record(area, 'ready.json', {'schema': 1, 'role': role, 'storage_prepared': True})
    for name, filesystem in (('etc', 'overlay'), ('var', 'tmpfs'), ('tmp', 'tmpfs')):
        view = facts.get(root/name)
        if not view or view.filesystem != filesystem or 'rw' not in view.flags:
            raise ValueError('Missing volatile image view')
    host_layout.decode_profile(host_storage.read_record(root/'data', host_layout.DATA_MARKER, 0o600, 8192),
                               role, data=True)
    saved = device_identity.saved_identity(root/'data')
    for binding in host_layout.bindings(role):
        target = host_storage.safe(root, binding.target)
        bound = facts.get(target)
        if (not bound or bound.device != data.device or bound.filesystem != 'ext4'
                or ('ro' if binding.readonly else 'rw') not in bound.flags):
            raise ValueError('Persistent image binding is missing or incompatible')
        host_layout.metadata(target.lstat(), binding.uid, binding.gid, binding.mode, binding.directory)
    for name, field in (('etc/machine-id', 'machine-id'), ('etc/hostname', 'hostname')):
        if host_storage.read_record(root, name, 0o644, 128) != saved[field]:
            raise ValueError('Bound image identity differs from committed identity')
    return True


# @llr LLR-SRV-HOST-021, LLR-TERM-MAINT-048
def main():
    try:
        if sys.argv[1:]:
            raise ValueError('Unexpected startup gate arguments')
        verify()
    except BaseException:
        print('Zmala storage is incomplete. Normal startup is blocked.', file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
