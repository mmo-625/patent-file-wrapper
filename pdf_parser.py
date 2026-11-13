"""Extract text from USPTO PDFs, using OCR for scanned pages.

Usage:  .venv/bin/python pdf_parser.py <file.pdf> [more files ...]
  Writes ./out/pdf-<name>.txt for each PDF (name = file name without .pdf,
  e.g. MGI2EARDX134X26), with a "--- page N (text|ocr) ---" line before each page.

Each page is handled on its own:
  - pages with a real text layer (e.g. uploaded response PDFs) -> pypdf
  - scanned pages (most USPTO PDFs, e.g. interview summaries)  -> Tesseract OCR
USPTO mailing cover sheets (PTOL-90A) are skipped, and the stock instructions at the
bottom of interview summary forms are cut. Page numbers in the output stay the original ones.

Needs: pip install pypdf pytesseract pdf2image   (in .venv)
       brew install tesseract poppler
"""
import re
import sys
import time
from pathlib import Path

import pytesseract
from pdf2image import convert_from_path
from pypdf import PdfReader

OCR_DPI = 300          # 300 dpi gives clean OCR on USPTO scans (~2 s per page)
MIN_TEXT_CHARS = 20    # fewer non-space characters than this = treat page as scanned

# USPTO cover sheet (form PTOL-90A: mailing address + e-mail notice) -> skip the page.
COVER_PAGE = re.compile(r"PTOL-90A|Please find below and/or attached an Office communication",
                        re.IGNORECASE)
# Stock instructions at the bottom of a form -> drop from here to the end of the page.
# Interview summary (PTOL-413): the MPEP 713.04 recordation instructions.
FORM_BOILERPLATE = re.compile(r"Applicant is reminded that a complete written statement",
                              re.IGNORECASE)


def page_text(reader, path, number):
    """Return (method, text) for one page (1-based), using OCR only when needed."""
    text = reader.pages[number - 1].extract_text() or ""
    if len(re.sub(r"\s", "", text)) >= MIN_TEXT_CHARS:
        return "text", text
    # No usable text layer: render just this page to an image and OCR it.
    image = convert_from_path(path, dpi=OCR_DPI, first_page=number, last_page=number,
                              grayscale=True)[0]
    return "ocr", pytesseract.image_to_string(image)


def tidy(text):
    """Trim trailing spaces and collapse runs of blank lines."""
    lines = [line.rstrip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def convert(path, out_dir="out"):
    """Extract one PDF, write <out_dir>/pdf-<name>.txt, print a summary, return the path."""
    start = time.time()
    reader = PdfReader(path)
    blocks, methods, empty, covers = [], [], [], []
    for number in range(1, len(reader.pages) + 1):
        method, text = page_text(reader, path, number)
        if COVER_PAGE.search(text):  # mailing cover sheet: no substance
            covers.append(number)
            continue
        boilerplate = FORM_BOILERPLATE.search(text)
        if boilerplate:
            text = text[:boilerplate.start()]
        text = tidy(text)
        methods.append(method)
        if not text:
            empty.append(number)
        blocks.append(f"--- page {number} ({method}) ---\n{text}")

    out_path = Path(out_dir) / f"pdf-{Path(path).stem}.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(f"Source: {path}\nPages: {len(blocks)}\n\n" + "\n\n".join(blocks) + "\n",
                        encoding="utf-8")

    print(f"{path}\n  -> {out_path}: {len(blocks)} pages "
          f"({methods.count('text')} text layer, {methods.count('ocr')} OCR), "
          f"{time.time() - start:.1f}s")
    if covers:
        print(f"  cover pages skipped: {', '.join(map(str, covers))}")
    if empty:  # e.g. blank pages, or a scan too faint to read
        print(f"  pages with no text found: {', '.join(map(str, empty))}")
    return out_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for arg in sys.argv[1:]:
        convert(Path(arg))
