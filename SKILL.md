---
name: doc-converter
description: OpenDocs document conversion microservice. Converts Markdown to branded Word (.docx) and PDF files via a FastAPI HTTP API. Supports configurable branding (colors, fonts, logos) for custom styling.
---

# OpenDocs Document Converter

FastAPI microservice that converts Markdown to professionally styled `.docx` and `.pdf` files with configurable branding.

## Project structure

```
doc-converter/
├── app/
│   ├── __init__.py
│   ├── main.py           # FastAPI endpoints
│   ├── converter.py       # Markdown → DOCX (python-docx)
│   ├── pdf_renderer.py    # Markdown → PDF (WeasyPrint)
│   └── branding.py        # BrandingConfig model (colors, fonts, identity)
├── assets/
│   └── logo.png           # Default OpenDocs logo for doc headers
├── requirements.txt
├── Dockerfile
└── .dockerignore
```

## Running locally

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```

## API endpoints

### `POST /convert/docx`

Convert markdown to a Word document.

```json
{
  "markdown": "# Hello World\n\nThis is a test.",
  "filename": "my-document",
  "landscape": false,
  "branding": null
}
```

Returns: `.docx` file as attachment.

### `POST /convert/pdf`

Convert markdown to a PDF. Internally generates a DOCX first, then prints it to PDF via LibreOffice headless. This guarantees the PDF is visually identical to the DOCX.

```json
{
  "markdown": "# Hello World\n\nThis is a test.",
  "filename": "my-document",
  "landscape": false,
  "branding": null
}
```

Returns: `.pdf` file as attachment.

### `GET /health`

Liveness check. Returns `{ "status": "ok", "version": "0.1.0", "max_workers": 6 }`.

## Custom branding

Pass a `branding` object to override any color, font, or identity value. All fields are optional — omitted fields use OpenDocs defaults.

```json
{
  "markdown": "# Custom branded doc",
  "branding": {
    "heading_color": "#1a73e8",
    "body_color": "#202124",
    "table_header_bg": "#1a73e8",
    "link_color": "#1a73e8",
    "font_main": "Helvetica",
    "company_name": "Acme Corp",
    "company_url": "https://acme.com",
    "company_url_label": "acme.com",
    "footer_subtitle": "Powered by Acme",
    "logo_url": "https://acme.com/logo.png"
  }
}
```

### Color map (OpenDocs defaults)

| Property | Default | Used for |
|----------|---------|----------|
| `heading_color` | `#2E1C5C` | All heading text (H1-H4) |
| `body_color` | `#171717` | Body text, lists, code text, table body |
| `metadata_color` | `#737373` | Metadata lines (small italic at doc top) |
| `link_color` | `#2E1C5C` | Hyperlink text |
| `table_header_bg` | `#2E1C5C` | Table header row background |
| `table_header_fg` | `#FFFFFF` | Table header row text |
| `alt_row_bg` | `#F9F5FF` | Alternating table row background |
| `border_color` | `#E5E5E5` | Table borders, horizontal rule |
| `code_bg` | `#F9F5FF` | Code block background |
| `code_border` | `#E9D7FE` | Code block border |
| `footer_bold_color` | `#2E1C5C` | Company name in footer |
| `footer_normal_color` | `#737373` | Footer subtitle / URL |
| `font_main` | `Arial` | All non-code text |
| `font_code` | `Courier New` | Code blocks and inline code |

### Font options

`font_main` can be any font name. Four are bundled in the Docker image:

| Name | Character |
|------|-----------|
| `Arial` *(default)* | Neutral, universal |
| `Inter` | Modern geometric sans |
| `Lato` | Warm humanist sans |
| `Vollkorn` | Editorial serif (legal / finance / academic) |

### Identity fields

| Property | Default | Description |
|----------|---------|-------------|
| `company_name` | `OpenDocs` | Bold line in footer |
| `company_url` | `https://opendocs.cc` | Footer hyperlink |
| `company_url_label` | `opendocs.cc` | Display text for footer URL |
| `footer_subtitle` | `Made with OpenDocs.cc` | Second line in footer |
| `logo_url` | `null` | Header logo: `null` (no logo), `"bundled:opendocs"` (packaged logo), or `"https://..."` (downloaded at request time) |

## Formulas

Use `formula(expression)` syntax in markdown to render native Word math formulas:

```markdown
formula(E = mc²)
formula(∑(i=1 to n) xi / n)
```

These render as editable OMML math paragraphs in Word. Since PDF output is produced by printing the DOCX through LibreOffice, formulas render correctly in both formats.

## Landscape mode

Set `"landscape": true` in the request body to render in landscape orientation (A4 rotated). Useful for documents with wide tables.

## Docker deployment

```bash
docker build -t opendocs-converter .
docker run -p 8080:8080 -e CONVERT_MAX_WORKERS=6 opendocs-converter
```

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CONVERT_MAX_WORKERS` | `6` | Max concurrent conversions (semaphore limit) |

## Dependencies

- `python-docx` — Word document generation
- `markdown-it-py` — Markdown parsing
- `LibreOffice` — DOCX → PDF conversion (headless, installed via Dockerfile)
- `fastapi` + `uvicorn` — HTTP framework
- `pydantic` — Request validation
- `httpx` — Logo URL downloading
