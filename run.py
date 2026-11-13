import argparse
import json

import chat_view
import conversation
import fetch_uspto
import organize
import parser
import summarizer
from fetch_uspto import DEFAULT_FORMATS, DEFAULT_OUT_ROOT




def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("application", help="application number, e.g. 18909470 or 18/909,470")
    ap.add_argument("--out", help=f"output folder (default {DEFAULT_OUT_ROOT}/<application number>)")
    ap.add_argument("--codes", nargs="*", help="download only these document codes (overrides ALLOWED_CODES)")
    ap.add_argument("--formats", nargs="*", default=DEFAULT_FORMATS,
                    help="format preference order (default: XML MS_WORD PDF)")
    ap.add_argument("--list-only", action="store_true", help="save JSON and manifest, skip file downloads")
    args = ap.parse_args()
    try:
        # fetch the application data
        result = fetch_uspto.run(args.application)
        # result["out"]        -> Path("example/data/18909470")
        # result["wrapper"]    -> wrapper JSON (also saved as wrapper.json)
        # result["documents"]  -> documents JSON (also saved as documents.json)
        # result["manifest"]   -> list of rows, each with "path" relative to out

        # organize application timeline
        timeline = organize.build_timeline(result["wrapper"], result["documents"], result["manifest"],
                                        files_root=result["out"],
                                        out_path=result["out"] / "timeline.json",
                                        verbose=True)       
        # parse files: one text file per downloaded document, linked back into the timeline
        text_dir = result["out"] / "text"
        for entry in timeline["timeline"]:
            if not entry.get("file"):  # filing/events, or a document that wasn't downloaded
                continue
            paths = parser.to_text(entry["file"], out_dir=text_dir)
            entry["text_file"] = str(paths[0]) if paths else None

        # messages: fixed sentence for milestone/cover codes (see summarizer.BOILERPLATE);
        # the rest are left for the AI summary step
        for entry in timeline["timeline"]:
            entry["message"] = summarizer.boilerplate(entry, timeline["case"])
        needs_ai = [e for e in timeline["timeline"] if e["message"] is None]
        for n, entry in enumerate(needs_ai, 1):  # spaced to 5/min; cached summaries are instant
            print(f"summarizing {n}/{len(needs_ai)}: {entry['date']} {entry['code']}")
            entry["message"] = summarizer.summarize(entry)
        (result["out"] / "timeline.json").write_text(
            json.dumps({k: timeline[k] for k in ("case", "entry_count", "timeline")}, indent=2))

        # conversation: one {date, sender, message} per entry
        messages = conversation.build_conversation(timeline, result["out"] / "conversation.json")
        # chat page: conversation.html, a text-message view of the same messages
        chat_view.render(messages, timeline["case"], result["out"] / "conversation.html")


    except ValueError as e:
        raise SystemExit(str(e))


if __name__ == "__main__":
    main()
