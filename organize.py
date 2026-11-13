"""Build a concise, chronological prosecution timeline for one USPTO application.

Usage:  python3 organize.py [wrapper.json] [documents.json] [manifest.json]
  wrapper.json    Patent File Wrapper response: case info, filing date, events
                  (defaults to ./patentapp-ex.json)
  documents.json  /documents API response (documentBag)
                  (defaults to ./patentapp-docs.json)
  manifest.json   fetch_uspto.py manifest; links each document to its downloaded copy
                  (optional; without it every "file" is null)
The timeline is: an "Application filed" entry, then documents whose code is in
whitelist-doc-codes.txt, plus events whose code is in whitelist-event-codes.txt.
Writes ./out/timeline.json and prints a table plus anything unrecognized.

From another script (e.g. run.py):
  import organize
  timeline = organize.build_timeline(wrapper, documents, manifest, files_root=out,
                                     out_path=out / "timeline.json")
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

from report import print_report  # report.py, in the same folder

HERE = Path(__file__).parent  # whitelists live next to this script
DOC_WHITELIST = HERE / "whitelist-doc-codes.txt"
EVENT_WHITELIST = HERE / "whitelist-event-codes.txt"
OUT = Path("out/timeline.json")

# Field names exactly as they appear in the USPTO API JSON.
CASE_FIELDS = ["inventionTitle", "filingDate", "applicationStatusDescriptionText",
               "grantDate", "patentNumber", "examinerNameText",
               "firstApplicantName", "groupArtUnitNumber"]
EVENT_FIELDS = {"eventCode", "eventDescriptionText", "eventDate"}
DOC_FIELDS = {"officialDate", "documentCode", "documentCodeDescriptionText",
              "directionCategory", "downloadOptionBag", "documentIdentifier",
              "applicationNumberText"}  # present in the API but not needed for the timeline
# directionCategory -> who the document came from
DIRECTION = {"OUTGOING": "USPTO", "INCOMING": "Applicant", "INTERNAL": "USPTO (internal)"}


def check_keys(record, expected, where, unrecognized):
    """Note any keys we don't use, so nothing is dropped silently."""
    for key in record:
        if key not in expected:
            unrecognized.append(f"{where}: unexpected field '{key}' = {str(record[key])[:60]!r}")


def load_codes(path):
    """Read a whitelist: one code per line, text after '#' is a comment."""
    return {line.split("#")[0].strip() for line in Path(path).read_text().splitlines()} - {""}


def page_count(doc):
    """Page count lives on each download option; take the first one that has it."""
    return next((o.get("pageTotalQuantity") for o in doc.get("downloadOptionBag") or []
                 if o.get("pageTotalQuantity") is not None), None)


def build_timeline(wrapper, documents, manifest=None, files_root=".", out_path=OUT,
                   verbose=True):
    """Build the timeline, write it to out_path (unless None), and return it.

    wrapper     wrapper JSON (dict)          documents  /documents JSON (dict)
    manifest    fetch_uspto manifest rows (list) or None
    files_root  folder the manifest's "path" values are relative to (fetch_uspto's out)
    Returns {"case", "entry_count", "timeline", "unrecognized"}. Each document entry
    has "document_id" and "file": the local copy's path, or None if not downloaded.
    """
    unrecognized = []  # everything odd goes here and is printed at the end

    # Step 1: pull case-level info from the wrapper's applicationMetaData.
    bag = wrapper.get("patentFileWrapperDataBag") or [wrapper]
    if len(bag) != 1:
        unrecognized.append(f"wrapper: expected 1 application, found {len(bag)}; using the first")
    app = bag[0]
    meta = app.get("applicationMetaData") or {}
    case = {"applicationNumberText": app.get("applicationNumberText")}
    for field in CASE_FIELDS:
        case[field] = meta.get(field)
        if case[field] is None:
            unrecognized.append(f"case: field '{field}' not found")

    # Step 2: the timeline opens with the filing itself (no single record says "filed").
    timeline = [{"date": case["filingDate"] or "", "kind": "case", "source": "Applicant",
                 "code": "FILED", "description": "Application filed", "pages": None,
                 "document_id": None, "file": None}]

    # Step 3: map document id -> local file, from the download manifest.
    local = {row.get("document_id"): Path(files_root) / row["path"]
             for row in manifest or [] if row.get("path")}

    # Step 4: add whitelisted documents, labelled USPTO or Applicant by directionCategory.
    docs = documents.get("documentBag") or []
    if not docs:
        raise ValueError("no documentBag found in the documents JSON")
    for num in {d.get("applicationNumberText") for d in docs} - {case["applicationNumberText"], None}:
        unrecognized.append(f"documents: application {num} does not match wrapper "
                            f"{case['applicationNumberText']}")
    doc_codes, skipped_docs = load_codes(DOC_WHITELIST), Counter()

    # Some responses (e.g. ELC., A..., A.NE) appear twice on the same day: the full
    # response (no page count) and a 1-page split copy. Keep the full response.
    unpaged = {(d.get("documentCode"), (d.get("officialDate") or "")[:10])
               for d in docs if page_count(d) is None}
    dropped_dupes = []
    for d in docs:
        code, doc_id = d.get("documentCode"), d.get("documentIdentifier")
        if code not in doc_codes:
            skipped_docs[code] += 1
            continue
        date = (d.get("officialDate") or "")[:10]
        if page_count(d) is not None and (code, date) in unpaged:
            dropped_dupes.append(f"{date} {code} ({doc_id})")
            continue
        check_keys(d, DOC_FIELDS, f"document {code}", unrecognized)
        direction = d.get("directionCategory")
        if direction not in DIRECTION:
            unrecognized.append(f"document {code}: unknown directionCategory {direction!r}")
        if not d.get("documentCodeDescriptionText"):
            unrecognized.append(f"document {code}: no description for this document code")
        file = local.get(doc_id)
        if manifest is not None and file is None:
            unrecognized.append(f"document {date} {code} ({doc_id}): not downloaded")
        elif file is not None and not file.exists():
            unrecognized.append(f"document {date} {code}: local file missing: {file}")
        timeline.append({"date": date, "kind": "document",
                         "source": DIRECTION.get(direction, f"UNKNOWN ({direction})"),
                         "code": code, "description": d.get("documentCodeDescriptionText"),
                         "pages": page_count(d), "document_id": doc_id,
                         "file": str(file) if file else None})

    # Step 5: add whitelisted events (USPTO milestones that no document records).
    event_codes, skipped_events = load_codes(EVENT_WHITELIST), 0
    for e in app.get("eventDataBag") or []:
        code = e.get("eventCode")
        if code not in event_codes:
            skipped_events += 1
            continue
        check_keys(e, EVENT_FIELDS, f"event {code}", unrecognized)
        timeline.append({"date": (e.get("eventDate") or "")[:10], "kind": "event",
                         "source": "USPTO", "code": code,
                         "description": e.get("eventDescriptionText"), "pages": None,
                         "document_id": None, "file": None})

    # Step 6: sort by date. The sort is stable, so "Application filed" stays first on its day.
    for entry in timeline:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", entry["date"]):
            unrecognized.append(f"{entry['kind']} {entry['code']}: unparseable date {entry['date']!r}")
    timeline.sort(key=lambda entry: entry["date"])

    # Step 7: write the JSON output.
    result = {"case": case, "entry_count": len(timeline), "timeline": timeline}
    if out_path:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=2))

    # Step 8: print the summary (table, filter stats, unrecognized items); see report.py.
    if verbose:
        print_report(case, timeline, out_path, len(docs), skipped_docs, dropped_dupes,
                     len(app.get("eventDataBag") or []), skipped_events, unrecognized)
    return {**result, "unrecognized": unrecognized}


if __name__ == "__main__":
    wrapper_path = Path(sys.argv[1] if len(sys.argv) > 1 else "patentapp-ex.json")
    docs_path = Path(sys.argv[2] if len(sys.argv) > 2 else "patentapp-docs.json")
    manifest_path = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    for path in (wrapper_path, docs_path, manifest_path, DOC_WHITELIST, EVENT_WHITELIST):
        if path and not path.exists():
            sys.exit(f"file not found: {path}")
    try:
        build_timeline(json.loads(wrapper_path.read_text()), json.loads(docs_path.read_text()),
                       json.loads(manifest_path.read_text()) if manifest_path else None,
                       files_root=manifest_path.parent if manifest_path else ".")
    except ValueError as e:
        sys.exit(str(e))
