"""Turn USPTO document XML (claims, remarks, office actions, notices) into clean text.

Usage:  python3 xml_parser.py <file.xml | archive.tar> [more files ...]
  Writes ./out/text-<documentId>.txt for each XML. documentId is the folder the XML
  sits in (e.g. M97JD5LWWFYGX54). XMLs inside a .tar are read in memory, not extracted.

Output: one paragraph per line; section headings start with "## ";
amendments are marked [+inserted+] and [-deleted-].

Claims come in three XML formats, depending on when they were filed:
  uspat:ClaimsDocument   ~2017+       amendments tagged Ins / Del
  pat:ClaimsDocument     ~2012-2017   amendments tagged InsertedText / DeletedText,
                                      when USPTO's OCR caught them
  us-patent-application  before 2012 scanned; amendments not tagged at all
In the two older formats, a claims file with no tagged amendments marks OCR-uncertain
text as [?...?] (often garbled struck-through words). claims.py uses that to rebuild
the amendments by comparing with the previous claims filing.
"""
import re
import sys
import tarfile
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path, PurePosixPath

# --- Rules table: what to do with each element (matched by local tag name) ----------
SKIP = {"DocumentMetadata",                                   # read separately, not body text
        "BoundaryDataBag", "BoundaryDataReference",           # page headers / footers
        "SpannedBoundaryData",
        "FormParagraphNumber", "FormParagraphCategory",       # form-paragraph labels
        "RelatedFormParagraph",
        "ClaimNumber", "ClaimStatusCategory",                 # shown in the claim header
        "ClaimTypeCategory",                                  # "Independent" / "Dependent"
        "BoundaryData", "boundary-data"}                      # older formats: margin line
                                                              # numbers, page headers
BLOCK = {"P", "LI", "ClaimText", "TableRow", "Heading", "Br",     # each starts a new line
         "claim-text"}
MARK = {"Ins": "ins", "Del": "del", "S": "del",               # S = strikethrough
        "InsertedText": "ins", "DeletedText": "del"}          # ~2012-2017 claims format
OCR = {"OCRConfidenceData", "confidence"}                     # text the OCR was unsure of
PASS = {"ClaimsDocument", "IncomingDocument", "OutgoingDocument",  # keep text, recurse
        "Claims", "FormParagraph", "DataField", "GeneralText", "OL",
        "DataTable", "DataTableBody", "TableHeaderCell",
        "ClaimReference", "B", "I", "U", "Sub", "Sup", "Font",
        "claims", "claim-ref"} | OCR
MARKERS = {"ins": ("[+", "+]"), "del": ("[-", "-]")}
OLD_CLAIMS = {"pat:ClaimsDocument", "us-patent-application"}  # see the docstring
FOOTER = re.compile(r"LAW OFFICES|Page \d+ of \d+", re.IGNORECASE)  # OCR'd page footers
CLAIM_PREFIX = re.compile(r"^\d+\s*\.\s*\([^)]*\)\s*")              # "1.  (Original) "


def local(tag):
    """'{urn:...}ClaimText' -> 'ClaimText', so namespace prefixes don't matter."""
    return tag.rsplit("}", 1)[-1]


def is_heading(elem):
    """A <Heading>, or a short <P> whose only text is bold/italic/underlined."""
    name = local(elem.tag)
    if name == "Heading":
        return True
    if name != "P" or (elem.text or "").strip():
        return False
    if any((c.tail or "").strip() for c in elem):
        return False
    styled = [c for c in elem if local(c.tag) not in SKIP]
    if not styled or any(local(c.tag) not in ("B", "I", "U") for c in styled):
        return False
    return len("".join(elem.itertext()).strip()) < 100


def render(elem, mode, unknown, ocr=False):
    """Walk an element and return (kind, text) segments.

    kind is 'plain', 'ins', 'del', or 'break' (start a new line). A child's tail text
    belongs to the *parent*, so it keeps `mode`. Unknown tags are kept as text and
    counted in `unknown`. With ocr=True, OCR-uncertain text is wrapped as [?...?].
    """
    out = [(mode, elem.text)] if elem.text else []
    for child in elem:
        name = local(child.tag)
        if name in SKIP:
            if name in ("BoundaryData", "boundary-data"):
                out.append((mode, " "))  # a margin number sat between two words
        elif name == "Image":  # an unreadable region the OCR stored as a picture
            out.append(("plain", " [unreadable image] "))
        elif name in BLOCK:
            prefix = [("plain", "## ")] if is_heading(child) else []
            out += [("break", "")] + prefix + render(child, mode, unknown, ocr) + [("break", "")]
        elif name in MARK:
            out += render(child, MARK[name], unknown, ocr)
        elif name in OCR and ocr:
            out += [(mode, "[?")] + render(child, mode, unknown, ocr) + [(mode, "?]")]
        else:
            if name not in PASS:
                unknown[name] += 1
            out += render(child, mode, unknown, ocr)
        if child.tail:
            out.append((mode, child.tail))
    return out


def to_text(segments):
    """Merge OCR fragments ([+u+][+ser+] -> [+user+]), add markup, return tidy lines.

    Returns (lines, insertions, deletions).
    """
    merged = []
    for kind, text in segments:
        text = text.replace("\n", " ")  # raw line breaks are OCR layout; breaks come from tags
        if kind in MARKERS and not text.strip():
            kind = "plain"  # an inserted/deleted space isn't worth marking
        if merged and merged[-1][0] == kind != "break":
            merged[-1][1] += text
        else:
            merged.append([kind, text])
    parts = []
    for kind, text in merged:
        if kind == "break":
            parts.append("\n")
        elif kind in MARKERS:
            # Keep surrounding spaces outside the markers: "[+actions on a+] software".
            core = text.strip()
            lead, trail = text[:len(text) - len(text.lstrip())], text[len(text.rstrip()):]
            parts.append(f"{lead}{MARKERS[kind][0]}{core}{MARKERS[kind][1]}{trail}")
        else:
            parts.append(text)
    lines = (re.sub(r"\s+", " ", line).strip() for line in "".join(parts).split("\n"))
    lines = [line for line in lines if line and line != "##"]
    lines = [re.sub(r"\[\?\s*\?\]", "", line) for line in lines]  # empty [? ?] left by spaces
    return lines, sum(k == "ins" for k, _ in merged), sum(k == "del" for k, _ in merged)


def claim_elements(root):
    """(number, status, element) for each numbered claim, in any of the claims formats."""
    for elem in root.iter():
        name = local(elem.tag)
        if name == "Claim":  # ST.96 formats: number and status are child elements
            fields = {local(c.tag): (c.text or "").strip() for c in elem}
            number = fields.get("ClaimNumber", "")
            status = fields.get("ClaimStatusCategory", "")
        elif name == "claim":  # pre-2012 format: attributes
            number, status = elem.get("num", ""), elem.get("claim-type", "")
        else:
            continue
        if number.isdigit():  # skips UNKNOWN-... entries (page headings like "CLAIMS")
            yield number, status or "unknown", elem


def document_lines(root, unknown, ocr=None):
    """Return (lines, insertions, deletions) for a whole document.

    Claims documents get a "Claim N (status)" header per claim and a blank line
    between claims; every other document is rendered paragraph by paragraph.
    ocr=None decides by itself: an older-format claims file with no tagged amendments
    is rendered again with OCR-uncertain text marked [?...?].
    """
    if local(root.tag) not in ("ClaimsDocument", "us-patent-application"):
        return to_text(render(root, "plain", unknown))
    lines, n_ins, n_del = [], 0, 0
    for number, status, claim in claim_elements(root):
        body, ins, dels = to_text(render(claim, "plain", unknown, bool(ocr)))
        if body:  # drop the "1.  (Currently Amended)" prefix; the header already says it
            body[0] = CLAIM_PREFIX.sub("", body[0])
        lines += ["", f"Claim {number} ({status})"] + body
        n_ins, n_del = n_ins + ins, n_del + dels
    if ocr is None and not (n_ins or n_del) and claims_format(root) in OLD_CLAIMS:
        return document_lines(root, Counter(), ocr=True)
    return lines[1:], n_ins, n_del


def claims_format(root):
    """'uspat:ClaimsDocument', 'pat:ClaimsDocument' or 'us-patent-application'.
    Both ClaimsDocument formats share a namespace; only the newer one uses WIPO ST.96 tags."""
    name = local(root.tag)
    if name == "ClaimsDocument":
        st96 = any(elem.tag.startswith("{http://www.wipo.int/") for elem in root.iter())
        return ("uspat:" if st96 else "pat:") + name
    return name


def xml_sources(arg):
    """Yield (label, path inside source, xml bytes) for an XML file or each XML in a tar.

    Tar is detected by content, not extension: USPTO "XML" downloads are tar archives
    even when saved with a .xml name.
    """
    path = Path(arg)
    if tarfile.is_tarfile(path):
        with tarfile.open(path) as tf:
            for member in tf.getmembers():
                if member.isfile() and member.name.lower().endswith(".xml"):
                    yield f"{path}:{member.name}", PurePosixPath(member.name), \
                        tf.extractfile(member).read()
    else:
        yield str(path), path, path.read_bytes()


def convert(label, inner_path, data, out_dir="out"):
    """Parse one XML document, write <out_dir>/text-<id>.txt, print a summary, return the path."""
    root = ET.fromstring(data)
    unknown = Counter()
    lines, n_ins, n_del = document_lines(root, unknown)
    # Blank line before each heading, so sections stand out.
    body = "\n".join(("\n" + line) if line.startswith("## ") and i else line
                     for i, line in enumerate(lines))
    doc_id = inner_path.parent.name or inner_path.stem
    out_path = Path(out_dir) / f"text-{doc_id}.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    markup = "[+inserted+]  [-deleted-]"
    if any("[?" in line for line in lines):
        markup += "  [?uncertain OCR?]"
    out_path.write_text(f"Source: {label}\nType: {local(root.tag)}\n"
                        f"Markup: {markup}\n\n{body}\n", encoding="utf-8")

    footers = [line for line in lines if FOOTER.search(line)]
    print(f"{label}\n  -> {out_path}: {len(lines)} lines, "
          f"{sum(line.startswith('## ') for line in lines)} headings, "
          f"{n_ins} insertions, {n_del} deletions")
    print("  unrecognized elements: " +
          (", ".join(f"{k} x{v}" for k, v in unknown.items()) or "none"))
    for line in footers:  # OCR text from page footers that ended up in the body
        print(f"  possible page-footer text: {line[:80]}")
    return out_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for arg in sys.argv[1:]:
        for label, inner_path, data in xml_sources(arg):
            convert(label, inner_path, data)
