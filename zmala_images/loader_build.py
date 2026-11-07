"""Compile the pinned experimental Pi loader with audited settings; no device I/O."""
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess

from . import bootloader, package_lock, sources


def build(output):
    if platform.system() != 'Linux' or os.geteuid() == 0:
        raise ValueError('Build the loader as an ordinary Linux user')
    output = Path(output).absolute()
    if output.exists() or output.resolve() != output:
        raise ValueError('Use a new absolute loader output directory')
    output.mkdir(parents=True)
    source = sources.acquire('bootloader_audit', output/'sources')
    bootloader.emit(output/'profile')
    build_root = output/'build'
    build_root.mkdir()
    args = ['make', '-C', str(source), 'O='+str(build_root), 'CROSS_COMPILE=aarch64-linux-gnu-']
    env = {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'SOURCE_DATE_EPOCH': '1793836800'}
    with (output/'build.log').open('x') as log:
        def run(command):
            subprocess.run(command, cwd=source, env=env, check=True, timeout=600,
                           stdout=log, stderr=subprocess.STDOUT)
        run(args+['rpi_arm64_defconfig'])
        run(['bash', str(source/'scripts/kconfig/merge_config.sh'), '-m', '-O', str(build_root),
             str(build_root/'.config'), str(output/'profile/probe.config')])
        run(args+['olddefconfig'])
        audit = bootloader.audit(build_root/'.config')
        _, config = bootloader.read_config(build_root/'.config')
        required = ('CONFIG_OF_BOARD_SETUP', 'CONFIG_OF_LIBFDT_OVERLAY', 'CONFIG_CMD_FDT',
                    'CONFIG_CMD_PART', 'CONFIG_CMD_BOOTI')
        if audit['violations'] or any(config.get(name) != 'y' for name in required):
            raise ValueError('Resolved loader settings do not implement the required payload path')
        run(args+['-j'+str(min(8, os.cpu_count() or 1)), 'all', 'u-boot-initial-env'])
    initial = (build_root/'u-boot-initial-env').read_text()
    fields = dict(line.split('=', 1) for line in initial.splitlines())
    if (any(key.startswith('zm_') for key in fields)
            or fields.get('bootcmd') != bootloader.LOCAL_BOOT
            or not all(name in fields for name in ('scriptaddr', 'kernel_addr_r', 'ramdisk_addr_r', 'fdt_addr_r'))):
        raise ValueError('Compiled fallback environment must not fabricate appliance state')
    if not 0 < (build_root/'u-boot.bin').stat().st_size <= 4*1024**2:
        raise ValueError('Unexpected loader binary footprint')
    files = {'u-boot.bin': build_root/'u-boot.bin', 'mkimage': build_root/'tools/mkimage',
             'initial.env': build_root/'u-boot-initial-env', 'resolved.config': build_root/'.config'}
    for name, path in files.items():
        shutil.copyfile(path, output/name)
        (output/name).chmod(0o755 if name == 'mkimage' else 0o644)
    result = {'schema': 1, 'purpose': 'experimental-pi4-appliance-loader',
              'source': sources.pins()['bootloader_audit'],
              'profile_sha256': package_lock.digest(bootloader.PROFILE),
              'files': {name: package_lock.digest(output/name) for name in files},
              'compiled': True, 'configuration_checked': True, 'firmware_fdt_fixups_enabled': True,
              'hardware_boot_verified': False, 'toolchain_fully_locked': False, 'production_qualified': False}
    (output/'READY.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    return result
