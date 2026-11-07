"""Send the confirmed application version to Plymouth without changing boot files."""
import json
from pathlib import Path
import re
import subprocess



def confirmed_version(root):
    """Use the durable boot recovery target, never an interrupted trial selection."""
    record = json.loads((root/'confirmed.json').read_text(encoding='utf-8'))
    identity = record['slot']
    if not isinstance(identity, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,95}', identity):
        raise ValueError('Invalid confirmed slot')
    slot = root/'slots'/identity
    if slot.is_symlink() or slot.resolve().parent != (root/'slots').resolve():
        raise ValueError('Invalid confirmed slot path')
    release = json.loads((slot/'update-release.json').read_text(encoding='utf-8'))
    version = release['version']
    if not isinstance(version, str) or not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Invalid confirmed version')
    return version



def main(root=Path('/opt/zmalacall-updates'), run=subprocess.run):
    """Missing metadata or an unavailable splash must not hold up startup."""
    try:
        version = confirmed_version(root)
        run(['plymouth', 'display-message', '--text=Zmala v'+version],
            check=True, capture_output=True, text=True, timeout=2)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return False
    return True


if __name__ == '__main__':
    main()
