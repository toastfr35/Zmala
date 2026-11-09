"""Authenticated package-intake/cache tooling; not runtime RBT or boot proof."""
import json
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest
from unittest.mock import patch

from zmala_images import package_lock as packages
from zmala_images import project


def fixture(root):
    for name in ('archives', 'keyrings', 'apt/lists'):
        (root/name).mkdir(parents=True, exist_ok=True)
    archive = root/'archives/example_1.0_arm64.deb'
    archive.write_bytes(b'retained authenticated archive fixture')
    keys = {}
    for name in ('debian', 'raspberrypi'):
        path = root/'keyrings'/(name+'.gpg')
        path.write_bytes(b'public key fixture '+name.encode())
        keys[name] = packages.digest(path)
    repositories = []
    for name in packages.RELEASES:
        path = root/'apt/lists'/name
        path.write_bytes(b'signed metadata fixture')
        repositories.append({'file': name, 'sha256': packages.digest(path), 'signers': ['A'*40]})
    value = {'schema': 1, 'purpose': 'requested-package-closure', 'architecture': 'arm64',
             'distribution': 'trixie', 'requested': ['example'], 'repositories': repositories,
             'keyrings': keys, 'image_qualified': False,
             'packages': [{'package': 'example', 'version': '1.0', 'architecture': 'arm64',
                           'archive': archive.name, 'bytes': archive.stat().st_size,
                           'sha256': packages.digest(archive), 'uri': 'https://deb.debian.org/pool/example.deb'}]}
    path = root/'packages.lock.json'
    path.write_text(json.dumps(value))
    return value, packages.digest(path)


class PackagePlanTests(unittest.TestCase):
    def test_uri_plan_and_budgets(self):
        line = "'https://deb.debian.org/debian/pool/example.deb' example_1.0_arm64.deb 123 SHA256:fixture"
        self.assertEqual(packages.plan('APT informational output\n'+line)['example_1.0_arm64.deb']['bytes'], 123)
        self.assertEqual(packages.plan(line.rsplit(' ', 1)[0])['example_1.0_arm64.deb']['bytes'], 123)
        for value in (line.replace('https:', 'http:'), line.replace('deb.debian.org', 'untrusted.invalid'),
                      line.replace(' example_', ' ../example_'), line.replace(' 123 ', ' -1 '),
                      line+'\n'+line, 'no archives'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                packages.plan(value)
        with patch.object(packages, 'MAX_BYTES', 122), self.assertRaises(ValueError):
            packages.plan(line)

    def test_debian_control_records(self):
        self.assertEqual(packages.paragraphs('Package: one\nDescription: text\n continuation\n\nPackage: two\n'),
                         [{'Package': 'one', 'Description': 'text'}, {'Package': 'two'}])
        with self.assertRaises(ValueError):
            packages.paragraphs('Package: one\nPackage: two')

    def test_apt_configuration_is_isolated_before_system_hook_loading(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            key = parent/'public.gpg'
            key.write_bytes(b'fixture')
            root = parent/'intake'
            packages.prepare(root, key, key)
            conf = (root/'apt.conf').read_text()
            self.assertIn((root/'empty.d').as_posix(), conf)
            self.assertIn('Dir::Etc::main', conf)
            self.assertIn('#clear APT::Architectures;', conf)
            with patch.object(packages, 'run') as run:
                packages.apt_run(root, ['apt-get', '--download-only', '--yes', 'install', 'example'])
                args = run.call_args.args
                self.assertIn('--download-only', args[0])
                self.assertIn('APT::Get::AllowUnauthenticated=false', args[0])
                self.assertIn('Acquire::AllowInsecureRepositories=false', args[0])
                self.assertIn('Dir::State::status='+str(root/'apt/status'), args[0])
                self.assertEqual(args[2], root/'apt.conf')
            self.assertEqual((root/'apt/status').read_text(), '')
            with self.assertRaises(ValueError):
                packages.prepare(root, key, key)


class ArchiveSignatureTests(unittest.TestCase):
    def result(self, text, code=0):
        return subprocess.CompletedProcess(['gpgv'], code, text, '')

    def test_known_signature_plus_unknown_rollover_signature(self):
        known = '[GNUPG:] VALIDSIG '+'A'*40+' 2026-11-04 0 0 4 0 1 8 01\n'
        missing = ('[GNUPG:] ERRSIG BBBBBBBBBBBBBBBB 1 8 00 0 9 '+'B'*40+'\n'
                   '[GNUPG:] NO_PUBKEY BBBBBBBBBBBBBBBB\n')
        self.assertEqual(packages.verified_signers(self.result(known)), ['A'*40])
        self.assertEqual(packages.verified_signers(self.result(known+missing, 2)), ['A'*40])
        with self.assertRaises(ValueError):
            packages.verified_signers(self.result(missing, 2))

    def test_invalid_expired_or_ambiguous_signature_errors_are_rejected(self):
        known = '[GNUPG:] VALIDSIG '+'A'*40+' 2026-11-04 0 0 4 0 1 8 01\n'
        for event in ('BADSIG', 'EXPKEYSIG', 'REVKEYSIG', 'SIGEXPIRED', 'ERROR', 'NODATA'):
            with self.subTest(event=event), self.assertRaises(ValueError):
                packages.verified_signers(self.result(known+'[GNUPG:] '+event+' example\n', 2))
        for text in (known, known+'[GNUPG:] ERRSIG BBBB 1 8 00 0 4\n'):
            with self.assertRaises(ValueError):
                packages.verified_signers(self.result(text, 2))


class RetainedPackageTests(unittest.TestCase):
    def test_git_checkout_preserves_hashed_input_bytes_with_autocrlf_enabled(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env = {**os.environ, 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1'}
            def git(*args):
                subprocess.run(['git', '-C', str(root), *args], env=env,
                               check=True, capture_output=True)
            git('init', '-q')
            git('config', 'core.autocrlf', 'true')
            shutil.copyfile(project.ROOT/'.gitattributes', root/'.gitattributes')
            names = ('zmala_images/locks/server.json', 'zmala_images/bootloader-profile.json')
            body = b'{\n  "fixture": true\n}\n'
            for name in names:
                path = root/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
            git('add', '.gitattributes', *names)
            for name in names:
                (root/name).unlink()
            git('checkout-index', '--all', '--force')
            for name in names:
                self.assertEqual((root/name).read_bytes(), body)

    def test_role_lock_index_detects_intent_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ('zmala_images/profiles.json', 'build_tools/linux/dependencies.txt'):
                target = root/name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(project.ROOT/name, target)
            shutil.copytree(project.ROOT/'zmala_images/locks', root/'zmala_images/locks')
            with patch.object(project, 'ROOT', root):
                self.assertEqual(set(project.package_locks()['roles']), {'server', 'terminal', 'combined'})
                path = root/'zmala_images/profiles.json'
                profile = json.loads(path.read_text())
                profile['roles']['server']['extra_packages'].append('unexpected-dependency')
                path.write_text(json.dumps(profile))
                with self.assertRaisesRegex(ValueError, 'intent'):
                    project.package_locks()

    def test_complete_retained_inputs_require_the_external_lock_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, expected = fixture(root)
            self.assertFalse(packages.verify(root, expected)['image_qualified'])
            with self.assertRaises(ValueError):
                packages.verify(root, '0'*64)
            path = root/'packages.lock.json'
            value = json.loads(path.read_text()); value['requested'] = ['changed']
            path.write_text(json.dumps(value))
            with self.assertRaises(ValueError):
                packages.verify(root, expected)

    def test_changed_added_or_missing_archives_and_trust_are_rejected(self):
        for target in ('archives/example_1.0_arm64.deb', 'keyrings/debian.gpg',
                       'apt/lists/'+next(iter(packages.RELEASES))):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _, expected = fixture(root)
                (root/target).write_bytes(b'changed')
                with self.assertRaises(ValueError):
                    packages.verify(root, expected)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, expected = fixture(root)
            (root/'archives/unexpected.deb').write_bytes(b'x')
            with self.assertRaises(ValueError):
                packages.verify(root, expected)

    def test_malformed_trusted_manifest_still_cannot_escape_or_overbudget(self):
        for name, value in (('archive', '../outside.deb'), ('architecture', 'amd64'), ('bytes', True), ('bytes', 0)):
            with self.subTest(name=name,value=value), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                manifest, _ = fixture(root)
                manifest['packages'][0][name] = value
                path = root/'packages.lock.json'; path.write_text(json.dumps(manifest))
                with self.assertRaises(ValueError):
                    packages.verify(root, packages.digest(path))

    @unittest.skipIf(os.name == 'nt', 'Linux image-build cache links')
    def test_linked_archive_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, expected = fixture(root)
            archive = root/'archives/example_1.0_arm64.deb'
            archive.rename(root/'original')
            archive.symlink_to(root/'original')
            with self.assertRaises(ValueError):
                packages.verify(root, expected)


if __name__ == '__main__':
    unittest.main()


class CombinedIntentTests(unittest.TestCase):
    def test_combined_resolves_exact_union_and_reviewed_shared_versions(self):
        from zmala_images import project
        self.assertEqual(project.packages('combined'),
                         sorted(set(project.packages('terminal')) | set(project.packages('server'))))
        index = project.package_locks()
        self.assertEqual(set(index['roles']), {'server', 'terminal', 'combined'})
        for role in ('terminal', 'combined'):
            self.assertTrue({'psmisc', 'uhubctl'} <= set(project.packages(role)))
            manifest = json.loads((project.ROOT/'zmala_images/locks'/index['roles'][role]['file']).read_text())
            self.assertIn('uhubctl', {item['package'] for item in manifest['packages']})
        self.assertNotIn('uhubctl', project.packages('server'))

    def test_reanchored_role_lock_cannot_change_a_shared_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ('zmala_images/profiles.json', 'build_tools/linux/dependencies.txt'):
                target = root/name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(project.ROOT/name, target)
            folder = root/'zmala_images/locks'
            shutil.copytree(project.ROOT/'zmala_images/locks', folder)
            manifest = json.loads((folder/'combined.json').read_text())
            shared = json.loads((folder/'server.json').read_text())['packages'][0]['package']
            next(p for p in manifest['packages'] if p['package'] == shared)['sha256'] = 'f'*64
            (folder/'combined.json').write_text(json.dumps(manifest))
            index = json.loads((folder/'index.json').read_text())
            index['roles']['combined']['sha256'] = packages.digest(folder/'combined.json')
            (folder/'index.json').write_text(json.dumps(index))
            with patch.object(project, 'ROOT', root), self.assertRaisesRegex(ValueError, 'Shared role'):
                project.package_locks()
