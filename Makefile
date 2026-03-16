# =============================================================================
# Galaxy Agentic OS — Top-Level Makefile
# =============================================================================
#
# Targets:
#   fmt          — auto-format Python source (black + isort)
#   lint         — static analysis (flake8 on core/ + tests/)
#   test:fast    — pytest smoke suite (-m "not slow"), fast CI gate
#   contract     — protobuf stub generation + proto lint
#   quick-verify — run the 10-min local minimal-stack smoke script
#   help         — show this help
#
# Usage:
#   make fmt
#   make lint
#   make test:fast
#   make contract
#   make quick-verify
#
# Cross-platform notes:
#   Linux / macOS: works as-is with make >= 3.81.
#   Windows       : use WSL2, Git Bash, or `nmake /f Makefile` with adjustments.
#                   Alternatively run the individual pip commands directly:
#                     pip install black isort flake8 pytest
#                     python -m black core/ tests/
#                     python -m isort core/ tests/
#                     python -m flake8 core/ tests/ --max-line-length=120
#                     python -m pytest tests/ -m "not slow"
# =============================================================================

.DEFAULT_GOAL := help

PYTHON   ?= python
PIP      ?= pip
SRC_DIRS  = core tests galaxy_gateway enhancements scripts
PYTEST    = $(PYTHON) -m pytest

# ── Help ──────────────────────────────────────────────────────────────────
.PHONY: help
help:
	@echo ""
	@echo "  Galaxy — available Make targets"
	@echo "  ─────────────────────────────────────────────────────"
	@echo "  fmt           Auto-format Python source (black + isort)"
	@echo "  lint          Static analysis (flake8)"
	@echo "  test:fast     Fast smoke tests (not slow)"
	@echo "  contract      Generate protobuf stubs + proto lint"
	@echo "  quick-verify  10-min local minimal-stack smoke"
	@echo "  ─────────────────────────────────────────────────────"
	@echo ""

# ── Format ────────────────────────────────────────────────────────────────
.PHONY: fmt
fmt:
	@echo "→ Formatting with black..."
	$(PYTHON) -m black core/ tests/
	@echo "→ Sorting imports with isort..."
	$(PYTHON) -m isort core/ tests/
	@echo "✓ Formatting complete."

# ── Lint ──────────────────────────────────────────────────────────────────
.PHONY: lint
lint:
	@echo "→ Linting with flake8 (max-line-length=120)..."
	$(PYTHON) -m flake8 core/ tests/ --max-line-length=120 --count --statistics
	@echo "✓ Lint complete."

# ── Fast tests ────────────────────────────────────────────────────────────
.PHONY: test\:fast
test\:fast:
	@echo "→ Running fast test suite (skipping slow)..."
	$(PYTEST) tests/ -m "not slow" -v --tb=short
	@echo "✓ Fast tests complete."

# Alias without backslash-escape (for shells that call it directly)
.PHONY: test-fast
test-fast: test\:fast

# ── Contract / Proto ──────────────────────────────────────────────────────
.PHONY: contract
contract:
	@echo "→ Building protobuf stubs + running contract lint..."
	$(MAKE) -C contracts proto-all lint
	@echo "✓ Contract build complete."

# ── Quick verify ──────────────────────────────────────────────────────────
.PHONY: quick-verify
quick-verify:
	@echo "→ Starting 10-minute local minimal-stack verify..."
	bash scripts/quick_verify.sh

# ── Install dev dependencies (convenience) ────────────────────────────────
.PHONY: install-dev
install-dev:
	$(PIP) install -r requirements.txt -r requirements-dev.txt
	@echo "✓ Dev dependencies installed."
