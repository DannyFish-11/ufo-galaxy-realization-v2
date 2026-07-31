"""分片的完整性契约。

分片最怕的**不是慢,是悄悄漏掉一批用例还显示绿灯** —— 那比原来那个会被
runner 杀掉的红门危险得多:红门至少让人知道没跑完,漏跑的绿门会让人以为
全都验过了。

所以这里守三条硬性质:并集 = 全集、两两不相交、结果确定。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from ci_test_shard import all_test_files, shard  # noqa: E402


@pytest.fixture(scope="module")
def files():
    return all_test_files()


# ── 完整性 ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("total", [1, 2, 3, 4, 5, 8])
def test_shards_cover_everything_exactly_once(files, total):
    """并集 = 全集,且两两不相交。

    漏一个文件 = 那批用例再也不会在 CI 上跑,而门是绿的。
    重复一个文件 = 白跑,浪费本来就紧张的 runner 资源。
    """
    seen: list[str] = []
    for i in range(1, total + 1):
        seen.extend(shard(files, i, total))

    assert sorted(seen) == sorted(files), f"{total} 分片的并集与全集不符"
    assert len(seen) == len(set(seen)), "有文件被分到了多个分片"


def test_single_shard_is_the_whole_set(files):
    """--of 1 必须等价于不分片 —— 这是回退路径。"""
    assert shard(files, 1, 1) == files


@pytest.mark.parametrize("total", [2, 4, 8])
def test_shards_are_reasonably_balanced(files, total):
    """轮转分配下各分片文件数最多差 1。

    按目录切会极不均匀(tests/ 顶层近千个文件、子目录寥寥),那样切等于没切:
    最大的那一份仍然会把 runner 压垮。
    """
    sizes = [len(shard(files, i, total)) for i in range(1, total + 1)]
    assert max(sizes) - min(sizes) <= 1, f"分片大小失衡: {sizes}"


# ── 确定性 ──────────────────────────────────────────────────────────────


def test_file_list_is_sorted(files):
    """排序是确定性的前提:文件系统遍历顺序不保证稳定,不排序的话同一次
    提交在两台机器上会切出不同的分片,失败就不可复现了。"""
    assert files == sorted(files)


def test_same_input_gives_same_output(files):
    assert shard(files, 2, 4) == shard(files, 2, 4)


def test_no_pycache_leaks_in(files):
    assert not any("__pycache__" in f for f in files)


def test_collects_a_plausible_number_of_files(files):
    """如果 glob 写错导致只找到几个文件,上面所有"并集=全集"的断言都会
    **依然通过**(空集合的并集也等于空集合)。这条把守卫自身钉住。"""
    assert len(files) > 100, f"只找到 {len(files)} 个测试文件,glob 可能写错了"


def test_finds_this_very_file(files):
    """最直接的自证:本文件必须在全集里。"""
    assert "tests/test_ci_test_shard.py" in files


# ── 参数校验 ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("index,total", [(0, 4), (5, 4), (-1, 4), (1, 0)])
def test_rejects_invalid_shard_parameters(files, index, total):
    """越界参数必须报错,不能静默返回空集合 —— 那会让作业"跑了 0 个用例
    然后绿灯"。"""
    with pytest.raises(ValueError):
        shard(files, index, total)
