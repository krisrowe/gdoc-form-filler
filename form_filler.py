#!/usr/bin/env python3
"""
Google Doc Form Filler

Reads a Google Doc structured as a form with numbered/lettered bullets,
and fills in answers based on an input JSON file keyed by outline position.
"""

import argparse
from datetime import datetime
import json
import logging
import os
import re
import sys
from typing import Optional

import yaml
from dotenv import load_dotenv
import google.auth
from google.auth.transport.requests import Request

# Load environment variables from .env file (if present)
load_dotenv()
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

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

# Google Docs API scope
SCOPES = ["https://www.googleapis.com/auth/documents"]

# Module-level config (loaded by main or set by callers)
CONFIG = {
    "answer_color": None,  # Optional: "blue", "red", etc.
}


def flatten_questions(data: dict) -> list[dict]:
    """
    Convert nested question format to flat list for processing.

    Input format (array of question objects):
    {
      "questions": [
        {"id": "1", "question": "...", "answer": "..."},
        {
          "id": "3",
          "question": "...",
          "questions": [
            {"id": "a", "question": "...", "answer": "..."},
            {"id": "b", "question": "...", "answer": "..."}
          ]
        }
      ]
    }

    Output format:
    [
      {"outline_id": "1", "validation_text": "...", "answer": "..."},
      {"outline_id": "3a", "validation_text": "...", "answer": "..."},
      ...
    ]
    """
    answers = []

    if "questions" in data and isinstance(data["questions"], list):
        # New array format
        for q in data["questions"]:
            main_id = str(q.get("id", ""))

            # Top-level question (include even without answer for validation)
            entry = {
                "outline_id": main_id,
            }
            if "answer" in q:
                entry["answer"] = q["answer"]
            if "question" in q:
                entry["validation_text"] = q["question"]
            answers.append(entry)

            # Nested sub-questions
            if "questions" in q and isinstance(q["questions"], list):
                for sub_q in q["questions"]:
                    sub_id = str(sub_q.get("id", ""))
                    sub_entry = {
                        "outline_id": f"{main_id}{sub_id}",
                    }
                    if "answer" in sub_q:
                        sub_entry["answer"] = sub_q["answer"]
                    if "question" in sub_q:
                        sub_entry["validation_text"] = sub_q["question"]
                    answers.append(sub_entry)

    elif "answers" in data:
        # Legacy format: {"answers": [...]}
        answers = data["answers"]
    elif isinstance(data, list):
        # Direct array format
        answers = data
    else:
        raise ValueError("Unrecognized input format. Expected 'questions' array or 'answers' key.")

    return answers


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


def get_docs_service(creds: Credentials):
    """Build and return a Google Docs service object."""
    return build("docs", "v1", credentials=creds)


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
    Fetch document and return a structured list of paragraphs with metadata.

    Supports two outline detection modes:
    - 'native_bullets': Use Google Docs API bullet property
    - 'text_based': Parse paragraph text for patterns like "1.", "a)", etc.
    - 'auto': Auto-detect based on document content (default)

    Returns a list of dicts, each containing:
    - index: position in the document content array
    - start_index: character start index in the document
    - end_index: character end index in the document
    - text: the paragraph text
    - is_bullet: whether this is a bulleted/outline paragraph
    - nesting_level: bullet nesting level (0-based)
    - outline_id: computed outline identifier (e.g., "1", "2", "3a", "3b")
    - indent_start: left indent in points (for detecting answer paragraphs)
    """
    from outline_detection import parse_document_structure

    doc = service.documents().get(documentId=doc_id).execute()
    content = doc.get("body", {}).get("content", [])

    return parse_document_structure(content, mode=outline_mode)


def find_question_paragraph(
    paragraphs: list[dict],
    outline_id: str,
    validation_text: Optional[str] = None
) -> Optional[dict]:
    """
    Find the paragraph matching the given outline ID.

    Args:
        paragraphs: List of paragraph info dicts from get_document_structure
        outline_id: The outline identifier to find (e.g., "1", "3b")
        validation_text: Optional text to validate we found the right question

    Returns:
        The paragraph dict if found and validated, None otherwise
    """
    for para in paragraphs:
        if para.get("outline_id") == outline_id:
            if validation_text:
                if validation_text.lower() not in para["text"].lower():
                    logger.warning(
                        f"Outline {outline_id} found but validation text "
                        f"'{validation_text}' not in paragraph: {para['text'][:50]}..."
                    )
                    return None
            return para
    return None


def determine_insertion_point(
    paragraphs: list[dict],
    question_para: dict
) -> tuple[int, Optional[dict], bool]:
    """
    Determine where to insert/update the answer for a question.

    Uses character indices (start_index/end_index) from the Google Docs API
    rather than list positions, so results remain valid after document edits.

    Returns:
        (insertion_index, existing_answer_para, detection_uncertain)
        - insertion_index: character index where new text should be inserted
        - existing_answer_para: if there's an existing answer paragraph, return it
        - detection_uncertain: True if we couldn't reliably detect existing answers
          (e.g., last question with non-indented text after it)
    """
    q_end = question_para["end_index"]
    q_indent = question_para.get("indent_start", 0)

    # Find the next paragraph by character position (not list index)
    # This is the paragraph whose start_index is closest to but greater than q_end
    next_para = None
    for p in paragraphs:
        if p["start_index"] >= q_end:
            if next_para is None or p["start_index"] < next_para["start_index"]:
                next_para = p

    # No paragraph after this question - insert at end
    if next_para is None:
        return q_end, None, False

    # If next paragraph is a bullet, insert between question and next bullet
    if next_para["is_bullet"]:
        return q_end, None, False

    # Next paragraph is not a bullet - check if it's an existing answer
    # We consider it an answer if:
    # 1. It's indented more than the question (traditional detection), OR
    # 2. There's another bullet/outline paragraph after it (meaning this non-bullet
    #    is sandwiched between questions, so it must be an answer)
    #
    # This handles:
    # - Properly indented answers (inserted by this tool)
    # - Manually typed answers without indentation (if followed by more questions)
    # - But NOT conclusion/footer paragraphs after the last question
    next_indent = next_para.get("indent_start", 0)

    if next_indent > q_indent:
        # Indented under question - definitely an answer
        return next_para["start_index"], next_para, False

    # Check if there's another bullet after this non-bullet paragraph
    # If so, this paragraph is between two questions and is likely an answer
    for p in paragraphs:
        if p["start_index"] > next_para["end_index"] and p["is_bullet"]:
            # Found a bullet after the non-bullet - treat non-bullet as answer
            return next_para["start_index"], next_para, False

    # No bullet after, and not indented - could be footer text OR an un-indented answer
    # We can't reliably tell, so we insert new answer but flag uncertainty
    return q_end, None, True


# Named colors mapped to RGB values (0-1 range for Google Docs API)
NAMED_COLORS = {
    "blue": {"red": 0.0, "green": 0.0, "blue": 1.0},
    "red": {"red": 1.0, "green": 0.0, "blue": 0.0},
    "green": {"red": 0.0, "green": 0.5, "blue": 0.0},
    "yellow": {"red": 1.0, "green": 1.0, "blue": 0.0},
    "cyan": {"red": 0.0, "green": 1.0, "blue": 1.0},
    "magenta": {"red": 1.0, "green": 0.0, "blue": 1.0},
    "orange": {"red": 1.0, "green": 0.5, "blue": 0.0},
    "purple": {"red": 0.5, "green": 0.0, "blue": 0.5},
}


def insert_answer(
    service,
    doc_id: str,
    index: int,
    answer_text: str,
    question_indent: float = 0
) -> None:
    """
    Insert answer text at the specified index.

    Note: index should be paragraph's end_index. We insert answer + newline,
    placing it after the paragraph's trailing newline (which is included in end_index).
    We also remove bullet formatting and indent the answer under the question.
    Color is read from CONFIG["answer_color"] if set.
    """
    text_to_insert = f"{answer_text}\n"
    # Indent answer more than the question (question_indent + 36pt)
    answer_indent = question_indent + 36
    requests = [
        {
            "insertText": {
                "location": {"index": index},
                "text": text_to_insert
            }
        },
        {
            "deleteParagraphBullets": {
                "range": {
                    "startIndex": index,
                    "endIndex": index + len(text_to_insert)
                }
            }
        },
        {
            "updateParagraphStyle": {
                "range": {
                    "startIndex": index,
                    "endIndex": index + len(text_to_insert)
                },
                "paragraphStyle": {
                    "indentStart": {"magnitude": answer_indent, "unit": "PT"},
                    "indentFirstLine": {"magnitude": answer_indent, "unit": "PT"}
                },
                "fields": "indentStart,indentFirstLine"
            }
        }
    ]

    # Apply color if configured
    color = CONFIG.get("answer_color")
    if color and color.lower() in NAMED_COLORS:
        rgb = NAMED_COLORS[color.lower()]
        requests.append({
            "updateTextStyle": {
                "range": {
                    "startIndex": index,
                    "endIndex": index + len(text_to_insert) - 1  # exclude trailing newline
                },
                "textStyle": {
                    "foregroundColor": {
                        "color": {"rgbColor": rgb}
                    }
                },
                "fields": "foregroundColor"
            }
        })

    service.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": requests}
    ).execute()
    logger.debug(f"Inserted answer at index {index}")


def replace_answer(
    service,
    doc_id: str,
    existing_para: dict,
    new_answer: str
) -> None:
    """Replace existing answer text."""
    start = existing_para["start_index"]
    end = existing_para["end_index"]

    requests = [
        {
            "deleteContentRange": {
                "range": {
                    "startIndex": start,
                    "endIndex": end
                }
            }
        },
        {
            "insertText": {
                "location": {"index": start},
                "text": f"{new_answer}\n"
            }
        }
    ]
    service.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": requests}
    ).execute()
    logger.debug(f"Replaced answer at index {start}-{end}")


def validate_questions(
    service,
    doc_id: str,
    answers: list[dict]
) -> dict:
    """
    Validate input questions against document structure.

    Returns dict with:
    - doc_ids: set of outline IDs found in document
    - input_ids: set of outline IDs from input
    - missing_in_doc: questions in input but not in document
    - missing_in_input: questions in document but not in input
    - text_mismatches: questions where text doesn't match
    """
    paragraphs = get_document_structure(service, doc_id)

    # Only consider bullet paragraphs
    doc_bullets = {p["outline_id"]: p for p in paragraphs if p["is_bullet"]}
    doc_ids = set(doc_bullets.keys())

    input_ids = {a["outline_id"] for a in answers if a.get("outline_id")}

    missing_in_doc = []
    missing_in_input = []
    text_mismatches = []

    # Check input questions against doc
    for answer in answers:
        oid = answer.get("outline_id")
        if not oid:
            continue

        if oid not in doc_ids:
            missing_in_doc.append({
                "outline_id": oid,
                "validation_text": answer.get("validation_text")
            })
        elif answer.get("validation_text"):
            doc_text = doc_bullets[oid]["text"]
            expected = answer["validation_text"]
            if expected.lower() not in doc_text.lower():
                text_mismatches.append({
                    "outline_id": oid,
                    "expected": expected,
                    "found": doc_text
                })

    # Check doc questions not in input
    for oid in doc_ids:
        if oid not in input_ids:
            missing_in_input.append({
                "outline_id": oid,
                "doc_text": doc_bullets[oid]["text"]
            })

    return {
        "doc_ids": doc_ids,
        "input_ids": input_ids,
        "missing_in_doc": missing_in_doc,
        "missing_in_input": missing_in_input,
        "text_mismatches": text_mismatches
    }


def process_answers(
    service,
    doc_id: str,
    answers: list[dict],
    dry_run: bool = False
) -> dict:
    """
    Process all answers from the input file.

    Args:
        service: Google Docs service
        doc_id: Document ID
        answers: List of answer dicts with keys:
            - outline_id: e.g., "1", "3b"
            - validation_text: (optional) expected question text
            - answer: the answer text to insert
        dry_run: If True, don't make changes, just report what would happen

    Returns:
        Dict with unified results array. Each entry contains:
            - outline_id: the question identifier
            - status: primary outcome (inserted, replaced, no_change, skipped, error, not_found)
            - actions: list of actions taken (e.g., ["inserted", "fixed_indentation"])
            - warning: (optional) warning message if detection was uncertain
            - Additional context fields as needed
    """
    results = []

    for answer_entry in answers:
        outline_id = answer_entry.get("outline_id")
        validation_text = answer_entry.get("validation_text")
        answer_text = answer_entry.get("answer")

        # Build result entry for this question
        entry = {"outline_id": outline_id}

        if not outline_id:
            entry["status"] = "error"
            entry["actions"] = []
            entry["error"] = "Missing outline_id"
            results.append(entry)
            continue

        # Skip entries without answers (parent questions or incomplete answers)
        if not answer_text:
            entry["status"] = "skipped"
            entry["actions"] = []
            entry["reason"] = "No answer provided"
            results.append(entry)
            continue

        # Re-fetch document structure each time (indices change after edits)
        paragraphs = get_document_structure(service, doc_id)

        # Find the question
        question_para = find_question_paragraph(
            paragraphs, outline_id, validation_text
        )

        if not question_para:
            entry["status"] = "not_found"
            entry["actions"] = []
            entry["reason"] = f"Question not found in document"
            results.append(entry)
            continue

        # Determine insertion point
        insert_idx, existing_answer, detection_uncertain = determine_insertion_point(
            paragraphs, question_para
        )

        # Track actions performed
        actions = []

        if existing_answer:
            existing_text = existing_answer["text"].strip()
            new_text = answer_text.strip()

            if existing_text == new_text:
                entry["status"] = "no_change"
                entry["actions"] = []
                entry["match_type"] = "answer_matches"
                entry["matched_text"] = existing_text[:100] if existing_text else "(empty)"
                results.append(entry)
                continue

            # Replace existing answer
            if dry_run:
                entry["status"] = "would_replace"
                actions.append("would_replace")
            else:
                replace_answer(service, doc_id, existing_answer, answer_text)
                entry["status"] = "replaced"
                actions.append("replaced")

            # Include mismatch details
            entry["previous_answer"] = existing_text
            entry["new_answer"] = new_text
        else:
            # Insert new answer
            if dry_run:
                entry["status"] = "would_insert"
                actions.append("would_insert")
            else:
                question_indent = question_para.get("indent_start", 0)
                insert_answer(service, doc_id, insert_idx, answer_text, question_indent)
                entry["status"] = "inserted"
                actions.append("inserted")

            # Add warning if detection was uncertain
            if detection_uncertain:
                entry["warning"] = (
                    "Could not reliably detect existing answer. "
                    "This is the last question with non-indented text after it."
                )

        entry["actions"] = actions
        results.append(entry)

    # Now report on document questions that weren't in the input
    # Get all doc outline IDs and input outline IDs
    input_ids = set(a.get("outline_id") for a in answers if a.get("outline_id"))
    paragraphs = get_document_structure(service, doc_id)
    doc_ids = set(p.get("outline_id") for p in paragraphs if p.get("outline_id"))

    for oid in sorted(doc_ids - input_ids):
        entry = {"outline_id": oid, "actions": []}

        # Find this question and check if it has an existing answer
        question_para = find_question_paragraph(paragraphs, oid, None)
        if question_para:
            _, existing_answer, _ = determine_insertion_point(paragraphs, question_para)
            if existing_answer:
                existing_text = existing_answer["text"].strip()
                entry["status"] = "not_in_input"
                entry["existing_answer"] = existing_text[:100] if existing_text else "(empty)"
                entry["has_answer"] = True
            else:
                entry["status"] = "not_in_input"
                entry["has_answer"] = False
        else:
            entry["status"] = "not_in_input"
            entry["has_answer"] = False

        results.append(entry)

    return {"results": results}


def run_form_filler(
    service,
    doc_id: str,
    answers: list[dict],
    dry_run: bool = False
) -> dict:
    """
    Core function that validates and processes answers.

    Args:
        service: Google Docs service
        doc_id: Document ID
        answers: Flattened list of answer dicts
        dry_run: If True, don't make changes

    Returns:
        Dict with validation and processing results
    """
    # Validate input against document structure
    validation = validate_questions(service, doc_id, answers)

    # Process answers
    processing = process_answers(service, doc_id, answers, dry_run=dry_run)

    # Build combined results
    return {
        "validation": {
            "doc_question_count": len(validation["doc_ids"]),
            "input_question_count": len(validation["input_ids"]),
            "doc_ids": sorted(validation["doc_ids"]),
            "input_ids": sorted(validation["input_ids"]),
            "missing_in_doc": validation["missing_in_doc"],
            "missing_in_input": validation["missing_in_input"],
            "text_mismatches": validation["text_mismatches"]
        },
        "results": processing["results"]
    }


def print_results(results: dict) -> None:
    """Print results in human-readable format."""
    v = results["validation"]
    r = results["results"]

    # Validation details (debug level - use LOG_LEVEL=DEBUG to see)
    if v["missing_in_doc"]:
        logger.debug("Input questions not found in document:")
        for item in v["missing_in_doc"]:
            text = item.get("validation_text", "")
            logger.debug(f"  {item['outline_id']}: {text[:50] if text else '(no text)'}")

    if v["missing_in_input"]:
        logger.debug("Document questions not in input:")
        for item in v["missing_in_input"]:
            logger.debug(f"  {item['outline_id']}: {item['doc_text'][:50]}...")

    if v["text_mismatches"]:
        logger.debug("Question text mismatches:")
        for item in v["text_mismatches"]:
            logger.debug(f"  {item['outline_id']}:")
            logger.debug(f"    expected: {item['expected'][:40]}...")
            logger.debug(f"    found:    {item['found'][:40]}...")

    # Summary to stdout
    print("\n=== Validation Summary ===")
    print(f"Document questions: {v['doc_question_count']}")
    print(f"Input questions: {v['input_question_count']}")
    print(f"Missing in doc: {len(v['missing_in_doc'])}")
    print(f"Missing in input: {len(v['missing_in_input'])}")
    print(f"Text mismatches: {len(v['text_mismatches'])}")

    # Results table
    print("\n=== Processing Results ===")
    print(f"{'ID':<8} {'Status':<16} {'Actions':<20} {'Details'}")
    print("-" * 70)
    for entry in r:
        oid = entry.get("outline_id", "?")
        status = entry.get("status", "unknown")
        actions = ", ".join(entry.get("actions", []))

        # Build details string based on status
        details = ""
        if entry.get("warning"):
            details = f"[WARN] {entry['warning'][:30]}..."
        elif status == "no_change":
            details = f"matched: {entry.get('matched_text', '')[:25]}..."
        elif status in ("replaced", "would_replace"):
            prev = entry.get("previous_answer", "")
            new = entry.get("new_answer", "")
            details = f"'{prev[:15]}...'({len(prev)}) -> '{new[:15]}...'({len(new)})"
        elif status == "not_in_input":
            if entry.get("has_answer"):
                existing = entry.get("existing_answer", "")
                details = f"has answer: '{existing[:25]}...'"
            else:
                details = "(blank)"
        elif status in ("skipped", "not_found", "error"):
            details = entry.get("reason", entry.get("error", ""))[:40]

        print(f"{oid:<8} {status:<16} {actions:<20} {details}")

    # Summary counts
    status_counts = {}
    for entry in r:
        status = entry.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    print("-" * 70)
    print(f"Total: {len(r)}  |  " + "  ".join(f"{s}: {c}" for s, c in sorted(status_counts.items())))


def print_doc_link(doc_id: str) -> None:
    """Print a link to the Google Doc."""
    print(f"\nhttps://docs.google.com/document/d/{doc_id}/edit")


def get_output_filename(prefix: str = "processed", suffix: str = None) -> str:
    """
    Generate a unique output filename with timestamp.

    Args:
        prefix: Filename prefix (default: "processed")
        suffix: Optional suffix to add before extension (e.g., "01", "native_bullets")

    Returns:
        Base filename without extension (e.g., "processed_2025-01-01-120000_01")
    """
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    if suffix:
        return f"{prefix}_{timestamp}_{suffix}"
    return f"{prefix}_{timestamp}"


def main():
    parser = argparse.ArgumentParser(
        description="Fill answers into a Google Doc form"
    )
    parser.add_argument(
        "doc_id",
        help="Google Doc ID"
    )
    parser.add_argument(
        "answers_file",
        help="JSON file with answers"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON instead of formatted text"
    )
    parser.add_argument(
        "--dump-structure",
        action="store_true",
        help="Dump document structure and exit (for debugging)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml (default: config.yaml)"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Load config and set module-level CONFIG
    if os.path.exists(args.config):
        with open(args.config) as f:
            file_config = yaml.safe_load(f) or {}
            CONFIG["answer_color"] = file_config.get("answer_color")

    try:
        creds = load_credentials()
        service = get_docs_service(creds)

        if args.dump_structure:
            paragraphs = get_document_structure(service, args.doc_id)
            print(json.dumps(paragraphs, indent=2))
            return 0

        # Load answers
        with open(args.answers_file) as f:
            data = json.load(f)

        # Convert nested format to flat list for processing
        answers = flatten_questions(data)

        # Run validation and processing
        results = run_form_filler(service, args.doc_id, answers, dry_run=args.dry_run)

        # Save results to timestamped JSON file
        base_name = get_output_filename()
        json_file = f"{base_name}.json"
        md_file = f"{base_name}.md"

        # Store doc_id in results for report generation
        results["doc_id"] = args.doc_id

        with open(json_file, 'w') as f:
            json.dump(results, f, indent=2)
            f.write('\n')
        logger.info(f"Results saved to {json_file}")

        # Output results
        if args.json:
            print(json.dumps(results, indent=2))
        else:
            print_results(results)

        # Generate Markdown report
        from report import generate_report
        generate_report(results, args.doc_id, md_file, json_file)
        print(f"\nReport: {md_file}")

        # Check for errors in results
        error_count = sum(1 for r in results["results"] if r.get("status") == "error")
        return 0 if error_count == 0 else 1

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
