# @test T-HLT-055
# @requirements HLR-TERM-MAINT-059
# @environment portable
# @plan Run the packaged timer expression through native systemd's calendar parser across the local daylight-saving boundary. Check the boot catch-up trigger and signing keyring condition.
# @pass The timer resolves to local midnight on both sides of the DST change, and unsigned hosts cannot start the discovery service via this timer.
from configparser import ConfigParser
import os
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[3] / 'zmala_system'


@unittest.skipUnless(shutil.which('systemd-analyze'), 'Native systemd is required')
class UpdateScheduleTests(unittest.TestCase):
    def test_packaged_timer_checks_at_midnight_across_dst(self):
        parser = ConfigParser(interpolation=None)
        parser.read(ROOT/'zmala-system-update-check.timer', encoding='utf-8')
        timer = parser['Timer']
        output = subprocess.run(['systemd-analyze', 'calendar', '--base-time=2026-10-24 23:59:59',
                                 '--iterations=2', timer['OnCalendar']], check=True, text=True,
                                capture_output=True, timeout=10,
                                env=dict(os.environ, TZ='Europe/London', LC_ALL='C')).stdout
        self.assertIn('2026-10-25 00:00:00 BST', output)
        self.assertIn('2026-10-26 00:00:00 GMT', output)
        self.assertEqual(timer['OnBootSec'], '5min')
        service = (ROOT/timer['Unit']).read_text(encoding='utf-8')
        self.assertIn('ConditionPathExists=/usr/lib/zmala/system-update-keyring.pem', service)
