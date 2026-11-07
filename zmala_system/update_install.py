"""Install the exact verified update into the inactive boot/root pair."""
import hashlib
import os
from pathlib import Path
import shutil
import stat
import subprocess
import time

from . import boot_capacity, boot_devices, boot_environment, boot_media, host_layout, update_discovery

MAX_BUNDLE = 2*1024**3
RESERVE = 256*1024**2
RUNTIME = Path('/run/zmalacall-updater')
CONFIG = RUNTIME/'rauc.conf'
BACKEND = '/usr/lib/zmala/bin/boot-backend'


# @llr LLR-TERM-MAINT-062
def download(slot, path, *, opener=None, clock=time.monotonic):
    url = update_discovery.bundle_url(slot)
    opener = opener or update_discovery.release_opener()
    deadline = clock()+900
    with opener.open(url, timeout=15) as response:
        update_discovery.check_url(response.geturl())
        length = int(response.headers.get('Content-Length', '0'))
        if response.status != 200 or not 0 < length <= MAX_BUNDLE or shutil.disk_usage(path.parent).free < length+RESERVE:
            raise ValueError('Bundle size or free space is outside its budget')
        with path.open('xb') as output:
            remaining = length
            while remaining:
                if clock() >= deadline:
                    raise TimeoutError('System release transfer timed out')
                block = response.read(min(1024**2, remaining))
                if not block:
                    raise ValueError('Truncated system release transfer')
                output.write(block)
                remaining -= len(block)
            if response.read(1):
                raise ValueError('Oversized system release transfer')
            output.flush()
            os.fsync(output.fileno())


# @llr LLR-TERM-MAINT-062
def devices(environment, current):
    system, root, data, disk, identity = environment.storage
    sectors = boot_devices.positive(boot_devices.read(root.parent/'size').decode().strip(), 2**63//512-1)
    fd = os.open(disk, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb', buffering=0) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISBLK(info.st_mode) or info.st_rdev != os.makedev(*map(int, root.parent_device.split(':'))):
            raise ValueError('System update media identity changed')
        table = boot_media.inspect(stream, sectors*512)
    boot_capacity.layout(table, root.number, identity, system.probe(data)['PART_ENTRY_UUID'])
    result = {}
    mounted = {mount.device for mount in system.facts().values()}
    for slot, numbers in (('A', (2, 4)), ('B', (3, 5))):
        for kind, number in zip(('boot', 'rootfs'), numbers):
            part = system.data_sibling(root, number)
            expected = table['partitions'][number-1]
            start = boot_devices.positive(boot_devices.read(part.parent/part.node.name/'start').decode().strip(), 2**63-1)
            if (part.number != number or part.sectors*512 != expected['bytes'] or start != expected['first_lba']
                    or (slot != current and part.device in mounted)):
                raise ValueError('A/B update target is mounted or has changed geometry')
            result[slot, kind] = part.node
    return result


def configuration(target, media, state):
    lines = [f'[system]\ncompatible={update_discovery.compatible(target)}', 'bootloader=custom',
             'activate-installed=false', 'bundle-formats=verity', f'data-directory={state}',
             f'\n[keyring]\npath=/{update_discovery.KEYRING}',
             f'\n[handlers]\nbootloader-custom-backend={BACKEND}']
    for index, slot in enumerate(('A', 'B')):
        lines += [f'\n[slot.rootfs.{index}]', f'device={media[slot, "rootfs"]}', 'type=ext4', f'bootname={slot}',
                  f'\n[slot.boot.{index}]', f'device={media[slot, "boot"]}', 'type=vfat', f'parent=rootfs.{index}']
    return '\n'.join(lines)+'\n'


def command(arguments, timeout=30):
    subprocess.run(arguments, check=True, timeout=timeout, stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   env={'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'LC_ALL': 'C'})


def stop_rauc(run=command):
    run(['/usr/bin/systemctl', 'stop', 'rauc.service'], timeout=65)
    CONFIG.unlink(missing_ok=True)


# @llr LLR-TERM-MAINT-062
def install(candidate, installed, state, *, run=command, inspect=update_discovery.inspect_release):
    """The image owner holds the maintenance fence until RAUC has exited."""
    target = candidate['target']
    archive = state/'candidate.raucb'
    archive.unlink(missing_ok=True)
    try:
        download(target, archive)
        if inspect(target, installed, source=str(archive)) != candidate:
            raise ValueError('Downloaded release differs from the authorized offer')
        with boot_environment.open_control() as (environment, current):
            control = environment.read()
            if (control.role != 'terminal' or current != control.confirmed or control.trial != '-'
                    or target == current):
                raise ValueError('Boot state no longer admits this target')
            media = devices(environment, current)
        stop_rauc(run)
        rauc_state = state/'rauc'
        rauc_state.mkdir(mode=0o700, exist_ok=True)
        host_layout.metadata(rauc_state.lstat(), mode=0o700, directory=True)
        boot_environment.private_file(CONFIG, configuration(target, media, rauc_state).encode())
        run(['/usr/bin/systemctl', 'start', 'rauc.service'], timeout=45)
        run(['/usr/bin/rauc', 'install', str(archive)], timeout=900)
    finally:
        stop_rauc(run)
        archive.unlink(missing_ok=True)
    with boot_environment.open_control() as (environment, current):
        if devices(environment, current) != media:
            raise ValueError('System update media changed after installation')
        verify_pair(candidate, media)


def verify_pair(candidate, media):
    # RAUC verifies the inputs. Read back the exact partition lengths before
    # publishing a trial, including the boot filesystem of the selected pair.
    for kind, identity in candidate['images'].items():
        path = media[candidate['target'], kind]
        with path.open('rb', buffering=0) as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != identity:
                raise ValueError('Installed system partition differs from its signed release')
