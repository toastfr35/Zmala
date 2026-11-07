"""Read-only FAT geometry checks for the three boot volumes in a probe image.

GPT checks alone cannot catch an undersized forced FAT32 filesystem. This checks
its BPB footprint, not file chains, firmware contents, signatures or bootability.
"""
from pathlib import Path
import struct

from . import inspect_disk


def header(data, partition_bytes):
    if len(data) != 512 or data[510:512] != b'\x55\xaa':
        raise ValueError('Missing FAT boot-sector signature')
    bps = struct.unpack_from('<H', data, 11)[0]
    spc = data[13]
    reserved = struct.unpack_from('<H', data, 14)[0]
    fats = data[16]
    root_entries = struct.unpack_from('<H', data, 17)[0]
    sectors16 = struct.unpack_from('<H', data, 19)[0]
    fat16 = struct.unpack_from('<H', data, 22)[0]
    sectors32 = struct.unpack_from('<I', data, 32)[0]
    sectors = sectors16 or sectors32
    if (bps not in (512, 1024, 2048, 4096) or spc not in (1, 2, 4, 8, 16, 32, 64, 128)
            or reserved == 0 or fats not in (1, 2) or sectors == 0
            or (sectors16 and sectors32) or sectors*bps > partition_bytes):
        raise ValueError('Invalid FAT boot-volume geometry')
    fat_sectors = fat16 or struct.unpack_from('<I', data, 36)[0]
    root_sectors = (root_entries*32+bps-1)//bps
    data_sectors = sectors-reserved-fats*fat_sectors-root_sectors
    if fat_sectors == 0 or data_sectors <= 0:
        raise ValueError('FAT metadata consumes the boot volume')
    clusters = data_sectors//spc
    if fat16 == 0:
        if root_entries or sectors16 or not 65525 <= clusters < 0x0ffffff5:
            raise ValueError('FAT32 boot volume needs at least 65525 data clusters; use FAT16 or a larger volume')
        root_cluster = struct.unpack_from('<I', data, 44)[0]
        if not 2 <= root_cluster < clusters+2:
            raise ValueError('Invalid FAT32 root-directory cluster')
        width = 4
        kind = 'FAT32'
    else:
        if not root_entries or not 4085 <= clusters < 65525:
            raise ValueError('Invalid FAT16 boot-volume footprint')
        width = 2
        kind = 'FAT16'
    if fat_sectors*bps//width < clusters+2:
        raise ValueError('FAT table is too short for the data clusters')
    return {'format': kind, 'clusters': clusters, 'bytes_per_sector': bps,
            'sectors_per_cluster': spc, 'filesystem_bytes': sectors*bps}


def audit(image, sector=512):
    # The GPT inspector rejects device paths, linked input, corrupt tables and
    # unexpected layouts before any filesystem offsets are used.
    layout = inspect_disk.audit(image, sector)
    volumes = []
    with Path(image).open('rb') as stream:
        for partition in layout['partitions'][:3]:
            stream.seek(partition['first_lba']*sector)
            try:
                info = header(stream.read(512), partition['bytes'])
            except ValueError as error:
                raise ValueError(partition['label']+': '+str(error)) from error
            volumes.append({'partition': partition['label'], **info})
    return {'schema': 1, 'checks': 'probe-gpt-and-fat-geometry',
            'volumes': volumes, 'production_qualified': False}
