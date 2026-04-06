.PHONY: up down seed migrate revision test test-integration logs lint format typecheck check loadtest

up:
	docker compose up -d --build

down:
	docker compose down -v

seed:
	python3 scripts/seed.py

migrate:
	python3 -m alembic upgrade head

revision:
	python3 -m alembic revision --autogenerate -m "$(msg)"

test:
	PYTHONPATH=src pytest src/tests/ -v --ignore=src/tests/test_integration.py

test-integration:
	PYTHONPATH=src pytest src/tests/test_integration.py -v

logs:
	docker compose logs -f app

lint:
	ruff check src/ scripts/

format:
	ruff format src/ scripts/
	ruff check --fix src/ scripts/

typecheck:
	PYTHONPATH=src mypy src/app/

check: lint typecheck test

loadtest:
	k6 run scripts/k6_loadtest.js
