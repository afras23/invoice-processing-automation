.PHONY: dev test lint format typecheck migrate docker clean evaluate evaluate-v2 evaluate-dry-run

dev:
	uvicorn app.main:app --reload --port 8000

test:
	pytest tests/ -v --tb=short

lint:
	ruff check app/ tests/
	ruff format --check app/ tests/

format:
	ruff format app/ tests/

typecheck:
	mypy app/ --ignore-missing-imports

migrate:
	alembic upgrade head

docker:
	docker-compose up --build

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .mypy_cache .pytest_cache htmlcov .coverage

evaluate:
	python scripts/evaluate.py --prompt-version v1

evaluate-v2:
	python scripts/evaluate.py --prompt-version v2

evaluate-dry-run:
	ANTHROPIC_API_KEY=$${ANTHROPIC_API_KEY:-test-key} python scripts/evaluate.py --dry-run
