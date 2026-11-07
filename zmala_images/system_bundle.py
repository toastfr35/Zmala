"""Prepare slot-specific RAUC inputs from an independently verified image.

Signing and publication are separate release operations. No block device is
opened and the common boot area and persistent data are excluded.
"""
import argparse
import hashlib
from pathlib import Path

from zmala_system import boot_capacity, boot_media, update_discovery
from . import image_assembly, package_lock


def copy_extent(stream, row, target):
    stream.seek(row['first_lba']*512)
    remaining = row['bytes']
    digest = hashlib.sha256()
    with target.open('xb') as output:
        while remaining:
            block = stream.read(min(4*1024**2, remaining))
            if not block:
                raise ValueError('Short appliance image partition')
            digest.update(block)
            if block.count(0) == len(block):
                output.seek(len(block), 1)
            else:
                output.write(block)
            remaining -= len(block)
        output.truncate(row['bytes'])
    return digest.hexdigest()


def manifest(slot, system, terminal):
    update_discovery.version(system)
    update_discovery.version(terminal)
    return (f'[update]\ncompatible={update_discovery.compatible(slot)}\nversion={system}\n'
            '\n[bundle]\nformat=verity\n'
            '\n[image.boot]\nfilename=boot.vfat\n'
            '\n[image.rootfs]\nfilename=root.ext4\n'
            f'\n[meta.zmala]\nterminal-version={terminal}\n')


def prepare(source, expected, output):
    source, output = Path(source).absolute(), Path(output).absolute()
    record = image_assembly.component(source, expected)
    if record.get('role') != 'terminal' or record.get('complete_disk_layout') is not True:
        raise ValueError('Expected a complete standalone Terminal appliance image')
    system, terminal = record['image_version'], record['components']['terminal']['version']
    manifests = {slot: manifest(slot, system, terminal) for slot in ('A', 'B')}
    image = image_assembly.regular(source/'appliance.img', record['image_sha256'])
    if output.exists() or output.resolve() != output or output.is_relative_to(source):
        raise ValueError('Use a new absolute output directory outside the source image')
    result = {}
    with image.open('rb') as stream:
        table = boot_media.inspect(stream, image.stat().st_size)
        boot_media.environment_ranges(table)
        rows = table['partitions']
        if table['sector_bytes'] != 512 or tuple(row['bytes'] for row in rows) != boot_capacity.SIZES:
            raise ValueError('Expected the fixed compact appliance layout')
        output.mkdir()
        for index, slot in enumerate(('A', 'B')):
            directory = output/slot
            directory.mkdir()
            result[slot] = {name: copy_extent(stream, rows[partition+index], directory/name)
                            for name, partition in (('boot.vfat', 1), ('root.ext4', 3))}
    if package_lock.digest(image) != record['image_sha256']:
        raise ValueError('Source image changed during extraction')
    for slot, body in manifests.items():
        (output/slot/'manifest.raucm').write_text(body, encoding='ascii', newline='\n')
    return result


def main():
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True, type=Path)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.image, args.manifest_sha256, args.output), indent=2))


if __name__ == '__main__':
    main()
