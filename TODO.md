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

---

## Priority: Confirmed Bugs

### 1. Document structure corruption after first insert

**Behavior observed:**
- After `process_answers` inserts the first answer into the document, subsequent operations fail
- Outline ID lookups return wrong paragraphs (e.g., looking for outline "4" returns question 3's text "Contact Information")
- Sub-bullet outline_ids (3a, 3b, 3c) disappear from the parsed structure entirely
- Validation text no longer matches expected paragraphs
- The function re-fetches document structure after each edit via `get_document_structure()`, but the returned structure is corrupted

**Root cause analysis:**
The issue is in `find_question_paragraph()` at `form_filler.py:269`. After an insert, we re-fetch the document and search for the outline_id. However:
1. `get_document_structure()` computes outline_ids based on bullet nesting and sequence
2. When we insert a non-bullet answer paragraph, it doesn't affect bullet numbering
3. BUT the `paragraphs` list now contains additional entries (the inserted answers)
4. `determine_insertion_point()` uses `paragraphs.index(question_para)` to find position
5. This index is into the NEW paragraphs list, which has different positions than before

**Proposed fix:**
Option A: Only track bullet paragraphs in the list used for index arithmetic, keep non-bullets separate
Option B: Use `start_index`/`end_index` (character positions) instead of list indices for insertion point calculation
Option C: Store the question's character `end_index` at lookup time, use that directly for insertion

### 2. Answer inserted at end of document instead of after question

**Behavior observed:**
- Running `make test` results in answer text appearing at the very end of the document
- The answer appears below the "Conclusion" paragraph instead of after its question
- Answer has blue color applied (so `insert_answer` ran), but at wrong location
- Specifically observed: "THIS SHOULD BE BLUE" at document end (from debug/test session)

**Root cause analysis:**
In `determine_insertion_point()` at `form_filler.py:282-317`:

```python
q_idx = paragraphs.index(question_para)  # Line 294
# ...
next_para = paragraphs[q_idx + 1]  # Line 302
```

The code finds the question in the `paragraphs` list, then looks at `q_idx + 1` to check the "next" paragraph. Problems:

1. `paragraphs` contains ALL paragraphs (intro, bullets, answers, conclusion)
2. After inserting answer for question 1, the list has a new paragraph between Q1 and Q2
3. When processing question 2, `q_idx + 1` might now point to the answer we just inserted for Q1
4. The logic then incorrectly determines insertion point based on this wrong "next" paragraph
5. In worst case, the calculated `insert_idx` points to end of document

**Related to:** Bug #1 - both stem from using list indices that become stale after document modifications.

**Proposed fix:**
Same as Bug #1 - use character indices (`start_index`/`end_index`) from the API rather than list position arithmetic. The character indices are absolute positions in the document that remain valid references even after we re-fetch structure.

### 3. Test doesn't set CONFIG["answer_color"]

**Behavior observed:**
- Test 5 in `test.py` calls `process_answers()` directly
- Answers are inserted but without color styling
- The `answer_color` config is never applied during tests

**Root cause analysis:**
- `form_filler.CONFIG` is a module-level dict initialized with `{"answer_color": None}`
- `CONFIG["answer_color"]` is only populated in `main()` when loading `config.yaml`
- `test.py` imports `process_answers` and calls it directly, bypassing `main()`
- Therefore `CONFIG["answer_color"]` remains `None` and no color is applied

**Fix:**
In `test.py`, before calling `process_answers()`, set the config:

```python
import form_filler
form_filler.CONFIG["answer_color"] = "blue"
```

Alternatively, have `test.py` load `config.yaml` the same way `main()` does, but explicit setting is cleaner for tests.

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
