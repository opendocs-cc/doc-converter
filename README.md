# OpenDocs Document Converter

A FastAPI microservice that converts Markdown to professionally styled **Word (.docx)** and **PDF** documents with configurable branding.

Built for [OpenDocs](https://opendocs.cc) — runs as a standalone service behind the main API.

## How it works

Every conversion goes through the same DOCX pipeline first. PDF is produced by printing the Word document via LibreOffice. This guarantees that DOCX and PDF output are visually identical — same tables, same formulas, same line breaks, same everything.

```
                              ┌──────────┐
                         ┌───→│  .docx   │
                         │    └──────────┘
Markdown → tokens → python-docx
                         │    ┌──────────┐    ┌──────────┐
                         └───→│  .docx   │───→│   .pdf   │
                              └──────────┘    └──────────┘
                              (temp file)   (LibreOffice)
```

### Step by step

1. **Parse** — [markdown-it-py](https://github.com/executablebooks/markdown-it-py) tokenizes the Markdown (CommonMark + tables)
2. **Build** — A `DocxBuilder` walks the token stream and constructs a Word document using [python-docx](https://python-docx.readthedocs.io/), applying heading styles, table formatting, list numbering, code block shading, inline formatting (bold, italic, links, underline), formula rendering, and metadata detection
3. **Brand** — Every color, font, and identity field comes from a `BrandingConfig` passed per-request. Different workspaces can have different styles.
4. **Serialize** — The document is written to bytes. For DOCX requests, these bytes are returned directly.
5. **Print to PDF** — For PDF requests, the DOCX is written to a temp file and converted using `soffice --headless --convert-to pdf` (LibreOffice). The resulting PDF is a faithful print of the Word document.

### Why DOCX-first?

- **100% consistency** — There is one layout engine making all decisions. Tables wrap the same way, headings break at the same points, footers land in the same position. Two independent renderers will always drift.
- **Heading navigation** — Word styles (Title, Heading 2-4) appear in the navigation pane and in PDF bookmarks.
- **Single source of truth** — One converter to maintain, not two. A bug fix to table rendering improves both DOCX and PDF output.

## Running locally

Two paths. Use Python directly for fast iteration, or Docker when you want to run exactly what production runs.

### Option A — Python + venv (fastest dev loop)

```bash
cd doc-converter
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

uvicorn app.main:app --reload --port 8080
```

`--reload` restarts the server on file changes. The `/convert/pdf` endpoint needs LibreOffice on `$PATH` — install once via `brew install --cask libreoffice` (macOS) or `apt install libreoffice-writer libreoffice-calc` (Linux). `/convert/docx` works without it.

Smoke-test:

```bash
curl http://localhost:8080/health
# {"status":"ok","version":"0.1.0","max_workers":6}

curl -X POST http://localhost:8080/convert/docx \
  -H 'Content-Type: application/json' \
  -d '{"markdown": "# Hello\n\nWorld"}' \
  -o out.docx
```

### Option B — Docker (same image as production)

```bash
cd doc-converter
docker build -t opendocs-converter .     # 3-5 min first time; cached afterwards
docker run --rm -p 8080:8080 opendocs-converter
```

Same `curl` commands work. LibreOffice, fonts, and tini are baked into the image — nothing else to install.

### What the Docker image does

- Boots under `tini` as PID 1 (reaps LibreOffice subprocesses, forwards SIGTERM cleanly).
- Runs a single uvicorn worker as a non-root user (`app`, uid 10001).
- All concurrency is gated by `asyncio.Semaphore(CONVERT_MAX_WORKERS)` inside that one process. Override at runtime with `-e CONVERT_MAX_WORKERS=N` if your box is larger or smaller than the 4 vCPU / 8 GB sizing baseline.
- Reports container health by polling `/health` every 30s — `docker ps` and orchestrators pick it up.

## API

### `POST /convert/docx`

Convert Markdown to a Word document.

```bash
curl -X POST http://localhost:8080/convert/docx \
  -H "Content-Type: application/json" \
  -d '{"markdown": "# Hello\n\nWorld", "filename": "hello"}' \
  -o hello.docx
```

### `POST /convert/pdf`

Convert Markdown to a PDF (via DOCX → LibreOffice).

```bash
curl -X POST http://localhost:8080/convert/pdf \
  -H "Content-Type: application/json" \
  -d '{"markdown": "# Hello\n\nWorld", "filename": "hello"}' \
  -o hello.pdf
```

### `GET /health`

Liveness check.

```json
{ "status": "ok", "version": "0.1.0", "max_workers": 6 }
```

### Request body

All fields except `markdown` are optional.

| Field          | Type   | Default      | Description                                                               |
| -------------- | ------ | ------------ | ------------------------------------------------------------------------- |
| `markdown`     | string | _(required)_ | Raw Markdown content                                                      |
| `filename`     | string | `"document"` | Output filename (without extension)                                       |
| `landscape`    | bool   | `false`      | Render in landscape A4                                                    |
| `accent_color` | string | `null`       | Single brand hex (e.g. `"#B91C1C"`). Derives the full palette — see below |
| `branding`     | object | `null`       | Custom branding overrides (see below)                                     |

### Quick custom color (`accent_color`)

For the common Pro-plan case of _"I have one brand color, use it everywhere"_, pass `accent_color` as a single hex instead of filling in a full `branding` object. The converter derives a matching palette from it — headings, hyperlinks, table header fill, and footer brand all snap to the accent, and the alt-row / code backgrounds get a 6% tint of the same hue so the document reads as a wash of brand color rather than a splash on white.

```bash
curl -X POST http://localhost:8080/convert/pdf \
  -H "Content-Type: application/json" \
  -d '{"markdown": "# Branded doc", "accent_color": "#B91C1C"}' \
  -o hello.pdf
```

Under the hood the derivation mixes the accent with white in sRGB channel space: **94% white** for the alt-row / code background (a near-invisible tint) and **78% white** for the code border (visible but soft). Body text, metadata, and borders stay neutral so they work with any accent.

You can combine `accent_color` with `branding` — the accent seeds the palette and any explicit `branding` fields layer on top. Handy for _"derive colors from my brand hex, but override the company name and footer"_:

```json
{
  "markdown": "# Report",
  "accent_color": "#0E7490",
  "branding": {
    "company_name": "Acme Corp",
    "company_url": "https://acme.com",
    "footer_subtitle": "Q2 2026 Results"
  }
}
```

### Custom branding

Pass a `branding` object to override any visual property. Omitted fields use OpenDocs defaults.

```json
{
  "markdown": "# Branded doc",
  "branding": {
    "heading_color": "#1a73e8",
    "body_color": "#202124",
    "table_header_bg": "#1a73e8",
    "font_main": "Helvetica",
    "company_name": "Acme Corp",
    "company_url": "https://acme.com",
    "company_url_label": "acme.com",
    "footer_subtitle": "Confidential",
    "logo_url": "https://acme.com/logo.png"
  }
}
```

#### Color map (defaults)

Defaults match the **OpenDocs house style** — a deep Purple-950 accent (`#2E1C5C`) with Purple-50/200 tints for a "wash of brand color" feel. The accent is intentionally dark so long-form output reads as ink rather than UI.

| Property              | Default   | Controls                                 |
| --------------------- | --------- | ---------------------------------------- |
| `heading_color`       | `#2E1C5C` | H1-H4 heading text                       |
| `body_color`          | `#171717` | Body text, lists, code text, table cells |
| `metadata_color`      | `#737373` | Metadata lines at document top           |
| `link_color`          | `#2E1C5C` | Hyperlink text                           |
| `table_header_bg`     | `#2E1C5C` | Table header row background              |
| `table_header_fg`     | `#FFFFFF` | Table header row text                    |
| `alt_row_bg`          | `#F9F5FF` | Alternating table row shading            |
| `border_color`        | `#E5E5E5` | Table borders, horizontal rules          |
| `code_bg`             | `#F9F5FF` | Code block background                    |
| `code_border`         | `#E9D7FE` | Code block border                        |
| `footer_bold_color`   | `#2E1C5C` | Company name in footer                   |
| `footer_normal_color` | `#737373` | Footer subtitle and URL                  |

#### Font and identity fields

| Property            | Default               | Description                          |
| ------------------- | --------------------- | ------------------------------------ |
| `font_main`         | `Arial`               | Primary font                         |
| `font_code`         | `Courier New`         | Monospace font                       |
| `company_name`      | `OpenDocs`            | Footer bold line                     |
| `company_url`       | `https://opendocs.cc` | Footer link target                   |
| `company_url_label` | `opendocs.cc`         | Footer link display text             |
| `footer_subtitle`   | `Made with OpenDocs`  | Footer second line                   |
| `logo_url`          | `null`                | Header logo. Three modes (see below) |

#### `logo_url` modes

| Value                | Behavior                                                          | Typical plan                                           |
| -------------------- | ----------------------------------------------------------------- | ------------------------------------------------------ |
| `null` (omitted)     | No logo in the page header                                        | Pro — unbranded document                               |
| `"bundled:opendocs"` | Use the packaged OpenDocs logo shipped with the image             | Free — OpenDocs branding is locked on                  |
| `"https://..."`      | Download the image at request time and embed it (PNG / JPG / GIF) | Pro — customer-supplied logo on Cloudflare / S3 / etc. |

External URLs are fetched with a 10 s timeout and a descriptive `User-Agent`. If the download fails the document still renders — just without the logo.

#### `font_main` options

Ten fonts are bundled in the Docker image and can be selected by name. Any other font name is accepted too, but if it isn't installed LibreOffice substitutes a similar face when producing PDF.

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
{ "branding": { "font_main": "Vollkorn" } }
```

`font_code` stays `Courier New` by default; change it per-request if you want a different monospace for code blocks. When `font_main` is `JetBrains Mono`, code blocks use it too.

## Pre-built themes

The service ships with 10 tuned themes in `app/themes.py`. Each theme is a full `BrandingConfig` — accent color, tinted alt-row / code backgrounds, fictional company identity, and footer subtitle — so you can preview the same content under different personas.

| Theme      | Accent                | Example identity                                                                          |
| ---------- | --------------------- | ----------------------------------------------------------------------------------------- |
| `opendocs` | `#2E1C5C` Deep purple | OpenDocs _(Free-plan default — bundled logo + "Made with OpenDocs" footer are locked on)_ |
| `charcoal` | `#1D2939` Slate       | Greystone Consulting                                                                      |
| `green`    | `#054F31` Forest      | Verdant Analytics                                                                         |
| `blue`     | `#194185` Royal       | Northwave Systems                                                                         |
| `indigo`   | `#2D3282` Midnight    | Helios Capital                                                                            |
| `violet`   | `#3E1C96` Imperial    | Prism Research                                                                            |
| `fuchsia`  | `#6F1574` Berry       | Bloom Health                                                                              |
| `red`      | `#7A271A` Crimson     | Ember Security                                                                            |
| `orange`   | `#772917` Mahogany    | Forge Industrial                                                                          |
| `navy`     | `#14306E` Oxford navy | Atlas Advisory — the "safe" blue for legal / finance / government                         |

All accents are drawn from the **800/900-weight** of their hue family (custom "950" for the OpenDocs purple), paired with 50/200 tints for alt-row and code surfaces. The deeper weight keeps long-form reading calm — vibrant 500–700 shades read as UI, a 900 reads as ink.

Two helpers in `app/themes.py` wire the themes into plan-aware defaults:

```python
from app.themes import free_plan_brand, pro_plan_brand

# Free plan — OpenDocs logo + footer are non-negotiable
brand = free_plan_brand()

# Pro plan — start from a theme, layer overrides on top
brand = pro_plan_brand(
    "indigo",
    company_name="Acme Corp",
    company_url="https://acme.com",
    logo_url="https://acme.com/logo.png",
)
```

`pro_plan_brand()` strips the bundled OpenDocs logo by default, so Pro users are never silently branded as OpenDocs. Pass `logo_url=None` to ship without a logo, or `logo_url="https://..."` to embed a customer logo at request time.

## Concurrency

The service uses an `asyncio.Semaphore` to limit concurrent conversions. Each request runs the CPU-bound conversion in a thread pool executor, but no more than `CONVERT_MAX_WORKERS` conversions run simultaneously. This keeps memory bounded on small VPS instances.

| Environment variable  | Default | Description                |
| --------------------- | ------- | -------------------------- |
| `CONVERT_MAX_WORKERS` | `6`     | Max concurrent conversions |

On a 4 vCPU / 8 GB box with 6 workers, expect roughly 80-100 DOCX conversions per minute. PDF is slower because each conversion spawns a LibreOffice process — expect roughly 30-50 PDFs per minute depending on document complexity.

## Tech stack

- **[FastAPI](https://fastapi.tiangolo.com/)** — async HTTP framework
- **[python-docx](https://python-docx.readthedocs.io/)** — Word document generation
- **[markdown-it-py](https://github.com/executablebooks/markdown-it-py)** — Markdown parsing (CommonMark + tables)
- **[LibreOffice](https://www.libreoffice.org/)** — DOCX → PDF conversion (headless mode)
- **[Pydantic](https://docs.pydantic.dev/)** — request validation and branding config
- **[httpx](https://www.python-httpx.org/)** — HTTP client for logo downloads

## License

Closed source. This service is part of the OpenDocs platform infrastructure.
