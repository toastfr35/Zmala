"""Bounded Settings commands and authenticated maintenance acknowledgements."""
import json
import os
from pathlib import Path
import re
import stat
import time
import uuid

from . import host_layout, update_discovery

RUNTIME = Path('/run/zmalacall-updater')
APP_RUNTIME = Path('/run/zmalacall')
APP_ROOT = Path('/opt/zmalacall/current')
TRIAL = RUNTIME/'trial.json'
USER = 1000
NORMAL_SERVICE = 'zmalacall-terminal.service'
TRIAL_SERVICE = 'zmalacall-terminal-trial.service'


def record(path, uid, mode):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != uid or info.st_nlink != 1
                or info.st_mode & 0o7777 != mode or info.st_size > 4096):
            raise ValueError('Invalid update IPC file')
        body = stream.read(4097)
    if len(body) > 4096:
        raise ValueError('Oversized update IPC file')
    value = json.loads(body, object_pairs_hook=host_layout.unique_fields)
    if not isinstance(value, dict):
        raise ValueError('Expected an update object')
    return value


def token(value, length):
    return isinstance(value, str) and re.fullmatch(f'[0-9a-f]{{{length}}}', value) is not None


def fresh(now, value, seconds):
    return type(value) in (int, float) and 0 <= now-value <= seconds


# @llr LLR-TERM-MAINT-062
class LocalUI:
    def __init__(self, runtime=RUNTIME, app=APP_RUNTIME, clock=time.monotonic, proc=Path('/proc'), app_root=APP_ROOT):
        self.runtime, self.app, self.clock, self.proc, self.app_root = runtime, app, clock, proc, app_root
        runtime.mkdir(mode=0o755, exist_ok=True)
        host_layout.metadata(runtime.lstat(), mode=0o755, directory=True)
        self.nonce = uuid.uuid4().hex
        self.previous = None
        self.language = 'en'
        self.sleeping = False

    def command(self):
        try:
            value = record(self.app/'update-command.json', USER, 0o600)
            keys = {'schema', 'action', 'issued', 'request'}
            if value.get('action') == 'apply':
                keys.add('release')
                if not token(value.get('release'), 64):
                    return None
            elif value.get('action') != 'check':
                return None
            if (set(value) != keys or type(value['schema']) is not int or value['schema'] != 1
                    or not token(value['request'], 32) or value['request'] == self.previous
                    or not fresh(self.clock(), value['issued'], 40)):
                return None
        except (OSError, ValueError, TypeError, KeyError):
            return None
        self.previous = value['request']
        return value

    def publish(self, name, value):
        update_discovery.save(self.runtime/name, value, mode=0o644)

    def offer(self, state, request='', **fields):
        self.publish('offer.json', {'schema': 1, 'state': state, 'request': request, **fields})

    def phase(self, phase, immediate=False):
        self.publish('state.json', {'phase': phase, 'nonce': self.nonce, 'heartbeat': self.clock(),
                                    'language': self.language, 'preserve_sleep': self.sleeping,
                                    'immediate': immediate and phase == 'request'})

    def heartbeat(self, unit=NORMAL_SERVICE):
        try:
            value = record(self.app/'update.json', USER, 0o600)
            pid = value['pid']
            if (type(pid) is not int or pid < 2 or value['nonce'] != self.nonce
                    or not token(value['generation'], 32) or not fresh(self.clock(), value['heartbeat'], 4)
                    or value.get('ready') is not True or value.get('maintenance') is not True):
                return None
            process = self.proc/str(pid)
            if process.stat().st_uid != USER or (process/'cwd').resolve(strict=True) != self.app_root.resolve(strict=True):
                return None
            with (process/'cgroup').open() as stream:
                groups = stream.read(8193)
            if len(groups) > 8192 or not any(unit in line.split('/') for line in groups.splitlines()):
                return None
            return value
        except (OSError, ValueError, TypeError, KeyError):
            return None

    def claim(self, immediate, sleep=time.sleep):
        self.nonce = uuid.uuid4().hex
        deadline = self.clock()+12
        while self.clock() < deadline:
            self.phase('request', immediate)
            response = self.heartbeat()
            if response and response.get('eligible') is True:
                language = response.get('language')
                self.language = language if isinstance(language, str) and re.fullmatch('[a-z]{2}(-Hans)?', language) else 'en'
                self.sleeping = response.get('sleeping') is True
                return True
            sleep(.25)
        self.phase('idle')
        return False
