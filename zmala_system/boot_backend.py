#!/usr/bin/python3 -IB
"""RAUC custom adapter plus explicit coordinator operations; no health guesses.

The caller must qualify complete candidate installation and product health.
These commands only enforce the boot-state transition boundary. Generic RAUC
mark-good changes eligibility; it cannot confirm a pending trial.
"""
import json
import sys

from zmala_system import boot_environment, boot_state


# @llr LLR-SRV-HOST-024, LLR-SRV-HOST-027, LLR-TERM-MAINT-051, LLR-TERM-MAINT-054
def request(arguments):
    args = tuple(arguments)
    counts = {'get-primary': 1, 'get-current': 1, 'snapshot': 1, 'get-state': 2,
              'set-state': 3, 'set-primary': 2, 'stage': 3, 'confirm': 3, 'cancel': 2}
    if not args or args[0] not in counts or len(args) != counts[args[0]]:
        raise ValueError('Unsupported boot-control command')
    if args[0] in ('get-state', 'set-state', 'set-primary', 'stage'):
        boot_state.slot(args[1])
    if args[0] == 'set-state' and args[2] not in ('good', 'bad'):
        raise ValueError('Unsupported slot eligibility')
    if args[0] in ('stage', 'confirm', 'cancel'):
        boot_state.transaction(args[2] if args[0] == 'stage' else args[1])
    if args[0] == 'confirm':
        if len(args[2]) != 16 or any(c not in '0123456789abcdef' for c in args[2]):
            raise ValueError('Invalid confirmation generation')
    return args


# @llr LLR-SRV-HOST-024, LLR-SRV-HOST-027, LLR-TERM-MAINT-051, LLR-TERM-MAINT-054
def execute(args, environment, current):
    args = request(args)
    boot_state.slot(current)
    state = environment.read()
    command = args[0]
    if command == 'get-current':
        return current
    if command == 'get-primary':
        return state.primary
    if command == 'get-state':
        return 'good' if state.good(args[1]) else 'bad'
    if command == 'snapshot':
        return json.dumps(state.fields(), sort_keys=True, separators=(',', ':'))
    if command == 'set-primary':
        # RAUC's unqualified two-argument activation cannot identify a product
        # transaction. Installation uses activate-installed=false; the coordinator
        # calls stage only after its complete-pair checks and durable transaction.
        raise ValueError('Activation requires an explicit boot transaction')
    if command == 'set-state':
        candidate = state.eligibility(args[1], args[2] == 'good')
    elif command == 'stage':
        candidate = state.stage(current, args[1], args[2])
    elif command == 'confirm':
        candidate = state.confirm(current, args[1], int(args[2], 16))
    else:
        candidate = state.cancel(current, args[1])
    if candidate != state:
        environment.commit(state, candidate)
    return None


# @llr LLR-SRV-HOST-027, LLR-TERM-MAINT-054
def main(arguments=None):
    try:
        args = request(sys.argv[1:] if arguments is None else arguments)
        with boot_environment.open_control() as (environment, current):
            result = execute(args, environment, current)
        if result is not None:
            print(result)
    except Exception:
        print('Zmala boot control failed. No successful change is acknowledged.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
