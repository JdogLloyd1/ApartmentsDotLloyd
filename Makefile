.DEFAULT_GOAL := help
APP_ROOT := App V1 Dynamic
BACKEND := $(APP_ROOT)/backend
COMPOSE_LOCAL := $(APP_ROOT)/docker-compose.local.yml
VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
ifeq ($(OS),Windows_NT)
  PY := $(VENV)/Scripts/python.exe
  PIP := $(VENV)/Scripts/pip.exe
endif
COMPOSE := docker compose -f "$(COMPOSE_LOCAL)"

.PHONY: help install install-dev lint format test run clean venv \
        up-local down-local logs-local build-local seed refresh-all smoke-e2e

help: ## Show available targets
	@echo "Alewife Apartment Intelligence -- developer targets"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

venv: ## Create the local virtual environment
	python -m venv $(VENV)

install: venv ## Install runtime + dev dependencies into .venv
	$(PIP) install --upgrade pip
	$(PIP) install -e "$(BACKEND)[dev,scraping,scheduling]"

install-dev: install ## Alias for `install`

lint: ## Run ruff check + format check
	cd "$(BACKEND)" && ../../$(PY) -m ruff check .
	cd "$(BACKEND)" && ../../$(PY) -m ruff format --check .

format: ## Auto-format with ruff
	cd "$(BACKEND)" && ../../$(PY) -m ruff format .
	cd "$(BACKEND)" && ../../$(PY) -m ruff check --fix .

test: ## Run the pytest suite
	cd "$(BACKEND)" && ../../$(PY) -m pytest

run: ## Start uvicorn in reload mode on port 8000
	cd "$(BACKEND)" && ../../$(PY) -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

build-local: ## Build the local Docker image (no cache)
	$(COMPOSE) build --no-cache

up-local: ## Bring up the local stack in the background (builds if needed)
	$(COMPOSE) up -d --build
	@echo "Dashboard: http://localhost:8000/"
	@echo "Health:    http://localhost:8000/api/health"

down-local: ## Stop the local stack and remove containers
	$(COMPOSE) down

logs-local: ## Follow logs from the local stack
	$(COMPOSE) logs -f --tail=100 api

seed: ## Load buildings_seed.json into the running container's DB
	$(COMPOSE) exec api python -m app.seed.loader

refresh-all: ## Run ORS + scrapers end-to-end inside the running container
	$(COMPOSE) exec api python -m app.refresh_cli

smoke-e2e: ## Run the E2E smoke suite against http://localhost:8000
	cd "$(BACKEND)" && E2E=1 ../../$(PY) -m pytest tests/e2e -v

clean: ## Remove caches, build artifacts, and the local SQLite DB
	rm -rf $(VENV)
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type d -name .ruff_cache -exec rm -rf {} +
	find . -type d -name .mypy_cache -exec rm -rf {} +
	find "$(BACKEND)" -name "*.db" -delete
