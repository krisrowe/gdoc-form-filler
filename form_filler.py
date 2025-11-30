#!/usr/bin/env python3
"""
Google Doc Form Filler

Reads a Google Doc structured as a form with numbered/lettered bullets,
and fills in answers based on an input JSON file keyed by outline position.
"""

import argparse
import json
import logging
import os
import re
import sys
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Google Docs API scope
SCOPES = ["https://www.googleapis.com/auth/documents"]


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

            # Top-level answer
            if "answer" in q:
                entry = {
                    "outline_id": main_id,
                    "answer": q["answer"]
                }
                if "question" in q:
                    entry["validation_text"] = q["question"]
                answers.append(entry)

            # Nested sub-questions
            if "questions" in q and isinstance(q["questions"], list):
                for sub_q in q["questions"]:
                    sub_id = str(sub_q.get("id", ""))
                    if "answer" in sub_q:
                        entry = {
                            "outline_id": f"{main_id}{sub_id}",
                            "answer": sub_q["answer"]
                        }
                        if "question" in sub_q:
                            entry["validation_text"] = sub_q["question"]
                        answers.append(entry)

    elif "answers" in data:
        # Legacy format: {"answers": [...]}
        answers = data["answers"]
    elif isinstance(data, list):
        # Direct array format
        answers = data
    else:
        raise ValueError("Unrecognized input format. Expected 'questions' array or 'answers' key.")

    return answers


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
        logger.info("Token refreshed and saved.")

    if not creds or not creds.valid:
        raise ValueError("Invalid credentials. Please regenerate the token.")

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


def get_document_structure(service, doc_id: str) -> list[dict]:
    """
    Fetch document and return a structured list of paragraphs with metadata.

    Returns a list of dicts, each containing:
    - index: position in the document content array
    - start_index: character start index in the document
    - end_index: character end index in the document
    - text: the paragraph text
    - is_bullet: whether this is a bulleted paragraph
    - nesting_level: bullet nesting level (0-based)
    - outline_id: computed outline identifier (e.g., "1", "2", "3a", "3b")
    - indent_start: left indent in points (for detecting answer paragraphs)
    """
    doc = service.documents().get(documentId=doc_id).execute()
    content = doc.get("body", {}).get("content", [])

    paragraphs = []
    # Track bullet counters per list and nesting level
    # list_counters[list_id][nesting_level] = current_count
    list_counters = {}
    current_outline_stack = []  # Stack of (nesting_level, identifier)

    for idx, element in enumerate(content):
        if "paragraph" not in element:
            continue

        para = element["paragraph"]
        para_style = para.get("paragraphStyle", {})
        bullet = para.get("bullet")

        text = get_paragraph_text(para)
        start_index = element.get("startIndex", 0)
        end_index = element.get("endIndex", 0)

        # Get indentation
        indent_start = para_style.get("indentStart", {}).get("magnitude", 0)

        para_info = {
            "content_index": idx,
            "start_index": start_index,
            "end_index": end_index,
            "text": text,
            "is_bullet": bullet is not None,
            "nesting_level": None,
            "outline_id": None,
            "indent_start": indent_start,
        }

        if bullet:
            list_id = bullet.get("listId", "default")
            nesting_level = bullet.get("nestingLevel", 0)
            para_info["nesting_level"] = nesting_level

            # Initialize list counter if needed
            if list_id not in list_counters:
                list_counters[list_id] = {}

            # Reset counters for deeper levels when we go back up
            levels_to_remove = [
                lvl for lvl in list_counters[list_id] if lvl > nesting_level
            ]
            for lvl in levels_to_remove:
                del list_counters[list_id][lvl]

            # Also trim the outline stack
            while current_outline_stack and current_outline_stack[-1][0] >= nesting_level:
                current_outline_stack.pop()

            # Increment counter for this level
            if nesting_level not in list_counters[list_id]:
                list_counters[list_id][nesting_level] = 0
            list_counters[list_id][nesting_level] += 1

            count = list_counters[list_id][nesting_level]

            # Determine the identifier format based on nesting level
            # Level 0: numbers (1, 2, 3...)
            # Level 1: lowercase letters (a, b, c...)
            # Level 2: roman numerals (i, ii, iii...)
            # etc.
            if nesting_level == 0:
                identifier = str(count)
            elif nesting_level == 1:
                identifier = chr(ord('a') + count - 1) if count <= 26 else f"a{count - 26}"
            elif nesting_level == 2:
                romans = ['i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii', 'viii', 'ix', 'x']
                identifier = romans[count - 1] if count <= 10 else f"r{count}"
            else:
                identifier = f"L{nesting_level}_{count}"

            # Build full outline ID from parent context
            if nesting_level == 0:
                outline_id = identifier
            else:
                # Get parent's outline_id
                parent_outline = ""
                for level, oid in current_outline_stack:
                    if level == nesting_level - 1:
                        parent_outline = oid
                        break
                outline_id = parent_outline + identifier

            para_info["outline_id"] = outline_id
            current_outline_stack.append((nesting_level, outline_id))

        paragraphs.append(para_info)

    return paragraphs


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
) -> tuple[int, Optional[dict]]:
    """
    Determine where to insert/update the answer for a question.

    Returns:
        (insertion_index, existing_answer_para)
        - insertion_index: character index where new text should be inserted
        - existing_answer_para: if there's an existing answer paragraph, return it
    """
    q_idx = paragraphs.index(question_para)
    q_indent = question_para.get("indent_start", 0)

    # Look at the next paragraph
    if q_idx + 1 >= len(paragraphs):
        # Question is at the end - insert after it
        return question_para["end_index"], None

    next_para = paragraphs[q_idx + 1]

    # If next paragraph is a bullet, insert between question and next bullet
    if next_para["is_bullet"]:
        # Insert point is right after the question paragraph
        return question_para["end_index"], None

    # Next paragraph is not a bullet - check if it's an answer (indented)
    next_indent = next_para.get("indent_start", 0)

    if next_indent > q_indent:
        # This appears to be an existing answer
        return next_para["start_index"], next_para

    # Not indented more - insert after question
    return question_para["end_index"], None


def insert_answer(
    service,
    doc_id: str,
    index: int,
    answer_text: str
) -> None:
    """Insert answer text at the specified index."""
    requests = [
        {
            "insertText": {
                "location": {"index": index},
                "text": f"\n{answer_text}"
            }
        }
    ]
    service.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": requests}
    ).execute()
    logger.info(f"Inserted answer at index {index}")


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
    logger.info(f"Replaced answer at index {start}-{end}")


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
        Dict with processing results
    """
    results = {
        "processed": [],
        "skipped": [],
        "mismatches": [],
        "errors": []
    }

    for answer_entry in answers:
        outline_id = answer_entry.get("outline_id")
        validation_text = answer_entry.get("validation_text")
        answer_text = answer_entry.get("answer")

        if not outline_id or not answer_text:
            results["errors"].append({
                "entry": answer_entry,
                "error": "Missing outline_id or answer"
            })
            continue

        # Re-fetch document structure each time (indices change after edits)
        paragraphs = get_document_structure(service, doc_id)

        # Find the question
        question_para = find_question_paragraph(
            paragraphs, outline_id, validation_text
        )

        if not question_para:
            results["skipped"].append({
                "outline_id": outline_id,
                "reason": f"Question not found for outline {outline_id}"
            })
            continue

        # Determine insertion point
        insert_idx, existing_answer = determine_insertion_point(
            paragraphs, question_para
        )

        if existing_answer:
            existing_text = existing_answer["text"].strip()
            new_text = answer_text.strip()

            if existing_text == new_text:
                results["processed"].append({
                    "outline_id": outline_id,
                    "action": "no_change",
                    "message": "Answer already matches"
                })
                continue

            # Log mismatch
            results["mismatches"].append({
                "outline_id": outline_id,
                "existing": existing_text,
                "new": new_text,
                "question": question_para["text"][:100]
            })

            if not dry_run:
                replace_answer(service, doc_id, existing_answer, answer_text)
                results["processed"].append({
                    "outline_id": outline_id,
                    "action": "replaced"
                })
            else:
                results["processed"].append({
                    "outline_id": outline_id,
                    "action": "would_replace"
                })
        else:
            if not dry_run:
                insert_answer(service, doc_id, insert_idx, answer_text)
                results["processed"].append({
                    "outline_id": outline_id,
                    "action": "inserted"
                })
            else:
                results["processed"].append({
                    "outline_id": outline_id,
                    "action": "would_insert"
                })

    return results


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
        "--token",
        default="user_token.json",
        help="Path to user_token.json (default: user_token.json)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes"
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

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        creds = load_credentials(args.token)
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

        results = process_answers(
            service,
            args.doc_id,
            answers,
            dry_run=args.dry_run
        )

        print("\n=== Processing Results ===")
        print(f"Processed: {len(results['processed'])}")
        print(f"Skipped: {len(results['skipped'])}")
        print(f"Mismatches: {len(results['mismatches'])}")
        print(f"Errors: {len(results['errors'])}")

        if results["mismatches"]:
            print("\n=== Mismatches ===")
            for m in results["mismatches"]:
                print(f"\nOutline {m['outline_id']}:")
                print(f"  Question: {m['question']}")
                print(f"  Existing: {m['existing'][:100]}...")
                print(f"  New: {m['new'][:100]}...")

        if results["errors"]:
            print("\n=== Errors ===")
            for e in results["errors"]:
                print(f"  {e}")

        return 0 if not results["errors"] else 1

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
