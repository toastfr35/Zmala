"""Bounded early-boot commands and same-parent partition discovery.

The production entry uses kernel-owned sysfs and fixed tools copied into its
initramfs. Constructor overrides support isolated fixtures, not saved settings
or command-line options. No method formats or resizes a filesystem.
"""
from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import stat
import subprocess
import time

from . import boot_layout as layout, host_storage


# @llr LLR-SRV-HOST-021, LLR-TERM-MAINT-048
def bounded_probe(arguments, timeout=5):
    """Bound bytes while reading, rather than after an unbounded communicate()."""
    process = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               env={'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'LC_ALL': 'C'})
    deadline, body = time.monotonic()+timeout, bytearray()
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline-time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(arguments, timeout)
                if not selector.select(remaining):
                    continue
                chunk = os.read(process.stdout.fileno(), min(4096, layout.MAX_PROBE_BYTES+1-len(body)))
                if not chunk:
                    result = process.wait(timeout=max(0.01, deadline-time.monotonic()))
                    if result:
                        raise subprocess.CalledProcessError(result, arguments)
                    return bytes(body)
                body.extend(chunk)
                if len(body) > layout.MAX_PROBE_BYTES:
                    raise ValueError('Block probe exceeds its output budget')
    finally:
        process.stdout.close()
        if process.poll() is None:
            try:
                process.kill()
                process.wait(timeout=5)
            except (OSError, subprocess.SubprocessError):
                pass  # Keep the original timeout/probe failure, not cleanup noise.


def read(path, limit=256):
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(path, flags), 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('Expected a kernel attribute or boot record')
        body = stream.read(limit+1)
    if not body or len(body) > limit or b'\0' in body:
        raise ValueError('Invalid or oversized kernel attribute')
    return body


def positive(value, limit):
    if not re.fullmatch(r'[1-9][0-9]{0,18}', value):
        raise ValueError('Invalid kernel partition number or size')
    result = int(value)
    if result > limit:
        raise ValueError('Kernel partition number or size exceeds its budget')
    return result


@dataclass(frozen=True)
class Partition:
    number: int
    device: str
    parent_device: str
    parent: Path
    node: Path
    sectors: int


class NativeBoot(host_storage.NativeMounts):
    def __init__(self, *, device_root=Path('/dev'), sys_blocks=Path('/sys/dev/block'),
                 sys_devices=Path('/sys/devices'), cmdline=Path('/proc/cmdline'), tools=None):
        self.device_root, self.sys_blocks, self.sys_devices, self.cmdline = map(
            Path, (device_root, sys_blocks, sys_devices, cmdline))
        self.tools = tools if tools is not None else {
            name: '/usr/lib/zmala/bin/'+name for name in ('mount', 'umount', 'blkid')}
        if (set(self.tools) != {'mount', 'umount', 'blkid'}
                or any(not PurePosixPath(value).is_absolute() for value in self.tools.values())):
            raise ValueError('Expected fixed absolute boot-tool paths')

    # @llr LLR-SRV-HOST-021, LLR-TERM-MAINT-048
    def run(self, arguments):
        if not arguments or arguments[0] not in ('mount', 'umount'):
            raise ValueError('Unsupported boot mount operation')
        return subprocess.run([self.tools[arguments[0]], *arguments[1:]], check=True,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
                              env={'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'LC_ALL': 'C'})

    # @llr LLR-SRV-HOST-018, LLR-TERM-MAINT-045
    def boot_arguments(self):
        return layout.command_line(read(self.cmdline, layout.MAX_RECORD_BYTES))

    # @llr LLR-SRV-HOST-019, LLR-TERM-MAINT-046
    def partition(self, device):
        major, minor = layout.device_number(device)
        current = (self.sys_blocks/device).resolve(strict=True)
        if not current.is_relative_to(self.sys_devices.resolve()) or current == self.sys_devices.resolve():
            raise ValueError('Block identity escaped the kernel device tree')
        if read(current/'dev').decode().strip() != device:
            raise ValueError('Kernel block identity changed')
        number = positive(read(current/'partition').decode().strip(), 128)
        parent_device = read(current.parent/'dev').decode().strip()
        layout.device_number(parent_device)
        event = layout.probe_record(read(current/'uevent', layout.MAX_PROBE_BYTES))
        name = event.get('DEVNAME', '')
        if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', name)
                or event.get('DEVTYPE') != 'partition' or event.get('PARTN') != str(number)):
            raise ValueError('Invalid kernel partition node')
        node = self.device_root/name
        info = node.lstat()
        if not stat.S_ISBLK(info.st_mode) or info.st_rdev != os.makedev(major, minor):
            raise ValueError('Block node differs from its kernel identity')
        sectors = positive(read(current/'size').decode().strip(), 2**63-1)
        return Partition(number, device, parent_device, current.parent, node, sectors)

    # @llr LLR-SRV-HOST-019, LLR-TERM-MAINT-046
    def data_sibling(self, root, number):
        matches = []
        with os.scandir(root.parent) as entries:
            for count, entry in enumerate(entries, 1):
                if count > 256:
                    raise ValueError('Kernel block parent exceeds its child budget')
                child = Path(entry.path)
                if not (child/'partition').exists():
                    continue
                if positive(read(child/'partition').decode().strip(), 128) == number:
                    candidate = self.partition(read(child/'dev').decode().strip())
                    if candidate.parent != root.parent or candidate.parent_device != root.parent_device:
                        raise ValueError('Data partition is not a sibling of the selected root')
                    matches.append(candidate)
        if len(matches) != 1:
            raise ValueError('Missing or ambiguous data sibling')
        return matches[0]

    # @llr LLR-SRV-HOST-019, LLR-SRV-HOST-021, LLR-TERM-MAINT-046, LLR-TERM-MAINT-048
    def probe(self, partition):
        record = layout.probe_record(bounded_probe([self.tools['blkid'], '-p', '-o', 'export', str(partition.node)]))
        # Bind returned filesystem geometry to this kernel partition, not just
        # an attacker-controlled label in a filesystem superblock.
        filesystem_bytes = positive(record.get('FSSIZE', ''), 2**63-1)
        if filesystem_bytes > partition.sectors*512:
            raise ValueError('Filesystem exceeds its kernel partition boundary')
        return record


# @llr LLR-SRV-HOST-019, LLR-TERM-MAINT-046
def discover(system, policy, slot, root_uuid, mounted_device):
    root = system.partition(mounted_device)
    key = 'root_'+slot.lower()
    if root.number != policy[key+'_partition']:
        raise ValueError('Mounted root is not the selected slot')
    root_record = layout.check_probe(system.probe(root), root.number, policy[key+'_label'],
                                     root.parent_device, root_uuid)
    data = system.data_sibling(root, policy['data_partition'])
    if (data.number != policy['data_partition']
            or data.parent != root.parent or data.parent_device != root.parent_device
            or data.device == root.device):
        raise ValueError('Data must be separate and on the selected root parent')
    data_record = layout.check_probe(system.probe(data), data.number, policy['data_label'], data.parent_device)
    if (data_record['UUID'] == root_record['UUID']
            or data_record['PART_ENTRY_UUID'] == root_record['PART_ENTRY_UUID']):
        raise ValueError('Root and data have conflicting identities')
    return root, data
