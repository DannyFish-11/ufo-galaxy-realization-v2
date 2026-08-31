"""``core/safe_fs`` —— 校验过的东西和用到的东西必须是同一个。

本模块守的是一个**实测复现过的**逃逸,不是假想的。复现方式见
``core/safe_fs`` 的 docstring:一个线程把工作区内的 ``f.txt`` 在"普通文件"与
"指向工作区外的符号链接"之间原子替换,另一个线程走"纯路径校验 → 打开"的流程,
42953 次通过校验里有 576 次读到了工作区外的内容。

三组断言缺一不可:

* **等价** —— 静态树上,守卫读到/写到的东西与 ``pathlib`` 逐字相同;
* **拒穿越** —— ``..``、绝对路径、指向外部的符号链接都要挡住;
* **抗竞态** —— 上面那个替换线程跑着的时候,一次都不许读到工作区外。

只有第三组会退化成"写个永远抛异常的函数也能过",所以前两组是它的配重。
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

from core.safe_fs import (
    MAX_SYMLINK_HOPS,
    PathEscapesWorkspace,
    SymlinkNotFollowed,
    WorkspaceGuard,
    dir_fd_supported,
)

pytestmark = pytest.mark.skipif(not dir_fd_supported(), reason="本平台不支持 dir_fd(如 Windows)")


@pytest.fixture()
def ws(tmp_path):
    root = tmp_path / "ws"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "a.txt").write_text("inside-a", encoding="utf-8")
    (root / "top.txt").write_text("inside-top", encoding="utf-8")
    return root


@pytest.fixture()
def outside(tmp_path):
    out = tmp_path / "outside"
    out.mkdir()
    (out / "secret.txt").write_text("TOP-SECRET-OUTSIDE", encoding="utf-8")
    return out


@pytest.fixture()
def guard(ws):
    with WorkspaceGuard(ws) as g:
        yield g


# ── 等价性 ────────────────────────────────────────────────────────────────


def test_read_matches_pathlib(guard, ws):
    assert guard.read_text("sub/a.txt") == (ws / "sub" / "a.txt").read_text(encoding="utf-8")
    assert guard.read_bytes("top.txt") == (ws / "top.txt").read_bytes()


def test_write_then_read_round_trips(guard, ws):
    guard.write_text("sub/new.txt", "写进去的")
    assert (ws / "sub" / "new.txt").read_text(encoding="utf-8") == "写进去的"
    assert guard.read_text("sub/new.txt") == "写进去的"


def test_append_extends(guard, ws):
    guard.append_text("top.txt", "-more")
    assert (ws / "top.txt").read_text(encoding="utf-8") == "inside-top-more"


def test_write_without_overwrite_is_atomic_refusal(guard):
    """``overwrite=False`` 走 ``O_EXCL``,由内核判"存在就失败"。

    比"先 exists() 再写"少一个窗口 —— 那两步之间同样能被人插进来。
    """
    with pytest.raises(FileExistsError):
        guard.write_text("top.txt", "x", overwrite=False)


def test_listdir_matches_os_listdir(guard, ws):
    assert sorted(guard.listdir("")) == sorted(os.listdir(ws))
    assert sorted(guard.listdir("sub")) == sorted(os.listdir(ws / "sub"))


def test_stat_size_matches(guard, ws):
    assert guard.stat("top.txt").st_size == (ws / "top.txt").stat().st_size


def test_absolute_path_inside_workspace_is_accepted(guard, ws):
    """旧实现允许工作区**内**的绝对路径,这条不许回退。

    注意"工作区内"是字面意义上的:旧代码 ``os.path.join(root, path)`` 在 path 为
    绝对路径时直接取 path,所以 ``/sub/a.txt`` 指的是**文件系统根**下的 sub,
    旧代码同样会拒。下一条守的就是这个区别 —— 别把绝对路径当成"相对工作区"。
    """
    assert guard.read_text(str(ws / "sub" / "a.txt")) == "inside-a"


def test_absolute_path_outside_workspace_is_refused(guard):
    with pytest.raises(PathEscapesWorkspace):
        guard.read_text("/etc/passwd")


def test_absolute_path_is_not_silently_reinterpreted_as_root_relative(guard, ws):
    """``/sub/a.txt`` 必须被拒,不许被悄悄理解成 ``<工作区>/sub/a.txt``。

    工作区里恰好**有**一个 ``sub/a.txt``,所以一旦实现把绝对路径当相对根处理,
    这里就会读成功 —— 那是把"越界"变成"命中",比读不到危险得多。
    """
    assert (ws / "sub" / "a.txt").exists(), "前提:同名文件在工作区内确实存在"
    with pytest.raises(PathEscapesWorkspace):
        guard.read_text("/sub/a.txt")


# ── 目录操作 ──────────────────────────────────────────────────────────────


def test_mkdir_parents_and_rmtree(guard, ws):
    guard.mkdir("x/y/z", parents=True)
    assert (ws / "x" / "y" / "z").is_dir()
    guard.write_text("x/y/z/f.txt", "hi")
    guard.rmtree("x")
    assert not (ws / "x").exists()


def test_rmdir_refuses_non_empty(guard):
    with pytest.raises(OSError):
        guard.rmdir("sub")


def test_rename_moves_within_workspace(guard, ws):
    guard.rename("top.txt", "sub/moved.txt")
    assert not (ws / "top.txt").exists()
    assert (ws / "sub" / "moved.txt").read_text(encoding="utf-8") == "inside-top"


def test_unlink_removes_the_name_not_the_target(guard, ws, outside):
    """删符号链接删的是链接本身 —— 和 ``rm`` 一致,别把人家目标文件删了。"""
    os.symlink(outside / "secret.txt", ws / "link")
    guard.unlink("link")
    assert not (ws / "link").is_symlink()
    assert (outside / "secret.txt").exists(), "只该删掉链接,不该动它指向的东西"


def test_root_itself_cannot_be_opened_as_a_file(guard):
    with pytest.raises(PathEscapesWorkspace):
        guard.read_text("")


# ── display_path:交出去的字符串同样不许指到工作区外 ──────────────────────


def test_display_path_refuses_to_hand_out_a_path_outside_the_workspace(guard):
    """``display_path`` 曾经是纯拼接,``"../../etc/passwd"`` 会原样返回
    ``<工作区>/../../etc/passwd``。

    当时不可利用 —— 唯一的调用方 ``Node_120._copy_tree`` 上游已经拦过一道。但那是
    靠调用方兜着,不是靠这个函数自己站得住;而它交出去的路径正是喂给
    ``shutil.copytree`` 的那个。CodeQL 的 ``py/path-injection`` 顺着这条流报到了
    ``copytree``,报得对。
    """
    with pytest.raises(PathEscapesWorkspace):
        guard.display_path("../../etc/passwd")


def test_display_path_returns_the_real_location_for_an_inside_path(guard, ws):
    assert guard.display_path("sub/a.txt") == (ws / "sub" / "a.txt").resolve()
    assert guard.display_path("") == ws.resolve()


def test_open_reports_a_name_inside_the_workspace(guard, ws):
    """文件对象的 ``.name`` 会进日志和异常消息 —— 它也该是个工作区内的路径。"""
    with guard.open("sub/a.txt") as handle:
        assert handle.name == str((ws / "sub" / "a.txt").resolve())


# ── 拒穿越 ────────────────────────────────────────────────────────────────


def test_dotdot_cannot_climb_above_root(guard):
    with pytest.raises(PathEscapesWorkspace):
        guard.read_text("../outside/secret.txt")


def test_dotdot_inside_is_fine(guard):
    """``sub/../top.txt`` 全程没出过工作区,不该被误杀。"""
    assert guard.read_text("sub/../top.txt") == "inside-top"


def test_dotdot_that_dips_out_and_back_is_still_refused(guard):
    """``../ws/top.txt`` 最终落点在工作区内,但**路上**爬到了根之上。

    内核的 ``RESOLVE_BENEATH`` 也是这么判的 —— 只看落点会给"先出去绕一圈"留门。
    """
    with pytest.raises(PathEscapesWorkspace):
        guard.read_text("../ws/top.txt")


def test_absolute_symlink_out_is_refused(guard, ws, outside):
    os.symlink(outside, ws / "escape")
    with pytest.raises(SymlinkNotFollowed):
        guard.read_text("escape/secret.txt", follow_final=True)


def test_relative_symlink_climbing_out_is_refused(guard, ws, outside):
    """相对目标也能爬出去 —— ``..`` 要在我们自己的 fd 栈上判,不能下发给内核。"""
    os.symlink(os.path.relpath(outside, ws), ws / "rel_escape")
    with pytest.raises(PathEscapesWorkspace):
        guard.read_text("rel_escape/secret.txt", follow_final=True)


def test_final_symlink_is_refused_by_default(guard, ws, outside):
    os.symlink(outside / "secret.txt", ws / "f.txt")
    with pytest.raises(SymlinkNotFollowed):
        guard.read_text("f.txt")


def test_inside_relative_symlink_is_followed_when_asked(guard, ws):
    """工作区内的相对符号链接是合法的,开了 ``follow_final`` 就得跟。

    没有这条,"堵死一切"就能冒充"堵住了逃逸"。
    """
    os.symlink("sub/a.txt", ws / "alias")
    assert guard.read_text("alias", follow_final=True) == "inside-a"


def test_symlink_loop_is_capped(guard, ws):
    os.symlink("loop_b", ws / "loop_a")
    os.symlink("loop_a", ws / "loop_b")
    with pytest.raises(PathEscapesWorkspace) as ctx:
        guard.read_text("loop_a", follow_final=True)
    assert str(MAX_SYMLINK_HOPS) in str(ctx.value)


def test_symlinked_intermediate_directory_inside_is_followed(guard, ws):
    os.symlink("sub", ws / "sub_alias")
    assert guard.read_text("sub_alias/a.txt") == "inside-a"


# ── 抗竞态(本模块存在的理由)────────────────────────────────────────────


def _swapper(ws: Path, secret: Path, stop: threading.Event) -> None:
    """把 ``ws/f.txt`` 在普通文件与"指向工作区外"的符号链接之间原子替换。

    ``rename`` 一个符号链接盖到已存在的普通文件上是允许且原子的 —— 这正是
    纯路径校验挡不住的那条路:校验时它是普通文件,``open()`` 时它已是外链。
    """
    plain = ws / ".plain"
    link = ws / ".link"
    target = ws / "f.txt"
    while not stop.is_set():
        try:
            plain.write_text("inside", encoding="utf-8")
            if link.is_symlink():
                os.unlink(link)
            os.symlink(secret, link)
            os.rename(link, target)
            os.rename(plain, target)
        except OSError:
            pass


@pytest.mark.timeout(120)
def test_guard_never_reads_outside_under_symlink_swapping(ws, outside):
    """替换线程全程跑着,守卫**一次**都不许读到工作区外的内容。

    参照组(纯路径校验)在同样压力下的实测逃逸率约 1.3%,记录在 ``core/safe_fs``
    的 docstring 里。这里不把参照组写成断言 —— 它是时序相关的,断言"它必须炸"
    只会造出一条不稳定的用例。
    """
    (ws / "f.txt").write_text("inside", encoding="utf-8")
    secret = outside / "secret.txt"
    stop = threading.Event()
    thread = threading.Thread(target=_swapper, args=(ws, secret, stop), daemon=True)
    thread.start()
    try:
        leaked = 0
        attempts = 0
        refused = 0
        with WorkspaceGuard(ws) as g:
            deadline = time.time() + 5
            while time.time() < deadline:
                attempts += 1
                try:
                    if "OUTSIDE" in g.read_text("f.txt"):
                        leaked += 1
                except (SymlinkNotFollowed, OSError):
                    refused += 1
        assert attempts > 100, f"压力不足,只跑了 {attempts} 轮"
        assert refused > 0, "一次都没撞上替换 —— 这轮没真的形成竞态,断言等于没做"
        assert leaked == 0, f"读到工作区外内容 {leaked} 次(共 {attempts} 轮)"
    finally:
        stop.set()
        thread.join(timeout=10)


@pytest.mark.timeout(120)
def test_guard_never_writes_outside_under_symlink_swapping(ws, outside):
    """写比读更要命:跟着外链写下去就是往工作区外**改**别人的文件。"""
    (ws / "f.txt").write_text("inside", encoding="utf-8")
    secret = outside / "secret.txt"
    original = secret.read_text(encoding="utf-8")
    stop = threading.Event()
    thread = threading.Thread(target=_swapper, args=(ws, secret, stop), daemon=True)
    thread.start()
    try:
        with WorkspaceGuard(ws) as g:
            deadline = time.time() + 5
            while time.time() < deadline:
                try:
                    g.write_text("f.txt", "OVERWRITTEN-BY-GUARD")
                except (SymlinkNotFollowed, OSError):
                    pass
    finally:
        stop.set()
        thread.join(timeout=10)
    assert secret.read_text(encoding="utf-8") == original, "工作区外的文件被改写了"


@pytest.mark.timeout(120)
def test_the_window_this_module_exists_to_close_is_real(ws, outside):
    """反向验证:同样压力下,**旧的纯路径校验**确实会漏。

    这条不断言"必然漏"(时序相关),只断言"若漏了,漏的正是我们说的那条路" ——
    并把实测计数打出来,免得哪天窗口其实已经不存在了却没人发现。
    """
    (ws / "f.txt").write_text("inside", encoding="utf-8")
    secret = outside / "secret.txt"

    def old_resolve(path: str) -> Path:
        """先前 ``Node_120._resolve_path`` 的判定形态,逐字保留。"""
        root = os.path.realpath(ws)
        candidate = os.path.realpath(os.path.join(root, path))
        try:
            inside = os.path.commonpath([root, candidate]) == root
        except ValueError:
            inside = False
        if not inside:
            raise ValueError("outside the workspace")
        return Path(candidate)

    stop = threading.Event()
    thread = threading.Thread(target=_swapper, args=(ws, secret, stop), daemon=True)
    thread.start()
    leaked = passed = 0
    try:
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                resolved = old_resolve("f.txt")
            except (ValueError, OSError):
                continue
            passed += 1
            try:
                if "OUTSIDE" in resolved.read_text(encoding="utf-8"):
                    leaked += 1
            except OSError:
                pass
    finally:
        stop.set()
        thread.join(timeout=10)

    print(f"\n旧写法:校验通过 {passed} 次,其中读到工作区外 {leaked} 次")
    assert passed > 0, "参照组一次都没通过校验,这轮压力测试没有意义"
