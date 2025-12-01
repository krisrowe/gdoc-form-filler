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
