"""Offline boot-volume preflight regressions, not Pi boot qualification."""
from pathlib import Path
import struct
import tempfile
import unittest
import uuid
import zlib

from zmala_images import inspect_boot


def fat_header(kind='FAT16', *, undersized=False):
    """Representative 32 MiB FAT16 and 128 MiB FAT32 BPB footprints."""
    data = bytearray(512)
    data[510:512] = b'\x55\xaa'
    struct.pack_into('<H', data, 11, 512)
    data[16] = 2
    if kind == 'FAT16':
        data[13] = 4
        struct.pack_into('<H', data, 14, 4)
        struct.pack_into('<H', data, 17, 512)
        struct.pack_into('<H', data, 22, 64)
        struct.pack_into('<I', data, 32, 65536)
    else:
        data[13] = 1
        struct.pack_into('<H', data, 14, 32)
        struct.pack_into('<I', data, 32, 65536 if undersized else 262144)
        struct.pack_into('<I', data, 36, 504 if undersized else 2048)
        struct.pack_into('<I', data, 44, 2)
    return data


def disk(path, sector):
    """Sparse six-partition GPT fixture with independently checksummed copies."""
    count, width = 128, 128
    table = bytearray(count*width)
    first = 64
    starts = []
    for index, (name, length) in enumerate(zip(
            ('bootconfig', 'boot_a', 'boot_b', 'system_a', 'system_b', 'persistent'),
            (262144, 262144, 262144, 10, 10, 10))):
        starts.append(first)
        offset = index*width
        table[offset:offset+16] = uuid.UUID(int=99).bytes_le
        table[offset+16:offset+32] = uuid.UUID(int=index+1).bytes_le
        struct.pack_into('<2Q', table, offset+32, first, first+length-1)
        label = name.encode('utf-16-le')
        table[offset+56:offset+56+len(label)] = label
        first += length
    sectors = first+64
    with path.open('wb') as stream:
        stream.truncate(sector*sectors)
        mbr = bytearray(512)
        mbr[450] = 0xee
        struct.pack_into('<2I', mbr, 454, 1, sectors-1)
        mbr[510:512] = b'\x55\xaa'
        stream.write(mbr)
        for current, other, rows in ((1, sectors-1, 2), (sectors-1, 1, sectors-33)):
            hdr = bytearray(sector)
            hdr[:8] = b'EFI PART'
            struct.pack_into('<4I4Q', hdr, 8, 0x10000, 92, 0, 0, current, other, 34, sectors-34)
            hdr[56:72] = uuid.UUID(int=42).bytes_le
            struct.pack_into('<Q3I', hdr, 72, rows, count, width, zlib.crc32(table))
            struct.pack_into('<I', hdr, 16, zlib.crc32(hdr[:92]))
            stream.seek(current*sector)
            stream.write(hdr)
            stream.seek(rows*sector)
            stream.write(table)
        for index, start in enumerate(starts[:3]):
            stream.seek(start*sector)
            stream.write(fat_header('FAT16' if index == 0 else 'FAT32'))
    return starts


class ImageBootTests(unittest.TestCase):
    def test_valid_geometry_does_not_claim_bootability(self):
        for kind, clusters in (('FAT16', 16343), ('FAT32', 258016)):
            result = inspect_boot.header(fat_header(kind), 128*1024*1024)
            self.assertEqual(result['format'], kind)
            self.assertEqual(result['clusters'], clusters)

    def test_forced_small_fat32_is_rejected_even_with_valid_signature(self):
        with self.assertRaisesRegex(ValueError, 'at least 65525'):
            inspect_boot.header(fat_header('FAT32', undersized=True), 32*1024*1024)

    def test_invalid_geometry_root_and_table_capacity(self):
        cases = ((11, '<H', 123), (13, 'B', 3), (14, '<H', 0),
                 (16, 'B', 0), (19, '<H', 1), (32, '<I', 0),
                 (22, '<H', 1), (17, '<H', 0))
        for offset, fmt, value in cases:
            with self.subTest(offset=offset):
                data = fat_header()
                struct.pack_into(fmt, data, offset, value)
                with self.assertRaises(ValueError):
                    inspect_boot.header(data, 32*1024*1024)
        for root in (0, 258018):
            data = fat_header('FAT32')
            struct.pack_into('<I', data, 44, root)
            with self.assertRaisesRegex(ValueError, 'root-directory'):
                inspect_boot.header(data, 128*1024*1024)
        for data in (b'', fat_header()[:-1], bytes(512)):
            with self.assertRaisesRegex(ValueError, 'signature'):
                inspect_boot.header(data, 32*1024*1024)
        with self.assertRaisesRegex(ValueError, 'geometry'):
            inspect_boot.header(fat_header(), 1024)

    def test_full_gpt_preflight_and_named_volume_failure_are_read_only(self):
        with tempfile.TemporaryDirectory() as folder:
            for sector in (512, 4096):
                path = Path(folder)/str(sector)
                starts = disk(path, sector)
                before = path.stat()
                result = inspect_boot.audit(path, sector)
                self.assertEqual([v['format'] for v in result['volumes']], ['FAT16', 'FAT32', 'FAT32'])
                self.assertFalse(result['production_qualified'])
                self.assertEqual(path.stat().st_mtime_ns, before.st_mtime_ns)
                self.assertEqual(path.stat().st_size, before.st_size)
                with path.open('r+b') as stream:
                    stream.seek(starts[2]*sector)
                    stream.write(fat_header('FAT32', undersized=True))
                with self.assertRaisesRegex(ValueError, 'boot_b: FAT32'):
                    inspect_boot.audit(path, sector)


if __name__ == '__main__':
    unittest.main()
