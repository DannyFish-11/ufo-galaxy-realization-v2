#!/usr/bin/env bash
# =============================================================================
# scripts/pin_deps.sh — Regenerate hash-locked Python requirements
# =============================================================================
#
# Usage:
#   scripts/pin_deps.sh             # regenerate requirements.hash.txt
#   scripts/pin_deps.sh --verify    # verify existing file is current
#   scripts/pin_deps.sh --help      # show this help
#
# Requirements:
#   pip install pip-tools
#
# The output file (requirements.hash.txt) is committed to the repository
# and used in CI for hash-verified installation:
#   pip install --require-hashes -r requirements.hash.txt
#
# What this covers:
#   Core framework, network, and security packages in requirements.in.
#   Full production dependencies (requirements.txt) are installed without
#   hash-checking for non-security-critical optional packages (e.g. GUI,
#   device-control, ML/media) to preserve platform flexibility.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

REQUIREMENTS_IN="${REPO_ROOT}/requirements.in"
HASH_OUT="${REPO_ROOT}/requirements.hash.txt"
VERIFY_MODE=false

for arg in "$@"; do
    case "$arg" in
        --verify)   VERIFY_MODE=true ;;
        --help|-h)
            sed -n '/^# Usage/,/^# ====/p' "$0" | grep '^#' | sed 's/^# \?//'
            exit 0
            ;;
        *)
            echo "Unknown argument: $arg" >&2
            exit 1
            ;;
    esac
done

# Ensure pip-tools is installed
if ! command -v pip-compile &>/dev/null; then
    echo "pip-tools not found. Installing..." >&2
    pip install --quiet pip-tools
fi

if [ "$VERIFY_MODE" = true ]; then
    # Generate to a temp file and compare
    TMP_OUT="$(mktemp /tmp/requirements.hash.XXXXXX.txt)"
    trap "rm -f '${TMP_OUT}'" EXIT
    echo "Verifying ${HASH_OUT} is up-to-date..."
    pip-compile \
        --generate-hashes \
        --quiet \
        --output-file="${TMP_OUT}" \
        "${REQUIREMENTS_IN}"
    if diff -q "${HASH_OUT}" "${TMP_OUT}" >/dev/null 2>&1; then
        echo "✅  requirements.hash.txt is up-to-date."
    else
        echo "❌  requirements.hash.txt is out-of-date. Run: scripts/pin_deps.sh"
        diff "${HASH_OUT}" "${TMP_OUT}" || true
        exit 1
    fi
else
    echo "Regenerating ${HASH_OUT} from ${REQUIREMENTS_IN} ..."
    pip-compile \
        --generate-hashes \
        --output-file="${HASH_OUT}" \
        "${REQUIREMENTS_IN}"
    echo "✅  requirements.hash.txt updated."
    echo "    Commit the updated file to enforce hashes in CI."
fi
