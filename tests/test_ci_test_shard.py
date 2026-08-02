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

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

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
    """各分片大小不得相差过大。

    这条曾经断言"最多差 1" —— 那是**轮转分配**(``i % total``)的精确性质。改成
    哈希分配后放宽到比例容差，这是一次自觉的取舍，不是把门调松来迁就实现：

      轮转  精确均分，但新增一个文件会重排所有分片 → 分片失败无法归因
      哈希  略有偏斜(实测 4 片约 12%、8 片约 22%)，但新增文件只动它自己

    分片存在的目的是【别让一个进程扛完四万条用例把 runner 压垮】，不是让四份
    一样长。十几个百分点的偏斜完全不影响这个目的，而归因能力影响每一次排查。

    容差取 1.5 倍：足以容纳哈希的自然偏斜，又能拦住"某一片畸大"这种真正的退化
    (比如误按目录切 —— tests/ 顶层近千个文件、子目录寥寥，那样切等于没切)。
    """
    sizes = [len(shard(files, i, total)) for i in range(1, total + 1)]
    assert min(sizes) > 0, f"有空分片: {sizes}"
    assert max(sizes) / min(sizes) <= 1.5, f"分片大小失衡: {sizes}"


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


# ── 稳定性:新增文件不得重排既有文件 ──────────────────────────────────────


@pytest.mark.parametrize("total", [2, 4, 8])
def test_adding_a_file_does_not_move_existing_files(files, total):
    """新增一个测试文件，只能影响它自己落在哪一片。

    这条守的是【归因能力】，不是性能。原先的轮转分配按排序后的下标切
    (``i % total``)，新增一个文件会让排在它后面的所有文件下标 +1 —— 四个分片
    整体重排。实测新增一个 tests/test_atomic_json.py 就让分片 3 的 262 个文件
    从第 21 项起全部换掉。

    后果是某个 PR 只要增删一个测试文件，就等于把所有测试重新掷一次骰子：潜伏的
    顺序依赖会随机地红或绿，而红的那条与该 PR 的改动可能毫无关系。本仓库真的
    因此排查过一次 —— 一条读全局状态的审计断言被无关的新增文件推到了污染源后面。
    """
    # 插一个排序上会落在最前面的名字，对轮转分配是最坏情况
    injected = "tests/test_000_injected_probe.py"
    grown = sorted([*files, injected])

    def layout(pool):
        return {f: next(i for i in range(1, total + 1) if f in shard(pool, i, total)) for f in pool}

    before = layout(files)
    after = layout(grown)

    moved = [f for f in files if before[f] != after[f]]
    assert not moved, f"新增一个文件导致 {len(moved)} 个既有文件换片(前 5 个: {moved[:5]})"


def test_assignment_is_stable_across_processes():
    """分片结果不能依赖 PYTHONHASHSEED —— 否则本地无法复现 CI 的某一片。

    内置 hash() 对 str 加了进程级随机盐，用它分片会让同一份文件清单在两个进程里
    切出不同结果。这里固定一组输入，断言分配与解释器的哈希种子无关。
    """
    import subprocess
    import sys

    sample = [f"tests/test_{c}.py" for c in "abcdefghijklmnopqrstuvwxyz"]
    expected = shard(sample, 1, 4)

    code = (
        "import sys; sys.path.insert(0, 'scripts');"
        "from ci_test_shard import shard;"
        f"print(shard({sample!r}, 1, 4))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env={"PYTHONHASHSEED": "424242", "PATH": "/usr/bin:/bin"},
        cwd=REPO_ROOT,
    )

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == str(expected), "不同 PYTHONHASHSEED 下分片结果不一致"
