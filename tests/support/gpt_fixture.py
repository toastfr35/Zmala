"""Deterministic new regular GPT images for parser and packaging checks only."""
import struct
import uuid
import zlib


def image(path, sector=512, overlap=False, unequal=False, backup_differs=False, first_lba=64):
    count, width, sectors = 128, 128, first_lba+1984
    table = bytearray(count*width)
    names = ('bootconfig', 'boot_a', 'boot_b', 'system_a', 'system_b', 'persistent')
    for i, name in enumerate(names):
        first = first_lba+i*20
        if overlap and i == 2:
            first = 85
        last = first+9+(1 if unequal and i == 2 else 0)
        offset = i*width
        table[offset:offset+16] = uuid.UUID('0fc63daf-8483-4772-8e79-3d69d8477de4').bytes_le
        table[offset+16:offset+32] = uuid.UUID(int=i+1).bytes_le
        struct.pack_into('<2Q', table, offset+32, first, last)
        label = name.encode('utf-16-le')
        table[offset+56:offset+56+len(label)] = label
    data = bytearray(sector*sectors)
    data[450] = 0xee
    struct.pack_into('<2I', data, 454, 1, sectors-1)
    data[510:512] = b'\x55\xaa'
    for current, other in ((1, sectors-1), (sectors-1, 1)):
        rows = bytearray(table)
        if backup_differs and current != 1:
            rows[16] ^= 1  # Both copies independently valid but inconsistent.
        table_lba = 2 if current == 1 else sectors-1-(len(rows)+sector-1)//sector
        hdr = bytearray(sector)
        hdr[:8] = b'EFI PART'
        struct.pack_into('<4I4Q', hdr, 8, 0x10000, 92, 0, 0, current, other, 34, sectors-34)
        hdr[56:72] = uuid.UUID(int=42).bytes_le
        struct.pack_into('<Q3I', hdr, 72, table_lba, count, width, zlib.crc32(rows))
        struct.pack_into('<I', hdr, 16, zlib.crc32(hdr[:92]))
        data[current*sector:(current+1)*sector] = hdr
        data[table_lba*sector:table_lba*sector+len(rows)] = rows
    path.write_bytes(data)
