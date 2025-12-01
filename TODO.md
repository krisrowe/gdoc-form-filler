# TODO

## Bugs Found

### 1. Redesign process_answers output structure

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

### 2. Document structure corruption after first insert

After `process_answers` inserts one answer into the document:
- Subsequent outline ID lookups fail
- Validation text no longer matches expected paragraphs
- Sub-bullet outline_ids (3a, 3b, 3c) disappear from the parsed structure
- Example: Outline 4 paragraph text becomes "Contact Information" (question 3's text)

The function re-fetches document structure after each edit, but something breaks the outline/bullet structure after the first insertion.

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
