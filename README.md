# Google Doc Form Filler

Fill answers into a Google Doc structured as a form with numbered/lettered bullet outlines.

## Quick Start

**1. Setup**
```bash
make setup
# Edit config.yaml with your doc_id
```

**2. Generate OAuth token** (requires [gwsa](https://github.com/krisrowe/gworkspace-access) CLI)
```bash
gwsa create-token \
  --scope https://www.googleapis.com/auth/documents \
  --scope https://www.googleapis.com/auth/drive.file \
  --client-creds ~/.config/gworkspace-access/client_secrets.json \
  --output user_token.json
```

**3. Test** (creates temp doc, runs tests, deletes doc)
```bash
make test
```

**4. Import your answers from CSV**
```bash
cp answers.csv.example answers.csv
# Edit answers.csv with your data
make import-answers
```

**5. Analyze and fill**
```bash
make analyze      # Check document structure
make fill         # Dry-run
make fill-apply   # Apply changes
```

---

## Prerequisites

- Python 3.10+
- [gwsa](https://github.com/krisrowe/gworkspace-access) CLI for OAuth token generation
- Google Cloud project with Docs API enabled

## Installation

```bash
git clone <this-repo>
cd gdoc-form-filler
make setup
```

This installs dependencies and creates `config.yaml` from the template.

## Configuration

Edit `config.yaml`:

```yaml
token: user_token.json
doc_id: 1aBcDeFgHiJkLmNoPqRsTuVwXyZ  # Your Google Doc ID
questions_file: answers.json
csv_file: answers.csv
```

The doc ID is the long string in your Google Doc URL:
```
https://docs.google.com/document/d/[DOC_ID_HERE]/edit
```

## OAuth Token

Generate a token with Docs and Drive scopes:

```bash
gwsa create-token \
  --scope https://www.googleapis.com/auth/documents \
  --scope https://www.googleapis.com/auth/drive.file \
  --client-creds ~/.config/gworkspace-access/client_secrets.json \
  --output user_token.json
```

This opens a browser for Google OAuth consent. The token is saved locally and auto-refreshes.

---

## Commands

| Command | Description |
|---------|-------------|
| `make setup` | Install dependencies, create config.yaml |
| `make test` | Run integration test (creates/deletes temp doc) |
| `make test-keep` | Run test but keep the document, print URL |
| `make import-answers` | Convert CSV to JSON |
| `make analyze` | Analyze doc structure against expected questions |
| `make analyze-dump` | Dump raw document structure (debugging) |
| `make fill` | Dry-run: show what would be changed |
| `make fill-apply` | Apply answers to document |
| `make clean` | Remove Python cache files |

---

## Input Format

### CSV (answers.csv)

Export from Google Sheets with these columns:

| # | ## | Question | Answer | Pending Issues | Status |
|---|-----|----------|--------|----------------|--------|
| 1 |     | What is your name? | John Smith | | Complete |
| 2 |     | Company? | Acme Corp | | Complete |
| 3 |     | Contact info: | | | |
| 3 | a   | Email? | john@example.com | | Complete |
| 3 | b   | Phone? | 555-1234 | Verify | Pending |

- `#` = main bullet number (1, 2, 3...)
- `##` = sub-bullet letter (a, b, c...) - blank for top-level
- `Question` = expected question text (for validation)
- `Answer` = your answer
- Additional columns are ignored

Run `make import-answers` to convert to JSON.

### JSON (answers.json)

```json
{
  "questions": [
    {
      "id": "1",
      "question": "What is your name?",
      "answer": "John Smith"
    },
    {
      "id": "3",
      "question": "Contact info:",
      "questions": [
        {"id": "a", "question": "Email?", "answer": "john@example.com"},
        {"id": "b", "question": "Phone?", "answer": "555-1234"}
      ]
    }
  ]
}
```

---

## Document Structure

The target Google Doc should have a bulleted outline like:

```
Introduction paragraph...

1. What is your name?
2. What company do you work for?
3. Contact information:
   a. Email address?
   b. Phone number?
4. Additional comments?

Conclusion paragraph...
```

The script identifies questions by their outline position (1, 2, 3a, 3b, etc.) and optionally validates the question text matches.

---

## Workflow Examples

### Analyze a document

```bash
# See what questions were found and if they match expectations
make analyze
```

Output:
```json
{
  "results": [
    {"id": "1", "found": true, "matched": true, "start_index": 42},
    {"id": "3b", "found": true, "matched": true, "start_index": 180}
  ]
}
```

### Preview changes

```bash
make fill
```

Shows what would be inserted/replaced without modifying the document.

### Apply changes

```bash
make fill-apply
```

Actually inserts or updates answers in the document.

### Debug document structure

```bash
make analyze-dump
```

Outputs raw paragraph data with outline IDs and character indices.

---

## Troubleshooting

### "Token file not found"
Run the `gwsa create-token` command to generate `user_token.json`.

### "Set doc_id in config.yaml"
Edit `config.yaml` and add your Google Doc ID.

### Questions not found
- Check that your doc uses Google Docs native bullets (not manually typed "1.", "2.", etc.)
- Run `make analyze-dump` to see the actual outline IDs detected
- Outline IDs are assigned sequentially (1, 2, 3...) based on bullet order

### Token expired
Tokens auto-refresh. If issues persist, regenerate with `gwsa create-token`.

---

## Files

| File | Description |
|------|-------------|
| `config.yaml` | Your local configuration (gitignored) |
| `user_token.json` | OAuth token (gitignored) |
| `answers.csv` | Your answers in CSV format (gitignored) |
| `answers.json` | Your answers in JSON format (gitignored) |
| `*.example` | Template files (committed) |
