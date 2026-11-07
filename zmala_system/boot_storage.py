"""Prepare image-managed host storage from a verified early-boot root.

This is not a live-host updater or disk repair tool. The selected root is an
input mount; only the discovered sibling data mount and new RAM views are owned.
"""
import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import platform
import stat
import subprocess

from . import boot_capacity, boot_devices, boot_layout, device_identity, host_layout, host_storage

READY = 'boot-ready.json'
NEXT = 'boot-ready.next'


# @llr LLR-SRV-HOST-018, LLR-SRV-HOST-021, LLR-TERM-MAINT-045, LLR-TERM-MAINT-048
def configured_role(root=Path('/')):
    role = host_storage.read_record(root, 'usr/lib/zmala/role', 0o644, 16).decode('ascii').strip()
    host_layout.profile(role)
    return role


# @llr LLR-SRV-HOST-018, LLR-TERM-MAINT-045
def admit(root, area, role, facts):
    root, area = map(host_storage.canonical, (root, area))
    if root == Path('/') or area.exists() or area.is_symlink():
        raise ValueError('Unsupported root or conflicting boot RAM area')
    selected = facts.get(root)
    if not selected or selected.filesystem != 'ext4' or 'ro' not in selected.flags:
        raise ValueError('Expected an already mounted read-only ext4 image root')
    boot_layout.device_number(selected.device)
    host_layout.metadata(root.lstat(), mode=0o755, directory=True)
    for name in ('etc', 'usr', 'var', 'tmp', 'data'):
        target = host_storage.safe(root, name)
        host_layout.metadata(target.lstat(), directory=True)
        if any(point.is_relative_to(target) for point in facts):
            raise ValueError('Conflicting mount inside a boot policy tree')
    data = root/'data'
    if any(data.iterdir()):
        raise ValueError('The image data mountpoint must be empty')
    if (area.is_relative_to(data) or data.is_relative_to(area)
            or (area.is_relative_to(root) and not area.is_relative_to(root/'run'))):
        raise ValueError('RAM working area overlaps image policy')
    parent = area.parent.lstat()
    host_layout.metadata(parent, directory=True)
    ram = [mount for point, mount in facts.items() if area.parent.is_relative_to(point)]
    ram = max(ram, key=lambda mount: len(mount.point.parts)) if ram else None
    if (not ram or ram.filesystem not in ('tmpfs', 'ramfs') or 'rw' not in ram.flags
            or stat.S_IMODE(parent.st_mode) & 0o022):
        raise ValueError('Expected a root-controlled RAM working parent')
    host_layout.decode_profile(host_storage.read_record(
        root, host_layout.PROFILE, 0o644, host_layout.MAX_PROFILE_BYTES), role)
    policy = boot_layout.decode_profile(host_storage.read_record(
        root, boot_layout.PROFILE, 0o644, boot_layout.MAX_RECORD_BYTES), role)
    return root, data, area, policy


# @llr LLR-SRV-HOST-020, LLR-TERM-MAINT-047
@dataclass
class PreparedBoot:
    root: Path
    data: Path
    area: Path
    system: object
    initial: dict
    data_device: str
    views: object = None
    owned_data: bool = False
    ready: bool = False

    def mount_data(self, source):
        try:
            self.system.run(['mount', '-t', 'ext4', '-o', 'rw,nodev,nosuid', str(source), str(self.data)])
        except BaseException:
            try:
                present = self.system.facts().get(self.data)
                self.owned_data = bool(present and present.device == self.data_device)
            except BaseException:
                self.owned_data = True  # Reinspect possible partial success during cleanup.
            raise
        self.owned_data = True

    def close(self):
        self.ready = False
        errors = []
        for name in (NEXT, READY):
            try:
                (self.area/name).unlink(missing_ok=True)
            except OSError as error:
                errors.append(error)
        if self.views is not None:
            try:
                self.views.close()
            except BaseException as error:
                errors.append(error)
        if self.owned_data:
            try:
                current = self.system.facts()
                protected = [self.root/name for name in ('etc', 'var', 'tmp')]+[self.area]
                residual = [point for point in current if point not in self.initial and point != self.data
                            and (point.is_relative_to(self.data)
                                 or any(point.is_relative_to(tree) for tree in protected))]
                if residual:
                    raise ValueError('Data retained because dependent boot mounts remain')
                mounted = current.get(self.data)
                if mounted:
                    if mounted.device != self.data_device:
                        raise ValueError('Owned data mount identity changed during cleanup')
                    self.system.run(['umount', str(self.data)])
                self.owned_data = False
            except BaseException as error:
                errors.append(error)
        if errors:
            raise errors[0]


# @llr LLR-SRV-HOST-018, LLR-SRV-HOST-019, LLR-SRV-HOST-020, LLR-TERM-MAINT-045, LLR-TERM-MAINT-046, LLR-TERM-MAINT-047, LLR-SRV-HOST-031, LLR-TERM-MAINT-058
def prepare(root, role, area=Path('/run/zmala-host'), system=None):
    if platform.system() != 'Linux' or os.geteuid() != 0 or os.getegid() != 0:
        raise ValueError('Early-boot storage requires Linux root with root group')
    system = system or boot_devices.NativeBoot()
    initial = system.facts()
    root, data, area, policy = admit(root, area, role, initial)
    slot, root_uuid = system.boot_arguments()
    selected, partition = boot_devices.discover(system, policy, slot, root_uuid, initial[root].device)
    if any(mount.device == partition.device for mount in initial.values()):
        raise ValueError('Selected data is already mounted')
    result = PreparedBoot(root, data, area, system, initial, partition.device)
    try:
        result.mount_data(partition.node)
        mounted = system.facts().get(data)
        if (not mounted or mounted.device != partition.device
                or mounted.filesystem != 'ext4' or 'rw' not in mounted.flags):
            raise ValueError('Selected data mount was not established')
        boot_capacity.prepare(root, data, role, system, selected, partition, root_uuid)
        device_identity.initialize(data, role, system)
        result.views = host_storage.prepare(root, data, area, role, system)
        # PID1's ordinary remount service must keep the selected root read-only.
        # This file is in the fresh /etc RAM overlay, never shared across slots.
        fstab = host_storage.safe(root, 'etc/fstab')
        pending_fstab = host_storage.safe(root, 'etc/fstab.next')
        body = '# Generated for this validated system slot.\nPARTUUID='+root_uuid+' / ext4 ro 0 0\n'
        device_identity.write_exclusive(pending_fstab, body.encode(), 0o644)
        pending_fstab.replace(fstab)
        status = {'schema': 1, 'role': role, 'slot': slot, 'boot_storage_prepared': True}
        device_identity.write_exclusive(area/NEXT, (json.dumps(status)+'\n').encode(), 0o600)
        (area/NEXT).replace(area/READY)
        result.ready = True
        return result
    except BaseException:
        try:
            result.close()
        except BaseException:
            pass  # Preserve the original preparation error; startup remains fenced.
        raise


# @llr LLR-SRV-HOST-021, LLR-TERM-MAINT-048
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--role', choices=host_layout.ROLES, required=True)
    args = parser.parse_args()
    try:
        prepare(args.root, args.role)
    except (OSError, ValueError, subprocess.SubprocessError):
        parser.error('Early-boot storage preparation failed; normal startup must remain fenced.')
    print('Image-managed boot storage prepared.')


if __name__ == '__main__':
    main()
