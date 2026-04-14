# OpenDocs Converter — Themes & Color Map

## Available themes

11 pre-built themes are defined in `app/themes.py`. Each is a full `BrandingConfig` built from a single primary accent color, with complementary surface and border tones.

All accents are drawn from the **Untitled UI 700-weight** palette (the OpenDocs default is Purple-900, slightly deeper). The 700 weight is deliberate: it reads as coloured ink rather than a UI highlight, so headings and link runs don't feel "neon" on a white page.

| Theme | Accent | Company Name | Vibe |
|-------|:------:|--------------|------|
| `opendocs` | `#42307D` | OpenDocs | Deep purple — the default |
| `charcoal` | `#344054` | Greystone Consulting | Slate, corporate, understated |
| `green` | `#027A48` | Verdant Analytics | Forest, sustainability, growth |
| `blue` | `#175CD3` | Northwave Systems | Royal blue, trust, enterprise |
| `indigo` | `#3538CD` | Helios Capital | Deep indigo, finance, premium |
| `violet` | `#5925DC` | Prism Research | Electric violet, creative, research |
| `fuchsia` | `#9F1AB1` | Bloom Health | Berry, healthcare, bold |
| `red` | `#B42318` | Ember Security | Crimson, urgency, security |
| `orange` | `#B93815` | Forge Industrial | Rust, construction, warmth |
| `teal` | `#107569` | Tidewater Clinical | Deep teal, clinical, tech |
| `amber` | `#B54708` | Aurum Legal | Gold, legal, premium |

## Full color breakdown per theme

Each theme sets all 12 color properties. The primary accent drives 4 of them (heading, link, table header bg, footer bold). The rest are tuned to complement, and the surface tints are drawn from the 50 and 200 weights of the same hue family.

### opendocs (default)

| Property | Value | Role |
|----------|:-----:|------|
| `heading_color` | `#42307D` | Heading text |
| `link_color` | `#42307D` | Hyperlinks |
| `table_header_bg` | `#42307D` | Table header fill |
| `footer_bold_color` | `#42307D` | Footer brand name |
| `body_color` | `#171717` | Body text |
| `metadata_color` | `#737373` | Metadata |
| `footer_normal_color` | `#737373` | Footer subtitle |
| `table_header_fg` | `#FFFFFF` | Table header text |
| `alt_row_bg` | `#F9F5FF` | Zebra stripe (purple-50) |
| `code_bg` | `#F9F5FF` | Code background (purple-50) |
| `border_color` | `#E5E5E5` | Borders |
| `code_border` | `#E9D7FE` | Code border (purple-200) |

### charcoal

| Property | Value | Role |
|----------|:-----:|------|
| `heading_color` | `#344054` | Heading text |
| `link_color` | `#344054` | Hyperlinks |
| `table_header_bg` | `#344054` | Table header fill |
| `footer_bold_color` | `#344054` | Footer brand name |
| `alt_row_bg` | `#F9FAFB` | Zebra stripe (gray-50) |
| `code_bg` | `#F9FAFB` | Code background (gray-50) |
| `border_color` | `#D0D5DD` | Borders (gray-300) |
| `code_border` | `#EAECF0` | Code border (gray-200) |

### green

| Property | Value | Role |
|----------|:-----:|------|
| `heading_color` | `#027A48` | Heading text |
| `link_color` | `#027A48` | Hyperlinks |
| `table_header_bg` | `#027A48` | Table header fill |
| `footer_bold_color` | `#027A48` | Footer brand name |
| `alt_row_bg` | `#ECFDF3` | Zebra stripe (success-50) |
| `code_bg` | `#ECFDF3` | Code background (success-50) |
| `code_border` | `#A6F4C5` | Code border (success-200) |

### blue

| Property | Value | Role |
|----------|:-----:|------|
| `heading_color` | `#175CD3` | Heading text |
| `link_color` | `#175CD3` | Hyperlinks |
| `table_header_bg` | `#175CD3` | Table header fill |
| `footer_bold_color` | `#175CD3` | Footer brand name |
| `alt_row_bg` | `#EFF4FF` | Zebra stripe (blue-50) |
| `code_bg` | `#EFF4FF` | Code background (blue-50) |
| `code_border` | `#B2CCFF` | Code border (blue-200) |

### indigo

| Property | Value | Role |
|----------|:-----:|------|
| `heading_color` | `#3538CD` | Heading text |
| `link_color` | `#3538CD` | Hyperlinks |
| `table_header_bg` | `#3538CD` | Table header fill |
| `footer_bold_color` | `#3538CD` | Footer brand name |
| `alt_row_bg` | `#EEF4FF` | Zebra stripe (indigo-50) |
| `code_bg` | `#EEF4FF` | Code background (indigo-50) |
| `code_border` | `#C7D7FE` | Code border (indigo-200) |

### violet

| Property | Value | Role |
|----------|:-----:|------|
| `heading_color` | `#5925DC` | Heading text |
| `link_color` | `#5925DC` | Hyperlinks |
| `table_header_bg` | `#5925DC` | Table header fill |
| `footer_bold_color` | `#5925DC` | Footer brand name |
| `alt_row_bg` | `#F4F3FF` | Zebra stripe (violet-50) |
| `code_bg` | `#F4F3FF` | Code background (violet-50) |
| `code_border` | `#D9D6FE` | Code border (violet-200) |

### fuchsia

| Property | Value | Role |
|----------|:-----:|------|
| `heading_color` | `#9F1AB1` | Heading text |
| `link_color` | `#9F1AB1` | Hyperlinks |
| `table_header_bg` | `#9F1AB1` | Table header fill |
| `footer_bold_color` | `#9F1AB1` | Footer brand name |
| `alt_row_bg` | `#FDF4FF` | Zebra stripe (fuchsia-50) |
| `code_bg` | `#FDF4FF` | Code background (fuchsia-50) |
| `code_border` | `#F6D0FE` | Code border (fuchsia-200) |

### red

| Property | Value | Role |
|----------|:-----:|------|
| `heading_color` | `#B42318` | Heading text |
| `link_color` | `#B42318` | Hyperlinks |
| `table_header_bg` | `#B42318` | Table header fill |
| `footer_bold_color` | `#B42318` | Footer brand name |
| `alt_row_bg` | `#FEF3F2` | Zebra stripe (error-50) |
| `code_bg` | `#FEF3F2` | Code background (error-50) |
| `code_border` | `#FECDCA` | Code border (error-200) |

### orange

| Property | Value | Role |
|----------|:-----:|------|
| `heading_color` | `#B93815` | Heading text |
| `link_color` | `#B93815` | Hyperlinks |
| `table_header_bg` | `#B93815` | Table header fill |
| `footer_bold_color` | `#B93815` | Footer brand name |
| `alt_row_bg` | `#FEF6EE` | Zebra stripe (orange-50) |
| `code_bg` | `#FEF6EE` | Code background (orange-50) |
| `code_border` | `#F9DBAF` | Code border (orange-200) |

### teal

| Property | Value | Role |
|----------|:-----:|------|
| `heading_color` | `#107569` | Heading text |
| `link_color` | `#107569` | Hyperlinks |
| `table_header_bg` | `#107569` | Table header fill |
| `footer_bold_color` | `#107569` | Footer brand name |
| `alt_row_bg` | `#F0FDF9` | Zebra stripe (teal-50) |
| `code_bg` | `#F0FDF9` | Code background (teal-50) |
| `code_border` | `#99F6E0` | Code border (teal-200) |

### amber

| Property | Value | Role |
|----------|:-----:|------|
| `heading_color` | `#B54708` | Heading text |
| `link_color` | `#B54708` | Hyperlinks |
| `table_header_bg` | `#B54708` | Table header fill |
| `footer_bold_color` | `#B54708` | Footer brand name |
| `alt_row_bg` | `#FFFAEB` | Zebra stripe (warning-50) |
| `code_bg` | `#FFFAEB` | Code background (warning-50) |
| `code_border` | `#FEDF89` | Code border (warning-200) |

## Shared neutral values

These are the same across all themes (only listed once above for opendocs):

| Property | Value | Role |
|----------|:-----:|------|
| `body_color` | `#171717` | Body text |
| `metadata_color` | `#737373` | Metadata text |
| `table_header_fg` | `#FFFFFF` | Table header text |
| `footer_normal_color` | `#737373` | Footer subtitle |
| `font_main` | `Arial` | Primary font |
| `font_code` | `Courier New` | Code font |

## How to use a theme via the API

Pass the theme's branding config in the request body:

```json
{
  "markdown": "# My Document\n\nContent here.",
  "branding": {
    "heading_color": "#2563EB",
    "link_color": "#2563EB",
    "table_header_bg": "#2563EB",
    "footer_bold_color": "#2563EB",
    "alt_row_bg": "#EFF6FF",
    "code_bg": "#EFF6FF",
    "code_border": "#BFDBFE",
    "company_name": "Northwave Systems",
    "company_url": "https://northwave.dev",
    "company_url_label": "northwave.dev",
    "footer_subtitle": "Engineering Excellence"
  }
}
```

Or from Python:

```python
from app.themes import THEMES
from app.converter import convert_md_to_docx

brand = THEMES["blue"]
docx_bytes = convert_md_to_docx(markdown_text, brand=brand)
```

## Design principles

- **Primary accent** — one color controls headings, links, table headers, and footer brand. Changing this single value rebrands the document.
- **Surface tones** — alt-row and code backgrounds use the 50-weight of the accent's Tailwind palette (very faint tint). Just enough warmth to feel cohesive.
- **Code borders** — use the 200-weight of the accent palette. Visible but not loud.
- **Neutrals stay neutral** — body text, metadata, borders, and fonts are the same across all themes. They're designed to work with any accent.

## Logo handling (Free vs. Pro plan)

The `logo_url` field on `BrandingConfig` drives the top-right header image. It has **three** modes:

| Value | Behavior | Intended plan |
|-------|----------|---------------|
| `None` | No header logo — plain page. | Pro (no custom logo yet) |
| `"bundled:opendocs"` | Renders the packaged OpenDocs logo from `assets/logo.png`. | **Free** (locked) |
| `"https://..."` / `"http://..."` | Downloads the image at that URL (PNG/JPG/GIF) into a temp file and embeds it. The temp file is deleted after the document is built. | Pro (custom logo hosted on Cloudflare, S3, etc.) |

### Footer handling

The footer has three editable pieces: `company_name` (bold line), `footer_subtitle` (grey line below the name), and `company_url` (hyperlink at end of the subtitle line). The rules:

- If all three are empty/`None`, the footer is suppressed entirely.
- On the **Free plan**, the footer always reads **“OpenDocs — Made with OpenDocs.cc – opendocs.cc”** and is not overridable.
- On the **Pro plan**, every field is freely editable, including a fully blank footer.

### Plan-aware helpers

Two convenience helpers in `app/themes.py` produce correctly-configured brands:

```python
from app.themes import free_plan_brand, pro_plan_brand

# Free plan — always OpenDocs branding, always bundled logo
brand = free_plan_brand()

# Pro plan — start from the 'blue' theme and attach a hosted logo
brand = pro_plan_brand(
    "blue",
    logo_url="https://cdn.northwave.dev/logo.png",
)

# Pro plan — fully unbranded document (no logo, no footer)
brand = pro_plan_brand(
    "charcoal",
    logo_url=None,
    company_name="",
    company_url="",
    footer_subtitle=None,
)
```

`pro_plan_brand()` automatically strips the `"bundled:opendocs"` sentinel from the base theme — a Pro user is never locked into OpenDocs branding.

### API request examples

Free plan (branding is ignored; always defaults to OpenDocs Free):

```json
{
  "markdown": "# Hello"
}
```

Pro plan with custom logo from S3:

```json
{
  "markdown": "# Hello",
  "branding": {
    "heading_color": "#2563EB",
    "link_color": "#2563EB",
    "table_header_bg": "#2563EB",
    "footer_bold_color": "#2563EB",
    "alt_row_bg": "#EFF6FF",
    "code_bg": "#EFF6FF",
    "code_border": "#BFDBFE",
    "company_name": "Northwave Systems",
    "company_url": "https://northwave.dev",
    "company_url_label": "northwave.dev",
    "footer_subtitle": "Engineering Excellence",
    "logo_url": "https://northwave-assets.s3.amazonaws.com/logo.png"
  }
}
```

Pro plan with **no** logo and **no** footer:

```json
{
  "markdown": "# Hello",
  "branding": {
    "company_name": "",
    "company_url": "",
    "footer_subtitle": null,
    "logo_url": null
  }
}
```
