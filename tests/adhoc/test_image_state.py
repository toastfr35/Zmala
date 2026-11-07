"""Offline archive preparation/packaging checks, outside runtime requirements."""
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from zmala_images import image_state, package_lock
from tests.adhoc.test_image_root_build import SELECTED, write_tar
from zmala_system import host_layout as layout


def fixture(path, extra=None):
    changes = {'var/lib/dpkg/alternatives': ('dir', b''),
               'var/lib/dpkg/alternatives/probe': ('file', b'slot alternative'),
               'var/log': ('dir', b''), 'var/log/vendor': ('file', b'public initial log fixture')}
    changes.update(extra or {})
    write_tar(path, changes)


class PreparedArchiveTests(unittest.TestCase):
    def test_package_state_moves_into_slot_and_runtime_matches_authored_sources(self):
        for role in ('server', 'terminal', 'combined'):
            with self.subTest(role=role), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); source = root/'source.tar'; fixture(source)
                checksum = package_lock.digest(source)
                output = root/'prepared'
                result = image_state.prepare(source, checksum, SELECTED, role, output)
                self.assertEqual(result['packages'], 1)
                self.assertTrue(result['runtime_storage_helper_packaged'])
                for name in ('production_qualified', 'early_boot_integration_installed',
                             'device_data_initialized', 'application_installed', 'hardware_boot_verified'):
                    self.assertFalse(result[name])
                self.assertEqual(package_lock.digest(source), checksum)
                self.assertEqual(package_lock.digest(output/'root.tar'), result['root_tar_sha256'])
                with tarfile.open(output/'root.tar') as archive:
                    members = {m.name: m for m in archive}
                    self.assertTrue(members['var'].isdir())
                    self.assertFalse(any(n.startswith('var/') for n in members))
                    self.assertEqual(members[layout.VAR_SEED+'/lib/dpkg'].linkname, '/'+layout.PACKAGE_DB)
                    self.assertEqual(archive.extractfile(layout.PACKAGE_DB+'/alternatives/probe').read(), b'slot alternative')
                    self.assertEqual(archive.extractfile(layout.VAR_SEED+'/log/vendor').read(), b'public initial log fixture')
                    profile = archive.extractfile(layout.PROFILE).read()
                    self.assertEqual(json.loads(profile), layout.profile(role))
                    for name, content in image_state.payloads(role).items():
                        self.assertEqual(archive.extractfile(name).read(), content)
                        mode = 0o755 if name == image_state.BOOT_BACKEND else 0o644
                        self.assertEqual((members[name].uid, members[name].gid, members[name].mode), (0, 0, mode))
                self.assertTrue((output/'READY.json').is_file())
                with self.assertRaises(ValueError):
                    image_state.prepare(source, checksum, SELECTED, role, output)

    def test_wrong_digest_private_state_and_unlisted_seed_aliases_leave_no_ready(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root/'source.tar'; fixture(source)
            output = root/'bad'
            with self.assertRaises(ValueError):
                image_state.prepare(source, '0'*64, SELECTED, 'server', output)
            self.assertFalse(output.exists())
        for extra in ({'var/lib/zmalacall/token.json': ('file', b'private fixture')},
                      {layout.PROFILE: ('file', b'preexisting configuration')}):
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder); source = root/'source.tar'; fixture(source, extra)
                output = root/'bad'
                with self.assertRaises(ValueError):
                    image_state.prepare(source, package_lock.digest(source), SELECTED, 'server', output)
                self.assertFalse((output/'READY.json').exists())
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root/'source.tar'
            fixture(source, {'var/unlisted': ('link', '/data/private-unlisted')})
            output = root/'bad'
            with self.assertRaises(ValueError):
                image_state.prepare(source, package_lock.digest(source), SELECTED, 'server', output)
            self.assertFalse((output/'READY.json').exists())

    def test_archive_paths_and_relocation_are_bounded_to_the_slot_graph(self):
        for name in ('../escape', '/absolute', 'var/../escape', 'var//lib', 'var\\lib'):
            with self.assertRaises(ValueError):
                image_state.relocate(name)
        self.assertEqual(image_state.relocate('./var/lib/dpkg/status'), layout.PACKAGE_DB+'/status')
        self.assertEqual(image_state.relocate('./var/lib/dpkg-other'), layout.VAR_SEED+'/lib/dpkg-other')
        self.assertEqual(image_state.relocate('etc/vendor'), 'etc/vendor')

    def test_hardlinks_follow_the_slot_and_malformed_graphs_fail_closed(self):
        for target, mode, valid in (('./var/lib/dpkg/status', 0o644, True),
                                    ('../escape', 0o644, False),
                                    ('missing-target', 0o644, False),
                                    ('./var/lib/dpkg/status', 0o600, False)):
            with self.subTest(target=target, mode=mode), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); source = root/'source.tar'; fixture(source)
                with tarfile.open(source, 'a') as archive:
                    member = tarfile.TarInfo('./var/lib/dpkg/status-alias')
                    member.type, member.linkname, member.mode = tarfile.LNKTYPE, target, mode
                    archive.addfile(member)
                output = root/'prepared'
                if valid:
                    image_state.prepare(source, package_lock.digest(source), SELECTED, 'server', output)
                    with tarfile.open(output/'root.tar') as archive:
                        member = archive.getmember(layout.PACKAGE_DB+'/status-alias')
                        self.assertEqual(member.linkname, layout.PACKAGE_DB+'/status')
                        self.assertEqual(archive.extractfile(member).read(), archive.extractfile(layout.PACKAGE_DB+'/status').read())
                else:
                    with self.assertRaises(ValueError):
                        image_state.prepare(source, package_lock.digest(source), SELECTED, 'server', output)
                    self.assertFalse((output/'READY.json').exists())

    def test_linked_runtime_parent_special_seed_and_budget_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root/'source.tar'
            fixture(source, {'usr/lib/python3/dist-packages': ('link', '/outside')})
            output = root/'bad'
            with self.assertRaises(ValueError):
                image_state.prepare(source, package_lock.digest(source), SELECTED, 'server', output)
            self.assertFalse((output/'READY.json').exists())
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root/'source.tar'; fixture(source)
            with tarfile.open(source, 'a') as archive:
                member = tarfile.TarInfo('var/log/fifo')
                member.type, member.mode = tarfile.FIFOTYPE, 0o600
                archive.addfile(member)
            output = root/'bad'
            with self.assertRaises(ValueError):
                image_state.prepare(source, package_lock.digest(source), SELECTED, 'server', output)
            self.assertFalse((output/'READY.json').exists())
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root/'source.tar'; fixture(source)
            output = root/'bad'
            with patch.object(layout, 'MAX_SEED_BYTES', 1), self.assertRaises(ValueError):
                image_state.prepare(source, package_lock.digest(source), SELECTED, 'server', output)
            self.assertFalse((output/'READY.json').exists())


if __name__ == '__main__':
    unittest.main()
