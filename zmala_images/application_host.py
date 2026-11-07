"""Offline host-service installation; no daemon starts or factory credentials."""

SOURCES = ('build_tools/linux/developer-access.py', 'build_tools/linux/zmala.plymouth',
           'build_tools/linux/zmala.script', 'zmala_terminal/common/assets/boot-family.png',
           'build_tools/linux/zmalacall-boot-version.service', 'build_tools/linux/boot-version.py')


def install(root, records, role):
    from .application_provision import put, link
    import json
    helper = '/usr/local/libexec/zmala-developer-access'
    put(root, helper[1:], records[SOURCES[0]][0], 0o755)
    put(root, 'etc/zmalacall/developer-access.json', json.dumps({'role': role, 'image': True})+'\n')
    base = '''HostKey /etc/ssh/keys/ssh_host_ed25519_key
PidFile none
UsePAM yes
PermitRootLogin no
KbdInteractiveAuthentication no
PermitEmptyPasswords no
X11Forwarding no
AllowAgentForwarding no
AllowStreamLocalForwarding no
PermitTunnel no
LogLevel ERROR
'''
    units = []

    def service(name, command, extra='', condition=''):
        unit = name+'.service'
        put(root, 'usr/lib/systemd/system/'+unit, '''[Unit]
Description=ZmalaCall controlled developer access
Requires=zmalacall-developer-prepare.service
After=zmalacall-developer-prepare.service network.target
StartLimitIntervalSec=0
'''+condition+'''[Service]
Type=simple
RuntimeDirectory=sshd
RuntimeDirectoryPreserve=yes
KillMode=control-group
ExecStart='''+command+'\n'+extra+'''[Install]
WantedBy=multi-user.target
''')
        units.append(unit)

    put(root, 'usr/lib/systemd/system/zmalacall-developer-prepare.service', '''[Unit]
Description=Prepare private developer identity
After=local-fs.target
Before=zmalacall-server.service zmalacall-terminal.service
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart='''+helper+' prepare\n[Install]\nWantedBy=multi-user.target\n')
    # Startup only creates the per-device identity. Shell/tunnel units have no
    # boot enable link; the live authenticated server setting starts them.
    units.append('zmalacall-developer-prepare.service')
    link(root, 'etc/systemd/system/multi-user.target.wants/zmalacall-developer-prepare.service',
         '/usr/lib/systemd/system/zmalacall-developer-prepare.service')
    rules = []
    if role in ('terminal', 'combined'):
        put(root, 'etc/ssh/zmala-developer-terminal.conf', base+'''Port 2223
ListenAddress 127.0.0.1
AllowUsers zmala
PasswordAuthentication no
PubkeyAuthentication yes
AuthorizedKeysFile none
AuthorizedKeysCommand /usr/local/libexec/zmala-developer-keys %u
AuthorizedKeysCommandUser root
AllowTcpForwarding no
''')
        service('zmalacall-developer-shell', '/usr/sbin/sshd -D -e -f /etc/ssh/zmala-developer-terminal.conf')
        put(root, 'usr/local/libexec/zmala-developer-keys',
            '#!/bin/sh\n[ "$1" = zmala ] || exit 1\nexec /usr/bin/cat /etc/ssh/keys/authorized_keys\n', 0o755)
        service('zmalacall-developer-tunnel', helper+' run', 'Restart=always\nRestartSec=10\nStandardInput=null\n')
        put(root, 'usr/local/libexec/zmala-developer-askpass', '#!/bin/sh\nexec '+helper+' askpass\n', 0o755)
        rules.append('zmalaterminal ALL=(root) NOPASSWD: '+helper+' apply, '+helper+' off')
        # A separate operator identity keeps privileged debugging permissions
        # away from the application service identity. It has no factory key.
        rules.append('zmala ALL=(root) NOPASSWD: ALL')
        for filename in ('zmala.plymouth', 'zmala.script'):
            put(root, 'usr/share/plymouth/themes/zmala/'+filename,
                records['build_tools/linux/'+filename][0].replace(b'\r\n', b'\n'))
        put(root, 'usr/share/plymouth/themes/zmala/boot-family.png', records[SOURCES[3]][0])
        put(root, 'etc/plymouth/plymouthd.conf', '[Daemon]\nTheme=zmala\nShowDelay=0\n')
        put(root, 'usr/local/lib/zmalacall-terminal-host/boot-version.py', records[SOURCES[5]][0])
        put(root, 'usr/lib/systemd/system/zmalacall-boot-version.service', records[SOURCES[4]][0])
        link(root, 'etc/systemd/system/sysinit.target.wants/zmalacall-boot-version.service',
             '/usr/lib/systemd/system/zmalacall-boot-version.service')
        units.append('zmalacall-boot-version.service')
    if role in ('server', 'combined'):
        put(root, 'etc/ssh/zmala-developer-server.conf', base+'''Port 2222
ListenAddress 0.0.0.0
ListenAddress ::
AllowUsers terminal
PasswordAuthentication yes
PubkeyAuthentication no
AllowTcpForwarding remote
GatewayPorts no
PermitListen 127.0.0.1:22001
PermitOpen none
MaxSessions 0
ForceCommand /bin/false
''')
        service('zmalacall-developer', '/usr/sbin/sshd -D -e -f /etc/ssh/zmala-developer-server.conf',
                condition='ConditionPathExists=/etc/ssh/keys/developer-session.json\n')
        # A persisted server activation survives an image reboot; without the
        # private activation record the listener is skipped.
        link(root, 'etc/systemd/system/multi-user.target.wants/zmalacall-developer.service',
             '/usr/lib/systemd/system/zmalacall-developer.service')
        rules.append('zmalaserver ALL=(root) NOPASSWD: '+', '.join(helper+' '+action for action in ('on', 'off', 'status', 'config')))
    put(root, 'etc/sudoers.d/zmalacall-developer', '\n'.join(rules)+'\n', 0o440)
    return units
