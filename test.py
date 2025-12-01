#!/usr/bin/env python3
"""
Integration test for gdoc-form-filler.

Reuses a single test Google Doc, clearing and rebuilding its contents each run.
The doc ID is stored in .test_doc_id (gitignored).
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

# Import our modules
from analyze import analyze_document, flatten_input_questions, get_document_structure
import form_filler
from form_filler import validate_questions, process_answers, flatten_questions

# Set config values for testing (normally loaded from config.yaml in main())
# Tests manipulate CONFIG directly rather than reading config files
form_filler.CONFIG["answer_color"] = "blue"

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

# Only need docs scope
SCOPES = ["https://www.googleapis.com/auth/documents"]

# File to store test doc ID (gitignored)
TEST_DOC_ID_FILE = ".test_doc_id"


def load_test_doc_id() -> str:
    """Load test doc ID from file."""
    if os.path.exists(TEST_DOC_ID_FILE):
        with open(TEST_DOC_ID_FILE) as f:
            return f.read().strip()
    return None


def save_test_doc_id(doc_id: str) -> None:
    """Save test doc ID to file."""
    with open(TEST_DOC_ID_FILE, 'w') as f:
        f.write(doc_id)


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


# Test document structure
TEST_QUESTIONS = {
    "questions": [
        {
            "id": "1",
            "question": "What is your full legal name?",
            "answer": "John Smith"
        },
        {
            "id": "2",
            "question": "What is your date of birth?",
            "answer": "January 1, 1990"
        },
        {
            "id": "3",
            "question": "Contact Information",
            "questions": [
                {"id": "a", "question": "Email address", "answer": "john@example.com"},
                {"id": "b", "question": "Phone number", "answer": "555-123-4567"},
                {"id": "c", "question": "Mailing address", "answer": "123 Main St"}
            ]
        },
        {
            "id": "4",
            "question": "Employment status",
            "answer": "Full-time employed"
        },
        {
            "id": "5",
            "question": "Additional comments",
            "answer": "None"
        }
    ]
}


def get_expected_outline_ids() -> list[str]:
    """Get list of expected outline IDs from TEST_QUESTIONS."""
    ids = []
    for q in TEST_QUESTIONS["questions"]:
        ids.append(q["id"])
        if "questions" in q:
            for sub in q["questions"]:
                ids.append(f"{q['id']}{sub['id']}")
    return ids


def get_expected_bullet_count() -> int:
    """Count total bullets expected from TEST_QUESTIONS."""
    count = 0
    for q in TEST_QUESTIONS["questions"]:
        count += 1
        if "questions" in q:
            count += len(q["questions"])
    return count


def check_doc_exists(docs_service, doc_id: str) -> bool:
    """Check if a document exists and is accessible."""
    try:
        docs_service.documents().get(documentId=doc_id).execute()
        return True
    except HttpError as e:
        if e.resp.status in [404, 403]:
            return False
        raise


def clear_document(docs_service, doc_id: str) -> None:
    """Clear all content from a document."""
    doc = docs_service.documents().get(documentId=doc_id).execute()
    content = doc.get("body", {}).get("content", [])

    if len(content) <= 1:
        return  # Already empty (just the initial newline)

    # Get the range to delete (from index 1 to end-1)
    end_index = content[-1].get("endIndex", 1) - 1
    if end_index <= 1:
        return

    requests = [{
        "deleteContentRange": {
            "range": {
                "startIndex": 1,
                "endIndex": end_index
            }
        }
    }]

    docs_service.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": requests}
    ).execute()
    logger.info(f"Cleared document content")


def create_test_document(docs_service, existing_doc_id: str = None, outline_type: str = 'native_bullets') -> str:
    """
    Create or reuse a test Google Doc with structured outline.

    Args:
        docs_service: Google Docs API service
        existing_doc_id: Existing doc ID to reuse, or None to create new
        outline_type: 'native_bullets' or 'text_based'

    Returns the document ID.
    """
    if existing_doc_id:
        doc_id = existing_doc_id
        logger.info(f"Reusing existing test document: {doc_id}")
        clear_document(docs_service, doc_id)
    else:
        # Create empty document
        doc = docs_service.documents().create(body={
            "title": "gdoc-form-filler Test Document"
        }).execute()
        doc_id = doc["documentId"]
        logger.info(f"Created new test document: {doc_id}")

    if outline_type == 'text_based':
        return _create_text_based_content(docs_service, doc_id)
    else:
        return _create_native_bullets_content(docs_service, doc_id)


def _create_native_bullets_content(docs_service, doc_id: str) -> str:
    """Create test document with native Google Docs bullets."""

    # Build content structure
    # Final structure:
    # - Intro paragraph
    # - Question 1 (bullet)
    # - Question 2 (bullet)
    # - Question 3 (bullet)
    #   a. sub-bullet
    #   b. sub-bullet
    #   c. sub-bullet
    # - Question 4 (bullet)
    # - Question 5 (bullet)
    # - Conclusion paragraph

    content_parts = []

    # Intro
    content_parts.append({
        "type": "paragraph",
        "text": "Introduction\n\nThis is a test form document. Please answer all questions below to the best of your ability. Your responses will be kept confidential.\n\n"
    })

    # Questions as bullets with sub-bullets
    for q in TEST_QUESTIONS["questions"]:
        content_parts.append({
            "type": "bullet",
            "level": 0,
            "text": q["question"] + "\n"
        })
        if "questions" in q:
            for sub_q in q["questions"]:
                content_parts.append({
                    "type": "bullet",
                    "level": 1,
                    "text": sub_q["question"] + "\n"
                })

    # Conclusion
    content_parts.append({
        "type": "paragraph",
        "text": "\nConclusion\n\nThank you for completing this form. Please review your answers before submitting.\n"
    })

    # Insert all text first
    current_index = 1
    text_insertions = []
    bullet_ranges = []

    for part in content_parts:
        text = part["text"]
        text_insertions.append({
            "insertText": {
                "location": {"index": current_index},
                "text": text
            }
        })
        if part["type"] == "bullet":
            bullet_ranges.append({
                "start": current_index,
                "end": current_index + len(text),
                "level": part.get("level", 0)
            })
        current_index += len(text)

    # Execute text insertions
    docs_service.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": text_insertions}
    ).execute()

    if bullet_ranges:
        # Step 1: Set indentation for nested items BEFORE applying bullets
        indent_requests = []
        for br in bullet_ranges:
            if br["level"] > 0:
                indent_requests.append({
                    "updateParagraphStyle": {
                        "range": {
                            "startIndex": br["start"],
                            "endIndex": br["end"]
                        },
                        "paragraphStyle": {
                            "indentStart": {"magnitude": 36 * br["level"], "unit": "PT"},
                            "indentFirstLine": {"magnitude": 36 * br["level"], "unit": "PT"}
                        },
                        "fields": "indentStart,indentFirstLine"
                    }
                })

        if indent_requests:
            docs_service.documents().batchUpdate(
                documentId=doc_id,
                body={"requests": indent_requests}
            ).execute()

        # Step 2: Apply bullets to all at once
        all_start = min(br["start"] for br in bullet_ranges)
        all_end = max(br["end"] for br in bullet_ranges)

        docs_service.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": [{
                "createParagraphBullets": {
                    "range": {
                        "startIndex": all_start,
                        "endIndex": all_end
                    },
                    "bulletPreset": "NUMBERED_DECIMAL_ALPHA_ROMAN"
                }
            }]}
        ).execute()

    return doc_id


def _create_text_based_content(docs_service, doc_id: str) -> str:
    """Create test document with text-based numbering (no native bullets)."""

    # Build content with text-based numbering like "1.", "2.", "a)", "b)"
    content_parts = []

    # Intro
    content_parts.append(
        "Introduction\n\n"
        "This is a test form document. Please answer all questions below "
        "to the best of your ability. Your responses will be kept confidential.\n\n"
    )

    # Questions with text-based numbering
    question_num = 0
    for q in TEST_QUESTIONS["questions"]:
        question_num += 1
        content_parts.append(f"{question_num}. {q['question']}\n")

        if "questions" in q:
            for i, sub_q in enumerate(q["questions"]):
                letter = chr(ord('a') + i)
                # Indent sub-questions with spaces and use "a)" format
                content_parts.append(f"   {letter}) {sub_q['question']}\n")

    # Conclusion
    content_parts.append(
        "\nConclusion\n\n"
        "Thank you for completing this form. Please review your answers before submitting.\n"
    )

    # Join all content
    full_text = "".join(content_parts)

    # Insert text
    docs_service.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": [{
            "insertText": {
                "location": {"index": 1},
                "text": full_text
            }
        }]}
    ).execute()

    return doc_id


def run_tests(docs_service, doc_id: str, outline_mode: str = 'auto') -> dict:
    """Run analysis tests against the document."""
    results = {
        "passed": 0,
        "failed": 0,
        "errors": []
    }

    expected_count = get_expected_bullet_count()
    expected_ids = get_expected_outline_ids()

    # Test 1: Get document structure
    logger.info("Test 1: Parsing document structure...")
    try:
        paragraphs = get_document_structure(docs_service, doc_id, outline_mode=outline_mode)
        bullet_count = len([p for p in paragraphs if p.get("outline_id")])

        if bullet_count == expected_count:
            logger.info(f"  PASS: Found {bullet_count} bullet paragraphs (expected {expected_count})")
            results["passed"] += 1
        else:
            logger.error(f"  FAIL: Expected {expected_count} bullets, found {bullet_count}")
            results["failed"] += 1
            results["errors"].append(f"Bullet count: expected {expected_count}, got {bullet_count}")
    except Exception as e:
        logger.error(f"  ERROR: {e}")
        results["failed"] += 1
        results["errors"].append(str(e))

    # Test 2: Analyze against expected questions
    logger.info("Test 2: Analyzing against expected questions...")
    try:
        input_questions = flatten_input_questions(TEST_QUESTIONS)
        analysis = analyze_document(docs_service, doc_id, input_questions)

        found_count = sum(1 for r in analysis if r["found"])
        matched_count = sum(1 for r in analysis if r["matched"] is True)

        logger.info(f"  Found: {found_count}/{len(analysis)}")
        logger.info(f"  Matched: {matched_count}/{len(analysis)}")

        if found_count == len(analysis):
            logger.info("  PASS: All questions found")
            results["passed"] += 1
        else:
            logger.error(f"  FAIL: Expected {len(analysis)} questions found, got {found_count}")
            results["failed"] += 1

        if matched_count == len(analysis):
            logger.info("  PASS: All question text matched")
            results["passed"] += 1
        else:
            logger.warning(f"  WARN: Only {matched_count}/{len(analysis)} questions matched text")

    except Exception as e:
        logger.error(f"  ERROR: {e}")
        results["failed"] += 1
        results["errors"].append(str(e))

    # Test 3: Check outline IDs
    logger.info("Test 3: Checking outline ID assignment...")
    try:
        paragraphs = get_document_structure(docs_service, doc_id, outline_mode=outline_mode)
        outline_ids = [p["outline_id"] for p in paragraphs if p.get("outline_id")]

        found_ids = [oid for oid in expected_ids if oid in outline_ids]

        if len(found_ids) == len(expected_ids):
            logger.info(f"  PASS: All expected outline IDs found: {found_ids}")
            results["passed"] += 1
        else:
            missing = set(expected_ids) - set(outline_ids)
            logger.error(f"  FAIL: Missing outline IDs: {missing}")
            results["failed"] += 1
            results["errors"].append(f"Missing outline IDs: {missing}")

        logger.info(f"  Expected: {expected_ids}")
        logger.info(f"  Found: {outline_ids}")

    except Exception as e:
        logger.error(f"  ERROR: {e}")
        results["failed"] += 1
        results["errors"].append(str(e))

    # Test 4: Validate using form_filler's validate_questions
    logger.info("Test 4: Testing validate_questions...")
    try:
        answers = flatten_questions(TEST_QUESTIONS)
        validation = validate_questions(docs_service, doc_id, answers)
        errors = []

        # Check counts match
        if len(validation["doc_ids"]) != expected_count:
            errors.append(f"doc_question_count: expected {expected_count}, got {len(validation['doc_ids'])}")

        if len(validation["input_ids"]) != expected_count:
            errors.append(f"input_question_count: expected {expected_count}, got {len(validation['input_ids'])}")

        # Check no missing questions
        if validation["missing_in_doc"]:
            errors.append(f"missing_in_doc: {validation['missing_in_doc']}")

        if validation["missing_in_input"]:
            errors.append(f"missing_in_input: {validation['missing_in_input']}")

        # Check no text mismatches
        if validation["text_mismatches"]:
            errors.append(f"text_mismatches: {validation['text_mismatches']}")

        # Check doc_ids match expected
        if sorted(validation["doc_ids"]) != sorted(expected_ids):
            errors.append(f"doc_ids mismatch: expected {expected_ids}, got {sorted(validation['doc_ids'])}")

        if errors:
            for err in errors:
                logger.error(f"  FAIL: {err}")
            results["failed"] += 1
            results["errors"].extend(errors)
        else:
            logger.info(f"  PASS: validate_questions found no discrepancies")
            logger.info(f"    doc_ids: {sorted(validation['doc_ids'])}")
            results["passed"] += 1

    except Exception as e:
        logger.error(f"  ERROR: {e}")
        results["failed"] += 1
        results["errors"].append(str(e))

    # Test 5: Actually fill in answers and verify they were inserted
    logger.info("Test 5: Testing process_answers...")
    try:
        answers = flatten_questions(TEST_QUESTIONS)
        processing = process_answers(docs_service, doc_id, answers, dry_run=False)
        errors = []

        # Check no processing errors
        if processing["errors"]:
            errors.append(f"processing errors: {processing['errors']}")

        # Check answers were inserted (action starts with "inserted", may have "_uncertain" suffix)
        inserted = [p for p in processing["processed"] if p.get("action", "").startswith("inserted")]
        expected_answers = [a for a in answers if a.get("answer")]
        if len(inserted) != len(expected_answers):
            errors.append(f"inserted count: expected {len(expected_answers)}, got {len(inserted)}")

        # Verify by re-reading full document (not just bullets)
        # Answers are separate non-bullet paragraphs following each question
        doc = docs_service.documents().get(documentId=doc_id).execute()
        content = doc.get("body", {}).get("content", [])

        # Build list of all paragraph texts in order
        all_paragraphs = []
        for elem in content:
            if "paragraph" in elem:
                para = elem["paragraph"]
                text = ""
                for e in para.get("elements", []):
                    tr = e.get("textRun")
                    if tr:
                        text += tr.get("content", "")
                all_paragraphs.append(text.strip())

        # Check that each answer appears somewhere in the document
        for answer_entry in expected_answers:
            oid = answer_entry["outline_id"]
            answer_text = answer_entry["answer"]
            found = any(answer_text in p for p in all_paragraphs)
            if not found:
                errors.append(f"answer for {oid} not found in document: '{answer_text}'")

        if errors:
            for err in errors:
                logger.error(f"  FAIL: {err}")
            results["failed"] += 1
            results["errors"].extend(errors)
        else:
            logger.info(f"  PASS: {len(inserted)} answers inserted and verified")
            results["passed"] += 1

    except Exception as e:
        logger.error(f"  ERROR: {e}")
        results["failed"] += 1
        results["errors"].append(str(e))

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Integration test for gdoc-form-filler"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    parser.add_argument(
        "--outline-type",
        choices=["native_bullets", "text_based", "both"],
        default="both",
        help="Outline type to test (default: both)"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        creds = load_credentials()
        docs_service = build("docs", "v1", credentials=creds)

        # Check for existing test doc
        existing_doc_id = load_test_doc_id()
        doc_id = None

        logger.info("=" * 60)
        if existing_doc_id:
            if check_doc_exists(docs_service, existing_doc_id):
                doc_id = existing_doc_id
            else:
                logger.warning(f"Test doc {existing_doc_id} not found/accessible, creating new one")

        # Determine which outline types to test
        if args.outline_type == "both":
            outline_types = ["native_bullets", "text_based"]
        else:
            outline_types = [args.outline_type]

        total_results = {"passed": 0, "failed": 0, "errors": []}

        for outline_type in outline_types:
            logger.info("\n" + "=" * 60)
            logger.info(f"TESTING OUTLINE TYPE: {outline_type}")
            logger.info("=" * 60)

            # Create or reuse test document with this outline type
            doc_id = create_test_document(docs_service, doc_id, outline_type=outline_type)
            doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"

            # Save doc_id if new
            if doc_id != existing_doc_id:
                save_test_doc_id(doc_id)
                existing_doc_id = doc_id

            logger.info(f"Document ID: {doc_id}")

            # Run tests with appropriate outline mode
            logger.info(f"\nRunning tests for {outline_type}...\n")
            results = run_tests(docs_service, doc_id, outline_mode=outline_type)

            # Accumulate results
            total_results["passed"] += results["passed"]
            total_results["failed"] += results["failed"]
            total_results["errors"].extend(
                [f"[{outline_type}] {e}" for e in results["errors"]]
            )

            logger.info(f"\n{outline_type} results: {results['passed']} passed, {results['failed']} failed")

        # Final Summary
        logger.info("\n" + "=" * 60)
        logger.info("FINAL TEST SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Total Passed: {total_results['passed']}")
        logger.info(f"Total Failed: {total_results['failed']}")

        if total_results["errors"]:
            logger.info("\nErrors:")
            for err in total_results["errors"]:
                logger.info(f"  - {err}")

        # Print URL to stdout for easy access
        print(f"\n{doc_url}\n")

        return 0 if total_results["failed"] == 0 else 1

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
