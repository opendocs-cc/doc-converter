# OpenDocs Converter — Themes & Color Map

## Available themes

10 pre-built themes are defined in `app/themes.py`. Each is a full `BrandingConfig` built from a single primary accent color, with complementary surface and border tones.

All accents are drawn from the deepest usable shade of their hue family — **Untitled UI 800 / 900**, with a custom "950" for OpenDocs purple. The deeper weight is deliberate: vibrant 500–700 shades read as a UI highlight on a white page, whereas a 900 reads as ink. Long-form docs stay calm and print well.

| Theme      |  Accent   | Company Name         | Vibe                                                   |
| ---------- | :-------: | -------------------- | ------------------------------------------------------ |
| `opendocs` | `#2E1C5C` | OpenDocs             | Deep purple — the default                              |
| `charcoal` | `#1D2939` | Greystone Consulting | Slate, corporate, understated                          |
| `green`    | `#054F31` | Verdant Analytics    | Forest, sustainability, growth                         |
| `blue`     | `#194185` | Northwave Systems    | Royal blue, trust, enterprise                          |
| `indigo`   | `#2D3282` | Helios Capital       | Midnight indigo, finance, premium                      |
| `violet`   | `#3E1C96` | Prism Research       | Imperial violet, creative, research                    |
| `fuchsia`  | `#6F1574` | Bloom Health         | Berry, healthcare, bold                                |
| `red`      | `#7A271A` | Ember Security       | Crimson, urgency, security                             |
| `orange`   | `#772917` | Forge Industrial     | Mahogany, construction, warmth                         |
| `navy`     | `#14306E` | Atlas Advisory       | Oxford navy — legal / finance / government "safe" blue |

## Full color breakdown per theme

Each theme sets all 12 color properties. The primary accent drives 4 of them (heading, link, table header bg, footer bold). The rest are tuned to complement, and the surface tints are drawn from the 50 and 200 weights of the same hue family.

### opendocs (default)

| Property              |   Value   | Role                        |
| --------------------- | :-------: | --------------------------- |
| `heading_color`       | `#2E1C5C` | Heading text                |
| `link_color`          | `#2E1C5C` | Hyperlinks                  |
| `table_header_bg`     | `#2E1C5C` | Table header fill           |
| `footer_bold_color`   | `#2E1C5C` | Footer brand name           |
| `body_color`          | `#171717` | Body text                   |
| `metadata_color`      | `#737373` | Metadata                    |
| `footer_normal_color` | `#737373` | Footer subtitle             |
| `table_header_fg`     | `#FFFFFF` | Table header text           |
| `alt_row_bg`          | `#F9F5FF` | Zebra stripe (purple-50)    |
| `code_bg`             | `#F9F5FF` | Code background (purple-50) |
| `border_color`        | `#E5E5E5` | Borders                     |
| `code_border`         | `#E9D7FE` | Code border (purple-200)    |

### charcoal

| Property            |   Value   | Role                      |
| ------------------- | :-------: | ------------------------- |
| `heading_color`     | `#1D2939` | Heading text              |
| `link_color`        | `#1D2939` | Hyperlinks                |
| `table_header_bg`   | `#1D2939` | Table header fill         |
| `footer_bold_color` | `#1D2939` | Footer brand name         |
| `alt_row_bg`        | `#F9FAFB` | Zebra stripe (gray-50)    |
| `code_bg`           | `#F9FAFB` | Code background (gray-50) |
| `border_color`      | `#D0D5DD` | Borders (gray-300)        |
| `code_border`       | `#EAECF0` | Code border (gray-200)    |

### green

| Property            |   Value   | Role                         |
| ------------------- | :-------: | ---------------------------- |
| `heading_color`     | `#054F31` | Heading text                 |
| `link_color`        | `#054F31` | Hyperlinks                   |
| `table_header_bg`   | `#054F31` | Table header fill            |
| `footer_bold_color` | `#054F31` | Footer brand name            |
| `alt_row_bg`        | `#ECFDF3` | Zebra stripe (success-50)    |
| `code_bg`           | `#ECFDF3` | Code background (success-50) |
| `code_border`       | `#A6F4C5` | Code border (success-200)    |

### blue

| Property            |   Value   | Role                      |
| ------------------- | :-------: | ------------------------- |
| `heading_color`     | `#194185` | Heading text              |
| `link_color`        | `#194185` | Hyperlinks                |
| `table_header_bg`   | `#194185` | Table header fill         |
| `footer_bold_color` | `#194185` | Footer brand name         |
| `alt_row_bg`        | `#EFF4FF` | Zebra stripe (blue-50)    |
| `code_bg`           | `#EFF4FF` | Code background (blue-50) |
| `code_border`       | `#B2CCFF` | Code border (blue-200)    |

### indigo

| Property            |   Value   | Role                        |
| ------------------- | :-------: | --------------------------- |
| `heading_color`     | `#2D3282` | Heading text                |
| `link_color`        | `#2D3282` | Hyperlinks                  |
| `table_header_bg`   | `#2D3282` | Table header fill           |
| `footer_bold_color` | `#2D3282` | Footer brand name           |
| `alt_row_bg`        | `#EEF4FF` | Zebra stripe (indigo-50)    |
| `code_bg`           | `#EEF4FF` | Code background (indigo-50) |
| `code_border`       | `#C7D7FE` | Code border (indigo-200)    |

### violet

| Property            |   Value   | Role                        |
| ------------------- | :-------: | --------------------------- |
| `heading_color`     | `#3E1C96` | Heading text                |
| `link_color`        | `#3E1C96` | Hyperlinks                  |
| `table_header_bg`   | `#3E1C96` | Table header fill           |
| `footer_bold_color` | `#3E1C96` | Footer brand name           |
| `alt_row_bg`        | `#F4F3FF` | Zebra stripe (violet-50)    |
| `code_bg`           | `#F4F3FF` | Code background (violet-50) |
| `code_border`       | `#D9D6FE` | Code border (violet-200)    |

### fuchsia

| Property            |   Value   | Role                         |
| ------------------- | :-------: | ---------------------------- |
| `heading_color`     | `#6F1574` | Heading text                 |
| `link_color`        | `#6F1574` | Hyperlinks                   |
| `table_header_bg`   | `#6F1574` | Table header fill            |
| `footer_bold_color` | `#6F1574` | Footer brand name            |
| `alt_row_bg`        | `#FDF4FF` | Zebra stripe (fuchsia-50)    |
| `code_bg`           | `#FDF4FF` | Code background (fuchsia-50) |
| `code_border`       | `#F6D0FE` | Code border (fuchsia-200)    |

### red

| Property            |   Value   | Role                       |
| ------------------- | :-------: | -------------------------- |
| `heading_color`     | `#7A271A` | Heading text               |
| `link_color`        | `#7A271A` | Hyperlinks                 |
| `table_header_bg`   | `#7A271A` | Table header fill          |
| `footer_bold_color` | `#7A271A` | Footer brand name          |
| `alt_row_bg`        | `#FEF3F2` | Zebra stripe (error-50)    |
| `code_bg`           | `#FEF3F2` | Code background (error-50) |
| `code_border`       | `#FECDCA` | Code border (error-200)    |

### orange

| Property            |   Value   | Role                        |
| ------------------- | :-------: | --------------------------- |
| `heading_color`     | `#772917` | Heading text                |
| `link_color`        | `#772917` | Hyperlinks                  |
| `table_header_bg`   | `#772917` | Table header fill           |
| `footer_bold_color` | `#772917` | Footer brand name           |
| `alt_row_bg`        | `#FEF6EE` | Zebra stripe (orange-50)    |
| `code_bg`           | `#FEF6EE` | Code background (orange-50) |
| `code_border`       | `#F9DBAF` | Code border (orange-200)    |

### navy

The "safe" color — an Oxford-style deep navy for formal documents where conservatism matters more than brand expression. Legal memos, finance whitepapers, government reports.

| Property            |   Value   | Role                      |
| ------------------- | :-------: | ------------------------- |
| `heading_color`     | `#14306E` | Heading text              |
| `link_color`        | `#14306E` | Hyperlinks                |
| `table_header_bg`   | `#14306E` | Table header fill         |
| `footer_bold_color` | `#14306E` | Footer brand name         |
| `alt_row_bg`        | `#EFF4FF` | Zebra stripe (blue-50)    |
| `code_bg`           | `#EFF4FF` | Code background (blue-50) |
| `code_border`       | `#B2CCFF` | Code border (blue-200)    |

## Shared neutral values

These are the same across all themes (only listed once above for opendocs):

| Property              |     Value     | Role              |
| --------------------- | :-----------: | ----------------- |
| `body_color`          |   `#171717`   | Body text         |
| `metadata_color`      |   `#737373`   | Metadata text     |
| `table_header_fg`     |   `#FFFFFF`   | Table header text |
| `footer_normal_color` |   `#737373`   | Footer subtitle   |
| `font_main`           |    `Arial`    | Primary font      |
| `font_code`           | `JetBrains Mono` | Code font      |

## Font options

The Docker image ships with ten curated `font_main` options. Pass any of these by name; other fonts work too but may render with substitution.

| Name                | Package                 | Character              | Good for                              |
| ------------------- | ----------------------- | ---------------------- | ------------------------------------- |
| `Arial` _(default)_ | `fonts-liberation`      | Neutral, universal     | Everything; the safe default          |
| `Inter`             | `fonts-inter`           | Modern geometric sans  | Product specs, design docs            |
| `IBM Plex Sans`     | `fonts-ibm-plex`        | Corporate tech sans    | Board updates, memos, policies        |
| `Lato`              | `fonts-lato`            | Warm humanist sans     | Handbooks, onboarding, how-tos        |
| `Roboto`            | `fonts-roboto-unhinted` | Familiar neutral sans  | Reports and docs of any kind          |
| `Manrope`           | `fonts-manrope`         | Modern grotesque       | Launches, one-pagers, announcements   |
| `Merriweather`      | static TTF download     | Screen-optimized serif | Whitepapers, studies, research        |
| `Vollkorn`          | `fonts-vollkorn`        | Editorial serif        | Essays and long reports               |
| `EB Garamond`       | static TTF download     | Classic book serif     | Proposals, letters, formal reports    |
| `JetBrains Mono`    | `fonts-jetbrains-mono`  | Monospace              | Changelogs, runbooks, incident reviews |

```json
{
  "markdown": "# My Report",
  "branding": {
    "font_main": "Vollkorn"
  }
}
```

`font_code` is `JetBrains Mono` by default (installed in the image). Change it per-request if you want a different monospace for code. When `font_main` is itself `JetBrains Mono`, code uses it too.

## How to use a theme via the API

Pass the theme's branding config in the request body:

```json
{
  "markdown": "# My Document\n\nContent here.",
  "branding": {
    "heading_color": "#194185",
    "link_color": "#194185",
    "table_header_bg": "#194185",
    "footer_bold_color": "#194185",
    "alt_row_bg": "#EFF4FF",
    "code_bg": "#EFF4FF",
    "code_border": "#B2CCFF",
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

## Custom accent colors (`brand_from_accent`)

Pro-plan callers who just want to supply one brand hex can skip `branding` entirely and pass `accent_color` on the request. The converter then derives a full palette from that single value — headings, hyperlinks, table header fill, footer brand, and both tint surfaces (alt-row and code backgrounds, plus the code border).

The derivation mixes the accent with white in sRGB channel space:

| Surface                                                               |          Mix           | Typical look                       |
| --------------------------------------------------------------------- | :--------------------: | ---------------------------------- |
| `heading_color`, `link_color`, `table_header_bg`, `footer_bold_color` |      100% accent       | The four "brand" touchpoints       |
| `alt_row_bg`, `code_bg`                                               | 94% white + 6% accent  | Near-invisible hue wash            |
| `code_border`                                                         | 78% white + 22% accent | Visible but soft                   |
| `body_color`, `metadata_color`, `border_color`, `footer_normal_color` |  neutral (unchanged)   | Always works, regardless of accent |

This matches the Untitled UI 50 / 200 convention that the pre-built themes follow by hand, but generates the tints algorithmically so any brand color gets a consistent palette.

### API shortcut

```json
{
  "markdown": "# Quarterly report",
  "accent_color": "#B91C1C"
}
```

Combine with `branding` to layer on overrides — the accent seeds the palette, `branding` fields win on top:

```json
{
  "markdown": "# Quarterly report",
  "accent_color": "#0E7490",
  "branding": {
    "company_name": "Acme Corp",
    "company_url": "https://acme.com",
    "footer_subtitle": "Q2 2026 Results"
  }
}
```

### Python helper

```python
from app.themes import brand_from_accent
from app.converter import convert_md_to_docx

brand = brand_from_accent(
    "#4338CA",
    company_name="Helios Capital",
    company_url="https://helioscap.com",
    company_url_label="helioscap.com",
    footer_subtitle="Private & Confidential",
    logo_url="https://cdn.helioscap.com/logo.png",
)
docx_bytes = convert_md_to_docx(markdown_text, brand=brand)
```

`brand_from_accent()` validates the hex up-front (raising `ValueError` on a malformed input) and normalizes it to `#RRGGBB` before building the palette, so downstream renderers always see a canonical form.

## Design principles

- **Primary accent** — one color controls headings, links, table headers, and footer brand. Changing this single value rebrands the document.
- **Deep accents** — 800/900-weight keeps long-form reading calm. Vibrant mid-weights look like UI, not ink.
- **Surface tones** — alt-row and code backgrounds use the 50-weight of the accent's family (very faint tint). Just enough warmth to feel cohesive.
- **Code borders** — use the 200-weight. Visible but not loud.
- **Neutrals stay neutral** — body text, metadata, and borders are the same across all themes. They're designed to work with any accent.

## Logo handling (Free vs. Pro plan)

The `logo_url` field on `BrandingConfig` drives the top-right header image. It has **three** modes:

| Value                            | Behavior                                                                                                                            | Intended plan                                    |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------ |
| `None`                           | No header logo — plain page.                                                                                                        | Pro (no custom logo yet)                         |
| `"bundled:opendocs"`             | Renders the packaged OpenDocs logo from `assets/logo.png`.                                                                          | **Free** (locked)                                |
| `"https://..."` / `"http://..."` | Downloads the image at that URL (PNG/JPG/GIF) into a temp file and embeds it. The temp file is deleted after the document is built. | Pro (custom logo hosted on Cloudflare, S3, etc.) |

### Footer handling

The footer has three editable pieces: `company_name` (bold line), `footer_subtitle` (grey line below the name), and `company_url` (hyperlink at end of the subtitle line). The rules:

- If all three are empty/`None`, the footer is suppressed entirely.
- On the **Free plan**, the footer always reads **“OpenDocs — Made with OpenDocs – opendocs.cc”** and is not overridable.
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
    "heading_color": "#194185",
    "link_color": "#194185",
    "table_header_bg": "#194185",
    "footer_bold_color": "#194185",
    "alt_row_bg": "#EFF4FF",
    "code_bg": "#EFF4FF",
    "code_border": "#B2CCFF",
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
