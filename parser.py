"""Turn any downloaded USPTO document into clean text, picking the right parser.

Usage:  .venv/bin/python parser.py <file or folder> [more ...] [--out DIR]
  XML, or a tar archive of XML (USPTO "XML" downloads, even when named .xml)
                                      -> xml_parser.py -> DIR/text-<documentId>.txt
  PDF (text layer or scanned)         -> pdf_parser.py -> DIR/pdf-<name>.txt
  folder                              -> every file inside it
DIR defaults to ./out. Anything else (e.g. MS_WORD .docx) is reported and skipped.

From another script (e.g. run.py):
  import parser
  paths = parser.to_text("example/data/18909470/files/2025-07-09_CLM_MCWHN4RGX24X232.xml")
"""
import sys
import tarfile
from pathlib import Path

import pdf_parser
import xml_parser


def file_type(path):
    """'pdf', 'xml' (plain XML or a tar of XML), or None. Sniffs the content, not the name."""
    with open(path, "rb") as f:
        head = f.read(512)
    if head.startswith(b"%PDF"):
        return "pdf"
    if tarfile.is_tarfile(path) or head.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"<"):
        return "xml"
    return None


def to_text(path, out_dir="out"):
    """Convert one file (or every file in a folder). Returns the list of text files written."""
    path = Path(path)
    if path.is_dir():
        return [out for child in sorted(path.iterdir()) if child.is_file()
                for out in to_text(child, out_dir)]
    kind = file_type(path)
    if kind == "pdf":
        return [pdf_parser.convert(path, out_dir)]
    if kind == "xml":
        return [xml_parser.convert(label, inner, data, out_dir)
                for label, inner, data in xml_parser.xml_sources(path)]
    print(f"{path}\n  skipped: not a PDF or XML file")
    return []


if __name__ == "__main__":
    args, out_dir = sys.argv[1:], "out"
    if "--out" in args:
        i = args.index("--out")
        out_dir, args = args[i + 1], args[:i] + args[i + 2:]
    if not args:
        sys.exit(__doc__)
    for arg in args:
        to_text(arg, out_dir)
