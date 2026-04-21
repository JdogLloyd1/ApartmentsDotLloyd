.DEFAULT_GOAL := help
BACKEND := App V1 Dynamic/backend
VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
ifeq ($(OS),Windows_NT)
  PY := $(VENV)/Scripts/python.exe
  PIP := $(VENV)/Scripts/pip.exe
endif

.PHONY: help install install-dev lint format test run clean venv

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

lint: ## Run ruff + mypy
	cd "$(BACKEND)" && ../../$(PY) -m ruff check .
	cd "$(BACKEND)" && ../../$(PY) -m ruff format --check .

format: ## Auto-format with ruff
	cd "$(BACKEND)" && ../../$(PY) -m ruff format .
	cd "$(BACKEND)" && ../../$(PY) -m ruff check --fix .

test: ## Run the pytest suite
	cd "$(BACKEND)" && ../../$(PY) -m pytest

run: ## Start uvicorn in reload mode on port 8000
	cd "$(BACKEND)" && ../../$(PY) -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

clean: ## Remove caches, build artifacts, and the local SQLite DB
	rm -rf $(VENV)
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type d -name .ruff_cache -exec rm -rf {} +
	find . -type d -name .mypy_cache -exec rm -rf {} +
	find "$(BACKEND)" -name "*.db" -delete
