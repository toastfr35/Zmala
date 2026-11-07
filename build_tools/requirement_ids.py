"""Themed requirement identity and document catalogue (not normative content)."""
from __future__ import annotations

import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = {'SRV': 'server', 'TERM': 'terminal', 'AND': 'android'}
ITEM = r'(?:HLR|LLR)-(?:SRV|TERM|AND)-[A-Z][A-Z0-9]{1,11}-[0-9]{3}'
LLR = r'LLR-(?:SRV|TERM|AND)-[A-Z][A-Z0-9]{1,11}-[0-9]{3}'


def document_prefix(uid: str) -> str:
    if re.fullmatch(r'PROD[0-9]{3}', uid):
        return 'PROD'
    if not re.fullmatch(ITEM, uid):
        raise ValueError(f'Invalid requirement ID: {uid}')
    return uid.rsplit('-', 1)[0]


def category(prefix: str) -> str:
    """Summary category without the theme (also accepts a full UID)."""
    return 'PROD' if prefix.startswith('PROD') else '-'.join(prefix.split('-')[:2])


def groups(root: Path = ROOT) -> dict:
    value = json.loads((root / 'requirements/groups.json').read_text(encoding='utf-8'))
    if not value or set(value) - set(COMPONENTS):
        raise ValueError('Requirement catalogue must list known component groups')
    for component, themes in value.items():
        if not isinstance(themes, dict) or not themes:
            raise ValueError(f'{component}: missing theme catalogue')
        for code, title in themes.items():
            if not re.fullmatch(r'[A-Z][A-Z0-9]{1,11}', code) or not isinstance(title, str) or not title.strip():
                raise ValueError(f'{component}: invalid theme {code}')
    return value


def documents(root: Path = ROOT) -> dict:
    result = {'PROD': ('product', None)}
    for component, themes in groups(root).items():
        for group in themes:
            base = f'{COMPONENTS[component]}/{group.lower()}'
            result[f'HLR-{component}-{group}'] = (base + '/hlr', 'PROD')
            result[f'LLR-{component}-{group}'] = (base + '/llr', f'HLR-{component}-{group}')
    return result


def next_id(root: Path, level: str, component: str, group: str) -> str:
    """Find the next number across both levels; migrated IDs remain reserved."""
    if level not in ('HLR', 'LLR') or group not in groups(root).get(component, {}):
        raise ValueError('Choose HLR/LLR and a component/theme from requirements/groups.json')
    numbers = []
    for kind in ('HLR', 'LLR'):
        prefix = f'{kind}-{component}-{group}'
        folder = documents(root)[prefix][0]
        numbers.extend(int(p.stem.rsplit('-', 1)[1]) for p in (root/'requirements'/folder).glob(prefix+'-*.yml'))
    history = root/'requirements/id-migration.json'
    if history.is_file():
        numbers.extend(int(uid.rsplit('-', 1)[1]) for uid in json.loads(history.read_text(encoding='utf-8')).values()
                       if uid.rsplit('-', 1)[0] in (f'HLR-{component}-{group}', f'LLR-{component}-{group}'))
    number = max(numbers, default=0) + 1
    if number > 999:
        raise ValueError('Theme sequence exhausted; agree an explicit ID format migration')
    return f'{level}-{component}-{group}-{number:03}'
