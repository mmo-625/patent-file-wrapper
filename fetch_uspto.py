#!/usr/bin/env python3
"""Pull one patent application from the USPTO Open Data Portal API.

Saves, under --out (default example/data/<application number>):
  wrapper.json    raw application wrapper (metadata, events, attorney, ...)
  documents.json  raw document list
  files/          downloaded documents (XML unzipped into a folder per document)
  manifest.json   one tidy row per document, with the local path of what was saved

Usage:
  export USPTO_API_KEY=your-key
  python fetch_uspto.py 18909470
  python fetch_uspto.py 18909470 --list-only
  python fetch_uspto.py 18909470 --codes CLM REM CTNF --formats XML MS_WORD PDF

From another script (e.g. run.py):
  import fetch_uspto
  result = fetch_uspto.run("18909470")   # -> {"out", "wrapper", "documents", "manifest", ...}
"""
import argparse
import io
import json
import os
import re
import time
import zipfile
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

BASE = "https://api.uspto.gov"
API_HOST = urlparse(BASE).netloc
EXT = {"PDF": ".pdf", "MS_WORD": ".docx", "XML": ".xml"}
DEFAULT_FORMATS = ["XML", "MS_WORD", "PDF"]  # format preference order
DEFAULT_OUT_ROOT = "example/data"             # output goes in <this>/<application number>

# Document codes to download by default. Paste your whitelist here; codes are
# matched exactly (ignoring case), so keep odd ones like "A..." and "ELC." as-is.
# Leave empty to download everything. --codes on the command line overrides this.
ALLOWED_CODES = {"CLM", "REM", "CTRS", "ELC.", "CTNF", "CTFR", "EXIN", "NOA"}


def fetch(url, key, tries=4):
    """GET with retries. The API key is sent only to the USPTO host, so redirects
    are followed by hand instead of letting requests forward the header elsewhere."""
    for attempt in range(tries):
        current = url
        for _ in range(5):
            headers = {"X-API-KEY": key} if urlparse(current).netloc == API_HOST else {}
            r = requests.get(current, headers=headers, allow_redirects=False, timeout=60)
            if r.is_redirect and r.headers.get("Location"):
                current = urljoin(current, r.headers["Location"])
                continue
            break
        else:
            raise RuntimeError(f"Too many redirects for {url}")
        if r.status_code in (429, 500, 502, 503, 504) and attempt < tries - 1:
            time.sleep(2 ** (attempt + 1))  # back off, then retry
            continue
        r.raise_for_status()
        return r


def find_docs(payload):
    for k in ("documentBag", "documents", "document_bag"):
        if isinstance(payload.get(k), list):
            return payload[k]
    raise SystemExit(
        f"Couldn't find the document list. Top-level keys: {list(payload)}. "
        "Open documents.json and adjust find_docs()."
    )


def options_of(doc):
    for k in ("downloadOptionBag", "downloadOptions", "documentFormats"):
        if isinstance(doc.get(k), list):
            return doc[k]
    return []


def pick_option(doc, preferred):
    """First option matching the preferred formats, in order."""
    by_fmt = {str(o.get("mimeTypeIdentifier", "")).upper(): o for o in options_of(doc)}
    for fmt in preferred:
        if fmt in by_fmt and by_fmt[fmt].get("downloadUrl"):
            return fmt, by_fmt[fmt]
    return None, None


def save(data, fmt, stem, files_dir):
    """Write bytes to disk. XML downloads may arrive as a zip: unzip those."""
    if fmt == "XML" and data[:2] == b"PK":
        folder = files_dir / stem
        folder.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            z.extractall(folder)
        return folder
    path = files_dir / (stem + EXT.get(fmt, ".bin"))
    path.write_bytes(data)
    return path


def fetch_application(app, key, out):
    """Download the wrapper and document list, save both as JSON, return them."""
    wrapper = fetch(f"{BASE}/api/v1/patent/applications/{app}", key).json()
    (out / "wrapper.json").write_text(json.dumps(wrapper, indent=2))
    payload = fetch(f"{BASE}/api/v1/patent/applications/{app}/documents", key).json()
    (out / "documents.json").write_text(json.dumps(payload, indent=2))
    return wrapper, payload


def download_documents(payload, key, out, codes=None, formats=DEFAULT_FORMATS,
                       list_only=False, verbose=True):
    """Download each wanted document (first available format in `formats`).

    Returns the manifest: one row per document, sorted by date, with the saved path
    relative to `out` (None if not downloaded). Files already on disk are reused.
    """
    files_dir = out / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    chosen = codes if codes else ALLOWED_CODES
    wanted = {c.upper() for c in chosen} or None  # None = download everything
    preferred = [f.upper() for f in formats]
    manifest = []
    for doc in find_docs(payload):
        code = str(doc.get("documentCode", ""))
        fmt, opt = pick_option(doc, preferred)
        date = str(doc.get("officialDate", ""))[:10]
        stem = f"{date}_{re.sub(r'[^A-Za-z0-9]+', '-', code).strip('-')}_{doc.get('documentIdentifier', '')}"
        row = {
            "date": date,
            "code": code,
            "description": doc.get("documentCodeDescriptionText"),
            "direction": doc.get("directionCategory"),
            "document_id": doc.get("documentIdentifier"),
            "pages": (opt or {}).get("pageTotalQuantity"),
            "format": fmt,
            "path": None,
        }
        skipped = wanted is not None and code.upper() not in wanted
        if fmt and not list_only and not skipped:
            existing = list(files_dir.glob(stem + "*"))
            if existing:  # already downloaded on an earlier run
                row["path"] = str(existing[0].relative_to(out))
            else:
                resp = fetch(opt["downloadUrl"], key)
                row["path"] = str(save(resp.content, fmt, stem, files_dir).relative_to(out))
                time.sleep(0.5)  # be polite to the API
        manifest.append(row)
        if verbose:
            print(f"{date}  {code:<12} {fmt or '-':<8} "
                  f"{'(not in whitelist)' if skipped else row['path'] or ''}")

    manifest.sort(key=lambda r: r["date"])
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def run(application, out=None, codes=None, formats=DEFAULT_FORMATS, list_only=False,
        key=None, verbose=True):
    """Fetch one application end to end. This is the entry point for run.py.

    application  number in any form ("18909470" or "18/909,470")
    out          output folder (default DEFAULT_OUT_ROOT/<application number>)
    codes        document codes to download (default ALLOWED_CODES; empty = all)
    key          API key (default: the USPTO_API_KEY environment variable)
    Returns {"application", "out", "wrapper", "documents", "manifest"}; "out" is a Path.
    Raises ValueError for a missing key or a bad application number.
    """
    key = key or os.environ.get("USPTO_API_KEY")
    if not key:
        raise ValueError("Set USPTO_API_KEY in your environment first.")
    app = re.sub(r"\D", "", str(application))
    if not app:
        raise ValueError(f"{application!r} doesn't look like an application number.")
    out = Path(out or Path(DEFAULT_OUT_ROOT) / app)
    out.mkdir(parents=True, exist_ok=True)

    wrapper, payload = fetch_application(app, key, out)
    manifest = download_documents(payload, key, out, codes, formats, list_only, verbose)
    if verbose:
        print(f"\n{len(manifest)} documents. Output in {out}/")
    return {"application": app, "out": out, "wrapper": wrapper, "documents": payload,
            "manifest": manifest}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("application", help="application number, e.g. 18909470 or 18/909,470")
    ap.add_argument("--out", help=f"output folder (default {DEFAULT_OUT_ROOT}/<application number>)")
    ap.add_argument("--codes", nargs="*", help="download only these document codes (overrides ALLOWED_CODES)")
    ap.add_argument("--formats", nargs="*", default=DEFAULT_FORMATS,
                    help="format preference order (default: XML MS_WORD PDF)")
    ap.add_argument("--list-only", action="store_true", help="save JSON and manifest, skip file downloads")
    args = ap.parse_args()
    try:
        run(args.application, args.out, args.codes, args.formats, args.list_only)
    except ValueError as e:
        raise SystemExit(str(e))


if __name__ == "__main__":
    main()
