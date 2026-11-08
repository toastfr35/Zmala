"""Versioned build intent and lab configuration, separate from package locks."""
import hashlib
import json
from pathlib import Path
import re

from zmala_system.host_layout import ROLES

ROOT = Path(__file__).resolve().parents[1]


def image_version():
    metadata = json.loads((ROOT/'VERSION.json').read_text(encoding='utf-8'))
    version = metadata.get('version') if isinstance(metadata, dict) else None
    if not isinstance(version, str) or not re.fullmatch(r'(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*)){2}', version):
        raise ValueError('Invalid SD image version in VERSION.json')
    return version


def profiles():
    value = json.loads((ROOT/'zmala_images/profiles.json').read_text())
    if (value['schema'] != 1 or value['architecture'] != 'arm64'
            or value['distribution'] != 'trixie' or value['board'] != 'pi4'
            or value['qualification'] != 'development-only'
            or set(value['roles']) != set(ROLES)):
        raise ValueError('Unknown or unqualified build profile')
    return value


def packages(role):
    profile = profiles()
    config = profile['roles'][role]
    if role == 'combined':
        if config.get('components') != ['terminal', 'server'] or config['extra_packages']:
            raise ValueError('Combined package intent must be the exact standalone union')
        return sorted(set(packages('terminal')) | set(packages('server')))
    result = {'rauc='+profile['rauc_version'], 'dbus', 'systemd', 'ca-certificates',
              'libubootenv-tool'}
    if 'packages_file' in config:
        result.update(line.strip() for line in (ROOT/config['packages_file']).read_text().splitlines()
                      if line.strip() and not line.startswith('#'))
    result.update(config['extra_packages'])
    if not all(re.fullmatch(r'[a-z0-9][a-z0-9+.-]*(?:=[A-Za-z0-9:+.~-]+)?', p) for p in result):
        raise ValueError('Invalid package name/version')
    return sorted(result)


def lab_config(role):
    """Minimal boot probe only: deliberately no production application or RAUC activation.

    Upstream image-rota's mutable /var and selector policy are not adopted as
    production design. This output exists to establish hardware boot feasibility.
    Role package intent is emitted separately for later locked image builds.
    """
    profiles()['roles'][role]
    return f'''# Development boot probe; not a Zmala installer or update candidate.
# Package resolution is not locked. Never publish to a stable image/feed.
device:
  layer: rpi4
artefact:
  version: unqualified-{role}-probe1
image:
  layer: image-rota
  name: zmala-{role}-boot-probe
  rootfs_type: ext4
  boot_part_size: 512M
  system_part_size: 8G
  data_part_size: 4G
layer:
  base: trixie-minbase
  eeprom_scope: zmala-probe-eeprom
packages:
  - rauc={profiles()['rauc_version']}
'''


def emit_lab(role, output):
    output = Path(output)
    if output.exists():
        raise ValueError('Use a new output directory')
    output.mkdir(parents=True)
    # Requiring a project-local layer makes omission of -S fail during layer
    # resolution, rather than silently assembling an unmasked probe. Emit the
    # standalone hook with LF, including from Windows checkouts.
    layer = output/'layer'
    layer.mkdir()
    (layer/'zmala-probe-eeprom.yaml').write_text('''# METABEGIN
# X-Env-Layer-Name: zmala-probe-eeprom
# X-Env-Layer-Desc: Keep EEPROM updates outside diagnostic probe scope
# X-Env-Layer-Category: policy
# X-Env-Layer-Version: 1.0.0
# X-Env-Layer-Requires: trixie-minbase
# METAEND
---
''', encoding='utf-8', newline='\n')
    hooks = layer/'zmala-probe-eeprom.d/hooks'
    hooks.mkdir(parents=True)
    hook = hooks/'customize99-zmala-eeprom-scope'
    hook.write_text(Path(__file__).with_name('eeprom_policy.py').read_text(encoding='utf-8'),
                    encoding='utf-8', newline='\n')
    hook.chmod(0o755)
    (output/'probe.yaml').write_text(lab_config(role), encoding='utf-8', newline='\n')
    (output/'package-intent.txt').write_text('\n'.join(packages(role))+'\n', encoding='utf-8')
    (output/'status.json').write_text(json.dumps({
        'schema': 1, 'role': role, 'purpose': 'minimal-boot-probe',
        'production_eligible': False, 'application_installed': False,
        'packages_locked': False, 'hardware_qualified': False,
        'required_project_source': '.', 'eeprom_scope_hook_emitted': True,
        'blockers': ['boot-selector-commit', 'early-watchdog', 'package-lock',
                     'product-provisioning', 'data-mount-policy', 'hardware-qualification']
    }, indent=2)+'\n', encoding='utf-8')
    return output


def package_locks():
    """Verify reviewed intent/lock synchronization without network or binaries."""
    folder = ROOT/'zmala_images/locks'
    index = json.loads((folder/'index.json').read_text())
    if (index['schema'] != 1 or index['purpose'] != 'requested-package-closure'
            or index['image_qualified'] is not False or set(index['roles']) != set(ROLES)):
        raise ValueError('Unknown role package lock index')
    common_base(index)
    shared = {}
    for role, record in index['roles'].items():
        if record['file'] != role+'.json':
            raise ValueError('Unexpected role lock filename')
        path = folder/record['file']
        if path.stat().st_size > 4*1024**2 or path.is_symlink():
            raise ValueError('Invalid role package lock')
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != record['sha256']:
            raise ValueError('Role package lock digest changed')
        manifest = json.loads(body)
        if (manifest['requested'] != packages(role) or manifest['schema'] != 1
                or manifest['architecture'] != profiles()['architecture']
                or manifest['distribution'] != profiles()['distribution']
                or manifest['image_qualified'] is not False
                or len(manifest['packages']) != record['archives']
                or sum(p['bytes'] for p in manifest['packages']) != record['archive_bytes']):
            raise ValueError('Package intent and reviewed closure disagree; refresh intake through review')
        for package in manifest['packages']:
            key = package['package']
            identity = (package['version'], package['architecture'], package['sha256'])
            if key in shared and shared[key] != identity:
                raise ValueError('Shared role package identities disagree; review the closures together')
            shared[key] = identity
    return index


def common_base(index=None):
    """Anchor observed base intent and closure without accepting a live inventory.

    The ledger hash identifies a reviewed clean pre-boot probe; it is not evidence
    of every future image package. Toolchain and full builder consumption remain
    separate qualification gates.
    """
    from . import base_intent, sources
    folder = ROOT/'zmala_images/locks'
    if index is None:
        index = json.loads((folder/'index.json').read_text())
    record = index['base']
    values = []
    for key, filename in (('intent', 'base-intent.json'), ('lock', 'base.json')):
        path = folder/filename
        if (record[key+'_file'] != filename or path.is_symlink() or not path.is_file()
                or path.stat().st_size > 4*1024**2):
            raise ValueError('Invalid common-base input')
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != record[key+'_sha256']:
            raise ValueError('Common-base input digest changed')
        values.append(json.loads(body))
    intent, lock = values
    requested = intent['requested']
    names = sorted(p.split('=')[0] for p in requested)
    if (intent['schema'] != 1 or intent['purpose'] != 'observed-common-base-intent'
            or intent['architecture'] != 'arm64' or intent['distribution'] != 'trixie'
            or intent['image_qualified'] is not False
            or intent['imagegen_commit'] != sources.pins()['imagegen']['commit']
            or not re.fullmatch('[a-f0-9]{64}', intent['ledger_sha256'])
            or not 0 < len(requested) <= 5000 or requested != sorted(set(requested))
            or not all(re.fullmatch(base_intent.NAME+'='+base_intent.VERSION, p) for p in requested)
            or len({p.split('=')[0] for p in requested}) != len(requested)
            or lock['schema'] != 1 or lock['purpose'] != 'requested-package-closure'
            or lock['architecture'] != 'arm64' or lock['distribution'] != 'trixie'
            or lock['image_qualified'] is not False or lock['requested'] not in (requested, names)
            or len(lock['packages']) != record['archives']
            or sum(p['bytes'] for p in lock['packages']) != record['archive_bytes']):
        raise ValueError('Common-base intent and reviewed closure disagree')
    installed = {p['package']: p['version'] for p in lock['packages']}
    selections = set(installed) | {name+'='+version for name, version in installed.items()}
    if not set(lock['requested']) <= selections:
        raise ValueError('Common-base closure is missing installed selections')
    return intent
