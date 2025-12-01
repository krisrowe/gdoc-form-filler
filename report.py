#!/usr/bin/env python3
"""
Generate Markdown reports from form filler JSON results.

Usage:
    # CLI: generate report from JSON file
    python report.py processed_2025-01-01-1200.json

    # Module: generate report from dict
    from report import generate_report
    generate_report(results_dict, doc_id, "output.md")
"""

import argparse
import json
import os
import sys


def generate_report(results: dict, doc_id: str, md_file: str, json_file: str = None) -> None:
    """
    Generate a Markdown report from results dict.

    Args:
        results: The results dict with 'validation' and 'results' keys
        doc_id: Google Doc ID for linking
        md_file: Output markdown file path
        json_file: Optional JSON file path for linking (defaults to md_file with .json extension)
    """
    v = results["validation"]
    r = results["results"]

    # Default json_file to same name as md_file
    if json_file is None:
        json_file = os.path.splitext(md_file)[0] + ".json"

    # Build status counts
    status_counts = {}
    for entry in r:
        status = entry.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    # Build table rows
    rows = []
    for entry in r:
        oid = entry.get("outline_id", "?")
        status = entry.get("status", "unknown")

        def truncate_with_len(text: str, max_len: int = 25) -> str:
            """Truncate text and show length if truncated."""
            if len(text) > max_len:
                return f"`{text[:max_len]}...` ({len(text)})"
            return f"`{text}`" if text else "_(blank)_"

        # Input column - what's in the input file
        input_col = "—"
        if status in ("inserted", "would_insert"):
            val = entry.get('new_answer', entry.get('answer', ''))
            input_col = truncate_with_len(val)
        elif status in ("replaced", "would_replace"):
            input_col = truncate_with_len(entry.get("new_answer", ""))
        elif status == "no_change":
            input_col = truncate_with_len(entry.get("matched_text", ""))
        elif status == "skipped":
            input_col = "_(no answer)_"
        elif status == "not_found":
            input_col = "_(provided)_"
        elif status == "not_in_input":
            input_col = "—"

        # Doc column - what's currently in the doc
        doc_col = "_(blank)_"
        if status in ("replaced", "would_replace"):
            doc_col = truncate_with_len(entry.get("previous_answer", ""))
        elif status == "no_change":
            doc_col = truncate_with_len(entry.get("matched_text", ""))
        elif status == "not_in_input":
            if entry.get("has_answer"):
                doc_col = truncate_with_len(entry.get("existing_answer", ""))
            else:
                doc_col = "_(blank)_"
        elif status in ("inserted", "would_insert"):
            doc_col = "_(blank)_"
        elif status == "skipped":
            if entry.get("existing_answer"):
                doc_col = truncate_with_len(entry.get("existing_answer", ""))
            else:
                doc_col = "_(blank)_"

        # Action column
        action_map = {
            "inserted": "inserted",
            "would_insert": "would insert",
            "replaced": "replaced",
            "would_replace": "would replace",
            "no_change": "no change",
            "skipped": "skipped",
            "not_found": "not found",
            "error": "error",
            "not_in_input": "—",
        }
        action_col = action_map.get(status, status)

        # Details column - warnings, errors, reasons
        details = ""
        if entry.get("warning"):
            details = f"⚠ {entry['warning'][:40]}..."
        elif status == "error":
            details = entry.get("error", "")
        elif status in ("skipped", "not_found"):
            details = entry.get("reason", "")

        rows.append(f"| **{oid}** | {input_col} | {doc_col} | {action_col} | {details} |")

    # Summary
    summary_parts = [f"{s}: {c}" for s, c in sorted(status_counts.items())]

    md = f"""# Form Filler Results

## Links

- [Open Google Doc](https://docs.google.com/document/d/{doc_id}/edit)
- [View JSON]({os.path.basename(json_file)})

## Validation Summary

| Metric | Count |
|--------|-------|
| Document questions | {v['doc_question_count']} |
| Input questions | {v['input_question_count']} |
| Missing in doc | {len(v['missing_in_doc'])} |
| Missing in input | {len(v['missing_in_input'])} |
| Text mismatches | {len(v['text_mismatches'])} |

## Processing Results

| ID | Input | Doc | Action | Details |
|----|-------|-----|--------|---------|
{chr(10).join(rows)}

---

**Total: {len(r)}** | {' | '.join(summary_parts)}
"""

    with open(md_file, 'w') as f:
        f.write(md)


def main():
    parser = argparse.ArgumentParser(
        description="Generate Markdown report from form filler JSON results"
    )
    parser.add_argument(
        "json_file",
        help="Path to the processed JSON results file"
    )
    parser.add_argument(
        "-o", "--output",
        help="Output markdown file (default: same name with .md extension)"
    )
    parser.add_argument(
        "--doc-id",
        help="Google Doc ID (extracted from JSON if not provided)"
    )

    args = parser.parse_args()

    # Load JSON
    with open(args.json_file) as f:
        results = json.load(f)

    # Determine output file
    if args.output:
        md_file = args.output
    else:
        md_file = os.path.splitext(args.json_file)[0] + ".md"

    # Get doc_id - try to extract from results or use provided
    doc_id = args.doc_id
    if not doc_id:
        # Try to find doc_id in the results (if stored there)
        doc_id = results.get("doc_id", "UNKNOWN_DOC_ID")

    generate_report(results, doc_id, md_file, args.json_file)
    print(f"Report: {md_file}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
