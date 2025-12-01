"""
Shared fixtures for integration tests.

Provides docs_service and test document fixtures that are shared across
all tests in a module for efficiency.
"""

import logging
import os
import sys

import pytest
from dotenv import load_dotenv
import google.auth
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import form_filler

# Load environment variables
load_dotenv()

# Suppress google.auth "No project ID" warning
logging.getLogger('google.auth._default').setLevel(logging.ERROR)

# Configure test answer color
form_filler.CONFIG["answer_color"] = "blue"

SCOPES = ["https://www.googleapis.com/auth/documents"]
TEST_DOC_ID_FILE = ".test_doc_id"

# Test document structure - covers all scenarios:
# 1. Parent with answer AND children with answers (question 3: "Work Experience")
# 2. Parent with NO answer but children have answers (question 4: "Contact Information")
# 3. Top-level question with answer (questions 1, 2, 5, 6)
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
            # Parent HAS an answer AND children have answers
            "id": "3",
            "question": "Work Experience",
            "answer": "10 years total",
            "questions": [
                {"id": "a", "question": "Current employer", "answer": "Acme Corp"},
                {"id": "b", "question": "Job title", "answer": "Senior Developer"}
            ]
        },
        {
            # Parent has NO answer but children have answers
            "id": "4",
            "question": "Contact Information",
            "questions": [
                {"id": "a", "question": "Email address", "answer": "john@example.com"},
                {"id": "b", "question": "Phone number", "answer": "555-123-4567"},
                {"id": "c", "question": "Mailing address", "answer": "123 Main St"}
            ]
        },
        {
            "id": "5",
            "question": "Employment status",
            "answer": "Full-time employed"
        },
        {
            "id": "6",
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
        return

    end_index = content[-1].get("endIndex", 1) - 1
    if end_index <= 1:
        return

    docs_service.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": [{
            "deleteContentRange": {
                "range": {"startIndex": 1, "endIndex": end_index}
            }
        }]}
    ).execute()


def create_native_bullets_content(docs_service, doc_id: str) -> None:
    """Create test document with native Google Docs bullets."""
    content_parts = []

    # Intro
    content_parts.append({
        "type": "paragraph",
        "text": "Introduction\n\nThis is a test form document. Please answer all questions below.\n\n"
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
        "text": "\nConclusion\n\nThank you for completing this form.\n"
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

    docs_service.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": text_insertions}
    ).execute()

    if bullet_ranges:
        # Set indentation for nested items
        indent_requests = []
        for br in bullet_ranges:
            if br["level"] > 0:
                indent_requests.append({
                    "updateParagraphStyle": {
                        "range": {"startIndex": br["start"], "endIndex": br["end"]},
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

        # Apply bullets
        all_start = min(br["start"] for br in bullet_ranges)
        all_end = max(br["end"] for br in bullet_ranges)

        docs_service.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": [{
                "createParagraphBullets": {
                    "range": {"startIndex": all_start, "endIndex": all_end},
                    "bulletPreset": "NUMBERED_DECIMAL_ALPHA_ROMAN"
                }
            }]}
        ).execute()


def create_text_based_content(docs_service, doc_id: str) -> None:
    """Create test document with text-based numbering (no native bullets)."""
    content_parts = []

    content_parts.append(
        "Introduction\n\n"
        "This is a test form document. Please answer all questions below.\n\n"
    )

    question_num = 0
    for q in TEST_QUESTIONS["questions"]:
        question_num += 1
        content_parts.append(f"{question_num}. {q['question']}\n")

        if "questions" in q:
            for i, sub_q in enumerate(q["questions"]):
                letter = chr(ord('a') + i)
                content_parts.append(f"   {letter}) {sub_q['question']}\n")

    content_parts.append(
        "\nConclusion\n\n"
        "Thank you for completing this form.\n"
    )

    full_text = "".join(content_parts)

    docs_service.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": [{
            "insertText": {
                "location": {"index": 1},
                "text": full_text
            }
        }]}
    ).execute()


@pytest.fixture(scope="module")
def docs_service():
    """Google Docs API service (module-scoped for efficiency)."""
    creds, _ = google.auth.default(scopes=SCOPES)

    if creds.expired and hasattr(creds, 'refresh'):
        creds.refresh(Request())

    return build("docs", "v1", credentials=creds)


@pytest.fixture(scope="module")
def test_doc_id(docs_service):
    """Get or create test document ID."""
    existing_id = load_test_doc_id()

    if existing_id and check_doc_exists(docs_service, existing_id):
        return existing_id

    # Create new doc
    doc = docs_service.documents().create(body={
        "title": "gdoc-form-filler Test Document"
    }).execute()
    doc_id = doc["documentId"]
    save_test_doc_id(doc_id)
    return doc_id
