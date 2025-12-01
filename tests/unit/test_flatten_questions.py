"""
Unit tests for flatten_questions function.

No network I/O required - tests pure data transformation.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from form_filler import flatten_questions


class TestFlattenQuestions:
    """Unit tests for flatten_questions()."""

    def test_simple_questions(self):
        """Test flattening simple top-level questions."""
        data = {
            "questions": [
                {"id": "1", "question": "First?", "answer": "One"},
                {"id": "2", "question": "Second?", "answer": "Two"},
            ]
        }

        result = flatten_questions(data)

        assert len(result) == 2
        assert result[0]["outline_id"] == "1"
        assert result[0]["answer"] == "One"
        assert result[0]["validation_text"] == "First?"
        assert result[1]["outline_id"] == "2"
        assert result[1]["answer"] == "Two"

    def test_nested_questions(self):
        """Test flattening nested sub-questions."""
        data = {
            "questions": [
                {
                    "id": "1",
                    "question": "Parent?",
                    "questions": [
                        {"id": "a", "question": "Child A?", "answer": "A"},
                        {"id": "b", "question": "Child B?", "answer": "B"},
                    ]
                }
            ]
        }

        result = flatten_questions(data)

        assert len(result) == 3
        assert result[0]["outline_id"] == "1"
        assert "answer" not in result[0]  # Parent has no answer
        assert result[1]["outline_id"] == "1a"
        assert result[1]["answer"] == "A"
        assert result[2]["outline_id"] == "1b"
        assert result[2]["answer"] == "B"

    def test_parent_with_answer_and_children(self):
        """Test parent that has both answer and children."""
        data = {
            "questions": [
                {
                    "id": "3",
                    "question": "Work Experience",
                    "answer": "10 years total",
                    "questions": [
                        {"id": "a", "question": "Employer?", "answer": "Acme"},
                    ]
                }
            ]
        }

        result = flatten_questions(data)

        assert len(result) == 2
        assert result[0]["outline_id"] == "3"
        assert result[0]["answer"] == "10 years total"
        assert result[1]["outline_id"] == "3a"
        assert result[1]["answer"] == "Acme"

    def test_question_without_answer(self):
        """Test questions without answers are included."""
        data = {
            "questions": [
                {"id": "1", "question": "Has answer?", "answer": "Yes"},
                {"id": "2", "question": "No answer?"},  # No answer key
            ]
        }

        result = flatten_questions(data)

        assert len(result) == 2
        assert result[0]["answer"] == "Yes"
        assert "answer" not in result[1]

    def test_validation_text_from_question(self):
        """Test that question text becomes validation_text."""
        data = {
            "questions": [
                {"id": "1", "question": "What is your name?", "answer": "John"},
            ]
        }

        result = flatten_questions(data)

        assert result[0]["validation_text"] == "What is your name?"

    def test_legacy_answers_format(self):
        """Test legacy format with 'answers' key."""
        data = {
            "answers": [
                {"outline_id": "1", "answer": "First"},
                {"outline_id": "2", "answer": "Second"},
            ]
        }

        result = flatten_questions(data)

        assert len(result) == 2
        assert result[0]["outline_id"] == "1"
        assert result[1]["outline_id"] == "2"

    def test_direct_array_format(self):
        """Test direct array format."""
        data = [
            {"outline_id": "1", "answer": "First"},
            {"outline_id": "2", "answer": "Second"},
        ]

        result = flatten_questions(data)

        assert len(result) == 2

    def test_invalid_format_raises(self):
        """Test that unrecognized format raises ValueError."""
        data = {"invalid_key": "something"}

        with pytest.raises(ValueError, match="Unrecognized input format"):
            flatten_questions(data)

    def test_mixed_structure(self):
        """Test realistic mixed structure with various question types."""
        data = {
            "questions": [
                {"id": "1", "question": "Name?", "answer": "John"},
                {"id": "2", "question": "DOB?", "answer": "1990-01-01"},
                {
                    "id": "3",
                    "question": "Work",
                    "answer": "10 years",
                    "questions": [
                        {"id": "a", "question": "Employer?", "answer": "Acme"},
                        {"id": "b", "question": "Title?", "answer": "Dev"},
                    ]
                },
                {
                    "id": "4",
                    "question": "Contact",  # No answer for parent
                    "questions": [
                        {"id": "a", "question": "Email?", "answer": "a@b.com"},
                        {"id": "b", "question": "Phone?", "answer": "555-1234"},
                    ]
                },
                {"id": "5", "question": "Status?", "answer": "Employed"},
            ]
        }

        result = flatten_questions(data)

        assert len(result) == 9
        outline_ids = [r["outline_id"] for r in result]
        assert outline_ids == ["1", "2", "3", "3a", "3b", "4", "4a", "4b", "5"]

        # Check parent with answer
        q3 = next(r for r in result if r["outline_id"] == "3")
        assert q3["answer"] == "10 years"

        # Check parent without answer
        q4 = next(r for r in result if r["outline_id"] == "4")
        assert "answer" not in q4

    def test_empty_questions_array(self):
        """Test empty questions array."""
        data = {"questions": []}

        result = flatten_questions(data)

        assert result == []

    def test_numeric_ids(self):
        """Test that numeric IDs are converted to strings."""
        data = {
            "questions": [
                {"id": 1, "question": "First?", "answer": "One"},
                {
                    "id": 2,
                    "question": "Parent",
                    "questions": [
                        {"id": "a", "question": "Child?", "answer": "A"},
                    ]
                },
            ]
        }

        result = flatten_questions(data)

        assert result[0]["outline_id"] == "1"
        assert result[1]["outline_id"] == "2"
        assert result[2]["outline_id"] == "2a"
