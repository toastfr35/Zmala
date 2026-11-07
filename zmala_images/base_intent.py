"""Capture exact package intent from a clean offline base ledger, not a live Pi.

This pins observed package inputs; it does not prove that a ledger describes
every file in an image, or make the upstream builder consume those inputs.
"""
import hashlib
import json
from pathlib import Path
import re
import stat

from . import package_lock, sources

MAX_LEDGER_BYTES = 16*1024**2
NAME = r'[a-z0-9][a-z0-9+.-]*'
VERSION = r'[A-Za-z0-9:+.~-]+'
SCALARS = {'Package', 'Version', 'Architecture', 'Status'}


def read_ledger(path, expected_sha256):
    """Reject special files before opening and require the caller's known digest."""
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_LEDGER_BYTES:
        raise ValueError('Expected a bounded regular offline package ledger')
    body = path.read_bytes()
    if (len(body) > MAX_LEDGER_BYTES or not re.fullmatch('[a-f0-9]{64}', expected_sha256)
            or hashlib.sha256(body).hexdigest() != expected_sha256):
        raise ValueError('Offline package ledger digest mismatch')
    return body.decode('utf-8')


def selections(text):
    """Accept only complete installed records; retain exact versions, not holds.

    Dpkg's first Status token is the desired action, not the current state:
    'purge ok installed' is still installed. Half-configured/removed entries
    are refused rather than silently omitted from a purported clean base.
    """
    previous = None
    for line in text.splitlines():
        if line.startswith((' ', '\t')):
            if previous is None or previous in SCALARS:
                raise ValueError('Ambiguous package ledger continuation')
        elif line:
            previous = line.partition(':')[0]
        else:
            previous = None
    records = package_lock.paragraphs(text)
    if not 0 < len(records) <= package_lock.MAX_PACKAGES:
        raise ValueError('Empty or oversized package ledger')
    result = {}
    for record in records:
        if not SCALARS <= record.keys():
            raise ValueError('Incomplete package ledger record')
        name, version = record['Package'], record['Version']
        if (not re.fullmatch(NAME, name) or not re.fullmatch(VERSION, version)
                or record['Architecture'] not in ('arm64', 'all')
                or record['Status'] not in {action+' ok installed' for action in
                                           ('install', 'hold', 'deinstall', 'purge', 'unknown')}
                or name in result):
            raise ValueError('Invalid, duplicate or unfinished package ledger record')
        result[name] = version
    return sorted(name+'='+version for name, version in result.items())


def capture(path, expected_sha256):
    requested = selections(read_ledger(path, expected_sha256))
    return {'schema': 1, 'purpose': 'observed-common-base-intent',
            'architecture': 'arm64', 'distribution': 'trixie',
            'imagegen_commit': sources.pins()['imagegen']['commit'],
            'ledger_sha256': expected_sha256, 'requested': requested,
            'image_qualified': False}


def emit(path, expected_sha256, output):
    value = capture(path, expected_sha256)
    # Exclusive creation preserves an earlier reviewed capture on failure.
    with Path(output).open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True)+'\n')
    return value
