# @test T-HLT-056
# @requirements HLR-TERM-MAINT-061, HLR-TERM-MAINT-063
# @environment portable
# @plan Inspect the packaged Terminal-only service graph and exercise RAUC's native signature verification on disposable verity bundles when RAUC is available. This test does not execute the maintenance handshake, partition installation or the sandboxed candidate. Physical slot writes and watchdog resets require a Pi.
# @pass Packaged configuration gates normal and trial services and declares read-only persistent state for the trial; the native signature example rejects the wrong certificate when its tools are available. Configuration inspection does not prove that a running candidate preserves persistent data.
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from zmala_images import image_state
from zmala_system import update_discovery, update_install


class SystemUpdateTests(unittest.TestCase):
    def test_packaged_trial_is_separate_from_normal_operation(self):
        payload = image_state.payloads('terminal')
        unit = 'usr/lib/systemd/system/'
        normal = payload['etc/systemd/system/zmalacall-terminal.service.d/40-update-boot.conf']
        trial = payload[unit+'zmalacall-terminal-trial.service']
        probe = payload[unit+'zmalacall-terminal-trial-probe.service']
        self.assertIn(b'ConditionPathExists=!/run/zmalacall-updater/trial.json', normal)
        self.assertIn(b'ConditionPathExists=/run/zmalacall-updater/trial.json', trial)
        self.assertIn(b'After=zmala-system-update-boot.service', normal)
        self.assertIn(b'ReadOnlyPaths=/data /var/lib/zmalacall', trial)
        self.assertIn(b'zmalacall-terminal-trial-probe.service', trial)
        self.assertIn(b'PrivateDevices=yes', probe)
        self.assertIn(b'InaccessiblePaths=/data', probe)
        self.assertIn(b'TemporaryFileSystem=/var/lib/zmalacall:', probe)
        self.assertNotIn(unit+'rauc.service', image_state.payloads('server'))
        self.assertNotIn(unit+'zmala-system-updater.service', image_state.payloads('combined'))
        media = {(slot, kind): f'/dev/mmcblk0p{number}'
                 for slot, numbers in (('A', (2, 4)), ('B', (3, 5)))
                 for kind, number in zip(('boot', 'rootfs'), numbers)}
        config = update_install.configuration('B', media, '/data/host/system-updates/rauc')
        self.assertIn('activate-installed=false', config)
        for number in (1, 6):
            self.assertNotIn(f'device=/dev/mmcblk0p{number}', config)

    @unittest.skipUnless(all(shutil.which(name) for name in ('rauc', 'openssl', 'mksquashfs')),
                         'Native RAUC signing tools are required')
    def test_native_verity_signature_rejects_untrusted_key(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root/'source'
            source.mkdir()
            (source/'manifest.raucm').write_text(
                '[update]\ncompatible=zmala-verify\nversion=0.0.1\n\n[bundle]\nformat=verity\n'
                '\n[image.test]\nfilename=test.img\n', encoding='ascii')
            # The SquashFS payload must exceed one block for dm-verity.
            (source/'test.img').write_bytes(os.urandom(65536))
            for identity in ('trusted', 'foreign'):
                subprocess.run(['openssl', 'req', '-new', '-newkey', 'rsa:2048', '-nodes', '-x509',
                                '-subj', f'/CN={identity}', '-keyout', root/(identity+'.key'),
                                '-out', root/(identity+'.pem')], check=True, capture_output=True, timeout=20)
            bundle = root/'test.raucb'
            result = subprocess.run(['rauc', f'--cert={root}/trusted.pem', f'--key={root}/trusted.key',
                                     'bundle', source, bundle], capture_output=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            for identity, success in (('trusted', True), ('foreign', False)):
                result = subprocess.run(['rauc', f'--keyring={root}/{identity}.pem', 'info', bundle],
                                        capture_output=True, timeout=15)
                self.assertEqual(result.returncode == 0, success, result.stderr.decode())
        self.assertIn(update_discovery.KEYRING, image_state.payloads('terminal'))
