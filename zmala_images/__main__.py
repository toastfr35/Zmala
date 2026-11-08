"""Development image tools. No command flashes a card or updates a live host."""
import argparse
import json
from pathlib import Path
import subprocess
import tarfile

from zmala_system.host_layout import ROLES

from . import (application_build, application_inputs, base_intent, bootloader, factory_data, image_assembly, image_state, initramfs_build,
              inspect_boot, inspect_disk, inspect_root, loader_build, local_repo, package_lock, project, root_build, sources)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('check', help='Validate checked-in source pins and role package intent')
    assembly = sub.add_parser('assemble-image', help='Assemble new regular-file development media; never flash a device')
    assembly.add_argument('role', choices=ROLES)
    assembly.add_argument('--media-bytes', type=int, help='Exact target byte capacity; default is minimal test geometry')
    for name in ('source', 'initramfs', 'loader', 'base-cache', 'role-cache', 'output'):
        assembly.add_argument('--'+name, required=True, type=Path)
    for name in ('expected-root-sha256', 'initramfs-manifest-sha256', 'loader-manifest-sha256'):
        assembly.add_argument('--'+name, required=True)
    loader = sub.add_parser('build-loader', help='Compile the pinned experimental Pi 4 loader (Linux)')
    loader.add_argument('--output', required=True, type=Path)
    applications = sub.add_parser('application-inputs', help='Retain locked component packages and their build dependencies')
    applications.add_argument('role', choices=ROLES)
    applications.add_argument('--output', required=True, type=Path)
    applications.add_argument('--components-lock', required=True, type=Path)
    applications.add_argument('--packages', required=True, type=Path)
    app_root = sub.add_parser('provision-applications', help='Build and check applications in an isolated offline root')
    app_root.add_argument('role', choices=ROLES)
    app_root.add_argument('--source', required=True, type=Path)
    app_root.add_argument('--expected-root-sha256', required=True)
    app_root.add_argument('--applications', required=True, type=Path)
    app_root.add_argument('--expected-applications-sha256', required=True)
    app_root.add_argument('--base-cache', required=True, type=Path)
    app_root.add_argument('--role-cache', required=True, type=Path)
    app_root.add_argument('--output', required=True, type=Path)
    fetch = sub.add_parser('fetch', help='Download and hash-check a pinned source into a new cache tree')
    fetch.add_argument('source', choices=sources.SOURCE_NAMES)
    fetch.add_argument('--cache', required=True, type=Path)
    probe = sub.add_parser('probe-config', help='Emit a development-only minimal boot configuration')
    probe.add_argument('role', choices=ROLES)
    probe.add_argument('--output', required=True, type=Path)
    boot_config = sub.add_parser('bootloader-config', help='Emit unqualified Pi 4 bootloader probe settings')
    boot_config.add_argument('--output', required=True, type=Path)
    boot_inspect = sub.add_parser('inspect-bootloader', help='Check the candidate resolved Kconfig subset')
    boot_inspect.add_argument('config', type=Path)
    inspect = sub.add_parser('inspect-root', help='Read an already unpacked offline root')
    inspect.add_argument('root', type=Path)
    disk = sub.add_parser('inspect-disk', help='Validate an offline probe image partition table')
    disk.add_argument('image', type=Path)
    disk.add_argument('--sector-size', choices=(512, 4096), type=int, default=512)
    boot = sub.add_parser('inspect-bootfs', help='Read GPT and FAT boot-volume geometry in an offline probe')
    boot.add_argument('image', type=Path)
    boot.add_argument('--sector-size', choices=(512, 4096), type=int, default=512)
    lock = sub.add_parser('lock-packages', help='Download and retain an authenticated dependency closure (Linux)')
    lock.add_argument('role', choices=ROLES)
    lock.add_argument('--output', type=Path, required=True)
    lock.add_argument('--debian-keyring', type=Path, required=True)
    lock.add_argument('--raspberrypi-keyring', type=Path, required=True)
    verify = sub.add_parser('verify-packages', help='Verify retained archives against a trusted lock digest')
    verify.add_argument('folder', type=Path)
    verify.add_argument('--expected-lock-sha256', required=True)
    ledger = sub.add_parser('capture-base', help='Capture exact clean-base intent from an offline dpkg ledger')
    ledger.add_argument('ledger', type=Path)
    ledger.add_argument('--expected-ledger-sha256', required=True)
    ledger.add_argument('--output', required=True, type=Path)
    base = sub.add_parser('lock-base', help='Retain the reviewed common-base package closure (Linux)')
    base.add_argument('--output', required=True, type=Path)
    base.add_argument('--debian-keyring', required=True, type=Path)
    base.add_argument('--raspberrypi-keyring', required=True, type=Path)
    repo = sub.add_parser('local-repo', help='Assemble a verified, build-only file repository (Linux)')
    repo.add_argument('--cache', nargs=2, action='append', required=True, metavar=('FOLDER', 'LOCK_SHA256'))
    repo.add_argument('--output', required=True, type=Path)
    root = sub.add_parser('build-root', help='Build an unqualified locked ARM64 root tar in namespaces (Linux)')
    root.add_argument('role', choices=ROLES)
    root.add_argument('--base-cache', required=True, type=Path)
    root.add_argument('--role-cache', required=True, type=Path)
    root.add_argument('--output', required=True, type=Path)
    state = sub.add_parser('prepare-root', help='Package experimental host storage into a new root tar; no extraction')
    state.add_argument('role', choices=ROLES)
    state.add_argument('--source', required=True, type=Path)
    state.add_argument('--expected-root-sha256', required=True)
    state.add_argument('--base-cache', required=True, type=Path)
    state.add_argument('--role-cache', required=True, type=Path)
    state.add_argument('--output', required=True, type=Path)
    factory = sub.add_parser('factory-data', help='Emit an empty marked data tar; no formatting or device access')
    factory.add_argument('role', choices=ROLES)
    factory.add_argument('--output', required=True, type=Path)
    initrd = sub.add_parser('build-initramfs', help='Build an unqualified initramfs from a reviewed root (Linux)')
    initrd.add_argument('role', choices=ROLES)
    initrd.add_argument('--source', required=True, type=Path)
    initrd.add_argument('--expected-root-sha256', required=True)
    initrd.add_argument('--base-cache', required=True, type=Path)
    initrd.add_argument('--role-cache', required=True, type=Path)
    initrd.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'check':
            sources.pins()
            bootloader.profile()
            locks = project.package_locks()
            print('Image version: '+project.image_version())
            components_lock = project.ROOT/'components.lock.json'
            if components_lock.is_file():
                components = application_inputs.read_component_lock('combined', components_lock)
                print('Application pins: '+', '.join(name+' '+pin['version'] for name, pin in components.items()))
            print('common base: '+str(len(project.common_base()['requested']))+' exact installed selections; '
                  +str(locks['base']['archives'])+' locked dependency archives')
            for role in project.profiles()['roles']:
                print(role+': '+str(len(project.packages(role)))+' requested packages; '
                      +str(locks['roles'][role]['archives'])+' locked dependency archives')
            print('Source pins, profiles and intent locks valid; no image is qualified.')
        elif args.command == 'application-inputs':
            print(json.dumps(application_inputs.emit(args.role, args.output, args.components_lock, args.packages), indent=2))
        elif args.command == 'assemble-image':
            print(json.dumps(image_assembly.build(args.role, args.source, args.expected_root_sha256,
                             args.initramfs, args.initramfs_manifest_sha256, args.loader,
                             args.loader_manifest_sha256, args.base_cache, args.role_cache, args.output,
                             args.media_bytes), indent=2))
        elif args.command == 'build-loader':
            print(json.dumps(loader_build.build(args.output), indent=2))
        elif args.command == 'provision-applications':
            print(json.dumps(application_build.build(args.role, args.source, args.expected_root_sha256,
                             args.applications, args.expected_applications_sha256, args.base_cache,
                             args.role_cache, args.output), indent=2))
        elif args.command == 'fetch':
            print(sources.acquire(args.source, args.cache))
        elif args.command == 'probe-config':
            print(project.emit_lab(args.role, args.output))
        elif args.command == 'bootloader-config':
            print(bootloader.emit(args.output))
        elif args.command == 'inspect-bootloader':
            result = bootloader.audit(args.config)
            print(json.dumps(result, indent=2))
            return 1 if result['violations'] else 0
        elif args.command == 'inspect-disk':
            print(json.dumps(inspect_disk.audit(args.image, args.sector_size), indent=2))
        elif args.command == 'inspect-bootfs':
            print(json.dumps(inspect_boot.audit(args.image, args.sector_size), indent=2))
        elif args.command == 'lock-packages':
            result = package_lock.intake(project.packages(args.role), args.output,
                                         args.debian_keyring, args.raspberrypi_keyring)
            print(str(len(result['packages']))+' package archives retained; lock SHA-256: '
                  +package_lock.digest(args.output/'packages.lock.json'))
        elif args.command == 'verify-packages':
            result = package_lock.verify(args.folder, args.expected_lock_sha256)
            print(str(len(result['packages']))+' retained package archives verified.')
        elif args.command == 'capture-base':
            result = base_intent.emit(args.ledger, args.expected_ledger_sha256, args.output)
            print(str(len(result['requested']))+' exact installed selections captured; not an image qualification.')
        elif args.command == 'lock-base':
            result = package_lock.intake(project.common_base()['requested'], args.output,
                                         args.debian_keyring, args.raspberrypi_keyring)
            print(str(len(result['packages']))+' base dependency archives retained; lock SHA-256: '
                  +package_lock.digest(args.output/'packages.lock.json'))
        elif args.command == 'local-repo':
            print(json.dumps(local_repo.emit(args.cache, args.output), indent=2))
        elif args.command == 'build-root':
            print(json.dumps(root_build.build(args.role, args.base_cache, args.role_cache, args.output), indent=2))
        elif args.command == 'prepare-root':
            index = project.package_locks()
            selected, _ = local_repo.role_inputs(args.role, [(args.base_cache, index['base']['lock_sha256']),
                                                            (args.role_cache, index['roles'][args.role]['sha256'])])
            print(json.dumps(image_state.prepare(args.source, args.expected_root_sha256, selected,
                                                args.role, args.output), indent=2))
        elif args.command == 'factory-data':
            print(json.dumps(factory_data.emit(args.role, args.output), indent=2))
        elif args.command == 'build-initramfs':
            print(json.dumps(initramfs_build.build(args.role, args.source, args.expected_root_sha256,
                                                  args.base_cache, args.role_cache, args.output), indent=2))
        else:
            result = inspect_root.audit(args.root)
            print(json.dumps(result, indent=2))
            return 1 if result['violations'] else 0
    except (OSError, ValueError, KeyError, tarfile.TarError) as error:
        parser.error(str(error))
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        parser.error('Isolated build/package tool failed; retain its incomplete output for diagnosis. '
                     'No completed output was accepted.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
