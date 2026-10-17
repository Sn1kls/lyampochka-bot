.PHONY: check test fmt lint typecheck layers run migrate probe up down logs simulate

check: lint typecheck layers test

lint:
	uv run ruff format --check .
	uv run ruff check .

typecheck:
	uv run mypy src

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

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f bot

simulate:
	docker compose exec bot python scripts/simulate_update.py
