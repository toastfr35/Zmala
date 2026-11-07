"""Private namespace regular-file media assembler. No loop devices or mounts."""
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import uuid

from zmala_system import boot_capacity, boot_media, device_identity, host_storage
from . import factory_data, image_assembly, image_case, image_payload, inspect_boot, package_lock
from .initramfs_worker import unpack_root


def run(args, **kwargs):
    return subprocess.run([str(value) for value in args], check=True, timeout=600, **kwargs)


def payload(root, name, maximum=64*1024**2):
    path = host_storage.safe(root, name)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= maximum:
        raise ValueError('Missing or oversized regular boot payload: '+name)
    return path.read_bytes()


def sparse_copy(source, destination, offset, length):
    """Copy allocated extents, bounded to one partition of a new regular image."""
    if not stat.S_ISREG(source.lstat().st_mode) or source.stat().st_size != length:
        raise ValueError('Unexpected filesystem file footprint')
    if offset < boot_media.FIRST_PARTITION_BYTES or offset+length > os.fstat(destination.fileno()).st_size:
        raise ValueError('Filesystem copy exceeds image bounds')
    with source.open('rb') as stream:
        position = 0
        while position < length:
            try:
                start = os.lseek(stream.fileno(), position, os.SEEK_DATA)
                end = min(length, os.lseek(stream.fileno(), start, os.SEEK_HOLE))
            except OSError as error:
                if error.errno == errno.ENXIO:
                    break
                raise
            stream.seek(start); destination.seek(offset+start)
            remaining = end-start
            while remaining:
                chunk = stream.read(min(4*1024**2, remaining))
                if not chunk:
                    raise ValueError('Short filesystem extent')
                at = destination.tell()
                destination.write(chunk)
                destination.seek(at)
                if destination.read(len(chunk)) != chunk:
                    raise ValueError('Assembled image extent readback differs')
                remaining -= len(chunk)
            position = end


def worker(request_file):
    request_file = Path(request_file).absolute()
    request = json.loads(request_file.read_text())
    if os.geteuid() != 0 or any(os.readlink('/proc/self/ns/'+name) == original
                              for name, original in request['host_namespaces'].items()):
        raise ValueError('Expected isolated root-mapped user/mount/PID/network namespaces')
    inside, outside, length = map(int, Path('/proc/self/uid_map').read_text().splitlines()[0].split())
    if (inside, length) != (0, 1) or outside == 0:
        raise ValueError('Never run this worker with host root privileges')
    output = Path(request['output'])
    if output.resolve() != output or output != request_file.parent or output == Path('/'):
        raise ValueError('Invalid private output directory')
    source = image_assembly.regular(request['source'], request['sha256'])
    initramfs, loader = Path(request['initramfs']), Path(request['loader'])
    init = image_assembly.component(initramfs, request['initramfs_manifest'])
    load = image_assembly.component(loader, request['loader_manifest'])
    for name, digest in load['files'].items():
        image_assembly.regular(loader/name, digest)
    image_assembly.regular(initramfs/'initramfs.img', init['initramfs_sha256'])
    if not 0 < (initramfs/'initramfs.img').stat().st_size <= 48*image_payload.MIB:
        raise ValueError('Initramfs exceeds its reserved memory window')
    root = output/'root'; root.mkdir(mode=0o700)
    try:
        unpack_root(source, root)
        argon_one = image_case.selected(root, request['role'])
        common = output/'common'; common.mkdir()
        slot = output/'slot'; slot.mkdir()
        version = init['kernel_version']
        if '/' in version or version in ('', '.', '..'):
            raise ValueError('Invalid kernel version path')
        kernel = payload(root, 'boot/vmlinuz-'+version)
        if kernel != payload(root, 'boot/firmware/kernel8.img'):
            raise ValueError('Firmware kernel differs from matched module kernel')
        (slot/'Image').write_bytes(image_payload.kernel_image(kernel))
        shutil.copyfile(initramfs/'initramfs.img', slot/'initramfs.img')
        dtb = payload(root, 'usr/lib/modules/'+version+'/dtb/broadcom/bcm2711-rpi-4-b.dtb', 2*image_payload.MIB)
        overlay = payload(root, 'usr/lib/modules/'+version+'/dtb/overlays/vc4-kms-v3d-pi4.dtbo', image_payload.MIB)
        if dtb != payload(root, 'boot/firmware/bcm2711-rpi-4-b.dtb', 2*image_payload.MIB):
            raise ValueError('Firmware device tree differs from matched module device tree')
        (common/'bcm2711-rpi-4-b.dtb').write_bytes(dtb)
        (common/'overlays').mkdir(); (common/'overlays/vc4-kms-v3d-pi4.dtbo').write_bytes(overlay)
        # Raspberry Pi overlays have dormant fragments and firmware overrides;
        # use the locked target dtmerge, not generic libfdt overlay application.
        staging = host_storage.safe(root, 'tmp/zmala-image-dtb')
        staging.mkdir(mode=0o700)
        (staging/'base.dtb').write_bytes(dtb)
        (staging/'overlay.dtbo').write_bytes(overlay)
        run(['chroot', root, '/usr/bin/dtmerge', '/tmp/zmala-image-dtb/base.dtb',
             '/tmp/zmala-image-dtb/board.dtb', '/tmp/zmala-image-dtb/overlay.dtbo'])
        image_case.configure_tree(root, staging, argon_one, run)
        shutil.copyfile(staging/'board.dtb', slot/'board.dtb')
        shutil.rmtree(staging)
        if (slot/'board.dtb').stat().st_size+65536 > 2*image_payload.MIB:
            raise ValueError('Device tree exceeds its reserved memory window')
        for name in ('start4.elf', 'fixup4.dat'):
            (common/name).write_bytes(payload(root, 'usr/lib/raspi-firmware/'+name, 8*image_payload.MIB))
        shutil.copyfile(loader/'u-boot.bin', common/'u-boot.bin')
        (common/'config.txt').write_text('arm_64bit=1\nenable_uart=1\nauto_initramfs=0\nkernel=u-boot.bin\n'
                                        'dtoverlay=vc4-kms-v3d-pi4\nmax_framebuffers=2\ndisable_splash=1\n'
                                       + image_case.boot_parameters(argon_one))
        (output/'boot.cmd').write_text(image_payload.boot_script())
        run([loader/'mkimage', '-A', 'arm64', '-O', 'linux', '-T', 'script', '-C', 'none',
             '-n', 'Zmala development A/B', '-d', output/'boot.cmd', common/'boot.scr'])
        seed = output/'data'; seed.mkdir(mode=0o700)
        marker = seed/device_identity.FACTORY
        marker.write_bytes(factory_data.content(request['role'])); marker.chmod(0o600)
        image = output/'appliance.img'
        size = image_payload.disk_bytes(request['media_bytes'])
        with image.open('xb') as stream:
            stream.truncate(size)
        offset = boot_media.FIRST_PARTITION_BYTES
        rows = []
        for index, (label, count) in enumerate(zip(boot_media.LABELS, image_payload.SIZES)):
            rows.append({'label': label, 'offset': offset, 'bytes': count, 'uuid': str(uuid.uuid4()),
                         'type': 'EBD0A0A2-B9E5-4433-87C0-68B6B72699C7' if index < 3 else
                                 '0FC63DAF-8483-4772-8E79-3D69D8477DE4'})
            offset += count
        # Keep the first usable LBA immediately after the primary array so
        # Windows GPT recovery does not redirect the array into the boot gap.
        table = f'label: gpt\nunit: sectors\nfirst-lba: {boot_capacity.GPT_FIRST_USABLE}\n\n'+''.join(
            f'start={row["offset"]//512}, size={row["bytes"]//512}, type={row["type"]}, '
            f'uuid={row["uuid"]}, name="{row["label"]}"\n' for row in rows)
        run(['sfdisk', '--no-reread', '--no-tell-kernel', image], input=table, text=True)
        payload_hashes = {}
        with image.open('r+b') as destination:
            for index, row in enumerate(rows):
                volume = output/(row['label']+'.fs')
                with volume.open('xb') as stream:
                    stream.truncate(row['bytes'])
                if index < 3:
                    run(['mkfs.vfat', '-F', '16' if index == 0 else '32', '-n', row['label'].upper(), volume])
                    tree = common if index == 0 else slot
                    run(['mcopy', '-i', volume, '-s', *sorted(tree.iterdir()), '::/'])
                    for file in sorted(tree.rglob('*')):
                        if file.is_file():
                            name = file.relative_to(tree).as_posix()
                            result = run(['mtype', '-i', volume, '::/'+name], capture_output=True)
                            expected = package_lock.digest(file)
                            if hashlib.sha256(result.stdout).hexdigest() != expected:
                                raise ValueError('FAT payload readback differs')
                            payload_hashes[row['label']+'/'+name] = expected
                else:
                    tree = seed if index == 5 else root
                    run(['mkfs.ext4', '-q', '-F', '-b', '4096', '-m', '0', '-L', row['label'],
                         '-U', str(uuid.uuid4()), '-E', 'lazy_itable_init=0,lazy_journal_init=0',
                         '-d', tree, volume])
                    if index == 5:
                        # mke2fs -d copies children, but does not inherit the source root's mode.
                        run(['debugfs', '-w', '-R', 'set_inode_field / mode 040700', volume])
                    name = '/'+device_identity.FACTORY if index == 5 else '/usr/lib/zmala-application-build.json'
                    result = run(['debugfs', '-R', 'cat '+name, volume], capture_output=True)
                    if result.stdout != (tree/name.lstrip('/')).read_bytes():
                        raise ValueError('Ext4 payload readback differs')
                    metadata = run(['debugfs', '-R', 'stat /', volume], capture_output=True, text=True).stdout
                    if 'User:     0' not in metadata or (index == 5 and '0700' not in metadata):
                        raise ValueError('Ext4 root ownership or factory privacy differs')
                sparse_copy(volume, destination, row['offset'], row['bytes'])
            initial = (loader/'initial.env').read_text()
            for offset, flag in zip(boot_media.ENV_OFFSETS, (1, 0)):
                destination.seek(offset)
                destination.write(image_payload.environment(initial, request['role'], flag))
            destination.flush(); os.fsync(destination.fileno())
        geometry = inspect_boot.audit(image)
        with image.open('rb') as stream:
            boot_media.environment_ranges(boot_media.inspect(stream, size))
            _, header = boot_capacity.checked_header(stream, 1, size)
            if header['first'] != boot_capacity.GPT_FIRST_USABLE:
                raise ValueError('The assembled GPT did not retain its first usable LBA')
        result = {'schema': 1, 'role': request['role'], 'argon_one': argon_one,
                  'source_root_sha256': request['sha256'],
                  'initramfs_manifest_sha256': request['initramfs_manifest'],
                  'loader_manifest_sha256': request['loader_manifest'], 'kernel_version': version,
                  'image_bytes': size, 'image_sha256': package_lock.digest(image), 'partitions': rows,
                  'required_device_bytes': size, 'automatic_media_expansion': False,
                  'factory_gpt_relocation': True, 'data_partition_bytes': image_payload.SIZES[-1],
                  'boot_payloads': payload_hashes, 'geometry': geometry, 'application_installed': True,
                  'complete_disk_layout': True, 'hardware_boot_verified': False,
                  'joint_health_implemented': False, 'confirmed_boot_watchdog_enabled': False,
                  'boot_script_sha256': package_lock.digest(output/'boot.cmd'),
                  'builder_sha256': {file.name: package_lock.digest(file)
                                     for file in sorted(Path(__file__).parent.glob('*.py'))},
                  'production_qualified': False, 'toolchain_fully_locked': False}
        (output/'worker-result.json').write_text(json.dumps(result, indent=2)+'\n')
    finally:
        if root.resolve() == root and root.parent == output:
            shutil.rmtree(root)


if __name__ == '__main__':
    worker(sys.argv[1])
