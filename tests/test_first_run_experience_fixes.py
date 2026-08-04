"""新用户第一次跑起来会撞上的两个坑。

两个都是**真跑一次 `python main.py`** 才暴露的,静态看代码看不出来:

1. ``/proc/net/tcp6`` 不存在时刷 ERROR —— 内核关掉 IPv6(容器里很常见)时
   这个文件根本没有,而采样函数每 10 秒调一次,于是一条无害的配置差异会
   **永久刷屏**。实测容器里 3 分钟刷了 13 条 ERROR,真正的错误会被淹掉。

2. ``npm install`` 撞 ENOTEMPTY —— 上一次安装被打断后,``node_modules`` 里
   残留形如 ``.decompress-response-HCi3ZryO`` 的暂存目录;下一次 install 想
   重命名到**同一个**暂存名时目标已存在且非空,直接失败。要命的是
   **重跑 install 修不好它**,而启动器"依赖不完整就重装"的修复逻辑正是靠
   重跑 install,于是死循环、桌面覆盖层永远起不来。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.electron_launch_guard import (
    is_npm_stale_dir_error,
    purge_npm_staging_dirs,
)

REPO = Path(__file__).resolve().parent.parent


# ── 1. npm 残留暂存目录 ────────────────────────────────────────────────


def _make_node_modules(tmp_path: Path) -> Path:
    nm = tmp_path / "node_modules"
    nm.mkdir()
    return nm


def test_purges_npm_staging_leftovers(tmp_path):
    nm = _make_node_modules(tmp_path)
    stale = nm / ".decompress-response-HCi3ZryO"
    stale.mkdir()
    (stale / "index.js").write_text("x", encoding="utf-8")  # 非空才是真实残局

    assert purge_npm_staging_dirs(str(nm)) == 1
    assert not stale.exists()


def test_never_deletes_npm_own_dot_entries(tmp_path):
    """误删 .bin 会把整个安装弄坏 —— 宁可漏删一个残留,也不能碰它。"""
    nm = _make_node_modules(tmp_path)
    for keep in (".bin", ".cache"):
        (nm / keep).mkdir()

    assert purge_npm_staging_dirs(str(nm)) == 0
    assert (nm / ".bin").is_dir()
    assert (nm / ".cache").is_dir()


def test_never_deletes_real_packages(tmp_path):
    """真实包目录不以点开头,一个都不能动。"""
    nm = _make_node_modules(tmp_path)
    (nm / "decompress-response").mkdir()
    (nm / "electron").mkdir()

    assert purge_npm_staging_dirs(str(nm)) == 0
    assert (nm / "decompress-response").is_dir()
    assert (nm / "electron").is_dir()


def test_ignores_dotted_files_and_odd_names(tmp_path):
    """只删**目录**,且只删符合暂存命名形态的。"""
    nm = _make_node_modules(tmp_path)
    (nm / ".package-lock.json").write_text("{}", encoding="utf-8")
    (nm / ".hidden").mkdir()  # 不符合 .<名>-<随机后缀> 形态

    assert purge_npm_staging_dirs(str(nm)) == 0
    assert (nm / ".hidden").is_dir()


def test_missing_node_modules_is_not_an_error(tmp_path):
    assert purge_npm_staging_dirs(str(tmp_path / "nope")) == 0


@pytest.mark.parametrize(
    "output",
    [
        "npm error ENOTEMPTY: directory not empty, rename '.../decompress-response'",
        "npm ERR! EEXIST: file already exists",
        "directory not empty",
    ],
)
def test_recognises_stale_dir_failures(output):
    assert is_npm_stale_dir_error(output) is True


@pytest.mark.parametrize(
    "output",
    ["", "npm error ETIMEDOUT request to https://registry.npmjs.org failed", "npm ERR! 404 Not Found"],
)
def test_does_not_mistake_network_failures_for_stale_dirs(output):
    """网络类失败要换镜像重试,残留目录类要清目录 —— 判错了修法就不对。"""
    assert is_npm_stale_dir_error(output) is False


def test_launcher_purges_before_reinstalling():
    """光有 helper 不够,启动器的修复路径必须真的调它。

    **检查对象搬家了**：自愈链从 ``unified_launcher.start_electron()`` 的内联段
    收敛到了 ``launcher/shell.py``（判据一条没改，改的是组织方式）。所以这里跟着
    指向新家。

    顺带把断言从"源码里出现这个名字"升级为"**运行时真的按顺序调了**"：清残留
    必须在任何 npm install 之前，顺序一换死循环就回来。子串断言钉不住顺序 ——
    tests/test_launcher_shell.py::test_staging_purge_happens_before_any_install
    记录真实调用序列来钉，这里只保留"确实用了这两个 helper"这层。
    """
    src = (REPO / "launcher" / "shell.py").read_text(encoding="utf-8")

    assert "purge_npm_staging_dirs" in src, "修复安装前未清残留,ENOTEMPTY 会一直撞"
    assert "is_npm_stale_dir_error" in src, "未识别残留目录类失败,会误当网络问题换镜像"


def test_launcher_escalates_to_full_rebuild_when_still_blocked():
    """清了还挡路(嵌套 node_modules / 本轮又被打断)时,要能整体重建 ——
    node_modules 完全可由 package.json 重建,删掉无损。

    同上：检查对象已搬到 ``launcher/shell.py`` 的第 5 级。
    """
    src = (REPO / "launcher" / "shell.py").read_text(encoding="utf-8")

    assert "重建 node_modules" in src


# ── 2. /proc 网络统计的 ERROR 刷屏 ──────────────────────────────────────


def test_missing_ipv6_is_not_logged_as_error():
    """内核关掉 IPv6 是**正常配置**,不是错误。

    原实现把 tcp6 的读放在同一个 try 里,一缺就跳去 except 打 ERROR;
    而这个函数每 10 秒被调一次 —— 无害的配置差异变成永久刷屏。
    """
    # 用 AST 断**结构**,不靠字符串位置 —— 后者一改缩进/注释就假红或假绿。
    import ast

    tree = ast.parse((REPO / "core" / "system_load_monitor.py").read_text(encoding="utf-8"))
    func = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_get_network_from_proc")

    guarded = [
        t
        for t in ast.walk(func)
        if isinstance(t, ast.Try)
        and "/proc/net/tcp6" in ast.unparse(ast.Module(body=t.body, type_ignores=[]))
        and any(isinstance(h.type, ast.Name) and h.type.id == "FileNotFoundError" for h in t.handlers)
    ]

    assert guarded, (
        "读 /proc/net/tcp6 必须包在自己的 try/except FileNotFoundError 里 —— "
        "内核关掉 IPv6 是正常配置,不该触发外层 ERROR 并每 10 秒刷屏"
    )


def test_persistent_proc_failure_warns_once_then_debugs():
    """真意外的失败仍要报,但不能每 10 秒报一次把日志刷爆。"""
    src = (REPO / "core" / "system_load_monitor.py").read_text(encoding="utf-8")

    assert "_proc_net_warned" in src, "缺少告警去重标志,持续性故障会刷屏"
    assert "logger.debug" in src, "去重后应降级为 DEBUG 而不是完全静默"


def test_monitor_initialises_the_dedup_flag():
    """标志没在 __init__ 里初始化的话,第一次进 except 会 AttributeError ——
    把一个日志问题升级成崩溃。"""
    from core.system_load_monitor import SystemLoadMonitor

    assert SystemLoadMonitor()._proc_net_warned is False


def test_ipv4_count_survives_missing_ipv6(tmp_path, monkeypatch):
    """IPv6 缺失不该把 IPv4 的连接数一起丢掉。"""
    from core.system_load_monitor import SystemLoadMonitor

    real_open = open

    def fake_open(path, *a, **kw):
        if str(path) == "/proc/net/tcp6":
            raise FileNotFoundError(path)
        if str(path) == "/proc/net/tcp":
            import io

            return io.StringIO("header\nconn1\nconn2\n")
        if str(path) == "/proc/net/dev":
            import io

            return io.StringIO("h1\nh2\n")
        return real_open(path, *a, **kw)

    monkeypatch.setattr("builtins.open", fake_open)
    stats = SystemLoadMonitor()._get_network_from_proc()

    assert stats.connections_count == 2, "IPv4 的 2 条连接应照常统计"
