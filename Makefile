.PHONY: check test fmt lint typecheck layers run migrate probe

check: lint typecheck layers test

lint:
	uv run ruff format --check .
	uv run ruff check .

typecheck:
	uv run mypy src/poweron/core src/poweron/adapters/toe_api

layers:
	uv run lint-imports

test:
	uv run pytest -q

fmt:
	uv run ruff format .
	uv run ruff check --fix .

run:
	uv run python -m poweron all

migrate:
	uv run alembic upgrade head

probe:
	uv run python scripts/probe.py
