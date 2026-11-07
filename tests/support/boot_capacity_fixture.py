"""Synthetic sparse GPT bytes; no production media or application data."""
import struct
import uuid
import zlib

from zmala_system import boot_capacity as capacity, boot_media

IDS = [str(uuid.UUID(int=n)) for n in range(1, 7)]


class MemoryDisk:
    def __init__(self, size):
        self.size, self.position, self.bytes = size, 0, {}

    def seek(self, position):
        self.position = position

    def read(self, length):
        length = min(length, self.size-self.position)
        body = bytes(self.bytes.get(n, 0) for n in range(self.position, self.position+length))
        self.position += length
        return body

    def write(self, body):
        assert self.position+len(body) <= self.size
        self.bytes.update(enumerate(body, self.position))
        self.position += len(body)
        return len(body)

    def flush(self):
        pass

    def fileno(self):
        return 999  # Only used with an explicitly mocked fsync in portable LLT.


def seed(stream):
    size = capacity.IMAGE_BYTES
    table = bytearray(16384)
    offset = boot_media.FIRST_PARTITION_BYTES
    for index, (name, length) in enumerate(zip(boot_media.LABELS, capacity.SIZES)):
        row = index*128
        kind = capacity.FAT_TYPE if index < 3 else '0fc63daf-8483-4772-8e79-3d69d8477de4'
        table[row:row+16] = uuid.UUID(kind).bytes_le
        table[row+16:row+32] = uuid.UUID(IDS[index]).bytes_le
        struct.pack_into('<2Q', table, row+32, offset//512, (offset+length)//512-1)
        table[row+56:row+128] = name.encode('utf-16-le').ljust(72, b'\0')
        offset += length
    mbr = bytearray(512); mbr[450] = 0xee; mbr[510:] = b'\x55\xaa'
    struct.pack_into('<2I', mbr, 454, 1, size//512-1)
    stream.seek(0); stream.write(mbr)
    for current, other, array in ((1, size//512-1, 2), (size//512-1, 1, size//512-33)):
        header = bytearray(512); header[:8] = b'EFI PART'
        struct.pack_into('<4I4Q', header, 8, 0x10000, 92, 0, 0, current, other, 2048, size//512-34)
        header[56:72] = uuid.UUID(int=99).bytes_le
        struct.pack_into('<Q3I', header, 72, array, 128, 128, zlib.crc32(table))
        struct.pack_into('<I', header, 16, zlib.crc32(header[:92]))
        stream.seek(current*512); stream.write(header)
        stream.seek(array*512); stream.write(table)


def memory(size=16000000000):
    stream = MemoryDisk(size)
    seed(stream)
    return stream
