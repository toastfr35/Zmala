"""Direct boot-policy verification with controlled kernel and operation facts."""
import contextlib
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from zmala_system import boot_devices as devices, boot_entry as entry, boot_gate as gate
from zmala_system import boot_layout as layout, boot_storage as storage
from tests.support import appliance_storage_fixture
from tests.support.appliance_storage_unit import controlled_ownership, info
from tests.support.boot_storage_kernel_fixture import kernel_tree

ROOT_UUID = '12345678-1234-1234-1234-123456789abc'
DATA_UUID = '87654321-4321-4321-4321-cba987654321'
ROOT_FS = '11111111-1234-1234-1234-123456789abc'
DATA_FS = '22222222-1234-1234-1234-123456789abc'


def probe(number, label, parent, partition, filesystem):
    return {'TYPE': 'ext4', 'USAGE': 'filesystem', 'LABEL': label,
            'PART_ENTRY_SCHEME': 'gpt', 'PART_ENTRY_NAME': label,
            'PART_ENTRY_TYPE': layout.LINUX_PARTITION, 'PART_ENTRY_NUMBER': str(number),
            'PART_ENTRY_DISK': parent, 'PART_ENTRY_UUID': partition, 'UUID': filesystem,
            'FSSIZE': '33554432'}


class KernelFacts:
    def __init__(self, name='mmcblk0'):
        parent = Path('/sys/devices/fixture/block')/name
        self.root = devices.Partition(4, '179:4', '179:0', parent, Path('/dev')/(name+'p4'), 65536)
        self.data = devices.Partition(6, '179:6', '179:0', parent, Path('/dev')/(name+'p6'), 65536)
        self.records = {self.root.device: probe(4, 'system_a', '179:0', ROOT_UUID, ROOT_FS),
                        self.data.device: probe(6, 'persistent', '179:0', DATA_UUID, DATA_FS)}
        self.calls = []

    def partition(self, device):
        self.calls.append(('partition', device))
        if device != self.root.device:
            raise ValueError('unknown fixture device')
        return self.root

    def data_sibling(self, root, number):
        self.calls.append(('sibling', root.device, number))
        return self.data

    def probe(self, partition):
        self.calls.append(('probe', partition.device))
        return dict(self.records[partition.device])


class OperationFacts(KernelFacts):
    def __init__(self, root, ram):
        super().__init__()
        self.target = root/'data'
        self.table = {root: storage.host_storage.Mount(root, self.root.device, frozenset({'ro'}), 'ext4'),
                      ram: storage.host_storage.Mount(ram, '0:91', frozenset({'rw'}), 'tmpfs')}
        self.operations = []
        self.fail_mount = None
        self.inspection_failure = None

    def facts(self):
        if self.inspection_failure:
            error, self.inspection_failure = self.inspection_failure, None
            raise error
        return dict(self.table)

    def boot_arguments(self):
        return 'A', ROOT_UUID

    def run(self, args):
        self.operations.append(args[0])
        if args[0] == 'mount':
            if self.fail_mount == 'before':
                raise OSError('primary mount failure')
            self.table[self.target] = storage.host_storage.Mount(
                self.target, self.data.device, frozenset({'rw'}), 'ext4')
            if self.fail_mount in ('after', 'inspection'):
                if self.fail_mount == 'inspection':
                    self.inspection_failure = OSError('secondary inspection failure')
                raise OSError('primary mount failure')
        elif args == ['umount', str(self.target)]:
            del self.table[self.target]
        else:
            raise AssertionError('Unexpected fixture operation')


@contextlib.contextmanager
def operations(role):
    with tempfile.TemporaryDirectory() as temporary, controlled_ownership(), \
            patch.object(storage.platform, 'system', return_value='Linux'), \
            patch.object(storage.os, 'geteuid', return_value=0, create=True), \
            patch.object(storage.os, 'getegid', return_value=0, create=True):
        base = Path(temporary)
        root = appliance_storage_fixture.image(base/'root', role)
        appliance_storage_fixture.file(root/layout.PROFILE, json.dumps(layout.profile(role)).encode())
        ram = base/'ram'; ram.mkdir(mode=0o700)
        system = OperationFacts(root, ram)
        state = SimpleNamespace(root=root, area=ram/'host', system=system, cleanup_error=False)
        def initialize(*args):
            system.operations.append('initialize')
        def views(*args):
            system.operations.append('views')
            state.area.mkdir(mode=0o700)
            target = root/'etc'
            system.table[target] = storage.host_storage.Mount(target, '0:92', frozenset({'rw'}), 'overlay')
            def close():
                system.operations.append('views-close')
                if state.cleanup_error:
                    raise OSError('secondary cleanup failure')
                del system.table[target]
                state.area.rmdir()
            return SimpleNamespace(close=close)
        with patch.object(storage.device_identity, 'initialize', side_effect=initialize) as init, \
                patch.object(storage.host_storage, 'prepare', side_effect=views) as view:
            state.initialize, state.views = init, view
            yield state


class BootStorageScenario(unittest.TestCase):
    role = None

    def test_exact_profile_types_bounds_duplicates_and_roles(self):
        expected = layout.profile(self.role)
        self.assertEqual(layout.decode_profile(json.dumps(expected).encode(), self.role), expected)
        invalid = [{**expected, 'schema': True}, {**expected, 'role': 'wrong'},
                   {**expected, 'root_a_partition': '4'}, {**expected, 'extra': 1}, [], {}]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                layout.decode_profile(json.dumps(value).encode(), self.role)
        for body in (b'', b' '*8193, b'{"schema":1,"schema":1}'):
            with self.assertRaises(ValueError):
                layout.decode_profile(body, self.role)
        with self.assertRaises(ValueError):
            layout.profile('wrong')

    def test_kernel_arguments_accept_multiple_consoles_but_no_ambiguous_root(self):
        line = b'console=tty0 console=ttyAMA0 root=PARTUUID='+ROOT_UUID.encode()+b' rauc.slot=A ro'
        self.assertEqual(layout.command_line(line), ('A', ROOT_UUID))
        for body in (b'', b' '*8193, line+b'\0', line+b' root=other', line+b' rauc.slot=B',
                     line.replace(b'rauc.slot=A', b'rauc.slot=C'), line.replace(b'rauc.slot=A', b'rauc.slot'),
                     b'root=LABEL=system_a rauc.slot=A', b'rauc.slot=A', b'root=PARTUUID='+ROOT_UUID.encode(),
                     line.replace(ROOT_UUID.encode(), ROOT_UUID.upper().encode()),
                     line.replace(ROOT_UUID.encode(), b'00000000-0000-0000-0000-000000000000')):
            with self.subTest(body=body), self.assertRaises(ValueError):
                layout.command_line(body)

    def test_device_numbers_and_probe_record_limits_and_duplicates(self):
        self.assertEqual(layout.device_number('179:4'), (179, 4))
        for value in ('0:0', '0179:4', '179:04', '4096:0', '1:1048576', '1:1/../../', '', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                layout.device_number(value)
        record = probe(4, 'system_a', '179:0', ROOT_UUID, ROOT_FS)
        encoded = ''.join(key+'='+value+'\n' for key, value in record.items()).encode()
        self.assertEqual(layout.probe_record(encoded), record)
        for body in (b'', b'x'*16385, encoded+b'TYPE=ext4\n', b'TYPE\n', b'TYPE=\n',
                     b'bad-key=ext4\n', b'TYPE=ext4\0', b'X='+b'x'*4097):
            with self.subTest(body=body[:50]), self.assertRaises(ValueError):
                layout.probe_record(body)

    def test_same_parent_discovery_uses_selected_root_for_pi_nvme_and_loop_names(self):
        for name in ('mmcblk0', 'nvme0n1', 'loop27'):
            with self.subTest(name=name):
                system = KernelFacts(name)
                root, data = devices.discover(system, layout.profile(self.role), 'A', ROOT_UUID, '179:4')
                self.assertEqual((root, data), (system.root, system.data))
                self.assertEqual(system.calls, [('partition', '179:4'), ('probe', '179:4'),
                                                ('sibling', '179:4', 6), ('probe', '179:6')])

    def test_slot_parent_number_type_and_uuid_mismatches_are_rejected(self):
        for key, value in (('TYPE', 'vfat'), ('PART_ENTRY_SCHEME', 'dos'),
                           ('PART_ENTRY_NAME', 'other'), ('LABEL', 'other'),
                           ('PART_ENTRY_TYPE', DATA_UUID), ('PART_ENTRY_NUMBER', '5'),
                           ('PART_ENTRY_DISK', '8:0'), ('PART_ENTRY_UUID', DATA_UUID),
                           ('UUID', 'invalid')):
            with self.subTest(key=key):
                system = KernelFacts(); system.records[system.root.device][key] = value
                with self.assertRaises(ValueError):
                    devices.discover(system, layout.profile(self.role), 'A', ROOT_UUID, '179:4')
        for variant in ('wrong-slot', 'wrong-data-number', 'other-parent', 'other-parent-device', 'same-device',
                        'filesystem-alias', 'partition-alias'):
            with self.subTest(variant=variant):
                system = KernelFacts()
                if variant == 'wrong-slot':
                    system.root = replace(system.root, number=5)
                elif variant == 'wrong-data-number':
                    system.data = replace(system.data, number=5)
                elif variant == 'other-parent':
                    system.data = replace(system.data, parent=Path('/sys/devices/other'))
                elif variant == 'other-parent-device':
                    system.data = replace(system.data, parent_device='8:0')
                elif variant == 'same-device':
                    system.data = replace(system.data, device=system.root.device)
                elif variant == 'filesystem-alias':
                    system.records[system.data.device]['UUID'] = ROOT_FS
                else:
                    system.records[system.data.device]['PART_ENTRY_UUID'] = ROOT_UUID
                with self.assertRaises(ValueError):
                    devices.discover(system, layout.profile(self.role), 'A', ROOT_UUID, '179:4')

    def test_native_tools_are_fixed_and_mount_helper_rejects_other_commands(self):
        with self.assertRaises(ValueError):
            devices.NativeBoot(tools={'mount': '/bin/mount'})
        with self.assertRaises(ValueError):
            devices.NativeBoot(tools={'mount': 'relative', 'umount': '/bin/umount', 'blkid': '/bin/blkid'})
        native = devices.NativeBoot()
        with patch.object(devices.subprocess, 'run') as call:
            for args in ([], ['mkfs.ext4', '/dev/untrusted'], ['sh', '-c', 'untrusted']):
                with self.assertRaises(ValueError):
                    native.run(args)
            call.assert_not_called()
            native.run(['umount', '/root/data'])
            self.assertEqual(call.call_args.args[0], ['/usr/lib/zmala/bin/umount', '/root/data'])
            self.assertEqual(call.call_args.kwargs['timeout'], 30)
            self.assertIs(call.call_args.kwargs['stderr'], subprocess.DEVNULL)

    def test_native_probe_binds_filesystem_geometry_to_kernel_partition(self):
        system = KernelFacts()
        native = devices.NativeBoot()
        for value in ('0', 'not-a-size', '33554433'):
            record = dict(system.records[system.root.device], FSSIZE=value)
            body = ''.join(key+'='+item+'\n' for key, item in record.items()).encode()
            with patch.object(devices, 'bounded_probe', return_value=body), self.assertRaises(ValueError):
                native.probe(system.root)
        record = system.records[system.root.device]
        body = ''.join(key+'='+item+'\n' for key, item in record.items()).encode()
        with patch.object(devices, 'bounded_probe', return_value=body) as bounded:
            self.assertEqual(native.probe(system.root), record)
            self.assertEqual(bounded.call_args.args[0][:4], ['/usr/lib/zmala/bin/blkid', '-p', '-o', 'export'])

    @unittest.skipIf(os.name == 'nt', 'Unix kernel-link paths and block stat model')
    def test_native_topology_validates_parent_node_and_bounded_attributes(self):
        with kernel_tree() as tree:
            root = tree.system.partition('179:4')
            data = tree.system.data_sibling(root, 6)
            self.assertEqual((root.number, data.number, data.parent_device), (4, 6, '179:0'))
            self.assertEqual(root.parent, data.parent)
        for variant in ('wrong-node', 'regular-node', 'unsafe-name', 'wrong-partn', 'changed-dev',
                        'oversized-attribute', 'escaped-sysfs', 'linked-attribute'):
            with self.subTest(variant=variant), kernel_tree() as tree:
                child = tree.parent/'mmcblk0p4'
                if variant == 'wrong-node':
                    tree.node_info[tree.nodes/child.name].st_rdev = os.makedev(179, 5)
                elif variant == 'regular-node':
                    tree.node_info[tree.nodes/child.name].st_mode = 0o100600
                elif variant == 'unsafe-name':
                    (child/'uevent').write_text('DEVNAME=../wrong\nDEVTYPE=partition\nPARTN=4\n')
                elif variant == 'wrong-partn':
                    (child/'uevent').write_text('DEVNAME=mmcblk0p4\nDEVTYPE=partition\nPARTN=5\n')
                elif variant == 'changed-dev':
                    (child/'dev').write_text('179:5\n')
                elif variant == 'oversized-attribute':
                    (child/'partition').write_bytes(b'4'*257)
                elif variant == 'escaped-sysfs':
                    (tree.links/'179:4').unlink(); (tree.links/'179:4').symlink_to(tree.base)
                else:
                    (child/'partition').unlink(); (child/'partition').symlink_to(child/'size')
                with self.assertRaises((OSError, ValueError)):
                    tree.system.partition('179:4')

    @unittest.skipIf(os.name == 'nt', 'Unix kernel sibling discovery model')
    def test_native_sibling_refuses_missing_duplicate_cross_parent_and_oversized_tree(self):
        for variant in ('missing', 'duplicate', 'cross-parent', 'oversized-tree'):
            with self.subTest(variant=variant), kernel_tree() as tree:
                root = tree.system.partition('179:4')
                child = tree.parent/'mmcblk0p6'
                if variant == 'missing':
                    (child/'partition').unlink()
                elif variant == 'duplicate':
                    (tree.parent/'alias').symlink_to(child, target_is_directory=True)
                elif variant == 'cross-parent':
                    other = tree.kernel/'other'; other.mkdir(); (other/'dev').write_text('8:0\n')
                    child.rename(other/child.name)
                    child.symlink_to(other/child.name, target_is_directory=True)
                    (tree.links/'179:6').unlink(); (tree.links/'179:6').symlink_to(other/child.name)
                else:
                    for number in range(257):
                        (tree.parent/('extra-'+str(number))).mkdir()
                with self.assertRaises(ValueError):
                    tree.system.data_sibling(root, 6)

    def test_boot_preparation_requires_linux_root_before_reading_system_facts(self):
        for platform, uid, gid in (('Windows', 0, 0), ('Linux', 1000, 0), ('Linux', 0, 1000)):
            system = Mock()
            with patch.object(storage.platform, 'system', return_value=platform), \
                    patch.object(storage.os, 'geteuid', return_value=uid, create=True), \
                    patch.object(storage.os, 'getegid', return_value=gid, create=True), self.assertRaises(ValueError):
                storage.prepare(Path('/root'), self.role, system=system)
            system.facts.assert_not_called()

    def test_boot_root_owner_refusal_precedes_policy_reads(self):
        root, area = Path('/fixture/root'), Path('/fixture/ram/area')
        facts = {root: storage.host_storage.Mount(root, '179:4', frozenset({'ro'}), 'ext4')}
        for actual in (info(0o40755, uid=1000), info(0o40755, gid=1000)):
            with patch.object(storage.host_storage, 'canonical', side_effect=lambda path: path), \
                    patch.object(Path, 'lstat', return_value=actual), \
                    patch.object(storage.host_storage, 'read_record') as record, self.assertRaises(ValueError):
                storage.admit(root, area, self.role, facts)
            record.assert_not_called()

    @unittest.skipIf(os.name == 'nt', 'Linux boot paths and filesystem modes')
    def test_invalid_mount_ram_policy_and_occupied_data_refuse_before_operations(self):
        for variant in ('rw-root', 'wrong-root-fs', 'ro-ram', 'wrong-ram-fs', 'occupied',
                        'existing-area', 'conflicting-mount', 'data-in-use', 'wrong-profile',
                        'profile-mode', 'public-ram-parent'):
            with self.subTest(variant=variant), operations(self.role) as state:
                root, area, system = state.root, state.area, state.system
                if variant == 'rw-root':
                    system.table[root] = replace(system.table[root], flags=frozenset({'rw'}))
                elif variant == 'wrong-root-fs':
                    system.table[root] = replace(system.table[root], filesystem='tmpfs')
                elif variant == 'ro-ram':
                    system.table[area.parent] = replace(system.table[area.parent], flags=frozenset({'ro'}))
                elif variant == 'wrong-ram-fs':
                    system.table[area.parent] = replace(system.table[area.parent], filesystem='ext4')
                elif variant == 'occupied':
                    (root/'data/keep').write_bytes(b'preserve')
                elif variant == 'existing-area':
                    area.mkdir()
                elif variant == 'conflicting-mount':
                    system.table[root/'etc'] = replace(system.table[root], point=root/'etc')
                elif variant == 'data-in-use':
                    system.table[Path('/previous-data')] = replace(system.table[root], point=Path('/previous-data'),
                                                                  device=system.data.device)
                elif variant == 'wrong-profile':
                    (root/layout.PROFILE).write_text('{}')
                elif variant == 'profile-mode':
                    (root/layout.PROFILE).chmod(0o600)
                else:
                    area.parent.chmod(0o777)
                with self.assertRaises(ValueError):
                    storage.prepare(root, self.role, area, system)
                self.assertEqual(system.operations, [])
                state.initialize.assert_not_called(); state.views.assert_not_called()

    @unittest.skipIf(os.name == 'nt', 'Linux boot readiness file publication')
    def test_ordered_success_requires_complete_views_then_owned_reverse_cleanup(self):
        with operations(self.role) as state:
            original = state.system.facts()
            result = storage.prepare(state.root, self.role, state.area, state.system)
            self.assertTrue(result.ready)
            self.assertEqual(state.system.operations, ['mount', 'initialize', 'views'])
            marker = json.loads((state.area/storage.READY).read_text())
            self.assertEqual(marker, {'schema': 1, 'role': self.role, 'slot': 'A', 'boot_storage_prepared': True})
            self.assertEqual((state.area/storage.READY).stat().st_mode & 0o777, 0o600)
            self.assertTrue((state.root/'etc/fstab').read_text().endswith('PARTUUID='+ROOT_UUID+' / ext4 ro 0 0\n'))
            result.close()
            self.assertFalse(result.ready)
            self.assertEqual(state.system.operations[-2:], ['views-close', 'umount'])
            self.assertEqual(state.system.facts(), original)

    @unittest.skipIf(os.name == 'nt', 'Linux boot mount and partial-success cleanup')
    def test_failed_data_mount_and_secondary_inspection_preserve_primary_error(self):
        for outcome in ('before', 'after', 'inspection'):
            with self.subTest(outcome=outcome), operations(self.role) as state:
                original = state.system.facts(); state.system.fail_mount = outcome
                with self.assertRaisesRegex(OSError, 'primary mount failure'):
                    storage.prepare(state.root, self.role, state.area, state.system)
                self.assertEqual(state.system.facts(), original)
                state.initialize.assert_not_called(); state.views.assert_not_called()
                self.assertFalse((state.area/storage.READY).exists())

    @unittest.skipIf(os.name == 'nt', 'Linux boot file failure and dependent-mount cleanup')
    def test_status_failure_preserves_original_and_retains_data_if_views_cannot_close(self):
        for cleanup_error in (False, True):
            with self.subTest(cleanup_error=cleanup_error), operations(self.role) as state:
                original = state.system.facts(); state.cleanup_error = cleanup_error
                failure = OSError('primary readiness failure')
                write = storage.device_identity.write_exclusive
                def fail_status(path, body, mode):
                    if path == state.area/storage.NEXT:
                        raise failure
                    return write(path, body, mode)
                with patch.object(storage.device_identity, 'write_exclusive', side_effect=fail_status), \
                        self.assertRaises(OSError) as error:
                    storage.prepare(state.root, self.role, state.area, state.system)
                self.assertIs(error.exception, failure)
                self.assertFalse((state.area/storage.READY).exists())
                if cleanup_error:
                    self.assertIn(state.root/'data', state.system.facts())
                    self.assertNotIn('umount', state.system.operations)
                else:
                    self.assertEqual(state.system.facts(), original)

    @unittest.skipIf(os.name == 'nt', 'Linux boot dependency failure cleanup')
    def test_identity_view_or_root_config_failures_retain_saved_bytes_and_unmount_owned_data(self):
        for stage in ('identity', 'views', 'fstab'):
            with self.subTest(stage=stage), operations(self.role) as state:
                original = state.system.facts()
                failure = OSError('primary dependency failure')
                saved = state.root/'data/saved-fixture'
                def initialize(*args):
                    state.system.operations.append('initialize')
                    saved.write_bytes(b'committed synthetic data')
                    if stage == 'identity':
                        raise failure
                state.initialize.side_effect = initialize
                if stage == 'views':
                    state.views.side_effect = failure
                write = storage.device_identity.write_exclusive
                def fail_config(path, body, mode):
                    if stage == 'fstab' and path == state.root/'etc/fstab.next':
                        raise failure
                    return write(path, body, mode)
                with patch.object(storage.device_identity, 'write_exclusive', side_effect=fail_config), \
                        self.assertRaises(OSError) as error:
                    storage.prepare(state.root, self.role, state.area, state.system)
                self.assertIs(error.exception, failure)
                self.assertEqual(state.system.facts(), original)
                self.assertEqual(saved.read_bytes(), b'committed synthetic data')
                self.assertFalse((state.area/storage.READY).exists())

    @unittest.skipIf(os.name == 'nt', 'Linux selector support for child-process pipes')
    def test_probe_process_output_timeout_and_error_are_bounded(self):
        prefix = [sys.executable, '-I', '-c']
        self.assertEqual(devices.bounded_probe(prefix+['print("bounded")']), b'bounded\n')
        with self.assertRaises(ValueError):
            devices.bounded_probe(prefix+['import sys;sys.stdout.write("x"*16385)'])
        with self.assertRaises(subprocess.CalledProcessError):
            devices.bounded_probe(prefix+['raise SystemExit(3)'])
        with self.assertRaises(subprocess.TimeoutExpired):
            devices.bounded_probe(prefix+['import time;time.sleep(10)'], timeout=0.05)

    def test_readiness_records_require_exact_typed_current_boot_success(self):
        expected = {'schema': 1, 'role': self.role, 'slot': 'A', 'boot_storage_prepared': True}
        for value in ({**expected, 'schema': True}, {**expected, 'boot_storage_prepared': 1},
                      {**expected, 'role': 'wrong'}, {**expected, 'slot': 'B'}, {**expected, 'extra': 1}):
            with patch.object(storage.host_storage, 'read_record', return_value=json.dumps(value).encode()), \
                    self.assertRaises(ValueError):
                gate.record(Path('/run/fixture'), storage.READY, expected)
        with patch.object(storage.host_storage, 'read_record', return_value=json.dumps(expected).encode()) as read:
            gate.record(Path('/run/fixture'), storage.READY, expected)
            self.assertEqual(read.call_args.args[2:], (0o600, 8192))

    def test_entry_success_and_incomplete_or_unexpected_failures_do_not_bypass_barrier(self):
        class Fenced(BaseException):
            pass
        barrier = Mock(side_effect=Fenced)
        self.assertEqual(entry.run(Path('/root'), self.role,
                                   prepare=Mock(return_value=SimpleNamespace(ready=True)), barrier=barrier), 0)
        barrier.assert_not_called()
        for result in (SimpleNamespace(ready=False), None, OSError('private detail'),
                       RuntimeError('private detail'), SystemExit('private detail')):
            options = {'side_effect': result} if isinstance(result, BaseException) else {'return_value': result}
            output = io.StringIO()
            with contextlib.redirect_stderr(output), self.assertRaises(Fenced):
                entry.run(Path('/root'), self.role, prepare=Mock(**options), barrier=barrier)
            self.assertIn('Normal startup is blocked', output.getvalue())
            self.assertNotIn('private detail', output.getvalue())
        waits = []
        def wait(seconds):
            waits.append(seconds)
            if len(waits) == 2:
                raise Fenced()
        with self.assertRaises(Fenced):
            entry.failure_barrier(wait)
        self.assertEqual(waits, [60, 60])

    def test_pid1_gate_returns_failure_for_any_invalid_or_missing_preparation(self):
        output = io.StringIO()
        with patch.object(sys, 'argv', ['boot_gate']), patch.object(gate, 'verify', return_value=True):
            self.assertEqual(gate.main(), 0)
        for error in (OSError('private detail'), ValueError('private detail'), RuntimeError('private detail')):
            with patch.object(sys, 'argv', ['boot_gate']), patch.object(gate, 'verify', side_effect=error), \
                    contextlib.redirect_stderr(output):
                self.assertEqual(gate.main(), 1)
        self.assertNotIn('private detail', output.getvalue())

    @unittest.skipUnless(os.name == 'posix', 'The installed PID1 root path is POSIX')
    def test_pid1_gate_accepts_canonical_root_path_before_policy_validation(self):
        self.assertEqual(storage.host_storage.canonical(Path('/')), Path('/'))
        for value in ('relative/path', '/tmp/../tmp', '/tmp/with space'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                storage.host_storage.canonical(Path(value))
        # Do not inspect this development host as an appliance. Reaching the
        # policy boundary proves the real default '/' survived path admission.
        with patch.object(storage, 'configured_role', side_effect=ValueError('fixture policy boundary')) as policy:
            with self.assertRaisesRegex(ValueError, 'fixture policy boundary'):
                gate.verify()
        policy.assert_called_once_with(Path('/'))
