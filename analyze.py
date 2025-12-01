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

# =============================================================================
# SUPPRESS "No project ID" WARNING FROM google.auth
# =============================================================================
# This suppresses the warning:
#   "No project ID could be determined. Consider running `gcloud config set project`"
#
# WHY IT'S SAFE HERE:
# - This is a locally-run batch job using only Google Workspace APIs (Docs)
# - Workspace APIs are free and don't require a quota_project_id
# - The OAuth client project handles quota tracking automatically
# - See: https://github.com/krisrowe/gworkspace-access/blob/main/QUOTAS.md
#
# DO NOT SUPPRESS THIS WARNING IN:
# - Server-side applications (may hide real configuration issues)
# - Reusable libraries or CLI tools (users need to see it)
# - Applications using paid/client-based APIs (Translation, Vision, etc.)
#
# ALTERNATIVES TO SUPPRESSION:
# - Set GOOGLE_CLOUD_PROJECT environment variable
# - Use gcloud ADC: gcloud auth application-default set-quota-project PROJECT_ID
# - Add quota_project_id to your token file manually
# =============================================================================
logging.getLogger('google.auth._default').setLevel(logging.ERROR)

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


def get_document_structure(service, doc_id: str, outline_mode: str = 'auto') -> list[dict]:
    """
    Fetch document and return a list of outline paragraphs with IDs.

    Supports two outline detection modes:
    - 'native_bullets': Use Google Docs API bullet property
    - 'text_based': Parse paragraph text for patterns like "1.", "a)", etc.
    - 'auto': Auto-detect based on document content (default)
    """
    from outline_detection import parse_document_structure

    doc = service.documents().get(documentId=doc_id).execute()
    content = doc.get("body", {}).get("content", [])

    # Filter to only return paragraphs with outline_id (for analyze.py compatibility)
    all_paragraphs = parse_document_structure(content, mode=outline_mode)
    return [p for p in all_paragraphs if p.get("outline_id")]


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
