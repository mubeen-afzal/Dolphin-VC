#!/usr/bin/env sh
set -eu

pytest -q --cov=app --cov-report=term-missing
ruff check .
mypy app/services app/schemas

