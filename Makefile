# Makefile for spec-driven-workflow development

.PHONY: help install install-dev clean test test-cov lint format type-check security qa pre-commit build

help:  ## Show this help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

install:  ## Install the package in development mode
	uv pip install -e .

install-dev:  ## Install development dependencies
	uv pip install -e ".[dev]"
	pre-commit install

clean:  ## Clean build artifacts and cache
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf htmlcov/
	rm -rf .coverage
	rm -rf coverage.xml
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	rm -rf .ruff_cache/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

test:  ## Run tests
	pytest

test-cov:  ## Run tests with coverage
	pytest --cov=spec_driven_workflow --cov-report=html --cov-report=term-missing

test-fast:  ## Run tests excluding slow tests
	pytest -m "not slow"

lint:  ## Run ruff linter
	ruff check .

lint-fix:  ## Run ruff linter with auto-fix
	ruff check --fix .

format:  ## Format code with ruff
	ruff format .

type-check:  ## Run mypy type checker
	mypy spec_driven_workflow

security:  ## Run security checks
	bandit -r spec_driven_workflow -f json

qa: lint type-check security test  ## Run all quality assurance checks

pre-commit:  ## Run pre-commit hooks on all files
	pre-commit run --all-files

build:  ## Build the package
	python -m build

release-check: qa build  ## Run all checks before release
	@echo "✅ All checks passed! Ready for release."

# Development commands
dev-setup: install-dev  ## Set up development environment
	@echo "Development environment set up successfully!"

dev-test:  ## Run tests in development mode with verbose output
	pytest -v --tb=short

dev-lint:  ## Run linting in development mode with detailed output
	ruff check --show-source --show-fixes .

# CI/CD helpers
ci-install:  ## Install for CI/CD
	uv pip install -e ".[dev]"

ci-test:  ## Run tests for CI/CD
	pytest --cov=spec_driven_workflow --cov-report=xml --cov-report=term

ci-lint:  ## Run linting for CI/CD
	ruff check --output-format=github .

ci-type-check:  ## Run type checking for CI/CD
	mypy spec_driven_workflow --junit-xml=mypy-results.xml

# Documentation
docs-serve:  ## Serve documentation locally (if docs exist)
	@echo "Documentation serving not yet implemented"

# Performance testing
perf-test:  ## Run performance tests
	pytest -m slow -v

# Debugging helpers
debug-deps:  ## Show dependency tree
	uv pip show spec-driven-workflow

debug-env:  ## Show environment information
	@echo "Python version: $(shell python --version)"
	@echo "UV version: $(shell uv --version)"
	@echo "Ruff version: $(shell ruff --version)"
	@echo "MyPy version: $(shell mypy --version)"
	@echo "Pytest version: $(shell pytest --version)"
