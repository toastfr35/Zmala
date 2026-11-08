"""Build application-bearing roots from exact OS/source inputs in Linux namespaces."""
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys

from . import application_inputs, application_provision, build_space, local_repo, package_lock, project, root_build


def build(role, source, expected_root, applications, expected_applications, base_cache, role_cache, output):
    argon_one = application_provision.uses_argon(role)
    if platform.system() != 'Linux' or os.geteuid() == 0:
        raise ValueError('Use an ordinary Linux user with subordinate UID/GID mappings')
    index = project.package_locks()
    selected, locks = local_repo.role_inputs(role, [(base_cache, index['base']['lock_sha256']),
                                                    (role_cache, index['roles'][role]['sha256'])])
    source, applications, output = (Path(p).absolute() for p in (source, applications, output))
    if not re.fullmatch('[a-f0-9]{64}', expected_root) or package_lock.digest(source) != expected_root:
        raise ValueError('OS root differs from its reviewed digest')
    root_build.audit(source, selected)
    _, manifest = application_inputs.verify(applications, expected_applications, role)
    if (output.exists() or output.resolve() != output
            or not re.fullmatch(r'/[A-Za-z0-9_./-]+', str(output))
            or output.is_relative_to(project.ROOT.resolve())):
        raise ValueError('Use a new simple absolute output directory outside the checkout')
    output.parent.mkdir(parents=True, exist_ok=True)
    if build_space.available(output.parent) < root_build.MIN_BUILD_FREE_BYTES:
        raise ValueError('At least 32 GiB free is required for application construction')
    output.mkdir()
    request = {'schema': 1, 'role': role, 'source': str(source), 'root_sha256': expected_root,
               'applications': str(applications), 'applications_sha256': expected_applications,
               'output': str(output), 'host_namespaces': {name: os.readlink('/proc/self/ns/'+name)
                                                       for name in ('user', 'mnt', 'pid', 'net')}}
    request_path = output/'request.json'
    request_path.write_text(json.dumps(request), encoding='utf-8')
    request_path.chmod(0o600)
    before = package_lock.digest('/var/lib/dpkg/status')
    command = ['unshare', '--user', '--map-root-user', '--map-auto', '--mount', '--net', '--pid',
               '--fork', '--kill-child=TERM', '--mount-proc', sys.executable,
               '-m', 'zmala_images.application_worker', str(request_path)]
    with (output/'build.log').open('x') as log:
        subprocess.run(command, check=True, timeout=1800, cwd=project.ROOT,
                       env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C',
                            'PYTHONPATH': str(project.ROOT), 'SOURCE_DATE_EPOCH': root_build.SOURCE_DATE_EPOCH},
                       stdout=log, stderr=subprocess.STDOUT)
    if (before != package_lock.digest('/var/lib/dpkg/status')
            or package_lock.digest(source) != expected_root
            or package_lock.digest(applications) != expected_applications):
        raise ValueError('Host package state or application build inputs changed')
    audit = root_build.audit(output/'root.tar', selected)
    result = json.loads((output/'worker-result.json').read_text())
    if result['role'] != role or result.get('argon_one') is not argon_one:
        raise ValueError('Application worker role mismatch')
    result.update(schema=1, packages=audit['packages'], source_root_sha256=expected_root,
                  applications_sha256=expected_applications, source_commit=manifest['source_commit'],
                  lock_sha256=locks, root_tar_sha256=package_lock.digest(output/'root.tar'),
                  root_tar_bytes=(output/'root.tar').stat().st_size, host_dpkg_unchanged=True,
                  application_installed=True, runtime_storage_prepared=False,
                  complete_image=False, hardware_boot_verified=False, production_qualified=False,
                  toolchain_fully_locked=False)
    result['builder_sha256'] = {path.name: package_lock.digest(path)
                               for path in sorted(Path(__file__).parent.glob('*.py'))}
    (output/'READY.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    return result
