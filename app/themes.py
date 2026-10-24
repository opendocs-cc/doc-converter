"""
Pre-built color themes for document conversion.

Each theme is a BrandingConfig with a tuned palette derived from a single
primary accent color.  The accent drives headings, links, table headers,
and the footer brand line.  Supporting colors (alt-row backgrounds, code
surfaces, borders) are adjusted to complement the accent.

Palette convention: every accent is the **deepest usable** shade of its
hue family (Untitled UI 800 / 900, or a custom "950" where 900 still
reads as vibrant).  Supporting tints (``alt_row_bg`` / ``code_bg`` /
``code_border``) use the same family's 50 and 200 weights so the
document reads as "a wash of brand color" rather than "a highlight
painted onto white."  Dark accents keep long-form reading calm and
hold up on white paper.

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
        font_code="JetBrains Mono",
        company_name=name,
        company_url=url,
        company_url_label=url_label,
        footer_subtitle=subtitle,
        logo_url=logo_url,
    )


# ─── Theme definitions ─────────────────────────────────────────────────────

THEMES: dict[str, BrandingConfig] = {
    # ── Purple 950 — OpenDocs default (Free plan: logo + footer locked) ──
    "opendocs": _theme(
        name="OpenDocs",
        accent="#2E1C5C",
        url="https://opendocs.cc",
        url_label="opendocs.cc",
        subtitle="Made with OpenDocs",
        alt_row="#F9F5FF",
        code_bg="#F9F5FF",
        code_border="#E9D7FE",
        logo_url="bundled:opendocs",
    ),

    # ── Gray 800 — understated corporate slate ─────────────────────────
    "charcoal": _theme(
        name="Greystone Consulting",
        accent="#1D2939",
        url="https://greystone.io",
        url_label="greystone.io",
        subtitle="Confidential",
        alt_row="#F9FAFB",
        code_bg="#F9FAFB",
        border="#D0D5DD",
        code_border="#EAECF0",
    ),

    # ── Success 900 — forest / sustainability ──────────────────────────
    "green": _theme(
        name="Verdant Analytics",
        accent="#054F31",
        url="https://verdant.eco",
        url_label="verdant.eco",
        subtitle="Sustainable Intelligence",
        alt_row="#ECFDF3",
        code_bg="#ECFDF3",
        code_border="#A6F4C5",
    ),

    # ── Blue 900 — classic royal blue, deeper ──────────────────────────
    "blue": _theme(
        name="Northwave Systems",
        accent="#194185",
        url="https://northwave.dev",
        url_label="northwave.dev",
        subtitle="Engineering Excellence",
        alt_row="#EFF4FF",
        code_bg="#EFF4FF",
        code_border="#B2CCFF",
    ),

    # ── Indigo 900 — midnight blue-purple ──────────────────────────────
    "indigo": _theme(
        name="Helios Capital",
        accent="#2D3282",
        url="https://helioscap.com",
        url_label="helioscap.com",
        subtitle="Private & Confidential",
        alt_row="#EEF4FF",
        code_bg="#EEF4FF",
        code_border="#C7D7FE",
    ),

    # ── Violet 900 — imperial purple ───────────────────────────────────
    "violet": _theme(
        name="Prism Research",
        accent="#3E1C96",
        url="https://prismresearch.org",
        url_label="prismresearch.org",
        subtitle="Advancing Discovery",
        alt_row="#F4F3FF",
        code_bg="#F4F3FF",
        code_border="#D9D6FE",
    ),

    # ── Fuchsia 900 — berry, serious ───────────────────────────────────
    "fuchsia": _theme(
        name="Bloom Health",
        accent="#6F1574",
        url="https://bloomhealth.co",
        url_label="bloomhealth.co",
        subtitle="Patient-First Innovation",
        alt_row="#FDF4FF",
        code_bg="#FDF4FF",
        code_border="#F6D0FE",
    ),

    # ── Error 900 — crimson, restrained ────────────────────────────────
    "red": _theme(
        name="Ember Security",
        accent="#7A271A",
        url="https://embersec.io",
        url_label="embersec.io",
        subtitle="Threat Intelligence Report",
        alt_row="#FEF3F2",
        code_bg="#FEF3F2",
        code_border="#FECDCA",
    ),

    # ── Orange-dark 900 — mahogany / terracotta ────────────────────────
    "orange": _theme(
        name="Forge Industrial",
        accent="#772917",
        url="https://forgeindustrial.com",
        url_label="forgeindustrial.com",
        subtitle="Built to Last",
        alt_row="#FEF6EE",
        code_bg="#FEF6EE",
        code_border="#F9DBAF",
    ),

    # ── Navy — deep Oxford blue, the "safe" document color ─────────────
    # Typical for legal memos, government reports, finance whitepapers
    # and other contexts where conservatism matters more than brand
    # expression.  Reads calm and authoritative on white.
    "navy": _theme(
        name="Atlas Advisory",
        accent="#14306E",
        url="https://atlasadvisory.com",
        url_label="atlasadvisory.com",
        subtitle="Strategic Counsel",
        alt_row="#EFF4FF",
        code_bg="#EFF4FF",
        code_border="#B2CCFF",
    ),
}


# ─── Custom-accent palette derivation ─────────────────────────────────────

def _hex_to_rgb(s: str) -> tuple[int, int, int]:
    """Parse ``#RRGGBB`` or ``RRGGBB`` into ``(r, g, b)``.  Raises
    ``ValueError`` if the input isn't a valid 6-char hex."""
    h = s.strip().lstrip("#")
    if len(h) != 6 or any(c not in "0123456789abcdefABCDEF" for c in h):
        raise ValueError(f"Invalid hex color: {s!r}")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02X}{g:02X}{b:02X}"


def _mix_with_white(accent: str, white_pct: float) -> str:
    """Return ``accent`` linearly mixed with white.

    ``white_pct=0.94`` means 94% white, 6% accent — a near-white wash
    suitable for alt-row striping.  ``white_pct=0.78`` produces a more
    visible tint suitable for code-block borders.  The mix is done in
    sRGB channel space, which is a simplification (perceptually
    linear mixing would use OKLCH), but is plenty accurate at these
    high white percentages where the result is dominated by white.
    """
    r, g, b = _hex_to_rgb(accent)
    new_r = round(r * (1 - white_pct) + 255 * white_pct)
    new_g = round(g * (1 - white_pct) + 255 * white_pct)
    new_b = round(b * (1 - white_pct) + 255 * white_pct)
    return _rgb_to_hex(new_r, new_g, new_b)


def brand_from_accent(
    accent: str,
    *,
    company_name: str = "",
    company_url: str = "",
    company_url_label: str = "",
    footer_subtitle: str | None = None,
    logo_url: str | None = None,
    font_main: str = "Arial",
    font_code: str = "JetBrains Mono",
) -> BrandingConfig:
    """Derive a full BrandingConfig from a single accent hex.

    The accent drives the four locations that need to read as "the
    brand color" on the page: heading text, hyperlinks, table header
    fill, and the footer brand line.  Supporting tints (alt-row / code
    backgrounds and code border) are mixed from the accent + white so
    each theme feels like a wash of its own hue rather than a highlight
    painted onto white.  Body text, metadata, and borders stay neutral.

    This is the Pro-plan "custom color" entry point: the customer
    passes a single hex value (their brand color), and the converter
    tailors every surface of the document around it.  Identity fields
    (company_name, logo_url, footer_subtitle) can be layered on via
    keyword args; they default to the un-branded state so callers
    who only care about color don't inherit anything surprising.
    """
    # Normalise input — this also validates the hex up-front so a bad
    # value fails fast rather than producing a half-built BrandingConfig.
    r, g, b = _hex_to_rgb(accent)
    accent = _rgb_to_hex(r, g, b)

    tint_50 = _mix_with_white(accent, 0.94)   # Near-white wash
    tint_200 = _mix_with_white(accent, 0.78)  # Visible-but-soft border

    return BrandingConfig(
        heading_color=accent,
        body_color="#171717",
        metadata_color="#737373",
        link_color=accent,
        table_header_bg=accent,
        table_header_fg="#FFFFFF",
        alt_row_bg=tint_50,
        border_color="#E5E5E5",
        code_bg=tint_50,
        code_border=tint_200,
        footer_bold_color=accent,
        footer_normal_color="#737373",
        font_main=font_main,
        font_code=font_code,
        company_name=company_name,
        company_url=company_url,
        company_url_label=company_url_label,
        footer_subtitle=footer_subtitle,
        logo_url=logo_url,
    )


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
