"""Actual GPT/loop/block-probe integration; not physical boot qualification."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from tests.support.boot_storage_fixture import PartitionedFixture, command
from zmala_system import boot_gate, boot_storage, device_identity, host_layout


def worker(parent, role):
    assert parent.parent == Path(tempfile.gettempdir()).resolve()
    fixture = PartitionedFixture(parent, role)
    try:
        fixture.setup()
        saved = None
        for slot in ('A', 'B'):
            fixture.select(slot)
            initial = set(fixture.system.facts())
            prepared = boot_storage.prepare(fixture.root, role, fixture.area, fixture.system)
            try:
                assert prepared.ready and boot_gate.verify(fixture.root, fixture.area, fixture.system)
                current = device_identity.saved_identity(fixture.root/'data')
                if saved:
                    assert current == saved
                saved = current
                app = fixture.root/('var/lib/zmalacall-server' if role == 'server' else 'var/lib/zmalacall')
                value = app/'boot-fixture'
                if slot == 'A':
                    with value.open('wb') as stream:
                        stream.write(b'state from first slot'); stream.flush(); os.fsync(stream.fileno())
                else:
                    assert value.read_bytes() == b'state from first slot'
                assert (fixture.root/'etc/vendor.conf').read_text() == 'factory-'+slot
                _, root_uuid = fixture.system.boot_arguments()
                assert (fixture.root/'etc/fstab').read_text().endswith('PARTUUID='+root_uuid+' / ext4 ro 0 0\n')
                assert (fixture.root/host_layout.PACKAGE_DB/'status').read_text() == 'slot-package-'+slot
                assert (fixture.root/'var/lib/dpkg').readlink().as_posix() == '/'+host_layout.PACKAGE_DB
                marker = fixture.area/boot_storage.READY
                contents = marker.read_bytes(); marker.unlink()
                try:
                    boot_gate.verify(fixture.root, fixture.area, fixture.system)
                except (OSError, ValueError):
                    pass
                else:
                    raise AssertionError('PID1 gate accepted missing current-boot readiness')
                marker.write_bytes(contents); marker.chmod(0o600)
                assert boot_gate.verify(fixture.root, fixture.area, fixture.system)
                hostname = fixture.root/'etc/hostname'
                fixture.system.run(['umount', str(hostname)])
                try:
                    boot_gate.verify(fixture.root, fixture.area, fixture.system)
                except ValueError:
                    pass
                else:
                    raise AssertionError('PID1 gate accepted a missing identity binding')
                fixture.system.run(['mount', '-o', 'bind', str(fixture.root/'data/identity/hostname'), str(hostname)])
                fixture.system.run(['mount', '-o', 'remount,bind,ro,nodev,nosuid', str(hostname)])
                assert boot_gate.verify(fixture.root, fixture.area, fixture.system)
            finally:
                prepared.close()
            assert set(fixture.system.facts()) == initial
            command(['umount', fixture.root])
        fixture.select('A')
        initial = set(fixture.system.facts())
        original = fixture.cmdline.read_text()
        fixture.cmdline.write_text(original.replace('rauc.slot=A', 'rauc.slot=B'))
        try:
            boot_storage.prepare(fixture.root, role, fixture.area, fixture.system)
        except ValueError:
            pass
        else:
            raise AssertionError('Wrong root slot was accepted')
        assert set(fixture.system.facts()) == initial
        fixture.cmdline.write_text(original)
        native_run = fixture.system.run
        # A failing command can leave a mount behind. Exercise both outcomes on
        # the actual discovered data device and on a later volatile-view mount.
        for target, after in ((fixture.root/'data', False), (fixture.root/'data', True),
                              (fixture.root/'var', True)):
            def fail(args):
                if args[0] == 'mount' and args[-1] == str(target):
                    if after:
                        native_run(args)
                    raise OSError('injected fixture mount failure')
                return native_run(args)
            fixture.system.run = fail
            try:
                try:
                    boot_storage.prepare(fixture.root, role, fixture.area, fixture.system)
                except OSError as error:
                    assert str(error) == 'injected fixture mount failure'
                else:
                    raise AssertionError('Injected preparation failure reported readiness')
            finally:
                fixture.system.run = native_run
            assert set(fixture.system.facts()) == initial
        fixture.mount_stage()
        try:
            assert device_identity.saved_identity(fixture.stage) == saved
            assert (fixture.stage/'state'/('terminal' if role == 'combined' else role)/'boot-fixture').read_bytes() == b'state from first slot'
        finally:
            command(['umount', fixture.stage])
        print(json.dumps({'role': role, 'selected_roots': 2, 'failure_cases': 4, 'passed': True}))
    finally:
        fixture.close()


class BootStorageNamespaceScenario(unittest.TestCase):
    role = None

    def test_real_gpt_sibling_data_both_roots_gate_and_owned_failure_cleanup(self):
        if sys.platform != 'linux' or os.geteuid() != 0:
            self.skipTest('Requires Linux root in an isolated fixture namespace')
        for name in ('unshare', 'losetup', 'sfdisk', 'mkfs.ext4', 'blkid', 'mount', 'umount'):
            self.assertIsNotNone(shutil.which(name), 'Missing GPT fixture tool: '+name)
        self.assertTrue(Path('/dev/loop-control').exists(), 'Loop partition support is required')
        with tempfile.TemporaryDirectory(prefix='zmala-boot-storage-') as folder:
            result = subprocess.run(['unshare', '--mount', '--net', '--pid', '--fork', '--kill-child=TERM',
                                     '--propagation', 'private', sys.executable,
                                     '-m', 'tests.support.boot_storage_namespace',
                                     '--fixture', folder, '--role', self.role],
                                    capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout+'\n'+result.stderr)
            self.assertEqual(json.loads(result.stdout.strip()),
                             {'role': self.role, 'selected_roots': 2, 'failure_cases': 4, 'passed': True})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', required=True, type=Path)
    parser.add_argument('--role', required=True, choices=('server', 'terminal', 'combined'))
    args = parser.parse_args()
    worker(args.fixture, args.role)
