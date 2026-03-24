# =============================================================================
# Galaxy Agentic OS — Top-Level Makefile
# =============================================================================
#
# Targets:
#   fmt            — auto-format Python source (black + isort)
#   lint           — static analysis (flake8 on core/ + tests/)
#   test:fast      — pytest smoke suite (-m "not slow"), fast CI gate
#   contract       — protobuf stub generation + proto lint
#   quick-verify   — run the 10-min local minimal-stack smoke script
#   governance     — run all CI governance checks locally (mirrors node-governance.yml)
#   audit-regen    — regenerate docs/node_audit_report.json + docs/NODE_SYSTEM_AUDIT.md
#   manifest-regen — regenerate docs/NODE_ACTIVE_MANIFEST.md from canonical sources
#   regen-all      — run audit-regen then manifest-regen (full governance doc refresh)
#   help           — show this help
#
# Usage:
#   make fmt
#   make lint
#   make test:fast
#   make contract
#   make quick-verify
#   make governance
#   make audit-regen
#   make manifest-regen
#   make regen-all
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
	@echo "  fmt            Auto-format Python source (black + isort)"
	@echo "  lint           Static analysis (flake8)"
	@echo "  test:fast      Fast smoke tests (not slow)"
	@echo "  contract       Generate protobuf stubs + proto lint"
	@echo "  quick-verify   10-min local minimal-stack smoke"
	@echo "  governance     Run all CI governance checks locally"
	@echo "  ─────────────────────────────────────────────────────"
	@echo "  audit-regen    Regenerate audit report + NODE_SYSTEM_AUDIT.md"
	@echo "  manifest-regen Regenerate NODE_ACTIVE_MANIFEST.md"
	@echo "  regen-all      Full governance doc refresh (audit + manifest)"
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

# ── Governance (mirrors the node-governance CI workflow) ──────────────────
.PHONY: governance
governance:
	@echo "→ [1/4] Canonical node audit (strict mode)..."
	$(PYTHON) scripts/node_audit.py --print-summary --strict
	@echo "→ [2/4] Repository hygiene check..."
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/check_repo_hygiene.py
	@echo "→ [3/4] Runtime structural validation..."
	$(PYTHON) scripts/validate_runtime.py
	@echo "→ [4/4] Governance unit tests..."
	$(PYTEST) tests/test_pr6_node_audit.py tests/test_pr8_optional_governance.py tests/test_repo_hygiene.py -v --tb=short
	@echo "✓ All governance checks passed."

# ── Governance document regeneration (PR-10) ─────────────────────────────

# Regenerate the structured audit report (JSON) and the human-readable
# Markdown summary.  Run after any change to nodes/ or node_dependencies.json.
.PHONY: audit-regen
audit-regen:
	@echo "→ Regenerating node audit report + NODE_SYSTEM_AUDIT.md..."
	$(PYTHON) scripts/node_audit.py --print-summary
	@echo "✓ Audit docs regenerated."

# Regenerate NODE_ACTIVE_MANIFEST.md from the canonical JSON sources.
# Requires docs/node_audit_report.json to be current; run audit-regen first
# if the audit data may be stale.
.PHONY: manifest-regen
manifest-regen:
	@echo "→ Regenerating NODE_ACTIVE_MANIFEST.md..."
	$(PYTHON) scripts/gen_node_active_manifest.py --print-summary
	@echo "✓ NODE_ACTIVE_MANIFEST.md regenerated."

# Full governance document refresh: regenerate audit outputs then rebuild
# NODE_ACTIVE_MANIFEST.md so all human-readable governance docs stay in sync
# with the canonical machine-readable sources.
#
# Run this before opening any PR that changes node_dependencies.json or
# any node directory:
#
#   make regen-all
#   git add docs/node_audit_report.json docs/NODE_SYSTEM_AUDIT.md docs/NODE_ACTIVE_MANIFEST.md
#   git commit -m "chore: regenerate governance docs"
.PHONY: regen-all
regen-all: audit-regen manifest-regen
	@echo "✓ All governance docs regenerated."
