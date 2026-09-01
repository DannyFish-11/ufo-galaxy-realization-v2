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


def test_open_never_goes_through_a_path_string(guard):
    """``open()`` 全程不碰路径字符串 —— 拿到的是 fd,交给内建 open 的也是 fd。

    这是刻意的取舍:``f.name`` 因此是 fd 号而不是路径。换来的是这条路上再没有
    "把用户给的路径拼成字符串交给 open"这个形状 —— 那既是本模块自己反对的,
    也是 CodeQL 报 py/path-injection 的那一条。要路径请调 ``display_path``。
    """
    with guard.open("sub/a.txt") as handle:
        assert isinstance(handle.name, int), f".name 应当是 fd,拿到的是 {handle.name!r}"
        assert handle.read() == "inside-a"


@pytest.mark.parametrize(
    "mode",
    ["r", "rb", "r+", "rb+", "w", "wb", "w+", "wb+", "a", "ab", "a+", "ab+", "x", "xb", "x+"],
)
def test_flags_for_mode_matches_what_builtin_open_computes(mode, tmp_path):
    """``flags_for_mode`` 是在重做 CPython io.open 的一小段活儿 —— 不靠眼力,靠比对。

    内建 ``open`` 会把自己算好的 flags 交给 ``opener``。这里把它截下来,和我们
    自己算的逐位比。任何一个 mode 对不上,这条就红。
    """
    from core.safe_fs import flags_for_mode

    target = tmp_path / "probe.bin"
    if mode.startswith(("r", "a")) or "+" in mode:
        target.write_bytes(b"seed")
    if mode.startswith("x") and target.exists():
        target.unlink()

    captured = {}

    def _capture(path, flags):
        captured["flags"] = flags
        return os.open(path, flags, 0o666)

    with open(target, mode, opener=_capture) as handle:  # noqa: SIM115 — 上下文管理器已经在这
        assert handle is not None
    assert captured["flags"] == flags_for_mode(
        mode
    ), f"mode={mode!r}:内建算出 {captured['flags']:#o},我们算出 {flags_for_mode(mode):#o}"


def test_flags_for_mode_rejects_nonsense(guard):
    from core.safe_fs import flags_for_mode

    with pytest.raises(ValueError):
        flags_for_mode("q")


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


# ── PathOnlyGuard:Windows 回退实现的穿越防护 ─────────────────────────────
#
# 这一档**没有**抗竞态能力(没有 dir_fd 就做不到),但"挡住此刻就已越界的路径"
# 这件事必须做到。此前它一行测试都没有 —— 一个安全边界零覆盖,是本次补上的。


@pytest.fixture()
def path_guard(ws):
    from core.safe_fs import PathOnlyGuard

    return PathOnlyGuard(ws)


def test_path_only_guard_advertises_its_weaker_guarantee(path_guard):
    """它必须**自报**关不上窗口 —— 调用方据此判断拿到的是哪一档。"""
    assert path_guard.closes_toctou_window is False


def test_path_only_guard_reads_and_writes_inside(path_guard, ws):
    assert path_guard.read_text("sub/a.txt") == "inside-a"
    path_guard.write_text("sub/new.txt", "写进去的")
    assert (ws / "sub" / "new.txt").read_text(encoding="utf-8") == "写进去的"


@pytest.mark.parametrize(
    "bad",
    [
        "../outside/secret.txt",
        "../../etc/passwd",
        "/etc/passwd",
        "sub/../../outside/secret.txt",
    ],
)
def test_path_only_guard_refuses_traversal(path_guard, bad):
    with pytest.raises(PathEscapesWorkspace):
        path_guard.read_text(bad)


def test_path_only_guard_refuses_a_symlink_that_escapes(path_guard, ws, outside):
    """工作区**内**的符号链接指向外面 —— realpath 会摊平它,必须判出界。"""
    os.symlink(outside, ws / "escape")
    with pytest.raises(PathEscapesWorkspace):
        path_guard.read_text("escape/secret.txt")


def test_path_only_guard_refuses_a_final_symlink_that_escapes(path_guard, ws, outside):
    os.symlink(outside / "secret.txt", ws / "f.txt")
    with pytest.raises(PathEscapesWorkspace):
        path_guard.read_text("f.txt")


@pytest.mark.parametrize(
    "op",
    [
        lambda g: g.write_text("../outside/pwned.txt", "x"),
        lambda g: g.unlink("../outside/secret.txt"),
        lambda g: g.mkdir("../outside/pwned"),
        lambda g: g.rmdir("../outside"),
        lambda g: g.rmtree("../outside"),
        lambda g: g.rename("top.txt", "../outside/moved.txt"),
        lambda g: g.rename("../outside/secret.txt", "stolen.txt"),
        lambda g: g.listdir("../outside"),
        lambda g: g.stat("../outside/secret.txt"),
        lambda g: g.open_fd("../outside/secret.txt", os.O_RDONLY),
    ],
)
def test_path_only_guard_refuses_every_mutating_surface(path_guard, outside, op):
    """**每一个**对外方法都要挡住,不能只有读那条路守着。

    这条是拿参数化把整个接口面扫一遍 —— 漏掉任何一个方法,那个方法就是后门。
    """
    with pytest.raises(PathEscapesWorkspace):
        op(path_guard)
    assert (outside / "secret.txt").read_text(encoding="utf-8") == "TOP-SECRET-OUTSIDE", "工作区外的文件被动过了"


def test_path_only_guard_display_path_refuses_escape(path_guard):
    with pytest.raises(PathEscapesWorkspace):
        path_guard.display_path("../../etc/passwd")


# ── copytree:整棵树的下降也必须是描述符锚定的 ────────────────────────────


def _tree_snapshot(root):
    """把一棵树抄成可比对的形状:类型、权限、内容/链接目标。"""
    import stat as stat_module

    out = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in sorted(dirnames + filenames):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
            info = os.lstat(full)
            if stat_module.S_ISLNK(info.st_mode):
                out[rel] = ("link", os.readlink(full))
            elif stat_module.S_ISDIR(info.st_mode):
                out[rel] = ("dir", stat_module.S_IMODE(info.st_mode))
            else:
                out[rel] = ("file", stat_module.S_IMODE(info.st_mode), open(full, "rb").read())
    return out


@pytest.fixture()
def rich_tree(ws):
    """带深度、空目录、二进制、相对链接、绝对链接、非默认权限的一棵树。"""
    (ws / "src" / "deep" / "deeper").mkdir(parents=True)
    (ws / "src" / "f1.txt").write_text("one", encoding="utf-8")
    (ws / "src" / "deep" / "f2.bin").write_bytes(b"\x00\x01\x02")
    (ws / "src" / "deep" / "deeper" / "f3.txt").write_text("three", encoding="utf-8")
    (ws / "src" / "empty").mkdir()
    os.symlink("f1.txt", ws / "src" / "link_rel")
    os.symlink("/etc/passwd", ws / "src" / "link_abs")
    os.chmod(ws / "src" / "f1.txt", 0o640)
    os.chmod(ws / "src" / "deep", 0o750)
    return ws


def test_copytree_matches_shutil_exactly(guard, rich_tree, tmp_path):
    """与 ``shutil.copytree(symlinks=True)`` 逐条一致 —— 换实现不许改行为。"""
    import shutil

    reference = tmp_path / "reference"
    shutil.copytree(rich_tree / "src", reference, symlinks=True)
    guard.copytree("src", "copied")
    assert _tree_snapshot(rich_tree / "copied") == _tree_snapshot(reference)


def test_copytree_copies_symlinks_as_symlinks(guard, rich_tree, outside):
    """指向工作区外的链接被**原样搬成链接**,而不是把它指的内容拷进来。

    跟随就等于把工作区外的文件复制进沙箱 —— 这正是 ``copytree`` 默认行为下真正的
    越界风险。
    """
    os.symlink(outside / "secret.txt", rich_tree / "src" / "escape")
    guard.copytree("src", "copied")
    copied = rich_tree / "copied" / "escape"
    assert copied.is_symlink(), "应当是链接"
    assert not (rich_tree / "copied" / "escape").is_file() or copied.is_symlink()
    # 工作区里不该出现那段秘密内容
    for dirpath, _dirs, files in os.walk(rich_tree / "copied"):
        for name in files:
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                continue
            assert b"TOP-SECRET-OUTSIDE" not in open(full, "rb").read()


def test_copytree_refuses_a_source_outside_the_workspace(guard):
    with pytest.raises(PathEscapesWorkspace):
        guard.copytree("../outside", "stolen")


def test_copytree_refuses_a_destination_outside_the_workspace(guard, rich_tree):
    with pytest.raises(PathEscapesWorkspace):
        guard.copytree("src", "../outside/pwned")


def test_copytree_caps_depth(guard, ws):
    """防御性上限:层数过深直接拒,不无限递归下去。"""
    from core.safe_fs import WorkspaceGuard

    deep = ws / "chain"
    parts = ["chain"] + [f"d{i}" for i in range(WorkspaceGuard.MAX_COPY_DEPTH + 3)]
    (ws.joinpath(*parts)).mkdir(parents=True)
    with pytest.raises(PathEscapesWorkspace):
        guard.copytree("chain", "chain_copy")
    assert deep.exists()


@pytest.mark.timeout(120)
def test_copytree_never_pulls_in_content_from_outside_under_churn(ws, outside):
    """有人在树里反复把普通文件换成"指向工作区外"的符号链接时,拷出来的东西
    里**一次**都不许出现工作区外的内容。

    这是 ``_copy_tree`` 先前那条已知未堵窗口的直接检验:旧实现是
    ``shutil.copytree(路径, 路径)`` —— 树内部逐个条目按名字重开,中间能被换掉。
    """
    src = ws / "src"
    (src / "sub").mkdir(parents=True)
    for i in range(20):
        (src / "sub" / f"f{i}.txt").write_text("inside", encoding="utf-8")
    secret = outside / "secret.txt"

    stop = threading.Event()

    def churn():
        link = src / "sub" / ".tmplink"
        plain = src / "sub" / ".tmpplain"
        i = 0
        while not stop.is_set():
            i = (i + 1) % 20
            target = src / "sub" / f"f{i}.txt"
            try:
                plain.write_text("inside", encoding="utf-8")
                if link.is_symlink():
                    os.unlink(link)
                os.symlink(secret, link)
                os.rename(link, target)
                os.rename(plain, target)
            except OSError:
                pass

    thread = threading.Thread(target=churn, daemon=True)
    thread.start()
    leaked = rounds = 0
    try:
        with WorkspaceGuard(ws) as g:
            deadline = time.time() + 4
            while time.time() < deadline:
                rounds += 1
                dest = f"copy{rounds}"
                try:
                    g.copytree("src", dest)
                except (OSError, PathEscapesWorkspace):
                    continue
                for dirpath, _dirs, files in os.walk(ws / dest):
                    for name in files:
                        full = os.path.join(dirpath, name)
                        if os.path.islink(full):
                            continue
                        if b"TOP-SECRET-OUTSIDE" in open(full, "rb").read():
                            leaked += 1
    finally:
        stop.set()
        thread.join(timeout=10)
    assert rounds > 3, f"压力不足,只跑了 {rounds} 轮"
    assert leaked == 0, f"拷进来了工作区外的内容 {leaked} 次(共 {rounds} 轮)"
