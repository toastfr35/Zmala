"""Build-tool checks for the conventional standalone Server layout."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from zmala_images import local_repo, server_single


class ServerSingleTests(unittest.TestCase):
    def test_server_excludes_rauc_from_authenticated_input_set(self):
        for role in ('server', 'terminal', 'combined'):
            with patch.object(local_repo, 'inputs', return_value=({'rauc': object(), 'nodejs': object()}, ['pin'])):
                selected, locks = local_repo.role_inputs(role, [])
            self.assertEqual('rauc' in selected, role != 'server')
            self.assertIn('nodejs', selected)
            self.assertEqual(locks, ['pin'])

    def test_native_boot_and_mount_table_agree(self):
        config, cmdline, fstab = server_single.boot_configuration('15fa098b')
        self.assertIn('initramfs initramfs8 followkernel', config)
        self.assertIn('root=PARTUUID=15fa098b-02', cmdline.split())
        self.assertIn('rw', cmdline.split())
        self.assertIn('PARTUUID=15fa098b-02 / ext4', fstab)
        self.assertIn('PARTUUID=15fa098b-01 /boot/firmware vfat', fstab)
        for invalid in ('00000000', 'abcd', '00000000\nroot=/dev/sda'):
            with self.assertRaises(ValueError):
                server_single.boot_configuration(invalid)

    def test_configure_refuses_a_server_root_with_rauc(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root/'usr/bin/rauc'
            path.parent.mkdir(parents=True)
            path.touch()
            with patch.object(server_single, 'firmware_kernel_version', return_value='version'), \
                    patch.object(server_single, 'payload', return_value=b'fixture'), \
                    self.assertRaisesRegex(ValueError, 'Found RAUC'):
                server_single.configure(root, root/'export', '15fa098b')
