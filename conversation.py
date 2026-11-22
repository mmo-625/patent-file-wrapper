"""Turn timeline.json into conversation.json: one {date, sender, message} per entry.

Usage:  python3 conversation.py <timeline.json> [conversation.json]
  conversation.json defaults to the same folder as timeline.json.
Entries without a message (e.g. not summarized yet) are skipped and listed.
Rejections (CTNF / CTFR) also get an optional "rejections" key: the rejection table and
cited references from rejections.py, shown as a collapsible breakdown in chat_view.py.
Claims filings (CLM) get an optional "claims" key: the independent claims from claims.py,
each shown as a collapsible claim (with its amendments marked) in chat_view.py.

From another script (e.g. run.py):
  import conversation
  messages = conversation.build_conversation(timeline, out / "conversation.json")
"""
import json
import sys
from pathlib import Path

import claims
import rejections

# Documents written by the examiner: these show sender "Examiner". Other USPTO entries
# (application complete, publication, issue/grant notices) stay "USPTO".
EXAMINER_CODES = {"CTRS", "CTNF", "CTFR", "CTAV", "CTEQ", "EXIN", "NOA"}
# Office actions whose text gets a rejection breakdown (non-final and final rejections).
REJECTION_CODES = {"CTNF", "CTFR"}
# Claims filings whose independent claims are attached.
CLAIM_CODES = {"CLM"}


def sender(entry):
    """'Examiner' for examiner-written documents, otherwise the timeline source."""
    if entry.get("code") in EXAMINER_CODES:
        return "Examiner"
    return entry.get("source")


def rejection_breakdown(entry):
    """Rejection table + references for a rejection entry with a text file, else None."""
    path = entry.get("text_file")
    if entry.get("code") not in REJECTION_CODES or not path or not Path(path).exists():
        return None
    return rejections.extract(Path(path).read_text(encoding="utf-8"))


def independent_claims(entry):
    """Independent claims for a claims entry with a text file, else None."""
    path = entry.get("text_file")
    if entry.get("code") not in CLAIM_CODES or not path or not Path(path).exists():
        return None
    return claims.independent_claims(Path(path).read_text(encoding="utf-8")) or None


def build_conversation(timeline, out_path=None, verbose=True):
    """timeline: the timeline.json dict (or just its "timeline" list).
    Writes out_path (unless None) and returns the list of messages, in date order."""
    entries = timeline["timeline"] if isinstance(timeline, dict) else timeline
    messages, skipped = [], []
    for entry in sorted(entries, key=lambda e: e.get("date") or ""):  # stable: same-day order kept
        message = (entry.get("message") or "").strip()
        if not message:
            skipped.append(f"{entry.get('date')} {entry.get('code')}")
            continue
        item = {"date": entry.get("date"), "sender": sender(entry), "message": message,
                "code": entry.get("code")}  # document code, used for the page summary
        breakdown = rejection_breakdown(entry)
        if breakdown:
            item["rejections"] = breakdown
        found = independent_claims(entry)
        if found:
            item["claims"] = found
        messages.append(item)

    if out_path:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(messages, indent=2, ensure_ascii=False), encoding="utf-8")
    if verbose:
        print(f"{len(messages)} messages" + (f" written to {out_path}" if out_path else ""))
        if skipped:
            print(f"skipped (no message): {', '.join(skipped)}")
    return messages


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    src = Path(sys.argv[1])
    dest = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_name("conversation.json")
    build_conversation(json.loads(src.read_text(encoding="utf-8")), dest)
