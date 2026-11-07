"""Controlled first-boot identity verification; no live devices are used."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from zmala_system import host_layout as layout, host_storage as storage
from tests.support.appliance_storage_unit import controlled_ownership
from tests.support.appliance_storage_unit import info
from tests.support.device_identity_fixture import factory, Facts

from zmala_system import device_identity as identity


@contextmanager
def prepared(role):
    with tempfile.TemporaryDirectory() as folder, controlled_ownership(), \
            patch.object(identity.os, 'geteuid', return_value=0, create=True), \
            patch.object(identity.os, 'getegid', return_value=0, create=True):
        data = factory(Path(folder)/'data', role)
        yield data, Facts(data)


class IdentityScenario(unittest.TestCase):
    role = None

    def test_kernel_entropy_short_reads_and_invalid_identity_no_fallback(self):
        with patch.object(identity.os, 'getrandom', side_effect=[b'\x12'*5, b'\x34'*11], create=True) as read:
            result = identity.random_identity(self.role)
        self.assertEqual([call.args for call in read.call_args_list], [(16,), (11,)])
        self.assertEqual(result['machine-id'], b'12'*5+b'34'*11+b'\n')
        self.assertEqual(result['hostname'], b'zmala-'+self.role.encode()+b'-121212121234\n')
        for outcome in (b'', b'\0'*16, b'\xff'*16, OSError('entropy unavailable')):
            options = {'side_effect': outcome} if isinstance(outcome, Exception) else {'return_value': outcome}
            with self.subTest(outcome=type(outcome).__name__), \
                    patch.object(identity.os, 'getrandom', create=True, **options), \
                    self.assertRaises((ValueError, OSError)):
                identity.random_identity(self.role)

    def test_factory_record_exact_schema_role_and_bounded_regular_read(self):
        expected = identity.factory_profile(self.role)
        invalid = [[], {**expected, 'schema': True}, {**expected, 'role': 'wrong'},
                   {**expected, 'extra': 1}, {'schema': 1}, b'{"schema":1,"schema":1}']
        for value in invalid:
            body = value if isinstance(value, bytes) else json.dumps(value).encode()
            with self.subTest(body=body), patch.object(storage, 'read_record', return_value=body), \
                    self.assertRaises(ValueError):
                identity.factory_record(Path('/fixture'), self.role)
        with patch.object(storage, 'read_record', return_value=json.dumps(expected).encode()) as read:
            identity.factory_record(Path('/fixture'), self.role)
            self.assertEqual(read.call_args.args, (Path('/fixture'), identity.FACTORY, 0o600, layout.MAX_PROFILE_BYTES))

    def test_initialize_requires_linux_root_without_reading_mounts(self):
        for system, uid, gid in (('Windows', 0, 0), ('Linux', 1000, 0), ('Linux', 0, 1000)):
            with patch.object(identity.platform, 'system', return_value=system), \
                    patch.object(identity.os, 'geteuid', return_value=uid, create=True), \
                    patch.object(identity.os, 'getegid', return_value=gid, create=True), \
                    patch.object(storage.NativeMounts, 'facts') as facts, self.assertRaises(ValueError):
                identity.initialize('/fixture', self.role)
            facts.assert_not_called()

    def test_owner_group_mode_and_directory_validation_precede_factory_reads(self):
        data = Path('/fixture')
        facts = Facts(data).facts()
        for actual in (info(0o40700, uid=1000), info(0o40700, gid=1000),
                       info(0o40755), info(0o100700)):
            with self.subTest(actual=actual), patch.object(storage, 'canonical', return_value=data), \
                    patch.object(Path, 'lstat', return_value=actual), \
                    patch.object(identity, 'factory_record') as record, self.assertRaises(ValueError):
                identity.admit(data, self.role, facts)
            record.assert_not_called()

    @unittest.skipIf(os.name == 'nt', 'Unix mount-path, owner and file-mode boundaries')
    def test_mount_and_unknown_data_refusal_precedes_lock_or_identity_writes(self):
        with prepared(self.role) as (data, facts):
            original = facts.table.copy()
            for table in ({}, {data: storage.Mount(data, '7:91', frozenset({'ro'}), 'ext4')},
                          {data: storage.Mount(data, '7:91', frozenset({'rw'}), 'tmpfs')},
                          {**original, Path('/'): storage.Mount(Path('/'), '7:91', frozenset({'rw'}), 'ext4')}):
                facts.table = table
                with self.assertRaises(ValueError):
                    identity.initialize(data, self.role, facts)
                self.assertFalse((data/identity.LOCK).exists())
            facts.table = original
            private = data/'old-user-state'; private.write_bytes(b'keep')
            with self.assertRaises(ValueError):
                identity.initialize(data, self.role, facts)
            self.assertEqual(private.read_bytes(), b'keep')
            self.assertFalse((data/identity.LOCK).exists())

    @unittest.skipIf(os.name == 'nt', 'Linux flock and Unix file-mode semantics')
    def test_success_is_idempotent_preserves_app_data_and_rejects_competitor(self):
        with prepared(self.role) as (data, facts):
            with identity.exclusive(data), self.assertRaises(BlockingIOError):
                identity.initialize(data, self.role, facts)
            self.assertEqual(identity.initialize(data, self.role, facts),
                             {'schema': 1, 'role': self.role, 'initialized': True})
            first = identity.saved_identity(data)
            (data/'state').mkdir(mode=0o700); (data/'state/value').write_bytes(b'preserved')
            with patch.object(identity.os, 'getrandom', side_effect=AssertionError('identity rotated')):
                self.assertTrue(identity.initialize(data, self.role, facts)['initialized'])
            self.assertEqual(identity.saved_identity(data), first)
            self.assertEqual((data/'state/value').read_bytes(), b'preserved')
            self.assertEqual((data/identity.LOCK).stat().st_size, 0)

    @unittest.skipIf(os.name == 'nt', 'Linux identity commit and directory sync semantics')
    def test_all_sync_failures_retry_without_rotating_committed_identity(self):
        for boundary in range(1, 9):
            with self.subTest(boundary=boundary), prepared(self.role) as (data, facts):
                real_sync, calls = os.fsync, []
                failure = OSError('injected sync failure')
                def sync(descriptor):
                    real_sync(descriptor)
                    calls.append(descriptor)
                    if len(calls) == boundary:
                        raise failure
                with patch.object(identity.os, 'fsync', side_effect=sync), self.assertRaises(OSError) as error:
                    identity.initialize(data, self.role, facts)
                self.assertIs(error.exception, failure)
                before = identity.saved_identity(data) if (data/'identity').exists() else None
                self.assertTrue(identity.initialize(data, self.role, facts)['initialized'])
                if before:
                    self.assertEqual(identity.saved_identity(data), before)

    @unittest.skipIf(os.name == 'nt', 'Linux identity staging and atomic rename semantics')
    def test_partial_stage_retries_but_committed_corruption_never_regenerates(self):
        with prepared(self.role) as (data, facts):
            stage = data/identity.STAGING; stage.mkdir(mode=0o700)
            (stage/'machine-id').write_bytes(b'0011'); (stage/'machine-id').chmod(0o644)
            self.assertTrue(identity.initialize(data, self.role, facts)['initialized'])
            first = identity.saved_identity(data)
            (data/'identity/hostname').unlink()
            with patch.object(identity.os, 'getrandom', side_effect=AssertionError('corrupt identity rotated')), \
                    self.assertRaises(ValueError):
                identity.initialize(data, self.role, facts)
            self.assertEqual((data/'identity/machine-id').read_bytes(), first['machine-id'])

    @unittest.skipIf(os.name == 'nt', 'Unix link/special-file and ownership semantics')
    def test_linked_unknown_or_oversized_staging_is_rejected_without_removal(self):
        for variant in ('unknown', 'symlink', 'hardlink', 'fifo', 'oversized', 'mode'):
            with self.subTest(variant=variant), prepared(self.role) as (data, facts):
                stage = data/identity.STAGING; stage.mkdir(mode=0o700)
                entry = stage/('unknown' if variant == 'unknown' else 'machine-id')
                if variant == 'symlink':
                    entry.symlink_to(data/identity.FACTORY)
                elif variant == 'hardlink':
                    os.link(data/identity.FACTORY, entry)
                elif variant == 'fifo':
                    os.mkfifo(entry, 0o644)
                else:
                    entry.write_bytes(b'x'*129 if variant == 'oversized' else b'partial')
                    entry.chmod(0o600 if variant == 'mode' else 0o644)
                with self.assertRaises(ValueError):
                    identity.initialize(data, self.role, facts)
                self.assertTrue(os.path.lexists(entry))
                self.assertFalse((data/'identity').exists())

    @unittest.skipIf(os.name == 'nt', 'Unix identity file and directory synchronization')
    def test_missing_marker_reuses_committed_identity_and_revalidates_role(self):
        with prepared(self.role) as (data, facts):
            identity.initialize(data, self.role, facts)
            original = identity.saved_identity(data)
            (data/layout.DATA_MARKER).unlink()
            with patch.object(identity.os, 'getrandom', side_effect=AssertionError('committed identity rotated')):
                self.assertTrue(identity.initialize(data, self.role, facts)['initialized'])
            self.assertEqual(identity.saved_identity(data), original)
            marker = data/layout.DATA_MARKER
            marker.write_text(json.dumps({'schema': 1, 'role': 'wrong'}))
            with self.assertRaises(ValueError):
                identity.initialize(data, self.role, facts)
            self.assertEqual(identity.saved_identity(data), original)
            self.assertIn('wrong', marker.read_text())

    @unittest.skipIf(os.name == 'nt', 'Linux rename, file modes and umask')
    def test_commit_order_and_fixed_modes_under_private_boot_umask(self):
        with prepared(self.role) as (data, facts):
            events = []
            sync, write = identity.sync_directory, identity.write_exclusive
            rename, replace = Path.rename, Path.replace
            def synced(path):
                events.append(('sync', path.name)); return sync(path)
            def written(path, body, mode):
                events.append(('write', path.name)); return write(path, body, mode)
            def renamed(path, target):
                events.append(('rename', path.name)); return rename(path, target)
            def replaced(path, target):
                events.append(('replace', path.name)); return replace(path, target)
            previous = os.umask(0o077)
            try:
                with patch.object(identity, 'sync_directory', side_effect=synced), \
                        patch.object(identity, 'write_exclusive', side_effect=written), \
                        patch.object(Path, 'rename', renamed), patch.object(Path, 'replace', replaced):
                    identity.initialize(data, self.role, facts)
            finally:
                os.umask(previous)
            self.assertEqual(events, [('write', 'machine-id'), ('write', 'hostname'),
                                     ('sync', identity.STAGING), ('rename', identity.STAGING),
                                     ('sync', 'data'), ('write', identity.NEXT),
                                     ('replace', identity.NEXT), ('sync', 'data')])
            for field in identity.IDENTITY:
                self.assertEqual((data/'identity'/field).stat().st_mode & 0o777, 0o644)
            self.assertEqual((data/'identity').stat().st_mode & 0o777, 0o700)
            self.assertEqual((data/layout.DATA_MARKER).stat().st_mode & 0o777, 0o600)

    @unittest.skipIf(os.name == 'nt', 'Linux partial writes and atomic directory/file publication')
    def test_write_and_pre_or_post_rename_failures_return_failure_and_retry(self):
        for method in ('write', 'rename', 'replace'):
            for after in (False, True):
                with self.subTest(method=method, after=after), prepared(self.role) as (data, facts):
                    failure = OSError('injected publication failure')
                    if method == 'write':
                        def broken(path, body, mode):
                            if after:
                                path.write_bytes(body[:1]); path.chmod(mode)
                            raise failure
                        context = patch.object(identity, 'write_exclusive', side_effect=broken)
                    else:
                        original = getattr(Path, method)
                        def broken(path, target):
                            if after:
                                original(path, target)
                            raise failure
                        context = patch.object(Path, method, broken)
                    with context, self.assertRaises(OSError) as error:
                        identity.initialize(data, self.role, facts)
                    self.assertIs(error.exception, failure)
                    before = identity.saved_identity(data) if (data/'identity').exists() else None
                    self.assertTrue(identity.initialize(data, self.role, facts)['initialized'])
                    if before:
                        self.assertEqual(identity.saved_identity(data), before)

    @unittest.skipIf(os.name == 'nt', 'Linux bounded staging and lock files')
    def test_partial_valid_hostname_and_complete_stage_resume_correctly(self):
        for complete in (False, True):
            with self.subTest(complete=complete), prepared(self.role) as (data, facts):
                stage = data/identity.STAGING; stage.mkdir(mode=0o700)
                body = {'machine-id': b'1234567890abcdef1234567890abcdef\n',
                        'hostname': b'zmala-'+self.role.encode()+b'-1234567890ab\n' if complete else b'zmala'}
                for field, value in body.items():
                    path = stage/field; path.write_bytes(value); path.chmod(0o644)
                if complete:
                    with patch.object(identity.os, 'getrandom', side_effect=AssertionError('complete stage discarded')):
                        identity.initialize(data, self.role, facts)
                    self.assertEqual(identity.saved_identity(data), body)
                else:
                    identity.initialize(data, self.role, facts)
                    saved = identity.saved_identity(data)
                    self.assertEqual(saved['hostname'], b'zmala-'+self.role.encode()+b'-'+saved['machine-id'][:12]+b'\n')

    @unittest.skipIf(os.name == 'nt', 'Linux first-boot owner/mode and lock refusal')
    def test_incompatible_private_modes_locks_and_recovered_data_are_preserved(self):
        for variant in ('data-mode', 'factory-mode', 'lock-content', 'lock-link', 'recovered'):
            with self.subTest(variant=variant), prepared(self.role) as (data, facts):
                if variant == 'data-mode':
                    data.chmod(0o755)
                elif variant == 'factory-mode':
                    (data/identity.FACTORY).chmod(0o644)
                elif variant == 'lock-content':
                    (data/identity.LOCK).write_bytes(b'keep'); (data/identity.LOCK).chmod(0o600)
                elif variant == 'lock-link':
                    (data/identity.LOCK).symlink_to(data/identity.FACTORY)
                else:
                    (data/'lost+found').mkdir(mode=0o700); (data/'lost+found/recovered').write_bytes(b'keep')
                with self.assertRaises((OSError, ValueError)):
                    identity.initialize(data, self.role, facts)
                self.assertFalse((data/'identity').exists())
                if variant == 'recovered':
                    self.assertEqual((data/'lost+found/recovered').read_bytes(), b'keep')
