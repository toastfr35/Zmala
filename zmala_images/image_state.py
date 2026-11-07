"""Offline archive preparation for experimental host storage; never mount/extract.

This packages the shared host runtime, role seed and startup gate into a trusted
OS/application root. It does not execute the runtime or initialize a device;
initramfs construction and disk assembly are separate build stages.
"""
import copy
import fnmatch
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile

from zmala_system import boot_capacity, boot_layout, boot_state, host_layout as layout
from . import base_intent, inspect_root, package_lock, root_build

RUNTIME = Path(layout.__file__).parent
INSTALLED = 'usr/lib/python3/dist-packages/zmala_system'
JOURNAL = 'etc/systemd/journald.conf.d/50-zmala-volatile.conf'
BOOT_GATE = 'usr/lib/systemd/system/zmala-host-storage.service'
BOOT_DEPENDENCY = 'usr/lib/systemd/system/sysinit.target.d/50-zmala-host-storage.conf'
BOOT_BACKEND = 'usr/lib/zmala/bin/boot-backend'


def name(value):
    value = value.removeprefix('./').rstrip('/')
    path = PurePosixPath(value)
    if value in ('', '.'):
        return '.'
    if path.is_absolute() or path.as_posix() != value or '..' in path.parts or '\\' in value or '\0' in value:
        raise ValueError('Unsafe root archive path')
    return value


def relocate(value):
    value = name(value)
    if value == 'var/lib/dpkg' or value.startswith('var/lib/dpkg/'):
        return layout.PACKAGE_DB+value[len('var/lib/dpkg'):]
    if value == 'var' or value.startswith('var/'):
        return layout.VAR_SEED+value[len('var'):]
    return value


def payloads(role):
    result = {layout.PROFILE: (json.dumps(layout.profile(role), indent=2)+'\n').encode(),
              boot_layout.PROFILE: (json.dumps(boot_layout.profile(role), indent=2)+'\n').encode(),
              boot_state.PROFILE: (json.dumps(boot_state.policy(role), indent=2)+'\n').encode(),
              boot_capacity.PROFILE: (json.dumps(boot_capacity.profile(role), indent=2)+'\n').encode(),
              'usr/lib/zmala/role': (role+'\n').encode()}
    special = {'journald.conf': JOURNAL, 'zmala-host-storage.service': BOOT_GATE,
               'sysinit-storage.conf': BOOT_DEPENDENCY,
               'trial-watchdog.conf': 'usr/lib/systemd/system.conf.d/99-zmala-trial.conf'}
    for filename in ('__init__.py', 'host_layout.py', 'host_storage.py', 'device_identity.py',
                     'boot_layout.py', 'boot_devices.py', 'boot_storage.py', 'boot_entry.py', 'boot_gate.py',
                     'boot_state.py', 'boot_media.py', 'boot_capacity.py', 'boot_environment.py', 'boot_backend.py',
                     'boot_select.sh',
                     *special):
        source = RUNTIME/filename
        if source.is_symlink() or not source.is_file() or source.stat().st_size > 128*1024:
            raise ValueError('Expected a bounded authored storage runtime file')
        target = special.get(filename, INSTALLED+'/'+filename)
        result[target] = source.read_text(encoding='utf-8').replace('\r\n', '\n').encode()
    result[BOOT_BACKEND] = result[INSTALLED+'/boot_backend.py']
    return result


def added_member(value, body=None, link=None):
    member = tarfile.TarInfo(value)
    member.uid = member.gid = 0
    member.uname = member.gname = 'root'
    member.mtime = int(root_build.SOURCE_DATE_EPOCH)
    member.mode = 0o755 if value == BOOT_BACKEND else 0o644
    if body is not None:
        member.size = len(body)
    elif link is not None:
        member.type, member.linkname, member.mode = tarfile.SYMTYPE, link, 0o777
    else:
        member.type, member.mode = tarfile.DIRTYPE, 0o755
    return member


def audit(path, role, selected, expected_payloads):
    root_build.preflight_tar(path)
    seen, found, nodes, hardlinks, seed_hardlinks = set(), {}, {}, {}, []
    seed_count, seed_bytes = 0, 0
    status = None
    package_link = False
    application = None
    with tarfile.open(path, 'r:') as archive:
        for member in archive:
            current = name(member.name)
            if current in seen:
                raise ValueError('Duplicate prepared-root archive path')
            seen.add(current)
            if (not 0 <= member.uid <= 65535 or not 0 <= member.gid <= 65535
                    or member.mode & ~0o7777):
                raise ValueError('Unsupported prepared-root ownership or mode')
            nodes[current] = (member.isdir(), member.isfile(), member.size,
                              member.uid, member.gid, member.mode)
            if current == 'usr/lib/zmala-application-build.json':
                if not member.isfile() or member.size > 32768 or member.uid or member.gid or member.mode != 0o644:
                    raise ValueError('Invalid application build record')
                body = archive.extractfile(member).read()
                application = json.loads(body)
                if (application.get('schema') != 1 or application.get('role') != role
                        or application.get('application_installed') is not True
                        or application.get('target_application_imports_checked') is not True
                        or application.get('target_unit_graph_checked') is not True
                        or application.get('joint_health_implemented') is not False):
                    raise ValueError('Incomplete or mismatched application build record')
            if current == '.' and (not member.isdir() or member.uid or member.gid or member.mode != 0o755):
                raise ValueError('Invalid prepared-root directory entry')
            if member.islnk():
                hardlinks[current] = name(member.linkname)
            if current.startswith('var/'):
                raise ValueError('Prepared variable state remains outside its seed')
            if current.startswith('data/'):
                raise ValueError('The image data mountpoint must not contain saved state')
            if current == 'data' and (not member.isdir() or member.uid or member.gid or member.mode != 0o755):
                raise ValueError('Invalid image data mountpoint')
            logical = ('var'+current[len(layout.VAR_SEED):]
                       if current.startswith(layout.VAR_SEED+'/') else current)
            if any(fnmatch.fnmatchcase(logical, pattern)
                   or (pattern.startswith('**/') and fnmatch.fnmatchcase(logical, pattern[3:]))
                   for pattern in inspect_root.FORBIDDEN):
                raise ValueError('Prepared root retains private factory state')
            if current.startswith(layout.VAR_SEED+'/'):
                if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                    raise ValueError('Special file in the prepared variable-state seed')
                seed_count += 1
                seed_bytes += member.size if member.isfile() else len(member.linkname.encode()) if member.issym() else 0
                if seed_count > layout.MAX_SEED_ENTRIES or seed_bytes > layout.MAX_SEED_BYTES:
                    raise ValueError('Prepared variable-state seed exceeds its RAM budget')
                if member.issym():
                    layout.seed_link(current[len(layout.VAR_SEED)+1:], member.linkname)
                if member.islnk():
                    seed_hardlinks.append(current)
            if current == layout.VAR_SEED+'/lib/dpkg':
                package_link = member.issym() and member.linkname == '/'+layout.PACKAGE_DB
            if current in expected_payloads or current == layout.PACKAGE_DB+'/status':
                limit = 16*1024**2 if current.endswith('/status') else 128*1024
                if not member.isfile() or member.uid != 0 or member.gid != 0 or member.size > limit:
                    raise ValueError('Invalid prepared runtime/package record')
                body = archive.extractfile(member).read(limit+1)
                if current in expected_payloads:
                    if member.mode != (0o755 if current == BOOT_BACKEND else 0o644) or body != expected_payloads[current]:
                        raise ValueError('Prepared runtime/configuration bytes changed')
                    found[current] = body
                else:
                    status = body.decode('utf-8')
    for current in seen:
        for parent in PurePosixPath(current).parents:
            if str(parent) != '.' and (str(parent) not in nodes or not nodes[str(parent)][0]):
                raise ValueError('Linked, missing or nondirectory prepared-root parent')
    for current, target in hardlinks.items():
        visited = {current}
        while target in hardlinks:
            if target in visited:
                raise ValueError('Cyclic prepared-root hard link')
            visited.add(target)
            target = hardlinks[target]
        if target not in nodes or not nodes[target][1] or nodes[target][3:] != nodes[current][3:]:
            raise ValueError('Invalid prepared-root hard-link target or metadata')
        if current in seed_hardlinks:
            seed_bytes += nodes[target][2]
    if seed_bytes > layout.MAX_SEED_BYTES:
        raise ValueError('Prepared hard links exceed the variable-state RAM budget')
    if (set(found) != set(expected_payloads) or not package_link or status is None
            or not {'data', 'var', layout.VAR_SEED, layout.PACKAGE_DB} <= seen):
        raise ValueError('Prepared host-storage root is incomplete')
    layout.decode_profile(found[layout.PROFILE], role)
    expected = sorted(key+'='+identity[0] for key, (identity, _, _) in selected.items())
    if base_intent.selections(status) != expected:
        raise ValueError('Prepared package state differs from the reviewed root')
    for record in package_lock.paragraphs(status):
        if record['Architecture'] != selected[record['Package']][0][1]:
            raise ValueError('Prepared package architecture changed')
    return {'packages': len(expected), 'variable_seed_entries': seed_count, 'variable_seed_bytes': seed_bytes,
            'application_installed': application is not None}


def prepare(source, expected_sha256, selected, role, output):
    source, output = Path(source), Path(output)
    root_build.preflight_tar(source)
    if not re.fullmatch('[a-f0-9]{64}', expected_sha256) or package_lock.digest(source) != expected_sha256:
        raise ValueError('Source root digest differs from its reviewed build record')
    root_build.audit(source, selected)
    content = payloads(role)
    if output.exists():
        raise ValueError('Use a new prepared-root output directory')
    output.mkdir(parents=True)
    target, seen = output/'root.tar', set()
    with tarfile.open(source, 'r:') as incoming, tarfile.open(target, 'w', format=tarfile.PAX_FORMAT) as outgoing:
        for original in incoming:
            current = name(original.name)
            if (current == 'usr/lib/zmala' or current.startswith('usr/lib/zmala/')
                    or current == INSTALLED or current.startswith(INSTALLED+'/') or current == JOURNAL):
                raise ValueError('Source is not a fresh unprepared OS-package root')
            member = copy.copy(original)
            member.name = relocate(current)
            member.pax_headers = {key: value for key, value in original.pax_headers.items()
                                  if key not in ('path', 'linkpath')}
            if original.islnk():
                member.linkname = relocate(original.linkname)
            if member.name in seen:
                raise ValueError('Prepared archive path collision')
            seen.add(member.name)
            outgoing.addfile(member, incoming.extractfile(original) if original.isfile() else None)
        additions = {**{path: None for path in ('data', 'var', 'usr/lib/zmala', layout.VAR_SEED,
                                                layout.VAR_SEED+'/lib', INSTALLED)}, **content}
        for path in content:
            for parent in PurePosixPath(path).parents:
                if str(parent) != '.':
                    additions.setdefault(str(parent), None)
        for path, body in sorted(additions.items(), key=lambda item: (len(PurePosixPath(item[0]).parts), item[0])):
            if path in seen:
                if body is not None:
                    raise ValueError('Prepared runtime/configuration collision')
                continue
            outgoing.addfile(added_member(path, body), io.BytesIO(body) if body is not None else None)
            seen.add(path)
        outgoing.addfile(added_member(layout.VAR_SEED+'/lib/dpkg', link='/'+layout.PACKAGE_DB))
    if package_lock.digest(source) != expected_sha256:
        raise ValueError('Source root changed during preparation')
    result = audit(target, role, selected, content)
    result.update(schema=1, purpose='unqualified-host-storage-root', role=role,
                  source_root_sha256=expected_sha256, root_tar_sha256=package_lock.digest(target),
                  root_tar_bytes=target.stat().st_size, runtime_storage_helper_packaged=True,
                  runtime_payload_sha256={name: hashlib.sha256(body).hexdigest() for name, body in content.items()},
                  device_initializer_packaged=True,
                  early_boot_policy_packaged=True, pid1_storage_gate_packaged=True,
                  early_boot_integration_installed=False, device_data_initialized=False,
                  toolchain_fully_locked=False,
                  hardware_boot_verified=False, production_qualified=False)
    (output/'READY.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    return result
