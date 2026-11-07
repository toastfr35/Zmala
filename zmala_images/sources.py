"""Acquire immutable upstream sources for isolated image experiments, not targets."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import stat
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MAX_ARCHIVE = 32*1024*1024
MAX_TREE = 160*1024*1024
MAX_MEMBERS = 10000
SOURCE_NAMES = ('imagegen', 'backend_audit', 'bootloader_audit')
# The reviewed U-Boot archive is 46.7 MB / 264.7 MB expanded / 41,465 entries.
# Keep the smaller sources' original budgets; this is not a global relaxation.
BOOTLOADER_LIMITS = {'archive': 64*1024*1024, 'tree': 384*1024*1024, 'members': 50000}


def pins():
    value = json.loads((ROOT/'zmala_images/sources.lock.json').read_text())
    if value['schema'] != 1 or set(value) != {'schema', *SOURCE_NAMES}:
        raise ValueError('Unknown source lock schema')
    for name in SOURCE_NAMES:
        pin = value[name]
        if (set(pin) != {'repository', 'commit', 'sha256'}
                or not re.fullmatch(r'[A-Za-z0-9_-]+/[A-Za-z0-9_-]+', pin['repository'])
                or not re.fullmatch('[a-f0-9]{40}', pin['commit'])
                or not re.fullmatch('[a-f0-9]{64}', pin['sha256'])):
            raise ValueError('Invalid immutable source pin')
    return value


def verify_tree(folder, manifest):
    """Fail if cached source bytes or paths change; a marker alone is not trust."""
    expected = set(manifest)
    actual = set()
    for path in folder.rglob('*'):
        name = path.relative_to(folder).as_posix()
        if path.is_symlink():
            actual.add(name)
            if manifest.get(name) != {'link': os.readlink(path)}:
                raise ValueError('Source link changed')
            continue
        if path.is_file():
            actual.add(name)
            if name not in expected or hashlib.sha256(path.read_bytes()).hexdigest() != manifest[name]:
                raise ValueError('Source tree does not match verified archive')
    if actual != expected:
        raise ValueError('Incomplete source tree')


def unpack(archive, destination, *, max_tree=None, max_members=None):
    """Extract files and contained relative links, never devices or hard links."""
    destination = Path(destination)
    max_tree = MAX_TREE if max_tree is None else max_tree
    max_members = MAX_MEMBERS if max_members is None else max_members
    if type(max_tree) is not int or type(max_members) is not int or min(max_tree, max_members) < 1:
        raise ValueError('Invalid source extraction budget')
    if destination.exists():
        raise ValueError('Source destination already exists')
    with tarfile.open(archive, 'r:gz') as tar:
        names, roots, total, files, links = set(), set(), 0, [], []
        for count, member in enumerate(tar, start=1):
            if count > max_members:
                raise ValueError('Too many source entries')
            raw = member.name
            parts = PurePosixPath(raw).parts
            if (not parts or raw.startswith('/') or '\\' in raw or '..' in parts
                    or any(':' in p or p.rstrip(' .') != p for p in parts)
                    or not (member.isdir() or member.isfile() or member.issym())):
                raise ValueError('Unsafe source archive member')
            roots.add(parts[0])
            name = '/'.join(parts[1:])
            if name in names or (not name and not member.isdir()):
                raise ValueError('Duplicate or invalid source member')
            names.add(name)
            total += member.size
            if total > max_tree or member.size > MAX_ARCHIVE:
                raise ValueError('Source archive exceeds extraction budget')
            if member.isfile():
                files.append((member, name))
            elif member.issym():
                link = member.linkname
                resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), link))
                if (not link or link.startswith('/') or '\\' in link or ':' in link
                        or resolved == '..' or resolved.startswith('../')):
                    raise ValueError('Source link escapes tree')
                links.append((name, link))
        if len(roots) != 1 or not files:
            raise ValueError('Expected one upstream source tree')
        if any(other.startswith(name+'/') for name, _ in links for other in names):
            raise ValueError('Source member descends through a link')
        destination.mkdir(parents=True)
        manifest = {}
        for member, name in files:
            target = destination/name
            target.parent.mkdir(parents=True, exist_ok=True)
            data = tar.extractfile(member).read()
            target.write_bytes(data)
            target.chmod(0o755 if member.mode & 0o111 else 0o644)
            manifest[name] = hashlib.sha256(data).hexdigest()
        # Links are installed last, so no file write can traverse one. Linux is
        # the supported build host; Windows may require Developer Mode for links.
        for name, link in links:
            target = destination/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(link)
            manifest[name] = {'link': link}
    return manifest


def acquire(name, cache, opener=urllib.request.urlopen):
    pin = pins()[name]
    archive_limit = BOOTLOADER_LIMITS['archive'] if name == 'bootloader_audit' else MAX_ARCHIVE
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache/(name+'-'+pin['commit']+'.tar.gz')
    if not archive.exists():
        url = 'https://codeload.github.com/'+pin['repository']+'/tar.gz/'+pin['commit']
        # codeload is fixed by reviewed pins; no target credentials are supplied.
        with opener(url, timeout=60) as response:
            if response.geturl() != url:
                raise ValueError('Unexpected source download redirect')
            data = response.read(archive_limit+1)
        if len(data) > archive_limit:
            raise ValueError('Source download exceeds budget')
        if hashlib.sha256(data).hexdigest() != pin['sha256']:
            raise ValueError('Source download hash mismatch')
        with archive.open('xb') as stream:
            stream.write(data)
    info = archive.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > archive_limit:
        raise ValueError('Cached source hash mismatch or non-regular archive')
    with archive.open('rb') as stream:
        cached = stream.read(archive_limit+1)
    if len(cached) > archive_limit or hashlib.sha256(cached).hexdigest() != pin['sha256']:
        raise ValueError('Cached source hash mismatch')
    destination = cache/(name+'-'+pin['commit'])
    # Re-extraction is deliberately explicit, avoiding untrusted stale checkouts.
    budgets = ({'max_tree': BOOTLOADER_LIMITS['tree'], 'max_members': BOOTLOADER_LIMITS['members']}
               if name == 'bootloader_audit' else {})
    manifest = unpack(archive, destination, **budgets)
    verify_tree(destination, manifest)
    return destination
