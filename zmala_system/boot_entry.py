#!/usr/bin/python3 -IB
"""Installed initramfs local-bottom entry; failures block ordinary startup.

Run before init-bottom's udev script moves /dev into the selected root. The
separate PID1 gate also refuses missing/incomplete preparation after a killed
or missing entry, without relying on initramfs run_scripts error handling.
"""
import os
from pathlib import Path
import sys
import time

from zmala_system import boot_storage


# @llr LLR-SRV-HOST-021, LLR-TERM-MAINT-048
def failure_barrier(wait=time.sleep):
    # Returning after a diagnostic shell would let initramfs continue startup.
    # Remain fenced; the separately qualified watchdog/recovery policy owns reset.
    while True:
        wait(60)


# @llr LLR-SRV-HOST-021, LLR-TERM-MAINT-048
def run(root, role, prepare=boot_storage.prepare, barrier=failure_barrier):
    try:
        result = prepare(root, role)
        if result.ready is not True:
            raise ValueError('Incomplete early-boot storage')
        return 0
    except BaseException:
        print('Zmala storage preparation failed. Normal startup is blocked.', file=sys.stderr, flush=True)
        barrier()
        raise RuntimeError('The boot failure barrier must never return')


# @llr LLR-SRV-HOST-021, LLR-TERM-MAINT-048
def main():
    sys.dont_write_bytecode = True
    if sys.argv[1:] == ['prereqs']:
        return 0
    try:
        if sys.argv[1:]:
            raise ValueError('Unsupported early-boot entry arguments')
        role = boot_storage.configured_role()
    except BaseException:
        print('Zmala boot configuration is invalid. Normal startup is blocked.', file=sys.stderr, flush=True)
        failure_barrier()
        raise RuntimeError('The boot failure barrier must never return')
    return run(Path(os.environ.get('rootmnt', '/root')), role)


if __name__ == '__main__':
    raise SystemExit(main())
