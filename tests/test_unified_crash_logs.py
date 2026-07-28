"""统一日志根 + 崩溃专区的契约回归测试。

锁住所有者要求的三件事:
1. 全仓日志只有**一个**根(不再是项目 logs/ 与 ~/.galaxy/logs 两处);
2. 崩溃日志汇到**一个**文件,托盘单独一行直接打开;
3. 重复崩溃被去重(同一崩溃跨来源只出现一次)、空/陈旧日志可被清理,
   且崩溃专区永不被清理误删。
"""

from __future__ import annotations

import importlib
import os
import time
from pathlib import Path

import pytest


@pytest.fixture()
def temp_log_root(tmp_path, monkeypatch):
    """把统一日志根指到临时目录,避免污染真实 logs/。"""
    monkeypatch.setenv("GALAXY_LOG_DIR", str(tmp_path))
    import core.log_paths as lp

    importlib.reload(lp)
    yield tmp_path
    monkeypatch.delenv("GALAXY_LOG_DIR", raising=False)
    importlib.reload(lp)


# ── 1. 单一日志根 ────────────────────────────────────────────────────────


def test_log_root_respects_env(temp_log_root):
    from core.log_paths import log_root

    assert log_root() == temp_log_root
    assert log_root().is_dir()


def test_crash_dir_under_log_root(temp_log_root):
    from core.log_paths import crash_dir, crash_latest_path

    assert crash_dir() == temp_log_root / "crashes"
    assert crash_latest_path().parent == crash_dir()
    assert crash_dir().is_dir()


def test_node_logs_land_under_unified_root(temp_log_root):
    """节点日志必须在统一根的 nodes/ 下 —— 修掉"裸文件名写进 CWD"的老问题。"""
    from core.log_paths import node_log_dir

    assert node_log_dir() == temp_log_root / "nodes"
    assert node_log_dir().is_dir()


def test_no_source_prefers_legacy_galaxy_logs():
    """生产代码不得再把 ~/.galaxy/logs 当作**首选**日志落点。

    该目录曾是第二个日志根,是"日志散在两处"的根因。统一后:
    - core/log_paths.legacy_log_roots 读它仅为迁移;
    - scripts/cleanup_logs.py 读它仅为搬运;
    - daemon/galaxy_daemon.py 把它降为**最后兜底**候选(统一根不可写的受限环境),
      统一根已排在候选首位,故允许其保留。
    除以上三处,任何模块都不应再出现该路径。
    """
    repo = Path(__file__).resolve().parent.parent
    allowed = {
        repo / "core" / "log_paths.py",
        repo / "scripts" / "cleanup_logs.py",
        repo / "tests" / "test_unified_crash_logs.py",
        repo / "daemon" / "galaxy_daemon.py",  # 仅作最后兜底,统一根优先
    }
    offenders: list[str] = []
    for path in list(repo.glob("*.py")) + [
        p
        for sub in ("core", "windows_service", "daemon", "launcher", "nodes")
        for p in (repo / sub).rglob("*.py")
        if (repo / sub).is_dir()
    ]:
        if path in allowed or "external" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("*"):
                continue  # 注释里解释历史沿革是允许的
            if '".galaxy"' in line and "logs" in line:
                offenders.append(f"{path.relative_to(repo)}: {stripped[:90]}")
    assert not offenders, "以下位置仍把 ~/.galaxy/logs 当日志落点:\n" + "\n".join(offenders)


# ── 2. 崩溃聚合 ──────────────────────────────────────────────────────────


def test_aggregator_detects_crash_patterns(temp_log_root):
    from core.crash_log_aggregator import aggregate_crashes

    (temp_log_root / "electron.log").write_text(
        "正常输出\nGPU process exited unexpectedly\n更多上下文\n", encoding="utf-8"
    )
    path, count = aggregate_crashes()
    assert count == 1
    body = path.read_text(encoding="utf-8")
    assert "GPU process exited" in body
    assert "electron.log" in body


def test_aggregator_dedupes_same_crash_across_sources(temp_log_root):
    """同一崩溃出现在多个日志里,聚合视图只保留一条并标注全部来源。"""
    from core.crash_log_aggregator import aggregate_crashes

    crash = "ERROR | 未处理的异常: Cannot call write() when UVStream is closing\n"
    (temp_log_root / "a.log").write_text("x\n" + crash, encoding="utf-8")
    (temp_log_root / "b.log").write_text("y\n" + crash, encoding="utf-8")

    path, count = aggregate_crashes()
    assert count == 1, "同一崩溃跨来源必须合并为一条"
    body = path.read_text(encoding="utf-8")
    assert "a.log" in body and "b.log" in body, "合并后仍应列出全部来源"


def test_aggregator_dedupes_across_timestamps(temp_log_root):
    """同一崩溃只是时间戳不同,不应算作两条(数字被归一化)。"""
    from core.crash_log_aggregator import aggregate_crashes

    (temp_log_root / "svc.log").write_text(
        "09:01:02 | FATAL | boom happened\n" "middle line\n" "10:20:30 | FATAL | boom happened\n",
        encoding="utf-8",
    )
    _, count = aggregate_crashes()
    assert count == 1


def test_aggregator_does_not_modify_sources(temp_log_root):
    """聚合器只读:源日志内容必须原样保留。"""
    from core.crash_log_aggregator import aggregate_crashes

    src = temp_log_root / "keep.log"
    original = "Traceback (most recent call last):\n  File 'x'\nValueError: v\n"
    src.write_text(original, encoding="utf-8")
    aggregate_crashes()
    assert src.read_text(encoding="utf-8") == original


def test_aggregator_reports_clean_when_no_crash(temp_log_root):
    from core.crash_log_aggregator import aggregate_crashes

    (temp_log_root / "quiet.log").write_text("一切正常\n启动完成\n", encoding="utf-8")
    path, count = aggregate_crashes()
    assert count == 0
    assert "未发现崩溃记录" in path.read_text(encoding="utf-8")


def test_aggregator_skips_its_own_output(temp_log_root):
    """崩溃专区自身不参与扫描,避免聚合结果被反复自我吞入。"""
    from core.crash_log_aggregator import aggregate_crashes

    (temp_log_root / "app.log").write_text("FATAL | 一次崩溃\n", encoding="utf-8")
    aggregate_crashes()
    _, second = aggregate_crashes()
    assert second == 1, "重复聚合不应把上一次的聚合结果算成新崩溃"


# ── 3. 清理 ──────────────────────────────────────────────────────────────


def test_cleanup_plan_targets_empty_and_stale_only(temp_log_root):
    from scripts.cleanup_logs import plan_cleanup

    old = time.time() - 60 * 86400
    (temp_log_root / "empty.log").write_text("", encoding="utf-8")
    stale = temp_log_root / "stale.log"
    stale.write_text("旧内容\n", encoding="utf-8")
    os.utime(stale, (old, old))
    fresh = temp_log_root / "fresh.log"
    fresh.write_text("新内容\n", encoding="utf-8")
    keep = temp_log_root / "notes.txt"
    keep.write_text("不是日志\n", encoding="utf-8")

    deletions, _ = plan_cleanup(days=30)
    targets = {p.name for p, _ in deletions}
    assert "empty.log" in targets
    assert "stale.log" in targets
    assert "fresh.log" not in targets, "当天日志可能正被写入,不能删"
    assert "notes.txt" not in targets, "非日志文件绝不能删"


def test_cleanup_never_touches_crash_area(temp_log_root):
    """崩溃专区是排障最后依据 —— 即便空/陈旧也不清理。"""
    from core.log_paths import crash_dir
    from scripts.cleanup_logs import plan_cleanup

    old = time.time() - 90 * 86400
    victim = crash_dir() / "latest.log"
    victim.write_text("", encoding="utf-8")
    os.utime(victim, (old, old))

    deletions, _ = plan_cleanup(days=30)
    assert all("crashes" not in str(p) for p, _ in deletions)


# ── 4. 托盘单行入口 ──────────────────────────────────────────────────────


def test_tray_has_single_crash_entry_and_no_split_log_entries():
    """托盘必须有独立的崩溃日志一行,且旧的分裂入口已移除。"""
    tray = (Path(__file__).resolve().parent.parent / "windows_service" / "tray_icon.py").read_text(encoding="utf-8")

    assert "self._open_crash_log" in tray, "缺少崩溃日志处理器"
    assert "崩溃日志 (Crash Log)" in tray, "托盘缺少崩溃日志单行入口"
    # 旧入口(只覆盖 Electron 一份、与 View Logs 指向不同根)必须已移除
    assert "_open_overlay_log" not in tray.replace("# ", ""), "旧的三态动画日志入口应已合并移除"


def test_tray_crash_entry_count_is_one():
    """崩溃入口只能有一行 —— 所有者明确要求"单独弄一行"。"""
    tray = (Path(__file__).resolve().parent.parent / "windows_service" / "tray_icon.py").read_text(encoding="utf-8")
    menu_lines = [ln for ln in tray.splitlines() if "MenuItem(" in ln and "崩溃日志" in ln]
    assert len(menu_lines) == 1, f"崩溃日志入口应恰好一行,实际 {len(menu_lines)}"
