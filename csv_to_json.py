#!/usr/bin/env python3
"""
Convert CSV export from Google Sheets to JSON format for form_filler.py

Expected CSV columns:
- #: Main bullet number (1, 2, 12, etc.)
- ##: Sub-bullet letter (a, b, c, etc.) - may be blank
- Question: The question text (used for validation)
- Answer: The answer text

Additional columns are ignored.

Output format is an array of question objects:
{
  "questions": [
    {
      "id": "1",
      "question": "What is your name?",
      "answer": "John Smith"
    },
    {
      "id": "3",
      "question": "Contact info:",
      "questions": [
        {"id": "a", "question": "Email?", "answer": "jane@acme.com"},
        {"id": "b", "question": "Phone?", "answer": "555-1234"}
      ]
    }
  ]
}
"""

import argparse
import csv
import json
import sys
from collections import OrderedDict


def csv_to_answers(csv_path: str) -> list:
    """
    Read CSV and convert to array of question objects.

    Returns list of question objects, each with id, optional question text,
    optional answer, and optional nested questions array.
    """
    # Use OrderedDict to preserve insertion order and allow lookup by id
    questions_map = OrderedDict()

    with open(csv_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)

        fieldnames = reader.fieldnames
        if not fieldnames:
            raise ValueError("CSV file has no headers")

        # Map expected columns - try exact match first, then case-insensitive
        def find_column(names, *candidates):
            for name in names:
                if name in candidates:
                    return name
                if name.lower() in [c.lower() for c in candidates]:
                    return name
            return None

        num_col = find_column(fieldnames, '#', 'Number', 'Num')
        sub_col = find_column(fieldnames, '##', 'Sub', 'SubNumber')
        question_col = find_column(fieldnames, 'Question', 'Q')
        answer_col = find_column(fieldnames, 'Answer', 'A', 'Response')

        if not num_col:
            raise ValueError("CSV must have a '#' column for main bullet number")
        if not answer_col:
            raise ValueError("CSV must have an 'Answer' column")

        for row in reader:
            main_id = row.get(num_col, '').strip()
            sub_id = row.get(sub_col, '').strip() if sub_col else ''
            question_text = row.get(question_col, '').strip() if question_col else ''
            answer = row.get(answer_col, '').strip()

            # Skip rows without a main number
            if not main_id:
                continue

            # Ensure the main question entry exists
            if main_id not in questions_map:
                questions_map[main_id] = {"id": main_id}

            if sub_id:
                # This is a sub-question
                if "questions" not in questions_map[main_id]:
                    questions_map[main_id]["questions"] = OrderedDict()

                sub_entry = {"id": sub_id}
                if question_text:
                    sub_entry["question"] = question_text
                if answer:
                    sub_entry["answer"] = answer

                questions_map[main_id]["questions"][sub_id] = sub_entry
            else:
                # This is a top-level question
                if question_text:
                    questions_map[main_id]["question"] = question_text
                if answer:
                    questions_map[main_id]["answer"] = answer

    # Convert to array format
    result = []
    for q in questions_map.values():
        # Convert sub-questions from OrderedDict to list
        if "questions" in q:
            q["questions"] = list(q["questions"].values())
        result.append(q)

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert CSV to JSON for form_filler.py"
    )
    parser.add_argument(
        "csv_file",
        help="Input CSV file path"
    )
    parser.add_argument(
        "-o", "--output",
        help="Output JSON file path (default: stdout)"
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        default=True,
        help="Pretty-print JSON output (default: true)"
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Compact JSON output (no indentation)"
    )

    args = parser.parse_args()

    try:
        questions = csv_to_answers(args.csv_file)

        output = {"questions": questions}

        indent = None if args.compact else 2
        json_str = json.dumps(output, indent=indent, ensure_ascii=False)

        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(json_str)
                f.write('\n')
            print(f"Wrote {len(questions)} top-level questions to {args.output}", file=sys.stderr)
        else:
            print(json_str)

        return 0

    except FileNotFoundError:
        print(f"Error: File not found: {args.csv_file}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
