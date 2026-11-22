"""Pull the rejection table out of an office action's text (no AI needed).

Usage:  python3 rejections.py <office action text file>
  e.g.  python3 rejections.py example/data/18909470/text/text-M97JD5LWWFYGX54.txt

Examiners state each rejection with a standard USPTO form paragraph, e.g.
  Claims 5-9 and 13 are rejected under 35 U.S.C. 103 as being unpatentable over Lu in
  view of "A Real-World Web Agent ..." by Gur et al. (hereinafter "Gur").
extract() turns those sentences into rows {statute, ground, claims, references} and
collects the cited references {short, citation} for 102 / 103 rejections.

From another script (e.g. conversation.py):
  import rejections
  breakdown = rejections.extract(text)   # {"rejections": [...], "references": [...]} or None
"""
import re
import sys
from pathlib import Path

# "Claims 1-18 are rejected under 35 U.S.C. 102(a)(1) ..." (also "Claim 16 is ...")
STATEMENT = re.compile(r"\bClaims?\s+(?P<claims>[\w ,\-–]+?)\s+(?:is|are)\s+(?:also\s+)?"
                       r"rejected under 35 U\.?\s?S\.?\s?C\.?\s*§?\s*"
                       r"(?P<statute>\d{3}(?:\s?\([a-z0-9]+\))*)(?P<rest>.*)")
# "... as being anticipated by X" / "... as being unpatentable over X" / "... as being indefinite"
GROUND = re.compile(r"\bas (?:being )?(?:an? )?(?P<ground>[a-z][a-z -]*?)\s+(?:by|over|for)\b")
PRIOR_ART = re.compile(r"\b(?:anticipated by|unpatentable over|obvious over)\s+(?P<refs>.*)")
HEADING_NOTE = re.compile(r"\(([^)]+)\)\s*$")           # "## ... § 101 (Abstract idea)"
QUOTED = re.compile(r"[“\"][^”\"]*[”\"]")                # a quoted (non-patent) title
HEREINAFTER = re.compile(r",?\s*\(?\s*hereinafter,?\s*[“\"']?([^”\"')]+)[”\"']?\s*\)?", re.I)
SPLIT_REFS = re.compile(r",?\s+(?:and\s+)?further in view of\s+|\s+in view of\s+|,?\s+and\s+")
# US patent / publication numbers: "US 10,123,456 B2", "US 2020/0123456 A1", "U.S. Pat. No. 9,876,543"
PATENT_NO = re.compile(r"\bU\.?S\.?\s*(?:Pat(?:ent)?\.?\s*(?:Pub(?:lication)?\.?\s*)?No\.?\s*)?"
                       r"(\d{4}/\d{7}|\d{1,2},\d{3},\d{3}|\d{7,11})(?:\s*([AB]\d))?")


def protect_quotes(text):
    """Swap quoted titles for placeholders, so their periods and 'and's are left alone."""
    saved = []
    def keep(match):
        saved.append(match.group(0))
        return f"\x00{len(saved) - 1}\x00"
    return QUOTED.sub(keep, text), saved


def restore_quotes(text, saved):
    return re.sub(r"\x00(\d+)\x00", lambda m: saved[int(m.group(1))], text)


def first_sentence(text):
    """Text up to the first full stop that isn't part of 'et al.', 'e.g.', 'i.e.' or 'No.'."""
    for match in re.finditer(r"\.(?=\s|$)", text):
        before = text[:match.start()]
        if not re.search(r"(?:\bet al|\be\.g|\bi\.e|\bNo|\bPat|\bPub|\bU\.S|\bU\.S\.C)$", before):
            return before
    return text


def short_name(citation):
    """'Smith et al. (US 2020/0123456 A1)' -> 'Smith' (used when there's no 'hereinafter')."""
    name = re.split(r"\s+et al\b|\s*\(|,", citation, maxsplit=1)[0]
    return name.strip(" .") or citation


def split_references(clause, references):
    """Short names cited in one rejection, in order; new references are added to `references`."""
    clause, saved = protect_quotes(clause)
    clause = first_sentence(clause)       # stop at the end of the rejection statement
    names = []
    for piece in SPLIT_REFS.split(clause):
        piece = restore_quotes(piece, saved).strip(" ,;")
        if not piece:
            continue
        alias = HEREINAFTER.search(piece)
        if alias:                                    # defines a reference: '"Title" by Lu et al. (hereinafter "Lu")'
            short, citation = alias.group(1).strip(), HEREINAFTER.sub("", piece).strip(" ,")
        elif piece in references or not (QUOTED.search(piece) or PATENT_NO.search(piece)):
            short, citation = piece, None            # a short name defined earlier: 'Lu'
        else:                                        # a patent cited without an alias
            short, citation = short_name(piece), piece
        if citation and short not in references:
            references[short] = citation
        names.append(short)
    return names


def extract(text):
    """Rejection rows and cited references from an office action's text; None if no rejections."""
    rows, references, heading = [], {}, ""
    for line in text.splitlines():
        if line.startswith("## "):
            heading = line
            continue
        match = STATEMENT.search(line)
        if not match:
            continue
        statute = re.sub(r"\s+", "", match.group("statute"))
        rest, saved = protect_quotes(match.group("rest"))
        ground = GROUND.search(first_sentence(rest))
        note = HEADING_NOTE.search(heading)
        ground = ground.group("ground") if ground else (note.group(1).lower() if note else "")
        refs = []
        if statute.startswith(("102", "103")):
            prior_art = PRIOR_ART.search(restore_quotes(rest, saved))
            if prior_art:
                refs = split_references(prior_art.group("refs"), references)
        row = {"statute": statute, "ground": ground.strip(),
               "claims": re.sub(r"\s+", " ", match.group("claims")).strip(), "references": refs}
        if row not in rows:  # final actions can repeat a statement
            rows.append(row)
    if not rows:
        return None
    return {"rejections": rows,
            "references": [{"short": s, "citation": c} for s, c in references.items()]}


def patent_links(citation):
    """[(number text, Google Patents URL)] for each US patent / publication number in a citation."""
    links = []
    for match in PATENT_NO.finditer(citation):
        number = re.sub(r"[^\d]", "", match.group(1))
        links.append((match.group(0), f"https://patents.google.com/patent/US{number}{match.group(2) or ''}"))
    return links


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    found = extract(Path(sys.argv[1]).read_text(encoding="utf-8"))
    if not found:
        sys.exit("no rejections found")
    print(f"{'STATUTE':12} {'GROUND':18} {'CLAIMS':14} REFERENCES")
    for r in found["rejections"]:
        print(f"§ {r['statute']:10} {r['ground'][:18]:18} {r['claims'][:14]:14} "
              f"{' + '.join(r['references']) or '-'}")
    for ref in found["references"]:
        print(f"\n{ref['short']}: {ref['citation']}")
