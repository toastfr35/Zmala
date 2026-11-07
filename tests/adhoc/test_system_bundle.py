"""Offline release preparation without signing secrets or a physical device."""
import hashlib
import io
from pathlib import Path
import tempfile
import unittest

from zmala_images import system_bundle


class BundleTests(unittest.TestCase):
    def test_manifest_matches_selected_slot_and_component_versions(self):
        value = system_bundle.manifest('B', '0.4.1', '0.4.4')
        self.assertIn('compatible=zmala-pi4-terminal-v1-b\nversion=0.4.1', value)
        self.assertIn('terminal-version=0.4.4', value)
        self.assertEqual(value.count('[image.'), 2)
        with self.assertRaises(ValueError):
            system_bundle.manifest('B', '0.4.1\n[hooks]', '0.4.4')

    def test_copy_is_bounded_to_exact_extent(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/'boot.vfat'
            body = b'boot\0data'
            disk = io.BytesIO(b'a'*512+body+b'outside')
            digest = system_bundle.copy_extent(disk, {'first_lba': 1, 'bytes': len(body)}, target)
            self.assertEqual(target.read_bytes(), body)
            self.assertEqual(digest, hashlib.sha256(body).hexdigest())
            with self.assertRaises(ValueError):
                system_bundle.copy_extent(disk, {'first_lba': 1, 'bytes': 100}, target.with_suffix('.short'))
