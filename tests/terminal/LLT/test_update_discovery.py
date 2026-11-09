# @test T-LLT-106
# @requirements LLR-TERM-MAINT-060
# @environment portable
# @plan Validate RAUC 1.13 metadata for complete hook-free A/B pairs and test bounded signature inspection and persisted local-date scheduling using controlled probes.
# Verify a dated OTA release can upgrade an older numeric release with the same app build.
# @pass Only newer complete matching pairs are recorded and the daily check does not invoke install, boot-state change or reboot.
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from zmala_system import boot_capacity, update_discovery


def fixture():
    return {'update': {'version': '0.4.1', 'compatible': 'zmala-pi4-terminal-v1-b'},
            'bundle': {'format': 'verity'}, 'manifest-hash': 'a'*64,
            'images': [{'slot-class': kind, 'filename': name, 'size': boot_capacity.SIZES[index],
                        'checksum': 'b'*64} for kind, name, index in (
                            ('boot', 'boot.vfat', 1), ('rootfs', 'root.ext4', 3))],
            'meta': {'zmala': {'terminal-version': '0.4.4'}}}


class DiscoveryTests(unittest.TestCase):
    def test_dated_release_can_update_the_os_with_the_same_app(self):
        data = fixture()
        data['update']['version'] = '20261109.0.1'
        body = json.dumps(data)
        for installed in ('0.4.9', '20261108.0.9'):
            candidate = update_discovery.release(body, 'B', installed)
            self.assertEqual(candidate['system_version'], '20261109.0.1')
            self.assertEqual(candidate['terminal_version'], '0.4.4')
        self.assertIsNone(update_discovery.release(body, 'B', '20261109.0.2'))

    def test_accepts_only_complete_newer_slot_pair(self):
        data = fixture()
        result = update_discovery.release(json.dumps(data), 'B', '0.4.0')
        self.assertEqual(result, {'system_version': '0.4.1', 'terminal_version': '0.4.4',
                                  'release': 'a'*64, 'target': 'B', 'images': {'boot': 'b'*64, 'rootfs': 'b'*64}})
        self.assertIsNone(update_discovery.release(json.dumps(data), 'B', '0.4.1'))
        with self.assertRaises(ValueError):
            update_discovery.release(json.dumps(data), 'A', '0.4.0')
        for altered in (data | {'images': data['images'][:1]},
                        data | {'hooks': {'filename': 'custom.sh'}},
                        data | {'manifest-hash': 'invalid'}, data | {'bundle': {'format': 'plain'}}):
            with self.assertRaises(ValueError):
                update_discovery.release(json.dumps(altered), 'B', '0.4.0')

    def test_probe_requires_local_keyring_and_fixed_feed(self):
        probe = Mock(return_value=json.dumps(fixture()).encode())
        with patch.object(update_discovery.host_storage, 'read_record') as keyring:
            update_discovery.inspect_release('B', '0.4.0', probe, exists=lambda url: True)
        keyring.assert_called_once_with(Path('/'), update_discovery.KEYRING, 0o644, 65536)
        command = probe.call_args.args[0]
        self.assertIn('info', command)
        self.assertIn('--keyring=/'+update_discovery.KEYRING, command)
        self.assertEqual(command[-1], update_discovery.FEED+'/ZmalaTerminal-System-B.raucb')
        self.assertLess(probe.call_args.kwargs['timeout'], 40)

    def test_missing_release_is_current_without_running_rauc(self):
        probe = Mock()
        with patch.object(update_discovery.host_storage, 'read_record'):
            self.assertIsNone(update_discovery.inspect_release('B', '0.4.0', probe, exists=lambda url: False))
        probe.assert_not_called()

    def test_once_per_local_day_with_catch_up_and_backwards_clock(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'status.json'
            probe = Mock(return_value={'system_version': '0.4.1'})
            with patch.object(update_discovery.host_storage, 'read_record', side_effect=lambda *args: path.read_bytes()), \
                    patch.object(update_discovery, 'save', side_effect=lambda target, value: target.write_text(json.dumps(value))):
                for day in ('2026-11-07', '2026-11-07', '2026-11-10', '2026-11-08'):
                    update_discovery.check_day(path, day, probe)
                self.assertEqual(probe.call_count, 2)
                self.assertEqual(json.loads(path.read_text())['state'], 'verified')
                probe.side_effect = TimeoutError()
                update_discovery.check_day(path, '2026-11-11', probe)
                self.assertEqual(json.loads(path.read_text())['state'], 'error')
