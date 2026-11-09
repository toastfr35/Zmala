"""Self-contained remote entry point for the immutable Terminal developer tool."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import time

BASE = Path('/run/zmala-terminal-test')
SESSION = BASE/'session'
RELEASE = SESSION/'release'
DRIVER = SESSION/'deploy.py'
DATA = Path('/var/lib/zmalacall')
STOCK_ROOT = Path('/opt/zmalacall/current')
STOCK = 'zmalacall-terminal.service'
TEST = 'zmalacall-terminal-test.service'
JOB = 'zmalacall-terminal-test-deploy.service'
SHELL = 'zmalacall-developer-shell.service'
UPDATER = 'zmala-system-updater.service'
MAX_ARCHIVE = 64*1024**2
MAX_TREE = 128*1024**2
RESERVE = 64*1024**2
NATIVE_SUFFIXES = {'.c', '.cpp', '.cc', '.cxx', '.h', '.hpp', '.patch'}
BUILDERS = {'build_tools/linux/build-media.sh', 'build_tools/linux/build-turn.py'}
RUNTIME = ('media/video/libzmala_video.so', 'media/audio/libzmala_speech_audio.so',
           'turn-runtime', 'media/framing-runtime', 'media/models')
TURN_FILES = tuple(Path('zmala_terminal/linux/turn-runtime')/name
                   for name in ('turn-fix.so', 'sdk-version'))


def systemctl(*args, check=True):
    return subprocess.run(['/usr/bin/systemctl', *args], check=check, timeout=25, text=True,
                          stdout=subprocess.PIPE).stdout.strip()


def state(unit, prop='ActiveState'):
    return systemctl('show', '--property='+prop, '--value', unit)


def busy(unit):
    return state(unit) not in ('inactive', 'failed')


def admit():
    if (Path('/usr/lib/zmala/role').read_text().strip() != 'terminal'
            or state(SHELL) != 'active'):
        raise ValueError('Expected an active standalone Terminal Developer Access session')
    if Path('/run/zmalacall-updater/trial.json').exists():
        raise ValueError('A system update trial is in progress')


def keep_space(size):
    if shutil.disk_usage(BASE).free < size+RESERVE:
        raise ValueError('Insufficient space in the Terminal runtime filesystem')


def package_name(value):
    path = PurePosixPath(value)
    if (not value or path.is_absolute() or path.as_posix() != value or '\\' in value
            or any(part in ('', '.', '..') or part.startswith('.') for part in value.split('/'))):
        raise ValueError('Unsafe package path')
    return value


def source_file(name):
    path = PurePosixPath(name)
    return (name.startswith(('zmala_terminal/common/', 'zmala_terminal/linux/', 'build_tools/linux/'))
            and not set(path.parts) & {'data', 'turn-runtime', 'framing-runtime', 'models', '__pycache__'}
            and path.suffix not in ('.so', '.o', '.dll', '.pyc'))


def extract(package, destination):
    with tarfile.open(package, 'r:gz') as archive:
        entries = {}
        total = 0
        for member in archive:
            name = package_name(member.name)
            if name in entries or not member.isfile() or len(entries) >= 5000 or not 0 <= member.size <= MAX_ARCHIVE:
                raise ValueError('Unsupported or oversized package member')
            entries[name] = member
            total += member.size
            if total > MAX_TREE:
                raise ValueError('Expanded test package exceeds its budget')
        keep_space(total)
        metadata = entries['ZMALA-COMPONENT.json']
        if metadata.size > 4096 or entries['build_tools/linux/release-info.json'].size > 4096:
            raise ValueError('Oversized package identity')
        identity = json.load(archive.extractfile(metadata))
        if (not isinstance(identity, dict) or identity.get('schema') != 1 or identity.get('component') != 'terminal'
                or identity.get('architecture') != 'arm64'
                or not re.fullmatch(r'[0-9]{1,8}\.[0-9]{1,8}\.[0-9]{1,8}', identity['version'])
                or not re.fullmatch('[0-9a-f]{40}', identity['commit'])
                or type(identity['sequence']) is not int or identity['sequence'] <= 0):
            raise ValueError('Expected a versioned Terminal ARM64 package')
        for name, member in entries.items():
            if source_file(name):
                path = destination/name
                path.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as stream, path.open('xb') as output:
                    shutil.copyfileobj(stream, output)
        release = json.loads((destination/'build_tools/linux/release-info.json').read_bytes())
        if release != {key: identity[key] for key in ('version', 'commit', 'sequence')}:
            raise ValueError('Package version record does not match')
        for name in ('kiosk-session.py', 'launcher.py'):
            if not (destination/'build_tools/linux'/name).is_file():
                raise ValueError('Package is missing its launcher')
        return release


def native_inputs(root):
    return BUILDERS | {
        path.relative_to(root).as_posix()
        for path in (root/'zmala_terminal').rglob('*')
        if path.is_file() and path.suffix in NATIVE_SUFFIXES
        and source_file(path.relative_to(root).as_posix())
        and not path.relative_to(root).as_posix().startswith('zmala_terminal/linux/native/upstream/')}


def reuse_native(candidate, stock):
    expected = native_inputs(stock)
    if native_inputs(candidate) != expected or any(
            (candidate/name).read_bytes() != (stock/name).read_bytes() for name in expected):
        raise ValueError('Native build inputs changed. This package needs a system image build')
    for index, name in enumerate(RUNTIME):
        relative = Path('zmala_terminal/linux')/name
        if index < 3 and not (stock/relative).exists():
            raise ValueError('The installed native runtime is incomplete')
        if (stock/relative).exists():
            (candidate/relative).parent.mkdir(parents=True, exist_ok=True)
            if name == 'turn-runtime':
                # Bind the stock files into the test namespace at these paths.
                # The preload guard compares /proc/self/maps with the test path
                # and the test root's /run mount is non-executable.
                (candidate/relative).mkdir()
                for filename in TURN_FILES:
                    if not stat.S_ISREG((stock/filename).lstat().st_mode):
                        raise ValueError('The installed TURN runtime is invalid')
                    (candidate/filename).touch()
            else:
                (candidate/relative).symlink_to(stock/relative)
    (candidate/'zmala_terminal/data').symlink_to(DATA, target_is_directory=True)


def snapshot(source, target, user):
    total, count = 0, 0
    target.mkdir(mode=0o700)
    for parent, directories, files in os.walk(source, followlinks=False):
        current = Path(parent)
        destination = target/current.relative_to(source)
        for name in directories+files:
            path = current/name
            info = path.lstat()
            copy = destination/name
            count += 1
            if count > 10000:
                raise ValueError('Terminal profile has too many entries for a temporary copy')
            if stat.S_ISDIR(info.st_mode):
                copy.mkdir(mode=0o700)
            elif stat.S_ISREG(info.st_mode):
                total += info.st_size
                if total > MAX_TREE:
                    raise ValueError('Terminal profile is too large for a temporary copy')
                keep_space(info.st_size)
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(fd, 'rb') as stream, copy.open('xb') as output:
                    if os.fstat(stream.fileno()) != info:
                        raise ValueError('Terminal profile changed during snapshot')
                    remaining = info.st_size
                    while remaining:
                        block = stream.read(min(1024**2, remaining))
                        if not block:
                            raise ValueError('Terminal profile was truncated during snapshot')
                        output.write(block)
                        remaining -= len(block)
                    if stream.read(1):
                        raise ValueError('Terminal profile grew during snapshot')
                copy.chmod(0o600)
            elif (stat.S_ISLNK(info.st_mode) and path.relative_to(source).parent == Path('.config/pulse')
                  and re.fullmatch(r'[a-f0-9]{32}-runtime', path.name)
                  and re.fullmatch(r'/tmp/pulse-[A-Za-z0-9]+', os.readlink(path))):
                # PulseAudio regenerates this link to its per-process runtime.
                # The test profile must never inherit or follow it.
                continue
            else:
                raise ValueError('Terminal profile contains a link or special file')
            os.chown(copy, user.pw_uid, user.pw_gid)
        os.chown(destination, user.pw_uid, user.pw_gid)


def launch():
    turn_bindings = ' '.join(f'{(STOCK_ROOT/path).resolve(strict=True)}:{RELEASE/path}' for path in TURN_FILES)
    subprocess.run(['/usr/bin/systemd-run', '--quiet', '--collect', '--unit='+TEST,
                    '--property=Type=exec', '--property=User=zmalaterminal',
                    '--property=SupplementaryGroups=audio video render input',
                    '--property=BindsTo='+SHELL+' zmalacall-display.service',
                    '--property=After='+SHELL+' zmalacall-display.service',
                    '--property=Conflicts='+STOCK, '--property=RuntimeMaxSec=30min',
                    '--property=TimeoutStopSec=15s', '--property=UMask=0077',
                    '--property=ProtectSystem=strict', '--property=ReadOnlyPaths=/data',
                    '--property=ReadWritePaths='+str(DATA)+' -/run/zmalacall-developer',
                    '--property=BindPaths='+str(SESSION/'data')+':'+str(DATA),
                    '--property=BindReadOnlyPaths='+turn_bindings,
                    '--property=InaccessiblePaths=-/run/zmalacall-updater',
                    '--property=EnvironmentFile=/etc/zmalacall/terminal.conf',
                    '--property=WorkingDirectory='+str(RELEASE),
                    '--property=RuntimeDirectory=zmalacall-test',
                    '--property=RuntimeDirectoryMode=0700',
                    '--property=ExecStopPost=+/usr/bin/systemctl --no-block start '+STOCK,
                    '--setenv=DISPLAY=:0', '--setenv=XAUTHORITY=/run/zmalacall-display/Xauthority',
                    '--setenv=PYTHONDONTWRITEBYTECODE=1', '--setenv=PYTHONUNBUFFERED=1',
                    '--setenv=ZMALA_LOG_STDERR=1', '--setenv=ZMALA_RUNTIME_DIR=/run/zmalacall-test',
                    '--setenv=ZMALA_PAIRING_STATUS=/run/zmalacall-pairing/status.json', '--setenv=ZMALA_C20_SETUP=1',
                    '/usr/bin/python3', str(RELEASE/'build_tools/linux/kiosk-session.py')],
                   check=True, timeout=25)


def activate():
    import pwd

    from zmala_system import update_ipc

    admit()
    if state(STOCK) != 'active' or state(UPDATER) != 'active' or state(UPDATER, 'FreezerState') != 'running':
        raise ValueError('The confirmed Terminal and its OTA coordinator must be running')
    (SESSION/'thaw').touch()
    systemctl('freeze', UPDATER)
    if state(UPDATER, 'FreezerState') != 'frozen':
        raise ValueError('Could not acquire exclusive Terminal maintenance')
    ui = update_ipc.LocalUI()
    lease = update_ipc.record(ui.runtime/'state.json', 0, 0o644)
    if lease['phase'] != 'idle' or state('rauc.service') != 'inactive':
        raise ValueError('The OTA coordinator is busy')
    (SESSION/'lease').touch()
    if not ui.claim(immediate=True):
        raise ValueError('The Terminal is busy. Close settings and finish the call or setup before retrying')
    (SESSION/'stopped').touch()
    systemctl('stop', STOCK)
    snapshot(DATA, SESSION/'data', pwd.getpwnam('zmalaterminal'))
    admit()
    launch()
    deadline = time.monotonic() + 15
    ready = Path('/run/zmalacall-test/terminal.pid.json')
    while time.monotonic() < deadline and state(TEST) == 'active':
        if ready.is_file():
            (SESSION/'ready').touch()
            return
        time.sleep(.25)
    raise ValueError('The test Terminal launcher did not become ready. Inspect its systemd journal')


def cleanup():
    from zmala_system import update_ipc

    try:
        if (SESSION/'lease').exists():
            update_ipc.LocalUI().phase('idle')
        if (SESSION/'stopped').exists():
            if busy(TEST) and not (SESSION/'ready').exists():
                systemctl('stop', TEST)
            if not busy(TEST):
                systemctl('start', STOCK)
    finally:
        if (SESSION/'thaw').exists():
            systemctl('thaw', UPDATER)


def deploy(size, digest, driver):
    if not 0 < size <= MAX_ARCHIVE or not re.fullmatch('[0-9a-f]{64}', digest):
        raise ValueError('Invalid package size or digest')
    if busy(TEST):
        raise ValueError('Restore the running test Terminal before deploying another')
    if SESSION.exists():
        shutil.rmtree(SESSION)
    SESSION.mkdir()
    keep_space(size)
    package = SESSION/'package.tar.gz'
    fingerprint = hashlib.sha256()
    with package.open('xb') as output:
        while size:
            block = sys.stdin.buffer.read(min(1024**2, size))
            if not block:
                raise ValueError('Truncated SSH package transfer')
            size -= len(block)
            fingerprint.update(block)
            output.write(block)
    if sys.stdin.buffer.read(1) or fingerprint.hexdigest() != digest:
        raise ValueError('Transferred package failed its digest or size check')
    release = extract(package, RELEASE)
    package.unlink()
    reuse_native(RELEASE, STOCK_ROOT.resolve(strict=True))
    (SESSION/'release.json').write_text(json.dumps(release))
    DRIVER.write_bytes(driver)
    subprocess.run(['/usr/bin/systemd-run', '--quiet', '--wait', '--pipe', '--collect', '--unit='+JOB,
                    '--property=RuntimeMaxSec=90s', '--property=TimeoutStopSec=30s',
                    '--property=ExecStopPost=/usr/bin/python3 -IB '+str(DRIVER)+' cleanup',
                    '/usr/bin/python3', '-IB', str(DRIVER), 'activate'],
                   stdin=subprocess.DEVNULL, check=True, timeout=180)
    print(json.dumps(release | {'state': 'test', 'maximum_minutes': 30}))


def main(driver=None):
    import fcntl

    action, *arguments = sys.argv[1:]
    if os.geteuid() != 0:
        raise ValueError('The test deploy tool requires the operator sudo session')
    if action in ('activate', 'cleanup') and Path(sys.argv[0]) == DRIVER:
        return {'activate': activate, 'cleanup': cleanup}[action]()
    if os.environ.get('SUDO_USER') != 'zmala':
        raise ValueError('Connect as the Developer Access operator')
    admit()
    os.umask(0o022)
    BASE.mkdir(mode=0o755, exist_ok=True)
    with (BASE/'lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if busy(JOB):
            raise ValueError('Another deployment is still running')
        if action == 'deploy':
            deploy(int(arguments[0]), arguments[1], driver)
        elif action == 'restore':
            systemctl('stop', TEST, check=False)
            if busy(TEST):
                raise ValueError('Test Terminal is still stopping')
            systemctl('start', STOCK)
            if SESSION.exists():
                shutil.rmtree(SESSION)
            print('Stock Terminal restored.')
        elif action == 'status':
            result = {'stock': state(STOCK), 'test': state(TEST)}
            if result['test'] == 'active':
                result['release'] = json.loads((SESSION/'release.json').read_text())
            print(json.dumps(result))
        else:
            raise ValueError('Unsupported test deployment action')


if __name__ == '__main__':
    try:
        main(globals().get('SOURCE'))
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError, subprocess.SubprocessError) as error:
        raise SystemExit(f'Terminal test deployment failed: {error}') from None
