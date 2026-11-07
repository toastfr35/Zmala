"""Actual native environment tools on a NEW regular GPT file, never an SD card."""
import argparse
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

from zmala_system import boot_backend, boot_environment, boot_media, boot_state
from tests.support.boot_storage_fixture import command


def outside_digest(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        position = 0
        for start, end in [(value, value+boot_media.ENV_BYTES) for value in boot_media.ENV_OFFSETS]+[(path.stat().st_size, path.stat().st_size)]:
            while position < start:
                chunk = stream.read(min(1024*1024, start-position))
                assert chunk
                digest.update(chunk); position += len(chunk)
            stream.seek(end); position = end
    return digest.hexdigest()


def seed(path, state):
    data = boot_state.encode(state).replace(b'\n', b'\0')+b'\0'
    data += b'\xff'*(boot_media.ENV_BYTES-5-len(data))
    with path.open('r+b') as stream:
        for offset, flag in zip(boot_media.ENV_OFFSETS, (1, 0)):
            stream.seek(offset); stream.write(struct.pack('<I', zlib.crc32(data))+bytes([flag])+data)
        stream.flush(); os.fsync(stream.fileno())


def selector(directory, fields):
    source = Path(__file__).resolve().parents[2]/'zmala_system/boot_select.sh'
    # Use the authored selector verbatim and a real fw_setenv transaction for its
    # saveenv operation. POSIX shell is explicitly not U-Boot interpreter coverage.
    code = '''setenv() { key=$1; shift; if test "$#" = 0; then unset "$key"; else export "$key=$1"; fi; }
# Shell functions have their own positional parameters; retain the private path.
operation=$2
saveenv() {
    printf 'zm_left=%s\\n' "$zm_left" > "$operation/consume.env"
    /usr/bin/fw_setenv -c "$operation/fw_env.config" -f "$operation/no-default-env" -s "$operation/consume.env"
}
. "$1"
printf '%s|%s' "$zm_selected" "$zm_is_trial"
'''
    result = subprocess.run(['/bin/sh', '-c', code, 'native-selector-fixture', str(source), str(directory)],
                            env={'PATH': '/usr/bin:/bin', **fields}, capture_output=True, text=True,
                            timeout=15, check=True)
    return result.stdout.split('|')


def worker(parent, role):
    assert parent.parent == Path(tempfile.gettempdir()).resolve()
    assert parent.name.startswith('zmala-boot-state-') and parent.stat().st_mode & 0o777 == 0o700
    # libubootenv owns a lock in /run/lock; isolate even that native-tool side effect.
    command(['mount', '-t', 'tmpfs', '-o', 'mode=0755,size=1M', 'tmpfs', '/run/lock'])
    path = parent/'new-gpt.img'
    with path.open('xb') as stream:
        stream.truncate(32*1024**2)
    rows = ['label: gpt', 'unit: sectors', '']; start = 16384
    for label in boot_media.LABELS:
        rows.append(f'start={start},size=2048,type=L,name="{label}"'); start += 2048
    command(['sfdisk', path], '\n'.join(rows)+'\n')
    with path.open('rb') as stream:
        table = boot_media.inspect(stream, path.stat().st_size)
    boot_media.environment_ranges(table)
    original = outside_digest(path)
    initial = boot_state.State(role, 'A'); seed(path, initial)
    with boot_environment.lock(parent/'control') as area:
        operation = area/'operation'; operation.mkdir(mode=0o700)
        boot_environment.private_file(operation/'fw_env.config', ''.join(
            f'{path} {offset:#x} {boot_media.ENV_BYTES:#x}\n' for offset in boot_media.ENV_OFFSETS).encode())
        boot_environment.private_file(operation/'no-default-env', b'')
        env = boot_environment.ToolEnvironment(operation, role)
        assert env.read() == initial
        for current, candidate, identity in (('A', 'B', '1'*64), ('B', 'A', '2'*64)):
            boot_backend.execute(['stage', candidate, identity], env, current)
            pending = env.read()
            assert selector(operation, pending.fields()) == [candidate, '1']
            consumed = env.read(); assert consumed == replace(pending, left=0)
            assert selector(operation, consumed.fields()) == [current, '0']
            assert env.read() == consumed
            # A generic RAUC good mark must never consume the product confirmation.
            boot_backend.execute(['set-state', candidate, 'good'], env, candidate)
            assert env.read() == consumed and consumed.confirmed == current
            boot_backend.execute(['confirm', identity, f'{consumed.generation:016x}'], env, candidate)
            assert env.read().confirmed == candidate and env.read().trial == '-'
        # A cancelled trial remains on the confirmed root; a stale CAS is refused.
        old = env.read(); boot_backend.execute(['stage', 'B', '3'*64], env, 'A')
        try:
            env.commit(old, old.stage('A', 'B', '4'*64))
        except ValueError:
            pass
        else:
            raise AssertionError('Actual native transport accepted stale expected state')
        boot_backend.execute(['cancel', '3'*64], env, 'A')
        # Corrupt either copy independently: the real tool must retain valid state.
        seed(path, initial)
        for offset in boot_media.ENV_OFFSETS:
            with path.open('r+b') as stream:
                stream.seek(offset); stream.write(b'BAD!'); stream.flush(); os.fsync(stream.fileno())
            if offset == boot_media.ENV_OFFSETS[0]:
                assert env.read() == initial
            else:
                try:
                    env.read()
                except (ValueError, subprocess.SubprocessError):
                    pass
                else:
                    raise AssertionError('Two invalid copies imported a default boot state')
    assert outside_digest(path) == original
    print(json.dumps({'role': role, 'native_transitions': 2, 'invalid_copies_refused': True,
                      'outside_environment_unchanged': True, 'passed': True}))


class BootStateNamespaceScenario(unittest.TestCase):
    role = None

    def test_native_environment_transactions_selector_fallback_and_gpt_gap(self):
        if sys.platform != 'linux' or os.geteuid() != 0:
            self.skipTest('Requires Linux root in an isolated new-fixture namespace')
        for name in ('unshare', 'sfdisk', 'mount', 'fw_printenv', 'fw_setenv'):
            self.assertIsNotNone(shutil.which(name), 'Missing native environment fixture tool: '+name)
        with tempfile.TemporaryDirectory(prefix='zmala-boot-state-') as folder:
            result = subprocess.run(['unshare', '--mount', '--net', '--pid', '--fork', '--kill-child=TERM',
                                     '--propagation', 'private', sys.executable,
                                     '-m', 'tests.support.boot_state_namespace',
                                     '--fixture', folder, '--role', self.role],
                                    capture_output=True, text=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout+'\n'+result.stderr)
            record = json.loads(result.stdout.strip())
            self.assertTrue(record['passed'] and record['outside_environment_unchanged'])
            self.assertTrue(record['invalid_copies_refused'])
            self.assertEqual((record['role'], record['native_transitions']), (self.role, 2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', required=True, type=Path)
    parser.add_argument('--role', required=True, choices=('server', 'terminal', 'combined'))
    args = parser.parse_args()
    worker(args.fixture, args.role)
