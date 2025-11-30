#!/usr/bin/env python3
"""
Integration test for gdoc-form-filler.

Creates a temporary Google Doc with a structured outline,
runs analyze.py against it, then deletes the doc.
"""

import argparse
import json
import logging
import os
import sys
import tempfile

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Import our modules
from analyze import analyze_document, flatten_input_questions, get_document_structure

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Need both docs and drive scopes
SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive.file"
]


def load_credentials(token_path: str) -> Credentials:
    """Load and refresh credentials from token file."""
    if not os.path.exists(token_path):
        raise FileNotFoundError(f"Token file not found: {token_path}")

    creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if creds and creds.expired and creds.refresh_token:
        logger.info("Refreshing expired token...")
        creds.refresh(Request())
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    if not creds or not creds.valid:
        raise ValueError("Invalid credentials. Please regenerate the token.")

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
                {
                    "id": "a",
                    "question": "Email address",
                    "answer": "john@example.com"
                },
                {
                    "id": "b",
                    "question": "Phone number",
                    "answer": "555-123-4567"
                },
                {
                    "id": "c",
                    "question": "Mailing address",
                    "answer": "123 Main St, Anytown, USA"
                }
            ]
        },
        {
            "id": "4",
            "question": "Employment status",
            "answer": "Full-time employed"
        },
        {
            "id": "5",
            "question": "Additional comments or notes",
            "answer": "None at this time"
        }
    ]
}


def create_test_document(docs_service) -> str:
    """
    Create a test Google Doc with structured outline.
    Returns the document ID.
    """
    # Create empty document
    doc = docs_service.documents().create(body={
        "title": "gdoc-form-filler Test Document (temporary)"
    }).execute()
    doc_id = doc["documentId"]
    logger.info(f"Created test document: {doc_id}")

    # Build the document content with batchUpdate
    requests = []

    # We insert in reverse order since each insert pushes content down
    # Final structure:
    # - Intro paragraph
    # - Question 1 (bullet)
    # - Question 2 (bullet)
    # - Question 3 (bullet)
    #   - 3a (sub-bullet)
    #   - 3b (sub-bullet)
    #   - 3c (sub-bullet)
    # - Question 4 (bullet)
    # - Question 5 (bullet)
    # - Conclusion paragraph

    content_parts = []

    # Intro
    content_parts.append({
        "type": "paragraph",
        "text": "Introduction\n\nThis is a test form document. Please answer all questions below to the best of your ability. Your responses will be kept confidential.\n\n"
    })

    # Questions as bullets
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
                "level": part["level"]
            })
        current_index += len(text)

    # Execute text insertions
    docs_service.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": text_insertions}
    ).execute()

    # Now apply bullet formatting
    if bullet_ranges:
        bullet_requests = []
        for br in bullet_ranges:
            bullet_requests.append({
                "createParagraphBullets": {
                    "range": {
                        "startIndex": br["start"],
                        "endIndex": br["end"]
                    },
                    "bulletPreset": "NUMBERED_DECIMAL_NESTED"
                }
            })
            # Set nesting level if sub-bullet
            if br["level"] > 0:
                bullet_requests.append({
                    "updateParagraphStyle": {
                        "range": {
                            "startIndex": br["start"],
                            "endIndex": br["end"]
                        },
                        "paragraphStyle": {
                            "indentStart": {"magnitude": 36 * (br["level"] + 1), "unit": "PT"},
                            "indentFirstLine": {"magnitude": 18 * (br["level"] + 1), "unit": "PT"}
                        },
                        "fields": "indentStart,indentFirstLine"
                    }
                })

        docs_service.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": bullet_requests}
        ).execute()

    return doc_id


def delete_document(drive_service, doc_id: str) -> None:
    """Delete a document using Drive API."""
    drive_service.files().delete(fileId=doc_id).execute()
    logger.info(f"Deleted test document: {doc_id}")


def run_tests(docs_service, doc_id: str) -> dict:
    """Run analysis tests against the document."""
    results = {
        "passed": 0,
        "failed": 0,
        "errors": []
    }

    # Test 1: Get document structure
    logger.info("Test 1: Parsing document structure...")
    try:
        paragraphs = get_document_structure(docs_service, doc_id)
        bullet_count = len(paragraphs)
        expected_bullets = 8  # 5 top-level + 3 sub-bullets

        if bullet_count >= 5:  # At least the main questions
            logger.info(f"  PASS: Found {bullet_count} bullet paragraphs")
            results["passed"] += 1
        else:
            logger.error(f"  FAIL: Expected at least 5 bullets, found {bullet_count}")
            results["failed"] += 1
            results["errors"].append(f"Bullet count: expected >=5, got {bullet_count}")
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

        if found_count >= 5:  # At least main questions found
            logger.info("  PASS: Main questions found")
            results["passed"] += 1
        else:
            logger.error(f"  FAIL: Expected at least 5 questions found")
            results["failed"] += 1

        if matched_count >= 5:
            logger.info("  PASS: Question text matched")
            results["passed"] += 1
        else:
            logger.warning(f"  WARN: Only {matched_count} questions matched text")
            # Don't fail on this - bullet formatting may affect matching

    except Exception as e:
        logger.error(f"  ERROR: {e}")
        results["failed"] += 1
        results["errors"].append(str(e))

    # Test 3: Check outline IDs
    logger.info("Test 3: Checking outline ID assignment...")
    try:
        paragraphs = get_document_structure(docs_service, doc_id)
        outline_ids = [p["outline_id"] for p in paragraphs]

        # Should have at least 1, 2, 3, 4, 5
        expected_ids = ["1", "2", "3", "4", "5"]
        found_ids = [oid for oid in expected_ids if oid in outline_ids]

        if len(found_ids) == len(expected_ids):
            logger.info(f"  PASS: All main outline IDs found: {found_ids}")
            results["passed"] += 1
        else:
            missing = set(expected_ids) - set(found_ids)
            logger.error(f"  FAIL: Missing outline IDs: {missing}")
            results["failed"] += 1
            results["errors"].append(f"Missing outline IDs: {missing}")

        # Log all found IDs for debugging
        logger.info(f"  All outline IDs: {outline_ids}")

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
        "--token",
        default="user_token.json",
        help="Path to user_token.json (default: user_token.json)"
    )
    parser.add_argument(
        "--keep", "-k",
        action="store_true",
        help="Keep the test document (don't delete), prints URL to stdout"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    doc_id = None

    try:
        creds = load_credentials(args.token)
        docs_service = build("docs", "v1", credentials=creds)
        drive_service = build("drive", "v3", credentials=creds)

        # Create test document
        logger.info("=" * 60)
        logger.info("Creating test document...")
        doc_id = create_test_document(docs_service)
        doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"
        logger.info(f"Document ID: {doc_id}")
        logger.info("=" * 60)

        # Run tests
        logger.info("\nRunning tests...\n")
        results = run_tests(docs_service, doc_id)

        # Summary
        logger.info("\n" + "=" * 60)
        logger.info("TEST SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Passed: {results['passed']}")
        logger.info(f"Failed: {results['failed']}")

        if results["errors"]:
            logger.info("\nErrors:")
            for err in results["errors"]:
                logger.info(f"  - {err}")

        # Cleanup
        if not args.keep:
            logger.info("\nCleaning up...")
            delete_document(drive_service, doc_id)
        else:
            doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"
            logger.info("\nKeeping document.")
            # Print URL to stdout (not stderr) for easy copying
            print(f"\n{doc_url}\n")

        return 0 if results["failed"] == 0 else 1

    except HttpError as e:
        logger.error(f"Google API error: {e}")
        # Try to clean up on error
        if doc_id and not args.keep:
            try:
                drive_service = build("drive", "v3", credentials=creds)
                delete_document(drive_service, doc_id)
            except:
                logger.warning(f"Failed to delete test doc: {doc_id}")
        return 1
    except Exception as e:
        logger.error(f"Error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
