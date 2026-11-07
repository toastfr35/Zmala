"""Initialize an experimental image-managed device identity before host storage.

The boot caller must already have selected/validated the data partition. Nothing
here selects or formats a disk, expands a filesystem, imports legacy data,
generates SSH keys or starts services. Never use this as a live-host repair tool.
"""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import platform

from zmala_system import host_layout as layout, host_storage as storage

FACTORY = '.zmala-factory.json'
LOCK = '.zmala-init.lock'
STAGING = '.zmala-identity.next'
NEXT = '.zmala-storage.next'
IDENTITY = ('machine-id', 'hostname')


# @llr LLR-SRV-HOST-014, LLR-TERM-MAINT-041, LLR-SRV-HOST-029, LLR-TERM-MAINT-056
def factory_profile(role):
    layout.profile(role)
    return {'schema': 1, 'role': role, 'purpose': 'zmala-factory-data'}


# @llr LLR-SRV-HOST-014, LLR-TERM-MAINT-041, LLR-SRV-HOST-029, LLR-TERM-MAINT-056
def factory_record(data, role):
    body = storage.read_record(data, FACTORY, 0o600, layout.MAX_PROFILE_BYTES)
    value = json.loads(body.decode('utf-8'), object_pairs_hook=layout.unique_fields)
    expected = factory_profile(role)
    if (value != expected or not isinstance(value, dict)
            or any(type(value[key]) is not type(item) for key, item in expected.items())):
        raise ValueError('Unsupported factory data record')


# @llr LLR-SRV-HOST-015, LLR-TERM-MAINT-042
def sync_directory(path):
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def names(path, allowed):
    # Bound even corrupt directories rather than materializing an unbounded list.
    found = set()
    with os.scandir(path) as entries:
        for entry in entries:
            if entry.name not in allowed:
                raise ValueError('Unexpected state in first-boot namespace')
            found.add(entry.name)
    return found


# @llr LLR-SRV-HOST-014, LLR-SRV-HOST-016, LLR-TERM-MAINT-041, LLR-TERM-MAINT-043
def saved_identity(data, name='identity'):
    directory = storage.safe(data, name)
    layout.metadata(directory.lstat(), mode=0o700, directory=True)
    if names(directory, IDENTITY) != set(IDENTITY):
        raise ValueError('Incomplete committed device identity')
    body = {}
    for field in IDENTITY:
        body[field] = storage.read_record(data, name+'/'+field, 0o644, 128)
        layout.identity(body[field], hostname=field == 'hostname')
    return body


def present(path):
    # A dangling symlink is state to reject, not an absent transaction.
    return path.exists() or path.is_symlink()


# @llr LLR-SRV-HOST-014, LLR-SRV-HOST-016, LLR-TERM-MAINT-041, LLR-TERM-MAINT-043, LLR-SRV-HOST-029, LLR-TERM-MAINT-056
def admit(data, role, facts):
    layout.profile(role)
    data = storage.canonical(data)
    current, host = facts.get(data), facts.get(Path('/'))
    if (data == Path('/') or not current or current.filesystem != 'ext4'
            or 'rw' not in current.flags or (host and host.device == current.device)):
        raise ValueError('Expected a validated separate writable ext4 data mount')
    layout.metadata(data.lstat(), mode=0o700, directory=True)
    if present(data/layout.DATA_MARKER):
        layout.decode_profile(storage.read_record(data, layout.DATA_MARKER, 0o600,
                                                 layout.MAX_PROFILE_BYTES), role, data=True)
        saved_identity(data)
        if present(data/STAGING) or present(data/NEXT):
            raise ValueError('Unexpected transaction after identity initialization')
        if present(data/FACTORY):
            factory_record(data, role)
    else:
        factory_record(data, role)
        names(data, {FACTORY, LOCK, STAGING, NEXT, 'identity', 'lost+found'})
        recovery = data/'lost+found'
        if present(recovery):
            layout.metadata(recovery.lstat(), mode=0o700, directory=True)
            names(recovery, set())
        if present(data/'identity'):
            saved_identity(data)
            if present(data/STAGING):
                raise ValueError('Conflicting staged and committed identities')
    return data


# @llr LLR-SRV-HOST-014, LLR-TERM-MAINT-041
@contextmanager
def exclusive(data):
    """Leave the lock inode in place: unlinking it would admit a second lock."""
    import fcntl
    descriptor = os.open(data/LOCK, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(descriptor)
        layout.metadata(info, mode=0o600)
        if info.st_nlink != 1 or info.st_size:
            raise ValueError('Invalid initializer lock')
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)


# @llr LLR-SRV-HOST-015, LLR-TERM-MAINT-042
def write_exclusive(path, body, mode):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    with os.fdopen(os.open(path, flags, mode), 'wb') as stream:
        os.fchmod(stream.fileno(), mode)  # New file only: do not inherit a restrictive boot umask.
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())


# @llr LLR-SRV-HOST-015, LLR-TERM-MAINT-042
def random_identity(role):
    layout.profile(role)
    value = b''
    while len(value) < 16:
        chunk = os.getrandom(16-len(value))
        if not chunk:
            raise ValueError('Kernel entropy read made no progress')
        value += chunk
    machine = value.hex().encode()
    layout.identity(machine)
    return {'machine-id': machine+b'\n',
            'hostname': b'zmala-'+role.encode()+b'-'+machine[:12]+b'\n'}


# @llr LLR-SRV-HOST-016, LLR-TERM-MAINT-043
def check_staging(data, role):
    """Inspect every known partial entry before removing or reusing any of it."""
    stage = data/STAGING
    if not present(stage):
        return None
    layout.metadata(stage.lstat(), mode=0o700, directory=True)
    found = names(stage, IDENTITY)
    for field in found:
        storage.read_record(data, STAGING+'/'+field, 0o644, 128)
    if found == set(IDENTITY):
        try:
            value = saved_identity(data, STAGING)
            expected = b'zmala-'+role.encode()+b'-'+value['machine-id'][:12]
            # A short hostname write may still be a valid DNS label. It is not
            # a complete stage unless it matches the generated identifier too.
            if value['hostname'].rstrip(b'\n') == expected:
                return value
        except ValueError:
            pass  # A bounded partial write is retryable only before identity commit.
    return False


# @llr LLR-SRV-HOST-015, LLR-SRV-HOST-016, LLR-TERM-MAINT-042, LLR-TERM-MAINT-043
def commit_identity(data, role):
    if present(data/'identity'):
        saved_identity(data)
        for field in IDENTITY:
            with (data/'identity'/field).open('rb') as stream:
                os.fsync(stream.fileno())
        sync_directory(data/'identity')
        sync_directory(data)
        return
    staged = check_staging(data, role)
    if staged is False:
        for field in names(data/STAGING, IDENTITY):
            (data/STAGING/field).unlink()
        (data/STAGING).rmdir()
    if not staged:
        body = random_identity(role)
        (data/STAGING).mkdir(mode=0o700)
        (data/STAGING).chmod(0o700)
        for field in IDENTITY:
            write_exclusive(data/STAGING/field, body[field], 0o644)
    # Sync again when adopting a complete stage from an interrupted prior process.
    for field in IDENTITY:
        with (data/STAGING/field).open('rb') as stream:
            os.fsync(stream.fileno())
    sync_directory(data/STAGING)
    (data/STAGING).rename(data/'identity')
    sync_directory(data)


# @llr LLR-SRV-HOST-014, LLR-SRV-HOST-015, LLR-SRV-HOST-016, LLR-TERM-MAINT-041, LLR-TERM-MAINT-042, LLR-TERM-MAINT-043
def initialize(data, role, mounts=None):
    if platform.system() != 'Linux' or os.geteuid() != 0 or os.getegid() != 0:
        raise ValueError('Device initialization requires Linux boot namespace root')
    mounts = mounts or storage.NativeMounts()
    data = admit(data, role, mounts.facts())
    with exclusive(data):
        admit(data, role, mounts.facts())
        if not present(data/layout.DATA_MARKER):
            # Inspect a leftover marker before changing any identity state.
            pending = data/NEXT
            if present(pending):
                storage.read_record(data, NEXT, 0o600, layout.MAX_PROFILE_BYTES)
            commit_identity(data, role)
            if present(pending):
                pending.unlink()
            body = (json.dumps({'schema': 1, 'role': role})+'\n').encode()
            write_exclusive(pending, body, 0o600)
            pending.replace(data/layout.DATA_MARKER)
        admit(data, role, mounts.facts())
        sync_directory(data)
    return {'schema': 1, 'role': role, 'initialized': True}


# @llr LLR-SRV-HOST-014, LLR-SRV-HOST-015, LLR-SRV-HOST-016, LLR-TERM-MAINT-041, LLR-TERM-MAINT-042, LLR-TERM-MAINT-043
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--role', choices=layout.ROLES, required=True)
    args = parser.parse_args()
    try:
        initialize(args.data, args.role)
    except (OSError, ValueError):
        parser.error('Device identity initialization failed; normal startup must remain fenced.')
    print('Image-managed device identity initialized.')


if __name__ == '__main__':
    main()
