"""
OpenDocs Markdown-to-DOCX Converter

Turns Markdown into a styled Word document with configurable branding.
The PDF export is LibreOffice's print of the same document, so everything
here shapes both formats.

Layout model
------------
Blocks are rendered into a *frame*: the document body, or the single cell
of a "box" table. Quotes, GitHub alerts and code blocks are boxes, so any
block (headings, lists, code, tables, images) can sit inside them and
keeps the box's bar or background, and boxes nest. Lists indent their
content with ``self._indent`` instead.
"""

from __future__ import annotations

import io
import os
import re
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Optional

from docx import Document
from docx.blkcntnr import BlockItemContainer
from docx.enum.section import WD_ORIENT
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_ALIGN_VERTICAL, WD_ROW_HEIGHT_RULE, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Cm, Emu, Inches, Pt, RGBColor
from lxml import etree

from .branding import BrandingConfig, OPENDOCS_BRAND
from .highlight import DIFF_BACKGROUNDS, highlight, language_of
from .images import BUNDLED_LOGO_SENTINEL, PreparedImage, prefetch_images, prepare_image_source, resolve_logo
from .markdown_parser import Slugger, emojize, make_parser, preprocess
from .math_omml import latex_to_omml
from .signature_blocks import SignatureEntry, date_tag, is_signature_info, parse_signature_block, signature_tag

__all__ = ["convert_md_to_docx", "BUNDLED_LOGO_SENTINEL"]

# ---------------------------------------------------------------------------
# House style
# ---------------------------------------------------------------------------

BODY_SIZE = Pt(10.5)
BODY_LINE = 1.3            # line height, as a multiple of single spacing
PARA_AFTER = Pt(7)         # space after a body paragraph
SMALL_SIZE = Pt(9)
CODE_SIZE = Pt(8.5)
CODE_LINE = Pt(12.5)       # exact line height in code blocks
QUOTE_TEXT = "404040"
MARK_FILL = "FDEFB2"
KBD_FILL = "F6F8FA"
KBD_BORDER = "D0D7DE"

# (size, bold, italic, all caps, space before, space after) per level.
HEADINGS = {
    1: (Pt(18), True, False, False, Pt(22), Pt(8)),
    2: (Pt(15), True, False, False, Pt(20), Pt(6)),
    3: (Pt(12.5), True, False, False, Pt(16), Pt(4)),
    4: (Pt(11), True, False, False, Pt(13), Pt(3)),
    5: (Pt(9.5), True, False, True, Pt(12), Pt(3)),
    6: (Pt(10), False, True, False, Pt(10), Pt(2)),
}
TITLE_SIZE = Pt(24)

# GitHub alert kinds: label, accent, background.
ALERTS = {
    "NOTE": ("Note", "0969DA", "F0F6FF"),
    "TIP": ("Tip", "1A7F37", "EFF8F1"),
    "IMPORTANT": ("Important", "8250DF", "F6F1FF"),
    "WARNING": ("Warning", "9A6700", "FFF8E5"),
    "CAUTION": ("Caution", "CF222E", "FFF1F0"),
}

# Lists: where level L's text starts, and how far the marker hangs left.
LIST_TEXT = Cm(0.85)
LIST_STEP = Cm(0.65)
LIST_HANG = Cm(0.6)
BULLETS = ("•", "◦", "▪")
ORDERED_FORMATS = (("decimal", "%{n}."), ("lowerLetter", "%{n}."), ("lowerRoman", "%{n}."))

# Pictures are drawn at the share of the page they take of the web view's
# text column, which is about this many CSS pixels wide.
WEB_COLUMN_PX = 720
# A figure never takes more than this share of the page's text height, so
# a heading and its figure (or two figures) usually share a page.
FIGURE_MAX_HEIGHT = 0.42

# Signature boxes (```signature blocks), two per row.
SIGNATURE_GAP = Pt(28)        # between the two boxes of a row
SIGNATURE_AREA = Pt(40)       # blank space to sign in, down to the line
SIGNATURE_ROW_GAP = Pt(20)    # between rows of boxes
DATE_LABEL = Pt(30)           # where the date line starts
DATE_LINE = Pt(120)           # how long it is
DATE_LINE_HEIGHT = Pt(18)     # blank space to write the date in, down to the line
# DocuSeal field tags (``signature_fields``) are white 1 pt text (Word's
# smallest size) on a line of their own at the top-left of the area the
# field covers. A tag never moves the visible layout, and even the tag for
# a 60-character role of wide letters stays on one line (a tag split over
# two lines is no longer a tag).
#
# DocuSeal puts the field where the tag is, sized by the tag's ``width``
# and ``height``. Units: DocuSeal's docs say "pixels" ("Absolute width of
# the field in pixels" at
# https://www.docuseal.com/guides/use-embedded-text-field-tags-in-the-pdf-to-create-a-fillable-form,
# "Width in pixels" in the docuseal@1.0.4 npm package's
# skills/docuseal-cli/references/field-tags.md) without defining a pixel.
# For a PDF that is the PDF unit, the point (1/72 in): DocuSeal reads pages
# with PDFium and scales field areas by the page size in points
# (lib/templates/find_pdfium_acro_fields.rb in github.com/docusealco/docuseal),
# and its sample https://www.docuseal.com/examples/fieldtags.pdf sizes an
# image field width=200;height=30 on a 612 x 792 pt page. So the sizes we
# write are points: the box width x the signature area, and the date line.
TAG_SIZE = Pt(1)
TAG_LINE = Pt(4)              # height of a tag's line
TAG_COLOR = "FFFFFF"
# The tag's glyphs start this far below the top of its line (measured in
# LibreOffice's PDF: pdftotext -bbox), so the field reaches the line.
TAG_TOP = Pt(2.3)

PAGE_BREAK_TEXT = {"\\pagebreak", "\\newpage", "\\clearpage"}
_PAGE_BREAK_HTML = re.compile(
    r"<!--\s*(?:page-?break|new-?page)\s*-->"
    r"|<(?:div|hr|p|span)\b[^>]*style\s*=\s*['\"][^'\"]*(?:page-break-(?:before|after)\s*:\s*always"
    r"|break-(?:before|after)\s*:\s*page)[^'\"]*['\"][^>]*>(?:\s*</(?:div|p|span)>)?",
    re.I,
)
_FORMULA = re.compile(r"^formula\((.+)\)$", re.S)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _hex_to_rgb(hex_color: str) -> RGBColor:
    h = hex_color.lstrip("#")
    return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _hex_strip(hex_color: str) -> str:
    return hex_color.lstrip("#").upper()


def _twips(length) -> int:
    return int(Emu(length).pt * 20)


def _points(length) -> int:
    return round(Emu(int(length)).pt)


def _detect_metadata_line(line: str) -> bool:
    """Return True if a line looks like 'Key: value | Key: value | ...'."""
    if "|" not in line or line.startswith("|"):
        return False
    parts = [p.strip() for p in line.split("|")]
    kv_count = sum(1 for p in parts if ":" in p and len(p) < 100)
    return kv_count >= 2


# Elements that follow w:pBdr inside w:pPr (Word rejects out-of-order ones).
_PPR_AFTER_PBDR = (
    "w:shd", "w:tabs", "w:suppressAutoHyphens", "w:kinsoku", "w:wordWrap",
    "w:overflowPunct", "w:topLinePunct", "w:autoSpaceDE", "w:autoSpaceDN",
    "w:bidi", "w:adjustRightInd", "w:snapToGrid", "w:spacing", "w:ind",
    "w:contextualSpacing", "w:mirrorIndents", "w:suppressOverlap", "w:jc",
    "w:textDirection", "w:textAlignment", "w:textboxTightWrap",
    "w:outlineLvl", "w:divId", "w:cnfStyle", "w:rPr", "w:sectPr", "w:pPrChange",
)
# Elements that follow w:shd / w:bdr inside w:rPr.
_RPR_AFTER_SHD = ("w:fitText", "w:vertAlign", "w:rtl", "w:cs", "w:em", "w:lang",
                  "w:eastAsianLayout", "w:specVanish", "w:oMath")
_RPR_AFTER_BDR = ("w:shd",) + _RPR_AFTER_SHD
# Elements that follow w:tcBorders inside w:tcPr.
_TCPR_AFTER_BORDERS = ("w:shd", "w:noWrap", "w:tcMar", "w:textDirection",
                       "w:tcFitText", "w:vAlign", "w:hideMark")
# Elements that follow w:cantSplit inside w:trPr.
_TRPR_AFTER_CANT_SPLIT = ("w:trHeight", "w:tblHeader", "w:tblCellSpacing", "w:jc", "w:hidden")


def _border(side: str, color: str, size: int, space: int = 0) -> str:
    return f'<w:{side} w:val="single" w:sz="{size}" w:space="{space}" w:color="{color}"/>'


def _no_border(side: str) -> str:
    return f'<w:{side} w:val="nil"/>'


def _set_paragraph_border(p, side: str, color: str, size: int, space: int):
    p_pr = p._p.get_or_add_pPr()
    pbdr = p_pr.find(qn("w:pBdr"))
    if pbdr is None:
        pbdr = p_pr.insert_element_before(parse_xml(f'<w:pBdr {nsdecls("w")}/>'), *_PPR_AFTER_PBDR)
    pbdr.append(parse_xml(f'<w:{side} {nsdecls("w")} w:val="single" w:sz="{size}" '
                          f'w:space="{space}" w:color="{color}"/>'))


def _shade_paragraph(p, fill: str):
    p._p.get_or_add_pPr().insert_element_before(
        parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill}" w:val="clear"/>'), *_PPR_AFTER_PBDR[1:])


def _shade_run(run, fill: str):
    run._r.get_or_add_rPr().insert_element_before(
        parse_xml(f'<w:shd {nsdecls("w")} w:val="clear" w:color="auto" w:fill="{fill}"/>'),
        *_RPR_AFTER_SHD)


def _border_run(run, color: str):
    run._r.get_or_add_rPr().insert_element_before(
        parse_xml(f'<w:bdr {nsdecls("w")} w:val="single" w:sz="4" w:space="1" w:color="{color}"/>'),
        *_RPR_AFTER_BDR)


def _letter_spacing(run, twentieths: int):
    run._r.get_or_add_rPr().insert_element_before(
        parse_xml(f'<w:spacing {nsdecls("w")} w:val="{twentieths}"/>'),
        "w:w", "w:kern", "w:position", "w:sz", "w:szCs", "w:highlight", "w:u",
        "w:effect", "w:bdr", "w:shd", *_RPR_AFTER_SHD)


def _keep_with_next(p):
    p.paragraph_format.keep_with_next = True


def _set_cell_shading(cell, fill: str):
    cell._tc.get_or_add_tcPr().insert_element_before(
        parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill}" w:val="clear"/>'), *_TCPR_AFTER_BORDERS[1:])


def _cant_split(row):
    row._tr.get_or_add_trPr().insert_element_before(
        parse_xml(f'<w:cantSplit {nsdecls("w")}/>'), *_TRPR_AFTER_CANT_SPLIT)


def _set_cell_margins(cell, *, top=0, right=0, bottom=0, left=0):
    """Padding of one cell, in twips (overrides the table's)."""
    cell._tc.get_or_add_tcPr().insert_element_before(
        parse_xml(f'<w:tcMar {nsdecls("w")}>'
                  f'<w:top w:w="{top}" w:type="dxa"/><w:left w:w="{left}" w:type="dxa"/>'
                  f'<w:bottom w:w="{bottom}" w:type="dxa"/><w:right w:w="{right}" w:type="dxa"/>'
                  f'</w:tcMar>'),
        *_TCPR_AFTER_BORDERS[_TCPR_AFTER_BORDERS.index("w:tcMar") + 1:])


def _exact_line(p, height, *, before=Pt(0), after=Pt(0)):
    pf = p.paragraph_format
    pf.space_before = before
    pf.space_after = after
    pf.line_spacing = Emu(int(height))  # a Length: a plain number is a multiple
    pf.line_spacing_rule = 4  # exact


def _repeat_header(row):
    row._tr.get_or_add_trPr().insert_element_before(
        parse_xml(f'<w:tblHeader {nsdecls("w")}/>'), *_TRPR_AFTER_CANT_SPLIT[2:])


def _table_properties(table, *, width, indent, borders: str, margins: tuple[int, int, int, int]):
    """Fixed layout at ``width`` (EMU), ``indent`` from the frame's left
    edge, with ``borders`` (w:tblBorders children) and cell ``margins``
    (top, right, bottom, left, in twips)."""
    tbl_pr = table._tbl.tblPr
    for tag in ("w:tblW", "w:tblInd", "w:tblBorders", "w:tblLayout", "w:tblCellMar", "w:tblLook", "w:jc"):
        for el in tbl_pr.findall(qn(tag)):
            tbl_pr.remove(el)
    top, right, bottom, left = margins
    tbl_pr.append(parse_xml(f'<w:tblW {nsdecls("w")} w:w="{_twips(width)}" w:type="dxa"/>'))
    tbl_pr.append(parse_xml(f'<w:tblInd {nsdecls("w")} w:w="{_twips(indent)}" w:type="dxa"/>'))
    tbl_pr.append(parse_xml(f'<w:tblBorders {nsdecls("w")}>{borders}</w:tblBorders>'))
    tbl_pr.append(parse_xml(f'<w:tblLayout {nsdecls("w")} w:type="fixed"/>'))
    tbl_pr.append(parse_xml(
        f'<w:tblCellMar {nsdecls("w")}>'
        f'<w:top w:w="{top}" w:type="dxa"/><w:left w:w="{left}" w:type="dxa"/>'
        f'<w:bottom w:w="{bottom}" w:type="dxa"/><w:right w:w="{right}" w:type="dxa"/>'
        f'</w:tblCellMar>'))
    tbl_pr.append(parse_xml(f'<w:tblLook {nsdecls("w")} w:val="0000" w:firstRow="0" w:lastRow="0" '
                            f'w:firstColumn="0" w:lastColumn="0" w:noHBand="1" w:noVBand="1"/>'))


# ---------------------------------------------------------------------------
# Inline content → styled segments
# ---------------------------------------------------------------------------

_SEGMENT_DEFAULTS = {
    "text": "", "bold": False, "italic": False, "underline": False,
    "strike": False, "code": False, "kbd": False, "sup": False, "sub": False,
    "mark": False, "small": False, "link": None, "image": None, "math": None,
}
_STYLE_KEYS = ("bold", "italic", "underline", "strike", "code", "kbd", "sup", "sub", "mark", "small")

# Inline HTML tags that map to run formatting. Other tags are dropped and
# their text kept.
_HTML_INLINE_STYLES = {
    "b": "bold", "strong": "bold", "i": "italic", "em": "italic", "cite": "italic",
    "var": "italic", "u": "underline", "ins": "underline",
    "s": "strike", "del": "strike", "strike": "strike",
    "sub": "sub", "sup": "sup", "code": "code", "samp": "code", "tt": "code",
    "kbd": "kbd", "mark": "mark", "small": "small",
}
_TOKEN_STYLES = {"strong": "bold", "em": "italic", "s": "strike", "sub": "sub",
                 "sup": "sup", "mark": "mark"}


def _html_attr(tag: str, name: str) -> str:
    import html as html_lib

    m = re.search(rf"""\b{name}\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", tag, re.I)
    if not m:
        return ""
    return html_lib.unescape(next(g for g in m.groups() if g is not None))


def _image_attrs(tag_or_token) -> dict:
    """``src``, ``alt``, ``title`` and CSS ``width``/``height`` of an image."""
    if isinstance(tag_or_token, str):
        get = lambda name: _html_attr(tag_or_token, name)  # noqa: E731
        alt = get("alt")
    else:
        get = lambda name: tag_or_token.attrGet(name) or ""  # noqa: E731
        alt = tag_or_token.content or ""
    size = {}
    for dim in ("width", "height"):
        m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(?:px)?\s*", get(dim))
        if m:
            size[dim] = float(m.group(1))
    return {"src": get("src"), "alt": alt, "title": get("title"), **size}


def _inline_segments(tokens) -> list[dict]:
    """Styled text segments from markdown-it inline tokens.

    Working from the parser's tokens keeps escaped characters literal:
    ``\\*not italic\\*`` stays as text. Images become ``image`` segments
    and ``$math$`` becomes ``math`` segments for the caller to embed.
    """
    segments: list[dict] = []
    depth = dict.fromkeys(_STYLE_KEYS, 0)
    links: list[Optional[str]] = []

    def add(text: str = "", **extra):
        if not text and not extra:
            return
        seg = dict(_SEGMENT_DEFAULTS, text=text, link=links[-1] if links else None)
        seg.update({k: v > 0 for k, v in depth.items()})
        seg.update(extra)
        segments.append(seg)

    def toggle(key: str, opening: bool):
        depth[key] = max(0, depth[key] + (1 if opening else -1))

    for tok in tokens or []:
        t = tok.type
        base = t.rsplit("_", 1)[0]
        if t == "text":
            add(emojize(tok.content))
        elif t == "code_inline":
            add(tok.content, code=True)
        elif t == "softbreak":
            add(" ")
        elif t == "hardbreak":
            add("\n")
        elif base in _TOKEN_STYLES and t.endswith(("_open", "_close")):
            toggle(_TOKEN_STYLES[base], t.endswith("_open"))
        elif t == "link_open":
            links.append(tok.attrGet("href") or None)
        elif t == "link_close":
            if links:
                links.pop()
        elif t == "image":
            add(image=_image_attrs(tok))
        elif t in ("math_inline", "math_inline_double"):
            add(math=tok.content, display=t == "math_inline_double")
        elif t == "footnote_ref":
            n = tok.meta["id"] + 1
            links.append(f"#__fn_{n}")
            add(str(n), sup=True)
            links.pop()
        elif t == "footnote_anchor":
            continue
        elif t == "html_inline":
            m = re.match(r"<\s*(/?)\s*([a-zA-Z][a-zA-Z0-9]*)", tok.content)
            if not m:
                continue  # comments, processing instructions
            closing, name = m.group(1) == "/", m.group(2).lower()
            self_closing = tok.content.rstrip().endswith("/>")
            if name == "br":
                add("\n")
            elif name == "img" and not closing:
                add(image=_image_attrs(tok.content))
            elif name == "a":
                if closing:
                    if links:
                        links.pop()
                elif not self_closing:
                    links.append(_html_attr(tok.content, "href") or None)
            elif name in _HTML_INLINE_STYLES and not self_closing:
                toggle(_HTML_INLINE_STYLES[name], not closing)
        elif tok.children:
            segments.extend(_inline_segments(tok.children))
        elif tok.content:
            add(tok.content)
    return segments


def _segments_text(segments: list[dict]) -> str:
    return "".join(seg["text"] for seg in segments)


def _plain(text: str) -> list[dict]:
    return [dict(_SEGMENT_DEFAULTS, text=text)]


def _only_images(segments: list[dict]) -> list[dict]:
    """The image segments of an image-only paragraph (``![a](x)`` or
    several images, possibly wrapped in links), else ``[]``."""
    images = [seg for seg in segments if seg["image"]]
    if not images or any(not seg["image"] and seg["text"].strip() for seg in segments):
        return []
    return images


class _HtmlSegments(HTMLParser):
    """Raw HTML → paragraphs of styled segments, for ``html_block``s.

    Block-level tags start a new paragraph; inline tags become formatting.
    Scripts, styles and comments are dropped.
    """

    BLOCK = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "summary",
             "details", "blockquote", "section", "article", "ul", "ol", "dl", "dt", "dd",
             "header", "footer", "figure", "figcaption", "center", "pre", "table"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.paragraphs: list[tuple[str, list[dict]]] = []
        self._current: list[dict] = []
        self._tag = ""
        self._depth = dict.fromkeys(_STYLE_KEYS, 0)
        self._links: list[Optional[str]] = []
        self._skip = 0

    def _flush(self):
        if any(seg["text"].strip() or seg["image"] for seg in self._current):
            while self._current and not self._current[-1]["image"] and not self._current[-1]["text"].strip("\n "):
                self._current.pop()
            self.paragraphs.append((self._tag, self._current))
        self._current = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "template"):
            self._skip += 1
        elif tag in self.BLOCK:
            self._flush()
            self._tag = tag
        elif tag == "br":
            self._add("\n")
        elif tag == "img":
            self._add("", image=_image_attrs(self.get_starttag_text() or ""))
        elif tag == "a":
            self._links.append(dict(attrs).get("href"))
        elif tag in _HTML_INLINE_STYLES:
            self._depth[_HTML_INLINE_STYLES[tag]] += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "template"):
            self._skip = max(0, self._skip - 1)
        elif tag in self.BLOCK:
            self._flush()
        elif tag == "a" and self._links:
            self._links.pop()
        elif tag in _HTML_INLINE_STYLES:
            key = _HTML_INLINE_STYLES[tag]
            self._depth[key] = max(0, self._depth[key] - 1)

    def handle_data(self, data):
        if self._skip:
            return
        text = re.sub(r"\s+", " ", data)
        if text.strip() or (self._current and text):
            self._add(text)

    def _add(self, text, **extra):
        seg = dict(_SEGMENT_DEFAULTS, text=text, link=self._links[-1] if self._links else None)
        seg.update({k: v > 0 for k, v in self._depth.items()})
        seg.update(extra)
        self._current.append(seg)

    def close(self):
        super().close()
        self._flush()


class _HtmlTables(HTMLParser):
    """The rows of each ``<table>`` in a raw HTML block, as cell segments."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables: list[list[tuple[bool, list[list[dict]]]]] = []
        self._row: Optional[list] = None
        self._cell: Optional[_HtmlSegments] = None
        self._header_row = False

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.tables.append([])
        elif tag == "tr":
            self._row, self._header_row = [], True
        elif tag in ("td", "th"):
            self._cell = _HtmlSegments()
            self._header_row = self._header_row and tag == "th"
        elif self._cell is not None:
            self._cell.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._cell.close()
            cell: list[dict] = []
            for n, (_, segs) in enumerate(self._cell.paragraphs):
                if n:
                    cell.append(dict(_SEGMENT_DEFAULTS, text="\n"))
                cell.extend(segs)
            self._row.append(cell)
            self._cell = None
        elif tag == "tr" and self._row is not None and self.tables:
            self.tables[-1].append((self._header_row, self._row))
            self._row = None
        elif self._cell is not None:
            self._cell.handle_endtag(tag)

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.handle_data(data)


# ---------------------------------------------------------------------------
# Frames
# ---------------------------------------------------------------------------

@dataclass
class _Frame:
    body: BlockItemContainer   # where blocks are added
    width: int                 # usable width in EMU
    fresh: Optional[object] = None  # a box cell's initial, still unused paragraph


# ---------------------------------------------------------------------------
# DocxBuilder
# ---------------------------------------------------------------------------

class DocxBuilder:
    """Stateful builder that turns markdown-it tokens into a styled Word doc."""

    def __init__(self, brand: BrandingConfig, *, landscape: bool = False,
                 page_break_before: int | None = None,
                 skip_first_break: bool = True,
                 signature_fields: bool = False):
        self.doc = Document()
        self.brand = brand
        self._landscape = landscape
        # Put DocuSeal field tags in signature boxes.
        self._signature_fields = signature_fields

        # Page-break config: which heading level triggers a break
        # e.g. page_break_before=2 means every H2 gets a page break above it.
        self._page_break_level = page_break_before
        self._skip_first_break = skip_first_break
        self._break_heading_count = 0

        self._c_heading = _hex_strip(brand.heading_color)
        self._c_body = _hex_strip(brand.body_color)
        self._c_muted = _hex_strip(brand.metadata_color)
        self._c_link = _hex_strip(brand.link_color)
        self._c_table_hdr_fg = _hex_strip(brand.table_header_fg)
        self._h_table_hdr_bg = _hex_strip(brand.table_header_bg)
        self._h_alt_row = _hex_strip(brand.alt_row_bg)
        self._h_border = _hex_strip(brand.border_color)
        self._h_code_bg = _hex_strip(brand.code_bg)
        self._h_code_border = _hex_strip(brand.code_border)

        self._setup_page()
        self._setup_styles()

        section = self.doc.sections[0]
        self._page_width = section.page_width - section.left_margin - section.right_margin
        self._page_height = section.page_height - section.top_margin - section.bottom_margin
        self._frames = [_Frame(self.doc._body, self._page_width)]

        # Block context
        self._indent = Emu(0)          # list indent of the current block
        self._list_level = 0           # nesting depth of lists in this frame
        self._ordered_depth = 0        # ordered lists around the current one
        self._align: Optional[WD_ALIGN_PARAGRAPH] = None
        self._text_color: Optional[str] = None
        self._tight = False            # inside a tight list item
        self._pending_break = False    # the next block starts a new page
        self._after_heading = False    # the last block was a heading
        self._last_rule = None
        self._last_p = None

        # Numbering
        self._num_counter = 100
        self._bullet_num: Optional[int] = None

        # Paragraph style name → style id (None for the default style)
        self._style_ids: dict[str, Optional[str]] = {}

        # Remote images downloaded up front (``prefetch_images``)
        self.prefetched: dict[str, Optional[bytes]] = {}

        # Bookmarks: heading slug → name, footnote anchors
        self.anchors: dict[str, str] = {}
        self._bookmark_id = 0

    # ── Page and styles ─────────────────────────────────────────────────

    def _setup_page(self):
        for section in self.doc.sections:
            if self._landscape:
                section.orientation = WD_ORIENT.LANDSCAPE
                section.page_width, section.page_height = Cm(29.7), Cm(21.0)
            else:
                section.orientation = WD_ORIENT.PORTRAIT
                section.page_width, section.page_height = Cm(21.0), Cm(29.7)
            for side in ("top_margin", "bottom_margin", "left_margin", "right_margin"):
                setattr(section, side, Cm(2.5))
            # Word's defaults are 0.5 in for both — pulling them in to
            # 0.3 in tucks the logo/footer closer to the content area.
            section.header_distance = Inches(0.3)
            section.footer_distance = Inches(0.3)

    def _setup_styles(self):
        styles = self.doc.styles
        b = self.brand

        sn = styles["Normal"]
        sn.font.name = b.font_main
        sn.font.size = BODY_SIZE
        sn.font.color.rgb = _hex_to_rgb(self._c_body)
        pf = sn.paragraph_format
        pf.space_before = Pt(0)
        pf.space_after = PARA_AFTER
        pf.line_spacing = BODY_LINE
        pf.widow_control = True
        # East Asian and complex scripts fall back to the same family.
        rfonts = sn.element.get_or_add_rPr().get_or_add_rFonts()
        for attr in ("w:eastAsia", "w:cs"):
            rfonts.set(qn(attr), b.font_main)

        st = styles["Title"]
        st.font.name = b.font_main
        st.font.size = TITLE_SIZE
        st.font.bold = True
        st.font.color.rgb = _hex_to_rgb(self._c_heading)
        st.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
        st.paragraph_format.space_before = Pt(0)
        st.paragraph_format.space_after = Pt(6)
        st.paragraph_format.line_spacing = 1.1
        st.paragraph_format.keep_with_next = True
        # The template's Title has a bottom rule; drop it.
        p_pr = st.element.get_or_add_pPr()
        for old in p_pr.findall(qn("w:pBdr")):
            p_pr.remove(old)

        for level, (size, bold, italic, caps, before, after) in HEADINGS.items():
            sh = styles[f"Heading {level}"]
            sh.font.name = b.font_main
            sh.font.size = size
            sh.font.bold = bold
            sh.font.italic = italic
            sh.font.all_caps = caps
            sh.font.color.rgb = _hex_to_rgb(self._heading_color(level))
            sh.paragraph_format.space_before = before
            sh.paragraph_format.space_after = after
            sh.paragraph_format.line_spacing = 1.15
            sh.paragraph_format.keep_with_next = True
            # Not keep-together: in LibreOffice it cancels keep-with-next
            # when the heading lands at the foot of a page.
            sh.paragraph_format.keep_together = False
            sh_rpr = sh.element.get_or_add_rPr()
            for el in sh_rpr.findall(qn("w:i")) + sh_rpr.findall(qn("w:iCs")):
                if not italic:
                    sh_rpr.remove(el)

    def _heading_color(self, level: int) -> str:
        if level <= 3 or level == 5:
            return self._c_heading
        if level == 6:
            return self._c_muted
        return self._c_body

    # ── Frames and paragraphs ───────────────────────────────────────────

    @property
    def _frame(self) -> _Frame:
        return self._frames[-1]

    @property
    def _available(self) -> int:
        return max(int(self._frame.width - self._indent), int(Cm(2)))

    def _style_id(self, name: str) -> Optional[str]:
        """The id to put in ``w:pStyle`` for a paragraph style, looked up
        once: python-docx scans every style for the default one on each
        assignment, which was a third of the build time."""
        if name not in self._style_ids:
            self._style_ids[name] = self.doc.part.get_style_id(name, WD_STYLE_TYPE.PARAGRAPH)
        return self._style_ids[name]

    def _add_paragraph(self, body, style: str = "Normal"):
        p = body.add_paragraph()
        p._p.style = self._style_id(style)
        return p

    def _new_paragraph(self, style: str = "Normal"):
        frame = self._frame
        if frame.fresh is not None:
            p, frame.fresh = frame.fresh, None
            p._p.style = self._style_id(style)
        else:
            p = self._add_paragraph(frame.body, style)
        if self._indent:
            p.paragraph_format.left_indent = self._indent
        if self._align is not None:
            p.alignment = self._align
        if self._pending_break:
            p.paragraph_format.page_break_before = True
            self._pending_break = False
        if self._after_heading and style == "Normal":
            # LibreOffice drops a heading's keep-with-next when widow control
            # stops the next paragraph from splitting (any two-line
            # paragraph at a page end), leaving the heading alone at the
            # bottom. Letting that one paragraph split keeps them together.
            p.paragraph_format.widow_control = False
        self._after_heading = False
        self._last_p = p
        return p

    def _keep_intro(self):
        """Keep a lead-in paragraph ("Python:", "Starting at seven:") on the
        same page as the block it introduces."""
        prev = self._last_p
        if prev is not None and prev.text.rstrip().endswith(":"):
            _keep_with_next(prev)

    def _take_pending_break(self):
        """Tables can't start a page themselves: put the break on an empty
        paragraph just above them."""
        if self._pending_break:
            p = self._new_paragraph()
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = Pt(1)
            p.paragraph_format.line_spacing_rule = 4

    def _spacer(self, height=PARA_AFTER):
        """An empty paragraph ``height`` tall. Keeps consecutive tables
        apart (Word merges touching tables) and spaces boxes."""
        p = self._add_paragraph(self._frame.body)
        pf = p.paragraph_format
        pf.space_before = Pt(0)
        pf.space_after = Pt(0)
        pf.line_spacing = Emu(int(height))
        pf.line_spacing_rule = 4  # exact
        self._last_p = None
        return p

    def _runs(self, p, segments, *, size=BODY_SIZE, color: Optional[str] = None,
              bold=False, italic=False, font: Optional[str] = None):
        """Add ``segments`` to ``p`` in the brand's fonts and colors."""
        color = color or self._text_color or self._c_body
        font = font or self.brand.font_main
        link_el, link_target = None, None
        for seg in segments:
            target = seg["link"]
            if target != link_target:
                link_el, link_target = (self._hyperlink(p, target) if target else None), target
            if seg["image"]:
                run = self._picture_run(p, seg["image"], inline=True)
                if run is None:
                    run = p.add_run(f"[{seg['image'].get('alt') or 'image'}]")
                    run.font.color.rgb = _hex_to_rgb(self._c_muted)
                    run.font.size = size
                    run.italic = True
                if link_el is not None:
                    link_el.append(run._r)
                continue
            if seg["math"] is not None:
                omml = latex_to_omml(seg["math"], display=False, font=self._math_font)
                if omml is not None:
                    (link_el if link_el is not None else p._p).append(omml)
                    continue
                seg = dict(seg, text=seg["math"], code=True)
            for n, part in enumerate(seg["text"].split("\n")):
                if n:
                    br = p.add_run()
                    br.add_break()
                    if link_el is not None:
                        link_el.append(br._r)
                if not part:
                    continue
                run = p.add_run(part)
                self._style_run(run, seg, size=size, color=color, bold=bold,
                                italic=italic, font=font, linked=link_target is not None)
                if link_el is not None:
                    link_el.append(run._r)

    def _style_run(self, run, seg, *, size, color, bold, italic, font, linked):
        f = run.font
        f.bold = bold or seg["bold"] or None
        f.italic = italic or seg["italic"] or None
        f.color.rgb = _hex_to_rgb(self._c_link if linked else color)
        f.name = font
        f.size = Pt(size.pt * 0.88) if seg["small"] else size
        if seg["code"] or seg["kbd"]:
            f.name = self.brand.code_block_font
            f.size = Pt(max(size.pt - 1.5, 6))
            _shade_run(run, KBD_FILL if seg["kbd"] else self._h_code_bg)
            if seg["kbd"]:
                _border_run(run, KBD_BORDER)
        if seg["mark"]:
            _shade_run(run, MARK_FILL)
        if seg["underline"] or linked:
            f.underline = True
        if linked and not seg["underline"]:
            # A quiet tinted underline, like the web's link style.
            run._r.rPr.find(qn("w:u")).set(qn("w:color"), self._h_code_border)
        if seg["strike"]:
            f.strike = True
        if seg["sup"]:
            f.superscript = True
        elif seg["sub"]:
            f.subscript = True

    @property
    def _math_font(self) -> str:
        return "Cambria Math"

    def _hyperlink(self, p, target: str):
        """An empty ``w:hyperlink`` appended to ``p``: an internal jump for
        ``#anchor`` targets, otherwise an external link."""
        if target.startswith("#"):
            key = target[1:]
            anchor = key if key.startswith("__fn_") else self.anchors.get(key)
            if anchor is None:
                return None
            el = parse_xml(f'<w:hyperlink {nsdecls("w")} w:anchor="{anchor}" w:history="1"/>')
        else:
            r_id = p.part.relate_to(
                target, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
                is_external=True)
            el = parse_xml(f'<w:hyperlink {nsdecls("w")} '
                           f'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
                           f'r:id="{r_id}"/>')
        p._p.append(el)
        return el

    def _bookmark(self, p, name: str):
        self._bookmark_id += 1
        start = parse_xml(f'<w:bookmarkStart {nsdecls("w")} w:id="{self._bookmark_id}" w:name="{name}"/>')
        end = parse_xml(f'<w:bookmarkEnd {nsdecls("w")} w:id="{self._bookmark_id}"/>')
        p_pr = p._p.find(qn("w:pPr"))
        if p_pr is not None:
            p_pr.addnext(start)
        else:
            p._p.insert(0, start)
        p._p.append(end)

    # ── Pictures ────────────────────────────────────────────────────────

    def _picture_run(self, p, image: dict, *, inline: bool, max_width: Optional[int] = None):
        """A run holding ``image``, or ``None`` if it can't be embedded.

        Pictures take the share of the page they'd take of the web column:
        an HTML ``width``, else the image's CSS size. Inline pictures are
        capped at a few lines tall; figures at part of the page.
        """
        prepared = prepare_image_source(image.get("src", ""), self.prefetched)
        if prepared is None:
            return None
        try:
            width, height = self._picture_size(prepared, image, inline=inline, max_width=max_width)
            run = p.add_run()
            run.add_picture(prepared.path, width=width, height=height)
            return run
        except Exception:
            # python-docx couldn't decode the payload (truncated, wrong
            # magic bytes, unsupported format).
            return None
        finally:
            try:
                os.unlink(prepared.path)
            except OSError:
                pass

    def _picture_size(self, prepared: PreparedImage, image: dict, *, inline: bool,
                      max_width: Optional[int]) -> tuple[Emu, Emu]:
        css_w, css_h = prepared.css_width or 1, prepared.css_height or 1
        if "width" in image and "height" in image:
            css_w, css_h = image["width"], image["height"]
        elif "width" in image:
            css_w, css_h = image["width"], image["width"] * css_h / css_w
        elif "height" in image:
            css_w, css_h = image["height"] * css_w / css_h, image["height"]
        per_px = self._page_width / WEB_COLUMN_PX
        width, height = css_w * per_px, css_h * per_px
        limit_w = max_width if max_width is not None else self._available
        limit_h = Pt(48) if inline else self._page_height * FIGURE_MAX_HEIGHT
        scale = min(1.0, limit_w / width, limit_h / height)
        return Emu(int(width * scale)), Emu(int(height * scale))

    def figure(self, images: list[dict], caption: Optional[list[dict]] = None,
               heading: Optional[tuple] = None):
        """Centered image(s) with an optional caption below. Images that
        don't fit side by side wrap onto their own lines.

        The figure sits in a borderless box that can't split, so it never
        breaks from its caption. A ``heading`` right above it goes in the
        box too: LibreOffice ignores keep-with-next when the next block is
        too tall for the rest of the page, which would leave the heading
        alone at the bottom.
        """
        if heading is not None:
            self._spacer(HEADINGS[min(heading[0], 6)][4])
        none = "".join(_no_border(side) for side in ("top", "left", "bottom", "right"))
        with self.box(borders=none, padding=(Pt(2), Pt(0), Pt(2), Pt(0)),
                      cant_split=True, after=Pt(10)):
            if heading is not None:
                level, segments, slug = heading
                self.heading(level, segments, slug=slug)
            return self._figure_content(images, caption)

    def _figure_content(self, images: list[dict], caption: Optional[list[dict]]):
        p = self._new_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        pf = p.paragraph_format
        pf.space_after = Pt(0)
        pf.line_spacing = 1.0
        used = 0
        for seg in images:
            if used:
                p.add_run(" ")
            link_el = self._hyperlink(p, seg["link"]) if seg["link"] else None
            run = self._picture_run(p, seg["image"], inline=False)
            if run is None:
                run = p.add_run(f"[{seg['image'].get('alt') or 'image'}]")
                run.italic = True
                run.font.color.rgb = _hex_to_rgb(self._c_muted)
            else:
                shape_w = int(run._r.xpath(".//wp:extent/@cx")[0])
                if used and used + shape_w > self._available:
                    run._r.addprevious(parse_xml(f'<w:r {nsdecls("w")}><w:br/></w:r>'))
                    used = 0
                used += shape_w
            if link_el is not None:
                link_el.append(run._r)
        if caption:
            cap = self._new_paragraph()
            cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
            cap.paragraph_format.space_before = Pt(6)
            cap.paragraph_format.line_spacing = 1.2
            self._runs(cap, caption, size=SMALL_SIZE, color=self._c_muted)
        return p

    # ── Text blocks ─────────────────────────────────────────────────────

    def title(self, segments, metadata: Optional[str]):
        p = self._new_paragraph("Title")
        self._runs(p, segments, size=TITLE_SIZE, color=self._c_heading, bold=True)
        last = p
        if metadata:
            last = self.metadata_line(metadata)
        last.paragraph_format.space_after = Pt(18)
        _set_paragraph_border(last, "bottom", self._h_border, 6, 10)
        return p

    def metadata_line(self, text: str):
        p = self._new_paragraph()
        p.paragraph_format.space_after = Pt(4)
        parts = [part.strip() for part in text.split("|") if part.strip()]
        self._runs(p, _plain("   ·   ".join(parts)), size=Pt(9.5), color=self._c_muted)
        return p

    def _heading_breaks(self, level: int) -> bool:
        """Whether a heading at ``level`` starts a new page (``page_break_before``).
        Counts the heading, so call it once per heading."""
        if self._page_break_level is None or min(level, 6) > self._page_break_level:
            return False
        self._break_heading_count += 1
        return not (self._skip_first_break and self._break_heading_count == 1)

    def heading(self, level: int, segments, *, slug: Optional[str] = None,
                page_break: Optional[bool] = None):
        """``page_break``: ``None`` decides from ``page_break_before``; a
        caller that already decided (a heading boxed with what follows it)
        passes ``False``."""
        level = min(level, 6)
        p = self._new_paragraph(f"Heading {level}")
        # On the paragraph itself, not just the style: LibreOffice maps
        # Word's heading styles onto its own, which keep lines together,
        # and keep-together cancels keep-with-next at the foot of a page.
        _keep_with_next(p)
        p.paragraph_format.keep_together = False
        size, bold, italic, caps, _, _ = HEADINGS[level]
        self._runs(p, segments, size=size, color=self._heading_color(level),
                   bold=bold, italic=italic)
        if caps:
            for run in p.runs:
                run.font.all_caps = True
                _letter_spacing(run, 12)
        if slug and slug in self.anchors:
            self._bookmark(p, self.anchors[slug])
        if self._heading_breaks(level) if page_break is None else page_break:
            p.paragraph_format.page_break_before = True
        self._after_heading = True
        return p

    def paragraph(self, segments, *, bold=False):
        p = self._new_paragraph()
        if self._tight:
            p.paragraph_format.space_after = Pt(2)
        self._runs(p, segments, bold=bold)
        return p

    def page_break(self):
        # Set on the next block rather than drawn as a break character, so
        # a break that falls at the bottom of a page can't leave a blank one.
        self._pending_break = True

    def hr(self):
        # Touching paragraphs with the same border are drawn as one group
        # with a single rule, so a rule right after a rule gets a
        # borderless sliver between them.
        if self._last_rule is not None and self._last_rule is self._last_p:
            self._spacer(Pt(1))
        p = self._new_paragraph()
        pf = p.paragraph_format
        pf.space_before = Pt(6)
        pf.space_after = Pt(14)
        pf.line_spacing = Pt(6)
        pf.line_spacing_rule = 4
        _set_paragraph_border(p, "bottom", self._h_border, 8, 1)
        self._last_rule = p

    def math_block(self, tex: str):
        omml = latex_to_omml(tex, display=True, font=self._math_font)
        if omml is None:
            self.code_block(tex, "latex")
            return
        p = self._new_paragraph()
        pf = p.paragraph_format
        pf.space_before = Pt(4)
        pf.space_after = Pt(10)
        p._p.append(omml)

    def definition_term(self, segments):
        p = self._new_paragraph()
        p.paragraph_format.space_after = Pt(1)
        _keep_with_next(p)
        self._runs(p, segments, bold=True)

    def footnote(self, number: int, segments, *, first: bool):
        p = self._new_paragraph()
        pf = p.paragraph_format
        pf.space_after = Pt(3)
        pf.line_spacing = 1.2
        pf.left_indent = self._indent + Cm(0.6)
        pf.first_line_indent = Cm(-0.6)
        pf.tab_stops.add_tab_stop(self._indent + Cm(0.6))
        mark = p.add_run(f"{number}\t" if first else "\t")
        mark.font.size = SMALL_SIZE
        mark.font.bold = True
        mark.font.color.rgb = _hex_to_rgb(self._c_heading)
        if first:
            self._bookmark(p, f"__fn_{number}")
        self._runs(p, segments, size=SMALL_SIZE)

    def footnote_rule(self):
        p = self._new_paragraph()
        pf = p.paragraph_format
        pf.space_before = Pt(18)
        pf.space_after = Pt(8)
        pf.line_spacing = Pt(4)
        pf.line_spacing_rule = 4
        pf.right_indent = Emu(int(self._available * 0.7))
        _set_paragraph_border(p, "bottom", self._h_border, 6, 1)

    # ── Boxes ───────────────────────────────────────────────────────────

    @contextmanager
    def box(self, *, borders: str, fill: Optional[str] = None,
            padding=(Pt(6), Pt(8), Pt(6), Pt(8)), cant_split: bool = False,
            text_color: Optional[str] = None, after=PARA_AFTER):
        """A one-cell table whose cell is the frame for nested blocks."""
        self._keep_intro()
        self._take_pending_break()
        width = self._available
        top, right, bottom, left = (_twips(x) for x in padding)
        table = BlockItemContainer.add_table(self._frame.body, 1, 1, Emu(width))
        _table_properties(table, width=width, indent=self._indent, borders=borders,
                          margins=(top, right, bottom, left))
        cell = table.cell(0, 0)
        cell.width = Emu(width)
        if fill:
            _set_cell_shading(cell, fill)
        if cant_split:
            _cant_split(table.rows[0])
        inner = int(width - Pt((left + right) / 20) - Pt(3))
        frame = _Frame(cell, inner, fresh=cell.paragraphs[0])
        saved = (self._indent, self._list_level, self._ordered_depth, self._text_color, self._tight)
        self._frames.append(frame)
        self._indent, self._list_level, self._ordered_depth, self._tight = Emu(0), 0, 0, False
        if text_color:
            self._text_color = text_color
        try:
            yield cell
        finally:
            self._frames.pop()
            self._indent, self._list_level, self._ordered_depth, self._text_color, self._tight = saved
            self._close_cell(cell, frame)
            self._spacer(after)

    def _close_cell(self, cell, frame: _Frame):
        """Trim a box cell: no space above the first block or below the last,
        and a paragraph at the end (Word requires one)."""
        tc = cell._tc
        blocks = [el for el in tc if el.tag in (qn("w:p"), qn("w:tbl"))]
        if frame.fresh is not None and len(blocks) > 1:
            tc.remove(frame.fresh._p)
            blocks.remove(frame.fresh._p)
        if blocks and blocks[-1].tag == qn("w:tbl"):
            BlockItemContainer.add_paragraph(cell)
        paragraphs = cell.paragraphs
        if not paragraphs:
            return
        if paragraphs[0]._p is blocks[0]:
            paragraphs[0].paragraph_format.space_before = Pt(0)
        final = paragraphs[-1]
        final.paragraph_format.space_after = Pt(0)
        previous = final._p.getprevious()
        if previous is not None and previous.tag == qn("w:tbl") and not final.text:
            # Only there because a cell must end in a paragraph.
            final.paragraph_format.line_spacing = Pt(1)
            final.paragraph_format.line_spacing_rule = 4

    def quote(self):
        return self.box(
            borders=_border("left", self._c_heading, 18) + _no_border("top")
            + _no_border("bottom") + _no_border("right"),
            padding=(Pt(1), Pt(0), Pt(1), Pt(12)), text_color=QUOTE_TEXT)

    @contextmanager
    def alert(self, kind: str):
        label, accent, fill = ALERTS.get(kind.upper(), ALERTS["NOTE"])
        with self.box(
            borders=_border("left", accent, 24) + _no_border("top")
            + _no_border("bottom") + _no_border("right"),
            fill=fill, padding=(Pt(7), Pt(11), Pt(8), Pt(11)), cant_split=True,
        ):
            p = self._new_paragraph()
            p.paragraph_format.space_after = Pt(3)
            _keep_with_next(p)
            self._runs(p, _plain(label), size=Pt(10), color=accent, bold=True)
            yield

    def code_block(self, code: str, info: str = ""):
        language = language_of(info)
        lines = code.rstrip("\n").expandtabs(4).split("\n")
        pieces = highlight(code.rstrip("\n").expandtabs(4), language)
        border = self._h_code_border
        with self.box(
            borders="".join(_border(side, border, 4) for side in ("top", "left", "bottom", "right")),
            fill=self._h_code_bg, padding=(Pt(7), Pt(10), Pt(7), Pt(10)),
            cant_split=len(lines) <= 20, text_color=self._c_body,
        ):
            if language and language not in ("text", "plaintext", "txt"):
                label = self._new_paragraph()
                label.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                lf = label.paragraph_format
                lf.space_after = Pt(0)
                lf.line_spacing = Pt(9)
                lf.line_spacing_rule = 4
                run = label.add_run(language)
                run.font.size = Pt(7)
                run.font.name = self.brand.font_main
                run.font.color.rgb = _hex_to_rgb(self._c_muted)
            # One paragraph per line, so diff lines can be washed and long
            # blocks break across pages between lines.
            line_pieces: list[list[tuple[str, Optional[str], bool]]] = [[]]
            for text, color, italic in pieces or [(code.rstrip("\n").expandtabs(4), None, False)]:
                for n, part in enumerate(text.split("\n")):
                    if n:
                        line_pieces.append([])
                    if part:
                        line_pieces[-1].append((part, color, italic))
            diff = language == "diff"
            for parts in line_pieces:
                p = self._new_paragraph()
                pf = p.paragraph_format
                pf.space_after = Pt(0)
                pf.line_spacing = CODE_LINE
                pf.line_spacing_rule = 4
                text = "".join(part for part, _, _ in parts)
                if diff and text[:1] in DIFF_BACKGROUNDS:
                    _shade_paragraph(p, DIFF_BACKGROUNDS[text[:1]])
                for part, color, italic in parts or [("", None, False)]:
                    if not part:
                        continue
                    run = p.add_run(part)
                    run.font.name = self.brand.code_block_font
                    run.font.size = CODE_SIZE
                    run.font.color.rgb = _hex_to_rgb(color or self._c_body)
                    if italic:
                        run.font.italic = True

    # ── Signature blocks ────────────────────────────────────────────────

    def signature_block(self, entries: list[SignatureEntry], heading: Optional[tuple] = None):
        """One signature box per entry, two per row.

        The rows sit in a borderless box that can't split, so the block
        stays on one page. A ``heading`` right above the block goes in the
        box too, as with figures: LibreOffice drops keep-with-next when the
        next block doesn't fit on the page.
        """
        if heading is not None:
            level = min(heading[0], 6)
            # A page break inside a table cell is ignored, so break above the box.
            if self._heading_breaks(level):
                self.page_break()
            else:
                self._spacer(HEADINGS[level][4])
        none = "".join(_no_border(side) for side in ("top", "left", "bottom", "right"))
        with self.box(borders=none, padding=(Pt(2), Pt(0), Pt(2), Pt(0)),
                      cant_split=True, after=Pt(10)):
            if heading is not None:
                level, segments, slug = heading
                self.heading(level, segments, slug=slug, page_break=False)
            self._signature_rows(entries)
        self._after_heading = False

    def _signature_rows(self, entries: list[SignatureEntry]):
        """A borderless table, two boxes across. Each pair of boxes takes
        two table rows, the signature areas with names and then the date
        lines, so the date lines line up even when one box has more lines."""
        width = self._available
        widths = [width // 2, width - width // 2]
        half_gap = _twips(SIGNATURE_GAP) // 2
        inner = int(width // 2 - Pt(half_gap / 20))  # text width of a box
        pairs = [entries[n:n + 2] for n in range(0, len(entries), 2)]
        table = BlockItemContainer.add_table(self._frame.body, 2 * len(pairs), 2, Emu(width))
        _table_properties(
            table, width=width, indent=self._indent,
            borders="".join(_no_border(side) for side in
                            ("top", "left", "bottom", "right", "insideH", "insideV")),
            margins=(0, 0, 0, 0))
        for column, w in zip(table.columns, widths):
            column.width = Emu(w)
        for r, row in enumerate(table.rows):
            _cant_split(row)
            pair = pairs[r // 2]
            last_row = r == len(table.rows) - 1
            for c, cell in enumerate(row.cells):
                cell.width = Emu(widths[c])
                # The gap is split between the two boxes, so their outer
                # edges line up with the text column.
                _set_cell_margins(cell, left=half_gap if c else 0, right=0 if c else half_gap)
                if c >= len(pair):
                    _exact_line(cell.paragraphs[0], Pt(1))  # odd one out: empty
                elif r % 2 == 0:
                    self._signature_box(cell, pair[c], inner)
                else:
                    self._date_line(cell, pair[c].role, inner, last_row=last_row)

    def _signature_box(self, cell, entry: SignatureEntry, width: int):
        """Blank signature area over a line, then the name in bold (the role
        if there's no name), the title and the role.

        The boxes look the same with and without ``signature_fields``: the
        tags' lines are there either way, empty without them.
        """
        role = entry.role

        # Signature area: the tag's line, then blank space down to the line.
        p = cell.paragraphs[0]
        _exact_line(p, TAG_LINE)
        if self._signature_fields:
            self._field_tag(p, signature_tag(role, width=_points(width),
                                             height=_points(SIGNATURE_AREA - TAG_TOP)))
        p = self._add_paragraph(cell)
        _exact_line(p, SIGNATURE_AREA - TAG_LINE)
        _set_paragraph_border(p, "bottom", self._h_border, 8, 0)

        p = self._add_paragraph(cell)
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = 1.2
        self._runs(p, _plain(entry.name or role), size=BODY_SIZE, color=self._c_body, bold=True)
        for text, size, shown in ((entry.title, Pt(9.5), bool(entry.title)),
                                  (role, Pt(8.5), bool(entry.name))):
            if not shown:
                continue
            p = self._add_paragraph(cell)
            p.paragraph_format.space_before = Pt(1)
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 1.2
            self._runs(p, _plain(text), size=size, color=self._c_muted)

    def _date_line(self, cell, role: str, width: int, *, last_row: bool):
        """The label "Date", then a short line: a borderless two-cell table
        whose second cell has a bottom border (LibreOffice draws neither
        the underline nor the leader of a tab at the end of a line). The
        date tag sits just above where the line starts, on a line as wide
        as the box so it never wraps."""
        line = min(int(DATE_LINE), int(width - DATE_LABEL))
        p = cell.paragraphs[0]
        _exact_line(p, TAG_LINE, before=Pt(6))
        p.paragraph_format.left_indent = DATE_LABEL
        if self._signature_fields:
            self._field_tag(p, date_tag(role, width=_points(line),
                                        height=_points(TAG_LINE - TAG_TOP + DATE_LINE_HEIGHT)))
        widths = [int(DATE_LABEL), line]
        table = BlockItemContainer.add_table(cell, 1, 2, Emu(sum(widths)))
        _table_properties(
            table, width=sum(widths), indent=0,
            borders="".join(_no_border(side) for side in
                            ("top", "left", "bottom", "right", "insideH", "insideV")),
            margins=(0, 0, 0, 0))
        row = table.rows[0]
        row.height = DATE_LINE_HEIGHT
        row.height_rule = WD_ROW_HEIGHT_RULE.EXACTLY
        for column, cell_, w in zip(table.columns, row.cells, widths):
            column.width = cell_.width = Emu(w)
        label, blank = row.cells
        label.vertical_alignment = WD_ALIGN_VERTICAL.BOTTOM
        p = label.paragraphs[0]
        _exact_line(p, Pt(11), after=Pt(1.5))
        self._runs(p, _plain("Date"), size=Pt(8.5), color=self._c_muted)
        blank._tc.get_or_add_tcPr().insert_element_before(
            parse_xml(f'<w:tcBorders {nsdecls("w")}>{_border("bottom", self._h_border, 8)}</w:tcBorders>'),
            *_TCPR_AFTER_BORDERS)
        _exact_line(blank.paragraphs[0], Pt(1))
        # A cell ends with a paragraph; this one spaces the rows of boxes.
        _exact_line(self._add_paragraph(cell), Pt(1),
                    after=Pt(0) if last_row else SIGNATURE_ROW_GAP)

    def _field_tag(self, p, tag: str):
        """A DocuSeal text tag: white, tiny, and never spell-checked (Word
        would draw red squiggles under the invisible text)."""
        run = p.add_run(tag)
        f = run.font
        f.name = self.brand.font_main
        f.size = TAG_SIZE
        f.color.rgb = _hex_to_rgb(TAG_COLOR)
        f.no_proof = True

    # ── Lists ───────────────────────────────────────────────────────────

    def _numbering(self, *, ordered: bool, start: int = 1) -> int:
        """A numbering definition: one shared for bullets, a fresh one per
        ordered list (so each restarts at its own ``start``)."""
        if not ordered and self._bullet_num is not None:
            return self._bullet_num
        self._num_counter += 1
        num_id = self._num_counter
        levels = ""
        for lvl in range(9):
            text_left = LIST_TEXT + LIST_STEP * lvl
            if ordered:
                fmt, text = ORDERED_FORMATS[self._ordered_depth % len(ORDERED_FORMATS)]
                text = text.format(n=lvl + 1)
                start_xml = f'<w:start w:val="{start}"/>'
            else:
                fmt, text, start_xml = "bullet", BULLETS[lvl % len(BULLETS)], '<w:start w:val="1"/>'
            levels += (
                f'<w:lvl w:ilvl="{lvl}">{start_xml}<w:numFmt w:val="{fmt}"/>'
                f'<w:lvlText w:val="{text}"/><w:lvlJc w:val="left"/>'
                f'<w:pPr><w:tabs><w:tab w:val="num" w:pos="{_twips(text_left)}"/></w:tabs>'
                f'<w:ind w:left="{_twips(text_left)}" w:hanging="{_twips(LIST_HANG)}"/></w:pPr>'
                f'<w:rPr><w:rFonts w:ascii="{self.brand.font_main}" w:hAnsi="{self.brand.font_main}"/>'
                f'{"<w:b/>" if ordered else ""}'
                f'<w:color w:val="{self._c_heading}"/>'
                f'<w:sz w:val="{int(BODY_SIZE.pt * 2)}"/></w:rPr></w:lvl>'
            )
        numbering = self.doc.part.numbering_part.numbering_definitions._numbering
        abstract = parse_xml(f'<w:abstractNum {nsdecls("w")} w:abstractNumId="{num_id}">'
                             f'<w:multiLevelType w:val="multilevel"/>{levels}</w:abstractNum>')
        first_num = numbering.find(qn("w:num"))
        if first_num is not None:
            first_num.addprevious(abstract)
        else:
            numbering.append(abstract)
        numbering.append(parse_xml(f'<w:num {nsdecls("w")} w:numId="{num_id}">'
                                   f'<w:abstractNumId w:val="{num_id}"/></w:num>'))
        if not ordered:
            self._bullet_num = num_id
        return num_id

    def list_text_indent(self, level: Optional[int] = None) -> Emu:
        level = self._list_level if level is None else level
        return Emu(LIST_TEXT + LIST_STEP * level)

    def list_item(self, segments, *, num_id: int, task: Optional[bool], tight: bool):
        level = self._list_level
        p = self._new_paragraph()
        pf = p.paragraph_format
        pf.space_after = Pt(2) if tight else Pt(5)
        if task is not None:
            indent = self.list_text_indent(level)
            pf.left_indent = indent
            pf.first_line_indent = -LIST_HANG
            pf.tab_stops.add_tab_stop(indent)
            box = p.add_run(("☑" if task else "☐") + "\t")
            box.font.name = "DejaVu Sans"
            box.font.size = BODY_SIZE
            box.font.color.rgb = _hex_to_rgb(self._c_heading if task else self._c_muted)
        else:
            # The numbering definition places the marker and text; a
            # paragraph indent would override it.
            pf.left_indent = None
            num_pr = p._p.get_or_add_pPr().get_or_add_numPr()
            num_pr.get_or_add_ilvl().val = level
            num_pr.get_or_add_numId().val = num_id
        self._runs(p, segments)
        return p

    # ── Tables ──────────────────────────────────────────────────────────

    def table(self, header: list[list[dict]], rows: list[list[list[dict]]],
              alignments: Optional[list[str]] = None):
        if not header and not rows:
            return
        n_cols = max(len(header), *(len(r) for r in rows)) if rows else len(header)
        header = header + [[] for _ in range(n_cols - len(header))] if header else []
        rows = [r + [[] for _ in range(n_cols - len(r))] for r in rows]
        alignments = (alignments or []) + ["left"] * n_cols
        size = Pt(9) if self._landscape else (Pt(8.5) if n_cols >= 7 else Pt(9.5))
        self._keep_intro()
        self._take_pending_break()
        width = self._available
        pad_h, pad_v = Pt(6), Pt(4)
        widths = self._column_widths(header, rows, width, size, pad_h)

        all_rows = ([header] if header else []) + rows
        table = BlockItemContainer.add_table(self._frame.body, len(all_rows), n_cols, Emu(width))
        _table_properties(
            table, width=width, indent=self._indent,
            borders=(_no_border("top") + _no_border("left") + _no_border("right")
                     + _border("bottom", self._h_border, 6)
                     + _border("insideH", self._h_border, 4) + _no_border("insideV")),
            margins=(_twips(pad_v), _twips(pad_h), _twips(pad_v), _twips(pad_h)),
        )
        for col, w in zip(table.columns, widths):
            col.width = Emu(w)
        for r, (row, data) in enumerate(zip(table.rows, all_rows)):
            is_header = bool(header) and r == 0
            _cant_split(row)
            if is_header:
                _repeat_header(row)
            body_index = r - (1 if header else 0)
            for c, (cell, content) in enumerate(zip(row.cells, data)):
                cell.width = Emu(widths[c])
                cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER if is_header else WD_ALIGN_VERTICAL.TOP
                if is_header:
                    _set_cell_shading(cell, self._h_table_hdr_bg)
                elif body_index % 2 == 1:
                    _set_cell_shading(cell, self._h_alt_row)
                p = cell.paragraphs[0]
                pf = p.paragraph_format
                pf.space_before = Pt(0)
                pf.space_after = Pt(0)
                pf.line_spacing = 1.2
                align = alignments[c] if c < len(alignments) else "left"
                if align == "center":
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                elif align == "right":
                    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                self._frames.append(_Frame(cell, int(widths[c] - 2 * pad_h)))
                saved = (self._indent, self._text_color)
                self._indent = Emu(0)
                try:
                    if is_header:
                        self._runs(p, content, size=size, color=self._c_table_hdr_fg, bold=True)
                    else:
                        self._text_color = None
                        self._runs(p, content, size=size)
                finally:
                    self._frames.pop()
                    self._indent, self._text_color = saved
        self._spacer(PARA_AFTER + Pt(3))

    def _column_widths(self, header, rows, width: int, size, pad_h) -> list[int]:
        """Column widths from the content: every column at least as wide as
        its longest word (so words don't break mid-word), the rest of the
        width shared out by how much text each column holds."""
        n_cols = len(header) if header else len(rows[0])
        char_w = size.pt * 0.56  # average glyph width in points
        overhead = 2 * pad_h.pt + 2

        def measure(cell) -> tuple[float, float]:
            text = _segments_text(cell)
            images = [seg["image"] for seg in cell if seg["image"]]
            longest_line = max((len(line) for line in text.split("\n")), default=0)
            longest_word = max((len(word) for word in re.split(r"[\s/]+", text)), default=0)
            image_w = max((img.get("width", 48) for img in images), default=0) * 0.75
            return (max(longest_line * char_w, image_w), max(longest_word * char_w, image_w))

        desired, minimum = [overhead] * n_cols, [overhead] * n_cols
        for row in ([header] if header else []) + rows:
            for c, cell in enumerate(row[:n_cols]):
                line, word = measure(cell)
                desired[c] = max(desired[c], min(line, 60 * char_w) + overhead)
                minimum[c] = max(minimum[c], min(word, 22 * char_w) + overhead)
        total = Emu(width).pt
        if sum(minimum) >= total:
            shares = [m / sum(minimum) * total for m in minimum]
        elif sum(desired) <= total:
            shares = [d / sum(desired) * total for d in desired]
        else:
            extra = total - sum(minimum)
            want = [max(d - m, 0) for d, m in zip(desired, minimum)]
            shares = [m + (extra * w / sum(want) if sum(want) else extra / n_cols)
                      for m, w in zip(minimum, want)]
        widths = [int(Pt(s)) for s in shares]
        widths[-1] += width - sum(widths)
        return widths

    # ── Finalize ────────────────────────────────────────────────────────

    def finalize(self, logo_path: str | None = None) -> Document:
        if logo_path and os.path.exists(logo_path):
            _add_header(self.doc, logo_path)
        _add_footer(self.doc, self.brand)
        return self.doc


# ---------------------------------------------------------------------------
# Header & Footer
# ---------------------------------------------------------------------------

def _add_footer(doc: Document, brand: BrandingConfig):
    """Add the branded footer to every section.

    The footer is skipped entirely when the brand provides no identity
    (no company name, no subtitle, no URL) — useful for Pro-plan users
    who want a plain document with no branding whatsoever.
    """
    has_name = bool(brand.company_name)
    has_subtitle = bool(brand.footer_subtitle)
    has_url = bool(brand.company_url)
    if not (has_name or has_subtitle or has_url):
        return

    footer_bold = _hex_to_rgb(brand.footer_bold_color)
    footer_normal = _hex_to_rgb(brand.footer_normal_color)

    for section in doc.sections:
        footer = section.footer
        footer.is_linked_to_previous = False
        p = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p.paragraph_format.line_spacing = 1.25
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(6)

        if has_name:
            run1 = p.add_run(brand.company_name)
            run1.bold = True
            run1.font.color.rgb = footer_bold
            run1.font.size = Pt(8)
            run1.font.name = brand.font_main
            if has_subtitle or has_url:
                p.add_run().add_break()

        if has_subtitle:
            sep = " – " if has_url else ""
            run2 = p.add_run(f"{brand.footer_subtitle}{sep}")
            run2.font.color.rgb = footer_normal
            run2.font.size = Pt(8)
            run2.font.name = brand.font_main

        if has_url:
            r_id = p.part.relate_to(
                brand.company_url,
                "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
                is_external=True)
            link = parse_xml(f'<w:hyperlink {nsdecls("w")} '
                             f'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
                             f'r:id="{r_id}"/>')
            p._p.append(link)
            run = p.add_run(brand.company_url_label or brand.company_url)
            run.font.color.rgb = footer_normal
            run.font.size = Pt(8)
            run.font.name = brand.font_main
            link.append(run._r)


def _add_header(doc: Document, logo_path: str):
    """Add a logo to the top-right of every page header."""
    for section in doc.sections:
        header = section.header
        header.is_linked_to_previous = False
        p = header.paragraphs[0] if header.paragraphs else header.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        run = p.add_run()
        run.add_picture(logo_path, width=Inches(0.46), height=Inches(0.46))


# ---------------------------------------------------------------------------
# Token walker
# ---------------------------------------------------------------------------

class _Renderer:
    """Walks markdown-it's token stream into a DocxBuilder."""

    def __init__(self, builder: DocxBuilder, tokens, *, title_tokens: set[int],
                 metadata: Optional[str], skip: set[int], front_title: Optional[str]):
        self.b = builder
        self.tokens = tokens
        self.title_tokens = title_tokens
        self.metadata = metadata
        self.skip = skip
        self.front_title = front_title
        self.slugger = Slugger()
        self.title_done = False

    # The title block goes first, before any body content.
    def _ensure_title(self):
        if self.title_done:
            return
        self.title_done = True
        if self.front_title:
            self.b.title(_plain(self.front_title), self.metadata)
        elif self.metadata:
            p = self.b.metadata_line(self.metadata)
            p.paragraph_format.space_after = Pt(14)

    def render(self, i: int = 0, stop: Optional[str] = None) -> int:
        tokens = self.tokens
        while i < len(tokens):
            tok = tokens[i]
            t = tok.type
            if stop is not None and t == stop:
                return i + 1
            if i in self.skip:
                i = self._skip_block(i)
                continue
            handler = getattr(self, f"_{t}", None)
            if handler is None:
                i += 1
                continue
            i = handler(i)
        return i

    def _skip_block(self, i: int) -> int:
        """Skip the block starting at ``i`` (an open token and its contents)."""
        tok = self.tokens[i]
        if tok.nesting != 1:
            return i + 1
        depth = 0
        while i < len(self.tokens):
            depth += self.tokens[i].nesting
            i += 1
            if depth == 0:
                return i
        return i

    def _inline_at(self, i: int) -> list[dict]:
        tok = self.tokens[i]
        return _inline_segments(tok.children) if tok.type == "inline" else []

    # Blocks

    def _front_matter(self, i):
        return i + 1

    def _heading_open(self, i):
        level = int(self.tokens[i].tag[1])
        segments = self._inline_at(i + 1)
        slug = self.slugger.slug(_segments_text(segments).strip())
        if i in self.title_tokens:
            self.title_done = True
            p = self.b.title(segments, self.metadata)
            if slug in self.b.anchors:
                self.b._bookmark(p, self.b.anchors[slug])
        else:
            self._ensure_title()
            figure = self._figure_at(i + 3)
            if figure is not None:
                images, caption, nxt = figure
                self.b.figure(images, caption, heading=(level, segments, slug))
                return nxt
            signers = self._signature_at(i + 3)
            if signers is not None:
                self.b.signature_block(signers, heading=(level, segments, slug))
                return i + 4
            self.b.heading(level, segments, slug=slug)
        return i + 3

    def _signature_at(self, i: int) -> Optional[list[SignatureEntry]]:
        """The entries if the block at ``i`` is a valid ```signature fence."""
        if i >= len(self.tokens):
            return None
        tok = self.tokens[i]
        if tok.type != "fence" or not is_signature_info(tok.info):
            return None
        return parse_signature_block(tok.content)

    def _figure_at(self, i: int):
        """``(images, caption, next index)`` if the block at ``i`` is an
        image-only paragraph, else ``None``."""
        tokens = self.tokens
        if i + 1 >= len(tokens) or tokens[i].type != "paragraph_open":
            return None
        images = _only_images(self._inline_at(i + 1))
        if not images:
            return None
        nxt = i + 3
        caption = None
        title = images[0]["image"].get("title") if len(images) == 1 else None
        if title:
            caption = _plain(title)
        elif self._is_caption(nxt):
            caption = self._inline_at(nxt + 1)
            nxt += 3
        return images, caption, nxt

    def _paragraph_open(self, i):
        self._ensure_title()
        segments = self._inline_at(i + 1)
        text = _segments_text(segments).strip()
        nxt = i + 3
        if text in PAGE_BREAK_TEXT:
            self.b.page_break()
            return nxt
        formula = _FORMULA.match(text)
        if formula and not any(seg["image"] or seg["math"] for seg in segments):
            self.b.math_block(formula.group(1))
            return nxt
        maths = [seg for seg in segments if seg["math"] is not None]
        if len(maths) == 1 and maths[0].get("display") and not text:
            self.b.math_block(maths[0]["math"])
            return nxt
        figure = self._figure_at(i)
        if figure is not None:
            images, caption, nxt = figure
            self.b.figure(images, caption)
            return nxt
        self.b.paragraph(segments)
        return nxt

    def _is_caption(self, i: int) -> bool:
        """An italic-only paragraph right under an image is its caption."""
        tokens = self.tokens
        if i + 2 >= len(tokens) or tokens[i].type != "paragraph_open" or tokens[i].level != tokens[i - 1].level:
            return False
        children = tokens[i + 1].children or []
        return (len(children) >= 3 and children[0].type == "em_open"
                and children[-1].type == "em_close"
                and not any(c.type in ("em_open", "em_close") for c in children[1:-1]))

    def _blockquote_open(self, i):
        self._ensure_title()
        with self.b.quote():
            return self.render(i + 1, "blockquote_close")

    def _alert_open(self, i):
        self._ensure_title()
        kind = (self.tokens[i].meta or {}).get("kind", "NOTE")
        j = i + 1
        if self.tokens[j].type == "alert_title_open":
            j += 3
        with self.b.alert(kind):
            return self.render(j, "alert_close")

    def _fence(self, i):
        self._ensure_title()
        tok = self.tokens[i]
        signers = self._signature_at(i)
        if signers is not None:
            self.b.signature_block(signers)
        elif language_of(tok.info) == "math":
            self.b.math_block(tok.content)
        else:
            # Includes ```signature blocks that aren't valid.
            self.b.code_block(tok.content, tok.info)
        return i + 1

    def _code_block(self, i):
        self._ensure_title()
        self.b.code_block(self.tokens[i].content)
        return i + 1

    def _math_block(self, i):
        self._ensure_title()
        self.b.math_block(self.tokens[i].content)
        return i + 1

    _math_block_label = _math_block

    def _hr(self, i):
        self._ensure_title()
        self.b.hr()
        return i + 1

    def _bullet_list_open(self, i):
        return self._list(i, ordered=False)

    def _ordered_list_open(self, i):
        return self._list(i, ordered=True)

    def _list(self, i, *, ordered: bool) -> int:
        self._ensure_title()
        b = self.b
        open_tok = self.tokens[i]
        try:
            start = int(open_tok.attrGet("start") or 1)
        except (TypeError, ValueError):
            start = 1
        num_id = b._numbering(ordered=ordered, start=start)
        b._keep_intro()
        close = "ordered_list_close" if ordered else "bullet_list_close"
        tight = self._is_tight(i)
        level = b._list_level
        saved = (b._indent, b._tight, b._ordered_depth)
        i += 1
        while i < len(self.tokens) and self.tokens[i].type != close:
            tok = self.tokens[i]
            if tok.type != "list_item_open":
                i += 1
                continue
            task = (tok.meta or {}).get("checked") if "task-list-item" in (tok.attrGet("class") or "") else None
            i += 1
            # The item's first paragraph carries the bullet or number; its
            # other blocks are indented under the text.
            if self.tokens[i].type == "paragraph_open":
                b.list_item(self._inline_at(i + 1), num_id=num_id, task=task, tight=tight)
                i += 3
            else:
                b.list_item([], num_id=num_id, task=task, tight=tight)
            b._indent = b.list_text_indent(level)
            b._tight = tight
            b._list_level = level + 1
            if ordered:
                b._ordered_depth = saved[2] + 1
            i = self.render(i, "list_item_close")
            b._list_level = level
            b._indent, b._tight, b._ordered_depth = saved
        if level == 0 and b._last_p is not None:
            b._last_p.paragraph_format.space_after = PARA_AFTER
        return i + 1

    def _is_tight(self, i: int) -> bool:
        """markdown-it hides the paragraphs of tight lists."""
        level = self.tokens[i].level
        j = i + 1
        while j < len(self.tokens):
            tok = self.tokens[j]
            if tok.level == level and tok.nesting == -1:
                break
            if tok.type == "paragraph_open" and tok.level == level + 2:
                return tok.hidden
            j += 1
        return True

    def _table_open(self, i):
        self._ensure_title()
        tokens = self.tokens
        header: list = []
        rows: list = []
        alignments: list[str] = []
        current: list = []
        in_head = False
        i += 1
        while i < len(tokens) and tokens[i].type != "table_close":
            tok = tokens[i]
            if tok.type == "thead_open":
                in_head = True
            elif tok.type == "thead_close":
                in_head = False
            elif tok.type == "tr_open":
                current = []
            elif tok.type == "tr_close":
                if in_head:
                    header = current
                else:
                    rows.append(current)
            elif tok.type in ("th_open", "td_open"):
                if tok.type == "th_open":
                    m = re.search(r"text-align:\s*(left|center|right)", tok.attrGet("style") or "")
                    alignments.append(m.group(1) if m else "left")
                current.append(self._inline_at(i + 1))
                i += 3
                continue
            i += 1
        self.b.table(header, rows, alignments)
        return i + 1

    def _dl_open(self, i):
        self._ensure_title()
        return self.render(i + 1, "dl_close")

    def _dt_open(self, i):
        self.b.definition_term(self._inline_at(i + 1))
        return i + 3

    def _dd_open(self, i):
        saved = self.b._indent
        self.b._indent = Emu(saved + Cm(0.7))
        try:
            return self.render(i + 1, "dd_close")
        finally:
            self.b._indent = saved

    def _html_block(self, i):
        html = self.tokens[i].content
        b = self.b
        if _PAGE_BREAK_HTML.search(html):
            self._ensure_title()
            b.page_break()
            html = _PAGE_BREAK_HTML.sub("", html)
        html = re.sub(r"<!--.*?-->", "", html, flags=re.S).strip()
        if not html:
            return i + 1
        self._ensure_title()

        # <div align="center"> ... </div> around Markdown content
        opening = re.fullmatch(r"<(div|p|center|section)\b([^>]*)>", html, re.I)
        if opening:
            attrs = opening.group(2)
            css = re.search(r"text-align\s*:\s*(left|center|right)", attrs, re.I)
            align = _html_attr(f"<x {attrs}>", "align").lower() or (css.group(1).lower() if css else "")
            if opening.group(1).lower() == "center":
                align = "center"
            b._align = {"center": WD_ALIGN_PARAGRAPH.CENTER, "right": WD_ALIGN_PARAGRAPH.RIGHT}.get(align)
            return i + 1
        if re.fullmatch(r"</(div|p|center|section)>", html, re.I):
            b._align = None
            return i + 1

        if re.search(r"<table\b", html, re.I):
            parser = _HtmlTables()
            parser.feed(html)
            parser.close()
            for rows in parser.tables:
                header = rows[0][1] if rows and rows[0][0] else []
                body = [cells for is_header, cells in (rows[1:] if header else rows)]
                b.table(header, body)
            html = re.sub(r"<table\b.*?</table>", "", html, flags=re.I | re.S).strip()

        parser = _HtmlSegments()
        parser.feed(html)
        parser.close()
        if len(parser.paragraphs) == 1 and _only_images(parser.paragraphs[0][1]) and self._is_caption(i + 1):
            b.figure(_only_images(parser.paragraphs[0][1]), self._inline_at(i + 2))
            return i + 4
        for tag, segments in parser.paragraphs:
            images = _only_images(segments)
            if images:
                b.figure(images)
            elif tag == "summary":
                p = b.paragraph([dict(_SEGMENT_DEFAULTS, text="▸ ", bold=True)] + segments, bold=True)
                _keep_with_next(p)
            elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
                b.heading(int(tag[1]), segments)
            else:
                b.paragraph(segments)
        return i + 1

    def _footnote_block_open(self, i):
        self._ensure_title()
        self.b.footnote_rule()
        tokens = self.tokens
        i += 1
        number = 0
        while i < len(tokens) and tokens[i].type != "footnote_block_close":
            tok = tokens[i]
            if tok.type == "footnote_open":
                number = tok.meta["id"] + 1
                first = True
                i += 1
                while i < len(tokens) and tokens[i].type != "footnote_close":
                    if tokens[i].type == "paragraph_open":
                        self.b.footnote(number, self._inline_at(i + 1), first=first)
                        first = False
                        i += 3
                    else:
                        saved = self.b._indent
                        self.b._indent = Emu(saved + Cm(0.6))
                        i = self._render_one(i)
                        self.b._indent = saved
                i += 1
                continue
            i += 1
        return i + 1

    def _render_one(self, i: int) -> int:
        handler = getattr(self, f"_{self.tokens[i].type}", None)
        return handler(i) if handler else i + 1


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _image_urls(tokens) -> list[str]:
    """Every image source in the document, in order (Markdown images and
    ``<img>`` tags), so they can be downloaded in parallel up front."""
    urls: list[str] = []
    for tok in tokens:
        if tok.type == "html_block":
            urls.extend(_html_attr(tag, "src") for tag in re.findall(r"<img\b[^>]*>", tok.content, re.I))
        for child in tok.children or []:
            if child.type == "image":
                urls.append(child.attrGet("src") or "")
            elif child.type == "html_inline" and re.match(r"<\s*img\b", child.content, re.I):
                urls.append(_html_attr(child.content, "src"))
    return urls


def _front_matter_title(tokens) -> Optional[str]:
    for tok in tokens:
        if tok.type == "front_matter":
            m = re.search(r"^title\s*:\s*(.+?)\s*$", tok.content, re.M)
            if m:
                return m.group(1).strip().strip("'\"") or None
        break
    return None


def _scan(tokens):
    """Find the title heading, the metadata line and heading anchors.

    Returns ``(title_tokens, metadata, skip, slugs)``. The title is the
    first H1 before any body content. The metadata line (``Key: value |
    Key: value``, or ``**Key:** value`` lines) may sit just above or just
    below the title; it's drawn under the title either way.
    """
    title_tokens: set[int] = set()
    skip: set[int] = set()
    metadata: Optional[str] = None
    bold_meta: list[str] = []
    slugs: list[str] = []
    slugger = Slugger()
    seen_body = False
    after_title = False
    for i, tok in enumerate(tokens):
        if tok.type == "heading_open":
            text = _segments_text(_inline_segments(tokens[i + 1].children)).strip()
            slugs.append(slugger.slug(text))
            if tok.tag == "h1" and not seen_body and not title_tokens:
                title_tokens.add(i)
                after_title = True
                continue
            seen_body = True
            after_title = False
        elif tok.level == 0 and tok.nesting != -1 and tok.type not in ("front_matter", "inline"):
            children = (tokens[i + 1].children or []) if tok.type == "paragraph_open" else []
            text = _segments_text(_inline_segments(children)).strip()
            if children and metadata is None and (not seen_body or after_title) \
                    and _detect_metadata_line(text):
                metadata = text
                skip.add(i)
            elif children and not seen_body and not title_tokens \
                    and children[0].type == "strong_open" and re.match(r"^[^:\n]{1,40}:\s", text):
                # **Author:** Jane, above the title
                bold_meta.append(text)
                skip.add(i)
            elif tok.type != "html_block" or re.sub(r"<!--.*?-->", "", tok.content, flags=re.S).strip():
                seen_body = True
            after_title = False
    if metadata is None and bold_meta:
        metadata = " | ".join(bold_meta)
    return title_tokens, metadata, skip, slugs


def convert_md_to_docx(
    md_text: str,
    *,
    brand: BrandingConfig | None = None,
    landscape: bool = False,
    page_break_before: int | None = None,
    skip_first_break: bool = True,
    signature_fields: bool = False,
) -> bytes:
    """Convert markdown text to a styled .docx and return the bytes.

    Parameters
    ----------
    md_text : str
        Raw markdown content.
    brand : BrandingConfig | None
        Branding overrides. Uses OpenDocs defaults when None.
    landscape : bool
        Render in landscape orientation.
    page_break_before : int | None
        Insert a page break before headings at this level or above.
        E.g. ``2`` means every H2 (and H1) starts on a new page.
        ``None`` (default) disables page breaks.
    skip_first_break : bool
        When True (default), the very first heading that would trigger
        a page break is skipped — avoids a blank page at the start
        of the document.
    signature_fields : bool
        Put invisible DocuSeal field tags (signature and signing date) in
        each ```signature box, for documents sent for e-signature.
    """
    if brand is None:
        brand = OPENDOCS_BRAND

    builder = DocxBuilder(
        brand,
        landscape=landscape,
        page_break_before=page_break_before,
        skip_first_break=skip_first_break,
        signature_fields=signature_fields,
    )
    tokens = make_parser().parse(preprocess(md_text))
    # Download the logo and every image at once rather than one by one as
    # the document is built.
    with ThreadPoolExecutor(max_workers=1) as pool:
        logo = pool.submit(resolve_logo, brand)
        builder.prefetched = prefetch_images(_image_urls(tokens))
        logo_path, logo_is_temp = logo.result()
    title_tokens, metadata, skip, slugs = _scan(tokens)
    for n, slug in enumerate(slugs):
        builder.anchors.setdefault(slug, f"_od_h{n + 1}")

    renderer = _Renderer(builder, tokens, title_tokens=title_tokens, metadata=metadata,
                         skip=skip, front_title=None if title_tokens else _front_matter_title(tokens))
    renderer.render()
    renderer._ensure_title()

    doc = builder.finalize(logo_path=logo_path)

    # Clean up temp logo if downloaded (never unlink the bundled asset)
    if logo_is_temp and logo_path and os.path.exists(logo_path):
        try:
            os.unlink(logo_path)
        except OSError:
            pass

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
