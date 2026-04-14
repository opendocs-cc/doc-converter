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

- **Formula rendering** — `formula(E = mc²)` renders as native OMML math in Word. LibreOffice understands OMML and prints it correctly to PDF. A separate HTML/CSS pipeline would not.
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

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `markdown` | string | *(required)* | Raw Markdown content |
| `filename` | string | `"document"` | Output filename (without extension) |
| `landscape` | bool | `false` | Render in landscape A4 |
| `branding` | object | `null` | Custom branding overrides (see below) |

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

| Property | Default | Controls |
|----------|---------|----------|
| `heading_color` | `#7F56D9` | H1-H4 heading text |
| `body_color` | `#171717` | Body text, lists, code text, table cells |
| `metadata_color` | `#737373` | Metadata lines at document top |
| `link_color` | `#7F56D9` | Hyperlink text |
| `table_header_bg` | `#7F56D9` | Table header row background |
| `table_header_fg` | `#FFFFFF` | Table header row text |
| `alt_row_bg` | `#FAFAFA` | Alternating table row shading |
| `border_color` | `#E5E5E5` | Table borders, horizontal rules |
| `code_bg` | `#FAFAFA` | Code block background |
| `code_border` | `#E5E5E5` | Code block border |
| `footer_bold_color` | `#7F56D9` | Company name in footer |
| `footer_normal_color` | `#737373` | Footer subtitle and URL |

#### Font and identity fields

| Property | Default | Description |
|----------|---------|-------------|
| `font_main` | `Arial` | Primary font |
| `font_code` | `Courier New` | Monospace font |
| `company_name` | `OpenDocs` | Footer bold line |
| `company_url` | `https://opendocs.cc` | Footer link target |
| `company_url_label` | `opendocs.cc` | Footer link display text |
| `footer_subtitle` | `Made with OpenDocs.cc` | Footer second line |
| `logo_url` | `null` | Header logo URL (falls back to bundled OpenDocs logo) |

## Concurrency

The service uses an `asyncio.Semaphore` to limit concurrent conversions. Each request runs the CPU-bound conversion in a thread pool executor, but no more than `CONVERT_MAX_WORKERS` conversions run simultaneously. This keeps memory bounded on small VPS instances.

| Environment variable | Default | Description |
|---------------------|---------|-------------|
| `CONVERT_MAX_WORKERS` | `6` | Max concurrent conversions |

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
