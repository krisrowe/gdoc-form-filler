"""
Unit tests for report.py - Markdown report generation.

No network I/O required - tests pure transformation of JSON to Markdown.
"""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from report import generate_report


# Sample results data covering all status types
SAMPLE_RESULTS = {
    "doc_id": "test-doc-id-12345",
    "validation": {
        "doc_question_count": 8,
        "input_question_count": 5,
        "doc_ids": ["1", "2", "3", "3a", "3b", "4", "5", "6"],
        "input_ids": ["1", "2", "3", "5", "99"],
        "missing_in_doc": [{"outline_id": "99", "validation_text": "Fake question"}],
        "missing_in_input": [
            {"outline_id": "3a", "doc_text": "Sub question a"},
            {"outline_id": "3b", "doc_text": "Sub question b"},
            {"outline_id": "4", "doc_text": "Question 4"},
        ],
        "text_mismatches": [
            {"outline_id": "3", "expected": "Work Experience", "found": "Years of Experience"}
        ]
    },
    "results": [
        {"outline_id": "1", "status": "no_change", "actions": [], "match_type": "answer_matches", "matched_text": "John Smith"},
        {"outline_id": "2", "status": "would_replace", "actions": ["would_replace"], "previous_answer": "January 1, 1990", "new_answer": "December 31, 1985"},
        {"outline_id": "3", "status": "not_found", "actions": [], "reason": "Question not found in document"},
        {"outline_id": "5", "status": "skipped", "actions": [], "reason": "No answer provided"},
        {"outline_id": "99", "status": "not_found", "actions": [], "reason": "Question not found in document"},
        {"outline_id": "3a", "status": "not_in_input", "actions": [], "has_answer": True, "existing_answer": "Sub answer a"},
        {"outline_id": "3b", "status": "not_in_input", "actions": [], "has_answer": True, "existing_answer": "Sub answer b"},
        {"outline_id": "4", "status": "not_in_input", "actions": [], "has_answer": False},
    ]
}

# Results with long text to test truncation
RESULTS_WITH_LONG_TEXT = {
    "doc_id": "test-doc-long",
    "validation": {
        "doc_question_count": 2,
        "input_question_count": 2,
        "doc_ids": ["1", "2"],
        "input_ids": ["1", "2"],
        "missing_in_doc": [],
        "missing_in_input": [],
        "text_mismatches": []
    },
    "results": [
        {
            "outline_id": "1",
            "status": "would_replace",
            "actions": ["would_replace"],
            "previous_answer": "This is a very long previous answer that should be truncated in the report",
            "new_answer": "This is an equally long new answer that also needs truncation for display"
        },
        {
            "outline_id": "2",
            "status": "not_in_input",
            "actions": [],
            "has_answer": True,
            "existing_answer": "Another long existing answer in the document that exceeds the truncation limit"
        }
    ]
}

# Results with inserted answers
RESULTS_WITH_INSERTS = {
    "doc_id": "test-doc-inserts",
    "validation": {
        "doc_question_count": 3,
        "input_question_count": 3,
        "doc_ids": ["1", "2", "3"],
        "input_ids": ["1", "2", "3"],
        "missing_in_doc": [],
        "missing_in_input": [],
        "text_mismatches": []
    },
    "results": [
        {"outline_id": "1", "status": "inserted", "actions": ["inserted"], "new_answer": "New answer 1"},
        {"outline_id": "2", "status": "would_insert", "actions": ["would_insert"], "new_answer": "Would insert answer 2"},
        {"outline_id": "3", "status": "replaced", "actions": ["replaced"], "previous_answer": "Old", "new_answer": "New"},
    ]
}

# Results with warnings and errors
RESULTS_WITH_WARNINGS = {
    "doc_id": "test-doc-warnings",
    "validation": {
        "doc_question_count": 2,
        "input_question_count": 2,
        "doc_ids": ["1", "2"],
        "input_ids": ["1", "2"],
        "missing_in_doc": [],
        "missing_in_input": [],
        "text_mismatches": []
    },
    "results": [
        {
            "outline_id": "1",
            "status": "inserted",
            "actions": ["inserted"],
            "warning": "Could not reliably detect existing answer. This is the last question."
        },
        {"outline_id": "2", "status": "error", "actions": [], "error": "Missing outline_id"}
    ]
}


class TestReportGeneration:
    """Unit tests for Markdown report generation."""

    def test_generate_report_creates_file(self):
        """Test that generate_report creates a markdown file."""
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            md_file = f.name

        try:
            generate_report(SAMPLE_RESULTS, "test-doc-id", md_file)
            assert os.path.exists(md_file)
            with open(md_file) as f:
                content = f.read()
            assert "# Form Filler Results" in content
        finally:
            os.unlink(md_file)

    def test_report_contains_doc_link(self):
        """Test that report contains link to Google Doc."""
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            md_file = f.name

        try:
            generate_report(SAMPLE_RESULTS, "my-doc-id-123", md_file)
            with open(md_file) as f:
                content = f.read()
            assert "https://docs.google.com/document/d/my-doc-id-123/edit" in content
        finally:
            os.unlink(md_file)

    def test_report_contains_json_link(self):
        """Test that report contains link to JSON file."""
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            md_file = f.name

        try:
            generate_report(SAMPLE_RESULTS, "doc-id", md_file, json_file="results.json")
            with open(md_file) as f:
                content = f.read()
            assert "[View JSON](results.json)" in content
        finally:
            os.unlink(md_file)

    def test_report_validation_summary(self):
        """Test that validation summary is correctly rendered."""
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            md_file = f.name

        try:
            generate_report(SAMPLE_RESULTS, "doc-id", md_file)
            with open(md_file) as f:
                content = f.read()

            assert "Document questions | 8" in content
            assert "Input questions | 5" in content
            assert "Missing in doc | 1" in content
            assert "Missing in input | 3" in content
            assert "Text mismatches | 1" in content
        finally:
            os.unlink(md_file)

    def test_report_table_headers(self):
        """Test that results table has correct headers."""
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            md_file = f.name

        try:
            generate_report(SAMPLE_RESULTS, "doc-id", md_file)
            with open(md_file) as f:
                content = f.read()

            assert "| ID | Input | Doc | Action | Details |" in content
        finally:
            os.unlink(md_file)

    def test_report_status_no_change(self):
        """Test no_change status shows matched text in both columns."""
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            md_file = f.name

        try:
            generate_report(SAMPLE_RESULTS, "doc-id", md_file)
            with open(md_file) as f:
                content = f.read()

            # no_change should show same text in Input and Doc
            assert "`John Smith`" in content
            assert "no change" in content
        finally:
            os.unlink(md_file)

    def test_report_status_would_replace(self):
        """Test would_replace status shows old and new values."""
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            md_file = f.name

        try:
            generate_report(SAMPLE_RESULTS, "doc-id", md_file)
            with open(md_file) as f:
                content = f.read()

            assert "`December 31, 1985`" in content  # new answer in Input
            assert "`January 1, 1990`" in content  # old answer in Doc
            assert "would replace" in content
        finally:
            os.unlink(md_file)

    def test_report_status_not_in_input(self):
        """Test not_in_input status shows dash for Input and existing answer."""
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            md_file = f.name

        try:
            generate_report(SAMPLE_RESULTS, "doc-id", md_file)
            with open(md_file) as f:
                content = f.read()

            # Should have dash in Input column for not_in_input
            assert "| **3a** | — |" in content
            assert "`Sub answer a`" in content
            # Question 4 has no answer
            assert "_(blank)_" in content
        finally:
            os.unlink(md_file)

    def test_report_status_skipped(self):
        """Test skipped status shows (no answer) in Input."""
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            md_file = f.name

        try:
            generate_report(SAMPLE_RESULTS, "doc-id", md_file)
            with open(md_file) as f:
                content = f.read()

            assert "_(no answer)_" in content
            assert "skipped" in content
        finally:
            os.unlink(md_file)

    def test_report_truncation_with_length(self):
        """Test that long text is truncated with length shown."""
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            md_file = f.name

        try:
            generate_report(RESULTS_WITH_LONG_TEXT, "doc-id", md_file)
            with open(md_file) as f:
                content = f.read()

            # Should show truncated text with ... and length in parentheses
            assert "..." in content
            # Length should appear for truncated text
            assert "(7" in content or "(6" in content or "(5" in content  # Various possible lengths
        finally:
            os.unlink(md_file)

    def test_report_inserted_status(self):
        """Test inserted status shows new answer and blank Doc."""
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            md_file = f.name

        try:
            generate_report(RESULTS_WITH_INSERTS, "doc-id", md_file)
            with open(md_file) as f:
                content = f.read()

            assert "`New answer 1`" in content
            assert "inserted" in content
        finally:
            os.unlink(md_file)

    def test_report_warnings_in_details(self):
        """Test warnings appear in Details column."""
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            md_file = f.name

        try:
            generate_report(RESULTS_WITH_WARNINGS, "doc-id", md_file)
            with open(md_file) as f:
                content = f.read()

            assert "Could not reliably detect" in content
        finally:
            os.unlink(md_file)

    def test_report_errors_in_details(self):
        """Test errors appear in Details column."""
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            md_file = f.name

        try:
            generate_report(RESULTS_WITH_WARNINGS, "doc-id", md_file)
            with open(md_file) as f:
                content = f.read()

            assert "Missing outline_id" in content
            assert "error" in content
        finally:
            os.unlink(md_file)

    def test_report_summary_totals(self):
        """Test summary line shows correct totals."""
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            md_file = f.name

        try:
            generate_report(SAMPLE_RESULTS, "doc-id", md_file)
            with open(md_file) as f:
                content = f.read()

            assert "**Total: 8**" in content
        finally:
            os.unlink(md_file)
