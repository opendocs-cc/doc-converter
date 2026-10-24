"""
OpenDocs Markdown-to-DOCX Converter

Converts Markdown (.md) into professionally styled Word (.docx) documents
with configurable branding.  Based on the battle-tested DORA converter with
formula rendering ported from MiCA.
"""

from __future__ import annotations

import base64
import binascii
import html as html_lib
import io
import ipaddress
import os
import re
import socket
import tempfile
from typing import Callable, Optional
from urllib.parse import urljoin, urlparse

import httpx
from docx import Document
from docx.image.image import Image as DocxImage
from docx.shared import Pt, Cm, Inches, RGBColor, Emu
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.enum.section import WD_ORIENT
from docx.oxml.ns import qn, nsdecls
from docx.oxml import parse_xml
from lxml import etree
from markdown_it import MarkdownIt
from mdit_py_plugins.footnote import footnote_plugin

from .branding import BrandingConfig, OPENDOCS_BRAND

# ---------------------------------------------------------------------------
# RGBColor helpers
# ---------------------------------------------------------------------------

def _hex_to_rgb(hex_color: str) -> RGBColor:
    """Convert '#RRGGBB' or 'RRGGBB' to python-docx RGBColor."""
    h = hex_color.lstrip("#")
    return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _hex_strip(hex_color: str) -> str:
    """Return bare 6-char uppercase hex (no '#')."""
    return hex_color.lstrip("#").upper()


def _xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# Monkey-patch RGBColor to have .hex() for convenience in hyperlink building
if not hasattr(RGBColor, "hex"):
    RGBColor.hex = lambda self: f"{self[0]:02X}{self[1]:02X}{self[2]:02X}"


# ---------------------------------------------------------------------------
# Inline markdown parsing helpers
# ---------------------------------------------------------------------------

def _parse_inline_segments(text: str):
    """Parse inline markdown (bold, italic, bold-italic, code, links,
    underline) into a list of segment dicts."""
    segments: list[dict] = []
    pattern = re.compile(
        r"(\*\*\*(.+?)\*\*\*)"          # bold-italic
        r"|(\*\*(.+?)\*\*)"             # bold
        r"|(\*(.+?)\*)"                 # italic
        r"|(_(.+?)_)"                   # italic (underscore)
        r"|(`(.+?)`)"                   # inline code
        r"|(\[([^\]]+)\]\(([^)]+)\))"   # link
        r"|(<u>(.+?)</u>)"              # underline
    )
    last = 0
    for m in pattern.finditer(text):
        start = m.start()
        if start > last:
            segments.append({"text": text[last:start], "bold": False, "italic": False,
                             "underline": False, "code": False, "link": None})
        if m.group(2) is not None:
            segments.append({"text": m.group(2), "bold": True, "italic": True,
                             "underline": False, "code": False, "link": None})
        elif m.group(4) is not None:
            segments.append({"text": m.group(4), "bold": True, "italic": False,
                             "underline": False, "code": False, "link": None})
        elif m.group(6) is not None:
            segments.append({"text": m.group(6), "bold": False, "italic": True,
                             "underline": False, "code": False, "link": None})
        elif m.group(8) is not None:
            segments.append({"text": m.group(8), "bold": False, "italic": True,
                             "underline": False, "code": False, "link": None})
        elif m.group(10) is not None:
            segments.append({"text": m.group(10), "bold": False, "italic": False,
                             "underline": False, "code": True, "link": None})
        elif m.group(11) is not None:
            segments.append({"text": m.group(12), "bold": False, "italic": False,
                             "underline": False, "code": False, "link": m.group(13)})
        elif m.group(15) is not None:
            segments.append({"text": m.group(15), "bold": False, "italic": False,
                             "underline": True, "code": False, "link": None})
        last = m.end()
    if last < len(text):
        segments.append({"text": text[last:], "bold": False, "italic": False,
                         "underline": False, "code": False, "link": None})
    return [dict(_SEGMENT_DEFAULTS, **seg) for seg in segments]


_SEGMENT_DEFAULTS = {
    "text": "", "bold": False, "italic": False, "underline": False,
    "strike": False, "code": False, "sup": False, "sub": False,
    "link": None, "image": None,
}

# Inline HTML tags that map to run formatting. Other tags are dropped and
# their text kept.
_HTML_INLINE_STYLES = {
    "b": "bold", "strong": "bold", "i": "italic", "em": "italic",
    "u": "underline", "ins": "underline",
    "s": "strike", "del": "strike", "strike": "strike",
    "sub": "sub", "sup": "sup", "code": "code", "kbd": "code", "samp": "code",
}


def _html_attr(tag: str, name: str) -> str:
    m = re.search(rf"""\b{name}\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", tag, re.I)
    if not m:
        return ""
    return html_lib.unescape(next(g for g in m.groups() if g is not None))


def _inline_segments(tokens) -> list[dict]:
    """Styled text segments from markdown-it inline tokens.

    Working from the parser's tokens (rather than re-serialised Markdown)
    keeps escaped characters literal: ``\\*not italic\\*`` stays as text.
    Images become ``image`` segments for the caller to embed.
    """
    segments: list[dict] = []
    depth = {"bold": 0, "italic": 0, "underline": 0, "strike": 0,
             "code": 0, "sup": 0, "sub": 0}
    link: Optional[str] = None

    def add(text: str = "", **extra):
        if not text and not extra.get("image"):
            return
        seg = dict(_SEGMENT_DEFAULTS, text=text, link=link)
        seg.update({k: v > 0 for k, v in depth.items()})
        seg.update(extra)
        segments.append(seg)

    def toggle(key: str, opening: bool):
        depth[key] = max(0, depth[key] + (1 if opening else -1))

    for tok in tokens or []:
        t = tok.type
        if t == "text":
            add(tok.content)
        elif t == "code_inline":
            add(tok.content, code=True)
        elif t == "softbreak":
            add(" ")
        elif t == "hardbreak":
            add("\n")
        elif t in ("strong_open", "strong_close"):
            toggle("bold", t == "strong_open")
        elif t in ("em_open", "em_close"):
            toggle("italic", t == "em_open")
        elif t in ("s_open", "s_close"):
            toggle("strike", t == "s_open")
        elif t == "link_open":
            link = tok.attrGet("href") or None
        elif t == "link_close":
            link = None
        elif t == "image":
            src, alt = _image_src_from_token(tok)
            add(image=(src, alt))
        elif t == "footnote_ref":
            add(str(tok.meta["id"] + 1), sup=True)
        elif t == "html_inline":
            m = re.match(r"<\s*(/?)\s*([a-zA-Z][a-zA-Z0-9]*)", tok.content)
            if not m:
                continue  # comments, processing instructions
            closing, name = m.group(1) == "/", m.group(2).lower()
            if name == "br":
                add("\n")
            elif name == "img" and not closing:
                add(image=(_html_attr(tok.content, "src"), _html_attr(tok.content, "alt")))
            elif name in _HTML_INLINE_STYLES and not tok.content.rstrip().endswith("/>"):
                toggle(_HTML_INLINE_STYLES[name], not closing)
        elif tok.children:
            segments.extend(_inline_segments(tok.children))
        elif tok.content:
            add(tok.content)
    return segments


def _segments_text(segments: list[dict]) -> str:
    return "".join(seg["text"] for seg in segments)


def _shade_run(run, fill_hex: str):
    run._r.get_or_add_rPr().insert_element_before(
        parse_xml(f'<w:shd {nsdecls("w")} w:val="clear" w:color="auto" w:fill="{fill_hex}"/>'),
        "w:fitText", "w:vertAlign", "w:rtl", "w:cs", "w:em", "w:lang",
        "w:eastAsianLayout", "w:specVanish", "w:oMath",
    )


# Elements that follow w:pBdr inside w:pPr (Word rejects out-of-order ones).
_PPR_AFTER_PBDR = (
    "w:shd", "w:tabs", "w:suppressAutoHyphens", "w:kinsoku", "w:wordWrap",
    "w:overflowPunct", "w:topLinePunct", "w:autoSpaceDE", "w:autoSpaceDN",
    "w:bidi", "w:adjustRightInd", "w:snapToGrid", "w:spacing", "w:ind",
    "w:contextualSpacing", "w:mirrorIndents", "w:suppressOverlap", "w:jc",
    "w:textDirection", "w:textAlignment", "w:textboxTightWrap",
    "w:outlineLvl", "w:divId", "w:cnfStyle", "w:rPr", "w:sectPr", "w:pPrChange",
)


# Elements that follow w:keepNext inside w:pPr.
_PPR_AFTER_KEEP_NEXT = (
    "w:keepLines", "w:pageBreakBefore", "w:framePr", "w:widowControl",
    "w:numPr", "w:suppressLineNumbers", "w:pBdr",
) + _PPR_AFTER_PBDR


def _set_paragraph_borders(p, sides: dict[str, str]):
    """Give ``p`` borders, e.g. ``{"left": 'w:val="single" w:sz="18" ...'}``,
    merged with any it already has."""
    p_pr = p._p.get_or_add_pPr()
    pbdr = p_pr.find(qn("w:pBdr"))
    if pbdr is None:
        pbdr = p_pr.insert_element_before(parse_xml(f'<w:pBdr {nsdecls("w")}/>'), *_PPR_AFTER_PBDR)
    existing = {etree.QName(el).localname: el for el in pbdr}
    for el in list(pbdr):
        pbdr.remove(el)
    for side in ("top", "left", "bottom", "right", "between", "bar"):
        if side in sides:
            pbdr.append(parse_xml(f'<w:{side} {nsdecls("w")} {sides[side]}/>'))
        elif side in existing:
            pbdr.append(existing[side])


def _shade_paragraph(p, fill_hex: str):
    p._p.get_or_add_pPr().insert_element_before(
        parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}" w:val="clear"/>'),
        *_PPR_AFTER_PBDR[1:],
    )


def _add_inline_runs(paragraph, content, *,
                     base_bold=False, base_italic=False,
                     base_color: RGBColor, base_font: str, base_size,
                     code_font: Optional[str] = None, code_bg: Optional[str] = None,
                     add_image: Optional[Callable] = None):
    """Add runs to a paragraph.

    ``content`` is a list of segments from ``_inline_segments`` or, for text
    that didn't come from the parser, a Markdown-ish string. Inline code
    uses ``code_font`` on a ``code_bg`` wash; image segments are passed to
    ``add_image(paragraph, src, alt)`` or shown as ``[alt]``.
    """
    if isinstance(content, str):
        content = _parse_inline_segments(re.sub(r"<br\s*/?>", "\n", content))
    for seg in content:
        if seg.get("image"):
            src, alt = seg["image"]
            if add_image is None or not add_image(paragraph, src, alt):
                run = paragraph.add_run(f"[{alt or 'image'}]")
                run.font.name = base_font
                run.font.size = base_size
                run.font.color.rgb = base_color
            continue
        if seg["link"] and not seg["code"]:
            _add_hyperlink(paragraph, seg["link"], seg["text"],
                           base_color=base_color, underline=True,
                           font_name=base_font, font_size=base_size)
            continue
        parts = seg["text"].split("\n")
        for pi, part in enumerate(parts):
            if pi > 0:
                paragraph.add_run().add_break()
            if not part:
                continue
            run = paragraph.add_run(part)
            run.font.color.rgb = base_color
            run.bold = base_bold or seg["bold"]
            run.italic = base_italic or seg["italic"]
            if seg["code"]:
                run.font.name = code_font or base_font
                run.font.size = Pt(max(base_size.pt - 1.5, 6))
                if code_bg:
                    _shade_run(run, code_bg)
            else:
                run.font.name = base_font
                run.font.size = base_size
            if seg["underline"]:
                run.underline = True
            if seg["strike"]:
                run.font.strike = True
            if seg["sup"]:
                run.font.superscript = True
            elif seg["sub"]:
                run.font.subscript = True


def _add_hyperlink(paragraph, url: str, text: str, *,
                   base_color: RGBColor, underline=True,
                   font_name: str, font_size=Pt(11)):
    """Add a clickable hyperlink to a paragraph."""
    part = paragraph.part
    r_id = part.relate_to(
        url,
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
        is_external=True,
    )
    hyperlink = parse_xml(
        f'<w:hyperlink {nsdecls("w")} r:id="{r_id}" '
        f'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/>'
    )
    underline_xml = '<w:u w:val="single"/>' if underline else ""
    sz_val = str(int(font_size.pt * 2))
    color_val = base_color.hex()
    escaped_text = _xml_escape(text)
    run_elem = parse_xml(
        f'<w:r {nsdecls("w")}>'
        f"<w:rPr>"
        f'<w:rFonts w:ascii="{font_name}" w:hAnsi="{font_name}"/>'
        f'<w:color w:val="{color_val}" />'
        f'<w:sz w:val="{sz_val}"/>'
        f"{underline_xml}"
        f"</w:rPr>"
        f'<w:t xml:space="preserve">{escaped_text}</w:t>'
        f"</w:r>"
    )
    hyperlink.append(run_elem)
    paragraph._p.append(hyperlink)


# ---------------------------------------------------------------------------
# Table helpers
# ---------------------------------------------------------------------------

# Elements that follow w:tcBorders / w:shd / w:tcMar inside w:tcPr.
_TCPR_AFTER_BORDERS = ("w:shd", "w:noWrap", "w:tcMar", "w:textDirection",
                       "w:tcFitText", "w:vAlign", "w:hideMark")


def _set_cell_shading(cell, color_hex: str):
    shading = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{color_hex}" w:val="clear"/>')
    cell._tc.get_or_add_tcPr().insert_element_before(shading, *_TCPR_AFTER_BORDERS[1:])


def _set_cell_borders(cell, color_hex: str = "E5E5E5", size: str = "4"):
    tc_pr = cell._tc.get_or_add_tcPr()
    borders = parse_xml(
        f'<w:tcBorders {nsdecls("w")}>'
        f'<w:top w:val="single" w:sz="{size}" w:space="0" w:color="{color_hex}"/>'
        f'<w:left w:val="single" w:sz="{size}" w:space="0" w:color="{color_hex}"/>'
        f'<w:bottom w:val="single" w:sz="{size}" w:space="0" w:color="{color_hex}"/>'
        f'<w:right w:val="single" w:sz="{size}" w:space="0" w:color="{color_hex}"/>'
        f"</w:tcBorders>"
    )
    tc_pr.insert_element_before(borders, *_TCPR_AFTER_BORDERS)


def _set_cell_padding(cell, v_padding_inches=0.07, h_padding_inches=0.08):
    """Set cell margins (tcMar).  Note: the paragraph inside the cell still
    inherits Normal's ``space_before``/``space_after``, which is the bigger
    lever for vertical whitespace.  Use ``_set_cell_paragraph_tight()`` on
    the contained paragraph to keep rows compact.

    The v_padding default of 0.07 in (~5 pt per side) keeps rows about one
    and a half lines tall: readable without the double-height rows a
    report table doesn't need.  Horizontal padding stays at 0.08 in so
    cells don't end up visually stretched."""
    tc_pr = cell._tc.get_or_add_tcPr()
    v_val = str(int(v_padding_inches * 1440))
    h_val = str(int(h_padding_inches * 1440))
    margins = parse_xml(
        f'<w:tcMar {nsdecls("w")}>'
        f'<w:top w:w="{v_val}" w:type="dxa"/>'
        f'<w:left w:w="{h_val}" w:type="dxa"/>'
        f'<w:bottom w:w="{v_val}" w:type="dxa"/>'
        f'<w:right w:w="{h_val}" w:type="dxa"/>'
        f"</w:tcMar>"
    )
    tc_pr.insert_element_before(margins, *_TCPR_AFTER_BORDERS[3:])


def _set_cell_paragraph_tight(p):
    """Zero out paragraph spacing inside a table cell.

    Without this, cell paragraphs inherit Normal's ~12pt space before/after
    which visually inflates every row.  Tables want compact rows, not
    body-paragraph whitespace."""
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.15


def _set_table_repeat_header(row):
    """Make a table row repeat on every page."""
    tr_pr = row._tr.get_or_add_trPr()
    tr_pr.append(parse_xml(f'<w:tblHeader {nsdecls("w")}/>'))


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

        needs_break = False

        # Line 1: company name (bold)
        if has_name:
            run1 = p.add_run(brand.company_name)
            run1.bold = True
            run1.font.color.rgb = footer_bold
            run1.font.size = Pt(8)
            run1.font.name = brand.font_main
            needs_break = True

        # Line 2: subtitle + URL — only break if line 1 was rendered
        if (has_subtitle or has_url) and needs_break:
            run_br = p.add_run()
            run_br.add_break()

        if has_subtitle:
            sep = " \u2013 " if has_url else ""
            run2 = p.add_run(f"{brand.footer_subtitle}{sep}")
            run2.font.color.rgb = footer_normal
            run2.font.size = Pt(8)
            run2.font.name = brand.font_main

        if has_url:
            _add_hyperlink(
                p, brand.company_url, brand.company_url_label or brand.company_url,
                base_color=footer_normal, underline=False,
                font_name=brand.font_main, font_size=Pt(8),
            )


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
# Inline image download
# ---------------------------------------------------------------------------
#
# Inline body images (Markdown `![alt](url)`) are downloaded at conversion
# time and embedded into the DOCX via python-docx's `add_picture`. Downloads
# are hard-capped on size, time, and format so a single bad URL can never
# take a worker down. Any failure falls back to a plain-text `[alt]`
# placeholder so exports always complete.
#
# The API server now rehosts remote images to R2 at publish time
# (`packages/shared/src/posts/image-rehost.ts`), so in the happy path the
# URLs we see here point at `assets.opendocs.cc`. Legacy documents published
# before that change — and any rehost that skipped a URL (oversize,
# unsupported type, SSRF guard) — will still fetch the upstream origin.

_INLINE_IMAGE_TIMEOUT = 15.0
_INLINE_IMAGE_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_REMOTE_FETCH_MAX_REDIRECTS = 3
_REMOTE_LOGO_MAX_BYTES = 5 * 1024 * 1024
_BLOCKED_HOSTS = {
    "localhost",
    "ip6-localhost",
    "ip6-loopback",
    "0.0.0.0",
    "broadcasthost",
    "metadata.google.internal",
    "metadata",
}


def _is_private_ip(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return True
    return not ip.is_global


def _is_blocked_host(host: str) -> bool:
    lower = host.lower().strip("[]")
    return (
        lower in _BLOCKED_HOSTS
        or lower.endswith(".local")
        or lower.endswith(".internal")
        or lower.endswith(".localhost")
    )


def _is_safe_remote_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    host = parsed.hostname
    if _is_blocked_host(host):
        return False
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError:
        return False
    addresses = {info[4][0] for info in infos}
    return bool(addresses) and all(not _is_private_ip(addr) for addr in addresses)


def _image_src_from_token(tok) -> tuple[str, str]:
    """Return ``(src, alt)`` from a markdown-it ``image`` token.

    ``alt`` comes from the token's surface content (which markdown-it fills
    from the bracketed portion of ``![...](...)``). ``src`` is read out of
    the attrs mapping.
    """
    src = ""
    for attr_name, attr_val in (tok.attrs or {}).items():
        if attr_name == "src":
            src = attr_val or ""
            break
    alt = tok.content or ""
    return src, alt


def _paragraph_images(segments: list[dict]) -> list[tuple[str, str]]:
    """The images of an image-only paragraph (``![a](x)`` or several images,
    possibly wrapped in links), else ``[]``. Those are drawn centered at
    their own size; images mixed with text are embedded inline."""
    images = [seg["image"] for seg in segments if seg["image"]]
    if not images:
        return []
    if any(not seg["image"] and seg["text"].strip() for seg in segments):
        return []
    return images


def _download_inline_image(url: str) -> Optional[str]:
    """Download ``url`` to a temp file. Returns the path or ``None`` on
    any failure (network error, non-2xx, size cap, unsupported type).

    The caller owns the returned path and must ``os.unlink`` it after
    ``add_picture`` has read the bytes. ``add_picture`` reads eagerly, so
    the file can be removed before ``doc.save``.
    """
    try:
        headers = {
            # Some CDNs (Wikimedia in particular) reject the default httpx
            # UA with a 403. Identify ourselves politely.
            "User-Agent": "OpenDocs-Converter/0.1 (+https://opendocs.cc)",
            "Accept": "image/*",
        }
        current_url = url
        for _hop in range(_REMOTE_FETCH_MAX_REDIRECTS + 1):
            if not _is_safe_remote_url(current_url):
                return None

            with httpx.stream(
                "GET",
                current_url,
                timeout=_INLINE_IMAGE_TIMEOUT,
                follow_redirects=False,
                headers=headers,
            ) as resp:
                if 300 <= resp.status_code < 400:
                    location = resp.headers.get("location")
                    if not location:
                        return None
                    current_url = urljoin(current_url, location)
                    continue

                if resp.status_code >= 400:
                    return None

                # The format is sniffed from the bytes afterwards
                # (`_prepare_image`), so the content type only screens out
                # obvious non-images; some origins serve images as
                # `application/octet-stream`.
                ctype = (resp.headers.get("content-type") or "").lower().split(";")[0].strip()
                if ctype.startswith(("text/html", "application/json", "video/", "audio/")):
                    return None

                data = bytearray()
                for chunk in resp.iter_bytes():
                    data.extend(chunk)
                    if len(data) > _INLINE_IMAGE_MAX_BYTES:
                        return None
                return _prepare_image(bytes(data))
        return None
    except Exception:
        return None


def _data_uri_image(uri: str) -> Optional[str]:
    """Decode a ``data:image/...;base64,...`` URI and prepare it."""
    m = re.match(r"data:image/[a-z0-9.+-]+;base64,(.*)$", uri.strip(), re.I | re.S)
    if not m or len(m.group(1)) > _INLINE_IMAGE_MAX_BYTES * 4 // 3 + 4:
        return None
    try:
        data = base64.b64decode(re.sub(r"\s+", "", m.group(1)), validate=True)
    except (binascii.Error, ValueError):
        return None
    return _prepare_image(data)


# Formats python-docx embeds as-is, by magic bytes.
_NATIVE_IMAGE_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
    (b"BM", ".bmp"),
)
_SVG_UNITS_PX = {"": 1.0, "px": 1.0, "pt": 4 / 3, "pc": 16.0,
                 "mm": 96 / 25.4, "cm": 96 / 2.54, "in": 96.0}
# Rasterized images: at most this many pixels wide or tall, and drawn at
# up to 3x their CSS size so they stay sharp in print.
_RASTER_MAX_SIDE = 2400
_RASTER_MAX_PIXELS = 40_000_000


def _write_temp(data: bytes, suffix: str) -> str:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    with tmp:
        tmp.write(data)
    return tmp.name


def _looks_like_svg(data: bytes) -> bool:
    head = data[:2048].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    return head.startswith((b"<svg", b"<?xml", b"<!--", b"<!doctype svg")) and b"<svg" in data[:4096].lower()


def _svg_length_px(value: Optional[str]) -> Optional[float]:
    m = re.fullmatch(r"\s*([0-9]*\.?[0-9]+)\s*([a-z%]*)\s*", value or "")
    if not m or m.group(2) not in _SVG_UNITS_PX:
        return None
    return float(m.group(1)) * _SVG_UNITS_PX[m.group(2)]


def _rasterize_svg(data: bytes) -> Optional[bytes]:
    """Render an SVG to PNG, sized from its own width/height/viewBox.

    CairoSVG runs in its default safe mode: no XML entities, no external
    files and no network, only ``data:`` URLs inside the SVG. The output
    size is fixed up front so an SVG that declares a huge canvas can't
    exhaust memory. The PNG's DPI records the scale, so it's placed at the
    SVG's CSS size.
    """
    try:
        root = etree.fromstring(
            data, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
        )
    except etree.XMLSyntaxError:
        return None
    if etree.QName(root).localname != "svg":
        return None
    width = _svg_length_px(root.get("width"))
    height = _svg_length_px(root.get("height"))
    viewbox = [float(v) for v in re.split(r"[\s,]+", (root.get("viewBox") or "").strip()) if v]
    if len(viewbox) == 4 and viewbox[2] > 0 and viewbox[3] > 0:
        aspect = viewbox[2] / viewbox[3]
        if width is None and height is None:
            width, height = viewbox[2], viewbox[3]
        elif width is None:
            width = height * aspect
        elif height is None:
            height = width / aspect
    if not width or not height:
        width, height = 600.0, 400.0
    scale = min(3.0, _RASTER_MAX_SIDE / width, _RASTER_MAX_SIDE / height)
    out_w, out_h = max(1, round(width * scale)), max(1, round(height * scale))
    try:
        import cairosvg
        from PIL import Image

        png = cairosvg.svg2png(bytestring=data, output_width=out_w, output_height=out_h)
        with Image.open(io.BytesIO(png)) as img:
            buf = io.BytesIO()
            img.save(buf, format="PNG", dpi=(96 * scale, 96 * scale))
            return buf.getvalue()
    except Exception:
        return None


def _prepare_image(data: bytes) -> Optional[str]:
    """Write ``data`` to a temp file python-docx can embed and return its path.

    PNG, JPEG, GIF and BMP are kept as they are. SVG is rasterized and
    anything else Pillow can read (WebP, TIFF, AVIF, ICO...) becomes a PNG.
    The caller owns the returned file.
    """
    for signature, suffix in _NATIVE_IMAGE_SIGNATURES:
        if data.startswith(signature):
            return _write_temp(data, suffix)
    if _looks_like_svg(data):
        png = _rasterize_svg(data)
        return _write_temp(png, ".png") if png else None
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as img:
            if img.width * img.height > _RASTER_MAX_PIXELS:
                return None
            img.seek(0)
            converted = img.convert("RGBA" if "A" in img.getbands() or img.mode == "P" else "RGB")
            buf = io.BytesIO()
            converted.save(buf, format="PNG")
            return _write_temp(buf.getvalue(), ".png")
    except Exception:
        return None


BUNDLED_LOGO_SENTINEL = "bundled:opendocs"


def _resolve_logo(brand: BrandingConfig) -> tuple[Optional[str], bool]:
    """Resolve brand.logo_url into a local file path.

    Three modes:
        * ``None``                     → no logo (return ``(None, False)``)
        * ``"bundled:opendocs"``       → use the packaged OpenDocs logo
          (Free plan branding).
        * ``"https://..."`` / ``"http://..."``
                                       → download to a temp file and return
          its path.

    Returns
    -------
    (path, is_temp) : tuple[str | None, bool]
        ``path``   : filesystem path to the logo image, or ``None``.
        ``is_temp``: ``True`` if the file was downloaded and the caller
                     should unlink it after use; ``False`` for the bundled
                     logo (never delete it).
    """
    if not brand.logo_url:
        return None, False

    # Bundled OpenDocs logo — used for the Free plan
    if brand.logo_url == BUNDLED_LOGO_SENTINEL:
        bundled = os.path.join(os.path.dirname(__file__), "..", "assets", "logo.png")
        if os.path.exists(bundled):
            return os.path.abspath(bundled), False
        return None, False

    # External URL — download into a temp file
    if brand.logo_url.startswith(("http://", "https://")):
        try:
            # Polite User-Agent — some CDNs (and Wikipedia) reject the
            # default httpx UA with a 403.
            headers = {
                "User-Agent": "OpenDocs-Converter/0.1 (+https://opendocs.cc)",
            }
            current_url = brand.logo_url
            for _hop in range(_REMOTE_FETCH_MAX_REDIRECTS + 1):
                if not _is_safe_remote_url(current_url):
                    return None, False
                with httpx.stream(
                    "GET",
                    current_url,
                    timeout=10,
                    follow_redirects=False,
                    headers=headers,
                ) as resp:
                    if 300 <= resp.status_code < 400:
                        location = resp.headers.get("location")
                        if not location:
                            return None, False
                        current_url = urljoin(current_url, location)
                        continue
                    resp.raise_for_status()
                    ctype = resp.headers.get("content-type", "").lower()
                    suffix = ".png"
                    if "jpeg" in ctype or "jpg" in ctype or current_url.lower().endswith((".jpg", ".jpeg")):
                        suffix = ".jpg"
                    elif "gif" in ctype or current_url.lower().endswith(".gif"):
                        suffix = ".gif"
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                    total = 0
                    try:
                        for chunk in resp.iter_bytes():
                            if not chunk:
                                continue
                            total += len(chunk)
                            if total > _REMOTE_LOGO_MAX_BYTES:
                                raise ValueError("logo exceeds size cap")
                            tmp.write(chunk)
                        tmp.close()
                        return tmp.name, True
                    except Exception:
                        tmp.close()
                        try:
                            os.unlink(tmp.name)
                        except OSError:
                            pass
                        return None, False
            return None, False
        except Exception:
            return None, False

    # Unrecognized value — treat as "no logo" rather than crash
    return None, False


# ---------------------------------------------------------------------------
# Markdown token text extraction
# ---------------------------------------------------------------------------

def _extract_text_from_inline_tokens(tokens) -> str:
    """Recursively extract text from inline tokens, preserving markdown
    formatting markers so _parse_inline_segments can handle them."""
    parts: list[str] = []
    for tok in tokens:
        if tok.type == "text":
            parts.append(tok.content)
        elif tok.type == "code_inline":
            parts.append(f"`{tok.content}`")
        elif tok.type == "softbreak":
            parts.append(" ")
        elif tok.type == "hardbreak":
            parts.append("\n")
        elif tok.type == "strong_open":
            parts.append("**")
        elif tok.type == "strong_close":
            parts.append("**")
        elif tok.type == "em_open":
            parts.append("*")
        elif tok.type == "em_close":
            parts.append("*")
        elif tok.type == "link_open":
            href = ""
            for attr_name, attr_val in (tok.attrs or {}).items():
                if attr_name == "href":
                    href = attr_val
            parts.append("[")
            parts.append(f"__LINK_HREF__{href}__")
        elif tok.type == "link_close":
            href = ""
            for j in range(len(parts) - 1, -1, -1):
                if parts[j].startswith("__LINK_HREF__"):
                    href = parts[j].replace("__LINK_HREF__", "").rstrip("_")
                    parts[j] = ""
                    break
            for j in range(len(parts) - 1, -1, -1):
                if parts[j] == "[":
                    link_text = "".join(parts[j + 1 :])
                    parts = parts[: j]
                    parts.append(f"[{link_text}]({href})")
                    break
        elif tok.type == "image":
            alt = tok.content or "image"
            parts.append(f"[{alt}]")
        elif tok.children:
            parts.append(_extract_text_from_inline_tokens(tok.children))
        else:
            if tok.content:
                parts.append(tok.content)
    return "".join(parts)


# ---------------------------------------------------------------------------
# Metadata detection
# ---------------------------------------------------------------------------

def _detect_metadata_line(line: str) -> bool:
    """Return True if a line looks like 'Key: value | Key: value | ...'."""
    if "|" not in line or line.startswith("|"):
        return False
    parts = [p.strip() for p in line.split("|")]
    kv_count = sum(1 for p in parts if ":" in p and len(p) < 100)
    return kv_count >= 2


# ---------------------------------------------------------------------------
# DocxBuilder — walks markdown-it tokens and builds a python-docx Document
# ---------------------------------------------------------------------------

class DocxBuilder:
    """Stateful builder that turns markdown-it tokens into a styled Word doc."""

    def __init__(self, brand: BrandingConfig, *, landscape: bool = False,
                 page_break_before: int | None = None,
                 skip_first_break: bool = True):
        self.doc = Document()
        self.brand = brand
        self._landscape = landscape

        # Page-break config: which heading level triggers a break
        # e.g. page_break_before=2 means every H2 gets a page break above it.
        self._page_break_level = page_break_before
        self._skip_first_break = skip_first_break
        self._break_heading_count = 0  # tracks how many matching headings we've seen

        # Resolved RGBColor instances
        self._c_heading = _hex_to_rgb(brand.heading_color)
        self._c_body = _hex_to_rgb(brand.body_color)
        self._c_metadata = _hex_to_rgb(brand.metadata_color)
        self._c_link = _hex_to_rgb(brand.link_color)
        self._c_table_hdr_fg = _hex_to_rgb(brand.table_header_fg)

        # Hex-only values (used in XML strings without '#')
        self._h_table_hdr_bg = _hex_strip(brand.table_header_bg)
        self._h_alt_row = _hex_strip(brand.alt_row_bg)
        self._h_border = _hex_strip(brand.border_color)
        self._h_code_bg = _hex_strip(brand.code_bg)
        self._h_code_border = _hex_strip(brand.code_border)

        self._current_list_level = 0
        self._num_id_counter = 100
        self._current_num_id: int | None = None
        # How many blockquotes the current block sits in.
        self._quote_depth = 0
        # The last code block paragraph, to keep adjacent blocks apart.
        self._last_code_p = None

        self._setup_page()
        self._setup_styles()

        section = self.doc.sections[0]
        self._content_width = section.page_width - section.left_margin - section.right_margin
        self._content_height = Cm(18)

    # ── Page setup ──────────────────────────────────────────────────────

    def _setup_page(self):
        for section in self.doc.sections:
            if self._landscape:
                section.orientation = WD_ORIENT.LANDSCAPE
                section.page_width = Cm(29.7)
                section.page_height = Cm(21.0)
            else:
                section.orientation = WD_ORIENT.PORTRAIT
                section.page_width = Cm(21.0)
                section.page_height = Cm(29.7)
            section.top_margin = Cm(2.5)
            section.bottom_margin = Cm(2.5)
            section.left_margin = Cm(2.5)
            section.right_margin = Cm(2.5)
            # Word's defaults are 0.5 in for both — pulling them in to
            # 0.3 in gives the page more usable vertical real estate
            # and tucks the logo/footer closer to the content area.
            section.header_distance = Inches(0.3)
            section.footer_distance = Inches(0.3)

    # ── Style setup ─────────────────────────────────────────────────────

    def _setup_styles(self):
        styles = self.doc.styles
        b = self.brand

        # Normal
        sn = styles["Normal"]
        sn.font.name = b.font_main
        sn.font.size = Pt(11)
        sn.font.color.rgb = self._c_body
        sn.paragraph_format.space_before = Pt(12)
        sn.paragraph_format.space_after = Pt(12)
        sn.paragraph_format.line_spacing = 1.25

        # Title (first document-level H1 only)
        st = styles["Title"]
        st.font.name = b.font_main
        st.font.size = Pt(18)
        st.font.bold = True
        st.font.color.rgb = self._c_heading
        st.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
        st.paragraph_format.space_before = Pt(0)
        st.paragraph_format.space_after = Pt(30)
        st.paragraph_format.line_spacing = 1.25
        # The template's Title has a bottom rule; replace it with none.
        p_pr = st.element.get_or_add_pPr()
        for old in p_pr.findall(qn("w:pBdr")):
            p_pr.remove(old)
        p_pr.insert_element_before(parse_xml(
            f'<w:pBdr {nsdecls("w")}>'
            f'<w:bottom w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
            f"</w:pBdr>"
        ), *_PPR_AFTER_PBDR)

        # Heading 1 (body H1)
        sh1 = styles["Heading 1"]
        sh1.font.name = b.font_main
        sh1.font.size = Pt(17)
        sh1.font.bold = True
        sh1.font.color.rgb = self._c_heading
        sh1.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
        sh1.paragraph_format.space_before = Pt(28)
        sh1.paragraph_format.space_after = Pt(8)
        sh1.paragraph_format.line_spacing = 1.2
        sh1.paragraph_format.keep_with_next = True

        # Heading 2
        sh2 = styles["Heading 2"]
        sh2.font.name = b.font_main
        sh2.font.size = Pt(14)
        sh2.font.bold = True
        sh2.font.color.rgb = self._c_heading
        sh2.paragraph_format.space_before = Pt(18)
        sh2.paragraph_format.space_after = Pt(6)
        sh2.paragraph_format.line_spacing = 1.25

        # Heading 3
        sh3 = styles["Heading 3"]
        sh3.font.name = b.font_main
        sh3.font.size = Pt(12)
        sh3.font.bold = False
        sh3.font.color.rgb = self._c_heading
        sh3.paragraph_format.space_before = Pt(14)
        sh3.paragraph_format.space_after = Pt(4)
        sh3.paragraph_format.line_spacing = 1.25

        # Heading 4+
        sh4 = styles["Heading 4"]
        sh4.font.name = b.font_main
        sh4.font.size = Pt(11)
        sh4.font.bold = True
        sh4.font.color.rgb = self._c_heading
        sh4.paragraph_format.space_before = Pt(12)
        sh4.paragraph_format.space_after = Pt(4)
        sh4.paragraph_format.line_spacing = 1.25

        # List Bullet
        slb = styles["List Bullet"]
        slb.font.name = b.font_main
        slb.font.size = Pt(11)
        slb.font.color.rgb = self._c_body
        slb.paragraph_format.space_before = Pt(2)
        slb.paragraph_format.space_after = Pt(2)
        slb.paragraph_format.line_spacing = 1.25
        slb.paragraph_format.left_indent = Cm(1.27)
        slb.paragraph_format.first_line_indent = Cm(-0.63)

        # List Number
        sln = styles["List Number"]
        sln.font.name = b.font_main
        sln.font.size = Pt(11)
        sln.font.color.rgb = self._c_body
        sln.paragraph_format.space_before = Pt(2)
        sln.paragraph_format.space_after = Pt(2)
        sln.paragraph_format.line_spacing = 1.25

        # Nested list styles
        bullet_indents = {
            "List Bullet 2": (Cm(1.90), Cm(-0.63)),
            "List Bullet 3": (Cm(2.54), Cm(-0.63)),
        }
        for name in ("List Bullet 2", "List Number 2",
                     "List Bullet 3", "List Number 3"):
            if name in styles:
                ns = styles[name]
                ns.font.name = b.font_main
                ns.font.size = Pt(11)
                ns.font.color.rgb = self._c_body
                ns.paragraph_format.space_before = Pt(2)
                ns.paragraph_format.space_after = Pt(2)
                ns.paragraph_format.line_spacing = 1.25
                if name in bullet_indents:
                    ns.paragraph_format.left_indent = bullet_indents[name][0]
                    ns.paragraph_format.first_line_indent = bullet_indents[name][1]

    # ── Content methods ─────────────────────────────────────────────────

    def _runs(self, p, content, *, bold=False, italic=False,
              color: RGBColor | None = None, size=Pt(11)):
        """Add inline content to ``p`` in the brand's fonts and colors."""
        _add_inline_runs(
            p, content, base_bold=bold, base_italic=italic,
            base_color=color or self._c_body, base_font=self.brand.font_main,
            base_size=size, code_font=self.brand.code_block_font,
            code_bg=self._h_code_bg, add_image=self._add_picture_run,
        )

    def _apply_quote(self, p, base_indent=Cm(0)):
        """Indent ``p`` and give it a brand-colored bar if it's in a quote.

        Consecutive paragraphs with the same border are drawn with one
        continuous bar, so a multi-paragraph quote reads as one block.
        """
        if not self._quote_depth:
            return
        pf = p.paragraph_format
        pf.left_indent = base_indent + Cm(0.75 * self._quote_depth)
        if pf.space_before is None or pf.space_before > Pt(4):
            pf.space_before = Pt(4)
        if pf.space_after is None or pf.space_after > Pt(4):
            pf.space_after = Pt(4)
        _set_paragraph_borders(p, {
            "left": f'w:val="single" w:sz="18" w:space="10" w:color="{_hex_strip(self.brand.heading_color)}"',
        })
        for run in p.runs:
            if run.font.color.rgb == self._c_body:
                run.font.color.rgb = _hex_to_rgb("#404040")

    def _heading(self, level: int, text, *, as_title: bool = False):
        b = self.brand

        # Insert a page break before this heading if configured.
        # page_break_level=2 means "break before every H2".
        # Headings at this level *or higher* (lower number) also trigger it
        # — so H1 always breaks if H2 breaks.  H3 does not.
        if (self._page_break_level is not None
                and level <= self._page_break_level):
            self._break_heading_count += 1
            should_break = True
            if self._skip_first_break and self._break_heading_count == 1:
                should_break = False
            if should_break:
                # "Page break before" via paragraph formatting on the heading
                # itself.  We set it after creating the paragraph below.
                pass  # flag handled after paragraph creation
            else:
                # First occurrence — no break
                pass

        if level == 1 and as_title:
            p = self.doc.add_paragraph(style="Title")
            self._runs(p, text, bold=True, color=self._c_heading, size=Pt(18))
        elif level == 1:
            p = self.doc.add_paragraph(style="Heading 1")
            self._runs(p, text, bold=True, color=self._c_heading, size=Pt(17))
        elif level == 2:
            p = self.doc.add_paragraph(style="Heading 2")
            self._runs(p, text, bold=True, color=self._c_heading, size=Pt(14))
        elif level == 3:
            p = self.doc.add_paragraph(style="Heading 3")
            self._runs(p, text, bold=False, color=self._c_heading, size=Pt(12))
        else:
            p = self.doc.add_paragraph(style="Heading 4")
            self._runs(p, text, bold=True, color=self._c_heading, size=Pt(11))

        # Apply page-break-before if this heading qualifies
        if (self._page_break_level is not None
                and level <= self._page_break_level):
            is_first = (self._break_heading_count == 1)
            if not (self._skip_first_break and is_first):
                p.paragraph_format.page_break_before = True

        return p

    def _paragraph(self, content, *, bold=False):
        p = self.doc.add_paragraph(style="Normal")
        self._runs(p, content, bold=bold)
        self._apply_quote(p)
        return p

    def _add_picture_run(self, paragraph, src: str, alt: str) -> bool:
        """Append ``src`` to ``paragraph`` as a picture; ``False`` if it fails.

        Only remote and ``data:`` images are embedded. Markdown comes from
        untrusted users, so a local path (e.g. `/dev/zero`, `/etc/...`)
        must never be read off the converter's own filesystem. Pictures
        keep their natural size (CSS pixels at 96 per inch), shrunk to fit
        the page.
        """
        src = (src or "").strip()
        if src.startswith(("http://", "https://")):
            path = _download_inline_image(src)
        elif src.lower().startswith("data:image/"):
            path = _data_uri_image(src)
        else:
            path = None
        if path is None:
            return False
        try:
            image = DocxImage.from_file(path)
            dpi = image.horz_dpi if image.horz_dpi and image.horz_dpi > 96 else 96
            width = Emu(int(image.px_width / dpi * 914400))
            height = Emu(int(width * image.px_height / max(image.px_width, 1)))
            max_width = self._content_width - (paragraph.paragraph_format.left_indent or 0)
            if width > max_width:
                height = Emu(int(height * max_width / width))
                width = max_width
            if height > self._content_height:
                width = Emu(int(width * self._content_height / height))
            paragraph.add_run().add_picture(path, width=width)
            return True
        except Exception:
            # python-docx couldn't decode the payload (truncated, wrong
            # magic bytes, unsupported format).
            return False
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def _image(self, images: list[tuple[str, str]]):
        """A centered paragraph of one or more images.

        An image that can't be fetched, decoded or embedded shows as its
        ``[alt]`` text, so a single broken URL never aborts the export.
        """
        p = self.doc.add_paragraph(style="Normal")
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        self._apply_quote(p)
        for n, (src, alt) in enumerate(images):
            if n:
                p.add_run(" ")
            if not self._add_picture_run(p, src, alt):
                self._runs(p, f"[{alt or 'image'}]")
        return p

    def _metadata_line(self, text: str):
        p = self.doc.add_paragraph(style="Normal")
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(6)
        run = p.add_run(text)
        run.font.name = self.brand.font_main
        run.font.size = Pt(9)
        run.italic = True
        run.font.color.rgb = self._c_metadata
        return p

    def _hr(self):
        p = self.doc.add_paragraph(style="Normal")
        p.paragraph_format.space_before = Pt(12)
        p.paragraph_format.space_after = Pt(12)
        p.paragraph_format.line_spacing = Pt(2)
        _set_paragraph_borders(p, {
            "bottom": f'w:val="single" w:sz="6" w:space="1" w:color="{self._h_code_border}"',
        })

    def _formula(self, text: str):
        """Add a formula as an OMML math paragraph (renders natively in Word)."""
        p = self.doc.add_paragraph(style="Normal")
        escaped = _xml_escape(text)
        math_xml = (
            f'<m:oMathPara xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"'
            f' xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<m:oMath>"
            f"<m:r>"
            f'<w:rPr><w:rFonts w:ascii="Cambria Math" w:hAnsi="Cambria Math"/></w:rPr>'
            f'<m:t xml:space="preserve">{escaped}</m:t>'
            f"</m:r>"
            f"</m:oMath>"
            f"</m:oMathPara>"
        )
        p._p.append(parse_xml(math_xml))
        return p

    # ── Numbering (ordered lists) ───────────────────────────────────────

    def _create_numbering(self, start: int = 1):
        self._num_id_counter += 1
        abstract_num_id = self._num_id_counter
        num_id = self._num_id_counter

        numbering_part = self.doc.part.numbering_part
        numbering_elem = numbering_part.numbering_definitions._numbering

        abstract_xml = (
            f'<w:abstractNum {nsdecls("w")} w:abstractNumId="{abstract_num_id}">'
            f'  <w:multiLevelType w:val="hybridMultilevel"/>'
        )
        indents = [(720, 360), (1440, 360), (2160, 360)]
        for lvl, (ind, hang) in enumerate(indents):
            abstract_xml += (
                f'<w:lvl w:ilvl="{lvl}">'
                f'  <w:start w:val="{start}"/>'
                f'  <w:numFmt w:val="decimal"/>'
                f'  <w:lvlText w:val="%{lvl + 1}."/>'
                f'  <w:lvlJc w:val="left"/>'
                f'  <w:pPr><w:ind w:left="{ind}" w:hanging="{hang}"/></w:pPr>'
                f"  <w:rPr>"
                f'    <w:rFonts w:ascii="{self.brand.font_main}" w:hAnsi="{self.brand.font_main}"/>'
                f'    <w:sz w:val="22"/>'
                f"  </w:rPr>"
                f"</w:lvl>"
            )
        abstract_xml += "</w:abstractNum>"
        abstract_elem = parse_xml(abstract_xml)

        first_num = numbering_elem.find(qn("w:num"))
        if first_num is not None:
            first_num.addprevious(abstract_elem)
        else:
            numbering_elem.append(abstract_elem)

        num_xml = (
            f'<w:num {nsdecls("w")} w:numId="{num_id}">'
            f'  <w:abstractNumId w:val="{abstract_num_id}"/>'
            f"</w:num>"
        )
        numbering_elem.append(parse_xml(num_xml))
        self._current_num_id = num_id
        return num_id

    def _apply_numbering(self, paragraph, num_id: int, level: int = 0):
        p_pr = paragraph._p.get_or_add_pPr()
        num_pr = parse_xml(
            f'<w:numPr {nsdecls("w")}>'
            f'  <w:ilvl w:val="{level}"/>'
            f'  <w:numId w:val="{num_id}"/>'
            f"</w:numPr>"
        )
        p_pr.insert(0, num_pr)

    # ── List items ──────────────────────────────────────────────────────

    @staticmethod
    def _list_text_indent(level: int):
        """Where a list item's text starts (bullets and numbers line up)."""
        return Cm(1.27 + 0.63 * level)

    def _list_item(self, content, *, ordered: bool = False, level: int = 0,
                   num_id: int | None = None, task: bool | None = None):
        """One list item. ``task`` is ``True``/``False`` for a checked or
        open task-list item (``- [x]`` / ``- [ ]``), drawn with a box
        instead of a bullet."""
        text = content if isinstance(content, str) else _segments_text(content)
        letter_ordered = not ordered and re.match(r"^\([a-z]+\)\s", text.lstrip())

        if letter_ordered or task is not None:
            p = self.doc.add_paragraph(style="Normal")
            pf = p.paragraph_format
            pf.space_before = Pt(2)
            pf.space_after = Pt(2)
            pf.left_indent = self._list_text_indent(level)
            pf.first_line_indent = Cm(-0.63)
            if task is not None:
                pf.tab_stops.add_tab_stop(pf.left_indent)
                box = p.add_run(("☑" if task else "☐") + "\t")
                box.font.name = "DejaVu Sans"
                box.font.size = Pt(11)
                box.font.color.rgb = self._c_heading if task else self._c_body
            self._runs(p, content)
            self._apply_quote(p, pf.left_indent)
            return p

        if not ordered:
            style_names = ["List Bullet", "List Bullet 2", "List Bullet 3"]
            style_idx = min(level, len(style_names) - 1)
            p = self.doc.add_paragraph(style=style_names[style_idx])
            self._runs(p, content)
            self._apply_quote(p, self._list_text_indent(level))
            return p

        p = self.doc.add_paragraph(style="Normal")
        p.paragraph_format.space_before = Pt(2)
        p.paragraph_format.space_after = Pt(2)
        num_id = num_id if num_id is not None else self._current_num_id
        if num_id is not None:
            self._apply_numbering(p, num_id, level=level)
        self._runs(p, content)
        self._apply_quote(p, self._list_text_indent(level))
        return p

    def _list_continuation(self, content, *, level: int = 0):
        """A later paragraph of a list item: indented, without a bullet."""
        p = self.doc.add_paragraph(style="Normal")
        pf = p.paragraph_format
        pf.space_before = Pt(2)
        pf.space_after = Pt(4)
        pf.left_indent = self._list_text_indent(level)
        self._runs(p, content)
        self._apply_quote(p, pf.left_indent)
        return p

    def _footnote(self, number: int, content):
        p = self.doc.add_paragraph(style="Normal")
        pf = p.paragraph_format
        pf.space_before = Pt(0)
        pf.space_after = Pt(3)
        pf.left_indent = Cm(0.5)
        pf.first_line_indent = Cm(-0.5)
        pf.tab_stops.add_tab_stop(Cm(0.5))
        mark = p.add_run(f"{number}\t")
        mark.font.name = self.brand.font_main
        mark.font.size = Pt(9)
        mark.font.color.rgb = self._c_heading
        self._runs(p, content, size=Pt(9))
        return p

    # ── Code blocks ─────────────────────────────────────────────────────

    def _code_block(self, text: str, *, indent=None):
        p = self.doc.add_paragraph(style="Normal")
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(6)
        p.paragraph_format.line_spacing = 1.0
        if indent is not None:
            p.paragraph_format.left_indent = indent
        # Adjacent paragraphs with identical borders are drawn as one box,
        # so two code blocks in a row get a small spacer between them.
        if self._last_code_p is not None and p._p.getprevious() is self._last_code_p._p:
            spacer = self.doc.add_paragraph(style="Normal")
            spacer.paragraph_format.space_before = Pt(0)
            spacer.paragraph_format.space_after = Pt(0)
            spacer.paragraph_format.line_spacing = Pt(4)
            p._p.addprevious(spacer._p)
        self._last_code_p = p
        if self._quote_depth:
            p.paragraph_format.left_indent = (indent or Cm(0)) + Cm(0.75 * self._quote_depth)

        _set_paragraph_borders(p, {
            side: f'w:val="single" w:sz="4" w:space="{space}" w:color="{self._h_code_border}"'
            for side, space in (("top", 2), ("left", 4), ("bottom", 2), ("right", 4))
        })
        _shade_paragraph(p, self._h_code_bg)

        run = p.add_run(text)
        run.font.name = self.brand.code_block_font
        run.font.size = Pt(9)
        run.font.color.rgb = self._c_body

    # ── Tables ──────────────────────────────────────────────────────────

    def _add_table(self, header_row: list, body_rows: list[list],
                   alignments: list[str] | None = None):
        """``header_row`` and ``body_rows`` hold cell segments (or strings)."""
        if not header_row:
            return

        table_font_size = Pt(7) if self._landscape else Pt(10)
        num_cols = len(header_row)
        table = self.doc.add_table(rows=1, cols=num_cols)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = True

        tbl = table._tbl
        tbl_pr = tbl.tblPr if tbl.tblPr is not None else parse_xml(
            f'<w:tblPr {nsdecls("w")}/>'
        )
        tbl_width = parse_xml(f'<w:tblW {nsdecls("w")} w:w="5000" w:type="pct"/>')
        tbl_pr.append(tbl_width)

        # Header row
        hdr = table.rows[0]
        _set_table_repeat_header(hdr)
        for i, cell_text in enumerate(header_row):
            cell = hdr.cells[i]
            _set_cell_shading(cell, self._h_table_hdr_bg)
            _set_cell_borders(cell, self._h_border)
            _set_cell_padding(cell)
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            p = cell.paragraphs[0]
            _set_cell_paragraph_tight(p)
            if alignments and i < len(alignments):
                if alignments[i] == "center":
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                elif alignments[i] == "right":
                    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            self._runs(p, cell_text, bold=True, color=self._c_table_hdr_fg,
                       size=table_font_size)

        # Body rows
        for row_idx, row_data in enumerate(body_rows):
            row_cells = table.add_row().cells
            for i, cell_text in enumerate(row_data):
                if i >= num_cols:
                    break
                cell = row_cells[i]
                _set_cell_borders(cell, self._h_border)
                _set_cell_padding(cell)
                cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
                if row_idx % 2 == 1:
                    _set_cell_shading(cell, self._h_alt_row)
                p = cell.paragraphs[0]
                _set_cell_paragraph_tight(p)
                if alignments and i < len(alignments):
                    if alignments[i] == "center":
                        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    elif alignments[i] == "right":
                        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                self._runs(p, cell_text, size=table_font_size)

    # ── Finalize ────────────────────────────────────────────────────────

    def finalize(self, logo_path: str | None = None) -> Document:
        if logo_path and os.path.exists(logo_path):
            _add_header(self.doc, logo_path)
        _add_footer(self.doc, self.brand)
        return self.doc


# ---------------------------------------------------------------------------
# Token-level list / table processors
# ---------------------------------------------------------------------------

_TASK_MARKER = re.compile(r"^\[([ xX])\]\s+")


def _take_task_marker(segments: list[dict]) -> Optional[bool]:
    """Strip a leading ``[ ]`` / ``[x]`` and return whether it was checked."""
    if not segments or segments[0]["image"] or segments[0]["code"]:
        return None
    m = _TASK_MARKER.match(segments[0]["text"])
    if not m:
        return None
    segments[0] = dict(segments[0], text=segments[0]["text"][m.end():])
    return m.group(1) != " "


def _process_list(tokens, start: int, builder: DocxBuilder,
                  ordered: bool, level: int) -> int:
    """Render a list. The first paragraph of each item gets the bullet or
    number; later paragraphs, code blocks, quotes and tables inside the
    item are indented under it."""
    list_type = "bullet_list" if not ordered else "ordered_list"
    close_tag = f"{list_type}_close"
    num_id = None
    if ordered:
        try:
            first_number = int(tokens[start].attrGet("start") or 1)
        except (TypeError, ValueError):
            first_number = 1
        num_id = builder._create_numbering(start=first_number)
    i = start + 1

    while i < len(tokens):
        tok = tokens[i]
        if tok.type == close_tag:
            return i + 1
        if tok.type != "list_item_open":
            i += 1
            continue

        i += 1
        first_paragraph = True
        while i < len(tokens) and tokens[i].type != "list_item_close":
            t = tokens[i]
            if t.type == "paragraph_open":
                inline = tokens[i + 1] if i + 1 < len(tokens) else None
                segments = _inline_segments(inline.children) if inline is not None else []
                if first_paragraph:
                    task = None if ordered else _take_task_marker(segments)
                    builder._list_item(segments, ordered=ordered, level=level,
                                       num_id=num_id, task=task)
                    first_paragraph = False
                else:
                    builder._list_continuation(segments, level=level)
                i += 3  # paragraph_open, inline, paragraph_close
            elif t.type in ("bullet_list_open", "ordered_list_open"):
                i = _process_list(tokens, i, builder,
                                  ordered=t.type == "ordered_list_open", level=level + 1)
            elif t.type in ("fence", "code_block"):
                builder._code_block(t.content.rstrip("\n"),
                                    indent=builder._list_text_indent(level))
                i += 1
            elif t.type == "blockquote_open":
                builder._quote_depth += 1
                i += 1
            elif t.type == "blockquote_close":
                builder._quote_depth = max(0, builder._quote_depth - 1)
                i += 1
            elif t.type == "table_open":
                i = _process_table(tokens, i, builder, "")
            else:
                i += 1
        i += 1  # list_item_close
    return i


def _process_table(tokens, start: int, builder: DocxBuilder, md_text: str = "") -> int:
    """Render a table. Column alignment comes from the header cells'
    ``text-align`` style, which markdown-it sets from the ``:---:`` row."""
    i = start + 1
    header_cells: list = []
    body_rows: list[list] = []
    current_row: list = []
    alignments: list[str] = []
    in_header = False

    while i < len(tokens):
        tok = tokens[i]
        if tok.type == "table_close":
            if header_cells:
                builder._add_table(header_cells, body_rows, alignments)
            return i + 1
        elif tok.type == "thead_open":
            in_header = True
        elif tok.type == "thead_close":
            in_header = False
        elif tok.type == "tr_open":
            current_row = []
        elif tok.type == "tr_close":
            if in_header:
                header_cells = current_row
            else:
                body_rows.append(current_row)
            current_row = []
        elif tok.type in ("th_open", "td_open"):
            if tok.type == "th_open":
                m = re.search(r"text-align:\s*(left|center|right)", tok.attrGet("style") or "")
                alignments.append(m.group(1) if m else "left")
            i += 1
            cell: list = []
            if i < len(tokens) and tokens[i].type == "inline":
                cell = _inline_segments(tokens[i].children)
                i += 1
            current_row.append(cell)
            if i < len(tokens) and tokens[i].type in ("th_close", "td_close"):
                i += 1
            continue
        i += 1

    if header_cells:
        builder._add_table(header_cells, body_rows, alignments)
    return i


def _render_html_block(html: str, builder: DocxBuilder) -> bool:
    """Render a raw HTML block as text: comments are dropped, ``<img>``
    tags become images, ``<summary>`` is bold and other tags are stripped.
    Returns whether anything was added."""
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    added = False
    images = [(_html_attr(tag, "src"), _html_attr(tag, "alt"))
              for tag in re.findall(r"<img\b[^>]*>", html, flags=re.I)]
    if images:
        builder._image(images)
        added = True
        html = re.sub(r"<img\b[^>]*>", "", html, flags=re.I)
    is_summary = bool(re.search(r"<summary\b", html, re.I))
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    text = html_lib.unescape(re.sub(r"<[^>]+>", "", html))
    text = "\n".join(line.strip() for line in text.strip().splitlines() if line.strip())
    if text:
        builder._paragraph([dict(_SEGMENT_DEFAULTS, text=text)], bold=is_summary)
        added = True
    return added


def _process_footnotes(tokens, start: int, builder: DocxBuilder) -> int:
    """Footnotes go at the end under a short rule, numbered like their
    superscript references."""
    builder._hr()
    i = start + 1
    number = 0
    first = True
    while i < len(tokens) and tokens[i].type != "footnote_block_close":
        tok = tokens[i]
        if tok.type == "footnote_open":
            number = tok.meta["id"] + 1
            first = True
        elif tok.type == "inline":
            segments = _inline_segments(tok.children)
            if first:
                builder._footnote(number, segments)
                first = False
            else:
                p = builder._footnote(number, segments)
                p.runs[0].text = "\t"
        i += 1
    return i + 1


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def convert_md_to_docx(
    md_text: str,
    *,
    brand: BrandingConfig | None = None,
    landscape: bool = False,
    page_break_before: int | None = None,
    skip_first_break: bool = True,
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

    Returns
    -------
    bytes
        The .docx file content.
    """
    if brand is None:
        brand = OPENDOCS_BRAND

    builder = DocxBuilder(
        brand,
        landscape=landscape,
        page_break_before=page_break_before,
        skip_first_break=skip_first_break,
    )
    logo_path, logo_is_temp = _resolve_logo(brand)

    # Pre-process metadata
    lines = md_text.split("\n")
    metadata_text: str | None = None
    content_start = 0

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            break
        if _detect_metadata_line(stripped):
            metadata_text = stripped
            content_start = idx + 1
            break
        if idx > 2:
            break

    pre_heading_meta: list[str] = []
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            content_start = max(content_start, 0)
            break
        if stripped.startswith("**") and ":" in stripped and not stripped.startswith("| "):
            pre_heading_meta.append(stripped)
            content_start = idx + 1

    if metadata_text:
        builder._metadata_line(metadata_text)
    if pre_heading_meta and not metadata_text:
        builder._metadata_line("  |  ".join(pre_heading_meta))

    # Parse tokens: CommonMark plus GitHub's tables, strikethrough and
    # footnotes. Task lists are handled in _process_list.
    md = MarkdownIt("commonmark", {"typographer": True})
    md.enable(["table", "strikethrough"])
    md.use(footnote_plugin)
    # markdown-it only allows GIF/PNG/JPEG/WebP data: URLs (a guard for
    # HTML output). SVG is rasterized here without scripts or external
    # files, so it's safe too.
    default_validate_link = md.validateLink
    md.validateLink = lambda url: (
        url.strip().lower().startswith("data:image/svg+xml;base64,")
        or default_validate_link(url)
    )
    tokens = md.parse(md_text)

    # Walk tokens
    i = 0
    skip_until_content_start = content_start > 0
    seen_heading = False
    emitted_body_content = False
    while i < len(tokens):
        tok = tokens[i]

        if skip_until_content_start and tok.map and tok.map[0] < content_start:
            if tok.type != "heading_open":
                i += 1
                continue
            else:
                skip_until_content_start = False

        if tok.type == "heading_open":
            skip_until_content_start = False
            level = int(tok.tag[1])
            i += 1
            if i < len(tokens) and tokens[i].type == "inline":
                as_title = (
                    level == 1
                    and not seen_heading
                    and not emitted_body_content
                )
                builder._heading(level, _inline_segments(tokens[i].children), as_title=as_title)
                seen_heading = True
            i += 2  # skip heading_close + advance
            continue

        elif tok.type == "paragraph_open":
            i += 1
            if i < len(tokens) and tokens[i].type == "inline":
                inline_tok = tokens[i]
                segments = _inline_segments(inline_tok.children)
                images = _paragraph_images(segments)
                if images:
                    previous = builder._image(images)._p.getprevious()
                    if previous is not None and previous.tag == qn("w:p"):
                        text_before = "".join(previous.itertext()).rstrip()
                        if text_before.endswith(":"):
                            ppr = previous.get_or_add_pPr()
                            ppr.insert_element_before(
                                parse_xml(f'<w:keepNext {nsdecls("w")}/>'),
                                *_PPR_AFTER_KEEP_NEXT,
                            )
                    emitted_body_content = True
                    i += 2
                    continue
                # Metadata and formulas are matched on the Markdown text
                text = (_extract_text_from_inline_tokens(inline_tok.children)
                        if inline_tok.children else inline_tok.content)
                # Skip already-processed metadata
                if metadata_text and text.strip() == metadata_text.strip():
                    i += 2
                    continue
                if pre_heading_meta:
                    is_meta = any(text.strip().startswith(m[:20]) for m in pre_heading_meta)
                    if is_meta:
                        i += 2
                        continue
                # Formula support: formula(text here)
                formula_match = re.match(r"^formula\((.+)\)$", text.strip())
                if formula_match:
                    builder._formula(formula_match.group(1))
                    emitted_body_content = True
                    i += 2
                    continue
                builder._paragraph(segments)
                emitted_body_content = True
            i += 2
            continue

        elif tok.type == "blockquote_open":
            builder._quote_depth += 1
            i += 1
            continue

        elif tok.type == "blockquote_close":
            builder._quote_depth = max(0, builder._quote_depth - 1)
            i += 1
            continue

        elif tok.type == "hr":
            builder._hr()
            i += 1
            continue

        elif tok.type == "bullet_list_open":
            i = _process_list(tokens, i, builder, ordered=False, level=0)
            emitted_body_content = True
            continue

        elif tok.type == "ordered_list_open":
            i = _process_list(tokens, i, builder, ordered=True, level=0)
            emitted_body_content = True
            continue

        elif tok.type in ("fence", "code_block"):
            builder._code_block(tok.content.rstrip("\n"))
            emitted_body_content = True
            i += 1
            continue

        elif tok.type == "table_open":
            i = _process_table(tokens, i, builder)
            emitted_body_content = True
            continue

        elif tok.type == "html_block":
            if _render_html_block(tok.content, builder):
                emitted_body_content = True
            i += 1
            continue

        elif tok.type == "footnote_block_open":
            i = _process_footnotes(tokens, i, builder)
            continue

        else:
            i += 1
            continue

    doc = builder.finalize(logo_path=logo_path)

    # Clean up temp logo if downloaded (never unlink the bundled asset)
    if logo_is_temp and logo_path and os.path.exists(logo_path):
        try:
            os.unlink(logo_path)
        except OSError:
            pass

    # Serialize to bytes
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.read()
