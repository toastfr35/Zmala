"""Assemble only new regular-file development media, never physical devices."""
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import sys

from . import bootloader, build_space, image_payload, image_state, initramfs_build, local_repo, package_lock, project, sources


def regular(path, expected):
    path = Path(path)
    if not stat.S_ISREG(path.lstat().st_mode) or package_lock.digest(path) != expected:
        raise ValueError('Expected a regular file matching its independently supplied digest')
    return path


def component(folder, expected):
    folder = Path(folder).absolute()
    if folder.resolve() != folder:
        raise ValueError('Component directory must not contain symlinks')
    path = regular(folder/'READY.json', expected)
    if path.stat().st_size > 1024**2:
        raise ValueError('Oversized component manifest')
    return json.loads(path.read_text())


def build(role, source, expected, initramfs, initramfs_manifest, loader, loader_manifest,
          base_cache, role_cache, output, media_bytes=None):
    if platform.system() != 'Linux' or os.geteuid() == 0:
        raise ValueError('Use an ordinary Linux user with subordinate UID/GID mappings')
    media_bytes = image_payload.disk_bytes(media_bytes)
    builders = {path.name: package_lock.digest(path) for path in sorted(Path(__file__).parent.glob('*.py'))}
    index = project.package_locks()
    selected, _ = local_repo.inputs([(base_cache, index['base']['lock_sha256']),
                                    (role_cache, index['roles'][role]['sha256'])])
    source = Path(source).absolute()
    audit = initramfs_build.checked_source(source, expected, selected, role)
    if not audit['application_installed']:
        raise ValueError('Image assembly requires an application-bearing prepared root')
    initramfs, loader = Path(initramfs).absolute(), Path(loader).absolute()
    init = component(initramfs, initramfs_manifest)
    if (init.get('role') != role or init.get('source_root_sha256') != expected
            or not all(init.get(name) is True for name in ('target_imports_checked',
                'target_prereqs_checked', 'target_unit_graph_checked', 'target_environment_tools_checked'))):
        raise ValueError('Initramfs is not checked against this exact root and role')
    regular(initramfs/'initramfs.img', init['initramfs_sha256'])
    load = component(loader, loader_manifest)
    if (load.get('source') != sources.pins()['bootloader_audit']
            or load.get('profile_sha256') != package_lock.digest(bootloader.PROFILE)
            or not load.get('compiled') or not load.get('configuration_checked')
            or set(load.get('files', {})) != {'u-boot.bin', 'mkimage', 'initial.env', 'resolved.config'}):
        raise ValueError('Loader does not match the pinned audited build')
    for name, digest in load['files'].items():
        regular(loader/name, digest)
    if bootloader.audit(loader/'resolved.config')['violations']:
        raise ValueError('Loader configuration failed review')
    output = Path(output).absolute()
    checkout = Path(__file__).resolve().parents[1]
    if output.exists() or output.resolve() != output or output.is_relative_to(checkout):
        raise ValueError('Use a new absolute output directory outside the checkout')
    for tool in ('unshare', 'tar', 'chroot', 'sfdisk', 'mkfs.vfat', 'mkfs.ext4', 'mcopy', 'mtype', 'debugfs'):
        if not shutil.which(tool):
            raise ValueError('Missing image assembly tool: '+tool)
    output.parent.mkdir(parents=True, exist_ok=True)
    if build_space.available(output.parent) < 32*1024**3:
        raise ValueError('Image assembly requires 32 GiB free scratch space')
    output.mkdir()
    request = {'role': role, 'source': str(source), 'sha256': expected, 'output': str(output),
               'initramfs': str(initramfs), 'initramfs_manifest': initramfs_manifest,
               'loader': str(loader), 'loader_manifest': loader_manifest, 'media_bytes': media_bytes,
               'host_namespaces': {name: os.readlink('/proc/self/ns/'+name) for name in ('user', 'mnt', 'pid', 'net')}}
    request_file = output/'request.json'
    request_file.write_text(json.dumps(request)); request_file.chmod(0o600)
    with (output/'build.log').open('x') as log:
        subprocess.run(['unshare', '--user', '--map-root-user', '--map-auto', '--net', '--mount', '--pid',
                        '--fork', '--kill-child=TERM', '--mount-proc', sys.executable,
                        '-m', 'zmala_images.image_worker', str(request_file)],
                       cwd=checkout, env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'PYTHONPATH': str(checkout),
                                         'LC_ALL': 'C', 'SOURCE_DATE_EPOCH': '1793836800'},
                       check=True, timeout=1800, stdout=log, stderr=subprocess.STDOUT)
    result = json.loads((output/'worker-result.json').read_text())
    current = {path.name: package_lock.digest(path) for path in sorted(Path(__file__).parent.glob('*.py'))}
    if current != builders or result.get('builder_sha256') != builders:
        raise ValueError('Image builder sources changed during assembly; no READY accepted')
    regular(source, expected)
    regular(output/'appliance.img', result['image_sha256'])
    image_state.audit(source, role, selected, image_state.payloads(role))
    (output/'READY.json').write_text(json.dumps(result, indent=2)+'\n')
    return result
