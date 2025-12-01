# Contributing

## Testing

### Test Document Persistence

The integration test (`make test`) reuses a single Google Doc to avoid polluting your Drive with multiple test documents. The doc ID is stored in `.test_doc_id` (gitignored).

- If the test doc is deleted or becomes inaccessible, the test will create a new one
- The test clears and rebuilds the document content on each run
- Only the `documents` scope is required (no `drive.file` scope needed)

### Running Tests

```bash
# Use default config.yaml for token path
make test

# Use alternative config file
CONFIG_FILE=config.yaml.example python test.py
```
