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
- Must be fully isolated - no network calls, no file I/O
- Mock all external dependencies
- Can run in any order, in parallel
- Fast execution (< 1 second per test)

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

### Running Tests

```bash
# Run all tests
make test

# Run with alternative config file
CONFIG_FILE=config.yaml.example python test.py

# Future: Run with pytest
pytest tests/unit/              # Unit tests only (fast)
pytest tests/integration/       # Integration tests only
pytest                          # All tests
```
