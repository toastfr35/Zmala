"""Exact experimental boot contract and bounded kernel/block metadata parsing."""
import json
import re
import uuid

from . import host_layout

PROFILE = 'usr/lib/zmala/boot-layout.json'
MAX_RECORD_BYTES = 8192
MAX_PROBE_BYTES = 16384
LINUX_PARTITION = '0fc63daf-8483-4772-8e79-3d69d8477de4'


# @llr LLR-SRV-HOST-018, LLR-TERM-MAINT-045
def profile(role):
    host_layout.profile(role)
    return {'schema': 1, 'role': role, 'layout': 'zmala-pi4-sd-ab-experimental-v1',
            'root_a_partition': 4, 'root_b_partition': 5, 'data_partition': 6,
            'root_a_label': 'system_a', 'root_b_label': 'system_b', 'data_label': 'persistent'}


# @llr LLR-SRV-HOST-018, LLR-TERM-MAINT-045
def decode_profile(body, role):
    expected = profile(role)
    if not 0 < len(body) <= MAX_RECORD_BYTES:
        raise ValueError('Boot layout record exceeds its budget')
    value = json.loads(body.decode('utf-8'), object_pairs_hook=host_layout.unique_fields)
    if (not isinstance(value, dict) or value != expected
            or any(type(value[key]) is not type(item) for key, item in expected.items())):
        raise ValueError('Unsupported or mismatched boot layout')
    return value


def identifier(value):
    if (not isinstance(value, str)
            or not re.fullmatch('[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', value)
            or uuid.UUID(value).int in (0, 2**128-1)):
        raise ValueError('Invalid canonical partition/filesystem identity')
    return value


# @llr LLR-SRV-HOST-018, LLR-TERM-MAINT-045
def command_line(body):
    if not 0 < len(body) <= MAX_RECORD_BYTES or b'\0' in body:
        raise ValueError('Invalid or oversized kernel boot arguments')
    selected = {}
    for token in body.decode('ascii').split():
        key, separator, value = token.partition('=')
        if key in ('root', 'rauc.slot'):
            if not separator or key in selected:
                raise ValueError('Missing or duplicate relevant kernel boot argument')
            selected[key] = value
    if set(selected) != {'root', 'rauc.slot'} or selected['rauc.slot'] not in ('A', 'B'):
        raise ValueError('Missing or unsupported system slot')
    root = selected['root']
    if not root.startswith('PARTUUID='):
        raise ValueError('Root must have an explicit GPT partition identity')
    return selected['rauc.slot'], identifier(root[len('PARTUUID='):])


def device_number(value):
    if not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]{0,9}:[0-9]{1,10}', value):
        raise ValueError('Invalid kernel block identity')
    major, minor = map(int, value.split(':'))
    if major >= 2**12 or minor >= 2**20 or value != f'{major}:{minor}':
        raise ValueError('Unsupported or noncanonical kernel block identity')
    return major, minor


# @llr LLR-SRV-HOST-019, LLR-TERM-MAINT-046
def probe_record(body):
    if not 0 < len(body) <= MAX_PROBE_BYTES or b'\0' in body:
        raise ValueError('Invalid or oversized block probe record')
    result = {}
    for line in body.decode('utf-8').splitlines():
        key, separator, value = line.partition('=')
        if (not separator or not re.fullmatch('[A-Z_][A-Z_0-9]*', key)
                or key in result or not value or len(value.encode()) > 4096 or len(result) >= 64):
            raise ValueError('Malformed or ambiguous block probe record')
        result[key] = value
    return result


# @llr LLR-SRV-HOST-019, LLR-TERM-MAINT-046
def check_probe(record, number, label, parent, expected_uuid=None):
    device_number(parent)
    expected = {'TYPE': 'ext4', 'USAGE': 'filesystem', 'LABEL': label,
                'PART_ENTRY_SCHEME': 'gpt', 'PART_ENTRY_NAME': label,
                'PART_ENTRY_TYPE': LINUX_PARTITION, 'PART_ENTRY_NUMBER': str(number),
                'PART_ENTRY_DISK': parent}
    if any(record.get(key) != value for key, value in expected.items()):
        raise ValueError('Block metadata does not match the declared slot/data partition')
    partition = identifier(record.get('PART_ENTRY_UUID'))
    identifier(record.get('UUID'))
    if expected_uuid is not None and partition != expected_uuid:
        raise ValueError('Mounted root differs from its kernel partition identity')
    return record
