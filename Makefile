.PHONY: help install dev test boot prod migrate parity lint clean

PY ?= venv/bin/python
PIP ?= venv/bin/pip

help: ## Show this help.
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

venv: ## Create the virtualenv if it doesn't already exist.
	@test -d venv || python3 -m venv venv

install: venv ## Install runtime + dev dependencies.
	$(PIP) install -q -r requirements.txt -r requirements-dev.txt

dev: ## Boot the full stack (Docker + uvicorn) — see start.sh.
	./start.sh

prod: ## Boot in single-worker production mode.
	./start.sh --prod

test: ## Run the pytest suite against the docker-compose stack.
	./start.sh --test

migrate: ## Run alembic + the v1 → PostgreSQL data migration.
	./start.sh --migrate

parity: ## Print a v1↔v2 endpoint parity report.
	$(PY) scripts/parity_diff.py

lint: ## Run pyflakes-equivalent quick sanity-check on the package.
	$(PY) -m compileall -q api repositories services schemas cache db scripts

clean: ## Remove Python caches.
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -prune -exec rm -rf {} +
