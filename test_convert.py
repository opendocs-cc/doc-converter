#!/usr/bin/env python3
"""
Test script — converts the .md file in testing-docs/md/ once per theme,
producing both DOCX and PDF for each.  Generates four variants:
  - default (no page breaks, no logo)
  - with page_break_before=2, skip_first_break=True
  - Free plan (OpenDocs branding + bundled logo, locked)
  - Pro plan (custom logo via external URL + no logo)
"""

import os
import sys
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.converter import convert_md_to_docx
from app.themes import THEMES, free_plan_brand, pro_plan_brand

MD_DIR = os.path.join(os.path.dirname(__file__), "testing-docs", "md")
EXPORT_DIR = os.path.join(os.path.dirname(__file__), "testing-docs", "exports")


def has_libreoffice() -> bool:
    try:
        subprocess.run(["soffice", "--version"], capture_output=True, timeout=10)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def convert_docx_to_pdf(docx_path: str, output_dir: str) -> str | None:
    result = subprocess.run(
        ["soffice", "--headless", "--norestore", "--convert-to", "pdf",
         "--outdir", output_dir, docx_path],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        print(f"    LibreOffice error: {result.stderr.strip()}")
        return None
    pdf_name = os.path.splitext(os.path.basename(docx_path))[0] + ".pdf"
    pdf_path = os.path.join(output_dir, pdf_name)
    return pdf_path if os.path.exists(pdf_path) else None


def convert_one(md_text, brand, out_name, lo_available, *,
                page_break_before=None, skip_first_break=True):
    """Convert a single md to DOCX (+ PDF), return summary string."""
    docx_path = os.path.join(EXPORT_DIR, f"{out_name}.docx")
    try:
        docx_bytes = convert_md_to_docx(
            md_text, brand=brand,
            page_break_before=page_break_before,
            skip_first_break=skip_first_break,
        )
        with open(docx_path, "wb") as f:
            f.write(docx_bytes)
        docx_kb = len(docx_bytes) / 1024
    except Exception as e:
        return f"  DOCX ERROR: {e}"

    pdf_kb_str = "—"
    if lo_available:
        try:
            pdf_path = convert_docx_to_pdf(docx_path, EXPORT_DIR)
            if pdf_path:
                pdf_kb_str = f"{os.path.getsize(pdf_path) / 1024:.0f} KB"
        except Exception:
            pdf_kb_str = "ERR"

    return f"{docx_kb:>5.0f} KB  {pdf_kb_str:>8}"


def main():
    os.makedirs(EXPORT_DIR, exist_ok=True)

    md_files = [f for f in os.listdir(MD_DIR) if f.endswith(".md")]
    if not md_files:
        print(f"No .md files found in {MD_DIR}")
        return

    md_file = md_files[0]
    md_path = os.path.join(MD_DIR, md_file)
    base = os.path.splitext(md_file)[0]

    with open(md_path, "r", encoding="utf-8") as f:
        md_text = f.read()

    lo_available = has_libreoffice()
    print(f"LibreOffice: {'yes' if lo_available else 'no'}")
    print(f"Source: {md_file}")
    print(f"Themes: {len(THEMES)}\n")

    # --- Pass 1: no page breaks ---
    print("═══ No page breaks ═══")
    print(f"  {'Theme':<12} {'Company':<28} {'DOCX':>8}  {'PDF':>8}")
    print(f"  {'-'*60}")
    for name, brand in THEMES.items():
        result = convert_one(md_text, brand, f"{base}_{name}", lo_available)
        print(f"  {name:<12} {brand.company_name:<28} {result}")

    # --- Pass 2: page break before H2, skip first ---
    print(f"\n═══ Page break before H2 (skip first) ═══")
    print(f"  {'Theme':<12} {'Company':<28} {'DOCX':>8}  {'PDF':>8}")
    print(f"  {'-'*60}")
    for name, brand in THEMES.items():
        result = convert_one(
            md_text, brand, f"{base}_{name}_h2break", lo_available,
            page_break_before=2, skip_first_break=True,
        )
        print(f"  {name:<12} {brand.company_name:<28} {result}")

    # --- Pass 3: Free vs. Pro plan logo handling ---
    print(f"\n═══ Logo handling (Free vs. Pro) ═══")
    print(f"  {'Variant':<22} {'Logo':<30} {'DOCX':>8}  {'PDF':>8}")
    print(f"  {'-'*70}")

    # Free plan — bundled OpenDocs logo is locked on
    free_brand = free_plan_brand()
    result = convert_one(md_text, free_brand, f"{base}_free_plan", lo_available)
    print(f"  {'free_plan':<22} {'bundled:opendocs':<30} {result}")

    # Pro plan — no logo at all (default)
    pro_no_logo = pro_plan_brand("blue")
    result = convert_one(md_text, pro_no_logo, f"{base}_pro_no_logo", lo_available)
    print(f"  {'pro_no_logo (blue)':<22} {'(none)':<30} {result}")

    # Pro plan — logo from an external URL.  Uses a public GitHub avatar
    # to exercise the download path against a realistic CDN.  If the
    # network is down the converter degrades to "no logo" silently.
    external_logo = (
        "https://avatars.githubusercontent.com/u/80113084"
        "?s=400&u=5b8ddcd14ccbf3bfd2e8a3b32a526670246f2e0d&v=4"
    )
    pro_custom = pro_plan_brand("green", logo_url=external_logo)
    result = convert_one(md_text, pro_custom, f"{base}_pro_custom_logo", lo_available)
    short_url = external_logo[:27] + "…" if len(external_logo) > 28 else external_logo
    print(f"  {'pro_custom (green)':<22} {short_url:<30} {result}")

    # Pro plan — fully unbranded: no logo, no footer
    pro_blank = pro_plan_brand(
        "charcoal",
        logo_url=None,
        company_name="",
        company_url="",
        footer_subtitle=None,
    )
    result = convert_one(md_text, pro_blank, f"{base}_pro_unbranded", lo_available)
    print(f"  {'pro_unbranded':<22} {'(none — no footer)':<30} {result}")

    print(f"\nDone. All exports in: {EXPORT_DIR}")


if __name__ == "__main__":
    main()
