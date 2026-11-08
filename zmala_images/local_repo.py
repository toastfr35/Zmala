"""Assemble a build-only file repository from externally anchored intake caches.

No host APT configuration or package state is changed. The generated unsigned
repository is trusted only as a local, verified build input. It must never be
served as an authenticated remote repository or shipped as a device source.
"""
import gzip
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess

from . import base_intent, package_lock

MAX_INDEX_BYTES = 64*1024**2


def inputs(caches):
    """Verify all inputs before output creation; never choose between conflicts."""
    if not 0 < len(caches) <= 3:
        raise ValueError('Supply one to three reviewed package caches')
    selected, names, total, locks = {}, {}, 0, []
    for folder, expected in caches:
        folder = Path(folder)
        manifest = package_lock.verify(folder, expected)
        locks.append(expected)
        for record in manifest['packages']:
            name, version, arch = record['package'], record['version'], record['architecture']
            if (not re.fullmatch(base_intent.NAME, name)
                    or not re.fullmatch(base_intent.VERSION, version)):
                raise ValueError('Invalid locked package identity')
            identity = (version, arch, record['sha256'])
            if name in selected:
                if selected[name][0] != identity:
                    raise ValueError('Conflicting locked package versions or contents: '+name)
                continue
            filename = record['archive']
            if filename in names:
                raise ValueError('Conflicting locked archive filename')
            names[filename] = name
            total += record['bytes']
            if total > package_lock.MAX_BYTES or len(selected) >= package_lock.MAX_PACKAGES:
                raise ValueError('Combined package repository exceeds budget')
            selected[name] = (identity, folder/'archives'/filename, record)
    return selected, sorted(set(locks))


def role_inputs(role, caches):
    """The shared lock is authenticated before applying the Server package policy."""
    selected, locks = inputs(caches)
    if role == 'server':
        selected.pop('rauc', None)
    return selected, locks


def audit_index(text, selected):
    """Compare archive identities and generated paths/hashes with reviewed inputs."""
    seen = set()
    for record in package_lock.paragraphs(text):
        name = record.get('Package')
        if name not in selected or name in seen:
            raise ValueError('Generated repository package set differs from its locks')
        _, _, expected = selected[name]
        fields = {'Version': expected['version'], 'Architecture': expected['architecture'],
                  'Filename': 'pool/'+expected['archive'], 'Size': str(expected['bytes']),
                  'SHA256': expected['sha256']}
        if any(record.get(key) != value for key, value in fields.items()):
            raise ValueError('Archive control identity differs from its lock: '+name)
        seen.add(name)
    if seen != set(selected):
        raise ValueError('Generated repository is incomplete')


def emit(caches, output, *, role=None):
    if platform.system() != 'Linux':
        raise ValueError('Local repository assembly requires Linux dpkg-scanpackages')
    selected, locks = role_inputs(role, caches)
    output = Path(output).absolute()
    if output.exists():
        raise ValueError('Use a new local repository directory')
    # A stable source line must not admit whitespace or APT option injection.
    if not re.fullmatch(r'/[A-Za-z0-9_./-]+', output.as_posix()):
        raise ValueError('Repository path must contain only simple absolute path characters')
    output.mkdir(parents=True)
    if shutil.disk_usage(output).free < sum(r['bytes'] for _, _, r in selected.values())+128*1024**2:
        raise ValueError('Not enough space for the verified local repository')
    pool = output/'pool'
    pool.mkdir()
    for _, archive, record in selected.values():
        target = pool/archive.name
        # Copy, never hard-link mutable cache inputs into a supposedly fixed repo.
        shutil.copyfile(archive, target)
        if target.stat().st_size != record['bytes'] or package_lock.digest(target) != record['sha256']:
            raise ValueError('Package changed while copying repository inputs')
    index = output/'Packages'
    # Bound captured output on disk; do not keep a potentially large index in
    # subprocess's stdout buffer. A failed/incomplete repo has no READY marker.
    with index.open('xb') as stream:
        subprocess.run(['dpkg-scanpackages', '--multiversion', 'pool', '/dev/null'],
                       cwd=output, stdout=stream, stderr=subprocess.PIPE, check=True,
                       timeout=600, env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
    if index.stat().st_size > MAX_INDEX_BYTES:
        raise ValueError('Generated repository index exceeds budget')
    audit_index(index.read_text(encoding='utf-8'), selected)
    with (output/'Packages.gz').open('xb') as stream:
        with gzip.GzipFile(filename='', fileobj=stream, mode='wb', mtime=0) as compressed:
            compressed.write(index.read_bytes())
    hashes = '\n'.join(f' {package_lock.digest(output/name)} {(output/name).stat().st_size} {name}'
                       for name in ('Packages', 'Packages.gz'))
    (output/'Release').write_text('Origin: Zmala verified local build inputs\n'
                                'Architectures: arm64 all\nSHA256:\n'+hashes+'\n', encoding='utf-8')
    source = 'deb [trusted=yes arch=arm64] file:'+output.as_posix()+' ./\n'
    (output/'build-only.list').write_text(source, encoding='utf-8')
    result = {'schema': 1, 'purpose': 'verified-local-build-repository',
              'lock_sha256': locks, 'packages': len(selected),
              'index_sha256': hashlib.sha256(index.read_bytes()).hexdigest(),
              'image_qualified': False, 'builder_consumption_verified': False}
    (output/'READY.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    return result
