import argparse
import json
import re
from pathlib import Path

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
    ap.add_argument("--from-summaries", action="store_true",
                    help="reuse the saved timeline.json and text/: skip fetching, organizing and "
                         "parsing, and start at the summaries (delete files in summaries/ to redo them)")
    args = ap.parse_args()
    try:
        if args.from_summaries:
            out = Path(args.out or Path(DEFAULT_OUT_ROOT) / re.sub(r"\D", "", args.application))
            path = out / "timeline.json"
            if not path.exists():
                raise ValueError(f"{path} not found; run without --from-summaries first.")
            timeline = json.loads(path.read_text(encoding="utf-8"))
            if not any(e.get("text_file") for e in timeline["timeline"]):
                raise ValueError(f"{path} has no parsed text; run without --from-summaries first.")
            summarize_and_render(timeline, out)
            return

        # fetch the application data
        result = fetch_uspto.run(args.application, args.out, args.codes, args.formats,
                                 args.list_only)
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
        (result["out"] / "timeline.json").write_text(  # keep the text links if summarizing crashes
            json.dumps({k: timeline[k] for k in ("case", "entry_count", "timeline")}, indent=2))

        summarize_and_render(timeline, result["out"])

    except ValueError as e:
        raise SystemExit(str(e))


def summarize_and_render(timeline, out):
    """Messages for every timeline entry, then timeline.json, conversation.json and
    conversation.html in `out`. Entries need their "text_file" set (the parse step)."""
    # messages: fixed sentence for milestone/cover codes (see summarizer.BOILERPLATE);
    # the rest are left for the AI summary step
    for entry in timeline["timeline"]:
        entry["message"] = summarizer.boilerplate(entry, timeline["case"])
    needs_ai = []
    for entry in timeline["timeline"]:
        if entry["message"] is not None:
            continue
        if entry.get("text_file"):
            needs_ai.append(entry)
        else:  # no fixed sentence and no document text: nothing to summarize
            print(f"no text for {entry['date']} {entry['code']}; skipped")
    for n, entry in enumerate(needs_ai, 1):  # spaced to 5/min; cached summaries are instant
        print(f"summarizing {n}/{len(needs_ai)}: {entry['date']} {entry['code']}")
        entry["message"] = summarizer.summarize(entry)
    (out / "timeline.json").write_text(
        json.dumps({k: timeline[k] for k in ("case", "entry_count", "timeline")}, indent=2))

    # conversation: one {date, sender, message} per entry
    messages = conversation.build_conversation(timeline, out / "conversation.json")
    # chat page: conversation.html, a text-message view of the same messages
    chat_view.render(messages, timeline["case"], out / "conversation.html")


if __name__ == "__main__":
    main()
