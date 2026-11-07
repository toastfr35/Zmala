# @test T-LLT-107
# @requirements LLR-TERM-MAINT-062, LLR-TERM-MAINT-064
# @environment portable
# @plan Simulate idle admission, installation failure, signed offer matching and healthy or failed trial boots with an in-memory boot environment and controlled clock.
# @pass Busy and failed writes never select a trial. Only the exact staged and consumed trial with stable application health can be confirmed.
from contextlib import contextmanager
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from zmala_system import boot_state, update_coordinator, update_ipc


OFFER = {'system_version': '0.4.2', 'terminal_version': '0.4.4', 'target': 'B',
         'release': 'a'*64, 'images': {'boot': 'b'*64, 'rootfs': 'c'*64}}


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.state = boot_state.State('terminal', 'A')
        self.slot = 'A'
        self.saved = None
        self.now = 0
        self.events = []
        self.ui = Mock(sleeping=True, language='en', runtime=Path('/update-run'))
        self.install = Mock(side_effect=lambda *args: self.events.append('install'))
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
        self.assertEqual(self.state.primary, 'B')
        self.assertEqual(self.state.confirmed, 'A')

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
