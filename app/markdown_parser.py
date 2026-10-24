"""
The Markdown dialect OpenDocs exports.

It matches what the web view renders (packages/shared/src/markdown in the
main repo): CommonMark + GitHub (tables, ``~~strike~~``, task lists,
autolinked URLs, footnotes, ``> [!NOTE]`` alerts), YAML front matter,
``$math$``, ``==highlight==``, ``H~2~O`` / ``x^2^``, definition lists and
emoji shortcodes, with smart quotes and dashes.
"""

from __future__ import annotations

import re
import unicodedata

from markdown_it import MarkdownIt
from markdown_it.rules_inline.state_inline import Delimiter, StateInline
from mdit_py_plugins.deflist import deflist_plugin
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.front_matter import front_matter_plugin
from mdit_py_plugins.gfm_autolink import gfm_autolink_plugin
from mdit_py_plugins.subscript import sub_plugin
from mdit_py_plugins.superscript import superscript_plugin

# ```private fences never leave the author's copy (same rule as the web's
# stripPrivateBlocks).
_PRIVATE_BLOCK = re.compile(r"```private\s*\n[\s\S]*?\n```")
# PHP Markdown Extra abbreviations: ``*[HTML]: HyperText Markup Language``.
_ABBREVIATION = re.compile(r"^\*\[([^\]\n]+)\]:[ \t]*(.+?)[ \t]*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def preprocess(md_text: str) -> str:
    """Drop private blocks and abbreviation definitions."""
    md_text = md_text.replace("\r\n", "\n").replace("\r", "\n")
    md_text = _PRIVATE_BLOCK.sub("", md_text)
    out: list[str] = []
    fence: str | None = None
    for line in md_text.split("\n"):
        m = _FENCE.match(line)
        if m:
            marker = m.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
        elif fence is None and _ABBREVIATION.match(line):
            continue
        out.append(line)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# ==highlight== (markdown-it-mark), built like ~~strikethrough~~
# ---------------------------------------------------------------------------

def _mark_tokenize(state: StateInline, silent: bool) -> bool:
    start = state.pos
    if silent or state.src[start] != "=":
        return False
    scanned = state.scanDelims(start, True)
    length = scanned.length
    if length < 2:
        return False
    if length % 2:
        token = state.push("text", "", 0)
        token.content = "="
        length -= 1
    for _ in range(0, length, 2):
        token = state.push("text", "", 0)
        token.content = "=="
        state.delimiters.append(Delimiter(
            marker=ord("="), length=0, token=len(state.tokens) - 1, end=-1,
            open=scanned.can_open, close=scanned.can_close,
        ))
    state.pos += scanned.length
    return True


def _mark_pairs(state: StateInline, delimiters: list[Delimiter]) -> None:
    for start in delimiters:
        if start.marker != ord("=") or start.end == -1:
            continue
        end = delimiters[start.end]
        for index, kind, nesting in ((start.token, "mark_open", 1), (end.token, "mark_close", -1)):
            token = state.tokens[index]
            token.type, token.tag, token.nesting = kind, "mark", nesting
            token.markup, token.content = "==", ""


def _mark_post_process(state: StateInline) -> None:
    _mark_pairs(state, state.delimiters)
    for meta in state.tokens_meta:
        if meta and "delimiters" in meta:
            _mark_pairs(state, meta["delimiters"])


def _mark_plugin(md: MarkdownIt) -> None:
    md.inline.ruler.before("emphasis", "mark", _mark_tokenize)
    md.inline.ruler2.before("emphasis", "mark", _mark_post_process)


def make_parser() -> MarkdownIt:
    md = MarkdownIt("commonmark", {"typographer": True})
    md.enable(["table", "strikethrough", "replacements", "smartquotes"])
    md.options["tasklists"] = True
    md.options["alerts"] = True
    md.use(front_matter_plugin)
    md.use(footnote_plugin, inline=False)
    md.use(gfm_autolink_plugin)
    md.use(deflist_plugin)
    # Pandoc's rule keeps prices as text: no space just inside the dollars
    # and no digit right after the closing one ("$5 and $10").
    md.use(dollarmath_plugin, allow_blank_lines=False, allow_space=False,
           allow_digits=False, double_inline=True)
    md.use(sub_plugin)
    md.use(superscript_plugin)
    md.use(_mark_plugin)
    # markdown-it only allows GIF/PNG/JPEG/WebP data: URLs (a guard for
    # HTML output). SVG is rasterized here without scripts or external
    # files, so it's safe too.
    default_validate_link = md.validateLink
    md.validateLink = lambda url: (
        url.strip().lower().startswith("data:image/svg+xml;base64,")
        or default_validate_link(url)
    )
    return md


# ---------------------------------------------------------------------------
# Heading slugs — the same ids rehype-slug (github-slugger) gives headings
# on the web, so ``[link](#5-tables)`` works in exports too.
# ---------------------------------------------------------------------------

class Slugger:
    def __init__(self):
        self._seen: dict[str, int] = {}

    def slug(self, text: str) -> str:
        base = "".join(
            ch for ch in text.lower()
            if ch in " -_" or unicodedata.category(ch)[0] in "LNM"
        ).replace(" ", "-")
        slug = base
        while slug in self._seen:
            self._seen[base] += 1
            slug = f"{base}-{self._seen[base]}"
        self._seen[slug] = 0
        return slug


def emojize(text: str) -> str:
    """``:rocket:`` → 🚀 (GitHub shortcodes, as remark-emoji does on the web)."""
    if ":" not in text:
        return text
    try:
        import emoji
    except ImportError:
        return text
    return emoji.emojize(text, language="alias")
