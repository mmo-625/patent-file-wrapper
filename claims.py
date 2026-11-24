"""Pick the independent claims out of a parsed claims (CLM) text file (no AI needed).

Usage:  python3 claims.py <claims text file> [previous claims text file]
  e.g.  python3 claims.py example/data/18909470/text/text-MHNVZFKJ4X45X46.txt

Reads the text xml_parser.py writes for a claims XML:
  Claim 1 (Currently amended)
  A system for ..., comprising:
  [+a processor; and+]            <- amendments marked [+inserted+] / [-deleted-]
  ...
A claim is independent when it doesn't refer back to another claim ("of claim 1").
Canceled and withdrawn claims are skipped.

Older (scanned) claims files often have no [+ +] / [- -] markup; xml_parser.py marks
their OCR-uncertain text [?...?] instead. Given the previous claims filing, the changes
in an amended claim are rebuilt with a word diff against that claim's previous version,
dropping OCR noise (usually garbled struck-through words). Those claims get
"reconstructed": True.

From another script (e.g. conversation.py):
  import claims
  found = claims.independent_claims(text, previous_text)
  # [{number, status, lines, amended, reconstructed}, ...]
"""
import difflib
import re
import sys
from pathlib import Path

HEADER = re.compile(r"^Claim (\d+) \(([^)]*)\)\s*$")     # "Claim 1 (Currently amended)"
NUMBER_PREFIX = re.compile(r"^\d+\s*\.\s*(?:\([^)]*\)\s*)?")  # "19. " / "1. (Original) "
DEPENDS = re.compile(r"\bclaims?\s+\d+", re.IGNORECASE)   # "of claim 1", "according to claims 1-3"
MARKUP = re.compile(r"\[\+|\[-")                          # [+inserted+] or [-deleted-]
UNCERTAIN = re.compile(r"\[\?(.*?)\?\]")                     # [?uncertain OCR?]
FLAG = "\x01"                                             # marks a word as OCR-uncertain
# OCR noise: uncertain, or shaped like a garbled word ("seeend-", "h--a", "digita4")
NOISE = re.compile(FLAG + r"|^-|-$|--|[a-z]\d|\d[a-z]", re.IGNORECASE)


def split_claims(text):
    """[(number, status, body lines)] for every claim in the file, in order."""
    found = []
    for line in text.splitlines():
        header = HEADER.match(line)
        if header:
            found.append((int(header.group(1)), header.group(2).strip(), []))
        elif found and line.strip():
            found[-1][2].append(line.strip())
    return found


def unwrap(line):
    """Drop the [?...?] OCR markers, keeping the text."""
    return UNCERTAIN.sub(r"\1", line)


def words(line):
    """The line's words as it stands after the filing: deletions dropped, insertions kept,
    and each OCR-uncertain word prefixed with FLAG."""
    line = re.sub(r"\[-.*?-\]", " ", line).replace("[+", "").replace("+]", "")
    line = UNCERTAIN.sub(lambda m: " ".join(FLAG + w for w in m.group(1).split()), line)
    return line.split()


def diff_lines(previous_lines, lines):
    """Mark what changed from previous_lines to lines with [+...+] / [-...-], word by word.
    Line breaks follow `lines`. OCR-noise words are dropped from the changes."""
    old = [w for line in previous_lines for w in words(line)]
    new = []
    for line in lines:
        new += words(line) + ["\n"]
    plain = lambda w: w.replace(FLAG, "")
    a, b = [plain(w) for w in old], [plain(w) for w in new]
    marked = []  # (kind, word) with kind "=", "+" or "-"
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            marked += [("=", w) for w in b[j1:j2]]
            continue
        marked += [("-", plain(w)) for w in old[i1:i2] if not NOISE.search(w)]
        marked += [("+", plain(w)) if w != "\n" else ("=", w)
                   for w in new[j1:j2] if w == "\n" or not NOISE.search(w)]
    out, line, run_kind, run = [], [], None, []

    def flush():
        if run_kind != "=" and len(run) >= 6 and sum(len(w) <= 2 for w in run) > len(run) / 2:
            return  # letters OCR'd one by one ("m o ry sto ra g e"): noise, not a change
        if run:
            text = " ".join(run)
            line.append(text if run_kind == "=" else f"[{run_kind}{text}{run_kind}]")
    for kind, word in marked:
        if word == "\n":
            flush(); run, run_kind = [], None
            if line:
                out.append(" ".join(line))
            line = []
            continue
        if kind != run_kind:
            flush(); run, run_kind = [], kind
        run.append(word)
    flush()
    if line:
        out.append(" ".join(line))
    return out


def claim_map(text):
    """{number: lines} for every claim, with the "1. (Original)" prefix removed."""
    return {number: [NUMBER_PREFIX.sub("", lines[0], count=1)] + lines[1:]
            for number, _, lines in split_claims(text) if lines}


def independent_claims(text, previous_text=None):
    """The independent claims, each {number, status, lines, amended, reconstructed};
    canceled and withdrawn claims are skipped. previous_text (the previous claims
    filing) is used only when this file has no amendment markup of its own."""
    found = split_claims(text)
    has_markup = any(MARKUP.search(line) for _, _, lines in found for line in lines)
    previous = claim_map(previous_text) if previous_text and not has_markup else {}
    result = []
    for number, status, lines in found:
        if not lines or any(word in status.lower() for word in ("cancel", "withdrawn")):
            continue  # canceled or withdrawn: no longer being examined
        lines = [NUMBER_PREFIX.sub("", lines[0], count=1)] + lines[1:]
        if status.lower() in ("", "unknown"):  # first filing: claims carry no status yet
            status = "Original"
        if DEPENDS.search(unwrap(" ".join(lines))):  # refers to another claim -> dependent
            continue
        reconstructed = "amend" in status.lower() and number in previous
        lines = (diff_lines(previous[number], lines) if reconstructed
                 else [unwrap(line) for line in lines])
        result.append({"number": number, "status": status, "lines": lines,
                       "amended": "amend" in status.lower()
                                  or any(MARKUP.search(line) for line in lines),
                       "reconstructed": reconstructed})
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    previous = Path(sys.argv[2]).read_text(encoding="utf-8") if len(sys.argv) > 2 else None
    found = independent_claims(Path(sys.argv[1]).read_text(encoding="utf-8"), previous)
    if not found:
        sys.exit("no independent claims found")
    for claim in found:
        print(f"Claim {claim['number']} ({claim['status']})"
              f"{'  [amended]' if claim['amended'] else ''}"
              f"{'  [reconstructed]' if claim['reconstructed'] else ''}: "
              f"{len(claim['lines'])} lines")
        for line in claim["lines"]:
            print("  " + line)
