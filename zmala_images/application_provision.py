"""Declarative provisioning of a disposable offline root, without live installers."""
import json
from pathlib import Path

from zmala_system import host_layout, host_storage
from . import application_inputs, application_host

TERMINAL = 'opt/zmalacall/releases/image'
SERVER = 'opt/zmalacall-server/releases/image'
HOST_FILES = {
    'prepare-display.py': 'build_tools/linux/prepare-display.py',
    'pair-presenter.py': 'build_tools/linux/pair-presenter.py',
    'picom.conf': 'build_tools/linux/picom.conf',
    'cec_observer.py': 'zmala_terminal/linux/cec_observer.py',
    'cec_device.py': 'zmala_terminal/linux/cec_device.py',
    'argon_fan.py': 'zmala_terminal/linux/argon_fan.py',
}


def target(root, name):
    relative = application_inputs.path_name(name)
    parent = host_storage.safe(root, str(relative.parent))
    parent.mkdir(parents=True, exist_ok=True)
    return parent/relative.name


def put(root, name, body, mode=0o644):
    path = target(root, name)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError('Unsafe offline configuration destination')
    path.write_bytes(body.encode() if isinstance(body, str) else body)
    path.chmod(mode)


def link(root, name, value):
    path = target(root, name)
    if path.exists() or path.is_symlink():
        raise ValueError('Preexisting offline link destination')
    path.symlink_to(value)


def install_sources(root, name, records):
    destination = host_storage.safe(root, name)
    if destination.exists() or destination.is_symlink():
        raise ValueError('Application release destination must be new')
    destination.mkdir(parents=True)
    application_inputs.write_files(destination, records)


def enable(root, unit):
    path = target(root, 'etc/systemd/system/multi-user.target.wants/'+unit)
    if path.is_symlink() and str(path.readlink()) in ('/lib/systemd/system/'+unit, '/usr/lib/systemd/system/'+unit):
        return
    link(root, 'etc/systemd/system/multi-user.target.wants/'+unit, '/usr/lib/systemd/system/'+unit)


def uses_argon(role):
    host_layout.profile(role)
    return role in ('terminal', 'combined')


def accounts(records, role):
    """Return fixed locked service identities, rejecting UID/name collisions."""
    argon_one = uses_argon(role)
    parsed = {}
    for name, width in (('passwd', 7), ('group', 4), ('shadow', 9), ('gshadow', 4)):
        parsed[name] = [line.split(':') for line in records[name].splitlines()]
        if (any(len(fields) != width for fields in parsed[name])
                or len({fields[0] for fields in parsed[name]}) != len(parsed[name])):
            raise ValueError('Malformed offline account ledger')
    users = [('zmalaterminal', 1000, '/var/lib/zmalacall')] if role in ('terminal', 'combined') else []
    if role in ('server', 'combined'):
        users.append(('zmalaserver', 1001 if role == 'combined' else 1000, '/var/lib/zmalacall-server'))
        users.append(('terminal', 499, '/nonexistent'))
    if role in ('terminal', 'combined'):
        users.append(('zmala', 1002, '/tmp'))
    for name, uid, home in users:
        if any(row[0] == name or row[2] == str(uid) for row in parsed['passwd']+parsed['group']):
            raise ValueError('Application account collides with the package root')
        if any(row[0] == name for row in parsed['shadow']+parsed['gshadow']):
            raise ValueError('Application credential entry already exists')
        parsed['passwd'].append([name, 'x', str(uid), str(uid), 'Zmala account', home,
                                 '/bin/bash' if name == 'zmala' else '/usr/sbin/nologin'])
        parsed['group'].append([name, 'x', str(uid), ''])
        parsed['shadow'].append([name, '*' if name == 'zmala' else '!', '1', '0', '99999', '7', '', '', ''])
        parsed['gshadow'].append([name, '!', '', ''])
    if role in ('terminal', 'combined'):
        for group in ('audio', 'video', 'render', 'input') + (('i2c',) if argon_one else ()):
            row = next((row for row in parsed['group'] if row[0] == group), None)
            if row is None:
                used = {int(row[2]) for row in parsed['group']}
                gid = next(value for value in range(500, 1000) if value not in used)
                row = [group, 'x', str(gid), '']
                parsed['group'].append(row)
                parsed['gshadow'].append([group, '!', '', ''])
            row[3] = ','.join(filter(None, (row[3], 'zmalaterminal')))
            shadow = next(row for row in parsed['gshadow'] if row[0] == group)
            shadow[3] = ','.join(filter(None, (shadow[3], 'zmalaterminal')))
    return {name: ''.join(':'.join(row)+'\n' for row in rows) for name, rows in parsed.items()}


def provision(root, records, role):
    argon_one = uses_argon(role)
    root = Path(root)
    if root.is_symlink() or not root.is_dir() or root.resolve() != root or root == Path('/'):
        raise ValueError('Expected a new absolute disposable offline root')
    host_layout.profile(role)
    ledgers = {name: host_storage.safe(root, 'etc/'+name).read_text() for name in ('passwd', 'group', 'shadow', 'gshadow')}
    changed = accounts(ledgers, role)
    for name, body in changed.items():
        path = host_storage.safe(root, 'etc/'+name)
        # Retain the distribution's root/shadow group ownership and restrictive modes.
        mode = path.stat().st_mode & 0o777
        put(root, 'etc/'+name, body, mode)
    units, tmpfiles = [], []
    if role in ('server', 'combined'):
        selected = {name: body for name, body in records.items()
                    if name.startswith(('zmala_server/', 'build_tools/', 'vendor/terminal-contracts/'))}
        install_sources(root, SERVER, selected)
        link(root, SERVER+'/zmala_server/data', '/var/lib/zmalacall-server')
        put(root, 'etc/systemd/system/zmalacall-server.service.d/bootstrap.conf',
            '[Service]\nEnvironment=ZMALA_BOOTSTRAP_EXPORT_DIRECTORY=/var/lib/zmalacall-server/bootstrap\n')
        link(root, 'opt/zmalacall-server/current', '/'+SERVER)
        unit = 'zmalacall-server.service'
        put(root, 'usr/lib/systemd/system/'+unit, records['build_tools/linux/'+unit][0])
        units.append(unit)
        tmpfiles += ['d /var/lib/zmalacall-server 0700 zmalaserver zmalaserver -',
                     'd /var/lib/zmalacall-server/bootstrap 0700 zmalaserver zmalaserver -']
    if role in ('terminal', 'combined'):
        selected = {name: body for name, body in records.items()
                    if name.startswith(('zmala_terminal/', 'build_tools/linux/', 'tests/'))}
        install_sources(root, TERMINAL, selected)
        link(root, TERMINAL+'/zmala_terminal/data', '/var/lib/zmalacall')
        link(root, 'opt/zmalacall/current', '/'+TERMINAL)
        for filename, original in HOST_FILES.items():
            put(root, 'usr/local/lib/zmalacall-terminal-host/'+filename, records[original][0])
        for component in ('terminal', 'display', 'pairing', 'cec', 'compositor'):
            unit = 'zmalacall-'+component+'.service'
            body = records['build_tools/linux/'+unit][0].replace(b'@USER@', b'zmalaterminal')
            put(root, 'usr/lib/systemd/system/'+unit, body)
            units.append(unit)
        put(root, 'etc/zmalacall/terminal.conf',
            'ZMALA_USER=zmalaterminal\nZMALA_WIFI_MODE=connect\nZMALA_DISPLAY_MODE=1280x720\n'
            + 'ZMALA_ARGON_ONE_FAN='+str(int(argon_one))+'\n')
        if argon_one:
            put(root, 'etc/modules-load.d/zmala-i2c.conf', 'i2c-dev\n')
            put(root, 'etc/udev/rules.d/99-zmalacall-i2c.rules',
                'SUBSYSTEM=="i2c-dev", KERNEL=="i2c-1", GROUP="i2c", MODE="0660"\n')
        for original, destination in (
                ('build_tools/linux/70-zmalacall-presenter.rules', 'etc/udev/rules.d/70-zmalacall-presenter.rules'),
                ('zmala_terminal/linux/99-zmalacall-c20.rules', 'etc/udev/rules.d/99-zmalacall-c20.rules')):
            put(root, destination, records[original][0])
        put(root, 'etc/polkit-1/rules.d/49-zmalacall-network.rules', '''polkit.addRule(function(action, subject) {
    var allowed = ["org.freedesktop.NetworkManager.settings.modify.system",
        "org.freedesktop.NetworkManager.network-control",
        "org.freedesktop.NetworkManager.enable-disable-wifi", "org.freedesktop.NetworkManager.wifi.scan"];
    if (subject.user == "zmalaterminal" && allowed.indexOf(action.id) >= 0)
        return polkit.Result.YES;
});
''')
        power_policy = records.get('build_tools/linux/49-zmalacall-power.rules')
        if power_policy:
            put(root, 'etc/polkit-1/rules.d/49-zmalacall-power.rules',
                power_policy[0].replace(b'@USER@', b'zmalaterminal'))
        tmpfiles.append('d /var/lib/zmalacall 0700 zmalaterminal zmalaterminal -')
        # An explicitly optional board-specific workaround is installed only when
        # the selected distribution's driver implements that path.
        driver = root/'usr/lib/xorg/modules/drivers/modesetting_drv.so'
        if driver.is_file() and b'msdri3' in driver.read_bytes():
            put(root, 'etc/X11/xorg.conf.d/21-zmalacall-pi4.conf', records['build_tools/linux/21-zmalacall-pi4.conf'][0])
    put(root, 'usr/lib/tmpfiles.d/zmala-appliance.conf', '\n'.join(tmpfiles)+'\n')
    put(root, 'etc/rpi/swap.conf.d/90-zmalacall-low-wear.conf', records['build_tools/linux/low-wear-swap.conf'][0])
    host_units = application_host.install(root, records, role)
    # Only one network manager owns the persistent network bindings. Ordinary
    # SSH stays off; the isolated developer listeners have their own lifecycle.
    for unit in ('ssh.service', 'ssh.socket', 'systemd-networkd.service', 'systemd-networkd.socket',
                 'systemd-networkd-wait-online.service', 'getty@tty1.service', 'getty@tty7.service',
                 'display-manager.service', 'zmalacall-updater.service', 'zmalacall-update-recover.service'):
        path = target(root, 'etc/systemd/system/'+unit)
        if path.exists() or path.is_symlink():
            if not path.is_symlink():
                raise ValueError('Unexpected existing host service override')
            path.unlink()
        path.symlink_to('/dev/null')
    for unit in units+['NetworkManager.service']:
        if not host_storage.safe(root, 'usr/lib/systemd/system/'+unit).is_file():
            raise ValueError('Missing selected application/network unit: '+unit)
        enable(root, unit)
    if role in ('terminal', 'combined'):
        path = target(root, 'etc/systemd/system/multi-user.target.wants/bluetooth.service')
        if not path.exists() and not path.is_symlink():
            path.symlink_to('/usr/lib/systemd/system/bluetooth.service')
    result = {'role': role, 'units': units+host_units, 'argon_one': argon_one, 'legacy_app_updater_enabled': False,
              'developer_access_installed': True, 'boot_theme_installed': role in ('terminal', 'combined'),
              'ssh_enabled': False, 'joint_health_implemented': False, 'secure_relay_configured': False}
    put(root, 'usr/lib/zmala-application-build.json', json.dumps(result, indent=2)+'\n')
    return result
