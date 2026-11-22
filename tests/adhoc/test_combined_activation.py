import tempfile
import unittest
from pathlib import Path

from zmala_images.application_provision import install_combined_activation


class CombinedActivationTest(unittest.TestCase):
    def test_server_start_is_conditional_and_only_fixed_command_is_delegated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            install_combined_activation(root)
            policy = root / 'etc/systemd/system/zmalacall-server.service.d/activation.conf'
            self.assertIn('ConditionPathExists=/etc/zmalacall/operator/terminal/server-active', policy.read_text())
            sudo = root / 'etc/sudoers.d/zmala-activate-server'
            self.assertIn('/usr/local/libexec/zmala-activate-server ""', sudo.read_text())
            self.assertFalse((root / 'etc/zmalacall/operator/terminal/server-active').exists())
