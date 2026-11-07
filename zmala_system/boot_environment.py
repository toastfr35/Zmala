"""Linux-only, root-controlled environment transport for experimental Pi 4 SD.

Only open_control admits a production device. ToolEnvironment is the narrow I/O
adapter also used by isolated regular-file tests; it does not discover disks or
initialize damaged environments. All read/modify/write operations share a lock.
"""
from contextlib import contextmanager
import os
from pathlib import Path, PurePosixPath
import platform
import re
import stat
import subprocess
import tempfile

try:
    import fcntl
except ImportError:  # Portable policy tests do not perform Linux environment I/O.
    fcntl = None

from . import (boot_devices, boot_gate, boot_layout, boot_media, boot_state,
               boot_storage, host_layout, host_storage)

TOOLS = {'print': '/usr/bin/fw_printenv', 'set': '/usr/bin/fw_setenv'}
RUNNING_BOOT_TOOLS = {'mount': '/usr/bin/mount', 'umount': '/usr/bin/umount', 'blkid': '/usr/sbin/blkid'}


# @llr LLR-SRV-HOST-026, LLR-TERM-MAINT-053
@contextmanager
def lock(area):
    if fcntl is None or os.geteuid() != 0:
        raise ValueError('Boot serialization requires Linux root')
    area = host_storage.canonical(area)
    area.mkdir(mode=0o700, exist_ok=True)
    host_layout.metadata(area.lstat(), mode=0o700, directory=True)
    descriptor = os.open(area/'lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(descriptor)
        host_layout.metadata(info, mode=0o600)
        if info.st_size or info.st_nlink != 1:
            raise ValueError('Invalid boot-control lock')
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield area
    finally:
        os.close(descriptor)  # Never unlink the shared lock inode.


def private_file(path, body):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb') as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(body); stream.flush(); os.fsync(stream.fileno())


class ToolEnvironment:
    """A pre-admitted configuration inside a private, locked operation directory."""
    def __init__(self, directory, role, tools=None):
        self.directory, self.role = Path(directory), role
        self.tools = tools if tools is not None else TOOLS
        if (role not in host_layout.ROLES or set(self.tools) != set(TOOLS)
                or any(not PurePosixPath(path).is_absolute() for path in self.tools.values())):
            raise ValueError('Invalid environment tool interface')

    def arguments(self, operation):
        return [self.tools[operation], '-c', str(self.directory/'fw_env.config'),
                '-f', str(self.directory/'no-default-env')]

    # @llr LLR-SRV-HOST-023, LLR-SRV-HOST-026, LLR-TERM-MAINT-050, LLR-TERM-MAINT-053
    def read(self):
        return boot_state.decode(boot_devices.bounded_probe(self.arguments('print')+list(boot_state.KEYS)),
                                 self.role)

    # @llr LLR-SRV-HOST-024, LLR-SRV-HOST-026, LLR-TERM-MAINT-051, LLR-TERM-MAINT-053
    def commit(self, expected, candidate):
        if (not isinstance(expected, boot_state.State) or not isinstance(candidate, boot_state.State)
                or expected.role != self.role or candidate.role != self.role
                or expected.generation == boot_state.LIMIT
                or candidate.generation != expected.generation+1 or self.read() != expected):
            raise ValueError('Stale or invalid boot-state mutation')
        script = self.directory/'change.env'
        private_file(script, boot_state.encode(candidate))
        try:
            # One native transaction updates the entire fixed-key contract.
            subprocess.run(self.arguments('set')+['-s', str(script)], check=True, timeout=15,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
            if self.read() != candidate:
                raise ValueError('Boot-state commit did not read back exactly')
        finally:
            script.unlink(missing_ok=True)
        return candidate


# @llr LLR-SRV-HOST-026, LLR-TERM-MAINT-053
def medium(system, root, data, root_uuid, selected, *, model_path=Path('/proc/device-tree/model')):
    """Bind the reserved raw gap to the actual current root, never a label search."""
    event = boot_layout.probe_record(boot_devices.read(root.parent/'uevent', boot_layout.MAX_PROBE_BYTES))
    name = event.get('DEVNAME', '')
    if (event.get('DEVTYPE') != 'disk' or not re.fullmatch(r'mmcblk[0-9]+', name)
            or boot_devices.read(root.parent/'device/type').strip() != b'SD'):
        raise ValueError('Boot-state writes require the supported onboard SD transport')
    with model_path.open('rb') as stream:
        model = stream.read(257)
    if (not 0 < len(model) <= 256 or not model.endswith(b'\0') or b'\0' in model[:-1]
            or not model.startswith(b'Raspberry Pi 4 Model B Rev ')):
        raise ValueError('Boot-state writes require the qualified board family')
    node = system.device_root/name
    info = node.lstat()
    if not stat.S_ISBLK(info.st_mode) or info.st_rdev != os.makedev(*boot_layout.device_number(root.parent_device)):
        raise ValueError('Parent block node differs from selected root topology')
    sectors = boot_devices.positive(boot_devices.read(root.parent/'size').decode().strip(), (2**63-1)//512)
    if boot_devices.read(root.parent/'queue/logical_block_size').strip() != b'512':
        raise ValueError('Unsupported SD logical-sector size')
    descriptor = os.open(node, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb', buffering=0) as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISBLK(opened.st_mode) or opened.st_rdev != info.st_rdev:
            raise ValueError('Parent block identity changed while opening')
        table = boot_media.inspect(stream, sectors*512)
    boot_media.environment_ranges(table)
    for partition in (root, data):
        row = table['partitions'][partition.number-1]
        start = boot_devices.positive(boot_devices.read(partition.parent/partition.node.name/'start').decode().strip(), 2**63-1)
        if (row['first_lba'] != start or row['bytes'] != partition.sectors*512
                or row['type'] != boot_layout.LINUX_PARTITION
                or row['uuid'] != system.probe(partition)['PART_ENTRY_UUID']):
            raise ValueError('GPT geometry differs from actual kernel partition')
    row = table['partitions'][3 if selected == 'A' else 4]
    if row['uuid'] != root_uuid:
        raise ValueError('GPT root identity differs from the current boot')
    return node


# @llr LLR-SRV-HOST-026, LLR-TERM-MAINT-053, LLR-SRV-HOST-029, LLR-TERM-MAINT-056
@contextmanager
def open_control():
    if platform.system() != 'Linux' or os.geteuid() != 0:
        raise ValueError('Boot control requires the image-managed Linux root context')
    system = boot_devices.NativeBoot(tools=RUNNING_BOOT_TOOLS)
    # The independent startup gate rechecks marked policy, all mounts and identity.
    boot_gate.verify(system=system)
    role = boot_storage.configured_role()
    boot_state.decode_policy(host_storage.read_record(Path('/'), boot_state.PROFILE, 0o644, 4096), role)
    selected, identity = system.boot_arguments()
    with lock(Path('/run/zmala-boot-state')) as area:
        root, data = boot_devices.discover(system, boot_layout.profile(role), selected, identity,
                                          system.facts()[Path('/')].device)
        node = medium(system, root, data, identity, selected)
        with tempfile.TemporaryDirectory(prefix='operation-', dir=area) as folder:
            directory = Path(folder)
            private_file(directory/'fw_env.config', ''.join(
                f'{node} {offset:#x} {boot_media.ENV_BYTES:#x}\n' for offset in boot_media.ENV_OFFSETS).encode())
            # Empty explicit defaults make two invalid CRC copies a failure,
            # rather than allowing the tool to import a host default environment.
            private_file(directory/'no-default-env', b'')
            environment = ToolEnvironment(directory, role)
            environment.storage = system, root, data, node, identity
            yield environment, selected
