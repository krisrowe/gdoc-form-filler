# Contributing

## Testing

### Test Structure

```
tests/
  ├── integration/       # Tests that interact with Google Docs API
  │   ├── conftest.py    # Shared fixtures (docs_service, test_doc)
  │   └── test_*.py      # Integration test modules
  └── unit/              # Isolated tests with no external dependencies
      └── test_*.py      # Unit test modules
```

### Test Guidelines

**Unit tests** (`tests/unit/`):
- Must be fully isolated - no network calls
- Test pure functions directly (no mocking needed currently)
- Can run in any order, in parallel
- Fast execution (< 1 second total)

**Integration tests** (`tests/integration/`):
- Test real interaction with Google Docs API
- May run sequentially when testing a workflow (e.g., validate → fill → verify)
- Use shared fixtures for document state
- Require valid OAuth credentials
- **Sequencing:** Use numbered prefixes on method names (e.g., `test_1_parse`, `test_2_validate`). Pytest runs tests alphabetically by default, so this ensures correct order without plugins.

### Test Document Persistence

The integration test (`make test`) reuses a single Google Doc to avoid polluting your Drive with multiple test documents. The doc ID is stored in `.test_doc_id` (gitignored).

- If the test doc is deleted or becomes inaccessible, the test will create a new one
- The test clears and rebuilds the document content on each run
- Only the `documents` scope is required (no `drive.file` scope needed)

### Configuration in Tests

Tests do **not** read from `config.yaml`. Instead, they directly manipulate the `CONFIG` singleton in `form_filler.py`:

```python
import form_filler

# Set config for this test scenario
form_filler.CONFIG["answer_color"] = "blue"

# Run test that expects blue-colored answers
result = process_answers(...)

# Test a different scenario
form_filler.CONFIG["answer_color"] = None

# Run test that expects default/no color
result = process_answers(...)
```

**Why this pattern:**
- Tests are self-contained, not dependent on external files
- Each test controls exactly the configuration it needs
- Multiple configuration scenarios can be tested in one run
- No risk of test behavior changing based on user's local config

**How it works:**
- `form_filler.CONFIG` is a module-level dict (singleton)
- `main()` loads `config.yaml` into this dict for CLI usage
- Tests set values directly, bypassing file I/O

### Running Tests

```bash
# Default: run unit tests only (fast, no credentials needed)
pytest
make test

# Run all tests (unit + integration)
make test-all

# Run integration tests only (requires credentials)
make test-integration
pytest tests/integration/
```

**Safe defaults:** Running `pytest` or `make test` with no arguments only runs unit tests. This allows anyone to clone the repo and run tests immediately without configuring credentials. Integration tests require Google Docs API credentials and are explicitly invoked.
