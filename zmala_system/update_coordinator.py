"""Single owner for standalone Terminal system update activation and recovery."""
import argparse
import logging
import os
from pathlib import Path
import subprocess
import time

from . import boot_environment, host_layout, host_storage, update_discovery, update_install, update_ipc

DATA = Path('/data')
STATE = 'host/system-updates'
JOURNAL = 'journal.json'
DISCOVERY = 'host/update-discovery/status.json'
UPDATE_SCREEN = 'zmalacall-system-update-screen.service'
FAILURES = (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError)


def validate_candidate(value):
    if (not isinstance(value, dict) or set(value) != {'system_version', 'terminal_version', 'release', 'target', 'images'}
            or not update_ipc.token(value['release'], 64) or value['target'] not in ('A', 'B')
            or set(value['images']) != {'boot', 'rootfs'}
            or not all(update_ipc.token(item, 64) for item in value['images'].values())):
        raise ValueError('Invalid system update candidate')
    update_discovery.version(value['system_version'])
    update_discovery.version(value['terminal_version'])
    return value


def journal(directory):
    try:
        value = update_ipc.record(directory/JOURNAL, 0, 0o600)
    except FileNotFoundError:
        return None
    if (set(value) != {'schema', 'state', 'candidate', 'previous', 'sleeping', 'language'}
            or type(value['schema']) is not int or value['schema'] != 1
            or value['state'] not in ('installing', 'staged', 'confirmed', 'rejected')
            or value['previous'] not in ('A', 'B') or type(value['sleeping']) is not bool
            or not isinstance(value['language'], str) or len(value['language']) > 12):
        raise ValueError('Invalid durable system update journal')
    if validate_candidate(value['candidate'])['target'] == value['previous']:
        raise ValueError('System update journal targets the previous slot')
    return value


# @llr LLR-TERM-MAINT-064
def boot_mode(control, current, saved, installed):
    if control.role != 'terminal':
        raise ValueError('System update is limited to standalone Terminals')
    if current != control.confirmed:
        if (not saved or saved['state'] != 'staged' or saved['previous'] != control.confirmed
                or saved['candidate']['target'] != current or saved['candidate']['release'] != control.transaction
                or control.trial != current or control.left or saved['candidate']['system_version'] != installed):
            raise ValueError('Booted candidate has no matching consumed trial')
        return 'trial'
    if not saved:
        if control.trial != '-':
            raise ValueError('Pending boot state has no system update journal')
        return 'normal'
    candidate = saved['candidate']
    if control.trial != '-':
        if (saved['state'] != 'staged' or saved['previous'] != current
                or candidate['release'] != control.transaction or candidate['target'] != control.trial):
            raise ValueError('Pending boot state differs from the system update journal')
        return 'reject'
    if (current == candidate['target'] and control.transaction == candidate['release']
            and installed == candidate['system_version'] and saved['state'] in ('staged', 'confirmed')):
        return 'confirmed'
    if saved['state'] in ('staged', 'installing'):
        return 'reject'
    return 'normal'


def systemctl(action, unit=None, *, timeout=45):
    args = ['/usr/bin/systemctl', action]
    if unit:
        args.append(unit)
    update_install.command(args, timeout)


def reboot():
    update_install.command(['/usr/bin/systemctl', '--no-block', 'reboot'])


class Coordinator:
    def __init__(self, directory, ui, installed, *, control=boot_environment.open_control,
                 install=update_install.install, restart=reboot, clock=time.monotonic, sleep=time.sleep):
        self.directory, self.ui, self.installed = directory, ui, installed
        self.control, self.install, self.restart, self.clock, self.sleep = control, install, restart, clock, sleep
        self.offered, self.expires = None, 0
        self.requested = None
        self.next_attempt = 0
        self.quiet_sleep_until = 0

    def read(self):
        return journal(self.directory)

    def write(self, value, phase):
        update_discovery.save(self.directory/JOURNAL, value | {'state': phase})

    # @llr LLR-TERM-MAINT-064
    def prepare_boot(self):
        saved = self.read()
        # If an installer exited abnormally, reap the RAUC bus owner before
        # restoring normal application admission. The configuration is volatile.
        update_install.stop_rauc()
        (self.directory/'candidate.raucb').unlink(missing_ok=True)
        with self.control() as (environment, current):
            control = environment.read()
            mode = boot_mode(control, current, saved, self.installed)
            if mode == 'reject':
                if control.trial != '-':
                    environment.commit(control, control.cancel(current, saved['candidate']['release']))
                self.write(saved, 'rejected')
            elif mode == 'confirmed' and saved['state'] != 'confirmed':
                self.write(saved, 'confirmed')
        if saved and (mode in ('trial', 'confirmed', 'reject')
                      or saved['state'] == 'rejected' and saved['previous'] == current):
            self.ui.sleeping, self.ui.language = saved['sleeping'], saved['language']
        if mode == 'trial':
            # The dedicated unit mounts persistent storage read-only. It has no
            # role in choosing or confirming the trial and never opens the watchdog.
            self.ui.sleeping = True
            self.ui.phase('checking')
            self.ui.publish('trial.json', {'nonce': self.ui.nonce})
        else:
            (self.ui.runtime/'trial.json').unlink(missing_ok=True)
            self.ui.phase('idle')
        return mode

    def inspect(self):
        with self.control() as (environment, current):
            value = environment.read()
            if value.role != 'terminal' or current != value.confirmed or value.trial != '-':
                raise ValueError('System update check requires a confirmed standalone Terminal')
            target = 'A' if current == 'B' else 'B'
        return update_discovery.inspect_release(target, self.installed)

    def admissible(self, candidate):
        if not candidate or update_discovery.version(candidate['system_version']) <= update_discovery.version(self.installed):
            return False
        saved = self.read()
        return not saved or saved['state'] != 'rejected' or saved['candidate']['release'] != candidate['release']

    # @llr LLR-TERM-MAINT-062
    def manual(self, request):
        identity = request['request']
        if request['action'] == 'check':
            self.offered = None
            candidate = self.inspect()
            if self.admissible(candidate):
                self.offered, self.expires = candidate, self.clock()+600
                self.ui.offer('available', identity, version=candidate['system_version'], release=candidate['release'])
            else:
                self.ui.offer('current', identity)
            return
        candidate = self.offered
        if not candidate or self.clock() > self.expires or candidate['release'] != request['release'] or not self.admissible(candidate):
            self.ui.offer('error', identity)
            return
        self.requested, self.offered = candidate, None
        self.next_attempt = 0
        self.ui.offer('queued', identity)

    def automatic(self):
        try:
            value = update_ipc.record(DATA/DISCOVERY, 0, 0o600)
            candidate = validate_candidate(value['candidate']) if value['state'] == 'verified' else None
            return candidate if self.admissible(candidate) else None
        except (OSError, ValueError, TypeError, KeyError):
            return None

    # @llr LLR-TERM-MAINT-062, LLR-TERM-MAINT-064
    def activate(self, candidate, immediate):
        candidate = validate_candidate(candidate)
        if not self.ui.claim(immediate):
            return False
        self.ui.phase('updating')
        # Keep the fence even if cleanup itself fails. systemd restarts this
        # owner, which stops RAUC and replays the journal before publishing idle.
        with self.control() as (environment, current):
            boot = environment.read()
            if boot.role != 'terminal' or current != boot.confirmed or candidate['target'] == current or boot.trial != '-':
                raise ValueError('Boot state changed after maintenance admission')
        saved = {'schema': 1, 'candidate': candidate, 'previous': current, 'sleeping': self.ui.sleeping,
                 'language': self.ui.language}
        self.write(saved, 'installing')
        try:
            systemctl('start', UPDATE_SCREEN)
            self.install(candidate, self.installed, self.directory)
        except FAILURES as error:
            update_install.stop_rauc()
            self.write(saved, 'rejected')
            systemctl('stop', UPDATE_SCREEN)
            self.ui.phase('idle')
            logging.warning('System update rejected (%s)', type(error).__name__)
            return False
        with self.control() as (environment, current):
            boot = environment.read()
            if current != saved['previous'] or current != boot.confirmed or boot.trial != '-':
                raise ValueError('Confirmed boot state changed during installation')
            eligible = boot.eligibility(candidate['target'], True)
            if eligible != boot:
                environment.commit(boot, eligible)
            self.write(saved, 'staged')
            environment.commit(eligible, eligible.stage(current, candidate['target'], candidate['release']))
        self.restart()
        return True

    # @llr LLR-TERM-MAINT-064
    def confirm_trial(self):
        saved = self.read()
        trial = update_ipc.record(self.ui.runtime/'trial.json', 0, 0o644)
        if not saved or not update_ipc.token(trial.get('nonce'), 32):
            raise ValueError('Missing boot trial lease')
        self.ui.nonce = trial['nonce']
        self.ui.sleeping, self.ui.language = True, saved['language']
        deadline = self.clock()+30
        stable_since = self.clock()
        process = None
        while self.clock() < deadline:
            self.ui.phase('checking')
            health = self.ui.heartbeat(update_ipc.TRIAL_SERVICE)
            current_process = (health['pid'], health['generation']) if health else None
            if process is not None and current_process not in (None, process):
                break  # An application restart invalidates this trial.
            if not current_process or current_process != process:
                stable_since = self.clock()
            if current_process and self.clock()-stable_since >= 8:
                with self.control() as (environment, current):
                    boot = environment.read()
                    if boot_mode(boot, current, saved, self.installed) != 'trial':
                        raise ValueError('Boot trial changed before confirmation')
                    latest = self.ui.heartbeat(update_ipc.TRIAL_SERVICE)
                    if not latest or (latest['pid'], latest['generation']) != process:
                        break
                    environment.commit(boot, boot.confirm(current, saved['candidate']['release'], boot.generation))
                self.write(saved, 'confirmed')
                self.restart()  # The confirmed boot starts the normal writable unit.
                return True
            if current_process:
                process = current_process
            self.sleep(.25)
        self.ui.phase('rollback')
        self.restart()  # The consumed attempt falls back to the confirmed slot.
        return False

    def serve(self):
        if (self.ui.runtime/'trial.json').exists():
            self.confirm_trial()
            return
        # Also replay recovery after a coordinator process crash on the same
        # confirmed boot. Preserve the first post-boot passive-media hint.
        self.prepare_boot()
        self.quiet_sleep_until = self.clock()+60
        self.ui.offer('current')
        while True:
            if self.clock() >= self.quiet_sleep_until:
                self.ui.sleeping = False
            self.ui.phase('idle')
            request = self.ui.command()
            if request:
                try:
                    self.manual(request)
                except FAILURES as error:
                    self.ui.offer('error', request['request'])
                    logging.warning('System update check failed (%s)', type(error).__name__)
            if self.clock() >= self.next_attempt:
                self.next_attempt = self.clock()+30
                candidate = self.requested or self.automatic()
                if candidate and self.admissible(candidate):
                    if self.activate(candidate, self.requested is not None):
                        return
                    if not self.admissible(candidate):
                        self.requested = None
            self.sleep(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('boot', 'serve'))
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise ValueError('System update coordinator requires root')
    directory = host_storage.safe(DATA, STATE)
    directory.mkdir(mode=0o700, exist_ok=True)
    host_layout.metadata(directory.lstat(), mode=0o700, directory=True)
    instance = Coordinator(directory, update_ipc.LocalUI(), update_discovery.installed_release())
    if args.action == 'boot':
        instance.prepare_boot()
    else:
        instance.serve()


if __name__ == '__main__':
    main()
