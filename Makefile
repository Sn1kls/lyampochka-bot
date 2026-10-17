.PHONY: check test fmt lint typecheck layers run migrate probe up down logs simulate backup

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

backup:
	mkdir -p backups
	docker compose exec -T bot python -c "import sqlite3; sqlite3.connect('/data/poweron.sqlite3').backup(sqlite3.connect('/data/backup.sqlite3'))"
	docker compose cp bot:/data/backup.sqlite3 backups/poweron-$$(date +%Y%m%d-%H%M%S).sqlite3
	docker compose exec -T bot rm /data/backup.sqlite3
