"""Native GPT relocation on new sparse files only; never open block devices."""
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import tempfile
import unittest

from zmala_system import boot_capacity as capacity, boot_media
from tests.support.boot_capacity_fixture import IDS


@unittest.skipUnless(platform.system() == 'Linux' and shutil.which('sfdisk'), 'Linux and sfdisk required')
class CapacityLinuxScenario(unittest.TestCase):
    role = 'server'

    def test_real_gpt_16gb_32gb_both_slots_retry_and_preservation(self):
        with tempfile.TemporaryDirectory(prefix='zmala-capacity-') as folder:
            directory = Path(folder).resolve()
            for size in (16000000000, 32000000000):
                for slot in (4, 5):
                    for stop in range(5):
                        with self.subTest(size=size, slot=slot, durable_writes=stop):
                            path = directory/f'{size}-{slot}-{stop}.img'
                            with path.open('xb') as stream:
                                stream.truncate(capacity.IMAGE_BYTES)
                            rows = []; offset = boot_media.FIRST_PARTITION_BYTES
                            for index, (label, length) in enumerate(zip(boot_media.LABELS, capacity.SIZES)):
                                kind = capacity.FAT_TYPE if index < 3 else '0fc63daf-8483-4772-8e79-3d69d8477de4'
                                rows.append(f'start={offset//512}, size={length//512}, type={kind}, uuid={IDS[index]}, name="{label}"')
                                offset += length
                            subprocess.run(['sfdisk', '--no-reread', '--no-tell-kernel', str(path)],
                                           input='label: gpt\nunit: sectors\n\n'+'\n'.join(rows)+'\n',
                                           text=True, capture_output=True, check=True, timeout=30)
                            # The guard precedes every writable open; the fixture owns the new inode.
                            info = path.lstat()
                            self.assertTrue(stat.S_ISREG(info.st_mode))
                            self.assertEqual(path.resolve().parent, directory)
                            with path.open('r+b', buffering=0) as stream:
                                self.assertEqual(os.fstat(stream.fileno()).st_ino, info.st_ino)
                                old = boot_media.inspect(stream, capacity.IMAGE_BYTES)
                                sentinels = {offset: (self.role.encode()+b'-boot-state').ljust(65536, b'X')
                                             for offset in boot_media.ENV_OFFSETS}
                                for row in old['partitions']:
                                    sentinels[row['first_lba']*512] = (row['label'].encode()+b'-preserve').ljust(512, b'Y')
                                for offset, body in sentinels.items():
                                    stream.seek(offset); stream.write(body)
                                stream.truncate(size)
                                arguments = (size, slot, IDS[slot-1], IDS[5])
                                writes = capacity.plan(stream, *arguments)
                                self.assertEqual(len(writes), 4)
                                for offset, body in writes:
                                    for row in old['partitions']:
                                        self.assertFalse(offset < (row['last_lba']+1)*512 and
                                                         offset+len(body) > row['first_lba']*512)
                                capacity.commit(stream, writes[:stop])
                                capacity.commit(stream, capacity.plan(stream, *arguments))
                                self.assertEqual(capacity.plan(stream, *arguments), ())
                                new = boot_media.inspect(stream, size)
                                self.assertEqual(old['partitions'], new['partitions'])
                                for offset, body in sentinels.items():
                                    self.assertEqual(capacity.read_at(stream, offset, len(body)), body)
                            result = subprocess.run(['sfdisk', '--verify', str(path)],
                                                    text=True, capture_output=True, timeout=30)
                            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
