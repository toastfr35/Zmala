"""Process-interruption integration on disposable ext4 files; never real cards."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests.support.appliance_storage_namespace import ext4, run
from tests.support.device_identity_fixture import factory
from zmala_system import device_identity as identity, host_storage as storage


def worker(parent, role):
    assert parent.parent == Path(tempfile.gettempdir()).resolve()
    assert parent.name.startswith('zmala-identity-process-')
    assert parent.stat().st_mode & 0o777 == 0o700
    owned = []
    try:
        for boundary in range(1, 9):
            data = ext4(parent, 'data-'+str(boundary)); owned.append(data)
            factory(data, role)
            child = os.fork()
            if child == 0:
                sync, calls = os.fsync, []
                def cut(fd):
                    sync(fd); calls.append(fd)
                    if len(calls) == boundary:
                        os._exit(121)
                with patch.object(identity.os, 'fsync', cut):
                    identity.initialize(data, role)
                os._exit(122)  # Every selected boundary must actually be reached.
            _, status = os.waitpid(child, 0)
            assert os.waitstatus_to_exitcode(status) == 121, (boundary, status)
            before = identity.saved_identity(data) if (data/'identity').exists() else None
            assert identity.initialize(data, role)['initialized']
            after = identity.saved_identity(data)
            if before:
                assert before == after
            for field in identity.IDENTITY:
                info = (data/'identity'/field).stat()
                assert (info.st_uid, info.st_gid, info.st_mode & 0o777) == (0, 0, 0o644)
            marker = data/identity.layout.DATA_MARKER
            assert marker.stat().st_mode & 0o777 == 0o600
            (data/'state').mkdir(mode=0o700)
            (data/'state/value').write_bytes(b'synthetic application state')
            assert identity.initialize(data, role)['initialized']
            assert identity.saved_identity(data) == after
            assert (data/'state/value').read_bytes() == b'synthetic application state'
            # Do not adopt files owned by an application as privileged identity.
            machine = data/'identity/machine-id'
            os.chown(machine, 1000, 1000)
            try:
                identity.initialize(data, role)
            except ValueError:
                pass
            else:
                raise AssertionError('Initializer accepted application-owned identity')
            assert (machine.stat().st_uid, machine.stat().st_gid) == (1000, 1000)
            assert machine.read_bytes() == after['machine-id']
            run(['umount', data]); owned.remove(data)
        print(json.dumps({'role': role, 'process_interruption_boundaries': 8, 'passed': True}))
    finally:
        for data in reversed(owned):
            if data in storage.NativeMounts.facts():
                run(['umount', data])


class IdentityNamespaceScenario(unittest.TestCase):
    role = None

    def test_real_ext4_interrupted_processes_preserve_committed_identity_and_data(self):
        if sys.platform != 'linux' or os.geteuid() != 0:
            self.skipTest('Requires Linux root inside an isolated test namespace')
        for executable in ('unshare', 'mount', 'umount', 'mkfs.ext4'):
            self.assertIsNotNone(shutil.which(executable), 'Missing namespace fixture tool: '+executable)
        self.assertTrue(Path('/dev/loop-control').exists(), 'Loop-file support is required for ext4 fixtures')
        with tempfile.TemporaryDirectory(prefix='zmala-identity-process-') as folder:
            result = subprocess.run(['unshare', '--mount', '--net', '--pid', '--fork', '--kill-child=TERM',
                                     '--propagation', 'private', sys.executable,
                                     '-m', 'tests.support.device_identity_namespace',
                                     '--fixture', folder, '--role', self.role],
                                    capture_output=True, text=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout+'\n'+result.stderr)
            self.assertEqual(json.loads(result.stdout.strip()),
                             {'role': self.role, 'process_interruption_boundaries': 8, 'passed': True})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--role', choices=('server', 'terminal', 'combined'), required=True)
    args = parser.parse_args()
    worker(args.fixture, args.role)
