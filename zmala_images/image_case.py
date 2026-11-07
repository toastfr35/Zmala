"""Enforce the terminal roles' Argon case configuration in root and boot slots."""
import json

from zmala_system import host_storage
from .application_provision import uses_argon


def selected(root, role):
    metadata = json.loads(host_storage.safe(root, 'usr/lib/zmala-application-build.json').read_text())
    if metadata.get('role') != role:
        raise ValueError('Application case metadata has a different role')
    argon_one = uses_argon(role)
    if metadata.get('argon_one') is not argon_one:
        raise ValueError('Application case metadata differs from the required role hardware')
    if role in ('terminal', 'combined'):
        settings = host_storage.safe(root, 'etc/zmalacall/terminal.conf').read_text().splitlines()
        flags = [line for line in settings if line.startswith('ZMALA_ARGON_ONE_FAN=')]
        if flags != ['ZMALA_ARGON_ONE_FAN='+str(int(argon_one))]:
            raise ValueError('Application case selection differs from terminal configuration')
    if argon_one:
        groups = host_storage.safe(root, 'etc/group').read_text().splitlines()
        if not any(row.split(':')[0] == 'i2c' and 'zmalaterminal' in row.split(':')[3].split(',')
                   for row in groups if len(row.split(':')) == 4):
            raise ValueError('Argon terminal lacks I2C group membership')
        if host_storage.safe(root, 'etc/modules-load.d/zmala-i2c.conf').read_text() != 'i2c-dev\n':
            raise ValueError('Argon image lacks I2C device module loading')
        if host_storage.safe(root, 'etc/udev/rules.d/99-zmalacall-i2c.rules').read_text() != (
                'SUBSYSTEM=="i2c-dev", KERNEL=="i2c-1", GROUP="i2c", MODE="0660"\n'):
            raise ValueError('Argon image lacks restricted I2C device access')
    return argon_one


def boot_parameters(argon_one):
    return 'dtparam=i2c_arm=on\n' if argon_one else ''


def configure_tree(root, staging, argon_one, run):
    if not argon_one:
        return
    # Apply the locked tree's named override, not a hard-coded node or phandle.
    run(['chroot', root, '/usr/bin/dtmerge', '/tmp/zmala-image-dtb/board.dtb',
         '/tmp/zmala-image-dtb/argon.dtb', '-', 'i2c_arm=on'])
    tree = '/tmp/zmala-image-dtb/argon.dtb'
    node = run(['chroot', root, '/usr/bin/fdtget', tree, '/aliases', 'i2c1'],
               capture_output=True, text=True).stdout.strip()
    status = run(['chroot', root, '/usr/bin/fdtget', tree, node, 'status'],
                 capture_output=True, text=True).stdout.strip()
    if status != 'okay':
        raise ValueError('Selected Argon boot tree does not enable I2C bus 1')
    (staging/'argon.dtb').replace(staging/'board.dtb')
