#!/usr/bin/env bash
# stop.sh — Galaxy AI System Stop Script
# ======================================
# Stops all Galaxy processes.
#
# B16 修复了三处：
#
#   1. **PID 无归属校验**。旧代码是 `kill $(cat .backend.pid)` —— PID 文件可能
#      是上次运行留下的陈旧文件，而该 PID 早已被系统回收并分配给别的进程。
#      直接 kill 就是在杀一个无关进程（在开发机上大概率是别人的编辑器或构建）。
#      现在 kill 之前先核对该 PID 的命令行确实属于本仓库。
#
#   2. **`&&`/`||` 优先级 bug**。旧代码：
#          pkill -f A && ok "..." || pkill -f B && ok "..." || true
#      Shell 从左到右求值为 `(((A && ok) || B) && ok) || true`：第一条 pkill
#      成功时 ok 会**打印两次**，且第二条 pkill 的执行条件与直觉相反。
#      现在改成显式 if。
#
#   3. **无 Windows 对应物**。只有 start.bat 没有 stop.bat —— 见同目录 stop.bat。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }

# ---------------------------------------------------------------------------
# 读取某个 PID 的完整命令行（跨 Linux / macOS）
# ---------------------------------------------------------------------------
# Linux 上 /proc/<pid>/cmdline 用 NUL 分隔；macOS 没有 /proc，退回 ps。
_pid_cmdline() {
    local pid="$1"
    if [[ -r "/proc/${pid}/cmdline" ]]; then
        tr '\0' ' ' < "/proc/${pid}/cmdline"
    else
        ps -p "$pid" -o command= 2>/dev/null || true
    fi
}

# ---------------------------------------------------------------------------
# 按 PID 文件停止进程 —— 先验归属，再 kill
# ---------------------------------------------------------------------------
# $1 PID 文件名  $2 人类可读名  $3 命令行里必须出现的特征串
stop_by_pidfile() {
    local pidfile="$1" label="$2" needle="$3"
    [[ -f "$pidfile" ]] || return 0

    local pid
    pid="$(tr -dc '0-9' < "$pidfile")"
    if [[ -z "$pid" ]]; then
        warn "${label}: PID 文件内容不是数字，跳过并清理 ($pidfile)"
        rm -f "$pidfile"
        return 0
    fi

    if ! kill -0 "$pid" 2>/dev/null; then
        info "${label}: PID $pid 已不存在（陈旧 PID 文件），仅清理文件"
        rm -f "$pidfile"
        return 0
    fi

    # 归属校验：这个 PID 现在跑的确实是本仓库的东西吗？
    # 不校验的话，PID 复用会让我们杀掉一个完全无关的进程。
    local cmdline
    cmdline="$(_pid_cmdline "$pid")"
    if [[ "$cmdline" != *"$needle"* ]]; then
        warn "${label}: PID $pid 不属于本仓库（PID 已被复用），拒绝 kill"
        warn "         该进程命令行: ${cmdline:0:120}"
        rm -f "$pidfile"
        return 0
    fi

    if kill "$pid" 2>/dev/null; then
        ok "${label} stopped (pid $pid)"
    else
        warn "${label}: kill PID $pid 失败"
    fi
    rm -f "$pidfile"
}

info "Stopping Galaxy AI System..."

# 后端与 Electron 都以仓库绝对路径为归属特征 —— 同一台机器上跑着别的 Galaxy
# 克隆时，不会互相误杀。
stop_by_pidfile .backend.pid  "Backend"  "$SCRIPT_DIR"
stop_by_pidfile .frontend.pid "Electron" "$SCRIPT_DIR"

# ---------------------------------------------------------------------------
# 兜底：清掉 PID 文件没覆盖到的残留进程
# ---------------------------------------------------------------------------
# 后端实际进程是 `python main.py`（unified_launcher 在同进程内）——旧模式
# "python.*galaxy_gateway" 匹配不到任何东西，后端从来没被这里杀掉过。
# 用仓库路径限定，避免误杀别的项目的 main.py。
#
# 这里刻意写成显式 if 而不是 `A && ok || B && ok || true`：后者会被求值成
# (((A && ok) || B) && ok) || true，成功时重复打印、且 B 的执行条件反直觉。
if pkill -f "python.*${SCRIPT_DIR}/main\.py" 2>/dev/null; then
    ok "Backend process killed (by repo path)"
elif pkill -f "python.*main\.py --host" 2>/dev/null; then
    ok "Backend process killed (by --host signature)"
fi

# 历史模式，可能仍有旧进程残留；匹配不到是正常的，不打印。
pkill -f "python.*galaxy_gateway" 2>/dev/null || true

if pkill -f "electron.*galaxy" 2>/dev/null; then
    ok "Electron process killed"
fi

ok "All Galaxy processes stopped."
