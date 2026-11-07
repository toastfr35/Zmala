"""Real private mount-namespace verification using synthetic ext4 file images.

No physical device is selected. The parent removes its new temporary directory
only after the worker namespace has exited and released every loop mount.
"""
import argparse
import errno
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

from zmala_system import host_layout as layout, host_storage as storage
from tests.support import appliance_storage_fixture as fixture


def run(args):
    return subprocess.run([str(a) for a in args], check=True, capture_output=True, text=True, timeout=30)


def ext4(parent, name):
    """Only format a newly created bounded regular file inside the fixture."""
    image = parent/(name+'.img')
    with image.open('xb') as stream:
        stream.truncate(32*1024**2)
    info = image.lstat()
    assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and image.parent == parent
    target = parent/name; target.mkdir()
    run(['mkfs.ext4', '-F', '-q', image])
    run(['mount', '-o', 'loop', image, target])
    return target


def probe(root, role, value, component=None):
    """Chroot the already loaded interpreter, then exercise app UID 1000.

    The fixture needs no binaries or host library copies in its synthetic root.
    Every returned value belongs to this synthetic test, never a real account.
    """
    component = component or role
    read_fd, write_fd = os.pipe()
    child = os.fork()
    if child == 0:
        os.close(read_fd)
        result, status = {}, 0
        try:
            os.chroot(root); os.chdir('/')
            result['vendor'] = Path('/etc/vendor.conf').read_text()
            result['package'] = Path('/var/lib/dpkg/status').read_text()
            result['alternative'] = Path('/var/lib/dpkg/alternatives/tool').read_text()
            result['product_default'] = Path('/etc/zmalacall/vendor.conf').read_text()
            result['only_a'] = Path('/etc/only-a').exists()
            result['var_a'] = Path('/var/tmp/only-a').exists()
            result['tmp_a'] = Path('/tmp/only-a').exists()
            try:
                Path('/etc/machine-id').write_bytes(b'changed')
            except OSError as error:
                result['identity_readonly'] = error.errno == errno.EROFS
            else:
                result['identity_readonly'] = False
            uid = 1001 if role == 'combined' and component == 'server' else 1000
            os.setgroups([]); os.setgid(uid); os.setuid(uid)
            result['identity'] = Path('/etc/machine-id').read_bytes().decode()
            result['hostname'] = Path('/etc/hostname').read_bytes().decode()
            app = Path('/var/lib/zmalacall-server' if component == 'server' else '/var/lib/zmalacall')
            record = app/'probe.json'
            result['previous'] = json.loads(record.read_text()) if record.exists() else None
            with os.fdopen(os.open(record, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as stream:
                json.dump({'value': value}, stream); stream.flush(); os.fsync(stream.fileno())
            if role == 'combined':
                own = Path('/etc/zmalacall/operator')/component/'private-fixture'
                assert own.read_text() == component
                other = 'server' if component == 'terminal' else 'terminal'
                forbidden = [Path('/etc/zmalacall/operator')/other/'private-fixture',
                             Path('/var/lib/zmalacall-server' if other == 'server' else '/var/lib/zmalacall')/'probe.json',
                             Path('/etc/letsencrypt/private-fixture')]
                for private in forbidden:
                    for mode in ('rb', 'wb'):
                        try:
                            with private.open(mode):
                                pass
                        except PermissionError:
                            pass
                        else:
                            raise AssertionError('Cross-component private access accepted')
                result['component_isolation'] = True
            try:
                Path('/etc/ssh/keys/private-fixture').read_bytes()
            except PermissionError:
                result['host_keys_private'] = True
            else:
                result['host_keys_private'] = False
        except BaseException as error:
            result, status = {'error': type(error).__name__+': '+str(error)}, 1
        os.write(write_fd, json.dumps(result).encode())
        os.close(write_fd); os._exit(status)
    os.close(write_fd)
    with os.fdopen(read_fd, 'rb') as stream:
        result = json.loads(stream.read(65536))
    _, status = os.waitpid(child, 0)
    assert os.waitstatus_to_exitcode(status) == 0, result
    return result


class FailingMounts(storage.NativeMounts):
    def __init__(self, target, after):
        self.target, self.after = target, after

    def run(self, args):
        if args[0] == 'mount' and args[-1] == str(self.target):
            if self.after:
                super().run(args)
            raise subprocess.CalledProcessError(97, args, stderr='injected fixture failure')
        return super().run(args)


def worker(parent, role):
    parent = parent.resolve()
    assert parent.parent == Path(tempfile.gettempdir()).resolve()
    assert parent.name.startswith('zmala-host-storage-') and stat.S_IMODE(parent.stat().st_mode) == 0o700
    owned = []
    try:
        data = ext4(parent, 'data'); owned.append(data); fixture.data(data, role)
        (data/'host').mkdir(mode=0o700); (data/'host/ssh').mkdir(mode=0o700)
        fixture.file(data/'host/ssh/private-fixture', b'synthetic private fixture', 0o600)
        components = ('terminal', 'server') if role == 'combined' else (role,)
        roots, lowers = [], []
        for generation in ('A', 'B'):
            root = ext4(parent, 'root-'+generation); owned.append(root)
            fixture.image(root, role, generation)
            run(['mount', '-o', 'remount,ro', root])
            lower = parent/('lower-'+generation); lower.mkdir()
            run(['mount', '--bind', root, lower]); owned.append(lower)
            roots.append(root); lowers.append(lower)
        ram = parent/'ram'; ram.mkdir()
        run(['mount', '-t', 'tmpfs', '-o', 'mode=0700,size=8M', 'tmpfs', ram]); owned.append(ram)
        area = ram/'storage'
        initial = set(storage.NativeMounts.facts())

        # Invalid data provenance must not create any mutable view/readiness.
        marker = data/layout.DATA_MARKER; original = marker.read_bytes()
        marker.write_bytes(json.dumps({'schema': 1, 'role': 'terminal' if role == 'server' else 'server'}).encode())
        try:
            storage.prepare(roots[0], data, area, role)
        except ValueError:
            pass
        else:
            raise AssertionError('Wrong-role data accepted')
        marker.write_bytes(original)
        assert set(storage.NativeMounts.facts()) == initial and not area.exists()
        identity_backup = data/'identity-backup'; (data/'identity').rename(identity_backup)
        (data/'identity').symlink_to(identity_backup, target_is_directory=True)
        try:
            storage.prepare(roots[0], data, area, role)
        except ValueError:
            pass
        else:
            raise AssertionError('Linked identity parent accepted')
        (data/'identity').unlink(); identity_backup.rename(data/'identity')
        assert set(storage.NativeMounts.facts()) == initial and not area.exists()

        # Exercise both a failed mount and a command that fails after mounting.
        for after in (False, True):
            try:
                storage.prepare(roots[0], data, area, role,
                                FailingMounts(roots[0]/'var/lib/bluetooth', after))
            except subprocess.CalledProcessError as error:
                assert error.returncode == 97
            else:
                raise AssertionError('Injected operation failure accepted')
            assert set(storage.NativeMounts.facts()) == initial
            assert not (area/'ready.json').exists()
            assert (data/'identity/machine-id').read_bytes() == fixture.MACHINE_ID
            assert (lowers[0]/'etc/vendor.conf').read_text() == 'factory-A'

        for number, (root, lower) in enumerate(zip(roots, lowers)):
            prepared = storage.prepare(root, data, area, role)
            try:
                assert json.loads((area/'ready.json').read_text()) == {
                    'schema': 1, 'role': role, 'storage_prepared': True}
                facts = storage.NativeMounts.facts()
                assert facts[root/'etc'].filesystem == 'overlay'
                assert facts[root/'var'].filesystem == facts[root/'tmp'].filesystem == 'tmpfs'
                for path, mib in ((root/'var', 128), (root/'tmp', 128), (area, 64)):
                    capacity = os.statvfs(path)
                    assert capacity.f_blocks*capacity.f_frsize == mib*1024**2
                assert all('ro' in facts[root/b.target].flags for b in layout.bindings(role) if b.readonly)
                if role in ('terminal', 'combined'):
                    token = root/'var/lib/zmalacall-pairing/bond.json'
                    if number == 0:
                        assert not token.exists()
                        fixture.file(token, b'{"token":"bond-fixture"}', 0o600)
                    else:
                        assert token.read_bytes() == b'{"token":"bond-fixture"}'
                    assert token.samefile(data/'host/presenter/bond.json')
                try:
                    storage.prepare(root, data, area, role)
                except ValueError:
                    pass
                else:
                    raise AssertionError('Active preparation repeated')
                if role == 'combined':
                    for component, gid in (('terminal', 1000), ('server', 1001)):
                        private = root/'etc/zmalacall/operator'/component/'private-fixture'
                        fixture.file(private, component.encode(), 0o640)
                        os.chown(private, 0, gid)
                    fixture.file(root/'etc/letsencrypt/private-fixture', b'private certificate fixture', 0o600)
                    server = probe(root, role, 'from-'+str(number), 'server')
                    assert server['component_isolation']
                    assert server['previous'] == (None if number == 0 else {'value': 'from-0'})
                result = probe(root, role, 'from-'+str(number), components[0])
                if role == 'combined':
                    assert result['component_isolation']
                assert result['vendor'] == 'factory-'+('A' if number == 0 else 'B')
                assert result['package'] == 'slot-package-'+('A' if number == 0 else 'B')
                assert result['alternative'] == 'alternative-'+('A' if number == 0 else 'B')
                assert result['product_default'] == 'product-default-'+('A' if number == 0 else 'B')
                assert result['identity'] == fixture.MACHINE_ID.decode()
                assert result['hostname'] == fixture.HOSTNAME.decode()
                assert result['identity_readonly'] and result['host_keys_private']
                assert result['previous'] == (None if number == 0 else {'value': 'from-0'})
                assert not result['only_a'] and not result['var_a'] and not result['tmp_a']
                app_file = data/'state'/components[0]/'probe.json'
                assert (app_file.stat().st_uid, app_file.stat().st_gid) == (1000, 1000)
                if number == 0:
                    (root/'etc/vendor.conf').write_text('RAM override')
                    for name in ('etc/only-a', 'var/tmp/only-a', 'tmp/only-a'):
                        (root/name).write_text('ephemeral')
                    assert (lower/'etc/vendor.conf').read_text() == 'factory-A'
                    assert not (lower/'var/tmp/only-a').exists()
                    try:
                        (lower/'etc/vendor.conf').write_text('must fail')
                    except OSError as error:
                        assert error.errno == errno.EROFS
                    else:
                        raise AssertionError('Selected lower root was writable')
            finally:
                prepared.close()
            assert set(storage.NativeMounts.facts()) == initial
        for component in components:
            saved = data/'state'/component/'probe.json'
            assert json.loads(saved.read_text()) == {'value': 'from-1'}
            uid = 1001 if role == 'combined' and component == 'server' else 1000
            assert (saved.stat().st_uid, saved.stat().st_gid) == (uid, uid)
        print(json.dumps({'role': role, 'root_generations': 2, 'failure_modes': 4, 'passed': True}), flush=True)
    finally:
        # Fixture volumes are separate from the helper's owned mutable views.
        # Namespace exit also releases these scoped auto-clear loop mounts.
        for target in reversed(owned):
            try:
                if target in storage.NativeMounts.facts():
                    run(['umount', target])
            except subprocess.SubprocessError:
                pass


class StorageNamespaceScenario(unittest.TestCase):
    role = None

    def test_real_readonly_generations_private_data_ram_views_and_failure_cleanup(self):
        if sys.platform != 'linux' or os.geteuid() != 0:
            self.skipTest('Requires Linux root inside an isolated test namespace')
        for executable in ('unshare', 'mount', 'umount', 'mkfs.ext4'):
            self.assertIsNotNone(shutil.which(executable), 'Missing namespace fixture tool: '+executable)
        self.assertTrue(Path('/dev/loop-control').exists(), 'Loop-file support is required for real ext4 fixtures')
        with tempfile.TemporaryDirectory(prefix='zmala-host-storage-') as folder:
            result = subprocess.run(
                ['unshare', '--mount', '--net', '--pid', '--fork', '--kill-child=TERM', '--propagation', 'private',
                 sys.executable, '-m', 'tests.support.appliance_storage_namespace', '--fixture', folder, '--role', self.role],
                capture_output=True, text=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout+'\n'+result.stderr)
            value = json.loads(result.stdout.strip())
            self.assertEqual(value, {'role': self.role, 'root_generations': 2, 'failure_modes': 4, 'passed': True})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', required=True, type=Path)
    parser.add_argument('--role', choices=('server', 'terminal', 'combined'), required=True)
    args = parser.parse_args()
    worker(args.fixture, args.role)
