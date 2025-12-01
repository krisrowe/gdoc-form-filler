.PHONY: help test analyze fill import-answers setup clean

CONFIG := config.yaml
PYTHON := python3

# Extract values from config.yaml
TOKEN := $(shell grep '^token:' $(CONFIG) 2>/dev/null | awk '{print $$2}')
DOC_ID := $(shell grep '^doc_id:' $(CONFIG) 2>/dev/null | awk '{print $$2}')
QUESTIONS_FILE := $(shell grep '^questions_file:' $(CONFIG) 2>/dev/null | awk '{print $$2}')
CSV_FILE := $(shell grep '^csv_file:' $(CONFIG) 2>/dev/null | awk '{print $$2}')

# Defaults if not in config
TOKEN := $(or $(TOKEN),user_token.json)
QUESTIONS_FILE := $(or $(QUESTIONS_FILE),answers.json)
CSV_FILE := $(or $(CSV_FILE),answers.csv)

help:
	@echo "gdoc-form-filler commands:"
	@echo ""
	@echo "  make setup       - Install dependencies and create config.yaml"
	@echo "  make test        - Run integration test (reuses test doc)"
	@echo "  make analyze     - Analyze doc against expected questions"
	@echo "  make analyze-dump - Dump document structure (for debugging)"
	@echo "  make fill        - Fill answers into document (dry-run)"
	@echo "  make fill-apply  - Fill answers into document (actually apply)"
	@echo "  make import-answers - Import answers from CSV to JSON"
	@echo "  make clean       - Remove generated files"
	@echo ""
	@echo "Configuration: $(CONFIG)"
	@echo "  token:          $(TOKEN)"
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

test:
	CONFIG_FILE=config.yaml.example $(PYTHON) test.py

analyze: config.yaml
	@if [ "$(DOC_ID)" = "YOUR_DOCUMENT_ID_HERE" ] || [ -z "$(DOC_ID)" ]; then \
		echo "Error: Set doc_id in config.yaml"; exit 1; \
	fi
	$(PYTHON) analyze.py $(DOC_ID) $(QUESTIONS_FILE) --token $(TOKEN)

analyze-dump: config.yaml
	@if [ "$(DOC_ID)" = "YOUR_DOCUMENT_ID_HERE" ] || [ -z "$(DOC_ID)" ]; then \
		echo "Error: Set doc_id in config.yaml"; exit 1; \
	fi
	$(PYTHON) analyze.py $(DOC_ID) $(QUESTIONS_FILE) --token $(TOKEN) --dump-doc

fill: config.yaml
	@if [ "$(DOC_ID)" = "YOUR_DOCUMENT_ID_HERE" ] || [ -z "$(DOC_ID)" ]; then \
		echo "Error: Set doc_id in config.yaml"; exit 1; \
	fi
	$(PYTHON) form_filler.py $(DOC_ID) $(QUESTIONS_FILE) --token $(TOKEN) --dry-run

fill-apply: config.yaml
	@if [ "$(DOC_ID)" = "YOUR_DOCUMENT_ID_HERE" ] || [ -z "$(DOC_ID)" ]; then \
		echo "Error: Set doc_id in config.yaml"; exit 1; \
	fi
	$(PYTHON) form_filler.py $(DOC_ID) $(QUESTIONS_FILE) --token $(TOKEN)

import-answers: config.yaml
	$(PYTHON) csv_to_json.py $(CSV_FILE) -o $(QUESTIONS_FILE)

clean:
	rm -rf __pycache__ *.pyc
	@echo "Cleaned generated files (config.yaml and data files preserved)"
