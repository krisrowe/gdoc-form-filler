.PHONY: help test test-all test-integration analyze fill import-answers setup clean check-access

CONFIG := config.yaml
PYTHON := python3

# Extract values from config.yaml
DOC_ID := $(shell grep '^doc_id:' $(CONFIG) 2>/dev/null | awk '{print $$2}')
QUESTIONS_FILE := $(shell grep '^questions_file:' $(CONFIG) 2>/dev/null | awk '{print $$2}')
CSV_FILE := $(shell grep '^csv_file:' $(CONFIG) 2>/dev/null | awk '{print $$2}')

# Defaults if not in config
QUESTIONS_FILE := $(or $(QUESTIONS_FILE),user-answers.json)
CSV_FILE := $(or $(CSV_FILE),user-answers.csv)

help:
	@echo "gdoc-form-filler commands:"
	@echo ""
	@echo "  make setup            - Install dependencies and create config.yaml"
	@echo "  make check-access     - Check Application Default Credentials for Docs API"
	@echo "  make test             - Run unit tests (fast, no network, safe default)"
	@echo "  make test-all         - Run all tests (unit + integration)"
	@echo "  make test-integration - Run integration tests (requires credentials)"
	@echo "  make analyze          - Analyze doc against expected questions"
	@echo "  make analyze-dump     - Dump document structure (for debugging)"
	@echo "  make fill             - Fill answers into document (dry-run)"
	@echo "  make fill-apply       - Fill answers into document (actually apply)"
	@echo "  make import-answers   - Import answers from CSV to JSON"
	@echo "  make clean            - Remove generated files"
	@echo ""
	@echo "Configuration: $(CONFIG)"
	@echo "  doc_id:         $(DOC_ID)"
	@echo "  questions_file: $(QUESTIONS_FILE)"
	@echo "  csv_file:       $(CSV_FILE)"

setup: config.yaml
	pip install -r requirements.txt
	@echo ""
	@echo "Setup complete. Edit config.yaml with your settings."
	@echo "Then run: make test"

config.yaml:
	@if [ ! -f config.yaml ]; then \
		cp config.yaml.example config.yaml; \
		echo "Created config.yaml from config.yaml.example"; \
	fi

check-access:
	@if command -v gwsa >/dev/null 2>&1; then \
		gwsa access check --only docs; \
	else \
		echo "gwsa not found. Install it from: https://github.com/krisrowe/gworkspace-access"; \
		echo ""; \
		echo "Or verify credentials manually:"; \
		echo "  gcloud auth application-default login --scopes=https://www.googleapis.com/auth/documents"; \
	fi

test:
	$(PYTHON) -m pytest

test-all:
	$(PYTHON) -m pytest tests/

test-integration:
	$(PYTHON) -m pytest tests/integration/

analyze: config.yaml
	@if [ "$(DOC_ID)" = "YOUR_DOCUMENT_ID_HERE" ] || [ -z "$(DOC_ID)" ]; then \
		echo "Error: Set doc_id in config.yaml"; exit 1; \
	fi
	$(PYTHON) analyze.py $(DOC_ID) $(QUESTIONS_FILE)

analyze-dump: config.yaml
	@if [ "$(DOC_ID)" = "YOUR_DOCUMENT_ID_HERE" ] || [ -z "$(DOC_ID)" ]; then \
		echo "Error: Set doc_id in config.yaml"; exit 1; \
	fi
	$(PYTHON) analyze.py $(DOC_ID) $(QUESTIONS_FILE) --dump-doc

fill: config.yaml
	@if [ "$(DOC_ID)" = "YOUR_DOCUMENT_ID_HERE" ] || [ -z "$(DOC_ID)" ]; then \
		echo "Error: Set doc_id in config.yaml"; exit 1; \
	fi
	$(PYTHON) form_filler.py $(DOC_ID) $(QUESTIONS_FILE) --dry-run

fill-apply: config.yaml
	@if [ "$(DOC_ID)" = "YOUR_DOCUMENT_ID_HERE" ] || [ -z "$(DOC_ID)" ]; then \
		echo "Error: Set doc_id in config.yaml"; exit 1; \
	fi
	$(PYTHON) form_filler.py $(DOC_ID) $(QUESTIONS_FILE)

import-answers: config.yaml
	$(PYTHON) csv_to_json.py $(CSV_FILE) -o $(QUESTIONS_FILE)

clean:
	rm -rf __pycache__ *.pyc
	@echo "Cleaned generated files (config.yaml and data files preserved)"
