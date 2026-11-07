"""Experimental confirmed/trial contract shared by Linux control and build tools.

No device I/O lives here. A factory state is an explicit image-building operation,
never a fallback when a running device has missing or damaged environment state.
"""
from dataclasses import dataclass, replace
import json
import re

from .host_layout import ROLES

KEYS = ('zm_schema', 'zm_role', 'zm_confirmed', 'zm_trial', 'zm_left',
        'zm_a_good', 'zm_b_good', 'zm_transaction', 'zm_generation')
MAX_BYTES = 4096
LIMIT = 2**64-1
PROFILE = 'usr/lib/zmala/boot-control.json'


# @llr LLR-SRV-HOST-027, LLR-TERM-MAINT-054, LLR-SRV-HOST-029, LLR-TERM-MAINT-056
def policy(role):
    if role not in ROLES:
        raise ValueError('Unsupported boot role')
    return {'schema': 1, 'role': role, 'contract': 'zmala-confirmed-trial-v1',
            'activate_installed': False, 'automatic_confirmation': False,
            'pid1_startup_watchdog_seconds': 0, 'health_handover_implemented': False}


# @llr LLR-SRV-HOST-026, LLR-SRV-HOST-027, LLR-TERM-MAINT-053, LLR-TERM-MAINT-054, LLR-SRV-HOST-029, LLR-TERM-MAINT-056
def decode_policy(body, role):
    from .host_layout import unique_fields
    if not isinstance(body, bytes) or not 0 < len(body) <= MAX_BYTES:
        raise ValueError('Invalid boot-control policy size')
    fields = json.loads(body.decode('utf-8'), object_pairs_hook=unique_fields)
    expected = policy(role)
    if (not isinstance(fields, dict) or fields != expected
            or any(type(fields[key]) is not type(value) for key, value in expected.items())):
        raise ValueError('Unsupported boot-control policy')
    return fields


def slot(value):
    if value not in ('A', 'B'):
        raise ValueError('Unsupported boot slot')
    return value


def transaction(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value) or value == '0'*64:
        raise ValueError('Invalid boot transaction identity')
    return value


@dataclass(frozen=True)
class State:
    role: str
    confirmed: str
    trial: str = '-'
    left: int = 0
    a_good: bool = True
    b_good: bool = True
    transaction: str = '-'
    generation: int = 0

    # @llr LLR-SRV-HOST-023, LLR-TERM-MAINT-050, LLR-SRV-HOST-029, LLR-TERM-MAINT-056
    def __post_init__(self):
        if self.role not in ROLES:
            raise ValueError('Unsupported boot role')
        slot(self.confirmed)
        if (type(self.left) is not int or self.left not in (0, 1)
                or type(self.a_good) is not bool or type(self.b_good) is not bool
                or type(self.generation) is not int or not 0 <= self.generation <= LIMIT
                or not self.good(self.confirmed)):
            raise ValueError('Invalid boot state fields')
        if self.transaction != '-':
            transaction(self.transaction)
            if not self.generation:
                raise ValueError('Factory generation cannot contain an update transaction')
        if self.trial == '-':
            if self.left:
                raise ValueError('An absent trial has no attempt')
        elif (slot(self.trial) == self.confirmed or not self.good(self.trial)
              or self.transaction == '-' or self.generation == 0):
            raise ValueError('Inconsistent pending boot trial')

    def good(self, selected):
        return self.a_good if slot(selected) == 'A' else self.b_good

    @property
    def primary(self):
        return self.trial if self.trial != '-' and self.left else self.confirmed

    # @llr LLR-SRV-HOST-023, LLR-TERM-MAINT-050
    def fields(self):
        return dict(zip(KEYS, ('1', self.role, self.confirmed, self.trial, str(self.left),
                              str(int(self.a_good)), str(int(self.b_good)), self.transaction,
                              f'{self.generation:016x}')))

    # @llr LLR-SRV-HOST-024, LLR-TERM-MAINT-051
    def changed(self, **values):
        if self.generation == LIMIT:
            raise ValueError('Boot generation is exhausted')
        return replace(self, generation=self.generation+1, **values)

    # @llr LLR-SRV-HOST-024, LLR-TERM-MAINT-051
    def stage(self, current, candidate, identity):
        slot(candidate); transaction(identity)
        if (current != self.confirmed or candidate == current or not self.good(candidate)
                or self.trial != '-' or identity == self.transaction):
            raise ValueError('Candidate is not eligible for a new trial')
        return self.changed(trial=candidate, left=1, transaction=identity)

    # @llr LLR-SRV-HOST-024, LLR-TERM-MAINT-051
    def confirm(self, current, identity, generation):
        if (self.trial == '-' or current != self.trial or self.left
                or identity != self.transaction or type(generation) is not int
                or generation != self.generation):
            raise ValueError('Confirmation does not identify the consumed boot trial')
        return self.changed(confirmed=current, trial='-', left=0)

    # @llr LLR-SRV-HOST-024, LLR-TERM-MAINT-051
    def eligibility(self, selected, good):
        slot(selected)
        if type(good) is not bool or (selected == self.confirmed and not good):
            raise ValueError('Cannot invalidate the confirmed system')
        if self.good(selected) == good:
            return self
        values = {selected.lower()+'_good': good}
        if selected == self.trial and not good:
            values.update(trial='-', left=0)
        return self.changed(**values)

    # @llr LLR-SRV-HOST-024, LLR-TERM-MAINT-051
    def cancel(self, current, identity):
        if current != self.confirmed or self.trial == '-' or identity != self.transaction:
            raise ValueError('Cancellation does not identify a pending trial on the confirmed system')
        return self.changed(trial='-', left=0)


# @llr LLR-SRV-HOST-023, LLR-TERM-MAINT-050, LLR-SRV-HOST-029, LLR-TERM-MAINT-056
def decode(body, role):
    if (not isinstance(body, bytes) or not 0 < len(body) <= MAX_BYTES
            or b'\0' in body or b'\r' in body or not body.endswith(b'\n')):
        raise ValueError('Invalid boot-state record size')
    fields = {}
    for line in body.decode('ascii').split('\n')[:-1]:
        key, separator, value = line.partition('=')
        if not separator or key not in KEYS or key in fields or not value:
            raise ValueError('Invalid or duplicate boot-state key')
        fields[key] = value
    if (set(fields) != set(KEYS) or fields['zm_schema'] != '1' or fields['zm_role'] != role
            or any(fields[key] not in ('0', '1') for key in ('zm_left', 'zm_a_good', 'zm_b_good'))
            or not re.fullmatch('[a-f0-9]{16}', fields['zm_generation'])):
        raise ValueError('Missing, mismatched or noncanonical boot-state fields')
    return State(role, fields['zm_confirmed'], fields['zm_trial'], int(fields['zm_left']),
                 fields['zm_a_good'] == '1', fields['zm_b_good'] == '1', fields['zm_transaction'],
                 int(fields['zm_generation'], 16))


def encode(state):
    return ''.join(key+'='+value+'\n' for key, value in state.fields().items()).encode('ascii')
