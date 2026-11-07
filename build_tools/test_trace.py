"""Validate requirement-based test plans and build bidirectional trace data.

Metadata describes a test scenario/suite, not a passed execution. Coverage is
explicit: every LLR requires a direct unit-test plan and every HLR a direct
system-test plan. Coverage is never inferred from imports or parent relationships.
"""
from __future__ import annotations

from collections import defaultdict
from html import escape
import json
from pathlib import Path
import re

from requirement_ids import ITEM, category, document_prefix

FIELDS = {'test', 'requirements', 'environment', 'plan', 'pass'}
ENVIRONMENTS = {'portable', 'display', 'native-sdk', 'native-display', 'hardware', 'linux-root'}
TEST_SUFFIXES = {'.py', '.js', '.cjs', '.c', '.cpp', '.sh', '.ps1', '.kt', '.java'}


def read_plan(path: Path) -> dict:
    """Read only leading standalone comments; code/string literals cannot trace."""
    fields = {}
    for number, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
        if not line.strip() or line.startswith('#!'):
            continue
        match = re.fullmatch(r'(?:#|//)\s*(.*)', line)
        if not match:
            break
        body = match[1]
        if not body.startswith('@'):
            continue
        directive = re.fullmatch(r'@(\w+) (\S.*)', body)
        if not directive or directive[1] not in FIELDS:
            raise ValueError(f'{path}:{number}: invalid test-plan directive')
        key, value = directive.groups()
        if key in fields:
            raise ValueError(f'{path}:{number}: duplicate @{key}')
        fields[key] = value
    missing = FIELDS - fields.keys()
    if missing:
        raise ValueError(f'{path}: missing leading test-plan fields: {sorted(missing)}')
    if not re.fullmatch(r'[STA]-(?:LLT|HLT)-\d{3}', fields['test']):
        raise ValueError(f'{path}: invalid stable test ID')
    if not re.fullmatch(ITEM + '(?:, ' + ITEM + ')*', fields['requirements']):
        raise ValueError(f'{path}: malformed requirement list')
    fields['requirements'] = fields['requirements'].split(', ')
    if len(set(fields['requirements'])) != len(fields['requirements']):
        raise ValueError(f'{path}: duplicate requirement in test plan')
    if fields['environment'] not in ENVIRONMENTS:
        raise ValueError(f'{path}: unknown test environment')
    for key in ('plan', 'pass'):
        if len(fields[key].split()) < 8:
            raise ValueError(f'{path}: @{key} must explain the procedure/oracle')
    return fields


def audit_tests(root: Path, records: dict) -> dict:
    """Reject orphan IDs/levels and missing plans; expose untested requirements."""
    errors, tests, by_requirement = [], {}, defaultdict(list)
    for component, prefix in (('server', 'S'), ('terminal', 'T'), ('android', 'A')):
        for level, reqlevel in (('LLT', 'LLR'), ('HLT', 'HLR')):
            directory = root / 'tests' / component / level
            for path in sorted(directory.rglob('*')):
                if not path.is_file() or path.suffix not in TEST_SUFFIXES or path.name == '__init__.py':
                    continue
                if '__pycache__' in path.parts:
                    continue
                name = path.relative_to(root).as_posix()
                try:
                    plan = read_plan(path)
                    uid = plan['test']
                    if not uid.startswith(f'{prefix}-{level}-'):
                        raise ValueError(f'{name}: test ID does not match component/level')
                    if uid in tests:
                        raise ValueError(f'{name}: duplicate test ID {uid}')
                    for requirement in plan['requirements']:
                        if requirement not in records:
                            raise ValueError(f'{name}: unknown requirement {requirement}')
                        expected = reqlevel + '-' + {'S': 'SRV', 'T': 'TERM', 'A': 'AND'}[prefix]
                        if category(records[requirement]['prefix']) != expected:
                            raise ValueError(f'{name}: {level} must trace to {expected}, not {requirement}')
                        references = [ref.get('path') for ref in records[requirement].get('references', [])]
                        if name not in references:
                            raise ValueError(f'{requirement}: missing reciprocal test reference {name}')
                    tests[uid] = plan | {'path': name, 'level': level, 'component': component}
                    for requirement in plan['requirements']:
                        by_requirement[requirement].append(uid)
                except ValueError as error:
                    errors.append(str(error))
    # A stale reciprocal link must not silently count as coverage.
    for uid, record in records.items():
        for ref in record.get('references', []):
            name = ref.get('path', '')
            if name.startswith('tests/') and not any(
                    test['path'] == name and uid in test['requirements'] for test in tests.values()):
                errors.append(f'{uid}: test reference has no reciprocal requirement trace: {name}')
    # Test sources cannot drift back into implementation directories.
    for folder in ('zmala_server', 'zmala_terminal', 'zmala_phone', 'build_tools'):
        for path in (root / folder).rglob('*'):
            if any(part in {'node_modules', 'runtime', 'tmp', 'dist', '__pycache__', 'data', 'framing-runtime', 'turn-runtime', 'build', '.gradle'}
                   for part in path.relative_to(root).parts):
                continue
            if path.is_file() and (path.name.startswith(('test_', 'test-', 'probe-'))
                                   or path.name.endswith('.test.js')
                                   or ('tests' in path.relative_to(root).parts and path.suffix in TEST_SUFFIXES)):
                # This module implements tracing, not an executable test.
                if path == root / 'build_tools/test_trace.py':
                    continue
                errors.append(f'Test/probe outside tests/: {path.relative_to(root).as_posix()}')
    missing = {prefix: sorted(uid for uid, record in records.items()
                             if category(record['prefix']) == prefix and uid not in by_requirement)
               for prefix in ('HLR-SRV', 'LLR-SRV', 'HLR-TERM', 'LLR-TERM', 'HLR-AND', 'LLR-AND')}
    for prefix in missing:
        for uid in missing[prefix]:
            level = 'LLT' if prefix.startswith('LLR') else 'HLT'
            errors.append(f'{uid}: no mapped {level} verifying this {prefix[:3]}')
    if errors:
        raise ValueError('\n'.join(errors))
    return {'tests': dict(sorted(tests.items())),
            'requirements': dict(sorted(by_requirement.items())), 'unmapped': missing,
            'qualification': 'Trace links identify planned checks, not full requirement coverage or passed executions. '
                             'Hardware, manual visual checks and skipped cases need separate execution evidence.'}


def write_test_report(output: Path, trace: dict) -> None:
    """Publish plans and explicit gaps; never invent execution/coverage results."""
    def requirement_link(uid):
        return f'<a href="documents/{document_prefix(uid)}.html#{uid}">{uid}</a>'

    rows, plans = [], []
    for uid, test in trace['tests'].items():
        requirements = ' '.join(requirement_link(item) for item in test['requirements'])
        plans.append(f'<section id="{uid}" class="panel"><h2>{uid}</h2>'
                     f'<p><code>{escape(test["path"])}</code></p><p>{requirements}</p>'
                     f'<p><strong>Environment:</strong> {escape(test["environment"])}</p>'
                     f'<p><strong>Plan:</strong> {escape(test["plan"])}</p>'
                     f'<p><strong>Pass criteria:</strong> {escape(test["pass"])}</p></section>')
    all_ids = set(trace['requirements']) | {uid for ids in trace['unmapped'].values() for uid in ids}
    for requirement in sorted(all_ids):
        tests = trace['requirements'].get(requirement, [])
        links = ' '.join(f'<a href="#{uid}">{uid}</a>' for uid in tests) or '<strong>No mapped test</strong>'
        rows.append(f'<tr><td>{requirement_link(requirement)}</td><td>{links}</td></tr>')
    gaps = sum(len(ids) for ids in trace['unmapped'].values())
    text = f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Requirement-based tests · ZmalaCall</title>
<link rel="stylesheet" href="template/zmala.css"><script src="template/zmala.js" defer></script></head><body>
<a class="skip" href="#main">Skip to content</a><header class="topbar"><a class="brand" href="index.html">ZmalaCall Engineering</a>
<nav aria-label="Report"><a href="index.html">Overview</a><a href="traceability.html">Traceability</a><a href="coverage.html">Source coverage</a><a href="tests.html" aria-current="page">Tests</a></nav></header>
<main id="main" style="margin:auto"><p class="eyebrow">Verification planning</p><h1>Requirement-based tests</h1>
<p>{len(plans)} test plans · {gaps} requirements without a mapped test</p>
<p class="notice">{escape(trace['qualification'])}</p>
<p>LLT → LLR: isolated unit/component checks. HLT → HLR: integrated behavior through service, process, UI or hardware boundaries. Shared fixtures and ad-hoc diagnostics do not count as requirement coverage.</p>
<p><a href="tests.json" download>Download trace data</a></p>
<div class="filter"><label for="search">Find requirement or test ID</label><input id="search" type="search"><output id="match-count" aria-live="polite"></output></div>
<div class="matrix" tabindex="0" aria-label="Scrollable requirement to test matrix"><table><thead><tr><th>Requirement</th><th>Mapped test plans</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<h2>Test plans</h2>{''.join(plans)}<footer><a href="#main">Back to top</a></footer></main></body></html>'''
    (output / 'tests.html').write_text(text, encoding='utf-8')
    (output / 'tests.json').write_text(json.dumps(trace, indent=2) + '\n', encoding='utf-8')
