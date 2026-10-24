"""
Signature blocks: a ```signature fence listing who signs a document.

    ```signature
    - role: Employee
      name: John Adams
      title: Head of Engineering
    - role: Board member
      name: Jón Jónsson
    ```

The exports draw one signature box per entry (``DocxBuilder.signature_block``)
and, with ``signature_fields``, put DocuSeal field tags in each box. The same
parsing rules live in the main repo's
``packages/shared/src/markdown/signature-blocks.ts``; keep them in step.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

MAX_ROLE_LENGTH = 60

_INFO = re.compile(r"[ \t]*signature[ \t]*", re.I)
_ROLE_FORBIDDEN = re.compile(r"[;{}=\n]")
_ITEM = re.compile(r"^\s*-\s+(.*)$")
_PAIR = re.compile(r"^\s*([A-Za-z_]+)\s*:\s*(.*)$")
_QUOTED = re.compile(r"([\"']).*\1")


@dataclass(frozen=True)
class SignatureEntry:
    role: str
    name: Optional[str] = None
    title: Optional[str] = None


def is_signature_info(info: str) -> bool:
    """Whether a fence's info string marks a signature block."""
    return bool(_INFO.fullmatch(info or ""))


def _unquote(value: str) -> str:
    trimmed = value.strip()
    if len(trimmed) >= 2 and _QUOTED.fullmatch(trimmed):
        return trimmed[1:-1].strip()
    return trimmed


def _js_length(text: str) -> int:
    """``text.length`` in JavaScript (UTF-16 code units), so a role with
    emoji is measured as the web measures it."""
    return len(text.encode("utf-16-le")) // 2


def is_valid_role(role: str) -> bool:
    return 0 < _js_length(role) <= MAX_ROLE_LENGTH and not _ROLE_FORBIDDEN.search(role)


def parse_signature_block(body: str) -> Optional[list[SignatureEntry]]:
    """The entries of one block's body, or ``None`` when it isn't a valid
    signature block and should be drawn as an ordinary code block.

    An entry starts with a ``- `` line (the rest of that line is a
    ``key: value`` pair too); the lines after it are ``key: value`` pairs.
    Keys are case-insensitive and only ``role``, ``name`` and ``title`` are
    used; values are trimmed and lose one level of matching quotes. The
    block is invalid if text comes before the first entry, there are no
    entries, or any role is missing, longer than 60 characters, contains
    ``;``, ``{``, ``}`` or ``=``, or repeats another (ignoring case).
    """
    entries: list[dict[str, str]] = []
    for raw_line in body.split("\n"):
        if not raw_line.strip():
            continue
        item = _ITEM.match(raw_line)
        content = item.group(1) if item else raw_line
        if item:
            entries.append({})
        if not entries:
            return None
        pair = _PAIR.match(content)
        if pair:
            entries[-1][pair.group(1).lower()] = _unquote(pair.group(2))
    if not entries:
        return None

    seen: set[str] = set()
    result: list[SignatureEntry] = []
    for entry in entries:
        role = entry.get("role", "")
        if not is_valid_role(role) or role.lower() in seen:
            return None
        seen.add(role.lower())
        result.append(SignatureEntry(role, entry.get("name") or None, entry.get("title") or None))
    return result


def field_tag(name: str, field_type: str, role: str, *, width: int, height: int) -> str:
    """A DocuSeal text tag, e.g. ``{{Employee signature;type=signature;
    role=Employee;width=200;height=38}}``. ``width``/``height`` are in
    DocuSeal's "pixels", which for a PDF are points (see
    ``converter.SIGNATURE_AREA``)."""
    return f"{{{{{name};type={field_type};role={role};width={width};height={height}}}}}"


def signature_tag(role: str, *, width: int, height: int) -> str:
    return field_tag(f"{role} signature", "signature", role, width=width, height=height)


def date_tag(role: str, *, width: int, height: int) -> str:
    return field_tag(f"{role} date", "datenow", role, width=width, height=height)
