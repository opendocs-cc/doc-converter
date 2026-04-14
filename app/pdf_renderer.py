"""
Markdown-to-PDF renderer via LibreOffice.

Pipeline: Markdown → DOCX (python-docx) → PDF (LibreOffice headless)

This ensures 100% visual consistency between DOCX and PDF output.
The PDF is a faithful print of the Word document — same tables, same
formula rendering, same line breaks, same everything.
"""

from __future__ import annotations

import os
import subprocess
import tempfile

from .branding import BrandingConfig, OPENDOCS_BRAND
from .converter import convert_md_to_docx


def convert_md_to_pdf(
    md_text: str,
    *,
    brand: BrandingConfig | None = None,
    landscape: bool = False,
    page_break_before: int | None = None,
    skip_first_break: bool = True,
) -> bytes:
    """Convert markdown to PDF by going through DOCX first.

    Pipeline:
        1. Convert markdown → DOCX bytes (using the same converter)
        2. Write DOCX to a temp file
        3. Run LibreOffice headless to convert DOCX → PDF
        4. Read and return the PDF bytes

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
    skip_first_break : bool
        Skip the page break on the very first matching heading.

    Returns
    -------
    bytes
        The PDF file content.

    Raises
    ------
    RuntimeError
        If LibreOffice conversion fails.
    """
    if brand is None:
        brand = OPENDOCS_BRAND

    # Step 1: Generate the DOCX using the exact same converter
    docx_bytes = convert_md_to_docx(
        md_text,
        brand=brand,
        landscape=landscape,
        page_break_before=page_break_before,
        skip_first_break=skip_first_break,
    )

    # Step 2: Write DOCX to a temp file
    tmp_dir = tempfile.mkdtemp(prefix="opendocs_convert_")
    docx_path = os.path.join(tmp_dir, "document.docx")
    pdf_path = os.path.join(tmp_dir, "document.pdf")

    try:
        with open(docx_path, "wb") as f:
            f.write(docx_bytes)

        # Step 3: Convert DOCX → PDF via LibreOffice headless
        result = subprocess.run(
            [
                "soffice",
                "--headless",
                "--norestore",
                "--convert-to", "pdf",
                "--outdir", tmp_dir,
                docx_path,
            ],
            capture_output=True,
            text=True,
            timeout=60,  # 60 second timeout per conversion
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"LibreOffice conversion failed (exit {result.returncode}): "
                f"{result.stderr.strip()}"
            )

        if not os.path.exists(pdf_path):
            raise RuntimeError(
                "LibreOffice ran but no PDF was produced. "
                f"stdout: {result.stdout.strip()}, stderr: {result.stderr.strip()}"
            )

        # Step 4: Read the PDF
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()

        return pdf_bytes

    finally:
        # Clean up temp files
        for path in (docx_path, pdf_path):
            try:
                os.unlink(path)
            except OSError:
                pass
        try:
            os.rmdir(tmp_dir)
        except OSError:
            pass
