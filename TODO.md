# TODO

## CRITICAL: Support Text-Based Outline Numbering

### Problem

The current implementation **only supports Google Docs native bullet lists**. It relies on the `bullet` property from the Google Docs API to identify questions and compute outline_ids.

Many real-world documents use **text-based numbering** instead:
- Numbers/letters typed directly into paragraph text: "1.", "2.", "a)", "b)", etc.
- No native bullet/list formatting from Google Docs
- Common in documents imported from Word or created by users who want stable numbering

These documents have no `bullet` property in the API response - they're just regular paragraphs that happen to start with "1." or "a)" text.

### Current Behavior

`get_document_structure()` in `form_filler.py`:
- Checks `para.get("bullet")` to identify list items
- Only assigns `outline_id` to paragraphs with native bullet formatting
- Paragraphs with text-based numbering are treated as regular paragraphs with no outline_id
- `find_question_paragraph()` therefore cannot find these questions

### Required Enhancement

Support **both** outline identification methods:

1. **Native bullets** (current): Use Google Docs API `bullet` property
2. **Text-based numbering** (new): Parse paragraph text for patterns like:
   - `1.`, `2.`, `3.` (numbered)
   - `a)`, `b)`, `c)` or `a.`, `b.`, `c.` (lettered sub-items)
   - `1. a)` or `1a.` (combined parent + sub-item)
   - Roman numerals: `i.`, `ii.`, `iii.`
   - Variations with parentheses, periods, or no punctuation

### Implementation Approach

1. **Detection phase**: Determine which method the document uses
   - If any paragraph has `bullet` property → use native bullet parsing
   - Otherwise → use text-based pattern matching

2. **Text pattern parsing**: For text-based documents:
   ```python
   # Example patterns to match at start of paragraph text
   patterns = [
       r'^(\d+)\.\s*',           # "1. ", "2. "
       r'^(\d+)\s*\)',           # "1)", "2)"
       r'^([a-z])\)\s*',         # "a) ", "b) "
       r'^([a-z])\.\s*',         # "a. ", "b. "
       r'^(\d+)\.\s*([a-z])\)',  # "1. a)", "2. b)"
       r'^(\d+)([a-z])\.\s*',    # "1a. ", "2b. "
   ]
   ```

3. **Nesting detection**: For text-based numbering, determine hierarchy by:
   - Indentation level (paragraph indent from API)
   - Pattern type (numbers = top level, letters = sub-level)
   - Context from surrounding paragraphs

4. **Unified outline_id**: Both methods should produce the same outline_id format ("1", "2", "3a", "3b") so downstream code works identically.

### Configuration Option

Consider a config option to force a specific mode:

```yaml
outline_detection:
  mode: auto    # auto | native_bullets | text_based
  # auto = detect from document structure
  # native_bullets = only use Google Docs bullet property
  # text_based = only parse text patterns
```

### Test Coverage Needed

1. Document with native Google Docs bullets (current test)
2. Document with text-based numbering only
3. Document with mixed formatting (if that's even possible)
4. Various text patterns: "1.", "1)", "a.", "a)", "1.a)", "1a."
5. Nested structures detected correctly in text-based mode

### Test Document Structure

Use a single test document with a reusable test procedure:

```python
def run_test_suite(docs_service, doc_id):
    """Run tests 1-5 against the current document state."""
    # Test 1: Parse structure
    # Test 2: Analyze against expected questions
    # Test 3: Check outline IDs
    # Test 4: validate_questions
    # Test 5: process_answers
    return results

def main():
    doc_id = get_or_create_test_doc()

    # Round 1: Native bullets
    clear_document(doc_id)
    create_test_content(doc_id, outline_type="native_bullets")
    results_bullets = run_test_suite(docs_service, doc_id)

    # Round 2: Text-based numbering
    clear_document(doc_id)
    create_test_content(doc_id, outline_type="text_based")
    results_text = run_test_suite(docs_service, doc_id)

    # Report combined results
```

This approach:
- Reuses single persistent test document
- Same test logic runs against both outline formats
- `create_test_content()` accepts outline_type parameter
- Clear separation between test setup and test execution

---

## Future: Extract Reusable Doc Utilities

### Motivation

The outline detection logic is completely generic - not specific to form filling. It answers: "given a Google Doc, find paragraphs that represent numbered/lettered outline items."

Other utilities being built here are also reusable:
- Paragraph insertion with proper newline/index handling
- Bullet formatting removal
- Indentation management
- Text styling (color, font, size)

### Proposed Architecture

Extract reusable utilities into **gworkspace-access** (or a new `gdoc-utils` package):

```
gworkspace-access (or gdoc-utils)
  └── outline_detection.py
      - find_outline_paragraphs()
      - parse_text_based_outline()
      - parse_native_bullets()
  └── paragraph_utils.py
      - insert_paragraph_after()
      - delete_paragraph()
      - set_paragraph_indent()
  └── text_style.py
      - apply_text_color()
      - apply_font()

gdoc-form-filler
  └── form_filler.py
      - answer matching/validation logic
      - uses gdoc-utils for all doc manipulation
```

### When to Extract

Not immediate - wait until:
1. Text-based outline detection is implemented and working
2. Patterns stabilize from real-world usage
3. Clear API boundaries emerge

Then extract to shared package for reuse across projects.

---

## Future: Test Structure Refactor

### Current State

Single `test.py` at project root runs integration tests sequentially via `run_tests()` function.

### Proposed Structure

```
tests/
  ├── integration/
  │   ├── conftest.py          # Shared fixtures (docs_service, test_doc)
  │   ├── test_native_bullets.py
  │   └── test_text_based.py   # When text-based support is added
  └── unit/                    # Future unit tests
      └── test_outline_parsing.py
```

### pytest Approach for Integration Tests

Use class-based tests with module-scoped fixtures to share document state:

```python
# tests/integration/conftest.py
import pytest

@pytest.fixture(scope="module")
def docs_service():
    # Load credentials, build service
    ...

@pytest.fixture(scope="module")
def test_doc(docs_service):
    doc_id = get_or_create_test_doc(docs_service)
    clear_document(docs_service, doc_id)
    create_test_content(docs_service, doc_id, outline_type="native_bullets")
    yield doc_id


# tests/integration/test_native_bullets.py
class TestNativeBullets:
    """Integration tests for native Google Docs bullet outlines."""

    def test_1_parse_structure(self, docs_service, test_doc):
        paragraphs = get_document_structure(docs_service, test_doc)
        assert len(paragraphs) == 8

    def test_2_analyze_questions(self, docs_service, test_doc):
        ...

    def test_3_check_outline_ids(self, docs_service, test_doc):
        ...

    def test_4_validate_questions(self, docs_service, test_doc):
        ...

    def test_5_process_answers(self, docs_service, test_doc):
        ...
```

Tests run in order (alphabetically by method name). Shared `test_doc` fixture provides same document to all tests in the module.

### When to Refactor

- After text-based outline support is added (need two test modules)
- When adding unit tests for isolated functions
- If test complexity grows beyond current single-file approach

---

## Future: Service Account for CI Testing

### Goal

Use a service account to create publicly-viewable test documents, eliminating the need for user OAuth tokens in CI/automated testing.

### How It Would Work

1. Service account creates test doc (lives in service account's "drive")
2. Share doc publicly via Drive API (`anyone` role = `reader`)
3. Output public URL for viewing test results
4. Clean up doc after test run (or leave for debugging)

### Required Scopes

- `https://www.googleapis.com/auth/documents` - create/edit docs
- `https://www.googleapis.com/auth/drive.file` - share files the account created

### Security Properties

The `drive.file` scope is minimal:
- Only accesses files the service account itself created
- Cannot access any user files or other docs
- If credentials compromised, attacker can only:
  - Create spam docs (quota-limited)
  - Delete/modify test docs created by this account
  - No access to any real user data

### Requirements

- Google Cloud project (free tier works)
- Service account with JSON key
- No Workspace org required
- Works with regular consumer Google accounts

### Implementation Notes

```python
from google.oauth2 import service_account

creds = service_account.Credentials.from_service_account_file(
    'service-account.json',
    scopes=[
        'https://www.googleapis.com/auth/documents',
        'https://www.googleapis.com/auth/drive.file'
    ]
)

# After creating doc, share publicly:
drive_service.permissions().create(
    fileId=doc_id,
    body={'type': 'anyone', 'role': 'reader'}
).execute()

public_url = f"https://docs.google.com/document/d/{doc_id}/view"
```

### When to Implement

- When setting up CI/CD pipeline
- When multiple contributors need to run tests without sharing OAuth tokens

### Future Enhancement: GitHub Actions Integration

Once service account testing works locally, enable automated testing on commits:

1. Store service account JSON in GitHub Secrets (e.g., `GOOGLE_SERVICE_ACCOUNT`)
2. GitHub Actions workflow decodes secret and writes to temp file
3. Tests run automatically on push/PR
4. Public doc URL included in workflow output for debugging failed tests

```yaml
# .github/workflows/test.yml
- name: Setup credentials
  run: echo "${{ secrets.GOOGLE_SERVICE_ACCOUNT }}" | base64 -d > service-account.json

- name: Run tests
  run: python test.py --service-account service-account.json
```

This provides true CI/CD without exposing any user credentials.

---

## Resolved Bugs

### ~~1. Document structure corruption after first insert~~ ✓ FIXED

**Fix applied:** Changed `determine_insertion_point()` to use character indices (`start_index`/`end_index`) instead of list positions. Commit 99d902a.

### ~~2. Answer inserted at end of document instead of after question~~ ✓ FIXED

**Fix applied:** Same as Bug #1 - use character indices instead of `paragraphs.index()` and list indexing. Commit 99d902a.

### ~~3. Test doesn't set CONFIG["answer_color"]~~ ✓ FIXED

**Fix applied:** Added `form_filler.CONFIG["answer_color"] = "blue"` in test.py. Commit 99d902a.

---

## Open Bugs

(None currently - see Resolved Bugs above for historical issues)

---

## Replace Logic Brittleness

### HIGH PRIORITY: Indent-based answer detection is fragile

`determine_insertion_point` assumes existing answers are indented MORE than their question (line 312). If someone manually typed an answer without proper indentation, or if the answer was inserted by another tool, it won't be detected as an existing answer - leading to duplicate answers being inserted.

**Fix:** Don't rely solely on indentation. Consider:
- Any non-bullet paragraph immediately after a question is likely an answer
- Or use a marker/pattern to identify answers

### Multi-paragraph answers

`determine_insertion_point` only looks at the NEXT paragraph (line 302). If an answer spans multiple paragraphs:
- Only the first paragraph is detected as "existing answer"
- `replace_answer` only deletes/replaces that first paragraph
- Remaining paragraphs are orphaned

**Fix:** Scan forward to find ALL consecutive non-bullet paragraphs that are indented, treat them as a single answer block.

### `replace_answer` doesn't apply styling or fix indentation

Currently `replace_answer` just deletes and inserts plain text. It doesn't:
- Apply the configured color
- Set proper indentation
- Preserve or apply any other formatting

**Required behavior (always, regardless of config):**
- `replace_answer` should ALWAYS ensure proper indentation of the answer (indented under question)
- This applies to both replaced answers AND existing answers that match (no_change)
- Indentation fix is structural correctness, not styling

**Fix:** Add `answer_format` config section (all optional, defaults to API behavior):

```yaml
answer_format:
  style:
    color: blue           # Optional: text color
    font: Arial           # Optional: font family
    size: 11              # Optional: font size in pt
    restyle_existing: false  # Optional: if true, apply style to existing answers
  indentation:
    enabled: true         # Optional: default true, always fix indentation
    offset: 36            # Optional: points to indent BEYOND question indent (default 36pt)
                          # e.g., if question is at 36pt, answer will be at 72pt
```

The entire `answer_format` section is optional. Each sub-section (`style`, `indentation`) is optional. Each individual setting is optional. If missing, use defaults (indentation enabled at 36pt offset, no explicit styling).

### Report array of actions per question

The `processed` output for each question should include an array of actions taken, not just a single action string. This provides transparency into exactly what was done:

```python
{
    "outline_id": "3a",
    "actions": [
        "replaced",           # Primary action
        "fixed_indentation",  # Corrected indent to be under question
        "applied_color"       # Applied configured color
    ]
}
```

Possible action items:
- `inserted` / `replaced` / `no_change` - primary action
- `fixed_indentation` - corrected answer indentation
- `applied_color` - applied color from config
- `applied_font` - applied font from config
- `removed_bullets` - removed inherited bullet formatting

### Test coverage for replace scenarios

Need test that:
1. Creates doc with questions
2. Fills answers (first pass)
3. Runs again with DIFFERENT answers
4. Verifies answers were replaced (not duplicated)
5. Verifies styling applied correctly

---

## Test Coverage Improvements

### Required Test Scenarios

1. **Dry-run test** - Call `process_answers` with `dry_run=True`, verify no document modifications occur, verify JSON output reports `would_insert` / `would_replace` actions correctly

2. **Fresh template fill test** - Fill out a questionnaire in its original "copy of the template" form (no existing answers), verify all answers inserted correctly, validate JSON output

3. **Mixed state document test** - Operate on a doc that has been worked on prior with:
   - Questions with answers that MATCH the input (should report `no_change`)
   - Questions with answers that DO NOT match the input (should report `replaced` or `would_replace`)
   - Questions WITHOUT answers (should report `inserted` or `would_insert`)
   - Validate the JSON output of `process_answers` confirms the right action was taken AND reported correctly for each question in the outline

### JSON Output Validation

All tests should validate the JSON output structure from `process_answers` to confirm:
- Correct action type for each outline_id
- Accurate counts in processed/skipped/mismatches/errors arrays
- Error messages are meaningful when things fail

---

## Enhancements

### Redesign process_answers output structure

The current output has separate arrays (processed, skipped, mismatches, errors) which fragments the results.

**New design:** Every question (whether found in doc, answers, or both) appears exactly once in the `processed` array by its unique outline_id, with status/action indicators:

```
processed: [
  ┌─────────────┬────────────┬─────────────┬──────────────────────────────────────┐
  │ outline_id  │ in_doc     │ in_answers  │ action / status                      │
  ├─────────────┼────────────┼─────────────┼──────────────────────────────────────┤
  │ "1"         │ yes        │ yes         │ "inserted" / "would_insert"          │
  │ "2"         │ yes        │ yes         │ "replaced" / "would_replace"         │
  │ "3"         │ yes        │ yes         │ "no_change" (answer matches)         │
  │ "3a"        │ yes        │ yes         │ "inserted"                           │
  │ "3b"        │ yes        │ no          │ "missing_answer" (leaf, no answer)   │
  │ "3c"        │ yes        │ yes         │ "no_change"                          │
  │ "4"         │ yes        │ no          │ "skipped" (parent, no answer needed) │
  │ "5"         │ no         │ yes         │ "not_in_doc" (answer has no target)  │
  │ "6"         │ yes        │ no          │ "missing_answer" (leaf, no answer)   │
  └─────────────┴────────────┴─────────────┴──────────────────────────────────────┘
]
```

**Action types:**
- `inserted` / `would_insert` - answer added to doc (or would be in dry-run)
- `replaced` / `would_replace` - existing answer updated (or would be)
- `no_change` - answer already matches
- `missing_answer` - leaf question in doc has no answer in input (informational)
- `skipped` - parent question, no answer needed
- `not_in_doc` - answer provided but question not found in doc (issue)
- `error` - processing failed for this item

This eliminates the need for separate `skipped`, `mismatches`, `missing_answers` arrays - everything is unified in `processed`.

**TODO:** Transfer this visualization to CONTRIBUTING.md (architectural/implementation details)

---

## Possible Follow-ups (Require Discussion)

These items came up during development but haven't been reviewed or prioritized yet.

### 1. Test document cleanup behavior

The test currently clears and rebuilds the doc each run, but stale content ("THIS SHOULD BE BLUE") was observed persisting. Need to verify:
- Is `clear_document` actually clearing everything?
- Are there edge cases where content survives the clear?
- Should the test verify the doc is clean before proceeding?

### 2. Test should set CONFIG["answer_color"]

Already documented in Bug #3 above. Decision needed: should test.py load config.yaml, or explicitly set `form_filler.CONFIG["answer_color"]` to test colored output?

### 3. Transfer visualization to CONTRIBUTING.md

The output structure visualization table in the Enhancements section should be moved to CONTRIBUTING.md for architectural documentation. Not yet done.

### 4. Future: gworkspace-access migration

Reusable Google Docs API utilities (paragraph handling, bullet management, index calculations) could eventually move to the gworkspace-access package. Not immediate - just a future consideration once patterns stabilize.

### 5. Note: Commit message style

Preference noted during development: do not mention AI tools or code generation in commit messages. Keep commits focused on what changed, not how it was written.
