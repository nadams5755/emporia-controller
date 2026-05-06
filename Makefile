VENV    := .venv
PYTHON  := python3
PIP     := $(VENV)/bin/pip
PYTEST  := $(VENV)/bin/pytest
PYLINT  := $(VENV)/bin/pylint

.PHONY: test lint clean check-python

check-python:
	@$(PYTHON) -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null || \
		{ echo "Error: python3 must be >= 3.10 (found $$($(PYTHON) --version 2>&1))"; exit 1; }

lint: $(VENV)/.installed
	$(PYLINT) custom_components/ tests/

test: lint
	$(PYTEST) tests/ -v -n auto

$(VENV)/.installed: check-python requirements_test.txt
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip --quiet
	$(PIP) install -r requirements_test.txt --quiet
	touch $(VENV)/.installed

clean:
	rm -rf $(VENV)
