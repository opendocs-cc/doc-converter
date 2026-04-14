"""
Branding configuration for document conversion.

Defines the full color/font/identity palette used by the DOCX and PDF
converters.  Every value has an OpenDocs default but can be overridden
per-request (Team tier custom branding).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class BrandingConfig(BaseModel):
    """All visual knobs for a converted document."""

    # ── Accent / structural colors ──────────────────────────────────────
    heading_color: str = Field(
        default="#53389E",
        description="Heading text (H1-H4)",
    )
    body_color: str = Field(
        default="#171717",
        description="Body paragraphs, list items, code text, table body",
    )
    metadata_color: str = Field(
        default="#737373",
        description="Metadata lines (small italic text at doc top)",
    )
    link_color: str = Field(
        default="#53389E",
        description="Hyperlink text",
    )

    # ── Table colors ────────────────────────────────────────────────────
    table_header_bg: str = Field(
        default="#53389E",
        description="Table header row background",
    )
    table_header_fg: str = Field(
        default="#FFFFFF",
        description="Table header row text",
    )
    alt_row_bg: str = Field(
        default="#FAFAFA",
        description="Alternating table row background (zebra stripe)",
    )
    border_color: str = Field(
        default="#E5E5E5",
        description="Table borders, horizontal rule",
    )

    # ── Code block colors ───────────────────────────────────────────────
    code_bg: str = Field(
        default="#FAFAFA",
        description="Code block background shading",
    )
    code_border: str = Field(
        default="#E5E5E5",
        description="Code block border",
    )

    # ── Footer colors ───────────────────────────────────────────────────
    footer_bold_color: str = Field(
        default="#53389E",
        description="Company/brand name in footer (bold line)",
    )
    footer_normal_color: str = Field(
        default="#737373",
        description="Footer subtitle / URL text",
    )

    # ── Fonts ───────────────────────────────────────────────────────────
    font_main: str = Field(
        default="Arial",
        description="Primary font for all non-code text",
    )
    font_code: str = Field(
        default="Courier New",
        description="Monospace font for code blocks and inline code",
    )

    # ── Identity ────────────────────────────────────────────────────────
    company_name: str = Field(
        default="OpenDocs",
        description="Shown in footer bold line",
    )
    company_url: str = Field(
        default="https://opendocs.cc",
        description="Hyperlinked in footer",
    )
    company_url_label: str = Field(
        default="opendocs.cc",
        description="Display text for the footer URL",
    )
    footer_subtitle: str | None = Field(
        default="Made with OpenDocs.cc",
        description=(
            "Second line in footer (below the company name).  Set to None "
            "to hide the subtitle.  The full footer is suppressed only when "
            "company_name is empty, footer_subtitle is None, and "
            "company_url is empty."
        ),
    )
    logo_url: str | None = Field(
        default=None,
        description=(
            "Logo shown top-right of every page header.  Three modes:\n"
            "  * None                 — no logo (Pro plan default).\n"
            "  * 'bundled:opendocs'   — use the packaged OpenDocs logo "
            "(Free plan).\n"
            "  * 'https://...'        — download the image from this URL "
            "(Pro plan with custom logo; PNG/JPG/GIF supported)."
        ),
    )

    # ── Helpers ─────────────────────────────────────────────────────────

    def hex_strip(self, color: str) -> str:
        """Return a bare 6-char hex string (no '#')."""
        return color.lstrip("#").upper()


# Convenience singleton for the OpenDocs house style.
OPENDOCS_BRAND = BrandingConfig()
