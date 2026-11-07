PYTHON ?= python3
NODE ?= node

.PHONY: requirements requirements-check
requirements:
	$(PYTHON) build_tools/requirements.py

requirements-check:
	$(PYTHON) build_tools/requirements.py --check

check:
	$(PYTHON) -m zmala_images check

lint:
	$(PYTHON) -m ruff check .

test-llt:
	$(PYTHON) -m unittest discover -s tests/server/LLT -t .
	$(PYTHON) -m unittest discover -s tests/terminal/LLT -t .

test-hlt:
	$(PYTHON) -m unittest discover -s tests/server/HLT -t .
	$(PYTHON) -m unittest discover -s tests/terminal/HLT -t .

test-adhoc:
	$(PYTHON) -m unittest discover -s tests/adhoc -t .
