"""Bounded read-only GPT inspection and fixed raw-environment range fencing.

The parser accepts a caller-owned seekable stream and its independently obtained
size. Opening an actual block device and binding it to current boot belongs to
boot_environment; build tools may inspect only regular image files.
"""
import struct
import uuid
import zlib

LABELS = ('bootconfig', 'boot_a', 'boot_b', 'system_a', 'system_b', 'persistent')
MAX_TABLE = 4*1024*1024
ENV_OFFSETS = (1048576, 5242880)
ENV_BYTES = 65536
FIRST_PARTITION_BYTES = 8*1024**2


# @llr LLR-SRV-HOST-026, LLR-TERM-MAINT-053
def header(stream, lba, sector, sectors):
    stream.seek(lba*sector)
    raw = stream.read(sector)
    if len(raw) != sector or raw[:8] != b'EFI PART':
        raise ValueError('Missing GPT header')
    revision, size, checksum, reserved = struct.unpack_from('<4I', raw, 8)
    if revision != 0x10000 or not 92 <= size <= sector or reserved or raw[56:72] == bytes(16):
        raise ValueError('Invalid GPT header format')
    checked = bytearray(raw[:size]); struct.pack_into('<I', checked, 16, 0)
    if zlib.crc32(checked) != checksum:
        raise ValueError('GPT header checksum mismatch')
    current, other, first, last = struct.unpack_from('<4Q', raw, 24)
    table_lba, count, width, table_crc = struct.unpack_from('<Q3I', raw, 72)
    if (current != lba or other != (sectors-1 if lba == 1 else 1)
            or not 2 < first <= last < sectors-1
            or not 128 <= width <= 4096 or width % 128 or not count
            or count*width > MAX_TABLE):
        raise ValueError('Invalid GPT bounds')
    table_sectors = (count*width+sector-1)//sector
    valid = (2 <= table_lba and table_lba+table_sectors <= first) if lba == 1 else (
        last < table_lba and table_lba+table_sectors <= sectors-1)
    if not valid:
        raise ValueError('GPT table overlaps usable disk area')
    stream.seek(table_lba*sector)
    table = stream.read(count*width)
    if len(table) != count*width or zlib.crc32(table) != table_crc:
        raise ValueError('GPT partition-array checksum mismatch')
    return {'first': first, 'last': last, 'guid': raw[56:72], 'count': count,
            'width': width, 'table': table}, (table_lba, table_lba+table_sectors)


# @llr LLR-SRV-HOST-026, LLR-TERM-MAINT-053
def inspect(stream, size, sector=512):
    if type(sector) is not int or sector not in (512, 4096):
        raise ValueError('Supported sector sizes are 512 and 4096 bytes')
    if type(size) is not int or size % sector or size < sector*68 or size > 2**63-1:
        raise ValueError('Invalid image byte length')
    sectors = size//sector
    stream.seek(0); mbr = stream.read(512)
    if (len(mbr) != 512 or mbr[510:512] != b'\x55\xaa' or mbr[446] != 0 or mbr[450] != 0xee
            or struct.unpack_from('<2I', mbr, 454) != (1, min(sectors-1, 2**32-1))
            or mbr[462:510] != bytes(48)):
        raise ValueError('Missing protective MBR')
    primary, first_table = header(stream, 1, sector, sectors)
    backup, last_table = header(stream, sectors-1, sector, sectors)
    if primary != backup:
        raise ValueError('Primary and backup GPT disagree')
    partitions, ids = [], set()
    for index in range(primary['count']):
        row = primary['table'][index*primary['width']:(index+1)*primary['width']]
        if row[:16] == bytes(16):
            if row != bytes(primary['width']):
                raise ValueError('Unexpected data in an unused GPT entry')
            continue
        identity = row[16:32]
        first, last = struct.unpack_from('<2Q', row, 32)
        if identity in (bytes(16), b'\xff'*16) or identity in ids:
            raise ValueError('Missing or duplicate partition identity')
        ids.add(identity)
        if not primary['first'] <= first <= last <= primary['last']:
            raise ValueError('Partition outside usable bounds')
        label = row[56:128].decode('utf-16-le').split('\0', 1)[0]
        if row[56:128] != label.encode('utf-16-le').ljust(72, b'\0'):
            raise ValueError('Noncanonical GPT partition label')
        partitions.append({'index': index+1, 'label': label,
                           'first_lba': first, 'last_lba': last,
                           'bytes': (last-first+1)*sector,
                           'type': str(uuid.UUID(bytes_le=row[:16])),
                           'uuid': str(uuid.UUID(bytes_le=identity))})
    if (tuple(p['label'] for p in partitions) != LABELS
            or tuple(p['index'] for p in partitions) != tuple(range(1, 7))):
        raise ValueError('Not the pinned six-partition A/B layout')
    for previous, following in zip(partitions, partitions[1:]):
        if previous['last_lba'] >= following['first_lba']:
            raise ValueError('Overlapping or unordered partitions')
    if partitions[1]['bytes'] != partitions[2]['bytes'] or partitions[3]['bytes'] != partitions[4]['bytes']:
        raise ValueError('A/B slot sizes differ')
    return {'partitions': partitions, 'metadata_end': first_table[1]*sector,
            'backup_metadata_start': last_table[0]*sector, 'image_bytes': size, 'sector_bytes': sector}


# @llr LLR-SRV-HOST-026, LLR-TERM-MAINT-053
def environment_ranges(table):
    if table['sector_bytes'] != 512:
        raise ValueError('The experimental SD environment requires 512-byte sectors')
    boundary = table['partitions'][0]['first_lba']*512
    if boundary < FIRST_PARTITION_BYTES:
        raise ValueError('The first partition overlaps the reserved environment gap')
    ranges = tuple((offset, offset+ENV_BYTES) for offset in ENV_OFFSETS)
    if (table['metadata_end'] > ranges[0][0] or ranges[0][1] > ranges[1][0]
            or ranges[1][1] > boundary or boundary >= table['backup_metadata_start']):
        raise ValueError('Environment ranges overlap partition metadata or filesystems')
    return ranges
