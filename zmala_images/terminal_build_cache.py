"""Exchange only the reviewed public Debian inputs for the hosted Terminal build."""
import argparse
import json
from pathlib import Path
import shutil
import tarfile

from . import package_lock, project


def inventory():
    index = project.package_locks()
    locks = {'base': (index['base']['lock_file'], index['base']['lock_sha256']),
             'terminal': (index['roles']['terminal']['file'], index['roles']['terminal']['sha256'])}
    files = {}
    for role, (name, _) in locks.items():
        lock = (project.ROOT/'zmala_images/locks'/name).read_bytes()
        metadata = json.loads(lock)
        entries = {'packages.lock.json': len(lock)}
        entries.update({'archives/'+row['archive']: row['bytes'] for row in metadata['packages']})
        entries.update({'keyrings/'+name+'.gpg': 4*1024**2 for name in metadata['keyrings']})
        entries.update({'apt/lists/'+row['file']: 4*1024**2 for row in metadata['repositories']})
        files.update({role+'/'+path: size for path, size in entries.items()})
    return locks, files


def pack(base, terminal, output):
    locks, files = inventory()
    caches = {'base': base, 'terminal': terminal}
    for role, cache in caches.items():
        package_lock.verify(cache, locks[role][1])
    with tarfile.open(output, 'x:') as archive:
        for name in sorted(files):
            role, path = name.split('/', 1)
            source = caches[role]/path
            entry = tarfile.TarInfo(name)
            entry.size = source.stat().st_size
            with source.open('rb') as stream:
                archive.addfile(entry, stream)


def unpack(source, output):
    locks, expected = inventory()
    limit = sum(expected.values()) + len(expected)*4096 + 10240
    if source.is_symlink() or not source.is_file() or not 0 < source.stat().st_size <= limit:
        raise ValueError('Expected a bounded regular build cache archive')
    output.mkdir()
    with tarfile.open(source, 'r:') as archive:
        for entry in archive:
            maximum = expected.pop(entry.name, 0)
            if not entry.isfile() or not 0 < entry.size <= maximum:
                raise ValueError('Unexpected or duplicate build cache member')
            destination = output/entry.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(entry) as stream, destination.open('xb') as target:
                shutil.copyfileobj(stream, target, 1024**2)
    if expected:
        raise ValueError('Incomplete build cache archive')
    for role, (_, digest) in locks.items():
        package_lock.verify(output/role, digest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('pack')
    for name in ('base', 'terminal', 'output'):
        create.add_argument(name, type=Path)
    restore = commands.add_parser('unpack')
    restore.add_argument('source', type=Path)
    restore.add_argument('output', type=Path)
    args = parser.parse_args()
    if args.command == 'pack':
        pack(args.base, args.terminal, args.output)
    else:
        unpack(args.source, args.output)


if __name__ == '__main__':
    main()
