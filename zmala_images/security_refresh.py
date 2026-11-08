"""Prepare a pinned package refresh when the Terminal has a new Debian security update."""
import argparse
import hashlib
import json
from pathlib import Path

from . import local_repo, package_lock, project, terminal_build_cache


def newer(version, previous):
    result = package_lock.run(['dpkg', '--compare-versions', version, 'gt', previous], check=False)
    if result.returncode not in (0, 1):
        raise ValueError('Invalid Debian package version')
    return result.returncode == 0


def security_updates(indexes, installed):
    result = {}
    for index in indexes:
        for package in package_lock.paragraphs(index):
            name, version = package['Package'], package['Version']
            if name in installed and newer(version, result.get(name, installed[name])):
                result[name] = version
    return result


def security_indexes(root):
    paths = package_lock.apt_run(root, [
        'apt-get', 'indextargets', '--format', '$(FILENAME)',
        'Identifier: Packages', 'Codename: trixie-security',
    ]).stdout.splitlines()
    if not paths:
        raise ValueError('No authenticated Debian security package index')
    for path in map(Path, paths):
        if path.parent != root/'apt/lists' or not path.name.startswith(
                'deb.debian.org_debian-security_dists_trixie-security_'):
            raise ValueError('Unexpected Debian security index path')
        yield package_lock.run(['/usr/lib/apt/apt-helper', 'cat-file', str(path)]).stdout


def lock_summary(path, manifest):
    return {'sha256': package_lock.digest(path), 'archives': len(manifest['packages']),
            'archive_bytes': sum(row['bytes'] for row in manifest['packages'])}


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8', newline='\n')


def refresh(work, baseline):
    work = work.resolve()
    work.mkdir()
    terminal_build_cache.unpack(baseline, work/'baseline')
    index = project.package_locks()
    folder = project.ROOT/'zmala_images/locks'
    base = json.loads((folder/'base.json').read_text())
    terminal = json.loads((folder/'terminal.json').read_text())
    installed = {row['package']: row['version'] for manifest in (base, terminal)
                 for row in manifest['packages']}
    keyrings = [work/'baseline/base/keyrings'/f'{name}.gpg' for name in ('debian', 'raspberrypi')]
    indexes = work/'indexes'
    package_lock.prepare(indexes, *keyrings)
    package_lock.apt_run(indexes, ['apt-get', 'update'])
    snapshot = package_lock.signed_indexes(indexes)
    changes = security_updates(security_indexes(indexes), installed)
    if not changes:
        print('No newer Debian security package in the Terminal package set.')
        return

    # Preserve the observed package names. Resolve compatible dependency closures
    # against the same signed snapshot for every role that shares the base.
    intent = {'base': [name.split('=')[0] for name in project.common_base(index)['requested']]}
    intent.update({role: project.packages(role) for role in index['roles']})
    manifests = {}
    for role, requested in intent.items():
        manifests[role] = package_lock.intake(requested, work/role, *keyrings)
        if manifests[role]['repositories'] != snapshot:
            raise ValueError('Package indexes changed during refresh; retry against a consistent snapshot')
    base_path = work/'base/packages.lock.json'
    for role in index['roles']:
        role_path = work/role/'packages.lock.json'
        selected, _ = local_repo.inputs([(work/'base', package_lock.digest(base_path)),
                                         (work/role, package_lock.digest(role_path))])
        if role == 'terminal':
            for name, version in changes.items():
                if name in selected and newer(version, selected[name][0][0]):
                    raise ValueError(f'Security package {name} is held below {version}')
            for name, previous in installed.items():
                if name in selected and newer(previous, selected[name][0][0]):
                    raise ValueError(f'Terminal package {name} would be downgraded')

    for role, manifest in manifests.items():
        source = work/role/'packages.lock.json'
        (folder/f'{role}.json').write_bytes(source.read_bytes())
        summary = lock_summary(source, manifest)
        if role == 'base':
            summary['lock_sha256'] = summary.pop('sha256')
            index['base'].update(summary)
        else:
            index['roles'][role].update(summary)
    write_json(folder/'index.json', index)
    project.package_locks()
    terminal_build_cache.pack(work/'base', work/'terminal', work/'ZmalaTerminal-Package-Cache.tar')
    terminal_build_cache.pack_caches({role: work/role for role in ('server', 'combined')},
                                    work/'ZmalaServer-Combined-Package-Caches.tar')
    identity = {'version': project.image_version(), 'packages': changes}
    change_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
    write_json(work/'security-updates.json', {'id': change_id, 'packages': changes})
    print(f'Refreshed locks for {len(changes)} newer Debian security packages.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('work', type=Path)
    parser.add_argument('baseline', type=Path)
    args = parser.parse_args()
    refresh(args.work, args.baseline)


if __name__ == '__main__':
    main()
