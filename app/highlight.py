"""
Syntax highlighting for code blocks, in the GitHub Light palette the web
view uses (rehype-pretty-code with Shiki's ``github-light``), so a code
block looks the same on the page and in the export.
"""

from __future__ import annotations

from typing import Optional

# (color, italic) per Pygments token type, most specific first.
_PALETTE: list[tuple[str, str, bool]] = [
    ("Comment", "6E7781", True),
    ("Keyword.Constant", "0550AE", False),
    ("Keyword", "CF222E", False),
    ("Operator.Word", "CF222E", False),
    ("Operator", "CF222E", False),
    ("Name.Builtin.Pseudo", "0550AE", False),
    ("Name.Builtin", "0550AE", False),
    ("Name.Function", "8250DF", False),
    ("Name.Class", "8250DF", False),
    ("Name.Decorator", "8250DF", False),
    ("Name.Tag", "116329", False),
    ("Name.Attribute", "0550AE", False),
    ("Name.Constant", "0550AE", False),
    ("Name.Variable", "953800", False),
    ("Name.Label", "953800", False),
    ("Literal.String.Escape", "0550AE", False),
    ("Literal.String.Regex", "0A3069", False),
    ("Literal.String", "0A3069", False),
    ("Literal.Number", "0550AE", False),
    ("Literal", "0550AE", False),
    ("Generic.Inserted", "116329", False),
    ("Generic.Deleted", "82071E", False),
    ("Generic.Heading", "0550AE", False),
    ("Generic.Subheading", "0550AE", False),
    ("Generic.Emph", "24292F", True),
]

# Whole-line washes for diffs.
DIFF_BACKGROUNDS = {"+": "E6FFEC", "-": "FFEBE9"}

# Fence names people use that Pygments spells differently.
_ALIASES = {"ts": "typescript", "tsx": "tsx", "js": "javascript", "jsx": "jsx",
            "sh": "bash", "shell": "bash", "zsh": "bash", "console": "console",
            "yml": "yaml", "py": "python", "rb": "ruby", "md": "markdown",
            "dockerfile": "docker", "jsonc": "json", "plaintext": "text", "txt": "text"}


def _style(ttype) -> tuple[Optional[str], bool]:
    name = str(ttype).removeprefix("Token.")
    for prefix, color, italic in _PALETTE:
        if name == prefix or name.startswith(prefix + "."):
            return color, italic
    return None, False


def language_of(info: str) -> str:
    """The language named in a fence's info string (``python title=x`` → python)."""
    return (info or "").strip().split(maxsplit=1)[0].lower() if (info or "").strip() else ""


def highlight(code: str, language: str) -> Optional[list[tuple[str, Optional[str], bool]]]:
    """``(text, color, italic)`` pieces for ``code``, or ``None`` when the
    language is unknown or empty (the block is then drawn plain)."""
    if not language or language in ("text", "math", "mermaid"):
        return None
    try:
        from pygments.lexers import get_lexer_by_name
        from pygments.util import ClassNotFound

        lexer = get_lexer_by_name(_ALIASES.get(language, language), stripnl=False, ensurenl=False)
    except (ImportError, ClassNotFound):
        return None
    pieces: list[tuple[str, Optional[str], bool]] = []
    for ttype, value in lexer.get_tokens(code):
        if not value:
            continue
        color, italic = _style(ttype)
        if pieces and pieces[-1][1] == color and pieces[-1][2] == italic:
            pieces[-1] = (pieces[-1][0] + value, color, italic)
        else:
            pieces.append((value, color, italic))
    return pieces
