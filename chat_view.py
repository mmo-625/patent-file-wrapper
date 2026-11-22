"""Show conversation.json as a text-message thread in a single HTML page.

Usage:  python3 chat_view.py <conversation.json> [out.html]
  out.html defaults to conversation.html next to the JSON. If timeline.json is in the
  same folder, its case info (title, numbers, applicant) goes in the page header.

From another script (e.g. run.py):
  import chat_view
  chat_view.render(messages, timeline["case"], out / "conversation.html")

Applicant messages are on the right (blue); Examiner and USPTO messages are on the
left, each in its own color. The page is self-contained: inline CSS, no JavaScript.
Messages with a "rejections" key (see rejections.py) get a collapsible "Rejection
breakdown" under the bubble: a table of rejections and the cited references.
A summary card at the top counts the key events (restrictions, rejections, responses,
interviews, allowance) from each message's "code", plus the filing-to-grant time.
Messages with a "claims" key (see claims.py) get one collapsible button per independent
claim; amendments show as green insertions and struck-through red deletions.
"""
import json
import re
import sys
from datetime import date as Date
from html import escape
from pathlib import Path

from rejections import patent_links

# sender -> (side, CSS class). Anything not listed goes left in plain gray.
# Shown in the page footer.
DISCLAIMER = ("Educational project. Summaries are AI-generated from public USPTO "
              "records and may contain errors.")

SENDERS = {"Applicant": ("right", "applicant"),
           "Examiner": ("left", "examiner"),
           "USPTO": ("left", "uspto")}

CSS = """
:root { --ins:#0a7d32; --ins-bg:#dcfce7; --del:#b42318; --del-bg:#fee4e2; --bg:#ffffff; --text:#111; --muted:#6b7280; --bar:#f3f4f6; --line:#e5e7eb;
        --applicant:#0a84ff; --applicant-text:#fff; --examiner:#e9e9eb; --examiner-text:#111;
        --uspto:#fdecc8; --uspto-text:#4a3500; --other:#e5e7eb; --other-text:#111; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#000; --text:#f5f5f7; --muted:#9ca3af; --bar:#1c1c1e; --line:#2c2c2e;
          --examiner:#2c2c2e; --examiner-text:#f5f5f7; --uspto:#4a3a12; --uspto-text:#fde9b8;
          --other:#3a3a3c; --other-text:#f5f5f7;
          --ins:#6ee7a0; --ins-bg:#0f3d23; --del:#fca5a5; --del-bg:#4a1717; } }
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
.breakdown { max-width:70%; margin:4px 0 0; font-size:13px; }
@media (max-width:480px) { .breakdown { max-width:100%; } }
.breakdown summary { cursor:pointer; color:var(--muted); font-weight:600; padding:2px 12px;
                     list-style-position:inside; }
.breakdown[open] summary { margin-bottom:6px; }
.breakdown .panel { background:var(--examiner); color:var(--examiner-text); border-radius:14px;
                    padding:10px 12px; overflow-x:auto; }
.breakdown table { border-collapse:collapse; width:100%; }
.breakdown th, .breakdown td { text-align:left; vertical-align:top; padding:4px 8px 4px 0;
                               border-bottom:1px solid var(--line); }
.breakdown th { font-size:11px; text-transform:uppercase; letter-spacing:.03em; color:var(--muted); }
.breakdown td.statute { white-space:nowrap; }
.breakdown h4 { margin:12px 0 4px; font-size:11px; text-transform:uppercase; color:var(--muted); }
.breakdown ul { margin:0; padding-left:18px; }
.breakdown li { margin:2px 0; }
.breakdown a { color:inherit; }
.claim { max-width:70%; margin:4px 0 0; font-size:13px; }
@media (max-width:480px) { .claim { max-width:100%; } }
.claim summary { cursor:pointer; color:var(--muted); font-weight:600; padding:2px 12px;
                 list-style-position:inside; }
.claim[open] summary { margin-bottom:6px; }
.claim .panel { background:var(--examiner); color:var(--examiner-text); border-radius:14px;
                padding:10px 12px; text-align:left; }
.claim p { margin:0 0 6px; overflow-wrap:anywhere; }
.claim p.limit { padding-left:14px; }
.claim ins { color:var(--ins); background:var(--ins-bg); text-decoration:underline; }
.claim del { color:var(--del); background:var(--del-bg); text-decoration:line-through; }
.claim .legend { font-size:11px; color:var(--muted); margin:0 0 8px; }
.summary { background:var(--bar); border:1px solid var(--line); border-radius:14px;
           padding:10px 14px; margin:12px 0 4px; text-align:center; font-size:13px; color:var(--muted); }
.summary p { margin:2px 0; }
.summary strong { color:var(--text); }
.summary span { white-space:nowrap; }
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


def citation_html(citation):
    """Escaped citation text with any US patent numbers linked to Google Patents."""
    html = escape(citation)
    for number, url in patent_links(citation):
        html = html.replace(escape(number), f'<a href="{escape(url)}">{escape(number)}</a>', 1)
    return html


def breakdown_html(breakdown):
    """Collapsible rejection table + reference list (native <details>, no JavaScript)."""
    rows = "".join(
        f'<tr><td class="statute">§ {escape(r["statute"])}</td><td>{escape(r["ground"])}</td>'
        f'<td>{escape(r["claims"])}</td><td>{escape(" + ".join(r["references"])) or "—"}</td></tr>'
        for r in breakdown.get("rejections") or [])
    refs = "".join(f'<li><strong>{escape(ref["short"])}</strong>: {citation_html(ref["citation"])}</li>'
                   for ref in breakdown.get("references") or [])
    count = len(breakdown.get("rejections") or [])
    return (f'<details class="breakdown"><summary>Rejection breakdown ({count})</summary>'
            f'<div class="panel"><table><thead><tr><th>Statute</th><th>Ground</th><th>Claims</th>'
            f'<th>References</th></tr></thead><tbody>{rows}</tbody></table>'
            + (f"<h4>References</h4><ul>{refs}</ul>" if refs else "") + "</div></details>")


def markup_html(line):
    """Escape a claim line, then turn [+inserted+] into <ins> and [-deleted-] into <del>."""
    html = escape(line)
    html = re.sub(r"\[\+(.*?)\+\]", r"<ins>\1</ins>", html)
    return re.sub(r"\[-(.*?)-\]", r"<del>\1</del>", html)


def claims_html(found):
    """One collapsible button per independent claim (native <details>, no JavaScript)."""
    parts = []
    for claim in found:
        body = "".join(f'<p{" class=\"limit\"" if i else ""}>{markup_html(line)}</p>'
                       for i, line in enumerate(claim.get("lines") or []))
        legend = ('<p class="legend"><ins>inserted</ins> · <del>deleted</del></p>'
                  if claim.get("amended") else "")
        parts.append(f'<details class="claim"><summary>Claim {escape(str(claim.get("number")))} · '
                     f'{escape(claim.get("status") or "")}</summary>'
                     f'<div class="panel">{legend}{body}</div></details>')
    return "".join(parts)


# Summary card categories: label -> document codes. Responses arrive as several documents
# on one day (e.g. ELC. + CLM + REM), so they are counted once per date.
SUMMARY = [("restriction", {"CTRS"}),
           ("rejection", {"CTNF", "CTFR"}),
           ("response", {"ELC.", "A...", "A.NE", "AMSB", "RCEX", "SA..", "A.QU", "REM"}),
           ("interview", {"EXIN"}),
           ("allowance", {"NOA"})]
COUNT_BY_DATE = {"response"}
FINAL_REJECTION = "CTFR"


def months_between(start, end):
    """Whole months from one ISO date to another, or None if either is missing/invalid."""
    try:
        a, b = Date.fromisoformat(start), Date.fromisoformat(end)
    except (TypeError, ValueError):
        return None
    return (b.year - a.year) * 12 + b.month - a.month - (b.day < a.day)


def summary_html(messages, case):
    """Card with event counts and the filing-to-grant line; '' when there's nothing to show."""
    counts = []
    for label, codes in SUMMARY:
        hits = [m for m in messages if m.get("code") in codes]
        n = len({m.get("date") for m in hits}) if label in COUNT_BY_DATE else len(hits)
        if not n:
            continue
        text = f"<strong>{n}</strong> {label}{'s' if n != 1 else ''}"
        finals = sum(m.get("code") == FINAL_REJECTION for m in hits)
        if label == "rejection" and finals:
            text += f" ({finals} final)"
        counts.append(f"<span>{text}</span>")  # keeps "1 allowance" on one line
    case = case or {}
    filed, granted = case.get("filingDate"), case.get("grantDate")
    dates = ""
    if filed and granted:
        months = months_between(filed, granted)
        dates = (f"Filed <strong>{escape(nice_date(filed))}</strong> → Granted "
                 f"<strong>{escape(nice_date(granted))}</strong>"
                 + (f" ({months} month{'s' if months != 1 else ''})" if months is not None else ""))
    elif filed:
        status = case.get("applicationStatusDescriptionText")
        dates = f"Filed <strong>{escape(nice_date(filed))}</strong>" + (f" · {escape(status)}" if status else "")
    lines = [" · ".join(counts), dates]
    lines = "".join(f"<p>{line}</p>" for line in lines if line)
    return f'<section class="summary">{lines}</section>' if lines else ""


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
                    f'<div class="bubble">{escape(str(m.get("message") or "").strip())}</div>'
                    + (breakdown_html(m["rejections"]) if m.get("rejections") else "")
                    + (claims_html(m["claims"]) if m.get("claims") else "") + "</div>")
        last_sender = sender

    title = (case or {}).get("inventionTitle") or "Patent conversation"
    page = (f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{escape(title)}</title><style>{CSS}</style></head><body>"
            f"{header_html(case)}<main>\n{summary_html(messages, case)}\n" + "\n".join(rows) + "\n</main>"
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
