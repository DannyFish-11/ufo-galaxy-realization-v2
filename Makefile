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
#   preflight      — run the blocking CI gates locally (mirrors ci.yml + guardrails.yml)
#   governance     — run all CI governance checks locally (mirrors node-governance.yml)
#   audit-regen    — regenerate docs/node_audit_report.json + docs/NODE_SYSTEM_AUDIT.md
#   manifest-regen — regenerate docs/NODE_ACTIVE_MANIFEST.md from canonical sources
#   regen-all      — run audit-regen then manifest-regen (full governance doc refresh)
#   deploy-up      — deploy production stack (deploy/compose/production.yml)
#   deploy-full    — bring up full-system stack (deploy/compose/full.yml)
#   deploy-down    — stop production stack
#   help           — show this help
#
# Usage:
#   make fmt
#   make lint
#   make test:fast
#   make contract
#   make quick-verify
#   make preflight
#   make governance
#   make audit-regen
#   make manifest-regen
#   make regen-all
#   make deploy-up
#   make deploy-full
#   make deploy-down
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

# Deployment compose files (under deploy/)
COMPOSE_PROD  = deploy/compose/production.yml
COMPOSE_FULL  = deploy/compose/full.yml
COMPOSE_DEV   = docker-compose.yml

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
	@echo "  preflight      Run the blocking CI gates locally (推送前跑这个)"
	@echo "  governance     Run all CI governance checks locally"
	@echo "  ─────────────────────────────────────────────────────"
	@echo "  audit-regen    Regenerate audit report + NODE_SYSTEM_AUDIT.md"
	@echo "  manifest-regen Regenerate NODE_ACTIVE_MANIFEST.md"
	@echo "  regen-all      Full governance doc refresh (audit + manifest)"
	@echo "  ─────────────────────────────────────────────────────"
	@echo "  deploy-up      Deploy production stack (deploy/compose/production.yml)"
	@echo "  deploy-full    Bring up full-system stack (deploy/compose/full.yml)"
	@echo "  deploy-down    Stop production stack"
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

# ── Preflight (mirrors the blocking gates in ci.yml + guardrails.yml) ─────
#
# 为什么要有这个目标
# ------------------
# `make governance` 早就证明了这个模式管用 —— 它的注释写着 "mirrors the
# node-governance CI workflow"，并且**照抄了 CI 的参数**（`--strict`）。
# 缺的只是 ci.yml / guardrails.yml 那两组门的对应物。
#
# 缺的代价是实测出来的：一次改动连着三条 CI 红，三条全部是"本地跑法和 CI 不一样"：
#
#   1. `check_file_complexity.py` 不加 `--strict` 返回 0 —— 本地看着过了，CI 用
#      `--strict`，三个文件越过基线；
#   2. `check_completion_matrix.py` 同样漏了 `--strict`；
#   3. 改了 panel/src 没重建 dist/ —— 这个门本地**根本没跑过**。
#
# 所以这里的规矩是：**参数必须与 CI 逐字一致**。少一个 `--strict`，这个目标就
# 退化成"看着像跑过了"，比不跑更糟。改 CI 的时候请同步改这里。
#
# 不含四分片全量（那要十几分钟，见 `make test:fast` / scripts/ci_test_shard.py）。
.PHONY: preflight
preflight:
	@echo "→ [1/4] 格式与静态检查（范围与 ci.yml 的 lint 作业一致）..."
	$(PYTHON) -m flake8 core/ galaxy_gateway/ --max-line-length=120 --count --statistics
	$(PYTHON) -m black --check core/ tests/ galaxy_gateway/
	$(PYTHON) -m isort --check-only core/ tests/ galaxy_gateway/
	@echo "→ [2/4] guardrails 门（**参数与 CI 逐字一致**）..."
	$(PYTHON) scripts/check_file_complexity.py --strict
	$(PYTHON) scripts/check_completion_matrix.py --strict
	$(PYTHON) scripts/check_wiring.py
	$(PYTHON) scripts/check_reachability.py
	$(PYTHON) scripts/check_import_boundaries.py
	$(PYTHON) scripts/check_evidence_anchors.py
	$(PYTHON) scripts/check_debt_freeze.py
	$(PYTHON) scripts/check_legacy_regression.py --warn-only
	$(PYTHON) scripts/check_mainline_routing_enforcement.py
	$(PYTHON) scripts/check_repo_hygiene.py
	$(PYTHON) scripts/validate_ports.py
	@echo "→ [3/4] 面板构建产物与源码一致（panel-dist-consistency）..."
	@bash scripts/check_panel_dist.sh
	@echo "→ [4/4] 本次改动涉及的测试文件..."
	@echo "   （跳过：全量请跑 scripts/ci_test_shard.py --shard N --of 4）"
	@echo "✓ preflight 全过 —— 与 CI 的阻塞门同口径。"

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

# ── Deployment targets ────────────────────────────────────────────────────
# These targets wrap the deploy/ compose files for convenience.
# The root docker-compose.yml remains the canonical development surface.

# Deploy production stack
.PHONY: deploy-up
deploy-up:
	@echo "→ Deploying production stack ($(COMPOSE_PROD))..."
	docker compose -f $(COMPOSE_PROD) up -d
	@echo "✓ Production stack started."

# Bring up full-system stack (all 130 nodes)
.PHONY: deploy-full
deploy-full:
	@echo "→ Deploying full-system stack ($(COMPOSE_FULL))..."
	docker compose -f $(COMPOSE_FULL) --profile full up -d
	@echo "✓ Full-system stack started."

# Stop production stack
.PHONY: deploy-down
deploy-down:
	@echo "→ Stopping production stack ($(COMPOSE_PROD))..."
	docker compose -f $(COMPOSE_PROD) down
	@echo "✓ Production stack stopped."
