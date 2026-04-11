# Local parity with .github/workflows/ci.yml (lint, types, fixtures, tests).
# Requires GNU Make; on Windows, use Git Bash / WSL or run the commands manually — see README.md.

PYTHON ?= python

.PHONY: fixtures lint typecheck test ci

fixtures:
	$(PYTHON) tests/generate_fixtures.py

lint:
	ruff check .

typecheck:
	mypy hermes/

test: fixtures
	$(PYTHON) -m pytest

ci: lint typecheck fixtures test
