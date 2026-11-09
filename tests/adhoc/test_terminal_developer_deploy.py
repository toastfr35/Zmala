"""Test the operator package handoff and recovery without restarting a Terminal."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from zmala_images import terminal_test, terminal_test_remote as remote
from zmala_system import update_ipc


IDENTITY = {'version': '0.4.4', 'commit': 'a'*40, 'sequence': 117}
NATIVE = 'zmala_terminal/linux/media/video/codec.c'


def archive(path, extra=None):
    files = {'ZMALA-COMPONENT.json': json.dumps(IDENTITY | {
                 'schema': 1, 'component': 'terminal', 'architecture': 'arm64'}).encode(),
             'build_tools/linux/release-info.json': json.dumps(IDENTITY).encode(),
             'build_tools/linux/kiosk-session.py': b'',
             'build_tools/linux/launcher.py': b'',
             NATIVE: b'native', 'docs/terminal.md': b'documentation'}
    files.update(dict.fromkeys(remote.BUILDERS, b'build'))
    files.update(extra or {})
    with tarfile.open(path, 'w:gz') as output:
        for name, content in files.items():
            entry = tarfile.TarInfo(name)
            entry.size = len(content)
            output.addfile(entry, io.BytesIO(content))


class TerminalDeveloperDeployTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def test_transfer_uses_the_operator_ssh_command_and_pins_exact_bytes(self):
        package = self.root/'test.tar.gz'
        archive(package)
        payload = package.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        arguments = ['terminal-test', '--ssh-arg=-T', '--ssh-arg=terminal-dev',
                     'deploy', str(package), '--sha256', digest]
        with patch.object(sys, 'argv', arguments), patch.object(subprocess, 'run', return_value=Mock(returncode=0)) as run:
            self.assertEqual(terminal_test.main(), 0)
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ['ssh', '-T', 'terminal-dev'])
        self.assertIn(digest, command[-1])
        self.assertTrue(run.call_args.kwargs['input'].endswith(payload))

    def test_extracts_arm_package_with_matching_native_inputs(self):
        package, candidate, stock = (self.root/name for name in ('package.tar.gz', 'candidate', 'stock'))
        archive(package)
        with patch.object(remote, 'BASE', self.root):
            self.assertEqual(remote.extract(package, stock), IDENTITY)
            self.assertEqual(remote.extract(package, candidate), IDENTITY)
        self.assertFalse((candidate/'docs').exists())
        self.assertEqual(remote.native_inputs(candidate), remote.native_inputs(stock))
        (candidate/NATIVE).write_bytes(b'incompatible')
        with self.assertRaisesRegex(ValueError, 'Native build inputs changed'):
            remote.reuse_native(candidate, stock)

    def test_refuses_traversal_before_extracting(self):
        package, destination = self.root/'test.tar.gz', self.root/'candidate'
        archive(package, {'zmala_terminal/common/../../../outside': b'unsafe'})
        with self.assertRaisesRegex(ValueError, 'Unsafe package path'):
            remote.extract(package, destination)
        self.assertFalse(destination.exists())

    def test_turn_preloader_binds_stock_files_at_the_test_paths(self):
        stock = self.root/'stock'
        candidate = self.root/'candidate'
        for name in remote.RUNTIME[:3]:
            path = stock/'zmala_terminal/linux'/name
            path.parent.mkdir(parents=True, exist_ok=True)
            if name == 'turn-runtime':
                path.mkdir()
                (path/'turn-fix.so').write_bytes(b'library')
                (path/'sdk-version').write_text('sdk')
            else:
                path.write_bytes(b'installed library')
        with patch.object(remote, 'BASE', self.root), patch.object(remote, 'native_inputs', return_value=set()):
            remote.reuse_native(candidate, stock)
        with (patch.object(remote, 'STOCK_ROOT', stock), patch.object(remote, 'RELEASE', candidate),
              patch.object(remote.subprocess, 'run') as run):
            remote.launch()
        bindings = next(arg for arg in run.call_args.args[0] if arg.startswith('--property=BindReadOnlyPaths='))
        self.assertIn('--setenv=TMPDIR=/run/zmalacall-test', run.call_args.args[0])
        for filename in remote.TURN_FILES:
            self.assertEqual((candidate/filename).resolve(), (candidate/filename).absolute())
            self.assertEqual((candidate/filename).read_bytes(), b'')
            self.assertIn(f'{(stock/filename).resolve()}:{candidate/filename}', bindings)

    @unittest.skipIf(sys.platform == 'win32', 'Linux deployment APIs')
    def test_no_service_swap_until_app_acknowledges_maintenance(self):
        ui = Mock(claim=Mock(return_value=False), runtime=self.root)
        with (
            patch.object(remote, 'SESSION', self.root),
            patch.object(remote, 'admit'),
            patch.object(remote, 'systemctl') as control,
            patch.object(remote, 'state', side_effect=('active', 'active', 'running', 'frozen', 'inactive')),
            patch.object(update_ipc, 'LocalUI', return_value=ui),
            patch.object(update_ipc, 'record', return_value={'phase': 'idle'}),
        ):
            with self.assertRaisesRegex(ValueError, 'Terminal is busy'):
                remote.activate()
            remote.cleanup()
        ui.claim.assert_called_once_with(immediate=True)
        ui.phase.assert_called_once_with('idle')
        self.assertEqual([call.args for call in control.call_args_list],
                         [('freeze', remote.UPDATER), ('thaw', remote.UPDATER)])

    def test_failed_launch_restores_stock_and_thaws_coordinator(self):
        for name in ('lease', 'stopped', 'thaw'):
            (self.root/name).touch()
        with (
            patch.object(remote, 'SESSION', self.root),
            patch.object(remote, 'systemctl') as control,
            patch.object(remote, 'busy', return_value=False),
            patch.object(update_ipc, 'LocalUI') as ui,
        ):
            remote.cleanup()
        ui.return_value.phase.assert_called_once_with('idle')
        self.assertEqual([call.args for call in control.call_args_list],
                         [('start', remote.STOCK), ('thaw', remote.UPDATER)])

    def test_unready_test_service_is_stopped_before_stock_restores(self):
        (self.root/'stopped').touch()
        with (patch.object(remote, 'SESSION', self.root),
              patch.object(remote, 'systemctl') as control,
              patch.object(remote, 'busy', side_effect=(True, False))):
            remote.cleanup()
        self.assertEqual([call.args for call in control.call_args_list],
                         [('stop', remote.TEST), ('start', remote.STOCK)])

    @unittest.skipIf(sys.platform == 'win32', 'Linux profile ownership and file types')
    def test_snapshot_has_independent_data_and_rejects_links(self):
        source = self.root/'source'
        source.mkdir()
        (source/'config').write_text('stock profile')
        pulse = source/'.config/pulse'
        pulse.mkdir(parents=True)
        runtime = pulse/('a'*32+'-runtime')
        runtime.symlink_to('/tmp/pulse-testRuntime')
        target = self.root/'target'
        user = SimpleNamespace(pw_uid=1000, pw_gid=1000)
        with patch.object(remote, 'BASE', self.root), patch.object(remote.os, 'chown'):
            remote.snapshot(source, target, user)
            (target/'config').write_text('test profile')
            self.assertEqual((source/'config').read_text(), 'stock profile')
            self.assertTrue(runtime.is_symlink())
            self.assertFalse((target/runtime.relative_to(source)).is_symlink())
            untrusted_runtime = pulse/('b'*32+'-runtime')
            untrusted_runtime.symlink_to('/etc/passwd')
            with self.assertRaisesRegex(ValueError, 'link or special file'):
                remote.snapshot(source, self.root/'untrusted-runtime', user)
            untrusted_runtime.unlink()
            (source/'unsafe').symlink_to('/etc/passwd')
            with self.assertRaisesRegex(ValueError, 'link or special file'):
                remote.snapshot(source, self.root/'unsafe', user)
