"""Direct compact-capacity admission, transaction and refusal assertions."""
import json
import os
from pathlib import Path
import tempfile
from contextlib import nullcontext
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from zmala_system import boot_capacity as capacity, boot_media, boot_storage, device_identity
from tests.support.boot_capacity_fixture import IDS, memory


class CapacityScenario(unittest.TestCase):
    role = 'server'

    def proposed(self, stream, slot=4):
        return capacity.plan(stream, stream.size, slot, IDS[slot-1], IDS[5])

    def test_original_relocated_and_repeated_boot_preserve_partition_rows(self):
        for size in (capacity.IMAGE_BYTES, 16000000000, 31266439168, 32000000000):
            for slot in (4, 5):
                with self.subTest(size=size, slot=slot):
                    stream = memory(size)
                    before = boot_media.inspect(stream, capacity.IMAGE_BYTES)['partitions']
                    writes = self.proposed(stream, slot)
                    self.assertEqual(bool(writes), size != capacity.IMAGE_BYTES)
                    with patch.object(capacity.os, 'fsync') as sync:
                        capacity.commit(stream, writes)
                    self.assertEqual(sync.call_count, len(writes))
                    self.assertEqual(boot_media.inspect(stream, size)['partitions'], before)
                    self.assertEqual(self.proposed(stream, slot), ())
                    allowed = {n for offset, body in writes for n in range(offset, offset+len(body))}
                    original = memory(size)
                    changed = {n for n in stream.bytes if stream.bytes[n] != original.bytes.get(n, 0)}
                    self.assertLessEqual(changed, allowed)

    def test_retry_after_every_partial_or_complete_metadata_write(self):
        for stop in range(4):
            for fraction in (0, 1, 2):
                with self.subTest(stop=stop, fraction=fraction):
                    stream = memory(); writes = self.proposed(stream)
                    for index, (offset, body) in enumerate(writes):
                        stream.seek(offset)
                        stream.write(body if index < stop else body[:len(body)*fraction//2])
                        if index == stop:
                            break
                    with patch.object(capacity.os, 'fsync'):
                        capacity.commit(stream, self.proposed(stream))
                    self.assertEqual(self.proposed(stream), ())
                    boot_media.inspect(stream, stream.size)

    def test_wrong_capacity_identity_unknown_geometry_and_corruption_are_refused(self):
        stream = memory()
        for size in (True, capacity.IMAGE_BYTES-512, 16000000001, capacity.MAX_BYTES+512):
            with self.subTest(size=size), self.assertRaises(ValueError):
                capacity.plan(stream, size, 4, IDS[3], IDS[5])
        for slot, root, data in ((3, IDS[2], IDS[5]), (4, IDS[4], IDS[5]), (4, IDS[3], IDS[0])):
            with self.assertRaises(ValueError):
                capacity.plan(stream, stream.size, slot, root, data)
        for offset in (450, 510, 512+16, 1024+32, capacity.IMAGE_BYTES-512+16):
            damaged = memory(); damaged.bytes[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                self.proposed(damaged)
        table = boot_media.inspect(stream, capacity.IMAGE_BYTES)
        table['partitions'][4]['bytes'] += 512
        with self.assertRaises(ValueError):
            capacity.layout(table, 4, IDS[3], IDS[5])
        # Even a complete new backup never authorizes repairing a changed primary array.
        damaged = memory(); writes = self.proposed(damaged)
        for offset, body in writes[:2]:
            damaged.seek(offset); damaged.write(body)
        damaged.bytes[512+16] ^= 1; damaged.bytes[1024] ^= 1
        with self.assertRaises(ValueError):
            self.proposed(damaged)

    def test_short_write_or_readback_failure_stops_transaction(self):
        stream = memory(); writes = self.proposed(stream)
        with patch.object(stream, 'write', return_value=0), self.assertRaises(OSError), \
                patch.object(capacity.os, 'fsync') as sync:
            capacity.commit(stream, writes)
        sync.assert_not_called()
        with patch.object(capacity.os, 'fsync'), patch.object(capacity, 'read_at', return_value=b'bad'), \
                self.assertRaises(OSError):
            capacity.commit(stream, writes)
        stream = memory()
        with patch.object(capacity.os, 'fsync', side_effect=OSError('sync failed')), \
                patch.object(stream, 'write', wraps=stream.write) as write, self.assertRaises(OSError):
            capacity.commit(stream, self.proposed(stream))
        self.assertEqual(write.call_count, 1)

    def test_policy_is_typed_and_old_roots_do_not_open_media(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); path = root/capacity.PROFILE
            path.parent.mkdir(parents=True)
            system = Mock()
            with patch.object(capacity, 'medium') as medium:
                capacity.prepare(root, root/'data', self.role, system, None, None, IDS[3])
                medium.assert_not_called()
            for value in ({**capacity.profile(self.role), 'schema': True}, {}, []):
                path.write_text(json.dumps(value))
                with patch.object(capacity.host_storage, 'read_record', return_value=path.read_bytes()), \
                        patch.object(capacity, 'medium') as medium, self.assertRaises(ValueError):
                    capacity.prepare(root, root/'data', self.role, system, None, None, IDS[3])
                medium.assert_not_called()

    @unittest.skipUnless(os.name == 'posix', 'Linux descriptor admission adapter')
    def test_preparation_orders_factory_check_before_writes_and_repeat_is_read_only(self):
        import stat
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); policy = root/capacity.PROFILE
            policy.parent.mkdir(parents=True); policy.write_text('{}')
            stream = memory(); number = os.makedev(179, 0)
            selected = SimpleNamespace(number=4); partition = SimpleNamespace(number=6)
            system = Mock(); system.probe.return_value = {'PART_ENTRY_UUID': IDS[5]}
            info = SimpleNamespace(st_mode=stat.S_IFBLK | 0o600, st_rdev=number)
            with patch.object(capacity.host_storage, 'read_record', return_value=json.dumps(capacity.profile(self.role)).encode()), \
                    patch.object(capacity, 'medium', return_value=(Path('/dev/mmcblk0'), number, stream.size)), \
                    patch.object(capacity.os, 'open', return_value=999) as opened, \
                    patch.object(capacity.os, 'fstat', return_value=info), \
                    patch.object(capacity.os, 'fdopen', side_effect=lambda *a, **k: nullcontext(stream)), \
                    patch.object(capacity.os, 'fsync'), \
                    patch.object(device_identity, 'exclusive', side_effect=lambda *a: nullcontext()), \
                    patch.object(capacity, 'factory') as factory:
                factory.side_effect = ValueError('initialized')
                with self.assertRaisesRegex(ValueError, 'initialized'):
                    capacity.prepare(root, root/'data', self.role, system, selected, partition, IDS[3])
                self.assertEqual(opened.call_count, 1)
                self.assertEqual(opened.call_args.args[1] & os.O_RDWR, 0)
                self.assertTrue(self.proposed(stream))
                factory.reset_mock(); factory.side_effect = None; opened.reset_mock()
                capacity.prepare(root, root/'data', self.role, system, selected, partition, IDS[3])
                self.assertEqual(factory.call_count, 2)
                self.assertEqual(opened.call_count, 2)
                self.assertTrue(opened.call_args.args[1] & os.O_RDWR)
                self.assertTrue(opened.call_args.args[1] & os.O_NOFOLLOW)
                self.assertEqual(self.proposed(stream), ())
                factory.reset_mock(); opened.reset_mock()
                capacity.prepare(root, root/'data', self.role, system, selected, partition, IDS[3])
                factory.assert_not_called(); self.assertEqual(opened.call_count, 1)
                self.assertEqual(opened.call_args.args[1] & os.O_RDWR, 0)
    def test_factory_rejects_initialized_or_foreign_data(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder); (data/device_identity.FACTORY).touch()
            with patch.object(device_identity, 'admit'), patch.object(device_identity, 'factory_record'):
                capacity.factory(data, self.role, Mock())
                for name in ('identity', '.zmala-storage.json', 'unknown'):
                    (data/name).touch()
                    with self.subTest(name=name), self.assertRaises(ValueError):
                        capacity.factory(data, self.role, Mock())
                    (data/name).unlink()

    @unittest.skipUnless(os.name == 'posix', 'Linux boot adapter; portable policy assertions run separately')
    def test_capacity_failure_fences_identity_and_normal_boot(self):
        from tests.support.boot_storage_unit import operations
        with operations(self.role) as state, \
                patch.object(capacity, 'prepare', side_effect=ValueError('capacity refused')) as operation, \
                patch.object(device_identity, 'initialize') as identity:
            with self.assertRaisesRegex(ValueError, 'capacity refused'):
                boot_storage.prepare(state.root, self.role, state.area, state.system)
            operation.assert_called_once()
            identity.assert_not_called()
            self.assertFalse((state.area/boot_storage.READY).exists())

    @unittest.skipUnless(os.name == 'posix', 'Linux sysfs/block adapter with controlled stat')
    def test_native_parent_refuses_wrong_board_transport_and_geometry(self):
        from tests.support.boot_storage_kernel_fixture import kernel_tree
        import stat
        with kernel_tree() as fixture:
            parent = fixture.parent
            for name, body in {'uevent': 'DEVTYPE=disk\nDEVNAME=mmcblk0\n',
                               'size': str(16000000000//512), 'device/type': 'SD\n',
                               'queue/logical_block_size': '512\n'}.items():
                path = parent/name; path.parent.mkdir(exist_ok=True); path.write_text(body)
            for number in (4, 6):
                child = parent/f'mmcblk0p{number}'
                (child/'size').write_text(str(capacity.SIZES[number-1]//512))
                (child/'start').write_text(str((boot_media.FIRST_PARTITION_BYTES+sum(capacity.SIZES[:number-1]))//512))
            node = fixture.nodes/'mmcblk0'; node.touch()
            fixture.node_info[node] = SimpleNamespace(st_mode=stat.S_IFBLK | 0o600, st_rdev=os.makedev(179, 0))
            selected = fixture.system.partition('179:4'); data = fixture.system.partition('179:6')
            model = fixture.base/'model'; model.write_bytes(b'Raspberry Pi 4 Model B Rev 1.5\0')
            self.assertEqual(capacity.medium(fixture.system, selected, data, model)[2], 16000000000)
            for path, value in ((parent/'device/type', b'MMC\n'), (model, b'Raspberry Pi 5 Model B\0'),
                                (parent/'queue/logical_block_size', b'4096\n'),
                                (parent/'mmcblk0p6/start', b'1\n')):
                saved = path.read_bytes(); path.write_bytes(value)
                with self.subTest(path=path), self.assertRaises(ValueError):
                    capacity.medium(fixture.system, selected, data, model)
                path.write_bytes(saved)
