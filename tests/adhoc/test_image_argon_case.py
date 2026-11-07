"""Required appliance case configuration; physical fan behavior is separate."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from tests.support.image_application_fixtures import provisioning_records
from zmala_images import application_provision as provision, image_case


class ArgonImageTests(unittest.TestCase):
    @staticmethod
    def ledgers():
        return {'passwd': 'root:x:0:0:root:/root:/bin/sh\n', 'group': 'root:x:0:\n',
                'shadow': 'root:!:1:0:99999:7:::\n', 'gshadow': 'root:!::\n'}

    def test_terminal_roles_always_receive_argon_access_and_server_does_not(self):
        self.assertFalse(provision.uses_argon('server'))
        self.assertNotIn('i2c:', provision.accounts(self.ledgers(), 'server')['group'])
        with self.assertRaises(ValueError):
            provision.uses_argon('unknown')
        for role in ('terminal', 'combined'):
            self.assertTrue(provision.uses_argon(role))
            groups = provision.accounts(self.ledgers(), role)['group']
            row = next(row for row in groups.splitlines() if row.startswith('i2c:'))
            self.assertEqual(row.split(':')[3], 'zmalaterminal')

    @unittest.skipIf(os.name == 'nt', 'Offline Unix roots require Linux symlinks')
    def test_case_provisioning_and_assembly_agree_for_both_terminal_roles(self):
        records = provisioning_records()
        for role in ('terminal', 'combined', 'server'):
            selected = role != 'server'
            with self.subTest(role=role, selected=selected), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                (root/'etc').mkdir()
                for name, body in self.ledgers().items():
                    (root/'etc'/name).write_text(body)
                units = root/'usr/lib/systemd/system'
                units.mkdir(parents=True)
                (units/'NetworkManager.service').write_text('[Service]\nExecStart=/bin/true\n')
                result = provision.provision(root, records, role)
                self.assertIs(result['argon_one'], selected)
                self.assertIs(image_case.selected(root, role), selected)
                with self.assertRaises(ValueError):
                    image_case.selected(root, 'server' if role != 'server' else 'terminal')
                module = root/'etc/modules-load.d/zmala-i2c.conf'
                self.assertIs(module.exists(), selected)
                rules = root/'etc/udev/rules.d/99-zmalacall-i2c.rules'
                self.assertIs(rules.exists(), selected)
                if selected:
                    self.assertIn('ExecStopPost=-/usr/bin/python3 /usr/local/lib/zmalacall-terminal-host/argon_fan.py',
                                  (units/'zmalacall-terminal.service').read_text())
                    for path in (module, rules, root/'etc/group'):
                        before = path.read_text()
                        path.write_text('')
                        with self.assertRaises(ValueError):
                            image_case.selected(root, role)
                        path.write_text(before)
                    config = root/'etc/zmalacall/terminal.conf'
                    before = config.read_text()
                    config.write_text('ZMALA_ARGON_ONE_FAN=0\n')
                    with self.assertRaises(ValueError):
                        image_case.selected(root, role)
                    config.write_text(before)
                else:
                    self.assertFalse((root/'etc/zmalacall/terminal.conf').exists())
                marker = root/'usr/lib/zmala-application-build.json'
                original = json.loads(marker.read_text())
                for value in (not selected, int(selected), None):
                    marker.write_text(json.dumps({**original, 'argon_one': value}))
                    with self.assertRaises(ValueError):
                        image_case.selected(root, role)

    def test_server_boot_keeps_i2c_unchanged_and_terminal_boot_checks_alias(self):
        run = Mock()
        image_case.configure_tree(Path('/root'), Path('/staging'), False, run)
        run.assert_not_called()
        self.assertEqual(image_case.boot_parameters(False), '')
        self.assertEqual(image_case.boot_parameters(True), 'dtparam=i2c_arm=on\n')
        with tempfile.TemporaryDirectory() as folder:
            stage = Path(folder)
            (stage/'board.dtb').write_bytes(b'original')
            (stage/'argon.dtb').write_bytes(b'i2c enabled')
            run.side_effect = [None, SimpleNamespace(stdout='/soc/i2c@7e804000\n'),
                               SimpleNamespace(stdout='okay\n')]
            image_case.configure_tree(Path('/root'), stage, True, run)
            self.assertEqual((stage/'board.dtb').read_bytes(), b'i2c enabled')
            self.assertEqual(run.call_args_list[0].args[0][-2:], ['-', 'i2c_arm=on'])
            self.assertEqual(run.call_args_list[1].args[0][-2:], ['/aliases', 'i2c1'])

    def test_disabled_or_failed_parameter_application_never_replaces_slot_tree(self):
        for failure in ('disabled', 'command'):
            with tempfile.TemporaryDirectory() as folder:
                stage = Path(folder)
                (stage/'board.dtb').write_bytes(b'original')
                (stage/'argon.dtb').write_bytes(b'bad')
                run = Mock(side_effect=(subprocess.CalledProcessError(1, 'dtmerge') if failure == 'command'
                    else [None, SimpleNamespace(stdout='/soc/i2c@7e804000\n'), SimpleNamespace(stdout='disabled\n')]))
                with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                    image_case.configure_tree(Path('/root'), stage, True, run)
                self.assertEqual((stage/'board.dtb').read_bytes(), b'original')


if __name__ == '__main__':
    unittest.main()
