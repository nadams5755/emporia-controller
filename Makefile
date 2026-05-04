VENV    := .venv
PYTHON  := python3
PIP     := $(VENV)/bin/pip
PYTEST  := $(VENV)/bin/pytest

.PHONY: test clean

test: $(VENV)/.installed
	$(PYTEST) tests/ -v -n auto

$(VENV)/.installed: requirements_test.txt
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip --quiet
	$(PIP) install -r requirements_test.txt --quiet
	touch $(VENV)/.installed

clean:
	rm -rf $(VENV)
