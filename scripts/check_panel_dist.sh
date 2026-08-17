#!/usr/bin/env bash
# =============================================================================
# scripts/check_panel_dist.sh — dist/ 必须与 panel/src 一致（本地版）
# =============================================================================
#
# 镜像 ci.yml 的 panel-dist-consistency 作业。Electron 生产环境**直接加载 dist/**，
# 改了源码不重建的话用户看到的是旧界面 —— 加进面板的新配置项根本不会出现。
#
# 为什么本地要单独写一个脚本，而不是照抄 CI 那三行
# ------------------------------------------------
# CI 是全新 checkout，仓库里只有 panel/node_modules（npm ci 装的）。开发机上不是：
# `electron/node_modules/@types/` 这个**父目录**里常年躺着一批残缺的类型包
# (node / keyv / yauzl / responselike / http-cache-semantics)，而 tsc 会**向上
# walk 目录树**去找 @types。结果是一串 TS2688 "Cannot find type definition file"，
# 看起来像仓库坏了，实际只是本地环境的遗留物 —— CI 上永远不会出现。
#
# 实测踩过一次：以为是构建坏了，去查 tsconfig，其实把那个目录挪开就好了。
# 所以这里显式把它临时移开、构建完再放回去，并且**无论成败都放回**（trap）。
set -euo pipefail

PANEL_DIR="electron/renderer/panel"
STRAY_MODULES="electron/node_modules"
STASHED=""

cleanup() {
    if [ -n "$STASHED" ] && [ -d "$STASHED" ]; then
        mv "$STASHED" "$STRAY_MODULES"
    fi
}
trap cleanup EXIT

if [ ! -d "$PANEL_DIR" ]; then
    echo "  跳过：找不到 $PANEL_DIR"
    exit 0
fi

if ! command -v npm >/dev/null 2>&1; then
    echo "  ⚠ 跳过：本机没有 npm —— 这一门在 CI 上仍会跑，本地过不等于 CI 过"
    exit 0
fi

# 父目录里的残缺 @types 会毒化 tsc 的类型解析（见文件头）。临时挪开。
if [ -d "$STRAY_MODULES/@types" ]; then
    STASHED="$(mktemp -d)/electron_node_modules"
    mkdir -p "$(dirname "$STASHED")"
    mv "$STRAY_MODULES" "$STASHED"
fi

(
    cd "$PANEL_DIR"
    npm ci --no-audit --no-fund >/dev/null 2>&1
    npm run build >/dev/null 2>&1
)

# 判据与 CI 逐字一致：构建完 dist/ 不该有任何 diff。
if ! git diff --exit-code -- "$PANEL_DIR/dist/" >/dev/null 2>&1; then
    echo "  ✗ panel/dist 与 panel/src 不一致 —— 改了源码但没重建构建产物。"
    echo "    Electron 生产环境直接加载 dist/，不重建的话用户看到的是旧界面。"
    echo "    修法: cd $PANEL_DIR && npm ci && npm run build，然后提交 dist/ 的改动。"
    git --no-pager diff --stat -- "$PANEL_DIR/dist/"
    exit 1
fi

echo "  ✓ dist/ 与源码一致"
