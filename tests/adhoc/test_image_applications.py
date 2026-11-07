"""Offline application intake/provisioning regressions; not runtime RBT."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest

from tests.support.image_application_fixtures import provisioning_records
from zmala_images import application_inputs as inputs, application_provision as provision, application_host


class ApplicationInputTests(unittest.TestCase):
    def component_package(self, root, component, files, **metadata_changes):
        pin = {'version': '1.2.3', 'commit': ('a' if component == 'server' else 'b')*40}
        metadata = dict(pin, schema=1, component=component, architecture='arm64')
        if component == 'terminal':
            metadata['sequence'] = 101
        metadata.update(metadata_changes)
        path = root/f'Zmala{component.title()}-1.2.3-linux-arm64.tar.gz'
        with tarfile.open(path, 'w:gz') as archive:
            for name, data in (files | {'ZMALA-COMPONENT.json': json.dumps(metadata).encode()}).items():
                member = tarfile.TarInfo(name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        return dict(pin, sha256=hashlib.sha256(path.read_bytes()).hexdigest())

    def test_pinned_packages_are_selected_by_role_and_shared_payloads_must_agree(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            shared = 'build_tools/linux/low-wear-swap.conf'
            server = {'zmala_server/main.js': b'// server\n',
                      shared: b'# @llr LLR-SRV-HOST-005\n[Main]\n'}
            terminal = {'zmala_terminal/common/main.py': b'# terminal\n',
                        shared: b'# @llr LLR-TERM-MAINT-013\n[Main]\n'}
            pins = {'server': self.component_package(root, 'server', server),
                    'terminal': self.component_package(root, 'terminal', terminal)}
            lock = root/'components.lock.json'
            lock.write_text(json.dumps({'schema': 1, 'components': pins}))
            self.assertEqual(set(inputs.component_packages('server', lock, root)[0]), set(server))
            self.assertEqual(set(inputs.component_packages('terminal', lock, root)[0]), set(terminal))
            records, components = inputs.component_packages('combined', lock, root)
            self.assertEqual(set(records), set(server) | set(terminal))
            self.assertEqual(records[shared][0], server[shared])
            self.assertEqual(components['server']['commit'], 'a'*40)
            self.assertEqual(components['terminal']['sequence'], 101)
            lock.write_text(json.dumps({'schema': 1, 'components': dict(pins, terminal=dict(pins['terminal'], sha256='0'*64))}))
            with self.assertRaisesRegex(ValueError, 'digest'):
                inputs.component_packages('combined', lock, root)
            pins['terminal'] = self.component_package(root, 'terminal', terminal, architecture='amd64')
            lock.write_text(json.dumps({'schema': 1, 'components': pins}))
            with self.assertRaisesRegex(ValueError, 'metadata'):
                inputs.component_packages('combined', lock, root)
            pins['terminal'] = self.component_package(root, 'terminal', terminal | {shared: b'[Different]\n'})
            lock.write_text(json.dumps({'schema': 1, 'components': pins}))
            with self.assertRaisesRegex(ValueError, 'Conflicting component package payload'):
                inputs.component_packages('combined', lock, root)

    def test_tar_rejects_links_traversal_duplicates_and_file_parents(self):
        for names, link in ((['../escape'], False), (['/absolute'], False),
                            (['ok', 'ok'], False), (['parent', 'parent/child'], False),
                            (['linked'], True), (['C:/outside'], False),
                            (['file:stream'], False), (['parent./child'], False),
                            (['parent /child'], False)):
            with self.subTest(names=names), tempfile.TemporaryDirectory() as folder:
                path = Path(folder)/'input.tar'
                with tarfile.open(path, 'w') as archive:
                    for name in names:
                        member = tarfile.TarInfo(name)
                        if link:
                            member.type, member.linkname = tarfile.SYMTYPE, '/outside'
                            archive.addfile(member)
                        else:
                            member.size = 4
                            archive.addfile(member, io.BytesIO(b'data'))
                with self.assertRaises(ValueError):
                    inputs.read_tar(path)
                self.assertEqual(list(Path(folder).iterdir()), [path])

    def test_dependency_admission_requires_integrity_and_supported_script_free_kind(self):
        good = {'version': '1.0.0', 'resolved': 'https://registry.npmjs.org/example/-/example-1.0.0.tgz',
                'integrity': 'sha512-'+base64.b64encode(b'x'*64).decode()}
        def lock(value):
            return {'lockfileVersion': 3, 'packages': {'': {}, 'node_modules/example': value}}
        self.assertEqual(len(inputs.npm_entries(lock(good))), 1)
        for change in ({'resolved': 'https://other.invalid/example.tgz'}, {'integrity': 'sha512-AA=='},
                       {'hasInstallScript': True}, {'os': ['linux']}, {'optional': True},
                       {'resolved': 'file:/outside'}, {'link': True}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                inputs.npm_entries(lock({**good, **change}))

    def test_dependency_hash_and_redirect_failure_leave_no_accepted_artifact(self):
        uri = 'https://registry.npmjs.org/example/-/example.tgz'
        class Response(io.BytesIO):
            def geturl(self):
                return uri
        for checksum in (hashlib.sha512(b'good').digest(), hashlib.sha512(b'bad').digest()):
            with tempfile.TemporaryDirectory() as folder:
                action = lambda: inputs.acquire_dependency(('node_modules/example', uri, checksum),
                                                           Path(folder), lambda *a, **k: Response(b'good'))
                if checksum == hashlib.sha512(b'good').digest():
                    self.assertEqual(action()[1].read_bytes(), b'good')
                else:
                    with self.assertRaises(ValueError):
                        action()
                self.assertFalse((Path(folder)/'READY.json').exists())
        class Redirect(Response):
            def geturl(self):
                return 'https://other.invalid/source'
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(ValueError):
            inputs.acquire_dependency(('node_modules/example', uri, b'x'*64), Path(folder),
                                      lambda *a, **k: Redirect(b'good'))

    def test_manifest_digest_role_and_file_inventory_are_checked(self):
        body = b'public source'
        manifest = {'schema': 2, 'role': 'terminal', 'package_scripts_executed': False,
                    'components': {'terminal': {'version': '1.2.3', 'commit': 'a'*40, 'sha256': 'b'*64,
                                                'architecture': 'arm64', 'component': 'terminal'}},
                    'files': {'app.py': {'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body), 'mode': 0o644}}}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'source.tar'
            with tarfile.open(path, 'w') as archive:
                for name, data in (('app.py', body), (inputs.MARKER, json.dumps(manifest).encode())):
                    member = tarfile.TarInfo(name)
                    member.size = len(data)
                    archive.addfile(member, io.BytesIO(data))
            checksum = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(inputs.verify(path, checksum, 'terminal')[0]['app.py'][0], body)
            with self.assertRaises(ValueError):
                inputs.verify(path, checksum, 'combined')
            with self.assertRaises(ValueError):
                inputs.verify(path, '0'*64, 'terminal')


class ApplicationProvisionTests(unittest.TestCase):
    def ledgers(self):
        return {'passwd': 'root:x:0:0:root:/root:/bin/sh\n', 'group': 'root:x:0:\n',
                'shadow': 'root:!:1:0:99999:7:::\n', 'gshadow': 'root:!::\n'}

    def test_combined_accounts_are_locked_separate_and_collision_refusing(self):
        result = provision.accounts(self.ledgers(), 'combined')
        self.assertIn('zmalaterminal:x:1000:1000:', result['passwd'])
        self.assertIn('zmalaserver:x:1001:1001:', result['passwd'])
        self.assertIn('zmalaserver:!:', result['shadow'])
        self.assertIn('/usr/sbin/nologin', result['passwd'])
        self.assertNotIn('zmalaserver', '\n'.join(line for line in result['group'].splitlines()
                                                if line.startswith(('audio:', 'video:', 'render:', 'input:'))))
        for role in ('server', 'terminal'):
            self.assertIn(':x:1000:1000:', provision.accounts(self.ledgers(), role)['passwd'])
        for ledger, line in (('passwd', 'existing:x:1001:1001:existing:/tmp:/bin/sh\n'),
                             ('group', 'existing:x:1000:\n')):
            values = self.ledgers()
            values[ledger] += line
            with self.assertRaises(ValueError):
                provision.accounts(values, 'combined')

    @unittest.skipIf(os.name == 'nt', 'Offline Unix roots require Linux symlinks')
    def test_combined_release_paths_separate_server_bootstrap_and_terminal_state(self):
        records = provisioning_records()
        records['zmala_server/main.js'] = (b'// synthetic application', False)
        records['zmala_terminal/common/main.py'] = (b'# synthetic application', False)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'etc').mkdir()
            for name, body in self.ledgers().items():
                (root/'etc'/name).write_text(body)
            destination = root/'usr/lib/systemd/system'
            destination.mkdir(parents=True)
            (destination/'NetworkManager.service').write_text('[Service]\nExecStart=/bin/true\n')
            wants = root/'etc/systemd/system/multi-user.target.wants'
            wants.mkdir(parents=True)
            (wants/'NetworkManager.service').symlink_to('/usr/lib/systemd/system/NetworkManager.service')
            result = provision.provision(root, records, 'combined')
            self.assertTrue(result['developer_access_installed'])
            self.assertTrue(result['boot_theme_installed'])
            self.assertIn('zmalacall-developer-shell.service', result['units'])
            self.assertFalse((wants/'zmalacall-developer-shell.service').exists())
            self.assertFalse((wants/'zmalacall-developer-tunnel.service').exists())
            self.assertIn('ListenAddress 127.0.0.1', (root/'etc/ssh/zmala-developer-terminal.conf').read_text())
            self.assertIn('PasswordAuthentication no', (root/'etc/ssh/zmala-developer-terminal.conf').read_text())
            self.assertFalse((root/'etc/ssh/keys').exists())
            self.assertIn('zmala:*:', (root/'etc/shadow').read_text())
            self.assertEqual((root/'usr/share/plymouth/themes/zmala/boot-family.png').read_bytes(), records[application_host.SOURCES[3]][0])
            self.assertEqual((root/'etc/systemd/system/zmalacall-server.service.d/bootstrap.conf').read_text(),
                             '[Service]\nEnvironment=ZMALA_BOOTSTRAP_EXPORT_DIRECTORY=/var/lib/zmalacall-server/bootstrap\n')
            self.assertEqual(str((root/provision.TERMINAL/'zmala_terminal/data').readlink()), '/var/lib/zmalacall')
            self.assertIn('zmalaserver:x:1001:1001:', (root/'etc/passwd').read_text())
            for unit in ('ssh.service', 'systemd-networkd.service', 'zmalacall-updater.service'):
                self.assertEqual(str((root/'etc/systemd/system'/unit).readlink()), '/dev/null')
            self.assertFalse((root/'var/lib/zmalacall-server/bootstrap').exists())
            with self.assertRaises(ValueError):
                provision.provision(root, records, 'combined')

    @unittest.skipIf(os.name == 'nt', 'Offline Unix roots require Linux symlinks')
    def test_linked_configuration_parent_cannot_escape_fixture(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)/'root'
            outside = Path(folder)/'outside'
            root.mkdir(); outside.mkdir()
            (root/'etc').symlink_to(outside)
            with self.assertRaises(ValueError):
                provision.put(root, 'etc/config', b'bad')
            self.assertEqual(list(outside.iterdir()), [])
