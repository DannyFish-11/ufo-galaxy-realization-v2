#!/usr/bin/env bash
# scripts/bootstrap.sh — Galaxy 一键初始化 (Linux/macOS 包装器)
# 实际逻辑在跨平台的 scripts/bootstrap.py 中，这里仅转发参数。
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$(command -v python3 || command -v python)"
if [ -z "${PY}" ]; then
  echo "[ERR] 未找到 python3/python，请先安装 Python 3.10+" >&2
  exit 1
fi
exec "${PY}" "${HERE}/bootstrap.py" "$@"
