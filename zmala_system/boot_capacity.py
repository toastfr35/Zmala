"""Factory-only compact SD GPT relocation; partition/filesystem sizes never change.

The unchanged primary partition array and either a complete original GPT pair or
a complete new backup allow retry after our metadata writes. This is not a disk
repair utility and does not claim physical power-loss qualification.
"""
import json
import os
from pathlib import Path
import re
import stat
import struct
import zlib

from . import boot_devices, boot_layout, boot_media, device_identity, host_layout, host_storage

PROFILE = 'usr/lib/zmala/media-capacity.json'
SIZES = tuple(n*1024**2 for n in (32, 512, 512, 4096, 4096, 4096))
IMAGE_BYTES = boot_media.FIRST_PARTITION_BYTES+sum(SIZES)+1024**2
MAX_BYTES = 128*1024**3
TABLE_BYTES = 128*128
GPT_FIRST_USABLE = 2+TABLE_BYTES//512
LEGACY_GPT_FIRST_USABLE = 2048
FAT_TYPE = 'ebd0a0a2-b9e5-4433-87c0-68b6b72699c7'


# @llr LLR-SRV-HOST-031, LLR-TERM-MAINT-058
def profile(role):
    host_layout.profile(role)
    return {'schema': 1, 'role': role, 'layout': 'compact-fixed-data-v1',
            'image_bytes': IMAGE_BYTES, 'maximum_media_bytes': MAX_BYTES}


class MetadataView:
    """Read-through metadata overrides, without allocating an entire disk image."""
    def __init__(self, stream, overrides):
        self.stream, self.overrides, self.position = stream, overrides, 0

    def seek(self, offset):
        self.position = offset

    def read(self, count):
        self.stream.seek(self.position)
        body = bytearray(self.stream.read(count))
        for offset, content in self.overrides.items():
            start, end = max(offset, self.position), min(offset+len(content), self.position+count)
            if start < end:
                body[start-self.position:end-self.position] = content[start-offset:end-offset]
        self.position += len(body)
        return bytes(body)


def read_at(stream, offset, count):
    stream.seek(offset)
    body = stream.read(count)
    if len(body) != count:
        raise ValueError('Short media metadata read')
    return body


def make_header(template, size, backup=False):
    body = bytearray(template)
    last = size//512-1
    struct.pack_into('<2Q', body, 24, last if backup else 1, 1 if backup else last)
    struct.pack_into('<Q', body, 48, last-33)
    struct.pack_into('<Q', body, 72, last-32 if backup else 2)
    struct.pack_into('<I', body, 16, 0)
    struct.pack_into('<I', body, 16, zlib.crc32(body[:92]))
    return bytes(body)


# @llr LLR-SRV-HOST-031, LLR-TERM-MAINT-058
def checked_header(stream, lba, size):
    raw = read_at(stream, lba*512, 512)
    value, table_range = boot_media.header(stream, lba, 512, size//512)
    if (struct.unpack_from('<I', raw, 12)[0] != 92 or raw[92:] != bytes(420)
            or value['count'] != 128 or value['width'] != 128
            or value['first'] not in (GPT_FIRST_USABLE, LEGACY_GPT_FIRST_USABLE)
            or value['last'] != size//512-34
            or table_range != ((2, 34) if lba == 1 else (size//512-33, size//512-1))):
        raise ValueError('Not the compact factory GPT format')
    return raw, value


# @llr LLR-SRV-HOST-031, LLR-TERM-MAINT-058
def layout(table, root_number, root_uuid, data_uuid):
    boot_media.environment_ranges(table)
    offset = boot_media.FIRST_PARTITION_BYTES
    for index, (row, size) in enumerate(zip(table['partitions'], SIZES)):
        expected_type = FAT_TYPE if index < 3 else boot_layout.LINUX_PARTITION
        if row['first_lba']*512 != offset or row['bytes'] != size or row['type'] != expected_type:
            raise ValueError('Media is not the fixed compact partition layout')
        offset += size
    if (root_number not in (4, 5) or table['partitions'][root_number-1]['uuid'] != root_uuid
            or table['partitions'][5]['uuid'] != data_uuid):
        raise ValueError('Compact GPT identities differ from this boot')


# @llr LLR-SRV-HOST-031, LLR-TERM-MAINT-058
def plan(stream, size, root_number, root_uuid, data_uuid):
    """Return bounded metadata writes, admitting only the original pair or retry state."""
    if type(size) is not int or size % 512 or not IMAGE_BYTES <= size <= MAX_BYTES:
        raise ValueError('Media cannot hold the compact image or exceeds its capacity bound')
    mbr = bytearray(read_at(stream, 0, 512))
    primary = read_at(stream, 512, 512)
    declared = (struct.unpack_from('<Q', primary, 32)[0]+1)*512
    source = None
    if declared in (IMAGE_BYTES, size):
        try:
            template, source = checked_header(stream, 1, declared)
            checked_header(stream, declared//512-1, declared)
            normalized = bytearray(mbr)
            struct.pack_into('<I', normalized, 458, declared//512-1)
            table = boot_media.inspect(MetadataView(stream, {0: bytes(normalized)}), declared)
        except ValueError:
            source = None
    if source is None:
        # After backup commit, a torn primary header or PMBR count can be retried.
        # The primary array is NEVER written by this operation and must still match.
        template, source = checked_header(stream, size//512-1, size)
        if read_at(stream, 1024, TABLE_BYTES) != source['table']:
            raise ValueError('Primary array differs from the committed relocation backup')
        normalized = bytearray(mbr)
        struct.pack_into('<I', normalized, 458, size//512-1)
        table = boot_media.inspect(MetadataView(stream, {
            0: bytes(normalized), 512: make_header(template, size)}), size)
    layout(table, root_number, root_uuid, data_uuid)
    if any(struct.unpack_from('<Q', source['table'], n*128+48)[0] for n in range(6)):
        raise ValueError('Unexpected compact partition attributes')
    writes = (
        (size-512-TABLE_BYTES, source['table']),
        (size-512, make_header(template, size, backup=True)),
        (512, make_header(template, size)),
        (458, struct.pack('<I', size//512-1)),
    )
    if all(read_at(stream, offset, len(body)) == body for offset, body in writes):
        # Includes the original exact-size image; normal repeated boots write nothing.
        boot_media.inspect(stream, size)
        return ()
    return writes


# @llr LLR-SRV-HOST-031, LLR-TERM-MAINT-058
def commit(stream, writes):
    """Durably commit backup first; read back every bounded write before proceeding."""
    for offset, body in writes:
        stream.seek(offset)
        if stream.write(body) != len(body):
            raise OSError('Short GPT relocation write')
        stream.flush()
        os.fsync(stream.fileno())
        if read_at(stream, offset, len(body)) != body:
            raise OSError('GPT relocation readback mismatch')


# @llr LLR-SRV-HOST-031, LLR-TERM-MAINT-058
def factory(data, role, system):
    device_identity.admit(data, role, system.facts())
    device_identity.factory_record(data, role)
    # A saved identity or initialized application data is never a factory resize request.
    device_identity.names(data, {device_identity.FACTORY, device_identity.LOCK, 'lost+found'})
    recovery = data/'lost+found'
    if device_identity.present(recovery):
        host_layout.metadata(recovery.lstat(), mode=0o700, directory=True)
        device_identity.names(recovery, set())


# @llr LLR-SRV-HOST-031, LLR-TERM-MAINT-058
def medium(system, selected, data, model_path=Path('/proc/device-tree/model')):
    event = boot_layout.probe_record(boot_devices.read(selected.parent/'uevent', boot_layout.MAX_PROBE_BYTES))
    name = event.get('DEVNAME', '')
    if (event.get('DEVTYPE') != 'disk' or not re.fullmatch(r'mmcblk[0-9]+', name)
            or boot_devices.read(selected.parent/'device/type').strip() != b'SD'
            or data.parent != selected.parent or data.parent_device != selected.parent_device
            or boot_devices.read(selected.parent/'queue/logical_block_size').strip() != b'512'):
        raise ValueError('Capacity adaptation requires same-parent onboard SD partitions')
    with model_path.open('rb') as stream:
        model = stream.read(257)
    if (not 0 < len(model) <= 256 or not model.endswith(b'\0') or b'\0' in model[:-1]
            or not model.startswith(b'Raspberry Pi 4 Model B Rev ')):
        raise ValueError('Capacity adaptation requires the experimental Pi 4 board family')
    node = system.device_root/name
    info = node.lstat()
    number = os.makedev(*boot_layout.device_number(selected.parent_device))
    if not stat.S_ISBLK(info.st_mode) or info.st_rdev != number:
        raise ValueError('Parent block node differs from the selected root topology')
    size = boot_devices.positive(boot_devices.read(selected.parent/'size').decode().strip(), MAX_BYTES//512)*512
    for partition in (selected, data):
        expected = boot_media.FIRST_PARTITION_BYTES+sum(SIZES[:partition.number-1])
        start = boot_devices.positive(boot_devices.read(
            partition.parent/partition.node.name/'start').decode().strip(), MAX_BYTES//512)*512
        if (partition.number not in (4, 5, 6) or start != expected
                or partition.sectors*512 != SIZES[partition.number-1]):
            raise ValueError('Kernel partitions differ from the compact geometry')
    return node, number, size


# @llr LLR-SRV-HOST-031, LLR-TERM-MAINT-058
def prepare(root, data, role, system, selected, partition, root_uuid):
    policy = host_storage.safe(root, PROFILE)
    if not device_identity.present(policy):
        return  # Existing noncompact image roots retain their original boot policy.
    body = host_storage.read_record(root, PROFILE, 0o644, 4096)
    value = json.loads(body, object_pairs_hook=host_layout.unique_fields)
    expected = profile(role)
    if value != expected or any(type(value[key]) is not type(item) for key, item in expected.items()):
        raise ValueError('Unsupported media-capacity policy')
    node, number, size = medium(system, selected, partition)
    data_uuid = system.probe(partition)['PART_ENTRY_UUID']

    def opened(mode):
        descriptor = os.open(node, mode | os.O_NOFOLLOW | os.O_NONBLOCK)
        info = os.fstat(descriptor)
        if not stat.S_ISBLK(info.st_mode) or info.st_rdev != number:
            os.close(descriptor)
            raise ValueError('Parent identity changed while opening')
        return os.fdopen(descriptor, 'r+b' if mode == os.O_RDWR else 'rb', buffering=0)

    with opened(os.O_RDONLY) as stream:
        writes = plan(stream, size, selected.number, root_uuid, data_uuid)
    if not writes:
        return
    factory(data, role, system)
    with device_identity.exclusive(data):
        factory(data, role, system)
        with opened(os.O_RDWR) as stream:
            if plan(stream, size, selected.number, root_uuid, data_uuid) != writes:
                raise ValueError('Media metadata changed before relocation')
            commit(stream, writes)
            if plan(stream, size, selected.number, root_uuid, data_uuid):
                raise ValueError('Media adaptation did not commit completely')
