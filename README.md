# Patent File Wrapper → Conversation

Turns a U.S. patent application's prosecution history (its "file wrapper") into a
readable, chronological conversation between the **applicant**, the **examiner**, and
the **USPTO**, with each step summarized in plain language.

Give it an application number and it will:

1. Fetch the application and its document list from the USPTO Open Data Portal.
2. Build a concise timeline of the documents that matter: filing, restriction,
   rejections, responses, interviews, allowance, grant.
3. Download those documents (XML when available, otherwise PDF).
4. Convert each one to clean text (XML parsing, or OCR for scanned PDFs).
5. Turn each step into a short message: a fixed sentence for milestones, or a Gemini
   summary for substantive documents.
6. Write `conversation.json` and a text-message style `conversation.html`.

See [`example/data/18909470/`](example/data/18909470/) for a complete run on
application 18/909,470. Open `conversation.html` in a browser to see the result.

## Setup

Requires Python 3.10+.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# OCR tools for scanned PDFs
brew install tesseract poppler            # macOS
# sudo apt install tesseract-ocr poppler-utils   # Ubuntu
```

Set two API keys as environment variables. Don't put them in files you commit.

```bash
export USPTO_API_KEY=...    # https://data.uspto.gov (Open Data Portal API key)
export GEMINI_API_KEY=...   # https://aistudio.google.com (Gemini API key)
```

## Usage

```bash
.venv/bin/python run.py 18909470
```

The output goes to `example/data/<application number>/`. To change that location, edit
`DEFAULT_OUT_ROOT` in `fetch_uspto.py`.

| File | Contents |
|---|---|
| `wrapper.json`, `documents.json` | Raw USPTO API responses |
| `manifest.json` | Every document, with the format and local path of what was downloaded |
| `files/` | Downloaded documents (XML downloads are tar archives) |
| `timeline.json` | The filtered, date-sorted timeline, with case info, file paths and messages |
| `text/` | Clean text extracted from each document |
| `summaries/` | Cached Gemini summaries (delete one to regenerate it) |
| `conversation.json` | `[{date, sender, message}]` |
| `conversation.html` | The conversation as a text-message thread |

Re-running is cheap. Downloads and Gemini summaries that already exist are reused, so
an interrupted run picks up where it stopped.

## How it works

```
run.py
 ├─ fetch_uspto.py   application number → wrapper.json, documents.json, files/, manifest.json
 ├─ organize.py      → timeline.json (whitelisted documents + events, sorted, linked to files)
 │    └─ report.py      terminal summary of what was kept, filtered, or unrecognized
 ├─ parser.py        each file → text/  (chooses by file content, not extension)
 │    ├─ xml_parser.py  USPTO XML: claims, remarks, office actions, notices
 │    └─ pdf_parser.py  PDF text layer, or Tesseract OCR for scanned pages
 ├─ summarizer.py    each timeline entry → a fixed sentence or a Gemini summary
 ├─ conversation.py  → conversation.json
 └─ chat_view.py     → conversation.html
```

Every script can also be run on its own. Its usage is in the docstring at the top of the file.

```bash
python3 organize.py wrapper.json documents.json manifest.json
.venv/bin/python parser.py example/data/18909470/files --out /tmp/text
.venv/bin/python summarizer.py example/data/18909470/text/text-M97JD5LWWFYGX54.txt ctnf
python3 conversation.py example/data/18909470/timeline.json
python3 chat_view.py example/data/18909470/conversation.json
python3 claim_parser.py <claims.xml>     # one claims XML → marked-up claim text
```

### Choosing what goes in the timeline

- **[`whitelist-doc-codes.txt`](whitelist-doc-codes.txt):** the USPTO document codes to
  keep, e.g. `CTNF` (non-final rejection), `REM` (applicant remarks), `NOA` (notice of
  allowance). Use one code per line; anything after `#` is a comment.
- **[`whitelist-event-codes.txt`](whitelist-event-codes.txt):** milestone events with no
  document of their own, e.g. `COMP` (application complete) and `PG-ISSUE` (published).

Anything filtered out or not recognized is printed, never silently dropped.

### Messages

- **Fixed sentences** for milestones and cover documents (filing, Track One, publication,
  allowance, issue, grant) live in `BOILERPLATE` in `summarizer.py`.
- **Gemini prompts** for each document type (claims, restriction, rejections, remarks,
  interviews) live in `instructions()` in `summarizer.py`.
- **Senders:** examiner-written documents are shown as **Examiner**. Other office notices
  are shown as **USPTO**. The list is `EXAMINER_CODES` in `conversation.py`.

### Text markup

In parsed claims and remarks, amendments are marked `[+inserted text+]` and
`[-deleted text-]`. Section headings start with `## `.

## Notes and limitations

- **Gemini rate limits:** the free tier allows a few requests per minute, so
  `summarizer.py` spaces calls 12 s apart (`MIN_SECONDS_BETWEEN_CALLS`) and retries on
  HTTP 429. A typical application needs about 13 summaries, which takes about 3 minutes
  on the first run.
- **What gets downloaded:** `fetch_uspto.py` downloads only the codes in its
  `ALLOWED_CODES` set. Timeline entries for other whitelisted codes have `"file": null`
  and are reported as "not downloaded".
- **OCR text:** text from scanned documents can contain OCR errors and the law firm's
  page footers.
- **Same-day duplicates:** some responses appear twice on the same day (a full response
  and a 1-page split copy). The timeline keeps the full response.
- **Privacy:** Gemini's free tier may use your inputs to improve Google's products.
  Patent prosecution records are public, but keep this in mind for anything else you
  send.
