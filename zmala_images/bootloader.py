"""Emit/audit unqualified Pi 4 bootloader build settings, never a live device.

Kconfig names must match the pinned source. A fragment's presence is not proof
that Kconfig accepted it, that a binary compiled, or that a complete image boots.
"""
import hashlib
import json
from pathlib import Path
import re
import stat

from . import sources

PROFILE = Path(__file__).with_name('bootloader-profile.json')
LOCAL_BOOT = 'if fatload mmc 0:1 ${scriptaddr} boot.scr; then source ${scriptaddr}; fi; reset'


def validate(value):
    """Fence this profile to the experimentally checked Pi 4 SD layout."""
    if (not isinstance(value, dict)
            or set(value) != {'schema', 'qualification', 'source', 'defconfig', 'first_partition_bytes',
                       'environment', 'watchdog', 'boot_command'}
            or value['schema'] != 1 or value['qualification'] != 'development-only'
            or value['source'] != 'bootloader_audit' or value['defconfig'] != 'rpi_arm64_defconfig'
            or value['first_partition_bytes'] != 8*1024**2 or value['boot_command'] != LOCAL_BOOT):
        raise ValueError('Unsupported bootloader probe profile')
    env = value['environment']
    if (not isinstance(env, dict) or set(env) != {'offsets', 'bytes', 'device_index', 'hardware_partition'}
            or type(env['bytes']) is not int or env['bytes'] != 65536
            or type(env['device_index']) is not int or env['device_index'] != 0
            or type(env['hardware_partition']) is not int or env['hardware_partition'] != 0
            or not isinstance(env['offsets'], list) or len(env['offsets']) != 2):
        raise ValueError('Unsupported raw environment layout')
    first, second = env['offsets']
    if (any(type(offset) is not int or offset % 512 or offset < 1024**2 for offset in (first, second))
            or first+env['bytes'] > second
            or second+env['bytes'] > value['first_partition_bytes']):
        raise ValueError('Environment copies overlap GPT, each other or the first partition')
    watchdog = value['watchdog']
    if (not isinstance(watchdog, dict)
            or set(watchdog) != {'hardware_timeout_ms', 'userspace_open_timeout_seconds', 'runtime_seconds'}
            or any(type(v) is not int for v in watchdog.values())
            or watchdog['hardware_timeout_ms'] != 15000
            or not 15 <= watchdog['userspace_open_timeout_seconds'] <= 300
            or not 1 <= watchdog['runtime_seconds'] <= 15):
        raise ValueError('Invalid bounded watchdog handoff')
    return value


def profile():
    return validate(json.loads(PROFILE.read_text(encoding='utf-8')))


def required(value):
    env, watchdog = value['environment'], value['watchdog']
    # Current source uses ENV_REDUNDANT and ENV_MMC_DEVICE_INDEX. Legacy option
    # names can silently disappear when olddefconfig resolves a fragment.
    result = {key: 'y' for key in (
        'CONFIG_ARM64', 'CONFIG_ARCH_BCM283X', 'CONFIG_TARGET_RPI_ARM64',
        'CONFIG_ENV_IS_IN_MMC', 'CONFIG_ENV_REDUNDANT',
        'CONFIG_WDT', 'CONFIG_WDT_BCM2835', 'CONFIG_WATCHDOG',
        'CONFIG_WATCHDOG_AUTOSTART', 'CONFIG_CMD_WDT')}
    result.update({key: 'n' for key in (
        'CONFIG_ENV_IS_NOWHERE', 'CONFIG_ENV_IS_IN_FAT', 'CONFIG_ENV_MMC_USE_DT',
        'CONFIG_ENV_MMC_USE_SW_PARTITION', 'CONFIG_ENV_IMPORT_FDT', 'CONFIG_ENV_REDUNDANT_UPGRADE')})
    result.update({
        'CONFIG_ENV_OFFSET': hex(env['offsets'][0]),
        'CONFIG_ENV_OFFSET_REDUND': hex(env['offsets'][1]),
        'CONFIG_ENV_SIZE': hex(env['bytes']),
        'CONFIG_ENV_MMC_DEVICE_INDEX': str(env['device_index']),
        'CONFIG_ENV_MMC_EMMC_HW_PARTITION': str(env['hardware_partition']),
        'CONFIG_WATCHDOG_TIMEOUT_MSECS': str(watchdog['hardware_timeout_ms']),
        'CONFIG_BOOTCOMMAND': json.dumps(value['boot_command']),
    })
    return result


def emit(output):
    """Write ordinary build-input files only; intentionally omit boot.scr."""
    value = profile()
    pin = sources.pins()[value['source']]
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise ValueError('Use a new bootloader output directory')
    settings = required(value)
    fragment = '# Unqualified Pi 4 SD probe; resolve with pinned U-Boot Kconfig.\n'
    fragment += ''.join(f'# {key} is not set\n' if item == 'n' else f'{key}={item}\n'
                        for key, item in sorted(settings.items()))
    watchdog = value['watchdog']
    files = {
        'probe.config': fragment,
        'fw_env.config': ''.join(f'/dev/mmcblk0 {hex(offset)} {hex(value["environment"]["bytes"])}\n'
                               for offset in value['environment']['offsets']),
        'watchdog-probe.conf': '[Manager]\nRuntimeWatchdogSec='+str(watchdog['runtime_seconds'])
                               +'s\nWatchdogDevice=/dev/watchdog0\n',
        'kernel-handoff.txt': (
            '# Probe integration notes, not an executable boot script.\n'
            '# Preserve a placeable graphics CMA window; qualify the complete memory map.\n'
            'setenv fdt_high ${fdt_addr}\nsetenv initrd_high ${fdt_addr}\n'
            '# Add these to the selected kernel command line, retaining its slot/root identity:\n'
            'watchdog.handle_boot_enabled=1 watchdog.open_timeout='
            +str(watchdog['userspace_open_timeout_seconds'])+'\n'),
    }
    output.mkdir(parents=True)
    for name, content in files.items():
        (output/name).write_text(content, encoding='utf-8', newline='\n')
    status = {'schema': 1, 'qualification': 'development-only', 'source': pin,
              'defconfig': value['defconfig'], 'profile': value,
              'profile_sha256': hashlib.sha256(PROFILE.read_bytes()).hexdigest(),
              'files': {name: hashlib.sha256((output/name).read_bytes()).hexdigest() for name in files},
              'production_qualified': False, 'complete_image': False, 'compiled': False,
              'missing': ['boot-selection script/backend', 'qualified common-loader policy',
                          'product health confirmation', 'complete fault/power-loss matrix',
                          'locked build toolchain', 'factory provisioning and data policy']}
    (output/'status.json').write_text(json.dumps(status, indent=2)+'\n', encoding='utf-8', newline='\n')
    return output


def read_config(path):
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > 1024**2:
        raise ValueError('Expected a bounded regular Kconfig file')
    with path.open('rb') as stream:
        data = stream.read(1024**2+1)
    if len(data) > 1024**2:
        raise ValueError('Kconfig file exceeds budget')
    values = {}
    for line in data.decode('utf-8').splitlines():
        disabled = re.fullmatch(r'# (CONFIG_[A-Z0-9_]+) is not set', line)
        enabled = re.fullmatch(r'(CONFIG_[A-Z0-9_]+)=(.+)', line)
        if disabled:
            key, value = disabled[1], 'n'
        elif enabled:
            key, value = enabled.groups()
        elif not line or line.startswith('#'):
            continue
        else:
            raise ValueError('Malformed Kconfig line')
        if key in values:
            raise ValueError('Duplicate Kconfig setting')
        values[key] = value
    return data, values


def audit(path):
    data, values = read_config(path)
    expected = required(profile())
    violations = [key for key, value in expected.items() if values.get(key) != value]
    violations += [key for key, value in values.items()
                   if key.startswith('CONFIG_ENV_IS_IN_') and key != 'CONFIG_ENV_IS_IN_MMC' and value == 'y'
                   and key not in violations]
    return {'schema': 1, 'checks': 'probe-bootloader-kconfig-subset',
            'configuration_sha256': hashlib.sha256(data).hexdigest(),
            'violations': sorted(violations), 'production_qualified': False,
            'compilation_verified': False, 'hardware_boot_verified': False}
