"""Deploy a disposable Terminal app through an existing operator SSH tunnel."""
import argparse
import hashlib
from pathlib import Path
import re
import shlex
import subprocess

from . import terminal_test_remote as remote


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ssh', default='ssh', help='SSH executable or operator wrapper')
    parser.add_argument('--ssh-arg', action='append', default=[], help='Repeat for SSH options and destination')
    actions = parser.add_subparsers(dest='action', required=True)
    deploy = actions.add_parser('deploy')
    deploy.add_argument('package', type=Path)
    deploy.add_argument('--sha256', required=True)
    actions.add_parser('status')
    actions.add_parser('restore')
    args = parser.parse_args()
    source = Path(remote.__file__).read_bytes()
    bootstrap = ('import sys; source=sys.stdin.buffer.read(int(sys.argv.pop(1))); '
                 'exec(compile(source, "<terminal-test>", "exec"), {"__name__":"__main__", "SOURCE":source})')
    runner = ['/usr/bin/sudo', '-n', '/usr/bin/python3', '-IBc', bootstrap, str(len(source)), args.action]
    ssh = [args.ssh, *args.ssh_arg]
    if args.action != 'deploy':
        return subprocess.run([*ssh, shlex.join(runner)], input=source).returncode
    if not re.fullmatch('[0-9a-f]{64}', args.sha256):
        parser.error('Expected a lowercase SHA-256 digest')
    if args.package.is_symlink() or not args.package.is_file():
        parser.error('Expected a regular Terminal ARM64 package')
    with args.package.open('rb') as package:
        payload = package.read(remote.MAX_ARCHIVE+1)
    if not 0 < len(payload) <= remote.MAX_ARCHIVE or hashlib.sha256(payload).hexdigest() != args.sha256:
        parser.error('Package size or digest differs from the deployment input')
    return subprocess.run([*ssh, shlex.join([*runner, str(len(payload)), args.sha256])],
                          input=source+payload).returncode


if __name__ == '__main__':
    raise SystemExit(main())
