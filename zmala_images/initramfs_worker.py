"""Private-namespace build worker; invoked only by initramfs_build."""
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
from types import SimpleNamespace

from . import image_state, package_lock
from zmala_system import host_layout, host_storage


def command(arguments, timeout=300):
    return subprocess.run([str(value) for value in arguments], check=True, timeout=timeout,
                          env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C',
                               'SOURCE_DATE_EPOCH': os.environ['SOURCE_DATE_EPOCH']})


def unpack_root(source, root):
    """Only root /dev is omitted, not e.g. drivers/net/can/dev inside /usr."""
    command(['tar', '--extract', '--numeric-owner', '--anchored', '--exclude=dev/*', '--exclude=./dev/*',
             '--file', source, '--directory', root])


def firmware_kernel_version(root):
    """Use the kernel the reviewed root's Raspberry Pi firmware installed."""
    firmware = host_storage.safe(root, 'boot/firmware/kernel8.img')
    info = firmware.lstat()
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 64*1024**2:
        raise ValueError('Invalid Raspberry Pi firmware kernel payload')
    digest = package_lock.digest(firmware)
    matches = []
    for directory in host_storage.safe(root, 'usr/lib/modules').iterdir():
        version = directory.name
        if (not re.fullmatch('[A-Za-z0-9._+-]{1,96}', version)
                or not stat.S_ISDIR(directory.lstat().st_mode)):
            continue
        image = host_storage.safe(root, 'boot/vmlinuz-'+version)
        if image.exists():
            candidate = image.lstat()
            if (stat.S_ISREG(candidate.st_mode) and candidate.st_size == info.st_size
                    and package_lock.digest(image) == digest):
                matches.append(version)
    if len(matches) != 1:
        raise ValueError('Expected one module version matching the Raspberry Pi firmware kernel')
    return matches[0]


def inspect_initramfs(root, extracted, role):
    """Compare our payload bytes and target executables in the freshly built cpio."""
    candidates = [path for path in (extracted/'main', extracted)
                  if path.is_dir() and not path.is_symlink()
                  and (path/'usr/bin/python3.13').is_file()
                  and (path/'scripts/local-bottom/zmala-host').is_file()]
    if len(candidates) != 1:
        raise ValueError('Missing or ambiguous extracted main initramfs payload')
    main = candidates[0]
    if role in ('terminal', 'combined'):
        for name in ('zmala.plymouth', 'zmala.script', 'boot-family.png'):
            relative = 'usr/share/plymouth/themes/zmala/'+name
            if (main/relative).read_bytes() != (root/relative).read_bytes():
                raise ValueError('Boot theme was not retained in the real initramfs')
        config = (main/'etc/plymouth/plymouthd.conf').read_text()
        if 'Theme=zmala' not in config or not list(main.glob('usr/lib/*/plymouth/script.so')):
            raise ValueError('Boot theme selection or script plugin is missing')
    payload = image_state.payloads(role)
    paths = [f'{image_state.INSTALLED}/{name}' for name in image_state.EARLY_BOOT_FILES]
    expected = {name: payload[name] for name in (*paths, 'usr/lib/zmala/role')}
    for name, body in expected.items():
        target = host_storage.safe(main, name)
        info = target.lstat()
        host_layout.metadata(info, mode=0o644)
        if info.st_size != len(body) or target.read_bytes() != body:
            raise ValueError('Copied initramfs runtime bytes or metadata differ')
    entry = main/'scripts/local-bottom/zmala-host'
    host_storage.safe(main, 'scripts/local-bottom/zmala-host')
    host_layout.metadata(entry.lstat(), mode=0o755)
    body = Path(__file__).with_name('initramfs_entry.sh').read_bytes()
    if entry.stat().st_size != len(body) or entry.read_bytes() != body:
        raise ValueError('Invalid executable early-boot entry')
    order = host_storage.safe(main, 'scripts/local-bottom/ORDER')
    host_layout.metadata(order.lstat(), mode=0o644)
    if not 0 < order.stat().st_size <= 65536:
        raise ValueError('Missing or oversized early-boot dispatch')
    lines = order.read_text().splitlines()
    invocation = '/scripts/local-bottom/zmala-host "$@"'
    parameter_reload = '[ -e /conf/param.conf ] && . /conf/param.conf'
    if (lines.count(invocation) != 1 or any(
            line != parameter_reload and not re.fullmatch(r'/scripts/local-bottom/[A-Za-z0-9_.-]+ "\$@"', line)
            for line in lines)):
        raise ValueError('Early-boot entry is not dispatched exactly once')
    binaries = {'python3.13': ('usr/bin/python3.13', root/'usr/bin/python3.13')}
    for name in ('mount', 'umount', 'blkid'):
        paths = [host_storage.safe(root, folder+'/'+name) for folder in ('usr/bin', 'usr/sbin')]
        source = next((path for path in paths if path.is_file()), None)
        if source is None:
            raise ValueError('Missing locked target tool')
        binaries[name] = ('usr/lib/zmala/bin/'+name, source)
    hashes = {}
    for name, (destination, source) in binaries.items():
        copied = host_storage.safe(main, destination)
        host_layout.metadata(copied.lstat(), mode=0o755)
        if package_lock.digest(copied) != package_lock.digest(source):
            raise ValueError('Copied target executable changed or retained special mode bits')
        hashes[name] = package_lock.digest(copied)
    return main, expected, hashes


def check_target_dispatch(main):
    """Trace the real vendor dispatcher with the entry's harmless prereqs mode."""
    result = subprocess.run(['chroot', str(main), '/bin/sh', '-xc',
                             '. /scripts/functions; run_scripts /scripts/local-bottom prereqs; :'],
                            check=True, capture_output=True, text=True, timeout=30,
                            env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C'})
    if result.stderr.splitlines().count('+ /scripts/local-bottom/zmala-host prereqs') != 1:
        raise ValueError('Vendor dispatcher did not execute the storage entry exactly once')


def check_target_environment_tools(root, role):
    """Exercise target ARM64 tools using only new worker RAM /tmp and /run files.

    This emulated build check is separate from actual Pi transport admission,
    bootloader interpretation and physical power-loss qualification.
    """
    script = '''from pathlib import Path
import os, struct, subprocess, sys, tempfile, zlib
from zmala_system import boot_environment, boot_media, boot_state
for tool in boot_environment.RUNNING_BOOT_TOOLS.values():
    subprocess.run([tool, '--version'], check=True, timeout=10)
Path('/run/lock').mkdir(mode=0o700, exist_ok=True)
state = boot_state.State(sys.argv[1], 'A')
with tempfile.TemporaryDirectory(prefix='zmala-env-check-') as folder:
    directory = Path(folder)
    image = directory/'new.img'
    data = boot_state.encode(state).replace(b'\\n', b'\\0')+b'\\0'
    data += b'\\xff'*(boot_media.ENV_BYTES-5-len(data))
    with image.open('xb') as stream:
        stream.truncate(8*1024**2)
        for offset, flag in zip(boot_media.ENV_OFFSETS, (1, 0)):
            stream.seek(offset)
            stream.write(struct.pack('<I', zlib.crc32(data))+bytes([flag])+data)
        stream.flush(); os.fsync(stream.fileno())
    boot_environment.private_file(directory/'fw_env.config', ''.join(
        f'{image} {offset:#x} {boot_media.ENV_BYTES:#x}\\n' for offset in boot_media.ENV_OFFSETS).encode())
    boot_environment.private_file(directory/'no-default-env', b'')
    environment = boot_environment.ToolEnvironment(directory, sys.argv[1])
    assert environment.read() == state
    candidate = state.stage('A', 'B', '1'*64)
    assert environment.commit(state, candidate) == candidate
    assert environment.read() == candidate
'''
    command(['chroot', root, '/usr/bin/python3', '-IB', '-c', script, role])


def worker(request_file):
    if os.geteuid() != 0:
        raise ValueError('Expected namespace root, not a host-user invocation')
    request = json.loads(Path(request_file).read_text())
    if (set(request) != {'schema', 'role', 'source', 'sha256', 'output', 'checkout', 'host_namespaces'}
            or request['schema'] != 1):
        raise ValueError('Unsupported initramfs build request')
    expected_namespaces = request['host_namespaces']
    if (not isinstance(expected_namespaces, dict) or set(expected_namespaces) != {'user', 'mnt', 'pid', 'net'}
            or any(os.readlink('/proc/self/ns/'+name) == original
                   for name, original in expected_namespaces.items())):
        raise ValueError('Worker requires separate user, mount, PID and network namespaces')
    mapping = Path('/proc/self/uid_map').read_text().splitlines()
    if not mapping:
        raise ValueError('Missing namespace UID mapping')
    inside, outside, length = map(int, mapping[0].split())
    if inside != 0 or outside == 0 or length != 1:
        raise ValueError('Worker requires a root-mapped subordinate user namespace')
    output, source = Path(request['output']), Path(request['source'])
    if (output.resolve() != Path(request_file).resolve().parent or output.is_symlink()
            or not output.is_absolute() or output == Path('/') or package_lock.digest(source) != request['sha256']):
        raise ValueError('Changed source or invalid worker directory')
    root = output/'root'
    if root.exists() or root.is_symlink():
        raise ValueError('The worker root must be new')
    root.mkdir(mode=0o700)
    try:
        command(['mount', '--make-rprivate', '/'])
        # Stock device nodes are replaced with RAM and fixed safe char binds.
        unpack_root(source, root)
        for name in ('proc', 'sys', 'dev', 'var', 'tmp', 'run'):
            target = host_storage.safe(root, name)
            target.mkdir(exist_ok=True)
        for name, filesystem, options in (('proc', 'proc', 'nosuid,nodev,noexec'),
                ('sys', 'sysfs', 'ro,nosuid,nodev,noexec'), ('dev', 'tmpfs', 'mode=0755,size=8M'),
                ('var', 'tmpfs', 'mode=0755,size=128M'), ('tmp', 'tmpfs', 'mode=1777,size=512M'),
                ('run', 'tmpfs', 'mode=0755,size=32M')):
            target = root/name
            command(['mount', '-t', filesystem, '-o', options, filesystem, target])
        for name in ('null', 'zero', 'random', 'urandom'):
            target = root/'dev'/name; target.touch()
            command(['mount', '--bind', '/dev/'+name, target])
        host_storage.copy_seed(SimpleNamespace(root=root, seed=host_storage.seed_entries(root)))
        hook = host_storage.safe(root, 'etc/initramfs-tools/hooks/zmala-host')
        if hook.exists() or hook.is_symlink():
            raise ValueError('Refusing a preexisting build hook')
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text(Path(__file__).with_name('initramfs_hook.sh').read_text(encoding='utf-8'),
                        encoding='utf-8', newline='\n'); hook.chmod(0o755)
        entry = host_storage.safe(root, 'etc/initramfs-tools/scripts/local-bottom/zmala-host')
        if entry.exists() or entry.is_symlink():
            raise ValueError('Refusing a preexisting boot entry')
        entry.parent.mkdir(parents=True, exist_ok=True)
        entry.write_text(Path(__file__).with_name('initramfs_entry.sh').read_text(encoding='utf-8'),
                         encoding='utf-8', newline='\n'); entry.chmod(0o755)
        version = firmware_kernel_version(root)
        # Validate the gate against this role's actual vendor-unit graph. This
        # checks offline configuration only; it does not start PID1 or services.
        units = ['zmala-host-storage.service', 'sysinit.target', 'systemd-machine-id-commit.service']
        if (request['role'] == 'terminal'
                and (root/'usr/lib/systemd/system/zmalacall-terminal.service').is_file()):
            units += ['zmala-system-updater.service', 'zmalacall-terminal.service',
                      'zmalacall-system-update-screen.service', 'rauc.service']
        command(['chroot', root, '/usr/bin/systemd-analyze', '--man=no', 'verify', *units])
        command(['chroot', root, '/usr/sbin/mkinitramfs', '-c', 'gzip', '-o', '/tmp/zmala-initramfs.img', version])
        generated = root/'tmp/zmala-initramfs.img'
        if generated.is_symlink() or not generated.is_file() or not 0 < generated.stat().st_size <= 256*1024**2:
            raise ValueError('Generated initramfs exceeds its budget')
        pending = output/'initramfs.pending.img'
        shutil.copyfile(generated, pending)
        command(['chroot', root, '/usr/bin/unmkinitramfs', '/tmp/zmala-initramfs.img', '/tmp/inspection'])
        main, expected, hashes = inspect_initramfs(root, root/'tmp/inspection', request['role'])
        command(['chroot', main, '/usr/bin/python3', '-IB', '-c',
                 'import fcntl,ctypes,zlib,bz2,lzma; import zmala_system.boot_entry,zmala_system.boot_gate,zmala_system.boot_backend'])
        command(['chroot', main, '/scripts/local-bottom/zmala-host', 'prereqs'])
        check_target_dispatch(main)
        check_target_environment_tools(root, request['role'])
        pending.replace(output/'initramfs.img')
        result = {'schema': 1, 'role': request['role'], 'source_root_sha256': request['sha256'],
                  'kernel_version': version, 'initramfs_sha256': package_lock.digest(output/'initramfs.img'),
                  'initramfs_bytes': generated.stat().st_size, 'runtime_files_checked': len(expected),
                  'target_binary_sha256': hashes, 'target_imports_checked': True, 'target_prereqs_checked': True,
                  'target_unit_graph_checked': True,
                  'target_dispatch_checked': True,
                  'target_environment_tools_checked': True,
                  'hardware_boot_verified': False, 'complete_image': False, 'production_qualified': False,
                  'toolchain_fully_locked': False}
        (output/'worker-result.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    finally:
        primary_failed = sys.exc_info()[0] is not None
        errors = []
        # Also find a mount command that failed after partial success. Every
        # mount under this exclusively created worker root belongs to this build.
        current = host_storage.NativeMounts.facts()
        for target in sorted(current, key=lambda path: len(path.parts), reverse=True):
            if not target.is_relative_to(root):
                continue
            try:
                command(['umount', target], timeout=30)
            except (OSError, subprocess.SubprocessError) as error:
                errors.append(error)
        # Root has sub-UID-owned files. Remove it while its owning user namespace
        # still exists, only after every worker mount has been released.
        remaining = [point for point in host_storage.NativeMounts.facts() if point.is_relative_to(root)]
        if remaining:
            errors.append(ValueError('Worker mount cleanup is incomplete'))
        if not errors and root.parent == output and root.resolve() == root and root.name == 'root':
            shutil.rmtree(root)
        if errors and not primary_failed:
            raise errors[0]


if __name__ == '__main__':
    worker(sys.argv[1])
