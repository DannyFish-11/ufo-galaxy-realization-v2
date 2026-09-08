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


# ── 4. 崩溃日志入口:有且只有一个 ────────────────────────────────────────
#
# 所有者当初的要求是「崩溃日志单独弄一行」,那时那一行在托盘菜单里。后来托盘
# 菜单按所有者要求**整个清空**,于是那一行搬到了启动横幅上(见
# launcher/services.py 的 summary_card)。
#
# 守的东西没变,还是同样两件:
#   1. 崩溃日志**得有**一个入口 —— 没有的话出了事没人找得到那份聚合;
#   2. 入口**只能有一个** —— 分裂过一次(「三态动画日志」只覆盖 Electron 一份、
#      与 View Logs 指向两个不同根),那种状态下人会看错地方。
#
# 所以这里改成**跨托盘与横幅一起数**:两处加起来必须恰好一个。这比原先只数托盘
# 更严 —— 哪天有人把托盘那一行加回来而横幅那行还在,原先那条不会红,这条会。


def _code_only(path: "Path") -> str:
    """去掉注释与文档字符串之后的代码。

    **这一步不是讲究,是必需的。** 直接在文件文本里数 ``MenuItem(``,会把
    ``_build_menu`` 文档里那行「要把退出加回来,在这里补一行」的示例一起数进去 ——
    那测的是「文件里有没有提到这个名字」,而要测的是「还有没有代码在用它」。
    这个仓库为同一个坑栽过不止一次。
    """
    import ast

    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    spans: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = node.body[0] if node.body else None
            if (
                isinstance(doc, ast.Expr)
                and isinstance(doc.value, ast.Constant)
                and isinstance(doc.value.value, str)
                and doc.end_lineno is not None
            ):
                spans.append((doc.lineno, doc.end_lineno))
    drop = {n for a, b in spans for n in range(a, b + 1)}
    return "\n".join(ln for i, ln in enumerate(src.splitlines(), 1) if i not in drop and not ln.strip().startswith("#"))


def _crash_entries() -> list[str]:
    """全仓里「崩溃日志入口」的所有出处。托盘菜单项 + 横幅行,各算一个。"""
    root = Path(__file__).resolve().parent.parent
    found: list[str] = []

    tray = _code_only(root / "windows_service" / "tray_icon.py")
    found += [f"托盘菜单:{ln.strip()}" for ln in tray.splitlines() if "MenuItem(" in ln and "崩溃" in ln]

    launcher = (root / "launcher" / "services.py").read_text(encoding="utf-8")
    found += [f"就绪横幅:{ln.strip()}" for ln in launcher.splitlines() if '("崩溃"' in ln]

    return found


def test_there_is_exactly_one_crash_log_entry():
    """崩溃日志入口有且只有一个 —— 没有则没人找得到,多个则会看错地方。"""
    entries = _crash_entries()
    assert len(entries) == 1, f"崩溃日志入口应恰好一个,实际 {len(entries)}: {entries}"


def test_the_crash_entry_points_at_a_real_path_not_a_menu_that_is_gone():
    """入口必须指向**真实存在的东西**。

    托盘菜单清空之后,横幅一度还写着「托盘 →「💥 崩溃日志」」—— 指路指向一个不
    存在的菜单项,用户会在托盘上找半天然后以为是自己没找到。现在横幅给的是路径,
    而路径来自 core.log_paths(唯一事实来源),不在横幅里另拼一份。
    """
    from launcher.services import _crash_hint

    hint = _crash_hint()
    assert "托盘" not in hint, "崩溃入口又指回托盘了 —— 那个菜单是空的"
    assert hint.endswith(".log"), f"崩溃入口不像一个日志路径: {hint}"
    # 与 core.log_paths 现算的那条比,而不是跟一个写死的字符串比。
    from core.log_paths import crash_latest_path

    assert hint == str(crash_latest_path()), (
        f"崩溃入口与 core.log_paths 不一致 —— 又分裂出第二个根了。" f"横幅给的是 {hint},权威是 {crash_latest_path()}"
    )


def test_the_old_split_entry_is_still_gone():
    """旧的分裂入口(只覆盖 Electron 一份、与 View Logs 指向不同根)必须仍然不在。"""
    root = Path(__file__).resolve().parent.parent
    tray = (root / "windows_service" / "tray_icon.py").read_text(encoding="utf-8")
    assert "_open_overlay_log" not in tray.replace("# ", ""), "旧的三态动画日志入口又回来了"


#: 被清掉的那九项。所有者当初的要求是「全部删掉」,所以它们一个都不许回来。
#: 后来所有者要求「但凡需要日志的统一放进右下角的托盘里」,于是**只**多了「日志」
#: 这一项 —— 那是新的要求,不是这九项复活。
_REMOVED_NINE = (
    "唤醒覆盖层",
    "隐藏覆盖层",
    "配置面板",
    "崩溃日志",
    "查看日志",
    "远程桌面接管",
    "重启服务",
    "退出",
)


def _fake_tray():
    """用假 pystray 把托盘真建出来。

    这台机器没有 X11,真 pystray 一 import 就 ``Bad display name`` —— 所以要验
    菜单的形状只能替掉它。**验真建出来的菜单,而不是数源码里 MenuItem( 出现几次**:
    后者一改实现就红,而它想守的性质(菜单里到底有什么)其实没变。
    """
    import sys
    import types

    fake = types.ModuleType("pystray")

    class MenuItem:
        def __init__(self, text, action=None, default=False, visible=True):
            self.text, self.action = text, action
            self.default, self.visible = default, visible

    class Menu:
        SEPARATOR = "---"

        def __init__(self, *items):
            self.items = items

    fake.MenuItem, fake.Menu, fake.Icon = MenuItem, Menu, type("Icon", (), {})
    sys.modules.setdefault("pystray", fake)
    pil = sys.modules.setdefault("PIL", types.ModuleType("PIL"))
    for sub in ("Image", "ImageDraw", "ImageFilter", "ImageFont"):
        mod = sys.modules.setdefault(f"PIL.{sub}", types.ModuleType(f"PIL.{sub}"))
        setattr(pil, sub, mod)

    import windows_service.tray_icon as t

    t.pystray = fake
    t._HAVE_TRAY = True
    tray = t.GalaxyTray.__new__(t.GalaxyTray)
    tray._icon = None
    return t, tray


def test_the_tray_menu_holds_only_what_the_owner_asked_for():
    """托盘菜单里只有所有者要过的东西。

    先是「把之前那九项全部删掉,暂时先不放任何东西」;后来是「但凡需要日志的
    统一放进右下角的托盘里」。所以现在**恰好**是:一个承接单击的不可见默认项,
    加一个「日志」子菜单 —— 那九项一个都没回来。

    钉住它,是因为「菜单空着」与「菜单坏了」在外面看起来一模一样;
    而多出来一项没人要过的东西,和少了那个默认项一样是问题。
    """
    _t, tray = _fake_tray()
    menu = tray._build_menu()

    visible = [i for i in menu.items if getattr(i, "visible", True)]
    assert len(visible) == 1, f"可见的顶层项应只有「日志」,实际 {[i.text for i in visible]}"
    assert "日志" in visible[0].text

    hidden = [i for i in menu.items if not getattr(i, "visible", True)]
    assert len(hidden) == 1, "承接单击的不可见默认项必须有且只有一个"
    assert hidden[0].default is True, "没有默认项的话,点托盘不会触发任何回调 —— 就成了一张贴纸"


def test_the_removed_nine_did_not_come_back():
    """那九项一个都不许回来。「日志」是新要求,不是它们复活。"""
    root = Path(__file__).resolve().parent.parent
    tray = _code_only(root / "windows_service" / "tray_icon.py")
    back = [name for name in _REMOVED_NINE if name in tray]
    assert not back, f"被清掉的项又回来了: {back}"


def test_the_logs_entry_is_one_entry_not_two():
    """当初那两个日志入口的毛病是**指向不同的根**(见上面那条判据)。
    现在只有一个入口,而且由 core.log_locations 那张登记表驱动 —— 不许再分裂。
    """
    _t, tray = _fake_tray()
    menu = tray._build_menu()
    log_entries = [i for i in menu.items if getattr(i, "visible", True) and "日志" in i.text]
    assert len(log_entries) == 1, f"日志入口分裂成了 {len(log_entries)} 个"

    root = Path(__file__).resolve().parent.parent
    tray_src = _code_only(root / "windows_service" / "tray_icon.py")
    assert "existing_logs" in tray_src, "日志菜单没有走 core.log_locations 那张登记表"
