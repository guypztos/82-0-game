.PHONY: setup format lint typecheck test check run

setup:  ## Install dependencies and git hooks (run once per clone)
	uv sync
	uv run pre-commit install

format:  ## Format the code and apply safe lint fixes
	uv run ruff format
	uv run ruff check --fix

lint:  ## Check formatting and lint rules without changing files
	uv run ruff format --check
	uv run ruff check

typecheck:  ## Run the strict type checker
	uv run mypy

test:  ## Run the tests with coverage
	uv run pytest

check: lint typecheck test  ## Everything CI runs

run:  ## Play the game
	uv run eighty-two-o
