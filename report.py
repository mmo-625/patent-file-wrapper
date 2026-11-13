"""Terminal summary for organize.py: case header, timeline table, filter stats."""


def print_report(case, timeline, out_path, total_docs, skipped_docs, dropped_dupes,
                 total_events, skipped_events, unrecognized):
    """Print everything organize.py found, filtered out, or didn't recognize.

    case            dict of case-level fields (applicationNumberText, inventionTitle, ...)
    timeline        sorted list of timeline entries
    out_path        where timeline.json was written
    total_docs      number of documents in the documents file
    skipped_docs    Counter of document code -> count removed by the whitelist
    dropped_dupes   list of same-day duplicate documents removed
    total_events    number of events in the wrapper
    skipped_events  number of events removed by the whitelist
    unrecognized    list of notes about unexpected or missing data
    """
    # Case header: the title on the first line, then every other case field.
    print(f"Application {case['applicationNumberText']}: {case['inventionTitle']}")
    for field, value in case.items():
        if field not in ("applicationNumberText", "inventionTitle"):
            print(f"  {field:34} {value}")

    # Readable table of the timeline.
    print(f"\n{'DATE':10}  {'SOURCE':16}  {'CODE':10}  DESCRIPTION")
    print("-" * 90)
    for entry in timeline:
        desc = entry["description"] or ""
        if entry["pages"]:
            desc += f" ({entry['pages']} pp)"
        print(f"{entry['date']:10}  {entry['source']:16}  {str(entry['code']):10}  {desc[:60]}")
    print(f"\n{len(timeline)} entries written to {out_path}")

    # What the whitelists and duplicate rule removed, so the filtering is visible.
    kept_docs = total_docs - sum(skipped_docs.values()) - len(dropped_dupes)
    print(f"\nDocuments: kept {kept_docs} of {total_docs}. Filtered out by code:")
    print("  " + ", ".join(f"{c} x{n}" for c, n in sorted(skipped_docs.items(), key=str)))
    print(f"Same-day duplicates dropped (no page count): {len(dropped_dupes)}")
    for note in dropped_dupes:
        print("  -", note)
    print(f"Events: kept {total_events - skipped_events}, filtered out {skipped_events}.")

    # Anything unexpected, instead of dropping it silently.
    print(f"\nUnrecognized / missing ({len(unrecognized)}):" if unrecognized
          else "\nNothing unrecognized.")
    for note in unrecognized:
        print("  -", note)
