"""Unqualified locked ARM64 root builds, isolated from the host and network.

This builds a tar of OS package contents, not a flashable/bootable Zmala image.
There is no application, provisioning, A/B assembly or production qualification.
"""
import fnmatch
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile

from . import base_intent, build_space, inspect_root, local_repo, package_lock, project

MAX_ROOT_BYTES = 8*1024**3
MAX_MEMBERS = 200000
MIN_BUILD_FREE_BYTES = 32*1024**3
SOURCE_DATE_EPOCH = '1793836800'  # Explicit development build epoch, 2026-11-05.


def preflight_tar(path):
    """Bound raw headers before tarfile can allocate extended-header payloads."""
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_ROOT_BYTES:
        raise ValueError('Expected a bounded regular root archive')
    length, offset, count = path.stat().st_size, 0, 0
    with path.open('rb') as stream:
        while offset+512 <= length:
            stream.seek(offset)
            header = stream.read(512)
            if header == b'\0'*512:
                return
            member = tarfile.TarInfo.frombuf(header, 'utf-8', 'strict')
            count += 1
            if (count > MAX_MEMBERS or member.size < 0 or member.size > MAX_ROOT_BYTES
                    or (member.type in (tarfile.XHDTYPE, tarfile.XGLTYPE,
                                        tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK)
                        and member.size > 64*1024)):
                raise ValueError('Root archive header exceeds budget')
            offset += 512+((member.size+511)//512)*512
            if offset > length:
                raise ValueError('Truncated root archive member')
    raise ValueError('Root archive has no end marker')


def audit(path, selected):
    """Read only selected factory boundaries; never extract archive members."""
    preflight_tar(path)
    wanted = {'var/lib/dpkg/status': base_intent.MAX_LEDGER_BYTES,
              'etc/machine-id': 128, 'etc/hostname': 256, 'etc/shadow': 1024**2}
    masks = {f'etc/systemd/system/{unit}': False for unit in
             ('rpi-eeprom-update.service', 'apt-daily.timer', 'apt-daily-upgrade.timer')}
    directories = {name: False for name in ('etc', 'etc/ssh', 'etc/apt',
                   'etc/apt/sources.list.d', 'etc/systemd', 'etc/systemd/system',
                   'var', 'var/lib', 'var/lib/dpkg')}
    contents, seen, size = {}, set(), 0
    with tarfile.open(path, 'r:') as archive:
        for member in archive:
            name = member.name.removeprefix('./').rstrip('/')
            pure = PurePosixPath(name)
            if name in ('', '.') and member.isdir():
                continue
            if (pure.is_absolute() or pure.as_posix() != name or '..' in pure.parts or '\\' in name
                    or name in seen or len(name.encode()) > 4096 or len(seen) >= MAX_MEMBERS):
                raise ValueError('Unsafe or duplicate root archive path')
            seen.add(name)
            size += member.size
            if size > MAX_ROOT_BYTES:
                raise ValueError('Expanded root archive exceeds budget')
            if name in directories:
                if not member.isdir():
                    raise ValueError('Linked or missing factory policy parent')
                directories[name] = True
            if (any(fnmatch.fnmatchcase(name, pattern)
                    or (pattern.startswith('**/') and fnmatch.fnmatchcase(name, pattern[3:]))
                    for pattern in inspect_root.FORBIDDEN)
                    or name.endswith('/authorized_keys')
                    or name == 'etc/apt/sources.list'
                    or (name.startswith('etc/apt/sources.list.d/') and not member.isdir())
                    or name in ('etc/resolv.conf', 'var/lib/dbus/machine-id',
                                'etc/apt/apt.conf.d/99mmdebstrap')):
                raise ValueError('Factory root retains temporary identity or build sources')
            if name in masks:
                if not member.issym() or member.linkname != '/dev/null':
                    raise ValueError('Missing experimental root safety mask')
                masks[name] = True
            if name in wanted:
                if (not member.isfile() or member.size > wanted[name] or member.uid != 0
                        or (name == 'etc/shadow' and member.mode & 0o027)):
                    raise ValueError('Invalid factory identity/package ledger entry')
                contents[name] = archive.extractfile(member).read(wanted[name]+1)
    if set(contents) != set(wanted) or not all(masks.values()) or not all(directories.values()):
        raise ValueError('Incomplete root audit inputs')
    if contents['etc/machine-id'] != b'' or contents['etc/hostname'] != b'zmala-unconfigured\n':
        raise ValueError('Factory root retains a machine identity')
    shadow = contents['etc/shadow'].decode('utf-8').splitlines()
    if not shadow or any(len(line.split(':')) != 9 or not line.split(':')[1].startswith(('!', '*')) for line in shadow):
        raise ValueError('Factory account is not password-locked')
    installed = base_intent.selections(contents['var/lib/dpkg/status'].decode('utf-8'))
    expected = sorted(name+'='+identity[0] for name, (identity, _, _) in selected.items())
    if installed != expected:
        raise ValueError('Built package ledger differs from reviewed selections')
    for record in package_lock.paragraphs(contents['var/lib/dpkg/status'].decode('utf-8')):
        if record['Architecture'] != selected[record['Package']][0][1]:
            raise ValueError('Built package architecture differs from its lock')
    return {'packages': len(installed), 'package_ledger_matches': True,
            'factory_identity_subset_checked': True, 'image_qualified': False}


def command(scratch, target, selected):
    include = ','.join(sorted(name+'='+identity[0] for name, (identity, _, _) in selected.items()))
    hook = (scratch/'root_cleanup.py').as_posix()
    return ['unshare', '--user', '--map-root-user', '--map-auto', '--net', '--mount', '--fork', '--kill-child=TERM',
            'mmdebstrap', '--mode=unshare', '--format=tar', '--variant=custom', '--architectures=arm64',
            '--hook-dir=/usr/share/mmdebstrap/hooks/file-mirror-automount',
            '--setup-hook='+hook+' setup "$1"', '--customize-hook='+hook+' clean "$1"',
            '--aptopt=APT::Install-Recommends "false"', '--aptopt=APT::Install-Suggests "false"',
            '--include='+include, 'trixie', target.as_posix(),
            'deb [trusted=yes] file:'+(scratch/'repo').as_posix()+' ./']


def emit_hook(scratch):
    """Normalize a Windows checkout before executing its Unix shebang."""
    hook = Path(scratch)/'root_cleanup.py'
    hook.write_text(Path(__file__).with_name('root_cleanup.py').read_text(encoding='utf-8'),
                    encoding='utf-8', newline='\n')
    hook.chmod(0o755)
    return hook


def build(role, base_cache, role_cache, output):
    if platform.system() != 'Linux' or os.geteuid() == 0:
        raise ValueError('Run as an ordinary Linux user with subordinate UID/GID namespace support')
    index = project.package_locks()
    project.profiles()['roles'][role]
    caches = [(base_cache, index['base']['lock_sha256']), (role_cache, index['roles'][role]['sha256'])]
    selected, locks = local_repo.inputs(caches)
    output = Path(output).absolute()
    if output.exists() or not re.fullmatch(r'/[A-Za-z0-9_./-]+', output.as_posix()):
        raise ValueError('Use a new simple absolute Linux build-output path')
    for tool in ('unshare', 'mmdebstrap', 'dpkg-scanpackages'):
        if not shutil.which(tool):
            raise ValueError('Missing build tool: '+tool)
    output.mkdir(parents=True)
    # Repository copies, bootstrap caches, expanded root and final tar can
    # coexist. Check both filesystems; /tmp need not share the output mount.
    if any(build_space.available(path) < MIN_BUILD_FREE_BYTES for path in (output, Path('/tmp'))):
        raise ValueError('At least 32 GiB free is required on both build and /tmp filesystems')
    scratch = Path(tempfile.mkdtemp(prefix='zmala-locked-root-', dir='/tmp'))
    # Only authenticated public archives and build hooks enter this workspace.
    # Namespace service UIDs must traverse it; private cache permissions stay put.
    local_repo.emit(caches, scratch/'repo')
    emit_hook(scratch)
    scratch.chmod(0o755)
    target = output/'root.tar'
    host_status = Path('/var/lib/dpkg/status')
    before = package_lock.digest(host_status)
    version = subprocess.check_output(['mmdebstrap', '--version'], text=True).strip()
    with (output/'build.log').open('x', encoding='utf-8') as log:
        subprocess.run(command(scratch, target, selected),
                       env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'SOURCE_DATE_EPOCH': SOURCE_DATE_EPOCH},
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=3600)
    if package_lock.digest(host_status) != before:
        raise ValueError('Host package database changed during isolated root construction')
    result = audit(target, selected)
    result.update(schema=1, purpose='unqualified-locked-arm64-root', role=role,
                  lock_sha256=locks, root_tar_sha256=package_lock.digest(target),
                  root_tar_bytes=target.stat().st_size, host_dpkg_unchanged=True,
                  bootstrap_version=version, source_date_epoch=SOURCE_DATE_EPOCH,
                  application_installed=False, toolchain_fully_locked=False,
                  runtime_mount_policy_installed=False, hardware_boot_verified=False)
    # Keep the public scratch and log for diagnosis; no recursive host deletion.
    # This marker appears only after the ledger and selected privacy checks pass.
    (output/'READY.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    return result
