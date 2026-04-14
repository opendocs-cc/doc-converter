"""
OpenDocs Document Conversion Service

FastAPI microservice that converts Markdown to DOCX and PDF with
configurable branding.

Endpoints:
    POST /convert/docx   → returns a .docx file
    POST /convert/pdf    → returns a .pdf file
    GET  /health         → liveness check
"""

from __future__ import annotations

import os
import time
import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .branding import BrandingConfig, OPENDOCS_BRAND
from .converter import convert_md_to_docx
from .pdf_renderer import convert_md_to_pdf

# ---------------------------------------------------------------------------
# Concurrency limiter — keeps memory bounded on a 4-vCPU / 8 GB box.
# Default: 6 workers (configurable via CONVERT_MAX_WORKERS env var).
# ---------------------------------------------------------------------------
MAX_WORKERS = int(os.getenv("CONVERT_MAX_WORKERS", "6"))
_semaphore: asyncio.Semaphore | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _semaphore
    _semaphore = asyncio.Semaphore(MAX_WORKERS)
    yield


app = FastAPI(
    title="OpenDocs Converter",
    version="0.1.0",
    description="Markdown → DOCX / PDF conversion with configurable branding.",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class ConvertRequest(BaseModel):
    """Payload for both /convert/docx and /convert/pdf."""

    markdown: str = Field(
        ...,
        description="Raw markdown content to convert.",
        min_length=1,
    )
    filename: str = Field(
        default="document",
        description="Base filename (without extension) for the output.",
    )
    landscape: bool = Field(
        default=False,
        description="Render in landscape orientation.",
    )
    page_break_before: Optional[int] = Field(
        default=None,
        description=(
            "Insert a page break before headings at this level or above. "
            "E.g. 2 = break before every H2 (and H1). null = no breaks."
        ),
        ge=1,
        le=6,
    )
    skip_first_break: bool = Field(
        default=True,
        description=(
            "When true, the very first heading that would trigger a page "
            "break is skipped — avoids a blank first page."
        ),
    )
    branding: Optional[BrandingConfig] = Field(
        default=None,
        description="Custom branding overrides. Omit for OpenDocs defaults.",
    )


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"
    max_workers: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(max_workers=MAX_WORKERS)


@app.post("/convert/docx")
async def convert_docx(req: ConvertRequest):
    """Convert markdown to a Word document (.docx)."""
    brand = req.branding or OPENDOCS_BRAND

    async with _semaphore:
        loop = asyncio.get_running_loop()
        try:
            docx_bytes = await loop.run_in_executor(
                None,
                lambda: convert_md_to_docx(
                    req.markdown,
                    brand=brand,
                    landscape=req.landscape,
                    page_break_before=req.page_break_before,
                    skip_first_break=req.skip_first_break,
                ),
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    safe_name = req.filename.replace('"', "")
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}.docx"',
        },
    )


@app.post("/convert/pdf")
async def convert_pdf(req: ConvertRequest):
    """Convert markdown to a PDF document."""
    brand = req.branding or OPENDOCS_BRAND

    async with _semaphore:
        loop = asyncio.get_running_loop()
        try:
            pdf_bytes = await loop.run_in_executor(
                None,
                lambda: convert_md_to_pdf(
                    req.markdown,
                    brand=brand,
                    landscape=req.landscape,
                    page_break_before=req.page_break_before,
                    skip_first_break=req.skip_first_break,
                ),
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    safe_name = req.filename.replace('"', "")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}.pdf"',
        },
    )
