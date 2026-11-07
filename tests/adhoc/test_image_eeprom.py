"""Offline image-build EEPROM guard; not installed product-runtime verification."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from zmala_images import eeprom_policy, inspect_root, project


class EepromBuildPolicyTests(unittest.TestCase):
    def root(self, folder):
        root = Path(folder)
        (root/'etc/rpi-image-gen').mkdir(parents=True)
        unit = root/eeprom_policy.VENDOR
        unit.parent.mkdir(parents=True)
        unit.write_text('[Service]\nExecStart=/usr/bin/rpi-eeprom-update -s -a\n')
        return root

    def test_vendor_service_is_reported_without_reading_or_running_it(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.root(folder)
            # Invalid text is immaterial: policy only checks unit presence.
            (root/eeprom_policy.VENDOR).write_bytes(b'\xff\xfe')
            result = inspect_root.audit(root)
            self.assertIn('unmasked-eeprom-update-service', result['violations'])
            self.assertFalse(result['production_qualified'])

    def test_host_root_and_non_image_directory_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'host filesystem root'):
            eeprom_policy.prepare(Path.cwd().anchor)
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'imagegen root marker'):
                eeprom_policy.prepare(folder)

    def test_existing_override_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.root(folder)
            mask = root/eeprom_policy.MASK
            mask.parent.mkdir(parents=True)
            mask.write_text('operator override')
            with self.assertRaisesRegex(ValueError, 'existing.*override'):
                eeprom_policy.prepare(root)
            self.assertEqual(mask.read_text(), 'operator override')

    def test_both_roles_emit_an_explicit_self_contained_hook_with_lf(self):
        for role in ('server', 'terminal'):
            with self.subTest(role=role), tempfile.TemporaryDirectory() as folder:
                output = Path(folder)/'project'
                project.emit_lab(role, output)
                hook = output/'layer/zmala-probe-eeprom.d/hooks/customize99-zmala-eeprom-scope'
                self.assertTrue(hook.is_file())
                self.assertTrue(hook.read_bytes().startswith(b'#!/usr/bin/env python3\n'))
                self.assertNotIn(b'\r', hook.read_bytes())
                self.assertNotIn('from build_tools', hook.read_text())
                self.assertIn('eeprom_scope: zmala-probe-eeprom', (output/'probe.yaml').read_text())
                self.assertIn('X-Env-Layer-Requires: trixie-minbase',
                              (output/'layer/zmala-probe-eeprom.yaml').read_text())

    @unittest.skipIf(os.name == 'nt', 'Unix image-root symlink masks')
    def test_mask_is_idempotent_and_removes_the_specific_inspection_violation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.root(folder)
            original = (root/eeprom_policy.VENDOR).read_bytes()
            eeprom_policy.prepare(root)
            eeprom_policy.prepare(root)
            mask = root/eeprom_policy.MASK
            self.assertEqual(mask.readlink().as_posix(), '/dev/null')
            self.assertEqual((root/eeprom_policy.VENDOR).read_bytes(), original)
            result = inspect_root.audit(root)
            self.assertNotIn('unmasked-eeprom-update-service', result['violations'])
            self.assertFalse(result['production_qualified'])

    @unittest.skipIf(os.name == 'nt', 'Unix image-root symlink guards')
    def test_linked_parent_and_retargeted_mask_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as outside:
            root = Path(folder)
            (root/'etc').symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'policy parent'):
                eeprom_policy.prepare(root)
            self.assertEqual(list(Path(outside).iterdir()), [])
            self.assertIn('uninspectable-eeprom-policy', inspect_root.audit(root)['violations'])
        with tempfile.TemporaryDirectory() as folder:
            root = self.root(folder)
            mask = root/eeprom_policy.MASK
            mask.parent.mkdir(parents=True)
            mask.symlink_to('/outside-image')
            with self.assertRaisesRegex(ValueError, 'existing.*override'):
                eeprom_policy.prepare(root)
            self.assertEqual(mask.readlink().as_posix(), '/outside-image')

    @unittest.skipIf(os.name == 'nt', 'Executable Unix build hook')
    def test_emitted_hook_runs_without_the_repository_on_python_path(self):
        with tempfile.TemporaryDirectory() as folder:
            parent = Path(folder)
            root = self.root(parent/'root')
            project.emit_lab('terminal', parent/'project')
            hook = parent/'project/layer/zmala-probe-eeprom.d/hooks/customize99-zmala-eeprom-scope'
            result = subprocess.run([str(hook), str(root)], cwd=parent,
                                    env=dict(os.environ, PYTHONPATH=''),
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((root/eeprom_policy.MASK).readlink().as_posix(), '/dev/null')


if __name__ == '__main__':
    unittest.main()
