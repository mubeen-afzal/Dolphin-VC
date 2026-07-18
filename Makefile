.PHONY: help up down logs migrate seed test test-unit lint fmt typecheck openapi

help:
	@echo "up | down | logs | migrate | seed | test | test-unit | lint | fmt | typecheck | openapi"

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f api worker

migrate:
	docker compose run --rm api alembic upgrade head

seed:
	docker compose run --rm api python -m scripts.seed

test:
	docker compose -f docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from tests tests

test-unit:
	cd backend && pytest -q tests/unit tests/contract

lint:
	cd backend && ruff check .

fmt:
	cd backend && ruff format . && ruff check --fix .

typecheck:
	cd backend && mypy app/services app/schemas

openapi:
	cd backend && python scripts/export_openapi.py
