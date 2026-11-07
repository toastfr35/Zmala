"""Locked-root build/archive regressions; no live product or hardware verification."""
import io
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from zmala_images import root_build, root_cleanup

LEDGER = ('Package: example\nVersion: 1.0\nArchitecture: arm64\nStatus: install ok installed\n\n')
SHADOW = b'root:!:1:0:99999:7:::\n'
SELECTED = {'example': (('1.0', 'arm64', 'a'*64), None, {})}
UNITS = ('rpi-eeprom-update.service', 'apt-daily.timer', 'apt-daily-upgrade.timer')


def write_tar(path, changes=None, omit=()):
    records = {name: ('dir', b'') for name in ('etc', 'etc/ssh', 'etc/apt',
               'etc/apt/sources.list.d', 'etc/systemd', 'etc/systemd/system', 'var', 'var/lib', 'var/lib/dpkg')}
    records.update({'var/lib/dpkg/status': ('file', LEDGER.encode()), 'etc/shadow': ('file', SHADOW),
                    'etc/machine-id': ('file', b''), 'etc/hostname': ('file', b'zmala-unconfigured\n')})
    records.update({f'etc/systemd/system/{unit}': ('link', '/dev/null') for unit in UNITS})
    records.update(changes or {})
    with tarfile.open(path, 'w') as archive:
        for name, (kind, value) in records.items():
            if name in omit:
                continue
            member = tarfile.TarInfo('./'+name)
            member.mode = 0o640 if name == 'etc/shadow' else 0o755 if kind == 'dir' else 0o644
            member.gid = 42 if name == 'etc/shadow' else 0
            if kind == 'dir':
                member.type = tarfile.DIRTYPE
            elif kind == 'link':
                member.type, member.linkname = tarfile.SYMTYPE, value
            else:
                member.size = len(value)
            archive.addfile(member, io.BytesIO(value) if kind == 'file' else None)


def offline(root):
    files = {'var/lib/dpkg/status': LEDGER.encode(), 'etc/shadow': SHADOW,
             'etc/ssh/ssh_host_ed25519_key': b'temporary build key fixture',
             'etc/ssh/ssh_host_ed25519_key.pub': b'public fixture',
             'etc/ssh/sshd_config': b'vendor defaults', 'etc/machine-id': b'build-id',
             'etc/resolv.conf': b'build resolver', 'etc/hostname': b'build hostname',
             'var/lib/dbus/machine-id': b'build-id', 'etc/hosts': b'build host mapping',
             'var/lib/systemd/random-seed': b'seed fixture',
             'var/lib/NetworkManager/secret_key': b'network identity fixture',
             'etc/apt/sources.list.d/build.sources': b'file build inputs',
             'etc/apt/apt.conf.d/99mmdebstrap': b'build-only options'}
    files.update({f'usr/lib/systemd/system/{unit}': b'vendor unit fixture' for unit in UNITS})
    for name, value in files.items():
        path = root/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(value)
    root_cleanup.setup(root)


class RootArchiveTests(unittest.TestCase):
    def test_exact_package_ledger_and_factory_subset(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'root.tar'; write_tar(path)
            result = root_build.audit(path, SELECTED)
            self.assertEqual(result['packages'], 1)
            self.assertFalse(result['image_qualified'])

    def test_missing_unsafe_sources_keys_identities_and_architectures_refused(self):
        changes = (
            {'etc/machine-id': ('file', b'build id')},
            {'etc/hostname': ('file', b'host name')},
            {'etc/shadow': ('file', b'root::1:0:99999:7:::\n')},
            {'etc/ssh/ssh_host_ed25519_key': ('file', b'key fixture')},
            {'var/lib/systemd/random-seed': ('file', b'seed fixture')},
            {'var/lib/NetworkManager/secret_key': ('file', b'network identity fixture')},
            {'var/lib/bluetooth/identity/info': ('file', b'pairing fixture')},
            {'etc/apt/sources.list.d/build.sources': ('file', b'file:/build')},
            {'var/lib/dpkg': ('link', '/outside')},
            {'../outside': ('file', b'escape')},
            {'etc/./shadow': ('file', SHADOW)},
            {'etc//shadow': ('file', SHADOW)},
            {'var/lib/dpkg/status': ('file', LEDGER.replace('1.0', '2.0').encode())},
            {'var/lib/dpkg/status': ('file', LEDGER.replace('arm64', 'all').encode())},
            {'etc/systemd/system/apt-daily.timer': ('link', '/unmasked')})
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'root.tar'
            for change in changes:
                with self.subTest(change=list(change)):
                    write_tar(path, change)
                    with self.assertRaises(ValueError):
                        root_build.audit(path, SELECTED)
            write_tar(path, omit=('var/lib/dpkg/status',))
            with self.assertRaises(ValueError):
                root_build.audit(path, SELECTED)

    def test_raw_header_budget_truncation_and_special_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'root.tar'; write_tar(path)
            with patch.object(root_build, 'MAX_ROOT_BYTES', 1), self.assertRaises(ValueError):
                root_build.audit(path, SELECTED)
            member = tarfile.TarInfo('huge-pax')
            member.type = tarfile.XHDTYPE; member.size = 1024**2
            path.write_bytes(member.tobuf()+b'\0'*1024)
            with self.assertRaises(ValueError):
                root_build.preflight_tar(path)
            member.type = tarfile.REGTYPE; member.size = 2048
            path.write_bytes(member.tobuf()+b'\0'*512)
            with self.assertRaises(ValueError):
                root_build.preflight_tar(path)

    def test_build_command_is_unprivileged_network_isolated_and_exact(self):
        args = root_build.command(Path('/tmp/build'), Path('/tmp/output/root.tar'), SELECTED)
        for flag in ('--user', '--map-root-user', '--map-auto', '--net', '--mount', '--mode=unshare', '--kill-child=TERM',
                     '--architectures=arm64', '--variant=custom', '--include=example=1.0'):
            self.assertIn(flag, args)
        self.assertFalse(any(value.startswith(('http:', 'https:')) for value in args))
        self.assertEqual(args[-1], 'deb [trusted=yes] file:/tmp/build/repo ./')

    def test_hook_emission_normalizes_windows_line_endings(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root/'source'; source.mkdir()
            body = b'#!/usr/bin/env python3\r\n# fixture\r\n'
            (source/'root_cleanup.py').write_bytes(body)
            output = root/'output'; output.mkdir()
            with patch.object(root_build, '__file__', str(source/'root_build.py')):
                path = root_build.emit_hook(output)
            self.assertEqual(path.read_bytes(), body.replace(b'\r\n', b'\n'))

    def test_windows_and_host_root_execution_refused(self):
        with patch.object(root_build.platform, 'system', return_value='Windows'), self.assertRaises(ValueError):
            root_build.build('server', '.', '.', '.')
        with patch.object(root_build.platform, 'system', return_value='Linux'), \
                patch.object(root_build.os, 'geteuid', return_value=0, create=True), self.assertRaises(ValueError):
            root_build.build('server', '.', '.', '.')


class RootCleanupTests(unittest.TestCase):
    def test_setup_and_marker_guard(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(ValueError):
                root_cleanup.prepare(root)
            root_cleanup.setup(root)
            self.assertEqual((root/root_cleanup.MARKER).read_bytes(), root_cleanup.TOKEN)
            with self.assertRaises(FileExistsError):
                root_cleanup.setup(root)
        with self.assertRaises(ValueError):
            root_cleanup.setup(Path.cwd().anchor)

    @unittest.skipIf(os.name == 'nt', 'Linux offline root symlinks')
    def test_cleanup_removes_temporary_identity_sources_and_keeps_package_db(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); offline(root)
            root_cleanup.prepare(root)
            root_cleanup.prepare(root)
            self.assertEqual((root/'var/lib/dpkg/status').read_text(), LEDGER)
            self.assertEqual((root/'etc/machine-id').read_bytes(), b'')
            self.assertEqual((root/'etc/ssh/sshd_config').read_bytes(), b'vendor defaults')
            self.assertFalse((root/'etc/ssh/ssh_host_ed25519_key').exists())
            self.assertFalse((root/'etc/resolv.conf').exists())
            self.assertFalse((root/'var/lib/systemd/random-seed').exists())
            self.assertFalse((root/'var/lib/NetworkManager/secret_key').exists())
            self.assertFalse(any((root/'etc/apt/sources.list.d').iterdir()))
            for unit in UNITS:
                self.assertEqual((root/'etc/systemd/system'/unit).readlink().as_posix(), '/dev/null')

    @unittest.skipIf(os.name == 'nt', 'Linux offline root symlinks')
    def test_links_and_existing_operator_overrides_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)/'root'; root.mkdir(); offline(root)
            outside = Path(temporary)/'outside'; outside.mkdir()
            (root/'etc/ssh/ssh_host_ed25519_key').unlink()
            (root/'etc/ssh/ssh_host_ed25519_key.pub').unlink()
            (root/'etc/ssh/sshd_config').unlink(); (root/'etc/ssh').rmdir()
            (root/'etc/ssh').symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                root_cleanup.prepare(root)
            self.assertFalse(any(outside.iterdir()))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); offline(root)
            mask = root/'etc/systemd/system/rpi-eeprom-update.service'
            mask.parent.mkdir(parents=True); mask.write_text('operator override')
            with self.assertRaises(ValueError):
                root_cleanup.prepare(root)
            self.assertEqual(mask.read_text(), 'operator override')


if __name__ == '__main__':
    unittest.main()
