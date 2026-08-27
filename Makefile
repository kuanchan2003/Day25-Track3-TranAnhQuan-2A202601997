.PHONY: test lint typecheck run-chaos report clean docker-up docker-down

test:
	uv run --extra dev pytest -q

lint:
	uv run --extra dev ruff check src tests scripts

typecheck:
	uv run --extra dev mypy src

run-chaos:
	uv run python scripts/run_chaos.py --config configs/default.yaml --out reports/metrics.json

report:
	uv run python scripts/generate_report.py --metrics reports/metrics.json --out reports/final_report.md

docker-up:
	docker compose up -d

docker-down:
	docker compose down

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache reports/metrics.json reports/final_report.md
