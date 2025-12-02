#!/usr/bin/env python3
"""
Outline detection for Google Docs.

Supports two outline identification methods:
1. Native bullets: Uses Google Docs API bullet property
2. Text-based numbering: Parses paragraph text for patterns like "1.", "a)", etc.
"""

import re
from typing import Optional


# Text-based outline patterns
# Order matters - more specific patterns first
TEXT_PATTERNS = [
    # Combined: "1. a)" or "1.a)" - parent + sub-item
    (r'^(\d+)\.\s*([a-z])\)\s*', 'combined'),
    # Combined: "1a." - parent + sub-item
    (r'^(\d+)([a-z])\.\s*', 'combined_dot'),
    # Numbered with period: "1. ", "2. "
    (r'^(\d+)\.\s+', 'number'),
    # Numbered with paren: "1)", "2)"
    (r'^(\d+)\)\s*', 'number_paren'),
    # Lettered with paren: "a) ", "b) "
    (r'^([a-z])\)\s*', 'letter_paren'),
    # Lettered with period: "a. ", "b. "
    (r'^([a-z])\.\s+', 'letter_dot'),
    # Roman numerals: "i.", "ii.", "iii."
    (r'^(i{1,3}|iv|v|vi{0,3}|ix|x)\.\s+', 'roman'),
]


def parse_text_outline(text: str) -> Optional[dict]:
    """
    Parse text-based outline numbering from paragraph text.

    Returns dict with:
        - pattern_type: type of pattern matched
        - identifier: the parsed identifier (e.g., "1", "a", "1a")
        - nesting_level: inferred nesting level
        - text_after: text after the outline marker

    Returns None if no pattern matches.
    """
    text = text.strip()

    for pattern, pattern_type in TEXT_PATTERNS:
        match = re.match(pattern, text)
        if match:
            groups = match.groups()
            text_after = text[match.end():]

            if pattern_type == 'combined':
                # "1. a)" -> parent=1, sub=a
                return {
                    'pattern_type': pattern_type,
                    'parent_id': groups[0],
                    'sub_id': groups[1].lower(),
                    'identifier': f"{groups[0]}{groups[1].lower()}",
                    'nesting_level': 1,
                    'text_after': text_after
                }
            elif pattern_type == 'combined_dot':
                # "1a." -> parent=1, sub=a
                return {
                    'pattern_type': pattern_type,
                    'parent_id': groups[0],
                    'sub_id': groups[1].lower(),
                    'identifier': f"{groups[0]}{groups[1].lower()}",
                    'nesting_level': 1,
                    'text_after': text_after
                }
            elif pattern_type in ('number', 'number_paren'):
                return {
                    'pattern_type': pattern_type,
                    'identifier': groups[0],
                    'nesting_level': 0,
                    'text_after': text_after
                }
            elif pattern_type in ('letter_paren', 'letter_dot'):
                return {
                    'pattern_type': pattern_type,
                    'identifier': groups[0].lower(),
                    'nesting_level': 1,  # Letters are sub-items
                    'text_after': text_after
                }
            elif pattern_type == 'roman':
                return {
                    'pattern_type': pattern_type,
                    'identifier': groups[0].lower(),
                    'nesting_level': 2,  # Roman numerals are deeper
                    'text_after': text_after
                }

    return None


def get_paragraph_text(para: dict) -> str:
    """Extract text content from a paragraph element."""
    text = ""
    for elem in para.get("elements", []):
        text_run = elem.get("textRun")
        if text_run:
            text += text_run.get("content", "")
    return text.strip()


def detect_outline_mode(content: list) -> str:
    """
    Detect which outline mode the document uses.

    Returns:
        'native_bullets' if any paragraph has bullet property
        'text_based' if paragraphs match text patterns
        'none' if no outline detected
    """
    has_bullets = False
    has_text_patterns = False

    for element in content:
        if "paragraph" not in element:
            continue

        para = element["paragraph"]

        # Check for native bullets
        if para.get("bullet"):
            has_bullets = True
            break

        # Check for text-based patterns
        text = get_paragraph_text(para)
        if parse_text_outline(text):
            has_text_patterns = True

    if has_bullets:
        return 'native_bullets'
    elif has_text_patterns:
        return 'text_based'
    else:
        return 'none'


def build_outline_id_native(nesting_level: int, count: int, outline_stack: list) -> str:
    """Build outline ID for native bullet items."""
    # Determine identifier format based on nesting level
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
        return identifier
    else:
        parent_outline = ""
        for level, oid in outline_stack:
            if level == nesting_level - 1:
                parent_outline = oid
                break
        return parent_outline + identifier


def parse_document_structure(content: list, mode: str = 'auto') -> list[dict]:
    """
    Parse document content and return structured paragraph list.

    Args:
        content: Document body content array from Google Docs API
        mode: 'auto', 'native_bullets', or 'text_based'

    Returns:
        List of paragraph dicts with outline_id, text, indices, etc.
    """
    if mode == 'auto':
        mode = detect_outline_mode(content)

    if mode == 'native_bullets':
        return _parse_native_bullets(content)
    elif mode == 'text_based':
        return _parse_text_based(content)
    else:
        return []


def _parse_native_bullets(content: list) -> list[dict]:
    """Parse document using native bullet properties."""
    paragraphs = []
    list_counters = {}
    current_outline_stack = []

    for idx, element in enumerate(content):
        if "paragraph" not in element:
            continue

        para = element["paragraph"]
        para_style = para.get("paragraphStyle", {})
        bullet = para.get("bullet")

        text = get_paragraph_text(para)
        start_index = element.get("startIndex", 0)
        end_index = element.get("endIndex", 0)
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

            # Trim outline stack
            while current_outline_stack and current_outline_stack[-1][0] >= nesting_level:
                current_outline_stack.pop()

            # Increment counter for this level
            if nesting_level not in list_counters[list_id]:
                list_counters[list_id][nesting_level] = 0
            list_counters[list_id][nesting_level] += 1

            count = list_counters[list_id][nesting_level]
            outline_id = build_outline_id_native(nesting_level, count, current_outline_stack)

            para_info["outline_id"] = outline_id
            current_outline_stack.append((nesting_level, outline_id))

        paragraphs.append(para_info)

    return paragraphs


def _parse_text_based(content: list) -> list[dict]:
    """Parse document using text-based outline patterns."""
    paragraphs = []
    current_parent_id = None
    letter_counters = {}  # Track letter counts per parent

    for idx, element in enumerate(content):
        if "paragraph" not in element:
            continue

        para = element["paragraph"]
        para_style = para.get("paragraphStyle", {})

        text = get_paragraph_text(para)
        start_index = element.get("startIndex", 0)
        end_index = element.get("endIndex", 0)
        indent_start = para_style.get("indentStart", {}).get("magnitude", 0)

        parsed = parse_text_outline(text)

        para_info = {
            "content_index": idx,
            "start_index": start_index,
            "end_index": end_index,
            "text": text,
            "is_bullet": parsed is not None,
            "nesting_level": None,
            "outline_id": None,
            "indent_start": indent_start,
        }

        if parsed:
            nesting_level = parsed['nesting_level']
            para_info["nesting_level"] = nesting_level

            if nesting_level == 0:
                # Top-level numbered item
                outline_id = parsed['identifier']
                current_parent_id = outline_id
                letter_counters[current_parent_id] = 0
            elif 'parent_id' in parsed:
                # Combined format like "1. a)" - has explicit parent
                outline_id = parsed['identifier']
                current_parent_id = parsed['parent_id']
            else:
                # Sub-item (letter) - attach to current parent
                if current_parent_id:
                    outline_id = current_parent_id + parsed['identifier']
                else:
                    # No parent context, use identifier alone
                    outline_id = parsed['identifier']

            para_info["outline_id"] = outline_id

        paragraphs.append(para_info)

    return paragraphs
