"""
Pre-built color themes for document conversion.

Each theme is a BrandingConfig with a tuned palette derived from a single
primary accent color.  The accent drives headings, links, table headers,
and the footer brand line.  Supporting colors (alt-row backgrounds, code
surfaces, borders) are adjusted to complement the accent.

Logo handling:
    * The default 'opendocs' theme represents the **Free plan** — it
      always carries the bundled OpenDocs logo and the "Made with
      OpenDocs.cc" footer.  These are non-negotiable on the Free tier.
    * All other themes default to *no logo* (``logo_url=None``) so that
      Pro-plan callers can optionally set ``logo_url="https://..."`` to
      insert their own logo from an external URL (Cloudflare / S3 / etc).
"""

from __future__ import annotations

from .branding import BrandingConfig


def _theme(
    *,
    name: str,
    accent: str,
    url: str,
    url_label: str,
    subtitle: str | None = None,
    alt_row: str = "#FAFAFA",
    code_bg: str = "#FAFAFA",
    border: str = "#E5E5E5",
    code_border: str = "#E5E5E5",
    logo_url: str | None = None,
) -> BrandingConfig:
    """Helper to build a theme from an accent color."""
    return BrandingConfig(
        heading_color=accent,
        body_color="#171717",
        metadata_color="#737373",
        link_color=accent,
        table_header_bg=accent,
        table_header_fg="#FFFFFF",
        alt_row_bg=alt_row,
        border_color=border,
        code_bg=code_bg,
        code_border=code_border,
        footer_bold_color=accent,
        footer_normal_color="#737373",
        font_main="Arial",
        font_code="Courier New",
        company_name=name,
        company_url=url,
        company_url_label=url_label,
        footer_subtitle=subtitle,
        logo_url=logo_url,
    )


# ─── Theme definitions ─────────────────────────────────────────────────────

#
# Palette convention: every accent is the Untitled-UI **700-weight** equivalent
# of its hue family.  Supporting tints (``alt_row_bg`` / ``code_bg`` / ``code_border``)
# use the same family's 50 and 200 weights so the document reads as "a
# wash of brand color" rather than "a highlight painted onto white."
#
THEMES: dict[str, BrandingConfig] = {
    # ── Purple 900 — OpenDocs default (Free plan: logo + footer locked) ──
    "opendocs": _theme(
        name="OpenDocs",
        accent="#42307D",
        url="https://opendocs.cc",
        url_label="opendocs.cc",
        subtitle="Made with OpenDocs.cc",
        alt_row="#F9F5FF",
        code_bg="#F9F5FF",
        code_border="#E9D7FE",
        logo_url="bundled:opendocs",
    ),

    # ── Gray 700 — understated corporate slate ─────────────────────────
    "charcoal": _theme(
        name="Greystone Consulting",
        accent="#344054",
        url="https://greystone.io",
        url_label="greystone.io",
        subtitle="Confidential",
        alt_row="#F9FAFB",
        code_bg="#F9FAFB",
        border="#D0D5DD",
        code_border="#EAECF0",
    ),

    # ── Success 700 — forest / sustainability ──────────────────────────
    "green": _theme(
        name="Verdant Analytics",
        accent="#027A48",
        url="https://verdant.eco",
        url_label="verdant.eco",
        subtitle="Sustainable Intelligence",
        alt_row="#ECFDF3",
        code_bg="#ECFDF3",
        code_border="#A6F4C5",
    ),

    # ── Blue-dark 700 — classic royal blue ─────────────────────────────
    "blue": _theme(
        name="Northwave Systems",
        accent="#175CD3",
        url="https://northwave.dev",
        url_label="northwave.dev",
        subtitle="Engineering Excellence",
        alt_row="#EFF4FF",
        code_bg="#EFF4FF",
        code_border="#B2CCFF",
    ),

    # ── Indigo 700 — deep blue-purple, premium feel ────────────────────
    "indigo": _theme(
        name="Helios Capital",
        accent="#3538CD",
        url="https://helioscap.com",
        url_label="helioscap.com",
        subtitle="Private & Confidential",
        alt_row="#EEF4FF",
        code_bg="#EEF4FF",
        code_border="#C7D7FE",
    ),

    # ── Violet 700 — electric but grounded ─────────────────────────────
    "violet": _theme(
        name="Prism Research",
        accent="#5925DC",
        url="https://prismresearch.org",
        url_label="prismresearch.org",
        subtitle="Advancing Discovery",
        alt_row="#F4F3FF",
        code_bg="#F4F3FF",
        code_border="#D9D6FE",
    ),

    # ── Fuchsia 700 — berry, not neon ──────────────────────────────────
    "fuchsia": _theme(
        name="Bloom Health",
        accent="#9F1AB1",
        url="https://bloomhealth.co",
        url_label="bloomhealth.co",
        subtitle="Patient-First Innovation",
        alt_row="#FDF4FF",
        code_bg="#FDF4FF",
        code_border="#F6D0FE",
    ),

    # ── Error 700 — crimson, serious ───────────────────────────────────
    "red": _theme(
        name="Ember Security",
        accent="#B42318",
        url="https://embersec.io",
        url_label="embersec.io",
        subtitle="Threat Intelligence Report",
        alt_row="#FEF3F2",
        code_bg="#FEF3F2",
        code_border="#FECDCA",
    ),

    # ── Orange-dark 700 — rust / terracotta, warm ──────────────────────
    "orange": _theme(
        name="Forge Industrial",
        accent="#B93815",
        url="https://forgeindustrial.com",
        url_label="forgeindustrial.com",
        subtitle="Built to Last",
        alt_row="#FEF6EE",
        code_bg="#FEF6EE",
        code_border="#F9DBAF",
    ),

    # ── Teal 700 — deep teal for tech / medical / legal ────────────────
    "teal": _theme(
        name="Tidewater Clinical",
        accent="#107569",
        url="https://tidewaterclinical.com",
        url_label="tidewaterclinical.com",
        subtitle="Evidence-Based Care",
        alt_row="#F0FDF9",
        code_bg="#F0FDF9",
        code_border="#99F6E0",
    ),

    # ── Warning 700 — amber / gold, premium finance & legal ────────────
    "amber": _theme(
        name="Aurum Legal",
        accent="#B54708",
        url="https://aurumlegal.com",
        url_label="aurumlegal.com",
        subtitle="Counsel Since 1987",
        alt_row="#FFFAEB",
        code_bg="#FFFAEB",
        code_border="#FEDF89",
    ),
}


# ─── Plan-aware helpers ────────────────────────────────────────────────────

# Sentinel so callers can pass an explicit ``None`` to clear a field
# (e.g. ``footer_subtitle=None``) and still be distinguishable from
# "caller didn't override this".
_UNSET: object = object()


def free_plan_brand() -> BrandingConfig:
    """Branding for a Free-plan user — OpenDocs logo + footer are locked."""
    return THEMES["opendocs"].model_copy()


def pro_plan_brand(
    base: BrandingConfig | str = "opendocs",
    *,
    logo_url: str | None | object = _UNSET,
    company_name: str | object = _UNSET,
    company_url: str | object = _UNSET,
    company_url_label: str | object = _UNSET,
    footer_subtitle: str | None | object = _UNSET,
) -> BrandingConfig:
    """Branding for a Pro-plan user.

    Starts from a named theme (or a caller-supplied ``BrandingConfig``)
    and applies optional overrides.  ``logo_url`` may be ``None`` (no
    logo) or an ``http(s)://...`` URL (downloaded and embedded).  The
    ``"bundled:opendocs"`` sentinel is only meaningful on the Free plan
    and is stripped here.

    To ship a truly unbranded document, pass ``company_name=""``,
    ``company_url=""``, and ``footer_subtitle=None``.
    """
    if isinstance(base, str):
        if base not in THEMES:
            raise KeyError(f"Unknown theme: {base!r}")
        brand = THEMES[base].model_copy()
    else:
        brand = base.model_copy()

    # Strip the bundled OpenDocs logo — Pro users are never locked in.
    # Override with the caller's value if they passed one.
    if logo_url is _UNSET:
        if brand.logo_url == "bundled:opendocs":
            brand.logo_url = None
    else:
        brand.logo_url = logo_url  # type: ignore[assignment]

    if company_name is not _UNSET:
        brand.company_name = company_name  # type: ignore[assignment]
    if company_url is not _UNSET:
        brand.company_url = company_url  # type: ignore[assignment]
    if company_url_label is not _UNSET:
        brand.company_url_label = company_url_label  # type: ignore[assignment]
    if footer_subtitle is not _UNSET:
        brand.footer_subtitle = footer_subtitle  # type: ignore[assignment]

    return brand
