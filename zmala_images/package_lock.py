"""Isolated, download-only APT intake and retained archive verification.

This is build tooling. It never installs a package or changes host APT settings.
The recorded closure covers the requested package intent, not a complete image.
"""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
from urllib.parse import urlsplit

MAX_BYTES = 4*1024**3
MAX_PACKAGES = 5000
PACKAGE = r'[a-z0-9][a-z0-9+.-]*(?:=[A-Za-z0-9:+.~-]+)?'
ARCHIVE = r'[A-Za-z0-9+_.%~-]+\.deb'
RELEASES = {
    'deb.debian.org_debian_dists_trixie_InRelease': ('debian', 'trixie'),
    'deb.debian.org_debian_dists_trixie-updates_InRelease': ('debian', 'trixie-updates'),
    'deb.debian.org_debian-security_dists_trixie-security_InRelease': ('debian', 'trixie-security'),
    'archive.raspberrypi.com_debian_dists_trixie_InRelease': ('raspberrypi', 'trixie'),
}


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def paragraphs(text):
    """Parse Debian control fields, ignoring continuation text we do not consume."""
    result, fields = [], {}
    for line in [*text.splitlines(), '']:
        if not line:
            if fields:
                result.append(fields)
                fields = {}
        elif not line.startswith((' ', '\t')):
            name, sep, value = line.partition(':')
            if not sep or name in fields:
                raise ValueError('Invalid or duplicate Debian control field')
            fields[name] = value.strip()
    return result


def plan(text):
    files, total = {}, 0
    for line in text.splitlines():
        if not line.startswith("'"):
            continue
        parts = shlex.split(line)
        if len(parts) not in (3, 4):
            raise ValueError('Unexpected APT URI output')
        # Some security indexes omit legacy MD5Sum entirely. We use this output
        # for URLs/size budgets, never as the archive authenticity decision.
        uri, filename, size = parts[:3]
        url = urlsplit(uri)
        if (url.scheme != 'https' or url.hostname not in ('deb.debian.org', 'archive.raspberrypi.com')
                or url.username or url.password or url.port not in (None, 443)
                or not re.fullmatch(ARCHIVE, filename) or filename in files):
            raise ValueError('Unexpected package download source or filename')
        length = int(size)
        total += length
        if length <= 0 or total > MAX_BYTES or len(files) >= MAX_PACKAGES:
            raise ValueError('Package closure exceeds download budget')
        files[filename] = {'uri': uri, 'bytes': length}
    if not files:
        raise ValueError('APT resolved an empty package closure')
    return files


def apt_options(root):
    """All state, cache, sources and logs are private; no host hooks are loaded."""
    settings = {
        'Dir': str(root/'apt'), 'Dir::State::status': str(root/'apt/status'),
        'Dir::State::lists': str(root/'apt/lists'), 'Dir::Cache::archives': str(root/'archives'),
        'Dir::Cache': str(root/'apt/cache'),
        'Dir::Log': str(root/'logs'), 'Dir::Etc::sourcelist': str(root/'sources.sources'),
        'Dir::Etc::sourceparts': '-', 'Dir::Etc::main': '-', 'Dir::Etc::parts': '-',
        'APT::Architecture': 'arm64',
        'APT::Install-Recommends': 'false', 'APT::Install-Suggests': 'false',
        'APT::Get::AllowUnauthenticated': 'false', 'APT::Update::Error-Mode': 'any',
        'Acquire::AllowInsecureRepositories': 'false',
        'Acquire::AllowDowngradeToInsecureRepositories': 'false',
        'Acquire::Retries': '2', 'Acquire::https::Timeout': '30',
    }
    return [value for name, setting in settings.items() for value in ('-o', name+'='+setting)]


def run(args, timeout=600, apt_config='/dev/null', check=True):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                          check=check, env={**os.environ, 'LC_ALL': 'C', 'APT_CONFIG': str(apt_config)})


def apt_run(root, args, timeout=600):
    # APT_CONFIG is read before system apt.conf.d; command-line options alone
    # are too late to prevent loading a host's update/install hook definitions.
    return run([args[0], *apt_options(root), *args[1:]], timeout, root/'apt.conf')


def prepare(root, debian_keyring, raspberrypi_keyring):
    if root.exists():
        raise ValueError('Use a new empty intake directory')
    for key in (debian_keyring, raspberrypi_keyring):
        if key.is_symlink() or not key.is_file() or not 0 < key.stat().st_size <= 4*1024**2:
            raise ValueError('Expected a trusted public archive keyring file')
    root.mkdir(parents=True)
    for directory in ('apt/lists/partial', 'apt/cache', 'archives/partial', 'logs', 'keyrings', 'empty.d'):
        (root/directory).mkdir(parents=True, exist_ok=True)
    (root/'apt/status').write_text('')
    (root/'apt.conf').write_text(f'''Dir::Etc::parts "{(root/'empty.d').as_posix()}";
Dir::Etc::main "{(root/'no-host-config').as_posix()}";
#clear APT::Architectures;
APT::Architecture "arm64";
APT::Architectures {{ "arm64"; }};
''')
    for name, source in (('debian', debian_keyring), ('raspberrypi', raspberrypi_keyring)):
        shutil.copyfile(source, root/'keyrings'/(name+'.gpg'))
    entries = []
    for uri, suites, components, key in (
        ('https://deb.debian.org/debian', 'trixie trixie-updates', 'main contrib non-free non-free-firmware', 'debian'),
        ('https://deb.debian.org/debian-security', 'trixie-security', 'main contrib non-free non-free-firmware', 'debian'),
        ('https://archive.raspberrypi.com/debian', 'trixie', 'main', 'raspberrypi')):
        entries.append(f'Types: deb\nURIs: {uri}\nSuites: {suites}\nComponents: {components}\n'
                       f'Architectures: arm64\nSigned-By: {root}/keyrings/{key}.gpg\n')
    (root/'sources.sources').write_text('\n'.join(entries))


def verified_signers(result):
    """Accept a known valid signature during archive-key overlap, like APT.

    gpgv returns 2 for additional unknown rollover keys even when an existing
    archive key verifies the same payload. Only that specific extra-error case
    is accepted; malformed/bad/expired/revoked signatures remain a rejection.
    """
    events = [line.split()[1:] for line in result.stdout.splitlines() if line.startswith('[GNUPG:] ')]
    blocked = {'BADSIG', 'EXPSIG', 'EXPKEYSIG', 'REVKEYSIG', 'KEYEXPIRED', 'SIGEXPIRED',
               'NODATA', 'BADARMOR', 'ERROR', 'FAILURE'}
    if any(event and event[0] in blocked for event in events):
        raise ValueError('Invalid repository signature')
    signers = {event[1] for event in events if len(event) > 1 and event[0] == 'VALIDSIG'
               and re.fullmatch('[A-F0-9]{40,64}', event[1])}
    errors = [event for event in events if event and event[0] == 'ERRSIG']
    missing = {event[1] for event in events if len(event) == 2 and event[0] == 'NO_PUBKEY'}
    if (not signers or result.returncode not in (0, 2)
            or any(len(event) < 7 or event[6] != '9' for event in errors)
            or {event[1] for event in errors} != missing
            or (result.returncode == 2 and not missing)):
        raise ValueError('Repository lacks a valid signature from the selected archive keyring')
    return sorted(signers)


def signed_indexes(root):
    paths = {p.name: p for p in (root/'apt/lists').glob('*InRelease')}
    if set(paths) != set(RELEASES):
        raise ValueError('Authenticated repository set is incomplete')
    records = []
    for name, (key, codename) in RELEASES.items():
        path = paths[name]
        result = run(['gpgv', '--status-fd', '1', '--keyring', str(root/'keyrings'/(key+'.gpg')), str(path)], check=False)
        signers = verified_signers(result)
        if not signers or '\nCodename: '+codename+'\n' not in path.read_text():
            raise ValueError('Repository signature/codename mismatch')
        records.append({'file': name, 'sha256': digest(path), 'signers': signers})
    return records


def intake(requested, output, debian_keyring, raspberrypi_keyring):
    if platform.system() != 'Linux':
        raise ValueError('Package intake requires Linux APT; verification is portable')
    requested = sorted(set(requested))
    if not requested or not all(re.fullmatch(PACKAGE, p) for p in requested):
        raise ValueError('Invalid package intent')
    root = Path(output).absolute()
    prepare(root, Path(debian_keyring), Path(raspberrypi_keyring))
    # --download-only and the isolated empty status database prevent host installs.
    apt_run(root, ['apt-get', 'update'])
    repositories = signed_indexes(root)
    downloads = plan(apt_run(root, ['apt-get', '--print-uris', '--download-only', '--yes',
                          'install', *requested]).stdout)
    if shutil.disk_usage(root).free < sum(p['bytes'] for p in downloads.values())+256*1024**2:
        raise ValueError('Not enough space for the bounded package intake')
    apt_run(root, ['apt-get', '--download-only', '--yes', 'install', *requested], timeout=1800)
    archives = {p.name: p for p in (root/'archives').glob('*.deb')}
    if set(archives) != set(downloads):
        raise ValueError('Downloaded package set differs from resolved intent')
    candidates = []
    for filename, archive in sorted(archives.items()):
        if archive.is_symlink() or archive.stat().st_size != downloads[filename]['bytes']:
            raise ValueError('Invalid archive length or path')
        control = paragraphs(run(['dpkg-deb', '-f', str(archive), 'Package', 'Version', 'Architecture']).stdout)
        if len(control) != 1 or set(control[0]) != {'Package', 'Version', 'Architecture'}:
            raise ValueError('Invalid archive control identity')
        fields = control[0]
        if (fields['Architecture'] not in ('arm64', 'all')
                or not re.fullmatch('[a-z0-9][a-z0-9+.-]*', fields['Package'])
                or not re.fullmatch('[A-Za-z0-9:+.~-]+', fields['Version'])):
            raise ValueError('Unexpected package identity/architecture')
        checksum = digest(archive)
        candidates.append((filename, archive, fields, checksum))
    # Load authenticated metadata once, rather than rebuilding APT's package
    # cache separately for every archive in a large terminal dependency closure.
    selections = sorted({fields['Package']+'='+fields['Version'] for _, _, fields, _ in candidates})
    records = paragraphs(apt_run(root, ['apt-cache', 'show', *selections]).stdout)
    indexed = {}
    for record in records:
        indexed.setdefault((record.get('Package'), record.get('Version'), record.get('Architecture')), []).append(record)
    packages = []
    for filename, archive, fields, checksum in candidates:
        matched = [record for record in indexed.get((fields['Package'], fields['Version'], fields['Architecture']), [])
                   if record.get('SHA256') == checksum
                   and record.get('Size') == str(archive.stat().st_size)]
        if not matched:
            raise ValueError('Archive is not covered by authenticated package SHA-256 metadata')
        packages.append({'package': fields['Package'], 'version': fields['Version'],
                         'architecture': fields['Architecture'], 'archive': filename,
                         'bytes': archive.stat().st_size, 'sha256': checksum,
                         'uri': downloads[filename]['uri']})
    manifest = {'schema': 1, 'purpose': 'requested-package-closure', 'architecture': 'arm64',
                'distribution': 'trixie', 'requested': requested, 'repositories': repositories,
                'keyrings': {name: digest(root/'keyrings'/(name+'.gpg')) for name in ('debian', 'raspberrypi')},
                'packages': packages, 'image_qualified': False}
    (root/'packages.lock.json').write_text(json.dumps(manifest, indent=2, sort_keys=True)+'\n')
    verify(root, digest(root/'packages.lock.json'))
    return manifest


def verify(folder, expected_sha256):
    """Fail closed on missing, renamed, added or changed retained archives."""
    root = Path(folder)
    path = root/'packages.lock.json'
    if (root.is_symlink() or path.is_symlink() or not path.is_file() or path.stat().st_size > 4*1024**2
            or not re.fullmatch('[a-f0-9]{64}', expected_sha256) or digest(path) != expected_sha256):
        raise ValueError('Invalid package lock file')
    value = json.loads(path.read_text())
    if (value['schema'] != 1 or value['purpose'] != 'requested-package-closure'
            or value['architecture'] != 'arm64' or value['distribution'] != 'trixie'
            or value['image_qualified'] is not False or not 0 < len(value['packages']) <= MAX_PACKAGES):
        raise ValueError('Unknown package lock format')
    expected, total = set(), 0
    if any((root/name).is_symlink() for name in ('archives', 'keyrings', 'apt', 'apt/lists')):
        raise ValueError('Linked package cache is not allowed')
    for record in value['packages']:
        name = record['archive']
        if not re.fullmatch(ARCHIVE, name) or name in expected or record['architecture'] not in ('arm64', 'all'):
            raise ValueError('Invalid package identity/path')
        expected.add(name)
        if type(record['bytes']) is not int or record['bytes'] <= 0:
            raise ValueError('Invalid archive byte length')
        total += record['bytes']
        archive = root/'archives'/name
        if (total > MAX_BYTES
                or archive.is_symlink() or not archive.is_file()
                or archive.stat().st_size != record['bytes'] or digest(archive) != record['sha256']):
            raise ValueError('Retained package archive changed or is incomplete')
    if expected != {p.name for p in (root/'archives').glob('*.deb')}:
        raise ValueError('Unexpected retained package archive set')
    if set(value['keyrings']) != {'debian', 'raspberrypi'}:
        raise ValueError('Incomplete retained trust keyrings')
    for name, checksum in value['keyrings'].items():
        key = root/'keyrings'/(name+'.gpg')
        if key.is_symlink() or not key.is_file() or key.stat().st_size > 4*1024**2 or digest(key) != checksum:
            raise ValueError('Retained archive trust changed')
    if len(value['repositories']) != len(RELEASES) or {r['file'] for r in value['repositories']} != set(RELEASES):
        raise ValueError('Retained repository set changed')
    for record in value['repositories']:
        release = root/'apt/lists'/record['file']
        if (release.is_symlink() or not release.is_file()
                or release.stat().st_size > 4*1024**2 or digest(release) != record['sha256']):
            raise ValueError('Retained signed repository metadata changed')
    return value
