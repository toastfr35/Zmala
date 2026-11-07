"""Build-only initramfs generation from a reviewed prepared ARM64 root.

No command opens a card, selects a live disk or publishes an update candidate.
The output remains an unqualified boot component, not a flashable system image.
"""
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

from . import build_space, image_state, local_repo, package_lock, project, root_build


def checked_source(source, expected, selected, role):
    source = Path(source)
    root_build.preflight_tar(source)
    if not re.fullmatch('[a-f0-9]{64}', expected) or package_lock.digest(source) != expected:
        raise ValueError('Prepared-root digest differs from its reviewed record')
    return image_state.audit(source, role, selected, image_state.payloads(role))


def build(role, source, expected, base_cache, role_cache, output):
    if platform.system() != 'Linux' or os.geteuid() == 0:
        raise ValueError('Use an ordinary Linux user with subordinate UID/GID namespace support')
    index = project.package_locks()
    selected, _ = local_repo.inputs([(base_cache, index['base']['lock_sha256']),
                                     (role_cache, index['roles'][role]['sha256'])])
    source = Path(source).absolute()
    checked_source(source, expected, selected, role)
    output = Path(output).absolute()
    if (output.exists() or output.resolve() != output
            or not re.fullmatch(r'/[A-Za-z0-9_./-]+', output.as_posix())):
        raise ValueError('Use a new simple absolute Linux output directory')
    if output.resolve().is_relative_to(Path(__file__).resolve().parents[1]):
        raise ValueError('Keep the disposable target-root build outside the checkout')
    for name in ('unshare', 'mount', 'umount', 'tar', 'chroot'):
        if not shutil.which(name):
            raise ValueError('Missing isolated initramfs build tool: '+name)
    output.parent.mkdir(parents=True, exist_ok=True)
    if build_space.available(output.parent) < root_build.MIN_BUILD_FREE_BYTES:
        raise ValueError('Insufficient free space for the disposable target-root build')
    output.mkdir()
    request = {'schema': 1, 'role': role, 'source': str(source), 'sha256': expected,
               'output': str(output), 'checkout': str(Path(__file__).resolve().parents[1]),
               'host_namespaces': {name: os.readlink('/proc/self/ns/'+name)
                                   for name in ('user', 'mnt', 'pid', 'net')}}
    request_file = output/'request.json'
    request_file.write_text(json.dumps(request), encoding='utf-8')
    request_file.chmod(0o600)
    command = ['unshare', '--user', '--map-root-user', '--map-auto', '--net', '--mount', '--pid',
               '--fork', '--kill-child=TERM', '--mount-proc', sys.executable,
               '-m', 'zmala_images.initramfs_worker', str(request_file)]
    with (output/'build.log').open('w', encoding='utf-8') as stream:
        subprocess.run(command, check=True, stdout=stream, stderr=subprocess.STDOUT, timeout=900,
                       cwd=request['checkout'], env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin',
                       'PYTHONPATH': request['checkout'], 'LC_ALL': 'C',
                       'SOURCE_DATE_EPOCH': root_build.SOURCE_DATE_EPOCH})
    result = json.loads((output/'worker-result.json').read_text())
    if (result.get('role') != role or result.get('source_root_sha256') != expected
            or result.get('target_dispatch_checked') is not True
            or package_lock.digest(source) != expected
            or package_lock.digest(output/'initramfs.img') != result.get('initramfs_sha256')):
        raise ValueError('Initramfs result differs from its source/output record')
    (output/'READY.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    return result
