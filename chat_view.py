"""Show conversation.json as a text-message thread in a single HTML page.

Usage:  python3 chat_view.py <conversation.json> [out.html]
  out.html defaults to conversation.html next to the JSON. If timeline.json is in the
  same folder, its case info (title, numbers, applicant) goes in the page header.

From another script (e.g. run.py):
  import chat_view
  chat_view.render(messages, timeline["case"], out / "conversation.html")

Applicant messages are on the right (blue); Examiner and USPTO messages are on the
left, each in its own color. The page is self-contained: inline CSS, no JavaScript.
"""
import json
import sys
from datetime import date as Date
from html import escape
from pathlib import Path

# sender -> (side, CSS class). Anything not listed goes left in plain gray.
# Shown in the page footer.
DISCLAIMER = ("Educational project. Summaries are AI-generated from public USPTO "
              "records and may contain errors.")

SENDERS = {"Applicant": ("right", "applicant"),
           "Examiner": ("left", "examiner"),
           "USPTO": ("left", "uspto")}

CSS = """
:root { --bg:#ffffff; --text:#111; --muted:#6b7280; --bar:#f3f4f6; --line:#e5e7eb;
        --applicant:#0a84ff; --applicant-text:#fff; --examiner:#e9e9eb; --examiner-text:#111;
        --uspto:#fdecc8; --uspto-text:#4a3500; --other:#e5e7eb; --other-text:#111; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#000; --text:#f5f5f7; --muted:#9ca3af; --bar:#1c1c1e; --line:#2c2c2e;
          --examiner:#2c2c2e; --examiner-text:#f5f5f7; --uspto:#4a3a12; --uspto-text:#fde9b8;
          --other:#3a3a3c; --other-text:#f5f5f7; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--text);
       font:16px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; }
header { position:sticky; top:0; background:var(--bar); border-bottom:1px solid var(--line);
         padding:12px 16px; text-align:center; }
header h1 { margin:0; font-size:16px; font-weight:600; }
header p { margin:4px 0 0; font-size:12px; color:var(--muted); }
main { max-width:720px; margin:0 auto; padding:8px 16px 32px; }
.day { text-align:center; color:var(--muted); font-size:12px; font-weight:600; margin:20px 0 8px; }
.row { display:flex; flex-direction:column; margin-top:2px; }
.row.right { align-items:flex-end; } .row.left { align-items:flex-start; }
.row.first { margin-top:10px; }
.who { font-size:11px; color:var(--muted); margin:0 12px 2px; }
.bubble { max-width:70%; padding:8px 12px; border-radius:18px; white-space:pre-wrap;
          overflow-wrap:anywhere; }
@media (max-width:480px) { .bubble { max-width:85%; } }
.applicant .bubble { background:var(--applicant); color:var(--applicant-text); }
.examiner .bubble { background:var(--examiner); color:var(--examiner-text); }
.uspto .bubble { background:var(--uspto); color:var(--uspto-text); }
.other .bubble { background:var(--other); color:var(--other-text); }
footer { max-width:720px; margin:0 auto; padding:16px 16px 32px; border-top:1px solid var(--line);
         text-align:center; font-size:12px; color:var(--muted); }
"""


def nice_date(value):
    """'2024-10-08' -> 'Oct 8, 2024'; anything unparseable is shown as-is."""
    try:
        d = Date.fromisoformat(value)
        return f"{d:%b} {d.day}, {d.year}"
    except (TypeError, ValueError):
        return value or "Undated"


def header_html(case):
    """Title plus a line of case details; a generic title when there is no case info."""
    case = case or {}
    title = case.get("inventionTitle") or "Patent prosecution conversation"
    details = [f"Application {case['applicationNumberText']}" if case.get("applicationNumberText") else "",
               f"U.S. Patent No. {case['patentNumber']}" if case.get("patentNumber") else "",
               f"Applicant {case['firstApplicantName']}" if case.get("firstApplicantName") else ""]
    details = " · ".join(escape(d) for d in details if d)
    return f"<header><h1>{escape(title)}</h1>" + (f"<p>{details}</p>" if details else "") + "</header>"


def render(messages, case=None, out_path="conversation.html"):
    """Write the chat page for a list of {date, sender, message}; return its path."""
    rows, last_date, last_sender = [], object(), None
    for m in messages:
        if m.get("date") != last_date:  # date separator, like a phone's message thread
            rows.append(f'<div class="day">{escape(nice_date(m.get("date")))}</div>')
            last_date, last_sender = m.get("date"), None
        sender = m.get("sender") or "Unknown"
        side, css = SENDERS.get(sender, ("left", "other"))
        first = sender != last_sender  # name label only on the first of a run
        label = f'<div class="who">{escape(sender)}</div>' if first else ""
        rows.append(f'<div class="row {side} {css}{" first" if first else ""}">{label}'
                    f'<div class="bubble">{escape(str(m.get("message") or "").strip())}</div></div>')
        last_sender = sender

    title = (case or {}).get("inventionTitle") or "Patent conversation"
    page = (f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{escape(title)}</title><style>{CSS}</style></head><body>"
            f"{header_html(case)}<main>\n" + "\n".join(rows) + "\n</main>"
            f"<footer>{escape(DISCLAIMER)}</footer></body></html>\n")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(page, encoding="utf-8")
    print(f"{out_path.name} written ({len(messages)} messages): {out_path}")
    return out_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    src = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_name("conversation.html")
    timeline_path = src.with_name("timeline.json")  # optional: case info for the header
    case = json.loads(timeline_path.read_text()).get("case") if timeline_path.exists() else None
    render(json.loads(src.read_text(encoding="utf-8")), case, out)
