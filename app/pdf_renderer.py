"""
Markdown-to-PDF renderer via LibreOffice.

Pipeline: Markdown → DOCX (python-docx) → PDF (LibreOffice headless)

This ensures 100% visual consistency between DOCX and PDF output.
The PDF is a faithful print of the Word document — same tables, same
formula rendering, same line breaks, same everything.

The service converts through warm LibreOffice workers (libreoffice.py);
this function starts LibreOffice for one document, for scripts and tests.
"""

from __future__ import annotations

from .branding import BrandingConfig
from .converter import convert_md_to_docx
from .libreoffice import convert_oneshot


def convert_md_to_pdf(
    md_text: str,
    *,
    brand: BrandingConfig | None = None,
    landscape: bool = False,
    page_break_before: int | None = None,
    skip_first_break: bool = True,
    signature_fields: bool = False,
) -> bytes:
    """Convert markdown to PDF by going through DOCX first.

    Parameters are as for ``converter.convert_md_to_docx``. Raises
    ``libreoffice.ConversionError`` if LibreOffice fails.
    """
    docx_bytes = convert_md_to_docx(
        md_text,
        brand=brand,
        landscape=landscape,
        page_break_before=page_break_before,
        skip_first_break=skip_first_break,
        signature_fields=signature_fields,
    )
    return convert_oneshot(docx_bytes)
