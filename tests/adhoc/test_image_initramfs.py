"""Offline initramfs tool checks; not product boot or hardware qualification."""
import io
import json
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from zmala_images import image_state, initramfs_build as build, initramfs_worker as worker, package_lock
from tests.adhoc.test_image_root_build import SELECTED
from tests.adhoc.test_image_state import fixture
from tests.support.appliance_storage_unit import controlled_ownership


def copied_tree(base, main_subdirectory=True, role='server'):
    root = base/'source'; root.mkdir()
    extracted = base/'extracted'; extracted.mkdir()
    main = extracted/'main' if main_subdirectory else extracted
    main.mkdir(exist_ok=True)
    payload = image_state.payloads(role)
    # The shell hook copies the same early-boot files for every role.
    paths = [name for name in image_state.payloads('server')
             if name.startswith(image_state.INSTALLED+'/') or name == 'usr/lib/zmala/role']
    for name in paths:
        target = main/name; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload[name]); target.chmod(0o644)
    if role == 'terminal':
        for folder in (root, main):
            theme = folder/'usr/share/plymouth/themes/zmala'
            theme.mkdir(parents=True)
            for name in ('zmala.plymouth', 'zmala.script', 'boot-family.png'):
                (theme/name).write_bytes(name.encode())
        config = main/'etc/plymouth/plymouthd.conf'
        config.parent.mkdir(parents=True)
        config.write_text('Theme=zmala\n')
        plugin = main/'usr/lib/aarch64-linux-gnu/plymouth/script.so'
        plugin.parent.mkdir(parents=True)
        plugin.touch()
    entry = main/'scripts/local-bottom/zmala-host'; entry.parent.mkdir(parents=True)
    entry.write_bytes(Path(worker.__file__).with_name('initramfs_entry.sh').read_bytes()); entry.chmod(0o755)
    order = entry.parent/'ORDER'
    order.write_text('/scripts/local-bottom/zmala-host "$@"\n[ -e /conf/param.conf ] && . /conf/param.conf\n')
    order.chmod(0o644)
    for name, source, target in [('python', 'usr/bin/python3.13', 'usr/bin/python3.13')]+[
            (name, 'usr/bin/'+name, 'usr/lib/zmala/bin/'+name) for name in ('mount', 'umount', 'blkid')]:
        body = ('synthetic executable-byte fixture '+name).encode()
        for parent, relative in ((root, source), (main, target)):
            path = parent/relative; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body); path.chmod(0o755)
    return root, extracted, main


class InitramfsToolTests(unittest.TestCase):
    def test_kernel_selection_requires_unique_match_to_firmware(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old, current = '6.18.50+rpt-rpi-v8', '6.18.60+rpt-rpi-v8'
            for version, payload in ((old, b'old'), (current, b'new')):
                (root/'usr/lib/modules'/version).mkdir(parents=True)
                (root/'boot/firmware').mkdir(parents=True, exist_ok=True)
                (root/'boot'/('vmlinuz-'+version)).write_bytes(payload)
            firmware = root/'boot/firmware/kernel8.img'
            firmware.write_bytes(b'new')
            self.assertEqual(worker.firmware_kernel_version(root), current)
            firmware.write_bytes(b'bad')
            with self.assertRaisesRegex(ValueError, 'Expected one module version'):
                worker.firmware_kernel_version(root)
            firmware.write_bytes(b'new')
            (root/'boot'/('vmlinuz-'+old)).write_bytes(b'new')
            with self.assertRaisesRegex(ValueError, 'Expected one module version'):
                worker.firmware_kernel_version(root)

    def test_platform_and_root_refused_before_cache_or_source_access(self):
        for system, uid in (('Windows', 1000), ('Linux', 0)):
            with patch.object(build.platform, 'system', return_value=system), \
                    patch.object(build.os, 'geteuid', return_value=uid, create=True), \
                    patch.object(build.local_repo, 'inputs') as inputs, self.assertRaises(ValueError):
                build.build('server', 'source', 'a'*64, 'base', 'role', 'output')
            inputs.assert_not_called()

    def test_reviewed_source_digest_and_full_prepared_archive_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); raw = root/'raw.tar'; fixture(raw)
            image_state.prepare(raw, package_lock.digest(raw), SELECTED, 'server', root/'prepared')
            source = root/'prepared/root.tar'; digest = package_lock.digest(source)
            self.assertEqual(build.checked_source(source, digest, SELECTED, 'server')['packages'], 1)
            with self.assertRaises(ValueError):
                build.checked_source(source, '0'*64, SELECTED, 'server')
            with self.assertRaises(ValueError):
                build.checked_source(source, digest, SELECTED, 'terminal')

    def test_worker_refuses_host_namespaces_before_unpack_or_mount(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'request.json'
            request = {'schema': 1, 'role': 'server', 'source': '/not-read', 'sha256': 'a'*64,
                       'output': str(path.parent), 'checkout': '/not-read',
                       'host_namespaces': dict.fromkeys(('user', 'mnt', 'pid', 'net'), 'same-namespace')}
            path.write_text(json.dumps(request))
            with patch.object(worker.os, 'geteuid', return_value=0, create=True), \
                    patch.object(worker.os, 'readlink', return_value='same-namespace'), \
                    patch.object(worker, 'command') as command, self.assertRaises(ValueError):
                worker.worker(path)
            command.assert_not_called()

    @unittest.skipIf(os.name == 'nt', 'Linux GNU tar rootless device exclusion')
    def test_unpack_omits_only_root_dev_not_kernel_driver_dev_directories(self):
        self.assertIsNotNone(shutil.which('tar'))
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary); archive = base/'root.tar'; target = base/'root'; target.mkdir()
            with tarfile.open(archive, 'w') as output:
                device = tarfile.TarInfo('dev/null'); device.type = tarfile.CHRTYPE
                device.devmajor, device.devminor = 1, 3; output.addfile(device)
                for name in ('usr/lib/modules/test/kernel/drivers/net/can/dev/keep.ko', 'usr/lib/example/data'):
                    member = tarfile.TarInfo(name); member.size = 4; output.addfile(member, io.BytesIO(b'keep'))
            with patch.dict(os.environ, SOURCE_DATE_EPOCH='1793836800'):
                worker.unpack_root(archive, target)
            self.assertFalse((target/'dev/null').exists())
            self.assertEqual((target/'usr/lib/modules/test/kernel/drivers/net/can/dev/keep.ko').read_bytes(), b'keep')
            self.assertEqual((target/'usr/lib/example/data').read_bytes(), b'keep')

    @unittest.skipIf(os.name == 'nt', 'Unix copied-payload modes and modeled root ownership')
    def test_extracted_main_and_direct_layouts_have_exact_runtime_and_binary_bytes(self):
        for nested in (False, True):
            with self.subTest(nested=nested), tempfile.TemporaryDirectory() as temporary, controlled_ownership():
                root, extracted, main = copied_tree(Path(temporary), nested)
                actual, checked, binaries = worker.inspect_initramfs(root, extracted, 'server')
                self.assertEqual(actual, main)
                self.assertIn(image_state.INSTALLED+'/boot_gate.py', checked)
                self.assertEqual(set(binaries), {'python3.13', 'mount', 'umount', 'blkid'})

    @unittest.skipIf(os.name == 'nt', 'Unix copied-payload modes and modeled root ownership')
    def test_terminal_initramfs_does_not_require_system_updater(self):
        with tempfile.TemporaryDirectory() as temporary, controlled_ownership():
            root, extracted, main = copied_tree(Path(temporary), role='terminal')
            actual, checked, _ = worker.inspect_initramfs(root, extracted, 'terminal')
            self.assertEqual(actual, main)
            self.assertIn(image_state.INSTALLED+'/boot_gate.py', checked)
            self.assertNotIn(image_state.INSTALLED+'/update_coordinator.py', checked)

    @unittest.skipIf(os.name == 'nt', 'Unix payload integrity/modes and symlink refusal')
    def test_runtime_entry_binary_and_link_tampering_is_rejected(self):
        for variant in ('runtime', 'entry', 'mode', 'binary', 'source-link'):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as temporary, controlled_ownership():
                root, extracted, main = copied_tree(Path(temporary))
                if variant == 'runtime':
                    (main/image_state.INSTALLED/'boot_storage.py').write_bytes(b'changed')
                elif variant == 'entry':
                    (main/'scripts/local-bottom/zmala-host').write_bytes(b'changed')
                elif variant == 'mode':
                    (main/'usr/lib/zmala/bin/mount').chmod(0o4755)
                elif variant == 'binary':
                    (main/'usr/lib/zmala/bin/blkid').write_bytes(b'changed')
                else:
                    (root/'usr/bin/mount').unlink(); (root/'usr/bin/mount').symlink_to(main/'usr/lib/zmala/bin/mount')
                with self.assertRaises(ValueError):
                    worker.inspect_initramfs(root, extracted, 'server')

    @unittest.skipIf(os.name == 'nt', 'Unix extracted dispatch metadata')
    def test_entry_present_but_missing_skipped_or_duplicate_dispatch_is_rejected(self):
        for body in (None, '', '# /scripts/local-bottom/zmala-host "$@"\n',
                     '/scripts/local-bottom/other "$@"\n',
                     '/scripts/local-bottom/zmala-host "$@"\n'*2,
                     'false && /scripts/local-bottom/zmala-host "$@"\n'):
            with self.subTest(body=body), tempfile.TemporaryDirectory() as temporary, controlled_ownership():
                root, extracted, main = copied_tree(Path(temporary))
                order = main/'scripts/local-bottom/ORDER'
                if body is None:
                    order.unlink()
                else:
                    order.write_text(body)
                with self.assertRaises((OSError, ValueError)):
                    worker.inspect_initramfs(root, extracted, 'server')
