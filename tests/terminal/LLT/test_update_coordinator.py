# @test T-LLT-107
# @requirements LLR-TERM-MAINT-062, LLR-TERM-MAINT-064
# @environment portable
# @plan Simulate idle admission, installer success/failure, signed offer matching and healthy or failed trial boots with an in-memory boot environment and controlled clock. Admission and installation are mocked; health records are supplied by the fixture. Exercise transfer progress with controlled response bytes.
# @pass Refused admission and injected installer failures never select a trial. Only the exact staged and consumed trial with stable simulated health can be confirmed. These assertions do not execute process authentication, installed-partition readback or candidate native/UI health.
# Additional POSIX fixtures execute diagnostic heartbeat process/nonce authentication;
# unfenced diagnostic records never admit installation. Manual timeout publishes a
# matching error and suppresses the same automatic candidate without installing.
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import os
from unittest.mock import Mock, patch

from zmala_system import boot_state, update_coordinator, update_install, update_ipc


OFFER = {'system_version': '0.4.2', 'terminal_version': '0.4.4', 'target': 'B',
         'release': 'a'*64, 'images': {'boot': 'b'*64, 'rootfs': 'c'*64}}


class CoordinatorTests(unittest.TestCase):
    def test_diagnostic_heartbeat_cannot_grant_unfenced_admission(self):
        now = [0]
        ui = object.__new__(update_ipc.LocalUI)
        ui.clock = lambda: now[0]
        ui.phase = Mock()
        ui.heartbeat = Mock(return_value={'eligible': True, 'maintenance': False, 'blockers': ['usb']})
        self.assertFalse(ui.claim(True, sleep=lambda delay: now.__setitem__(0, now[0]+delay)))
        self.assertEqual(now[0], 12)
        self.assertEqual(ui.blockers, ['usb'])
        ui.phase.assert_called_with('idle')

    @unittest.skipUnless(os.name == 'posix', 'POSIX acknowledgement ownership and symlinks')
    def test_unfenced_diagnostics_still_authenticate_process_and_nonce(self):
        import json
        with TemporaryDirectory() as directory, patch.object(update_ipc, 'USER', os.getuid()):
            root = Path(directory)
            process = root/'proc'/'11'
            process.mkdir(parents=True)
            app = root/'app'
            app.mkdir()
            (process/'cwd').symlink_to(app, target_is_directory=True)
            (process/'cgroup').write_text('0::/system.slice/zmalacall-terminal.service\n')
            ui = object.__new__(update_ipc.LocalUI)
            ui.app, ui.app_root, ui.proc = app, app, root/'proc'
            ui.nonce, ui.clock = 'a'*32, lambda: 100
            data = {'pid':11, 'nonce':ui.nonce, 'generation':'b'*32, 'heartbeat':100,
                    'ready':True, 'maintenance':False, 'eligible':False, 'blockers':['tv']}
            status = app/'update.json'
            status.write_text(json.dumps(data))
            status.chmod(0o600)
            self.assertIsNone(ui.heartbeat())
            self.assertEqual(ui.heartbeat(require_maintenance=False)['blockers'], ['tv'])
            data['nonce'] = 'c'*32
            status.write_text(json.dumps(data))
            self.assertIsNone(ui.heartbeat(require_maintenance=False))

    def test_manual_admission_timeout_reports_blocker_without_installing(self):
        self.owner.manual_identity = 'a'*32
        self.owner.requested = OFFER
        self.ui.claim.return_value = False
        self.ui.blockers = ['usb']
        self.assertFalse(self.owner.activate(OFFER, True))
        self.ui.offer.assert_called_once_with('error', 'a'*32, blockers=['usb'])
        self.install.assert_not_called()
        self.restart.assert_not_called()
        self.assertEqual(self.owner.blocked_release, OFFER['release'])
        self.assertIsNone(self.owner.requested)

    def setUp(self):
        self.state = boot_state.State('terminal', 'A')
        self.slot = 'A'
        self.saved = None
        self.now = 0
        self.events = []
        self.ui = Mock(sleeping=True, language='en', runtime=Path('/update-run'))
        self.install = Mock(side_effect=lambda *args, **kwargs: self.events.append('install'))
        self.restart = Mock(side_effect=lambda: self.events.append('restart'))
        self.owner = update_coordinator.Coordinator(Path('/update-data'), self.ui, '0.4.1',
                                                   control=self.control, install=self.install,
                                                   restart=self.restart, clock=lambda: self.now,
                                                   sleep=self.advance)
        self.owner.read, self.owner.write = lambda: self.saved, self.write
        for target in ('systemctl', 'update_install.stop_rauc'):
            parent, _, name = target.rpartition('.')
            module = getattr(update_coordinator, parent) if parent else update_coordinator
            patcher = patch.object(module, name)
            patcher.start()
            self.addCleanup(patcher.stop)

    def advance(self, delay):
        self.now += delay

    @contextmanager
    def control(self):
        yield self, self.slot

    def read(self):
        return self.state

    def write(self, value, phase):
        self.saved = value | {'state': phase}
        self.events.append(phase)

    def commit(self, before, after):
        self.assertEqual(self.state, before)
        self.state = after
        self.events.append('commit')

    def test_no_install_until_ui_fences_calls(self):
        self.ui.claim.return_value = False
        self.assertFalse(self.owner.activate(OFFER, immediate=True))
        self.assertEqual(self.events, [])
        self.ui.claim.assert_called_once_with(True)

    def test_writes_journal_and_verifies_install_before_staging(self):
        self.assertTrue(self.owner.activate(OFFER, immediate=False))
        self.assertEqual(self.events, ['installing', 'install', 'staged', 'commit', 'restart'])
        self.ui.download_progress.assert_called_once_with(0)
        self.install.assert_called_once_with(OFFER, '0.4.1', Path('/update-data'), progress=self.ui.download_progress)
        self.assertEqual(self.state.primary, 'B')
        self.assertEqual(self.state.confirmed, 'A')

    def test_download_progress_follows_bytes_and_only_completes_for_a_full_transfer(self):
        body = b'x' * (2 * 1024 ** 2)
        for data, expected in ((body, [50, 99, 100]), (body[:1024 ** 2], [50])):
            with self.subTest(expected=expected), TemporaryDirectory() as folder, \
                    patch.object(update_install.update_discovery, 'check_url'), \
                    patch.object(update_install.shutil, 'disk_usage', return_value=Mock(free=2**32)):
                response = BytesIO(data)
                response.geturl = lambda: 'test'
                response.headers = {'Content-Length': str(len(body))}
                response.status = 200
                path = Path(folder) / 'bundle'
                progress = []
                opener = Mock()
                opener.open.return_value = response
                if len(data) == len(body):
                    update_install.download('B', path, opener=opener, progress=progress.append)
                    self.assertEqual(path.read_bytes(), body)
                else:
                    with self.assertRaisesRegex(ValueError, 'Truncated'):
                        update_install.download('B', path, opener=opener, progress=progress.append)
                self.assertEqual(progress, expected)

    def test_install_failure_is_quarantined_without_reboot(self):
        self.install.side_effect = ValueError('Readback mismatch')
        self.assertFalse(self.owner.activate(OFFER, immediate=False))
        self.assertEqual(self.events, ['installing', 'rejected'])
        self.assertFalse(self.owner.admissible(OFFER))
        self.assertEqual(self.state.trial, '-')

    def test_only_the_current_offer_can_be_accepted(self):
        self.owner.inspect = Mock(return_value=OFFER)
        self.owner.manual({'request': 'check', 'action': 'check'})
        self.ui.offer.assert_called_with('available', 'check', version='0.4.2', release=OFFER['release'])
        apply = {'request': 'apply', 'action': 'apply'}
        self.owner.manual(apply | {'release': 'f'*64})
        self.ui.offer.assert_called_with('error', 'apply')
        self.owner.manual(apply | {'release': OFFER['release']})
        self.ui.offer.assert_called_with('queued', 'apply')
        self.assertEqual(self.owner.requested, OFFER)

    def trial(self):
        self.owner.activate(OFFER, immediate=False)
        self.state = self.state.changed(left=0)
        self.slot = 'B'
        self.owner.installed = '0.4.2'
        self.events.clear()

    def test_only_matching_consumed_trial_boots(self):
        self.trial()
        with self.assertRaises(ValueError):
            update_coordinator.boot_mode(self.state, self.slot, self.saved, '0.4.3')
        self.assertEqual(update_coordinator.boot_mode(self.state, self.slot, self.saved, '0.4.2'), 'trial')
        self.assertEqual(update_coordinator.boot_mode(self.state, 'A', self.saved, '0.4.1'), 'reject')

    def test_stable_trial_qualifies_before_confirmed_restart(self):
        self.trial()
        self.ui.heartbeat.return_value = {'pid': 5, 'generation': 'b'*32}
        with patch.object(update_ipc, 'record', return_value={'nonce': 'a'*32}):
            self.assertTrue(self.owner.confirm_trial())
        self.assertGreaterEqual(self.now, 8)
        self.assertEqual(self.events, ['commit', 'confirmed', 'restart'])
        self.assertEqual(self.state.confirmed, 'B')

    def test_restart_during_trial_falls_back(self):
        self.trial()
        self.ui.heartbeat.side_effect = [{'pid': 5, 'generation': 'b'*32},
                                         {'pid': 6, 'generation': 'c'*32}]
        with patch.object(update_ipc, 'record', return_value={'nonce': 'a'*32}):
            self.assertFalse(self.owner.confirm_trial())
        self.assertEqual(self.events, ['restart'])
        self.assertEqual(self.state.primary, 'A')
        self.assertEqual(self.state.confirmed, 'A')
