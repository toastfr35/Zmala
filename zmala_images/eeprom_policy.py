#!/usr/bin/env python3
"""Offline build hook: keep EEPROM updates outside the probe's scope.

This file is also copied verbatim into emitted imagegen project hooks. Keep it
self-contained: the builder need not have the Zmala Python package installed.
Masking the known OS service does not qualify arbitrary boot firmware payloads.
"""
import argparse
from pathlib import Path

UNIT = 'rpi-eeprom-update.service'
MASK = 'etc/systemd/system/'+UNIT
VENDOR = 'usr/lib/systemd/system/'+UNIT


def contained(root, name):
    """Never traverse image symlinks into the build host while checking policy."""
    path = root/name
    if any((root/parent).is_symlink() for parent in Path(name).parents if str(parent) != '.'):
        raise ValueError('Uninspectable EEPROM policy parent: '+name)
    return path


def violations(root):
    """Report the known service's policy without reading a linked unit target."""
    try:
        vendor = contained(root, VENDOR)
        mask = contained(root, MASK)
    except ValueError:
        return ['uninspectable-eeprom-policy']
    if mask.is_symlink() and mask.readlink().as_posix() == '/dev/null':
        return []
    if vendor.exists() or vendor.is_symlink() or mask.exists() or mask.is_symlink():
        return ['unmasked-eeprom-update-service']
    return []


def prepare(root):
    """Mask only the known service in an explicit offline imagegen root.

    Refuse the host root, linked parent directories, and replacement of an
    operator's override. Repeating the hook after a completed mask is harmless.
    No systemctl/chroot/service or EEPROM command is executed.
    """
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Expected an offline real imagegen root')
    root = root.resolve()
    if root == Path(root.anchor):
        raise ValueError('Refusing the host filesystem root')
    marker = contained(root, 'etc/rpi-image-gen')
    if marker.is_symlink() or not marker.is_dir():
        raise ValueError('Expected an imagegen root marker')
    unit = contained(root, VENDOR)
    if unit.is_symlink() or not unit.is_file():
        raise ValueError('Expected the known vendor EEPROM update unit')
    mask = contained(root, MASK)
    if mask.is_symlink() and mask.readlink().as_posix() == '/dev/null':
        return
    if mask.exists() or mask.is_symlink():
        raise ValueError('Refusing to replace an existing EEPROM unit override')
    mask.parent.mkdir(parents=True, exist_ok=True)
    mask.symlink_to('/dev/null')
    if violations(root):
        raise ValueError('EEPROM unit mask verification failed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    try:
        prepare(args.root)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print('Known EEPROM update unit masked in the offline probe root.')


if __name__ == '__main__':
    main()
