"""Prepare experimental image-root storage before switching to the real root.

Inputs are already mounted/validated by the boot integration. This helper does
not select disks, generate device identities, initialize an empty data volume,
start services or implement an updater. Never run it against a live host root.
"""
import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import subprocess

from . import host_layout as layout


@dataclass(frozen=True)
class Mount:
    point: Path
    device: str
    flags: frozenset
    filesystem: str


# @llr LLR-SRV-HOST-009, LLR-TERM-MAINT-036
def mount_table(text):
    if len(text) > 1024**2:
        raise ValueError('Mount table exceeds its budget')
    result = {}
    for line in text.splitlines():
        fields = line.split()
        separator = fields.index('-')
        if separator < 6 or len(fields) < separator+4:
            raise ValueError('Invalid prepared-mount facts')
        point = re.sub(r'\\(040|011|012|134)', lambda m: chr(int(m[1], 8)), fields[4])
        # Refuse ambiguous stacked facts if that point is selected as an input;
        # unrelated automount stacks do not invalidate the whole namespace.
        flags = frozenset() if Path(point) in result else frozenset(fields[5].split(','))
        result[Path(point)] = Mount(Path(point), fields[2], flags, fields[separator+1])
    return result


class NativeMounts:
    """Only mount operations are permitted; no package/service/media commands."""

    @staticmethod
    def facts():
        with Path('/proc/self/mountinfo').open(encoding='utf-8') as stream:
            return mount_table(stream.read(1024**2+1))

    # @llr LLR-SRV-HOST-012, LLR-TERM-MAINT-039
    @staticmethod
    def run(arguments):
        if arguments[0] not in ('mount', 'umount'):
            raise ValueError('Unsupported storage operation')
        return subprocess.run(arguments, check=True, capture_output=True, text=True, timeout=30,
                              env={'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'LC_ALL': 'C'})


def safe(root, name):
    relative = PurePosixPath(name)
    if relative.is_absolute() or '..' in relative.parts or relative.as_posix() != name:
        raise ValueError('Unsafe image-state path')
    path = root/name
    for part in (relative, *relative.parents):
        if str(part) != '.' and (root/str(part)).is_symlink():
            raise ValueError('Linked image-state path')
    return path


def read_record(root, name, mode, limit):
    path = safe(root, name)
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    with os.fdopen(os.open(path, flags), 'rb') as stream:
        info = os.fstat(stream.fileno())
        layout.metadata(info, mode=mode)
        if info.st_size > limit or info.st_nlink != 1:
            raise ValueError('Image-state record exceeds its budget or has linked content')
        body = stream.read(limit+1)
    if len(body) > limit:
        raise ValueError('Image-state record grew beyond its budget')
    return body


# @llr LLR-SRV-HOST-021, LLR-TERM-MAINT-048
def canonical(path):
    path = Path(path)
    if (not path.is_absolute() or not re.fullmatch(r'/[A-Za-z0-9_./-]*', path.as_posix())
            or path.resolve() != path):
        raise ValueError('Expected a simple canonical absolute image path')
    return path


# @llr LLR-SRV-HOST-010, LLR-TERM-MAINT-037
def seed_entries(root):
    seed = safe(root, layout.VAR_SEED)
    layout.metadata(seed.lstat(), directory=True)
    package = safe(root, layout.PACKAGE_DB+'/status')
    layout.metadata(package.lstat())
    if not 0 < package.stat().st_size <= 16*1024**2:
        raise ValueError('Missing or oversized slot-local package status')
    link = seed/'lib/dpkg'
    if ((seed/'lib').is_symlink() or not link.is_symlink()
            or link.readlink().as_posix() != '/'+layout.PACKAGE_DB):
        raise ValueError('Variable-state seed does not reference its slot package database')
    entries, total, pending = [], 0, [seed]
    while pending:
        directory = pending.pop()
        for path in sorted(directory.iterdir()):
            info = path.lstat()
            if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)):
                raise ValueError('Special file in the variable-state seed')
            total += info.st_size if stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) else 0
            if total > layout.MAX_SEED_BYTES or len(entries) >= layout.MAX_SEED_ENTRIES:
                raise ValueError('Variable-state seed exceeds its RAM budget')
            entries.append((path.relative_to(seed), info))
            if stat.S_ISLNK(info.st_mode):
                relative = path.relative_to(seed).as_posix()
                link_target = path.readlink().as_posix()
                layout.seed_link(relative, link_target)
            if stat.S_ISDIR(info.st_mode):
                pending.append(path)
    return entries


@dataclass
class Context:
    root: Path
    data: Path
    area: Path
    role: str
    seed: list


# @llr LLR-SRV-HOST-009, LLR-TERM-MAINT-036
def context(root, data, area, role, facts):
    root, data, area = map(canonical, (root, data, area))
    if root == Path('/') or data == Path('/') or root == data or area.exists() or area.is_symlink():
        raise ValueError('Unsupported host root or conflicting RAM working area')
    if ((data.is_relative_to(root) and data != root/'data')
            or (area.is_relative_to(root) and not area.is_relative_to(root/'run'))):
        raise ValueError('Prepared data or RAM area would cover image policy')
    if any(point.is_relative_to(root/name) for point in facts for name in ('etc', 'usr', 'var', 'tmp')):
        raise ValueError('Unexpected existing mount inside an image policy tree')
    for name in ('etc', 'var', 'tmp'):
        target = safe(root, name)
        layout.metadata(target.lstat(), directory=True)
        if target in facts or data.is_relative_to(target) or area.is_relative_to(target):
            raise ValueError('Image views conflict with prepared mounts')
    if area.is_relative_to(data) or data.is_relative_to(area):
        raise ValueError('RAM work and persistent data must be separate')
    root_mount, data_mount = facts.get(root), facts.get(data)
    ram_mounts = [m for point, m in facts.items() if area.parent.is_relative_to(point)]
    ram = max(ram_mounts, key=lambda m: len(m.point.parts)) if ram_mounts else None
    if (not root_mount or 'ro' not in root_mount.flags or root_mount.filesystem != 'ext4'
            or not data_mount or 'rw' not in data_mount.flags or data_mount.filesystem != 'ext4'
            or root_mount.device == data_mount.device or not ram or 'rw' not in ram.flags
            or ram.filesystem not in ('tmpfs', 'ramfs')):
        raise ValueError('Expected a read-only image, separate writable ext4 data and RAM work parent')
    layout.metadata(data.lstat(), mode=0o700, directory=True)
    parent = area.parent.lstat()
    layout.metadata(parent, directory=True)
    if stat.S_IMODE(parent.st_mode) & 0o022:
        raise ValueError('RAM work parent is writable by another account')
    layout.decode_profile(read_record(root, layout.PROFILE, 0o644, layout.MAX_PROFILE_BYTES), role)
    layout.decode_profile(read_record(data, layout.DATA_MARKER, 0o600, layout.MAX_PROFILE_BYTES), role, data=True)
    for binding in layout.bindings(role):
        saved = safe(data, binding.saved)
        # Intermediate data namespaces are root-private. Missing directory
        # namespaces are created later, after every input has been validated.
        for relative in PurePosixPath(binding.saved).parents:
            if str(relative) != '.':
                parent = safe(data, str(relative))
                if parent.exists():
                    layout.metadata(parent.lstat(), mode=0o700, directory=True)
        if saved.exists():
            layout.metadata(saved.lstat(), binding.uid, binding.gid, binding.mode, binding.directory)
        elif not binding.directory:
            raise ValueError('Saved device identity has not been initialized')
        if not binding.directory:
            layout.identity(read_record(data, binding.saved, binding.mode, 128),
                            hostname=binding.target == 'etc/hostname')
    return Context(root, data, area, role, seed_entries(root))


# @llr LLR-SRV-HOST-011, LLR-TERM-MAINT-038
def saved_directory(data, binding):
    parts = PurePosixPath(binding.saved).parts
    for number in range(1, len(parts)+1):
        name = '/'.join(parts[:number])
        path = safe(data, name)
        final = number == len(parts)
        uid, gid, mode = ((binding.uid, binding.gid, binding.mode) if final else (0, 0, 0o700))
        if path.exists():
            layout.metadata(path.lstat(), uid, gid, mode, directory=True)
        else:
            path.mkdir(mode=mode)
            os.chown(path, uid, gid)
            path.chmod(mode)
    return data/binding.saved


# @llr LLR-SRV-HOST-010, LLR-TERM-MAINT-037
def copy_seed(current):
    source = current.root/layout.VAR_SEED
    target = current.root/'var'
    # Parent directories precede children in the scanned list. Never follow
    # vendor symlinks while copying, including the absolute package-db link.
    for relative, info in current.seed:
        original, destination = source/relative, target/relative
        if stat.S_ISDIR(info.st_mode):
            destination.mkdir()
        elif stat.S_ISLNK(info.st_mode):
            destination.symlink_to(original.readlink())
        else:
            shutil.copyfile(original, destination)
        os.chown(destination, info.st_uid, info.st_gid, follow_symlinks=False)
        if not stat.S_ISLNK(info.st_mode):
            destination.chmod(stat.S_IMODE(info.st_mode))


# @llr LLR-SRV-HOST-012, LLR-TERM-MAINT-039
class Prepared:
    def __init__(self, current, mounts):
        self.current, self.mounts, self.owned = current, mounts, []

    def mount(self, source, target, filesystem=None, options=None):
        args = (['mount', '-t', filesystem] if filesystem else ['mount'])
        args += ['-o', options, str(source), str(target)]
        try:
            self.mounts.run(args)
        except BaseException:
            # mount(8) can fail after creating a mount. Record that partial
            # success too, so cleanup does not leave a writable view behind.
            try:
                present = target in self.mounts.facts()
            except BaseException:
                present = True  # Reinspect this possible partial mount during cleanup.
            if present:
                self.owned.append(target)
            raise
        self.owned.append(target)

    def close(self):
        errors, remaining = [], []
        for target in reversed(self.owned):
            try:
                if target in self.mounts.facts():
                    self.mounts.run(['umount', str(target)])
            except BaseException as error:
                errors.append(error)
                remaining.append(target)
        self.owned = list(reversed(remaining))
        try:
            self.current.area.rmdir()
        except OSError:
            pass
        if errors:
            raise errors[0]


# @llr LLR-SRV-HOST-010, LLR-SRV-HOST-011, LLR-SRV-HOST-012, LLR-TERM-MAINT-037, LLR-TERM-MAINT-038, LLR-TERM-MAINT-039
def prepare(root, data, area, role, mounts=None):
    if platform.system() != 'Linux' or os.geteuid() != 0:
        raise ValueError('Host storage preparation requires a Linux boot/mount namespace root')
    mounts = mounts or NativeMounts()
    current = context(root, data, area, role, mounts.facts())
    # Exclusive creation rejects a competing or repeated invocation. This is
    # per-boot RAM state, never an updater lock stored on the SD card.
    current.area.mkdir(mode=0o700)
    prepared = Prepared(current, mounts)
    try:
        prepared.mount('tmpfs', current.area, 'tmpfs', 'mode=0700,nodev,nosuid,size=64M')
        (current.area/'etc-upper').mkdir()
        (current.area/'etc-work').mkdir()
        for filesystem, source, target, options in layout.volatile_mounts(current.root, current.area):
            prepared.mount(source, target, filesystem, options)
            if target == current.root/'var':
                copy_seed(current)
        for binding in layout.bindings(role):
            saved = saved_directory(current.data, binding) if binding.directory else safe(current.data, binding.saved)
            target = safe(current.root, binding.target)
            target.parent.mkdir(parents=True, exist_ok=True)
            if binding.directory:
                target.mkdir(exist_ok=True)
            elif not target.exists():
                target.touch()
            target_mode = target.lstat().st_mode
            if not (stat.S_ISDIR(target_mode) if binding.directory else stat.S_ISREG(target_mode)):
                raise ValueError('Persistent binding target has the wrong type')
            prepared.mount(saved, target, options='bind')
            if binding.readonly:
                mounts.run(['mount', '-o', 'remount,bind,ro,nodev,nosuid', str(target)])
        status = {'schema': 1, 'role': role, 'storage_prepared': True}
        # Publish only after the complete status file is flushed and closed.
        # A failed write/fsync must never leave a parseable success marker.
        staging = current.area/'ready.next'
        with staging.open('x', encoding='utf-8') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(status, stream)
            stream.flush()
            os.fsync(stream.fileno())
        staging.replace(current.area/'ready.json')
        return prepared
    except BaseException:
        for name in ('ready.next', 'ready.json'):
            try:
                (current.area/name).unlink(missing_ok=True)
            except BaseException:
                pass
        try:
            prepared.close()
        except BaseException:
            pass  # Preserve the preparation failure, not a later cleanup error.
        raise


# @llr LLR-SRV-HOST-012, LLR-TERM-MAINT-039
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--data', required=True, type=Path)
    parser.add_argument('--role', required=True, choices=layout.ROLES)
    parser.add_argument('--runtime-area', type=Path, default=Path('/run/zmala-host'))
    args = parser.parse_args()
    try:
        prepare(args.root, args.data, args.runtime_area, args.role)
    except (OSError, ValueError, subprocess.SubprocessError):
        parser.error('Host storage preparation failed; normal startup must remain fenced.')
    print('Image-managed host storage prepared.')


if __name__ == '__main__':
    main()
