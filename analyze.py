#!/usr/bin/env python3
"""
Analyze a Google Doc form structure against expected questions.

Outputs a flat JSON structure showing where each question was found
in the document and whether the question text matched expectations.
"""

import argparse
import json
import logging
import os
import sys

from dotenv import load_dotenv
import google.auth
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Load environment variables from .env file (if present)
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/documents.readonly"]


def load_credentials():
    """Load credentials using Application Default Credentials.

    Credentials are loaded from (in order):
    1. GOOGLE_APPLICATION_CREDENTIALS environment variable (path to token file)
    2. gcloud application-default credentials (~/.config/gcloud/application_default_credentials.json)
    3. GCE/Cloud Run metadata service (when running on Google Cloud)

    Returns:
        Google credentials object
    """
    creds, project = google.auth.default(scopes=SCOPES)

    if creds.expired and hasattr(creds, 'refresh'):
        logger.info("Refreshing expired credentials...")
        creds.refresh(Request())
        logger.info("Credentials refreshed.")

    return creds


def get_paragraph_text(paragraph: dict) -> str:
    """Extract plain text from a paragraph element."""
    text = ""
    for element in paragraph.get("elements", []):
        text_run = element.get("textRun")
        if text_run:
            text += text_run.get("content", "")
    return text.rstrip("\n")


def get_document_structure(service, doc_id: str) -> list[dict]:
    """
    Fetch document and return a list of bullet paragraphs with outline IDs.
    """
    doc = service.documents().get(documentId=doc_id).execute()
    content = doc.get("body", {}).get("content", [])

    paragraphs = []
    list_counters = {}
    current_outline_stack = []

    for idx, element in enumerate(content):
        if "paragraph" not in element:
            continue

        para = element["paragraph"]
        bullet = para.get("bullet")

        if not bullet:
            continue

        text = get_paragraph_text(para)
        start_index = element.get("startIndex", 0)
        end_index = element.get("endIndex", 0)

        list_id = bullet.get("listId", "default")
        nesting_level = bullet.get("nestingLevel", 0)

        if list_id not in list_counters:
            list_counters[list_id] = {}

        # Reset deeper level counters
        levels_to_remove = [
            lvl for lvl in list_counters[list_id] if lvl > nesting_level
        ]
        for lvl in levels_to_remove:
            del list_counters[list_id][lvl]

        # Trim outline stack
        while current_outline_stack and current_outline_stack[-1][0] >= nesting_level:
            current_outline_stack.pop()

        # Increment counter
        if nesting_level not in list_counters[list_id]:
            list_counters[list_id][nesting_level] = 0
        list_counters[list_id][nesting_level] += 1

        count = list_counters[list_id][nesting_level]

        # Determine identifier format
        if nesting_level == 0:
            identifier = str(count)
        elif nesting_level == 1:
            identifier = chr(ord('a') + count - 1) if count <= 26 else f"a{count - 26}"
        elif nesting_level == 2:
            romans = ['i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii', 'viii', 'ix', 'x']
            identifier = romans[count - 1] if count <= 10 else f"r{count}"
        else:
            identifier = f"L{nesting_level}_{count}"

        # Build full outline ID
        if nesting_level == 0:
            outline_id = identifier
        else:
            parent_outline = ""
            for level, oid in current_outline_stack:
                if level == nesting_level - 1:
                    parent_outline = oid
                    break
            outline_id = parent_outline + identifier

        current_outline_stack.append((nesting_level, outline_id))

        paragraphs.append({
            "outline_id": outline_id,
            "text": text,
            "start_index": start_index,
            "end_index": end_index,
            "nesting_level": nesting_level
        })

    return paragraphs


def flatten_input_questions(data: dict) -> list[dict]:
    """Flatten nested question format to flat list with outline IDs."""
    questions = []

    if "questions" in data and isinstance(data["questions"], list):
        for q in data["questions"]:
            main_id = str(q.get("id", ""))

            # Add top-level question
            entry = {"id": main_id}
            if "question" in q:
                entry["question"] = q["question"]
            if "answer" in q:
                entry["answer"] = q["answer"]
            questions.append(entry)

            # Add nested sub-questions
            if "questions" in q and isinstance(q["questions"], list):
                for sub_q in q["questions"]:
                    sub_id = str(sub_q.get("id", ""))
                    sub_entry = {"id": f"{main_id}{sub_id}"}
                    if "question" in sub_q:
                        sub_entry["question"] = sub_q["question"]
                    if "answer" in sub_q:
                        sub_entry["answer"] = sub_q["answer"]
                    questions.append(sub_entry)

    return questions


def analyze_document(service, doc_id: str, input_questions: list[dict]) -> list[dict]:
    """
    Analyze document against expected questions.

    Returns flat list of results for each input question.
    """
    doc_paragraphs = get_document_structure(service, doc_id)

    # Build lookup by outline_id
    doc_lookup = {p["outline_id"]: p for p in doc_paragraphs}

    results = []

    for q in input_questions:
        q_id = q.get("id", "")
        expected_text = q.get("question", "")

        result = {
            "id": q_id,
            "expected_question": expected_text if expected_text else None,
            "found": False,
            "doc_question": None,
            "matched": None,
            "start_index": None,
            "end_index": None
        }

        if q_id in doc_lookup:
            para = doc_lookup[q_id]
            result["found"] = True
            result["doc_question"] = para["text"]
            result["start_index"] = para["start_index"]
            result["end_index"] = para["end_index"]

            if expected_text:
                # Check if expected text is contained in doc question
                result["matched"] = expected_text.lower() in para["text"].lower()

        results.append(result)

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Analyze Google Doc form structure against expected questions"
    )
    parser.add_argument(
        "doc_id",
        help="Google Doc ID"
    )
    parser.add_argument(
        "questions_file",
        help="JSON file with expected questions"
    )
    parser.add_argument(
        "-o", "--output",
        help="Output JSON file (default: stdout)"
    )
    parser.add_argument(
        "--dump-doc",
        action="store_true",
        help="Dump document structure and exit (for debugging)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        creds = load_credentials()
        service = build("docs", "v1", credentials=creds)

        if args.dump_doc:
            paragraphs = get_document_structure(service, args.doc_id)
            print(json.dumps(paragraphs, indent=2))
            return 0

        # Load expected questions
        with open(args.questions_file) as f:
            data = json.load(f)

        input_questions = flatten_input_questions(data)
        results = analyze_document(service, args.doc_id, input_questions)

        output = {"results": results}
        json_str = json.dumps(output, indent=2)

        if args.output:
            with open(args.output, 'w') as f:
                f.write(json_str)
                f.write('\n')
            print(f"Wrote analysis to {args.output}", file=sys.stderr)
        else:
            print(json_str)

        # Summary
        found_count = sum(1 for r in results if r["found"])
        matched_count = sum(1 for r in results if r["matched"] is True)
        mismatched_count = sum(1 for r in results if r["matched"] is False)

        print(f"\nSummary: {found_count}/{len(results)} found, "
              f"{matched_count} matched, {mismatched_count} mismatched",
              file=sys.stderr)

        return 0

    except HttpError as e:
        logger.error(f"Google API error: {e}")
        return 1
    except Exception as e:
        logger.error(f"Error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
