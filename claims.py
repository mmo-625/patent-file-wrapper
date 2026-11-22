"""Pick the independent claims out of a parsed claims (CLM) text file (no AI needed).

Usage:  python3 claims.py <claims text file>
  e.g.  python3 claims.py example/data/18909470/text/text-MHNVZFKJ4X45X46.txt

Reads the text xml_parser.py writes for a claims XML:
  Claim 1 (Currently amended)
  A system for ..., comprising:
  [+a processor; and+]            <- amendments marked [+inserted+] / [-deleted-]
  ...
A claim is independent when it doesn't refer back to another claim ("of claim 1").
Canceled and withdrawn claims are skipped.

From another script (e.g. conversation.py):
  import claims
  found = claims.independent_claims(text)   # [{number, status, lines, amended}, ...]
"""
import re
import sys
from pathlib import Path

HEADER = re.compile(r"^Claim (\d+) \(([^)]*)\)\s*$")     # "Claim 1 (Currently amended)"
NUMBER_PREFIX = re.compile(r"^\d+\s*\.\s*(?:\([^)]*\)\s*)?")  # "19. " / "1. (Original) "
DEPENDS = re.compile(r"\bclaims?\s+\d+", re.IGNORECASE)   # "of claim 1", "according to claims 1-3"
MARKUP = re.compile(r"\[\+|\[-")                          # [+inserted+] or [-deleted-]


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


def independent_claims(text):
    """The independent claims, each {number, status, lines, amended}; canceled and
    withdrawn claims are skipped."""
    result = []
    for number, status, lines in split_claims(text):
        if not lines or any(word in status.lower() for word in ("cancel", "withdrawn")):
            continue  # canceled or withdrawn: no longer being examined
        lines = [NUMBER_PREFIX.sub("", lines[0], count=1)] + lines[1:]
        if status.lower() in ("", "unknown"):  # first filing: claims carry no status yet
            status = "Original"
        if DEPENDS.search(" ".join(lines)):  # refers to another claim -> dependent
            continue
        result.append({"number": number, "status": status, "lines": lines,
                       "amended": "amend" in status.lower()
                                  or any(MARKUP.search(line) for line in lines)})
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    found = independent_claims(Path(sys.argv[1]).read_text(encoding="utf-8"))
    if not found:
        sys.exit("no independent claims found")
    for claim in found:
        print(f"Claim {claim['number']} ({claim['status']})"
              f"{'  [amended]' if claim['amended'] else ''}: {len(claim['lines'])} lines")
        print("  " + claim["lines"][0][:100])
