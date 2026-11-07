"""Minimal cross-repository package records for offline provisioning tests."""
from zmala_images import application_host, application_provision, project


def provisioning_records():
    records = {name: (b'# fixture\n', False) for name in application_provision.HOST_FILES.values()}
    records.update({name: ((project.ROOT/name).read_bytes(), False)
                    for name in application_host.SOURCES if name.startswith('build_tools/linux/')})
    records[application_host.SOURCES[3]] = b'terminal boot artwork fixture', False
    for name in ('terminal', 'display', 'pairing', 'cec', 'compositor', 'server'):
        records['build_tools/linux/zmalacall-'+name+'.service'] = b'[Service]\n', False
    records['build_tools/linux/zmalacall-terminal.service'] = (
        b'[Service]\nUser=@USER@\nExecStopPost=-/usr/bin/python3 '
        b'/usr/local/lib/zmalacall-terminal-host/argon_fan.py\n', False)
    records['build_tools/linux/low-wear-swap.conf'] = b'[Main]\nMechanism=zram\n', False
    records['build_tools/linux/70-zmalacall-presenter.rules'] = b'# presenter fixture\n', False
    records['zmala_terminal/linux/99-zmalacall-c20.rules'] = b'# C20 fixture\n', False
    return records
