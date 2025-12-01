"""
Integration tests for native Google Docs bullet outlines.

Tests run in order (alphabetically by method name) and share the same
test document via module-scoped fixtures.
"""

import os
import sys

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from analyze import analyze_document, flatten_input_questions, get_document_structure
from form_filler import validate_questions, process_answers, flatten_questions

# Import from conftest (pytest handles this specially)
from tests.integration.conftest import (
    TEST_QUESTIONS,
    get_expected_outline_ids,
    get_expected_bullet_count,
    clear_document,
    create_native_bullets_content,
)


@pytest.fixture(scope="module")
def native_bullets_doc(docs_service, test_doc_id):
    """Prepare test doc with native bullets content."""
    clear_document(docs_service, test_doc_id)
    create_native_bullets_content(docs_service, test_doc_id)
    return test_doc_id


class TestNativeBullets:
    """Integration tests for native Google Docs bullet outlines."""

    def test_1_parse_structure(self, docs_service, native_bullets_doc):
        """Test parsing document structure finds all bullet paragraphs."""
        paragraphs = get_document_structure(
            docs_service, native_bullets_doc, outline_mode='native_bullets'
        )
        bullet_count = len([p for p in paragraphs if p.get("outline_id")])
        expected = get_expected_bullet_count()

        assert bullet_count == expected, f"Expected {expected} bullets, found {bullet_count}"

    def test_2_analyze_questions(self, docs_service, native_bullets_doc):
        """Test analyzing document against expected questions."""
        input_questions = flatten_input_questions(TEST_QUESTIONS)
        analysis = analyze_document(docs_service, native_bullets_doc, input_questions)

        found_count = sum(1 for r in analysis if r["found"])
        matched_count = sum(1 for r in analysis if r["matched"] is True)

        assert found_count == len(analysis), f"Expected all {len(analysis)} questions found, got {found_count}"
        assert matched_count == len(analysis), f"Expected all {len(analysis)} questions matched, got {matched_count}"

    def test_3_check_outline_ids(self, docs_service, native_bullets_doc):
        """Test outline ID assignment matches expected IDs."""
        paragraphs = get_document_structure(
            docs_service, native_bullets_doc, outline_mode='native_bullets'
        )
        outline_ids = [p["outline_id"] for p in paragraphs if p.get("outline_id")]
        expected_ids = get_expected_outline_ids()

        missing = set(expected_ids) - set(outline_ids)
        assert not missing, f"Missing outline IDs: {missing}"
        assert sorted(outline_ids) == sorted(expected_ids)

    def test_4_validate_questions(self, docs_service, native_bullets_doc):
        """Test validate_questions finds no discrepancies with matching input."""
        answers = flatten_questions(TEST_QUESTIONS)
        validation = validate_questions(docs_service, native_bullets_doc, answers)
        expected_count = get_expected_bullet_count()
        expected_ids = get_expected_outline_ids()

        assert len(validation["doc_ids"]) == expected_count
        assert len(validation["input_ids"]) == expected_count
        assert not validation["missing_in_doc"], f"Unexpected missing_in_doc: {validation['missing_in_doc']}"
        assert not validation["missing_in_input"], f"Unexpected missing_in_input: {validation['missing_in_input']}"
        assert not validation["text_mismatches"], f"Unexpected text_mismatches: {validation['text_mismatches']}"
        assert sorted(validation["doc_ids"]) == sorted(expected_ids)

    def test_5_process_answers_insert(self, docs_service, native_bullets_doc):
        """Test inserting answers into blank document."""
        answers = flatten_questions(TEST_QUESTIONS)
        processing = process_answers(docs_service, native_bullets_doc, answers, dry_run=False)
        results = processing.get("results", [])

        # Check for errors
        error_entries = [r for r in results if r.get("status") == "error"]
        assert not error_entries, f"Processing errors: {error_entries}"

        # Check answers were inserted
        inserted = [r for r in results if r.get("status") == "inserted"]
        expected_answers = [a for a in answers if a.get("answer")]
        assert len(inserted) == len(expected_answers), \
            f"Expected {len(expected_answers)} inserted, got {len(inserted)}"

        # Verify answers appear in document
        doc = docs_service.documents().get(documentId=native_bullets_doc).execute()
        content = doc.get("body", {}).get("content", [])

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

        for answer_entry in expected_answers:
            answer_text = answer_entry["answer"]
            found = any(answer_text in p for p in all_paragraphs)
            assert found, f"Answer '{answer_text}' not found in document"

    def test_6_validation_scenarios(self, docs_service, native_bullets_doc):
        """Test various validation scenarios with partial/mismatched input."""
        # First, delete question 6's answer to create blank slot for would_insert test
        doc = docs_service.documents().get(documentId=native_bullets_doc).execute()
        content = doc.get("body", {}).get("content", [])

        for elem in content:
            if "paragraph" in elem:
                para = elem["paragraph"]
                text = ""
                for e in para.get("elements", []):
                    tr = e.get("textRun")
                    if tr:
                        text += tr.get("content", "")
                if text.strip() == "None":
                    start_idx = elem.get("startIndex")
                    end_idx = elem.get("endIndex")
                    if start_idx and end_idx:
                        docs_service.documents().batchUpdate(
                            documentId=native_bullets_doc,
                            body={"requests": [{
                                "deleteContentRange": {
                                    "range": {"startIndex": start_idx, "endIndex": end_idx}
                                }
                            }]}
                        ).execute()
                        break

        # Partial input with various scenarios
        partial_input = [
            {"outline_id": "1", "answer": "John Smith"},  # no_change
            {"outline_id": "2", "answer": "December 31, 1985"},  # would_replace
            {"outline_id": "3", "validation_text": "Years of Experience", "answer": "Updated"},  # not_found (mismatch)
            {"outline_id": "99", "validation_text": "Fake question", "answer": "Fake"},  # not_found (missing)
            {"outline_id": "5"},  # skipped (no answer)
            {"outline_id": "6", "answer": "New comment"},  # would_insert
        ]

        # Test validation
        validation = validate_questions(docs_service, native_bullets_doc, partial_input)

        assert len(validation["missing_in_doc"]) == 1
        assert validation["missing_in_doc"][0]["outline_id"] == "99"

        expected_missing = {"3a", "3b", "4", "4a", "4b", "4c"}
        actual_missing = {m["outline_id"] for m in validation["missing_in_input"]}
        assert actual_missing == expected_missing

        assert len(validation["text_mismatches"]) == 1
        assert validation["text_mismatches"][0]["outline_id"] == "3"

        # Test process_answers statuses
        processing = process_answers(docs_service, native_bullets_doc, partial_input, dry_run=True)
        results = processing.get("results", [])
        status_map = {r["outline_id"]: r["status"] for r in results}

        assert status_map.get("1") == "no_change"
        assert status_map.get("2") == "would_replace"
        assert status_map.get("3") == "not_found"
        assert status_map.get("99") == "not_found"
        assert status_map.get("5") == "skipped"
        assert status_map.get("6") == "would_insert"

        # Check not_in_input entries
        not_in_input = [r for r in results if r["status"] == "not_in_input"]
        not_in_input_ids = {r["outline_id"] for r in not_in_input}
        assert not_in_input_ids == expected_missing

        # Verify has_answer flags
        has_answer_count = sum(1 for r in not_in_input if r.get("has_answer"))
        assert has_answer_count >= 5  # 3a, 3b, 4a, 4b, 4c have answers

        q4_entry = next((r for r in not_in_input if r["outline_id"] == "4"), None)
        assert q4_entry and not q4_entry.get("has_answer"), "Question 4 should have no answer"
