"""Fixed host-storage contract; operator data cannot add mounts or change owners."""
from dataclasses import dataclass
import json
import posixpath
import re
import stat

PROFILE = 'usr/lib/zmala/host-layout.json'
DATA_MARKER = '.zmala-storage.json'
PACKAGE_DB = 'usr/lib/zmala/slot-dpkg'
VAR_SEED = 'usr/lib/zmala/var-seed'
MAX_PROFILE_BYTES = 8192
MAX_SEED_BYTES = 32*1024**2
MAX_SEED_ENTRIES = 10000
VAR_MIB = 128
TMP_MIB = 128
ROLES = ('server', 'terminal', 'combined')


@dataclass(frozen=True)
class Binding:
    target: str
    saved: str
    uid: int = 0
    gid: int = 0
    mode: int = 0o700
    directory: bool = True
    readonly: bool = False


# @llr LLR-SRV-HOST-009, LLR-TERM-MAINT-036, LLR-SRV-HOST-029, LLR-TERM-MAINT-056
def profile(role):
    if role not in ROLES:
        raise ValueError('Unsupported image role')
    if role == 'combined':
        return {'schema': 1, 'role': role, 'terminal_uid': 1000, 'terminal_gid': 1000,
                'server_uid': 1001, 'server_gid': 1001,
                'package_database': PACKAGE_DB, 'variable_seed': VAR_SEED}
    return {'schema': 1, 'role': role, 'application_uid': 1000, 'application_gid': 1000,
            'package_database': PACKAGE_DB, 'variable_seed': VAR_SEED}


def unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate host-layout field')
        result[key] = value
    return result


# @llr LLR-SRV-HOST-009, LLR-TERM-MAINT-036, LLR-SRV-HOST-029, LLR-TERM-MAINT-056
def decode_profile(body, role, data=False):
    selected = profile(role)
    if not 0 < len(body) <= MAX_PROFILE_BYTES:
        raise ValueError('Host-layout record exceeds its budget')
    value = json.loads(body.decode('utf-8'), object_pairs_hook=unique_fields)
    expected = {'schema': 1, 'role': role} if data else selected
    if (not isinstance(value, dict) or value != expected
            or any(type(value[key]) is not type(item) for key, item in expected.items())):
        raise ValueError('Unsupported or mismatched host-layout record')
    return value


# @llr LLR-SRV-HOST-011, LLR-TERM-MAINT-038, LLR-SRV-HOST-029, LLR-TERM-MAINT-056
def bindings(role):
    profile(role)
    result = [
        Binding('etc/machine-id', 'identity/machine-id', mode=0o644, directory=False, readonly=True),
        Binding('etc/hostname', 'identity/hostname', mode=0o644, directory=False, readonly=True),
        Binding('etc/NetworkManager/system-connections', 'network/profiles'),
        Binding('var/lib/NetworkManager', 'network/state'),
        Binding('var/lib/bluetooth', 'bluetooth'),
        Binding('etc/ssh/keys', 'host/ssh'),
    ]
    if role == 'combined':
        result.extend((
            Binding('etc/zmalacall/operator/terminal', 'host/operator/terminal', gid=1000, mode=0o750),
            Binding('etc/zmalacall/operator/server', 'host/operator/server', gid=1001, mode=0o750),
            Binding('var/lib/zmalacall', 'state/terminal', uid=1000, gid=1000),
            Binding('var/lib/zmalacall-server', 'state/server', uid=1001, gid=1001),
        ))
    else:
        result.extend((Binding('etc/zmalacall/operator', 'host/operator', gid=1000, mode=0o750),
                       Binding('var/lib/zmalacall-server' if role == 'server' else 'var/lib/zmalacall',
                               'state/'+role, uid=1000, gid=1000)))
    if role in ('server', 'combined'):
        result.append(Binding('etc/letsencrypt', 'host/certificates'))
    if role in ('terminal', 'combined'):
        result.append(Binding('var/lib/zmalacall-pairing', 'host/presenter'))
    return tuple(result)


# @llr LLR-SRV-HOST-009, LLR-TERM-MAINT-036
def identity(body, hostname=False):
    if hostname:
        valid = re.fullmatch(rb'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\n?', body)
    else:
        valid = (re.fullmatch(rb'[a-f0-9]{32}\n?', body)
                 and body.rstrip(b'\n') not in (b'0'*32, b'f'*32))
    if not valid:
        raise ValueError('Invalid saved machine identity or hostname')


# @llr LLR-SRV-HOST-009, LLR-SRV-HOST-011, LLR-TERM-MAINT-036, LLR-TERM-MAINT-038
def metadata(info, uid=0, gid=0, mode=None, directory=False):
    correct_type = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if (not correct_type or info.st_uid != uid or info.st_gid != gid
            or (mode is not None and stat.S_IMODE(info.st_mode) != mode)):
        raise ValueError('Incompatible image-state type, ownership or permissions')


# @llr LLR-SRV-HOST-010, LLR-TERM-MAINT-037
def volatile_mounts(root, area):
    """All mutable views are bounded RAM mounts; package state stays in the slot."""
    return (
        ('overlay', 'overlay', root/'etc',
         'lowerdir='+str(root/'etc')+',upperdir='+str(area/'etc-upper')
         +',workdir='+str(area/'etc-work')+',nodev,nosuid'),
        ('tmpfs', 'tmpfs', root/'var', f'mode=0755,nodev,nosuid,size={VAR_MIB}M'),
        ('tmpfs', 'tmpfs', root/'tmp', f'mode=1777,nodev,nosuid,size={TMP_MIB}M'),
    )


# @llr LLR-SRV-HOST-010, LLR-TERM-MAINT-037
def seed_link(relative, target):
    """A vendor-state alias cannot create an unlisted persistent data path."""
    logical = posixpath.normpath(posixpath.join('/var', posixpath.dirname(relative), target))
    if (logical == '/data' or logical.startswith('/data/') or len(target.encode('utf-8')) > 4096
            or '\0' in target):
        raise ValueError('Variable-state seed would bypass selected data bindings')
