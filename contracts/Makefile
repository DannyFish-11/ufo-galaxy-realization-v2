# ============================================================================
# Galaxy Agentic OS — Protobuf Build Tooling
# ============================================================================
#
# Usage:
#   make proto-python   — Generate Python stubs in contracts/gen/python/
#   make proto-go       — Generate Go stubs in contracts/gen/go/
#   make proto-all      — Generate all languages
#   make clean          — Remove generated code
#
# Prerequisites:
#   - protoc (protobuf compiler) >= 3.21
#   - For Python: grpcio-tools (pip install grpcio-tools)
#   - For Go:     protoc-gen-go (go install google.golang.org/protobuf/cmd/protoc-gen-go@latest)
# ============================================================================

PROTO_DIR   := proto
GEN_DIR     := gen
PROTO_FILES := $(shell find $(PROTO_DIR) -name '*.proto')

PYTHON_OUT := $(GEN_DIR)/python
GO_OUT     := $(GEN_DIR)/go

.PHONY: proto-all proto-python proto-go clean lint

proto-all: proto-python proto-go

# ── Python generation ──────────────────────────────────────────────────────

proto-python: $(PROTO_FILES)
	@mkdir -p $(PYTHON_OUT)
	@echo "→ Generating Python protobuf stubs..."
	python -m grpc_tools.protoc \
		--proto_path=$(PROTO_DIR) \
		--python_out=$(PYTHON_OUT) \
		--pyi_out=$(PYTHON_OUT) \
		$(PROTO_FILES)
	@# Create __init__.py files for Python package structure
	@find $(PYTHON_OUT) -type d -exec touch {}/__init__.py \;
	@echo "✓ Python stubs generated in $(PYTHON_OUT)/"

# ── Go generation ──────────────────────────────────────────────────────────

proto-go: $(PROTO_FILES)
	@mkdir -p $(GO_OUT)
	@echo "→ Generating Go protobuf stubs..."
	protoc \
		--proto_path=$(PROTO_DIR) \
		--go_out=$(GO_OUT) \
		--go_opt=paths=source_relative \
		$(PROTO_FILES)
	@echo "✓ Go stubs generated in $(GO_OUT)/"

# ── Lint ───────────────────────────────────────────────────────────────────

lint:
	@echo "→ Linting proto files..."
	@which buf > /dev/null 2>&1 && buf lint $(PROTO_DIR) || echo "⚠ buf not installed, skipping lint"

# ── Clean ──────────────────────────────────────────────────────────────────

clean:
	@echo "→ Cleaning generated code..."
	rm -rf $(GEN_DIR)
	@echo "✓ Clean complete"
