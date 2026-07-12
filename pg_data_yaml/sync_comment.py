from __future__ import annotations

import re
from dataclasses import dataclass

SYNC_DIRECTORY_MARKER = 'synchronized directory'
SELECT_WORD_RE = re.compile(r'\bselect\b', re.IGNORECASE)


@dataclass(frozen=True)
class ParsedComment:
    custom_select: str | None
    where_filter: str | None


def _label_pattern(label: str) -> re.Pattern[str]:
    parts = re.split(r'\s+', label.strip())
    pattern = r'\s+'.join(re.escape(part) for part in parts if part)
    return re.compile(pattern, re.IGNORECASE)


def _extract_parenthesized(text: str, open_pos: int) -> str | None:
    if open_pos >= len(text) or text[open_pos] != '(':
        return None
    depth = 0
    for index in range(open_pos, len(text)):
        char = text[index]
        if char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
            if depth == 0:
                return text[open_pos + 1:index].strip()
    return None


def parse_table_comment(
    comment: str | None,
    label: str = SYNC_DIRECTORY_MARKER,
) -> ParsedComment | None:
    if not comment or label.lower() not in comment.lower():
        return None
    match = _label_pattern(label).search(comment)
    if not match:
        return None

    pos = match.end()
    while pos < len(comment) and comment[pos].isspace():
        pos += 1

    if pos >= len(comment) or comment[pos] != '(':
        return ParsedComment(custom_select=None, where_filter=None)

    paren = _extract_parenthesized(comment, pos)
    if not paren:
        return ParsedComment(custom_select=None, where_filter=None)

    if SELECT_WORD_RE.search(paren):
        return ParsedComment(custom_select=paren, where_filter=None)
    return ParsedComment(custom_select=None, where_filter=paren)
