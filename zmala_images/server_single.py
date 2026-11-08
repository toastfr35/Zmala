"""Build a native Raspberry Pi Server image from the verified application root."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

from . import image_assembly, local_repo, package_lock, project, root_build
from .image_worker import payload, run, sparse_copy
from .initramfs_worker import firmware_kernel_version, unpack_root
from zmala_system import host_storage

MIB = 1024**2
BOOT_OFFSET = 8 * MIB
BOOT_BYTES = 512 * MIB
ROOT_OFFSET = BOOT_OFFSET + BOOT_BYTES
IMAGE_BYTES = 8 * 1024**3
FIRMWARE_FILES = ('config.txt', 'cmdline.txt', 'start4.elf', 'fixup4.dat',
                  'kernel8.img', 'initramfs8', 'bcm2711-rpi-4-b.dtb')


def boot_configuration(signature):
    if not re.fullmatch('[0-9a-f]{8}', signature) or signature == '00000000':
        raise ValueError('Invalid MBR disk signature')
    boot, root = (f'PARTUUID={signature}-{number:02d}' for number in (1, 2))
    config = 'arm_64bit=1\nkernel=kernel8.img\ninitramfs initramfs8 followkernel\n'
    cmdline = f'console=tty1 root={root} rootfstype=ext4 rootwait rw net.ifnames=0\n'
    fstab = f'{root} / ext4 defaults,noatime 0 1\n{boot} /boot/firmware vfat defaults 0 2\n'
    return config, cmdline, fstab


def configure(root, firmware, signature):
    version = firmware_kernel_version(root)
    dtb = f'usr/lib/modules/{version}/dtb/broadcom/bcm2711-rpi-4-b.dtb'
    for copied, original in (('initramfs8', 'boot/initrd.img-'+version), ('bcm2711-rpi-4-b.dtb', dtb)):
        if payload(root, 'boot/firmware/'+copied, 128*MIB) != payload(root, original, 128*MIB):
            raise ValueError('Raspberry Pi boot payload differs from the selected kernel: '+copied)
    for name in ('etc/systemd/system/rauc.service', 'usr/lib/systemd/system/rauc.service',
                 'usr/bin/rauc', 'usr/lib/zmala/system-update-keyring.pem'):
        path = root/name
        if path.exists() or path.is_symlink():
            raise ValueError('Found RAUC or the system update service in the Server root')
    boot = host_storage.safe(root, 'boot/firmware')
    if any(not (path.is_file() or path.is_dir()) or path.is_symlink() for path in boot.rglob('*')):
        raise ValueError('Unexpected firmware tree member')
    boot.rename(firmware)
    boot.mkdir(mode=0o755)
    config, cmdline, fstab = boot_configuration(signature)
    for path, value in ((firmware/'config.txt', config), (firmware/'cmdline.txt', cmdline),
                        (host_storage.safe(root, 'etc/fstab'), fstab),
                        (host_storage.safe(root, 'etc/hostname'), 'zmalaserver\n')):
        path.write_text(value, encoding='ascii')
    hosts = host_storage.safe(root, 'etc/hosts')
    hosts.write_text('127.0.0.1 localhost\n127.0.1.1 zmalaserver\n::1 localhost ip6-localhost ip6-loopback\n',
                     encoding='ascii')
    for unit, target in (('NetworkManager.service', 'multi-user'), ('systemd-resolved.service', 'sysinit'),
                         ('avahi-daemon.service', 'multi-user')):
        service = 'usr/lib/systemd/system/'+unit
        if not (root/service).is_file():
            raise ValueError('Missing Server networking unit: '+unit)
        link = host_storage.safe(root, f'etc/systemd/system/{target}.target.wants')/unit
        link.parent.mkdir(parents=True, exist_ok=True)
        if not link.is_symlink():
            link.symlink_to('/'+service)
        elif link.readlink() != Path('/'+service):
            raise ValueError('Unexpected Server networking unit link: '+unit)
    host_storage.safe(root, 'etc/resolv.conf').symlink_to('/run/systemd/resolve/stub-resolv.conf')
    apt = host_storage.safe(root, 'etc/apt/sources.list.d/zmala-server.sources')
    sources = [
        ('https://deb.debian.org/debian', 'trixie trixie-updates', 'main contrib non-free non-free-firmware',
         'debian-archive-keyring.gpg'),
        ('https://deb.debian.org/debian-security', 'trixie-security', 'main contrib non-free non-free-firmware',
         'debian-archive-keyring.gpg'),
        ('https://archive.raspberrypi.com/debian', 'trixie', 'main', 'raspberrypi-archive-keyring.gpg'),
    ]
    entries = []
    for uri, suites, components, key in sources:
        key_path = 'usr/share/keyrings/'+key
        keyring = root/key_path
        if keyring.is_symlink():
            target = keyring.readlink()
            if target != Path(key).with_suffix('.pgp'):
                raise ValueError('Unexpected archive keyring link')
            payload(root, str(Path(key_path).with_suffix('.pgp')), MIB)
        else:
            payload(root, key_path, MIB)
        entries.append(f'Types: deb\nURIs: {uri}\nSuites: {suites}\nComponents: {components}\nSigned-By: /{key_path}\n')
    apt.write_text('\n'.join(entries), encoding='ascii')
    return version


def worker(request_file):
    request_file = Path(request_file).absolute()
    request = json.loads(request_file.read_text())
    if os.geteuid() != 0 or set(request['namespaces']) != {'user', 'mnt', 'pid', 'net'} or any(
            os.readlink('/proc/self/ns/'+name) == value for name, value in request['namespaces'].items()):
        raise ValueError('Server assembly needs isolated user, mount, PID and network namespaces')
    inside, outside, length = map(int, Path('/proc/self/uid_map').read_text().splitlines()[0].split())
    if (inside, length) != (0, 1) or outside == 0:
        raise ValueError('Server assembly requires subordinate UID mappings')
    output = request_file.parent
    if output.resolve() != output or output == Path('/'):
        raise ValueError('Invalid Server assembly directory')
    source = image_assembly.regular(request['source'], request['sha256'])
    root = output/'root'
    root.mkdir(mode=0o700)
    try:
        unpack_root(source, root)
        firmware = output/'firmware'
        signature = f'{uuid.uuid4().int % (2**32 - 1) + 1:08x}'
        version = configure(root, firmware, signature)
        boot, system, image = (output/name for name in ('boot.fs', 'root.fs', 'server.img'))
        for path, size in ((boot, BOOT_BYTES), (system, IMAGE_BYTES-ROOT_OFFSET), (image, IMAGE_BYTES)):
            with path.open('xb') as stream:
                stream.truncate(size)
        run(['mkfs.vfat', '-F', '32', '-n', 'bootfs', boot])
        run(['mcopy', '-i', boot, '-s', *sorted(firmware.iterdir()), '::/'])
        for name in FIRMWARE_FILES:
            read = run(['mtype', '-i', boot, '::/'+name], capture_output=True).stdout
            if read != payload(firmware, name, 128*MIB):
                raise ValueError('Boot partition differs from reviewed firmware payload: '+name)
        run(['mkfs.ext4', '-q', '-F', '-b', '4096', '-m', '0', '-L', 'rootfs',
             '-E', 'lazy_itable_init=0,lazy_journal_init=0', '-d', root, system])
        for name in ('etc/fstab', 'etc/hostname', 'usr/lib/zmala-application-build.json'):
            read = run(['debugfs', '-R', 'cat /'+name, system], capture_output=True).stdout
            if read != payload(root, name, MIB):
                raise ValueError('Root partition readback differs: '+name)
        table = (f'label: dos\nlabel-id: 0x{signature}\nunit: sectors\n\n'
                 f'start={BOOT_OFFSET//512}, size={BOOT_BYTES//512}, type=c, bootable\n'
                 f'start={ROOT_OFFSET//512}, size={(IMAGE_BYTES-ROOT_OFFSET)//512}, type=83\n')
        run(['sfdisk', '--no-reread', '--no-tell-kernel', image], input=table, text=True)
        with image.open('r+b') as stream:
            sparse_copy(boot, stream, BOOT_OFFSET, BOOT_BYTES)
            sparse_copy(system, stream, ROOT_OFFSET, IMAGE_BYTES-ROOT_OFFSET)
            stream.flush()
            os.fsync(stream.fileno())
        run(['sfdisk', '--verify', image])
        geometry = json.loads(run(['sfdisk', '--json', image], capture_output=True).stdout)['partitiontable']
        parts = [(item['start'], item['size'], item['type']) for item in geometry['partitions']]
        if (geometry['label'] != 'dos' or geometry['id'] != '0x'+signature or parts != [
                (BOOT_OFFSET//512, BOOT_BYTES//512, 'c'), (ROOT_OFFSET//512, (IMAGE_BYTES-ROOT_OFFSET)//512, '83')]):
            raise ValueError('Unexpected Server partition geometry')
        result = {'role': 'server', 'layout': 'single-system', 'kernel_version': version,
                  'image_bytes': IMAGE_BYTES, 'image_sha256': package_lock.digest(image),
                  'boot_partuuid': signature+'-01', 'root_partuuid': signature+'-02',
                  'rauc': False, 'hardware_boot_verified': False}
        (output/'worker-result.json').write_text(json.dumps(result, indent=2)+'\n')
    finally:
        shutil.rmtree(root)


def build(application, manifest_sha256, base_cache, role_cache, output):
    if not sys.platform.startswith('linux') or os.geteuid() == 0:
        raise ValueError('Run the image builder as an ordinary Linux user')
    manifest = image_assembly.component(application, manifest_sha256)
    if (manifest.get('role') != 'server' or manifest.get('server_namespace_readiness_checked') is not True
            or manifest.get('application_installed') is not True):
        raise ValueError('Expected a verified standalone Server application root')
    source = image_assembly.regular(Path(application).absolute()/'root.tar', manifest['root_tar_sha256'])
    index = project.package_locks()
    selected, locks = local_repo.role_inputs('server', [(base_cache, index['base']['lock_sha256']),
                                                        (role_cache, index['roles']['server']['sha256'])])
    if manifest['lock_sha256'] != locks:
        raise ValueError('Server application root uses different package locks')
    root_build.audit(source, selected)
    output = Path(output).absolute()
    if output.exists() or output.resolve() != output or output.is_relative_to(project.ROOT):
        raise ValueError('Use a new absolute output directory outside the checkout')
    if shutil.disk_usage(output.parent).free < 16*1024**3:
        raise ValueError('Server assembly requires 16 GiB free scratch space')
    output.mkdir()
    request = {'source': str(source), 'sha256': manifest['root_tar_sha256'],
               'namespaces': {name: os.readlink('/proc/self/ns/'+name) for name in ('user', 'mnt', 'pid', 'net')}}
    path = output/'request.json'
    path.write_text(json.dumps(request))
    path.chmod(0o600)
    command = ['unshare', '--user', '--map-root-user', '--map-auto', '--net', '--mount', '--pid',
               '--fork', '--kill-child=TERM', '--mount-proc', sys.executable,
               '-m', 'zmala_images.server_single', '--worker', str(path)]
    with (output/'build.log').open('x') as log:
        subprocess.run(command, check=True, timeout=1800, cwd=project.ROOT, stdout=log, stderr=subprocess.STDOUT,
                       env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C',
                            'PYTHONDONTWRITEBYTECODE': '1', 'SOURCE_DATE_EPOCH': root_build.SOURCE_DATE_EPOCH})
    result = json.loads((output/'worker-result.json').read_text())
    image_assembly.regular(output/'server.img', result['image_sha256'])
    result.update(schema=1, image_version=project.image_version(), components=manifest['components'],
                  production_qualified=False, source_root_sha256=manifest['root_tar_sha256'])
    (output/'READY.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--worker':
        worker(sys.argv[2])
        return
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('application', 'manifest-sha256', 'base-cache', 'role-cache', 'output'):
        parser.add_argument('--'+name, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.application, args.manifest_sha256, args.base_cache, args.role_cache, args.output), indent=2))


if __name__ == '__main__':
    main()
