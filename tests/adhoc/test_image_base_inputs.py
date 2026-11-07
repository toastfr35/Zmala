"""Build input capture/repository regressions, not installed product verification."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from zmala_images import base_intent, local_repo, package_lock, project
from tests.adhoc.test_image_packages import fixture


def ledger(name='example', version='1.0', architecture='arm64', status='install ok installed'):
    return (f'Package: {name}\nStatus: {status}\nArchitecture: {architecture}\n'
            f'Version: {version}\nDescription: ordinary description\n continuation\n\n')


class BaseCaptureTests(unittest.TestCase):
    def test_exact_versions_and_current_installed_state(self):
        value = ledger('two', '2:1.2~rc-1', 'all', 'purge ok installed')+ledger('one', '1.2+b1')
        self.assertEqual(base_intent.selections(value), ['one=1.2+b1', 'two=2:1.2~rc-1'])

    def test_incomplete_ambiguous_mixed_and_unfinished_ledgers_rejected(self):
        for text in ('', ledger()+ledger(), ledger(architecture='amd64'),
                     ledger(status='install ok half-configured'),
                     ledger().replace('Version: 1.0\n', ''),
                     ledger().replace('Version: 1.0\n', 'Version: 1.0\nVersion: 2.0\n'),
                     ledger().replace('Version: 1.0\n', 'Version: 1.0\n 2.0\n'),
                     ledger(name='--unsafe'), ' orphan\n'+ledger()):
            with self.subTest(text=text[:60]), self.assertRaises(ValueError):
                base_intent.selections(text)

    def test_external_hash_size_and_exclusive_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output = root/'status', root/'intent.json'
            source.write_text(ledger(), encoding='utf-8')
            checksum = package_lock.digest(source)
            result = base_intent.emit(source, checksum, output)
            self.assertEqual(result['requested'], ['example=1.0'])
            self.assertFalse(result['image_qualified'])
            with self.assertRaises(FileExistsError):
                base_intent.emit(source, checksum, output)
            with self.assertRaises(ValueError):
                base_intent.capture(source, '0'*64)
            with patch.object(base_intent, 'MAX_LEDGER_BYTES', 1), self.assertRaises(ValueError):
                base_intent.capture(source, checksum)

    @unittest.skipIf(os.name == 'nt', 'Unix special-file rejection')
    def test_links_and_fifo_are_rejected_before_open(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root/'status'; source.write_text(ledger())
            link = root/'linked'; link.symlink_to(source)
            fifo = root/'fifo'; os.mkfifo(fifo)
            for path in (link, fifo):
                with self.assertRaises(ValueError):
                    base_intent.capture(path, '0'*64)

    def test_checked_in_base_anchoring_detects_changes(self):
        self.assertEqual(len(project.common_base()['requested']), 259)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root/'zmala_images/locks'
            shutil.copytree(project.ROOT/'zmala_images/locks', folder)
            for name in ('base-intent.json', 'base.json'):
                path = folder/name
                original = path.read_bytes()
                path.write_bytes(original+b' ')
                with patch.object(project, 'ROOT', root), self.assertRaisesRegex(ValueError, 'digest'):
                    project.common_base()
                path.write_bytes(original)
            index = json.loads((folder/'index.json').read_text())
            index['base']['intent_file'] = '../elsewhere'
            with patch.object(project, 'ROOT', root), self.assertRaises(ValueError):
                project.common_base(index)


class LocalRepositoryTests(unittest.TestCase):
    def test_complete_hash_anchored_input_and_identical_duplicates(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, checksum = fixture(root)
            selected, locks = local_repo.inputs([(root, checksum), (root, checksum)])
            self.assertEqual(list(selected), ['example'])
            self.assertEqual(locks, [checksum])
            with self.assertRaises(ValueError):
                local_repo.inputs([(root, '0'*64)])

    def test_conflicting_versions_architectures_contents_and_identity_rejected(self):
        for field, value in (('version', '2.0'), ('architecture', 'all'), ('package', '--invalid')):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                one, two = root/'one', root/'two'
                _, a = fixture(one)
                manifest, _ = fixture(two)
                manifest['packages'][0][field] = value
                (two/'packages.lock.json').write_text(json.dumps(manifest))
                with self.assertRaises(ValueError):
                    local_repo.inputs([(one, a), (two, package_lock.digest(two/'packages.lock.json'))])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            one, two = root/'one', root/'two'
            _, a = fixture(one); manifest, _ = fixture(two)
            archive = two/'archives'/manifest['packages'][0]['archive']
            archive.write_bytes(b'changed fixture contents')
            manifest['packages'][0].update(bytes=archive.stat().st_size, sha256=package_lock.digest(archive))
            (two/'packages.lock.json').write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                local_repo.inputs([(one, a), (two, package_lock.digest(two/'packages.lock.json'))])

    def test_combined_budget_and_missing_inputs_rejected(self):
        with self.assertRaises(ValueError):
            local_repo.inputs([])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); _, checksum = fixture(root)
            with patch.object(package_lock, 'MAX_BYTES', 1), self.assertRaises(ValueError):
                local_repo.inputs([(root, checksum)])

    def test_index_identity_and_completeness_checked_against_archives(self):
        record = {'version': '1.0', 'architecture': 'arm64', 'archive': 'example.deb', 'bytes': 12, 'sha256': 'a'*64}
        selected = {'example': (None, None, record)}
        text = ('Package: example\nVersion: 1.0\nArchitecture: arm64\n'
                'Filename: pool/example.deb\nSize: 12\nSHA256: '+'a'*64+'\n\n')
        local_repo.audit_index(text, selected)
        for invalid in ('', text+text, text.replace('1.0', '2.0'),
                        text.replace('pool/example.deb', '../escape.deb'), text.replace('arm64', 'all')):
            with self.assertRaises(ValueError):
                local_repo.audit_index(invalid, selected)

    @unittest.skipUnless(os.name != 'nt' and shutil.which('dpkg-deb') and shutil.which('dpkg-scanpackages'),
                         'Linux package build/index tools')
    def test_real_package_export_and_control_mismatch_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = root/'cache'; manifest, _ = fixture(cache)
            package = root/'package'
            (package/'DEBIAN').mkdir(parents=True)
            (package/'DEBIAN/control').write_text('Package: example\nVersion: 1.0\nArchitecture: arm64\n'
                                                'Maintainer: Fixture <test@example.invalid>\nDescription: fixture\n')
            archive = cache/'archives/example_1.0_arm64.deb'
            subprocess.run(['dpkg-deb', '--build', str(package), str(archive)], check=True, capture_output=True)
            manifest['packages'][0].update(bytes=archive.stat().st_size, sha256=package_lock.digest(archive))
            path = cache/'packages.lock.json'; path.write_text(json.dumps(manifest))
            checksum = package_lock.digest(path)
            output = root/'repo'
            result = local_repo.emit([(cache, checksum)], output)
            self.assertEqual(result['packages'], 1)
            self.assertFalse(result['builder_consumption_verified'])
            self.assertTrue((output/'READY.json').is_file())
            self.assertIn('file:', (output/'build-only.list').read_text())
            self.assertEqual(hashlib.sha256((output/'Packages').read_bytes()).hexdigest(), result['index_sha256'])
            self.assertNotEqual(archive.stat().st_ino, (output/'pool'/archive.name).stat().st_ino)
            with self.assertRaises(ValueError):
                local_repo.emit([(cache, checksum)], output)
            manifest['packages'][0]['version'] = '2.0'
            path.write_text(json.dumps(manifest))
            bad = root/'bad'
            with self.assertRaisesRegex(ValueError, 'control identity'):
                local_repo.emit([(cache, package_lock.digest(path))], bad)
            self.assertFalse((bad/'READY.json').exists())

    @unittest.skipIf(os.name == 'nt', 'Unix cache special files')
    def test_retained_lock_trust_and_metadata_fifos_rejected_before_read(self):
        for name in ('packages.lock.json', 'keyrings/debian.gpg', 'apt/lists/'+next(iter(package_lock.RELEASES))):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); _, checksum = fixture(root)
                path = root/name; path.unlink(); os.mkfifo(path)
                with self.assertRaises(ValueError):
                    package_lock.verify(root, checksum)


if __name__ == '__main__':
    unittest.main()
