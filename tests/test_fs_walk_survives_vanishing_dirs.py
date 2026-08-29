"""``core/fs_walk`` —— 遍历途中目录消失,整轮扫描不能被炸掉。

这些测试守的是一个**已复现**的缺陷,不是假想:``Path.rglob`` 的迭代器在
``os.scandir`` 上只捕 ``PermissionError``,子目录此刻被删就抛 ``FileNotFoundError``
穿透到调用方 —— 而调用方的 ``try/except OSError`` 普遍只包住循环体,包不住迭代器。

两组断言缺一不可:
  * **抗竞态** —— 目录在脚下消失时不抛;
  * **等价** —— 静态树上结果与 ``rglob``/``glob`` 逐字相同。
只有前者会退化成"写个什么都不返回的函数也能过"。
"""

from __future__ import annotations

import shutil
import threading
import time

import pytest

from core.fs_walk import COMMON_SKIP_DIRS, iter_tree_files, walk_tree_files


@pytest.fixture()
def tree(tmp_path):
    """造一棵有深度、有多种后缀的小树。"""
    for i in range(6):
        d = tmp_path / f"pkg{i}" / "sub"
        d.mkdir(parents=True)
        (d / f"mod{i}.py").write_text(f"X = {i}\n", encoding="utf-8")
        (d / f"note{i}.md").write_text("# note\n", encoding="utf-8")
    (tmp_path / "top.py").write_text("TOP = 1\n", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "cached.py").write_text("C = 1\n", encoding="utf-8")
    return tmp_path


# ── 等价性 ────────────────────────────────────────────────────────────────


def test_recursive_matches_rglob(tree):
    assert {p.resolve() for p in iter_tree_files(tree, "*.py")} == {
        p.resolve() for p in tree.rglob("*.py") if p.is_file()
    }


def test_non_recursive_matches_glob(tree):
    assert {p.resolve() for p in iter_tree_files(tree, "*.py", recursive=False)} == {
        p.resolve() for p in tree.glob("*.py") if p.is_file()
    }


def test_include_dirs_matches_rglob_including_directories(tree):
    """``rglob`` 本来就产出目录 —— 开了 include_dirs 就必须一个不差。"""
    assert {p.resolve() for p in iter_tree_files(tree, "*", include_dirs=True)} == {
        p.resolve() for p in tree.rglob("*")
    }


def test_include_dirs_non_recursive_still_yields_directories(tree):
    """回归:曾经把"不下降"和"不产出"写成了一件事,非递归时目录全丢了。

    ``glob("*")`` 是产出目录的;不下降 ≠ 不产出。
    """
    got = {p.resolve() for p in iter_tree_files(tree, "*", recursive=False, include_dirs=True)}
    assert got == {p.resolve() for p in tree.glob("*")}
    assert any(p.is_dir() for p in got), "非递归 + include_dirs 必须含目录"


# ── 剪枝与降级 ────────────────────────────────────────────────────────────


def test_skip_dirs_prunes_before_descending(tree):
    out = list(iter_tree_files(tree, "*.py", skip_dirs=COMMON_SKIP_DIRS))
    assert out, "剪枝不该把整棵树剪没"
    assert not any("__pycache__" in p.parts for p in out)


def test_missing_root_is_reported_not_raised(tree):
    seen: list[str] = []
    assert list(iter_tree_files(tree / "没有这个目录", "*.py", unreadable=seen)) == []
    assert len(seen) == 1, "根不存在必须留下痕迹 —— 降级可以发生,但不许静默"


def test_healthy_tree_reports_nothing_unreadable(tree):
    seen: list[str] = []
    list(iter_tree_files(tree, "*.py", unreadable=seen))
    assert seen == [], "正常树上不该误报"


# ── 抗竞态(本模块存在的理由)────────────────────────────────────────────


def _churn(root, stop: threading.Event) -> None:
    i = 0
    while not stop.is_set():
        i += 1
        d = root / f"churn{i}" / "deep"
        try:
            d.mkdir(parents=True, exist_ok=True)
            (d / "x.py").write_text("A = 1\n", encoding="utf-8")
            shutil.rmtree(root / f"churn{i}", ignore_errors=True)
        except OSError:
            pass


@pytest.mark.timeout(60)
def test_vanishing_directories_do_not_break_the_scan(tree):
    """有目录在脚下不断消失时,整轮遍历必须跑完。

    对照:同样的压力下裸 ``rglob`` 会抛 ``FileNotFoundError``(见模块 docstring 的
    真实 traceback)。这里不断言对照组一定炸 —— 那是时序相关的,在测试里断言它
    反而会变成一条不稳定的用例;真实复现记录在 ``core/fs_walk`` 的 docstring 与 PR 里。
    """
    stop = threading.Event()
    t = threading.Thread(target=_churn, args=(tree, stop), daemon=True)
    t.start()
    try:
        deadline = time.time() + 3
        rounds = 0
        while time.time() < deadline:
            rounds += 1
            # 不加 try:这里一旦抛异常,测试就该红 —— 那正是本模块要消灭的行为。
            list(iter_tree_files(tree, "*.py"))
        assert rounds > 0
    finally:
        stop.set()
        t.join(timeout=5)


@pytest.mark.timeout(60)
def test_walk_tree_files_is_sorted_and_files_only(tree):
    out = walk_tree_files(tree, "*.py", skip_dirs=COMMON_SKIP_DIRS)
    assert out == sorted(out)
    assert out and all(p.is_file() for p in out)
