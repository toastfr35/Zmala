"""Controlled metadata/operation scenarios shared by component LLT plans."""
from contextlib import contextmanager
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from zmala_system import host_layout as layout, host_storage as storage
from tests.support import appliance_storage_fixture as fixture


def info(mode=stat.S_IFREG | 0o644, uid=0, gid=0):
    return SimpleNamespace(st_mode=mode, st_uid=uid, st_gid=gid)


class FakeMounts:
    def __init__(self, facts=None):
        self.table = dict(facts or {})
        self.calls = []
        self.failure = None
        self.fail_after_mount = False
        self.failure_target = None
        self.failure_remount = False
        self.inspection_failure = None
        self.fail_unmount = set()

    def facts(self):
        if self.inspection_failure:
            error, self.inspection_failure = self.inspection_failure, None
            raise error
        return dict(self.table)

    def run(self, args):
        self.calls.append(args)
        target = Path(args[-1])
        if args[0] == 'umount':
            if target in self.fail_unmount:
                raise RuntimeError('injected cleanup error')
            del self.table[target]
            return
        if args[0] != 'mount':
            raise AssertionError('Unexpected package/service operation')
        remount = len(args) > 2 and args[1] == '-o' and args[2].startswith('remount,')
        fail = (self.failure and (self.failure_target is None or target == self.failure_target)
                and remount == self.failure_remount)
        if remount:
            if fail:
                raise self.failure
            return
        if fail and not self.fail_after_mount:
            raise self.failure
        self.table[target] = storage.Mount(target, '0:123', frozenset({'rw'}), 'fixture')
        if fail:
            raise self.failure


@contextmanager
def controlled_ownership():
    """Unit fixture files belong to the test user; check real types/modes while
    modeling the privileged owner's metadata. Owner rejection has direct cases.
    """
    real = layout.metadata
    def checked(actual, uid=0, gid=0, mode=None, directory=False):
        return real(info(actual.st_mode, uid, gid), uid, gid, mode, directory)
    with patch.object(layout, 'metadata', side_effect=checked):
        yield


class StorageScenario(unittest.TestCase):
    role = None

    def test_exact_profile_types_bounds_and_no_mount_injection(self):
        expected = layout.profile(self.role)
        body = json.dumps(expected).encode()
        self.assertEqual(layout.decode_profile(body, self.role), expected)
        self.assertEqual(layout.decode_profile(json.dumps({'schema': 1, 'role': self.role}).encode(),
                                             self.role, data=True)['role'], self.role)
        cases = [b'', b'x'*(layout.MAX_PROFILE_BYTES+1), b'{"schema":1,"schema":1}', b'[]', b'{}']
        for key, value in (('schema', True), ('schema', 2), ('application_uid', 0),
                           ('application_gid', 0), ('role', 'other'), ('bindings', [])):
            changed = {**expected, key: value}; cases.append(json.dumps(changed).encode())
        for value in cases:
            with self.subTest(value=value[:60]), self.assertRaises((ValueError, UnicodeError)):
                layout.decode_profile(value, self.role)
        with self.assertRaises(ValueError):
            layout.decode_profile(b'{"schema":1,"role":"other"}', 'other', data=True)

    def test_identity_formats_and_root_owned_mode_guards(self):
        layout.identity(fixture.MACHINE_ID)
        layout.identity(fixture.HOSTNAME, hostname=True)
        for value in (b'', b'0'*32, b'f'*32, b'A'*32, b'a'*31, b'a'*32+b'\n\n'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                layout.identity(value)
        for value in (b'-bad', b'bad-', b'bad name', b'a'*64, b'bad\x00name'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                layout.identity(value, hostname=True)
        layout.metadata(info(), mode=0o644)
        layout.metadata(info(stat.S_IFDIR | 0o700, 1000, 1000), 1000, 1000, 0o700, directory=True)
        for value in (info(uid=1000), info(gid=1000), info(stat.S_IFLNK | 0o644),
                      info(stat.S_IFDIR | 0o644), info(stat.S_IFREG | 0o666)):
            with self.assertRaises(ValueError):
                layout.metadata(value, mode=0o644)
        for value in (info(stat.S_IFDIR | 0o700, 0, 1000), info(stat.S_IFDIR | 0o700, 1000, 0),
                      info(stat.S_IFDIR | 0o777, 1000, 1000), info(stat.S_IFREG | 0o700, 1000, 1000)):
            with self.assertRaises(ValueError):
                layout.metadata(value, 1000, 1000, 0o700, directory=True)

    def test_fixed_role_bindings_and_bounded_ram_plan(self):
        values = layout.bindings(self.role)
        self.assertEqual(len({v.target for v in values}), len(values))
        self.assertEqual(len({v.saved for v in values}), len(values))
        self.assertEqual({v.target for v in values if v.readonly}, {'etc/machine-id', 'etc/hostname'})
        expected = {'etc/machine-id', 'etc/hostname', 'etc/NetworkManager/system-connections',
                    'var/lib/NetworkManager', 'var/lib/bluetooth', 'etc/ssh/keys', 'etc/zmalacall/operator',
                    'var/lib/zmalacall-server' if self.role == 'server' else 'var/lib/zmalacall'}
        if self.role == 'server':
            expected.add('etc/letsencrypt')
        self.assertEqual({v.target for v in values}, expected)
        self.assertEqual('etc/letsencrypt' in {v.target for v in values}, self.role == 'server')
        app = next(v for v in values if v.saved == 'state/'+self.role)
        self.assertEqual((app.uid, app.gid, app.mode), (1000, 1000, 0o700))
        self.assertFalse(any(v.target in ('etc', 'var', 'etc/ssh', 'etc/zmalacall', 'var/lib/dpkg') for v in values))
        mounts = layout.volatile_mounts(PurePosixPath('/image'), PurePosixPath('/run/work'))
        self.assertEqual([str(v[2]) for v in mounts], ['/image/etc', '/image/var', '/image/tmp'])
        self.assertIn('lowerdir=/image/etc', mounts[0][3])
        self.assertIn('upperdir=/run/work/etc-upper', mounts[0][3])
        self.assertIn('size=128M', mounts[1][3]); self.assertIn('size=128M', mounts[2][3])
        self.assertIn('mode=1777', mounts[2][3])
        self.assertTrue(all('nodev,nosuid' in v[3] for v in mounts))

    def test_mount_table_limits_escapes_and_ambiguous_inputs(self):
        text = '10 1 8:1 / /image ro,relatime - ext4 /dev/test rw\n'
        point = Path('/image')
        self.assertIn('ro', storage.mount_table(text)[point].flags)
        self.assertEqual(storage.mount_table(text.replace('/image', r'/with\040space'))[Path('/with space')].device, '8:1')
        self.assertFalse(storage.mount_table(text+text)[point].flags)
        for value in ('invalid', 'x'*(1024**2+1)):
            with self.assertRaises(ValueError):
                storage.mount_table(value)

    def test_journal_policy_keeps_bounded_logs_in_ram(self):
        text = Path(layout.__file__).with_name('journald.conf').read_text(encoding='utf-8')
        values = dict(line.split('=', 1) for line in text.splitlines() if '=' in line and not line.startswith('#'))
        self.assertEqual(values, {'Storage': 'volatile', 'RuntimeMaxUse': '32M', 'RuntimeMaxFileSize': '4M'})

    def test_native_backend_rejects_nonmount_commands(self):
        with self.assertRaises(ValueError):
            storage.NativeMounts.run(['apt-get', 'update'])
        with patch.object(storage.platform, 'system', return_value='Windows'), self.assertRaises(ValueError):
            storage.prepare('/image', '/data', '/run/work', self.role)
        with patch.object(storage.platform, 'system', return_value='Linux'), \
                patch.object(storage.os, 'geteuid', return_value=1000, create=True), self.assertRaises(ValueError):
            storage.prepare('/image', '/data', '/run/work', self.role)

    def test_owned_mount_cleanup_partial_success_and_original_input_mounts(self):
        with tempfile.TemporaryDirectory() as folder:
            area = Path(folder)/'work'; area.mkdir()
            root, data = Path(folder)/'image', Path(folder)/'data'
            base = {p: storage.Mount(p, '8:1', frozenset({'rw'}), 'ext4') for p in (root, data)}
            fake = FakeMounts(base)
            prepared = storage.Prepared(storage.Context(root, data, area, self.role, []), fake)
            one, two = root/'etc', root/'var'
            prepared.mount('tmpfs', one, 'tmpfs', 'size=64M')
            failure = RuntimeError('original operation failure')
            fake.failure, fake.fail_after_mount = failure, True
            fake.inspection_failure = RuntimeError('secondary mount inspection failure')
            with self.assertRaises(RuntimeError) as caught:
                prepared.mount('tmpfs', two, 'tmpfs', 'size=64M')
            self.assertIs(caught.exception, failure)
            self.assertEqual(prepared.owned, [one, two])
            fake.failure = None; fake.fail_unmount.add(two)
            with self.assertRaisesRegex(RuntimeError, 'cleanup error'):
                prepared.close()
            self.assertEqual(prepared.owned, [two])
            self.assertEqual([a[-1] for a in fake.calls if a[0] == 'umount'], [str(two), str(one)])
            fake.fail_unmount.clear(); prepared.close(); prepared.close()
            self.assertEqual(fake.facts(), base)

    @unittest.skipIf(os.name == 'nt', 'Linux image seed/link/filesystem operations')
    def test_context_inputs_seed_and_existing_data_refusal(self):
        with tempfile.TemporaryDirectory() as folder, controlled_ownership():
            base = Path(folder)
            root = fixture.image(base/'image', self.role)
            data = fixture.data(base/'data', self.role)
            ram = base/'ram'; ram.mkdir(mode=0o700)
            area = ram/'work'
            facts = {root: storage.Mount(root, '8:1', frozenset({'ro'}), 'ext4'),
                     data: storage.Mount(data, '8:2', frozenset({'rw'}), 'ext4'),
                     ram: storage.Mount(ram, '0:1', frozenset({'rw'}), 'tmpfs')}
            current = storage.context(root, data, area, self.role, facts)
            self.assertGreater(len(current.seed), 2)
            for changed in ({**facts, root: storage.Mount(root, '8:1', frozenset({'rw'}), 'ext4')},
                            {**facts, data: storage.Mount(data, '8:2', frozenset({'ro'}), 'ext4')},
                            {**facts, data: storage.Mount(data, '8:1', frozenset({'rw'}), 'ext4')},
                            {**facts, data: storage.Mount(data, '0:9', frozenset({'rw'}), 'tmpfs')}):
                with self.assertRaises(ValueError):
                    storage.context(root, data, area, self.role, changed)
            with patch.object(layout, 'MAX_SEED_BYTES', 1), self.assertRaises(ValueError):
                storage.seed_entries(root)
            with patch.object(layout, 'MAX_SEED_ENTRIES', 1), self.assertRaises(ValueError):
                storage.seed_entries(root)
            escape = root/layout.VAR_SEED/'unlisted-state'
            for target in ('/data/unlisted', '../data/unlisted'):
                escape.symlink_to(target)
                with self.assertRaises(ValueError):
                    storage.seed_entries(root)
                escape.unlink()
            link = root/layout.VAR_SEED/'lib/dpkg'; link.unlink(); link.symlink_to('/data/dpkg')
            with self.assertRaises(ValueError):
                storage.seed_entries(root)

    def test_directory_creation_preserves_existing_bytes_and_declared_owners(self):
        binding = next(v for v in layout.bindings(self.role) if v.saved == 'state/'+self.role)
        with tempfile.TemporaryDirectory() as folder, patch.object(layout, 'metadata') as check, \
                patch.object(storage.os, 'chown', create=True) as chown:
            data = Path(folder)
            directory = storage.saved_directory(data, binding)
            self.assertEqual(chown.call_args_list[-1].args[1:], (1000, 1000))
            (directory/'existing').write_bytes(b'preserved')
            count = chown.call_count
            self.assertEqual(storage.saved_directory(data, binding), directory)
            self.assertEqual(chown.call_count, count)
            self.assertEqual((directory/'existing').read_bytes(), b'preserved')
            self.assertEqual(check.call_args.args[1:], (1000, 1000, 0o700))
            check.side_effect = ValueError('incompatible existing state')
            with self.assertRaises(ValueError):
                storage.saved_directory(data, binding)
            self.assertEqual(chown.call_count, count)
            self.assertEqual((directory/'existing').read_bytes(), b'preserved')

    @unittest.skipIf(os.name == 'nt', 'Unix record links and special-file boundaries')
    def test_record_limits_links_and_special_files_are_rejected_before_reading(self):
        with tempfile.TemporaryDirectory() as folder, controlled_ownership():
            root = Path(folder)
            fixture.file(root/'record', b'bounded', 0o600)
            self.assertEqual(storage.read_record(root, 'record', 0o600, 8), b'bounded')
            with self.assertRaises(ValueError):
                storage.read_record(root, 'record', 0o600, 1)
            os.link(root/'record', root/'alias')
            with self.assertRaises(ValueError):
                storage.read_record(root, 'alias', 0o600, 8)
            os.mkfifo(root/'fifo', 0o600)
            with self.assertRaises(ValueError):
                storage.read_record(root, 'fifo', 0o600, 8)
            (root/'linked').symlink_to(root, target_is_directory=True)
            with self.assertRaises(ValueError):
                storage.read_record(root, 'linked/record', 0o600, 8)

    @unittest.skipIf(os.name == 'nt', 'Linux image seed/link/filesystem operations')
    def test_seed_copy_preserves_modes_and_never_follows_package_database_link(self):
        with tempfile.TemporaryDirectory() as folder, controlled_ownership():
            root = fixture.image(Path(folder)/'image', self.role)
            entries = storage.seed_entries(root)
            current = storage.Context(root, Path(folder)/'data', Path(folder)/'work', self.role, entries)
            with patch.object(storage.os, 'chown') as chown:
                storage.copy_seed(current)
            self.assertEqual((root/'var/lib/dpkg').readlink().as_posix(), '/'+layout.PACKAGE_DB)
            self.assertEqual((root/'var/lib/vendor-state').read_bytes(), b'seed-A')
            self.assertEqual(stat.S_IMODE((root/'var/lib/vendor-state').stat().st_mode), 0o640)
            self.assertEqual(len(chown.call_args_list), len(entries))
            self.assertTrue(all(call.kwargs == {'follow_symlinks': False} for call in chown.call_args_list))
            self.assertEqual([call.args[1:] for call in chown.call_args_list],
                             [(item.st_uid, item.st_gid) for _, item in entries])

    @unittest.skipIf(os.name == 'nt', 'Linux preparation with controlled mount operations')
    def test_readiness_requires_complete_sequence_and_failure_preserves_original_error(self):
        for fail_name in (None, 'var', 'etc/hostname', 'var/lib/bluetooth'):
            with self.subTest(failure=fail_name), tempfile.TemporaryDirectory() as folder, \
                    controlled_ownership(), patch.object(storage.os, 'geteuid', return_value=0), \
                    patch.object(storage.os, 'chown'):
                base = Path(folder)
                root = fixture.image(base/'image', self.role)
                data = fixture.data(base/'data', self.role)
                ram = base/'ram'; ram.mkdir(mode=0o700)
                area = ram/'work'
                initial = {root: storage.Mount(root, '8:1', frozenset({'ro'}), 'ext4'),
                           data: storage.Mount(data, '8:2', frozenset({'rw'}), 'ext4'),
                           ram: storage.Mount(ram, '0:1', frozenset({'rw'}), 'tmpfs')}
                fake = FakeMounts(initial)
                failure = RuntimeError('original preparation failure')
                if fail_name:
                    fake.failure, fake.failure_target = failure, root/fail_name
                    fake.failure_remount = fail_name == 'etc/hostname'
                    with self.assertRaises(RuntimeError) as caught:
                        storage.prepare(root, data, area, self.role, fake)
                    self.assertIs(caught.exception, failure)
                    self.assertFalse((area/'ready.json').exists())
                    self.assertEqual(fake.facts(), initial)
                else:
                    result = storage.prepare(root, data, area, self.role, fake)
                    self.assertTrue(json.loads((area/'ready.json').read_text())['storage_prepared'])
                    self.assertEqual(len([a for a in fake.calls if a[0] == 'mount' and a[1:3] ==
                                          ['-o', 'remount,bind,ro,nodev,nosuid']]), 2)
                    with self.assertRaises(ValueError):
                        storage.prepare(root, data, area, self.role, fake)
                    result.close()
                    self.assertEqual(fake.facts(), initial)
                self.assertEqual((data/'identity/machine-id').read_bytes(), fixture.MACHINE_ID)

    @unittest.skipIf(os.name == 'nt', 'Linux preparation with controlled status-file failures')
    def test_status_sync_and_marker_cleanup_failures_still_unwind_owned_mounts(self):
        with tempfile.TemporaryDirectory() as folder, controlled_ownership(), \
                patch.object(storage.os, 'geteuid', return_value=0), patch.object(storage.os, 'chown'):
            base = Path(folder)
            root = fixture.image(base/'image', self.role)
            data = fixture.data(base/'data', self.role)
            ram = base/'ram'; ram.mkdir(mode=0o700)
            area = ram/'work'
            initial = {root: storage.Mount(root, '8:1', frozenset({'ro'}), 'ext4'),
                       data: storage.Mount(data, '8:2', frozenset({'rw'}), 'ext4'),
                       ram: storage.Mount(ram, '0:1', frozenset({'rw'}), 'tmpfs')}
            fake = FakeMounts(initial)
            failure = OSError('original status sync failure')
            real_unlink = Path.unlink
            def unlink(path, *args, **kwargs):
                if path.name == 'ready.next':
                    raise OSError('secondary marker cleanup failure')
                return real_unlink(path, *args, **kwargs)
            with patch.object(storage.os, 'fsync', side_effect=failure), patch.object(Path, 'unlink', unlink):
                with self.assertRaises(OSError) as caught:
                    storage.prepare(root, data, area, self.role, fake)
            self.assertIs(caught.exception, failure)
            self.assertFalse((area/'ready.json').exists())
            self.assertEqual(fake.facts(), initial)
