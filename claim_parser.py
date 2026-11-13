"""Turn a USPTO claims XML (CLM) into readable, marked-up plain text.

Usage:  python3 claim_parser.py <claims.xml> [out.txt]
  out.txt defaults to ./out/claims-<documentId>.txt

Amendment markup in the output:  [+inserted text+]  [-deleted text-]
Each claim limitation (<ClaimText>) goes on its own line.
The parsing itself lives in xml_parser.py (same folder); this adds the claims header
and summary.
"""
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from xml_parser import document_lines, local

# Step 1: parse the file and read the document metadata for the header.
src = Path(sys.argv[1]) if len(sys.argv) > 1 else sys.exit(__doc__)
root = ET.parse(src).getroot()
if local(root.tag) != "ClaimsDocument":
    sys.exit(f"not a claims document ({local(root.tag)}); use xml_parser.py instead")
doc_id = next((v for k, v in root.attrib.items() if local(k) == "id"), src.stem)
meta = {local(e.tag): (e.text or "").strip() for e in root.iter()
        if local(e.tag) in ("DocumentCode", "ApplicationNumberText", "OfficialDate")}
out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(f"out/claims-{doc_id}.txt")

# Step 2: render the claims (shared logic in xml_parser.py) and count statuses.
unknown = Counter()
lines, n_ins, n_del = document_lines(root, unknown)
claims = [e for e in root.iter() if local(e.tag) == "Claim"]
statuses = Counter(next((c.text.strip() for c in claim
                         if local(c.tag) == "ClaimStatusCategory" and c.text), "unknown")
                   for claim in claims)

# Step 3: write the text file.
header = (f"Claims document {doc_id} - {meta.get('DocumentCode', '?')} - application "
          f"{meta.get('ApplicationNumberText', '?')} - {meta.get('OfficialDate', '?')}\n"
          f"Markup: [+inserted+]  [-deleted-]")
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(header + "\n\n" + "\n".join(lines) + "\n", encoding="utf-8")

# Step 4: print a short summary, including anything we didn't recognize.
print(f"{len(claims)} claims written to {out_path}")
print("  by status: " + ", ".join(f"{s} x{n}" for s, n in statuses.items()))
print(f"  insertions: {n_ins}, deletions: {n_del}, "
      f"unreadable images: {sum(1 for e in root.iter() if local(e.tag) == 'Image')}")
print("  unrecognized elements: " + (", ".join(f"{k} x{v}" for k, v in unknown.items())
                                     or "none"))
