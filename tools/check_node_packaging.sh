#!/usr/bin/env bash
# tools/check_node_packaging.sh
#
# Diagnostic script: identify nodes that are missing a Dockerfile and/or
# requirements.txt.  Run from the repository root:
#
#   bash tools/check_node_packaging.sh
#
# Exit codes:
#   0  — all nodes have both Dockerfile and requirements.txt
#   1  — one or more nodes are missing at least one file
#
# Output sections
# ---------------
#   MISSING DOCKERFILE    — nodes that cannot be containerised independently
#   MISSING requirements.txt — nodes without declared Python dependencies
#   SUMMARY               — counts and suggested next steps
#
# How to add the missing files for a node
# ----------------------------------------
# 1. requirements.txt:
#      echo "# Add your node dependencies here" > nodes/<NodeDir>/requirements.txt
#
# 2. Dockerfile (minimal template — adjust base image as needed):
#
#    FROM python:3.11-slim
#    WORKDIR /app
#    COPY requirements.txt .
#    RUN pip install --no-cache-dir -r requirements.txt
#    COPY . .
#    CMD ["python", "main.py"]
#
# See existing nodes (e.g. nodes/Node_10_Slack/) for working examples.

set -euo pipefail

NODES_DIR="${1:-nodes}"

if [ ! -d "$NODES_DIR" ]; then
    echo "ERROR: nodes directory not found at '$NODES_DIR'." >&2
    echo "Run this script from the repository root." >&2
    exit 1
fi

missing_dockerfile=()
missing_requirements=()

for node_dir in "$NODES_DIR"/*/; do
    node_name=$(basename "$node_dir")
    # Skip the shared 'common' directory — it is not a deployable node.
    [ "$node_name" = "common" ] && continue

    [ -f "$node_dir/Dockerfile" ]       || missing_dockerfile+=("$node_name")
    [ -f "$node_dir/requirements.txt" ] || missing_requirements+=("$node_name")
done

total=$(find "$NODES_DIR" -maxdepth 1 -mindepth 1 -type d ! -name "common" | wc -l)
has_dockerfile=$(( total - ${#missing_dockerfile[@]} ))
has_requirements=$(( total - ${#missing_requirements[@]} ))

print_list() {
    local label="$1"; shift
    local items=("$@")
    if [ ${#items[@]} -eq 0 ]; then
        echo "  (none — all nodes have $label)"
    else
        for item in "${items[@]}"; do
            echo "  $item"
        done
    fi
}

echo "================================================================"
echo " Node Packaging Coverage Report"
echo " Generated: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "================================================================"
echo ""
echo "MISSING Dockerfile (${#missing_dockerfile[@]} nodes):"
print_list "Dockerfile" "${missing_dockerfile[@]+"${missing_dockerfile[@]}"}"
echo ""
echo "MISSING requirements.txt (${#missing_requirements[@]} nodes):"
print_list "requirements.txt" "${missing_requirements[@]+"${missing_requirements[@]}"}"
echo ""
echo "----------------------------------------------------------------"
echo " SUMMARY"
echo "----------------------------------------------------------------"
printf "  Total nodes          : %d\n" "$total"
printf "  With Dockerfile      : %d  (%d%%)\n" \
    "$has_dockerfile" "$(( has_dockerfile * 100 / total ))"
printf "  With requirements.txt: %d  (%d%%)\n" \
    "$has_requirements" "$(( has_requirements * 100 / total ))"
echo ""
echo " Next steps:"
echo "  1. Add requirements.txt to nodes that have Python dependencies."
echo "  2. Add a Dockerfile to nodes intended for independent deployment."
echo "  3. Use the template in the script header as a starting point."
echo "  4. Prioritise nodes with complex dependencies first:"
echo "     Node_101_CodeEngine, Node_90_MultimodalVision, Node_79_LocalLLM,"
echo "     Node_103_KnowledgeGraph"
echo "  5. Consider adding a CI check to enforce coverage on new node PRs."
echo ""

if [ ${#missing_dockerfile[@]} -gt 0 ] || [ ${#missing_requirements[@]} -gt 0 ]; then
    exit 1
fi
exit 0
