"""Image packaging regression: NetworkManager alone cannot join Wi-Fi."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from zmala_images import application_worker, project


class ImageWifiBackendTests(unittest.TestCase):
    def root(self, root):
        files = {
            'usr/sbin/wpa_supplicant': b'fixture executable',
            'usr/share/dbus-1/system-services/fi.w1.wpa_supplicant1.service':
                b'[D-BUS Service]\nName=fi.w1.wpa_supplicant1\nSystemdService=wpa_supplicant.service\n',
            'usr/share/dbus-1/system.d/wpa_supplicant.conf': b'fixture bus policy',
            'usr/lib/systemd/system/wpa_supplicant.service': b'fixture unit',
        }
        for name, body in files.items():
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(body)
        return files

    def test_wifi_roles_explicitly_request_the_backend_without_recommends(self):
        for role in ('terminal','combined'):
            self.assertIn('wpasupplicant',project.packages(role))

    def test_missing_backend_or_activation_files_fail_before_target_commands(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(application_worker,'command') as run:
            root=Path(folder)
            for name,body in self.root(root).items():
                path=root/name;path.unlink()
                with self.subTest(missing=name), self.assertRaisesRegex(ValueError,'supplicant'):
                    application_worker.wifi_smoke(root)
                run.assert_not_called();path.write_bytes(body)
            path=root/'usr/share/dbus-1/system-services/fi.w1.wpa_supplicant1.service'
            path.write_text('Name=other\nSystemdService=other.service\n')
            with self.assertRaisesRegex(ValueError,'activation'): application_worker.wifi_smoke(root)
            run.assert_not_called()

    def test_target_loader_and_unit_failures_cannot_be_accepted(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(application_worker,'command') as run:
            root=Path(folder);self.root(root)
            application_worker.wifi_smoke(root)
            self.assertEqual(run.call_args_list[0].args[0],['chroot',root,'/usr/sbin/wpa_supplicant','-v'])
            self.assertEqual(run.call_args_list[1].args[0][-2:],['verify','wpa_supplicant.service'])
            for sequence in ([subprocess.CalledProcessError(127,'missing-library')],
                             [None,subprocess.CalledProcessError(1,'bad-unit')]):
                run.reset_mock();run.side_effect=sequence
                with self.assertRaises(subprocess.CalledProcessError): application_worker.wifi_smoke(root)


if __name__=='__main__': unittest.main()
