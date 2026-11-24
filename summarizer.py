"""Turn a timeline entry into a short message: a fixed sentence or an AI summary.

Usage:  .venv/bin/python summarizer.py <entry> 

From another script (e.g. run.py):
  import summarizer
  text = summarizer.boilerplate(entry, case)       # fixed sentence, or None
  text = summarizer.summarize(entry)   # Gemini summary
"""
import sys
import time
from pathlib import Path

# --- Fixed messages: codes whose message doesn't need the document text ----------
# Milestones and cover documents. {name} fields come from the case info in timeline.json.
# Response wrappers (ELC., A..., A.NE) only announce the response; the same-day
# REM / CLM entries carry the substance and are summarized by AI.
BOILERPLATE = {
    "FILED":      "I've filed a patent application for {inventionTitle}.",
    "TRACK1.REQ": "I've requested Track One prioritized examination for this application.",
    "COMP":       "The application is complete and has been accepted for examination.",
    "PG-ISSUE":   "The application has been published.",
    "ELC.":       "I've responded to the restriction requirement with an election.",
    "A...":       "I've filed an amendment in response to the non-final rejection.",
    "A.NE":       "I've filed a response to the final rejection.",
    "RCEX":       "I've filed a Request for Continued Examination.",
    "AMSB":       "I've submitted claim amendments with the Request for Continued Examination.",
    "A.QU":       "I've responded to the Ex Parte Quayle action.",
    "A.NA":       "I've filed an amendment after allowance.",
    "N/AP":       "I've filed a notice of appeal.",
    "AP.B":       "I've filed an appeal brief.",
    "NOA":        "The application has been allowed. Once the issue fee is paid, the patent will be granted.",
    "ISSUE.NTF":  "The patent will issue as U.S. Patent No. {patentNumber}.",
    "EGRANT.NTF": "U.S. Patent No. {patentNumber} has been granted for {inventionTitle}.",
}


class _Blank(dict):
    """format_map helper: a missing or empty case field becomes '' instead of an error."""
    def __missing__(self, key):
        return ""


def boilerplate(entry, case):
    """The fixed message for this entry's code, filled in from the case info; None if
    the code needs an AI summary instead."""
    template = BOILERPLATE.get(entry.get("code"))
    if template is None:
        return None
    fields = _Blank({k: v for k, v in (case or {}).items() if v})
    return " ".join(template.format_map(fields).split())  # tidy spaces left by blanks


# --- AI summaries -----------------------------------------------------------------
# create overall system instruction that includes not mentioning application number or
# things that would not flow normally in a conversation
def instructions(mode, text):
    """(system_instruction, input) for one mode."""
    match mode:
        case "CLM":
            return ("You are an inventor sending a message about the claims in the text. In the text, [+...+] marks inserted claim text and [-...-] marks deleted text.",
                    f"Summarize the state of the invention given these claims. Do not call out specific claim numbers, just what the invention means given any insertions or deletions. 2-3 sentences. \n\n{text}")
        case "CTRS":
            return ("You are a patent examiner sending a message to the applicant requesting them to elect claims. This message should be 2-3 sentences.",
                    f"Summarize the restriction action in this text:\n {text}")
        case "CTNF":
            return ("You are a patent examiner sending a message to the applicant regarding a non final action. This message should be 2-3 sentences.",
                    f"Summarize the action in this text:\n {text}")
        case "CTFR":
            return ("You are a patent examiner sending a message to the applicant regarding a final action. This message should be 2-3 sentences.",
                    f"Summarize the action in this text:\n {text}")
        case "REM":
            return ("You are an inventor sending a message replying to an office action from an examiner. This message is 2-3 sentences.",
                    f"Summarize these remarks:\n {text}")
        case "EXIN":
            return ("You are an patent examiner messaging the results from a interview with the applicant. This message is 2-3 sentences.",
                    f"Summarize your response:\n {text}")
    raise ValueError(f"no summary instructions for mode {mode!r}")


# --- Rate limits ------------------------------------------------------------------
# The free tier allows 5 requests per minute. Calls are spaced out, a "too many
# requests" error (HTTP 429) is retried after a wait, and every summary is saved to
# disk, so re-running skips what's already done.
MIN_SECONDS_BETWEEN_CALLS = 12   # 60 s / 5 requests per minute (free-tier limit)
RETRY_WAITS = [30, 60, 120]      # seconds to wait after each 429 before giving up
_last_call = 0.0
#MODEL = "gemini-4-hydrogen"
#MODEL = "gemini-3.1-flash-lite"
MODEL = "gemini-3.5-flash-lite"
def _is_rate_limit(error):
    """True for Gemini's 'too many requests / quota exhausted' error."""
    return getattr(error, "code", None) == 429 or "RESOURCE_EXHAUSTED" in str(error)


def _ask_gemini(system_instruction, input_instruction):
    """One Gemini call, spaced out from the previous one and retried on 429."""
    global _last_call
    from google import genai  # imported here so boilerplate() works without it installed
    client = genai.Client()  # reads GEMINI_API_KEY
    for attempt in range(len(RETRY_WAITS) + 1):
        wait = MIN_SECONDS_BETWEEN_CALLS - (time.time() - _last_call)
        if wait > 0:  # only sleep for whatever is left of the gap
            time.sleep(wait)
        _last_call = time.time()
        try:
            interaction = client.interactions.create(
                model=MODEL,
                system_instruction=system_instruction,
                input=input_instruction
            )
            return interaction.output_text
        except Exception as error:
            if not _is_rate_limit(error) or attempt == len(RETRY_WAITS):
                raise  # a different error, or still limited after every retry
            print(f"  rate limit hit; waiting {RETRY_WAITS[attempt]} s, then retrying")
            time.sleep(RETRY_WAITS[attempt])


def summarize(entry):
    """Gemini summary of the entry's text_file, using the instructions for its code.

    The summary is saved as <out>/summaries/<text file name>.txt (next to the text/
    folder); if that file already exists it is returned without calling Gemini.
    """
    file = Path(entry.get("text_file"))
    cache = file.parent.parent / "summaries" / f"{file.stem}.txt"
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    text = file.read_text(encoding="utf-8")
    system_instruction, input_instruction = instructions(entry.get("code"), text)
    summary = _ask_gemini(system_instruction, input_instruction)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(summary, encoding="utf-8")
    return summary


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    print(summarize(sys.argv[1]))
