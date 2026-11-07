"""Image build/privacy and acquisition regressions, outside product runtime RBT."""
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from zmala_images import inspect_root, inventory, project, sources


def archive(path, entries):
    with tarfile.open(path, 'w:gz') as output:
        for name, data, kind in entries:
            member = tarfile.TarInfo(name)
            if kind == 'file':
                member.size = len(data)
                output.addfile(member, io.BytesIO(data))
            else:
                member.type = kind
                member.linkname = data
                output.addfile(member)


class ImageSourceTests(unittest.TestCase):
    def test_archive_hash_and_changed_source_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root/'source.tar.gz'
            archive(data, [('tree/tool', b'expected', 'file')])
            manifest = sources.unpack(data, root/'source')
            sources.verify_tree(root/'source', manifest)
            (root/'source/tool').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'does not match'):
                sources.verify_tree(root/'source', manifest)
            pin = sources.pins()['imagegen']
            (root/('imagegen-'+pin['commit']+'.tar.gz')).write_bytes(b'corrupted-cache')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                sources.acquire('imagegen', root, opener=lambda *a, **k: self.fail('unexpected network'))

    def test_archive_attacks_are_rejected_before_any_file_is_written(self):
        cases = [
            [('tree/../../outside', b'x', 'file')],
            [('/absolute/file', b'x', 'file')],
            [('tree/dir\\outside', b'x', 'file')],
            [('tree/file', b'x', 'file'), ('tree/file', b'y', 'file')],
            [('tree/file', b'x', 'file'), ('other/file', b'y', 'file')],
            [('tree/file', b'x', 'file'), ('tree/link', '/etc/shadow', tarfile.SYMTYPE)],
            [('tree/file', b'x', 'file'), ('tree/link', '../../outside', tarfile.SYMTYPE)],
            [('tree/file', b'x', 'file'), ('tree/link', 'file', tarfile.LNKTYPE)],
            [('tree/file', b'x', 'file'), ('tree/link', 'file', tarfile.SYMTYPE),
             ('tree/link/child', b'x', 'file')],
            [('tree/file', b'x', 'file'), ('tree/device', '', tarfile.CHRTYPE)],
        ]
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                archive(root/'bad.tar.gz', case)
                with self.assertRaises(ValueError):
                    sources.unpack(root/'bad.tar.gz', root/'source')
                self.assertFalse((root/'source').exists())

    def test_source_expansion_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive(root/'source.tar.gz', [('tree/a', b'1234', 'file'), ('tree/b', b'5678', 'file')])
            with patch.object(sources, 'MAX_TREE', 7), self.assertRaisesRegex(ValueError, 'budget'):
                sources.unpack(root/'source.tar.gz', root/'source')

    def test_download_identity_and_redirect_rejection(self):
        class Response(io.BytesIO):
            def geturl(self):
                return 'https://untrusted.invalid/source'
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, 'redirect'):
                sources.acquire('imagegen', temporary, opener=lambda *a, **k: Response(b'x'))
            self.assertEqual(list(Path(temporary).iterdir()), [])

    @unittest.skipIf(os.name == 'nt', 'Unix image-builder symlinks need a Linux build host')
    def test_contained_links_preserve_source_and_cannot_be_retargeted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive(root/'source.tar.gz', [('tree/dir/file', b'payload', 'file'),
                    ('tree/dir/link', 'file', tarfile.SYMTYPE)])
            manifest = sources.unpack(root/'source.tar.gz', root/'source')
            sources.verify_tree(root/'source', manifest)
            (root/'source/dir/link').unlink()
            (root/'source/dir/link').symlink_to('/etc/shadow')
            with self.assertRaisesRegex(ValueError, 'link changed'):
                sources.verify_tree(root/'source', manifest)


class ImageInspectionTests(unittest.TestCase):
    def root(self, folder):
        root = Path(folder)
        for name, data in [('etc/machine-id', ''), ('etc/shadow', 'root:!:0:0:99999:7:::\n'),
                           ('var/lib/dpkg/status', 'Package: fixture\n')]:
            path = root/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(data)
        return root

    def test_sanitized_subset_is_not_production_qualification(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = inspect_root.audit(self.root(temporary))
            self.assertEqual(result['violations'], [])
            self.assertFalse(result['production_qualified'])

    def test_factory_identity_credentials_and_imported_state_are_detected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self.root(temporary)
            for name in ('etc/ssh/ssh_host_ed25519_key', 'etc/NetworkManager/system-connections/home',
                         'var/lib/zmalacall/terminal.json', 'opt/app/google-services.json', '.env'):
                path = root/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('fixture-private-material')
            (root/'etc/machine-id').write_text('existing-machine')
            (root/'etc/shadow').write_text('fixture:$6$secret:0:0:99999:7:::\n')
            result = inspect_root.audit(root)
            self.assertIn('factory-machine-id:etc/machine-id', result['violations'])
            self.assertIn('enabled-or-invalid-factory-password', result['violations'])
            self.assertEqual(sum(v.startswith('private-state:') for v in result['violations']), 5)
            self.assertNotIn('secret', json.dumps(result))
            self.assertNotIn('fixture-private-material', json.dumps(result))

    @unittest.skipIf(os.name == 'nt', 'Linux offline image links')
    def test_linked_sensitive_parent_is_never_followed(self):
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as outside:
            root = Path(temporary)
            # If the inspector follows this directory, a malformed shadow would
            # raise; returning an uninspectable category proves it was not read.
            (Path(outside)/'shadow').write_bytes(b'\xff\xfe')
            (root/'etc').symlink_to(outside, target_is_directory=True)
            result = inspect_root.audit(root)
            self.assertIn('uninspectable-passwords:etc/shadow', result['violations'])


class InventoryAndProfileTests(unittest.TestCase):
    def test_probe_cannot_be_confused_with_an_installed_qualified_product(self):
        for role in ('terminal', 'server', 'combined'):
            with tempfile.TemporaryDirectory() as temporary:
                target = Path(temporary)/role
                project.emit_lab(role, target)
                status = json.loads((target/'status.json').read_text())
                for name in ('application_installed', 'packages_locked', 'hardware_qualified', 'production_eligible'):
                    self.assertFalse(status[name])
                self.assertIn('image-rota', (target/'probe.yaml').read_text())
                self.assertIn('version: unqualified-'+role+'-probe1', (target/'probe.yaml').read_text())
                self.assertIn('rauc=', (target/'package-intent.txt').read_text())
                with self.assertRaises(ValueError):
                    project.emit_lab(role, target)

    def test_private_command_errors_are_redacted(self):
        def runner(args, **kwargs):
            self.assertEqual(kwargs['timeout'], 20)
            self.assertNotIn('shell', kwargs)
            return subprocess.CompletedProcess(args, 1, 'private-stdout', 'private-stderr')
        self.assertEqual(inventory.command(['fixture'], runner), {'error': 'command-failed'})
        def timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(['fixture'], 20, stderr='private')
        self.assertEqual(inventory.command(['fixture'], timeout), {'error': 'TimeoutExpired'})

    @unittest.skipIf(os.name == 'nt', 'Linux allocated-block sizing')
    def test_tree_sizing_is_bounded_and_deduplicates_hard_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root/'file').write_bytes(b'payload'*4096)
            os.link(root/'file', root/'second')
            complete = inventory.footprint(root)
            self.assertTrue(complete['complete'])
            self.assertEqual(complete['entries'], 2)  # root plus one inode
            (root/'another').write_text('x')
            self.assertFalse(inventory.footprint(root, limit=2)['complete'])


if __name__ == '__main__':
    unittest.main()
