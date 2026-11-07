"""Read-only acceptance of the installed Pi storage/service policy."""
from pathlib import Path
import subprocess


def command(*args):
    return subprocess.check_output(args, text=True, timeout=15).strip()


def assert_installed_storage(test, service, data):
    """Do not apply policy here: acceptance must inspect the actual booted host."""
    swaps = [Path(line.split()[0]) for line in Path('/proc/swaps').read_text().splitlines()[1:]]
    test.assertTrue(swaps, 'Expected active compressed RAM swap')
    for swap in swaps:
        test.assertTrue(str(swap).startswith('/dev/zram'), 'Disk-backed swap is active')
        test.assertEqual((Path('/sys/block')/swap.name/'backing_dev').read_text().strip(), 'none')
    test.assertEqual(command('findmnt', '-no', 'FSTYPE', '/tmp'), 'tmpfs')
    test.assertIn('noatime', command('findmnt', '-no', 'OPTIONS', '/').split(','))
    section, journal = '', {}
    for raw in command('systemd-analyze', 'cat-config', 'systemd/journald.conf').splitlines():
        line = raw.strip()
        if line.startswith('['):
            section = line
        elif section == '[Journal]' and '=' in line and not line.startswith(('#', ';')):
            key, value = line.split('=', 1)
            journal[key.strip()] = value.strip()
    for key, value in {'Storage': 'volatile', 'RuntimeMaxUse': '64M', 'ForwardToSyslog': 'no'}.items():
        test.assertEqual(journal.get(key), value)
    properties = dict(line.split('=', 1) for line in command('systemctl', 'show', service,
        '-p', 'StandardOutput,StandardError,RuntimeDirectory,ActiveState').splitlines())
    test.assertEqual(properties['ActiveState'], 'active')
    test.assertEqual(properties['StandardOutput'], 'journal')
    test.assertEqual(properties['StandardError'], 'journal')
    runtime = Path('/run')/properties['RuntimeDirectory']
    test.assertTrue(runtime.is_dir())
    test.assertEqual(command('findmnt', '-T', str(runtime), '-no', 'FSTYPE'), 'tmpfs')
    data = Path(data).resolve(strict=True)
    test.assertNotIn(command('findmnt', '-T', str(data), '-no', 'FSTYPE'), ('tmpfs', 'ramfs'))
    test.assertTrue(data.is_dir())
    return data
