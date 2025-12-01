# Google Doc Form Filler

Fill Google Doc questionnaires from structured data (CSV, JSON, etc.).

## Prerequisites

Before starting, enable the Google Docs API in the same Google Cloud project used for your `client_creds.json`:

```bash
# Find your project ID in client_creds.json under "project_id"
gcloud services enable docs.googleapis.com --project=YOUR_PROJECT_ID
```

Or enable it via the [Google Cloud Console](https://console.cloud.google.com/apis/library/docs.googleapis.com).

**Requirements:**
- Python 3.10+
- Google Cloud project with Docs API enabled (as shown above)

Authentication is handled via [Application Default Credentials](https://cloud.google.com/docs/authentication/application-default-credentials) (ADC).

## Quick Start

**1. Setup**
```bash
make setup
# Edit config.yaml with your doc_id
```

**2. Authenticate** (see [Authentication](#authentication) for options)
```bash
gcloud auth application-default login --scopes=https://www.googleapis.com/auth/documents
```

**3. Test**
```bash
pytest          # Runs unit tests (fast, no credentials needed)
make test-all   # Runs all tests including integration (needs credentials)
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
doc_id: 1aBcDeFgHiJkLmNoPqRsTuVwXyZ  # Your Google Doc ID
questions_file: answers.json
csv_file: answers.csv
```

The doc ID is the long string in your Google Doc URL:
```
https://docs.google.com/document/d/[DOC_ID_HERE]/edit
```

## Authentication

This tool uses [Application Default Credentials](https://cloud.google.com/docs/authentication/application-default-credentials) (ADC), the standard Google Cloud authentication mechanism.

### Option 1: gcloud CLI (Recommended)

The simplest approach for most users:

```bash
gcloud auth application-default login --scopes=https://www.googleapis.com/auth/documents
```

This opens a browser for Google OAuth consent. Credentials are stored in `~/.config/gcloud/application_default_credentials.json` and auto-refresh.

### Option 2: Custom OAuth Token

For accounts with strict security settings (Advanced Protection Program, hardware security keys), or when you need a custom OAuth client:

1. Create a token using [gwsa](https://github.com/krisrowe/gworkspace-access):
   ```bash
   gwsa access token \
     --scope https://www.googleapis.com/auth/documents \
     --client-creds /path/to/client_secrets.json \
     --output ./user_token.json
   ```

2. Configure via `.env` file (recommended) or environment variable:
   ```bash
   # Option A: Use .env file (recommended for local development)
   cp .env.example .env

   # Option B: Set environment variable directly
   export GOOGLE_APPLICATION_CREDENTIALS=./user_token.json
   ```

The tool will automatically use this token instead of gcloud credentials.

### Option 3: Service Account (CI/CD)

For automated pipelines with Google Workspace:

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

Requires domain-wide delegation configured by your Workspace admin.

---

## Commands

| Command | Description |
|---------|-------------|
| `make setup` | Install dependencies, create config.yaml |
| `make test` | Run unit tests (fast, no credentials) |
| `make test-all` | Run all tests (unit + integration) |
| `make test-integration` | Run integration tests only |
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

### Supported Outline Formats

The tool supports two types of outline formatting:

#### 1. Native Google Docs Bullets (Currently Supported)

Documents using Google Docs' built-in numbered list formatting:

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

These are created using Format → Bullets & numbering in Google Docs. The API provides a `bullet` property that identifies list items and their nesting level.

#### 2. Text-Based Numbering (Planned)

Documents where numbers/letters are typed directly into paragraph text (common in Word imports or when authors want stable numbering):

```
1. What is your name?
2. What company do you work for?
3. Contact information:
   a) Email address?
   b) Phone number?
4. Additional comments?
```

**Patterns to be supported:**
- `1.`, `2.`, `3.` - numbered with period
- `1)`, `2)`, `3)` - numbered with parenthesis
- `a.`, `b.`, `c.` - lettered with period
- `a)`, `b)`, `c)` - lettered with parenthesis
- `1. a)`, `2. b)` - combined parent and sub-item
- `i.`, `ii.`, `iii.` - roman numerals

> **Note:** Text-based numbering support is not yet implemented. See TODO.md for details.

### How Outline IDs Work

Each question is identified by an `outline_id` like "1", "2", "3a", "3b":

| Document Position | outline_id |
|-------------------|------------|
| First top-level item | `1` |
| Second top-level item | `2` |
| Third top-level item | `3` |
| First sub-item under 3 | `3a` |
| Second sub-item under 3 | `3b` |
| Fourth top-level item | `4` |

Your answers JSON/CSV must use these same outline_ids to match questions.

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

### "Could not automatically determine credentials"
No credentials found. Either:
- Run `gcloud auth application-default login --scopes=https://www.googleapis.com/auth/documents`
- Or set `GOOGLE_APPLICATION_CREDENTIALS` to point to a token file

### "Set doc_id in config.yaml"
Edit `config.yaml` and add your Google Doc ID.

### Questions not found
- Check that your doc uses Google Docs native bullets (not manually typed "1.", "2.", etc.)
- Run `make analyze-dump` to see the actual outline IDs detected
- Outline IDs are assigned sequentially (1, 2, 3...) based on bullet order

### "Request had insufficient authentication scopes"
Your credentials don't include the Docs API scope. Re-authenticate:
```bash
gcloud auth application-default login --scopes=https://www.googleapis.com/auth/documents
```

### gcloud auth blocked by account security
Some accounts (Advanced Protection Program, hardware security keys) block gcloud's OAuth client. Use [Option 2](#option-2-custom-oauth-token) with a custom OAuth client instead.

---

## Files

| File | Description |
|------|-------------|
| `config.yaml` | Your local configuration (gitignored) |
| `.env` | Environment variables for credentials (gitignored) |
| `answers.csv` | Your answers in CSV format (gitignored) |
| `answers.json` | Your answers in JSON format (gitignored) |
| `*.example` | Template files (committed) |
