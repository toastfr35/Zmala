"""Emit/audit an empty factory data tar; never format, mount or select a device."""
import io
import json
from pathlib import Path
import stat
import tarfile

from zmala_system import device_identity as identity
from . import image_state, package_lock, root_build

MAX_TAR_BYTES = 64*1024


def content(role):
    return (json.dumps(identity.factory_profile(role), sort_keys=True, indent=2)+'\n').encode()


def audit(path, role):
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_TAR_BYTES:
        raise ValueError('Expected a bounded regular factory data archive')
    root_build.preflight_tar(path)
    body = content(role)
    seen = []
    with tarfile.open(path, 'r:') as archive:
        for member in archive:
            if (member.name not in ('.', identity.FACTORY) or member.name in seen
                    or member.uid != 0 or member.gid != 0):
                raise ValueError('Unexpected factory data content or ownership')
            seen.append(member.name)
            if member.name == '.':
                if not member.isdir() or member.mode != 0o700:
                    raise ValueError('Factory data root must be private')
            elif (not member.isfile() or member.mode != 0o600 or member.size != len(body)
                  or archive.extractfile(member).read(len(body)+1) != body):
                raise ValueError('Factory data record differs from its exact role contract')
    if seen != ['.', identity.FACTORY]:
        raise ValueError('Incomplete factory data archive')
    return {'schema': 1, 'role': role, 'empty_factory_data': True,
            'device_identity_present': False, 'device_data_initialized': False,
            'production_qualified': False}


def emit(role, output):
    body = content(role)
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise ValueError('Use a new factory-data output directory')
    output.mkdir(parents=True)
    target = output/'data.tar'
    with tarfile.open(target, 'w', format=tarfile.PAX_FORMAT) as archive:
        root = image_state.added_member('.'); root.mode = 0o700
        record = image_state.added_member(identity.FACTORY, body); record.mode = 0o600
        archive.addfile(root)
        archive.addfile(record, io.BytesIO(body))
    result = audit(target, role)
    result.update(data_tar_sha256=package_lock.digest(target), data_tar_bytes=target.stat().st_size)
    (output/'READY.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    return result
