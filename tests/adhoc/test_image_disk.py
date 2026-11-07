"""Read-only image artifact verification; not product runtime/boot evidence."""
import os
from pathlib import Path
import tempfile
import unittest

from zmala_images import inspect_disk


from tests.support.gpt_fixture import image


class ImageDiskTests(unittest.TestCase):
    def test_gpt_in_both_sector_formats_without_qualifying_boot(self):
        with tempfile.TemporaryDirectory() as temporary:
            for sector in (512, 4096):
                path = Path(temporary)/str(sector)
                image(path, sector)
                before = path.read_bytes()
                result = inspect_disk.audit(path, sector)
                self.assertEqual([p['label'] for p in result['partitions']],
                                 ['bootconfig', 'boot_a', 'boot_b', 'system_a', 'system_b', 'persistent'])
                self.assertFalse(result['production_qualified'])
                self.assertEqual(path.read_bytes(), before)

    def test_header_array_and_backup_corruption(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'image'
            for offset in (512+16, 2*512+16, 2047*512+16):
                image(path)
                with path.open('r+b') as stream:
                    stream.seek(offset)
                    changed = stream.read(1)[0] ^ 1
                    stream.seek(offset)
                    stream.write(bytes([changed]))
                with self.assertRaisesRegex(ValueError, 'checksum'):
                    inspect_disk.audit(path)

    def test_individually_valid_inconsistent_or_unsafe_layouts(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'image'
            for options, message in (({'overlap': True}, 'Overlapping'),
                                     ({'unequal': True}, 'sizes differ'),
                                     ({'backup_differs': True}, 'disagree')):
                image(path, **options)
                with self.assertRaisesRegex(ValueError, message):
                    inspect_disk.audit(path)

    def test_plain_or_truncated_files_are_not_disk_images(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'image'
            path.write_bytes(b'not-an-image')
            with self.assertRaisesRegex(ValueError, 'length'):
                inspect_disk.audit(path)
            path.write_bytes(bytes(512*100))
            with self.assertRaisesRegex(ValueError, 'MBR'):
                inspect_disk.audit(path)
            with self.assertRaisesRegex(ValueError, 'sector sizes'):
                inspect_disk.audit(path, 123)

    @unittest.skipIf(os.name == 'nt', 'Linux builder filesystem links')
    def test_linked_input_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'image'
            image(path)
            link = Path(temporary)/'link'
            link.symlink_to(path)
            with self.assertRaisesRegex(ValueError, 'regular image'):
                inspect_disk.audit(link)


if __name__ == '__main__':
    unittest.main()
