"""Read standalone @llr comments and check them against Doorstop source references.

The directive identifies the following declaration or cohesive implementation block.
It records traceability, not proof of test execution or behavioral completeness.
"""
from __future__ import annotations

from collections import defaultdict
import io
from pathlib import Path
import re
import tokenize

from requirement_ids import LLR

COMMENT_STYLES = {
    '.py': ('#', ''), '.sh': ('#', ''), '.service': ('#', ''),
    '.conf': ('#', ''), '.rules': ('#', ''), '.plymouth': ('#', ''),
    '.js': ('//', ''), '.cjs': ('//', ''), '.ts': ('//', ''),
    '.c': ('//', ''), '.h': ('//', ''), '.script': ('#', ''),
    '.css': ('/*', '*/'), '.html': ('<!--', '-->'),
    '.kt': ('//', ''), '.java': ('//', ''), '.xml': ('<!--', '-->'),
}
IDS = re.compile(LLR + '(?:, ' + LLR + ')*')


def read_markers(path: Path) -> list[tuple[int, list[str]]]:
    """Return one-based locations for full-line, language-appropriate directives.

    Python uses comment tokens so embedded shell/config text and docstrings cannot
    satisfy coverage. Other sources use the reserved standalone comment syntax;
    do not embed directives in string/heredoc literals or generated content.
    """
    style = COMMENT_STYLES.get(path.suffix)
    if not style:
        return []  # JSON and other comment-free formats are traced at their consumer.
    text = path.read_text(encoding='utf-8-sig')
    lines = text.splitlines()
    candidates = enumerate(lines, 1)
    if path.suffix == '.py':
        try:
            candidates = [(token.start[0], token.string) for token in
                          tokenize.generate_tokens(io.StringIO(text).readline)
                          if token.type == tokenize.COMMENT and
                          not lines[token.start[0]-1][:token.start[1]].strip()]
        except (tokenize.TokenError, IndentationError) as error:
            raise ValueError(f'{path}: cannot tokenize trace comments: {error}') from error
    opening, closing = style
    result = []
    for number, line in candidates:
        line = line.strip()
        if not line.startswith(opening):
            continue
        body = line[len(opening):].strip()
        if not body.startswith('@llr'):
            continue
        if closing:
            if not body.endswith(closing):
                raise ValueError(f'{path}:{number}: malformed @llr comment')
            body = body[:-len(closing)].rstrip()
        payload = body.removeprefix('@llr ')
        if not IDS.fullmatch(payload) or len(set(payload.split(', '))) != len(payload.split(', ')):
            raise ValueError(f'{path}:{number}: malformed @llr directive; use @llr LLR-TERM-START-003, LLR-SRV-BOOT-002')
        result.append((number, payload.split(', ')))
    return result


def audit_traces(root: Path, records: dict, files: list[str], referenced: dict) -> dict:
    """Every LLR needs a code anchor in one of its declared implementation files."""
    errors, traces = [], defaultdict(list)
    for name in sorted(files):
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            continue  # The reference validator reports unsafe/missing paths.
        try:
            markers = read_markers(path)
        except ValueError as error:
            errors.append(str(error))
            continue
        for line, ids in markers:
            for uid in ids:
                location = f'{name}:{line}'
                if uid not in records or not records[uid]['prefix'].startswith('LLR-'):
                    errors.append(f'{location}: unknown LLR {uid}')
                elif uid not in referenced.get(name, set()):
                    errors.append(f'{location}: {uid} must reference this implementation file')
                else:
                    traces[uid].append({'path': name, 'line': line})
    for uid, record in records.items():
        if record['prefix'].startswith('LLR-') and uid not in traces:
            errors.append(f'{uid}: no implementation @llr comment')
    if errors:
        raise ValueError('\n'.join(errors))
    return dict(sorted(traces.items()))
