# Claude Code Notes

Project-specific context for Claude Code sessions.

## Google Docs API Gotchas

### Paragraph end_index includes trailing newline

When you get a paragraph's `endIndex` from the API, it includes the trailing newline character.

- To insert AFTER a paragraph: insert at `end_index` with `text + "\n"` (not `"\n" + text`)
- The newline is already there at `end_index - 1`, so inserting `"\n" + text` at `end_index` pushes content into the next paragraph

### Inserted text inherits bullet formatting

When you insert text adjacent to a bullet paragraph, the new paragraph inherits the bullet formatting.

- Use `deleteParagraphBullets` after inserting to remove unwanted bullet formatting
- Apply in the same `batchUpdate` request as the insert for atomicity

### Setting paragraph indentation

To indent a paragraph (e.g., answer under a question), use `updateParagraphStyle`:

```python
{
    "updateParagraphStyle": {
        "range": {"startIndex": start, "endIndex": end},
        "paragraphStyle": {
            "indentStart": {"magnitude": 36, "unit": "PT"},
            "indentFirstLine": {"magnitude": 36, "unit": "PT"}
        },
        "fields": "indentStart,indentFirstLine"
    }
}
```

- 36 PT is approximately one indent level
- Can be combined with other requests in a single `batchUpdate`

### Creating sub-bullets

When creating bulleted content with nesting:

1. Insert all text first
2. Set indentation for nested items BEFORE applying bullets
3. Apply `createParagraphBullets` to the entire range at once

If you apply bullets first, then try to set indentation, the nesting may not work correctly.

### Outline ID assignment

Bullet outline IDs (1, 2, 3a, 3b, etc.) are computed based on:
- List membership (`listId`)
- Nesting level
- Sequential position within the list

After inserting/deleting content, outline IDs may shift. Always re-fetch document structure after modifications.

## Project Architecture

See `CONTRIBUTING.md` for implementation details and `TODO.md` for planned changes.
