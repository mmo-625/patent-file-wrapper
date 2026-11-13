"""Turn USPTO document XML (claims, remarks, office actions, notices) into clean text.

Usage:  python3 xml_parser.py <file.xml | archive.tar> [more files ...]
  Writes ./out/text-<documentId>.txt for each XML. documentId is the folder the XML
  sits in (e.g. M97JD5LWWFYGX54). XMLs inside a .tar are read in memory, not extracted.

Output: one paragraph per line; section headings start with "## ";
amendments are marked [+inserted+] and [-deleted-].
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
        "ClaimNumber", "ClaimStatusCategory"}                 # shown in the claim header
BLOCK = {"P", "LI", "ClaimText", "TableRow", "Heading", "Br"}     # each starts a new line
MARK = {"Ins": "ins", "Del": "del", "S": "del"}               # S = strikethrough
PASS = {"ClaimsDocument", "IncomingDocument", "OutgoingDocument",  # keep text, recurse
        "Claims", "FormParagraph", "DataField", "GeneralText", "OL",
        "DataTable", "DataTableBody", "TableHeaderCell",
        "OCRConfidenceData", "ClaimReference", "B", "I", "U", "Sub", "Sup", "Font"}
MARKERS = {"ins": ("[+", "+]"), "del": ("[-", "-]")}
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


def render(elem, mode, unknown):
    """Walk an element and return (kind, text) segments.

    kind is 'plain', 'ins', 'del', or 'break' (start a new line). A child's tail text
    belongs to the *parent*, so it keeps `mode`. Unknown tags are kept as text and
    counted in `unknown`.
    """
    out = [(mode, elem.text)] if elem.text else []
    for child in elem:
        name = local(child.tag)
        if name in SKIP:
            pass
        elif name == "Image":  # an unreadable region the OCR stored as a picture
            out.append(("plain", " [unreadable image] "))
        elif name in BLOCK:
            prefix = [("plain", "## ")] if is_heading(child) else []
            out += [("break", "")] + prefix + render(child, mode, unknown) + [("break", "")]
        elif name in MARK:
            out += render(child, MARK[name], unknown)
        else:
            if name not in PASS:
                unknown[name] += 1
            out += render(child, mode, unknown)
        if child.tail:
            out.append((mode, child.tail))
    return out


def to_text(segments):
    """Merge OCR fragments ([+u+][+ser+] -> [+user+]), add markup, return tidy lines.

    Returns (lines, insertions, deletions).
    """
    merged = []
    for kind, text in segments:
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
    return lines, sum(k == "ins" for k, _ in merged), sum(k == "del" for k, _ in merged)


def document_lines(root, unknown):
    """Return (lines, insertions, deletions) for a whole document.

    Claims documents get a "Claim N (status)" header per claim and a blank line
    between claims; every other document is rendered paragraph by paragraph.
    """
    if local(root.tag) != "ClaimsDocument":
        return to_text(render(root, "plain", unknown))
    lines, n_ins, n_del = [], 0, 0
    for claim in (e for e in root.iter() if local(e.tag) == "Claim"):
        fields = {local(c.tag): (c.text or "").strip() for c in claim}
        body, ins, dels = to_text(render(claim, "plain", unknown))
        if body:  # drop the "1.  (Currently Amended)" prefix; the header already says it
            body[0] = CLAIM_PREFIX.sub("", body[0])
        lines += ["", f"Claim {fields.get('ClaimNumber', '?')} "
                      f"({fields.get('ClaimStatusCategory', 'unknown')})"] + body
        n_ins, n_del = n_ins + ins, n_del + dels
    return lines[1:], n_ins, n_del


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
    out_path.write_text(f"Source: {label}\nType: {local(root.tag)}\n"
                        f"Markup: [+inserted+]  [-deleted-]\n\n{body}\n", encoding="utf-8")

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
