"""tests/test_node65_merkle_behavior.py
=======================================
``nodes/Node_65_LoggerCentral`` 的 MerkleTree 行为测试。

这个节点此前**没有任何测试覆盖**(tests/test_all_nodes.py 对它收集到 0 项),
而它承担的是审计日志的防篡改根。本文件锁定两件事:

1. **防篡改语义不能被性能优化削弱** —— 惰性算根、叶子折叠都不得改变
   "内容变则根变" 这一根本性质;
2. **写入热路径必须有界** —— add_leaf 由每条审计日志触发,既不能每次重建整棵树
   (原 O(n^2)),也不能让叶子表无限增长。
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

_MAIN = pathlib.Path(__file__).resolve().parent.parent / "nodes" / "Node_65_LoggerCentral" / "main.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("_n65_under_test", _MAIN)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_n65_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def merkle_cls():
    return _load_module().MerkleTree


def _tree_with(merkle_cls, items):
    t = merkle_cls()
    for it in items:
        t.add_leaf(it)
    return t


class TestTamperEvidence:
    """防篡改是这棵树存在的唯一理由,任何优化都不能动摇它。"""

    def test_same_input_yields_same_root(self, merkle_cls):
        a = _tree_with(merkle_cls, [f"log{i}" for i in range(50)])
        b = _tree_with(merkle_cls, [f"log{i}" for i in range(50)])
        assert a.get_root() == b.get_root()
        assert a.get_root() is not None

    def test_altering_any_entry_changes_root(self, merkle_cls):
        clean = _tree_with(merkle_cls, [f"log{i}" for i in range(50)])
        tampered = _tree_with(merkle_cls, ["TAMPERED" if i == 7 else f"log{i}" for i in range(50)])
        assert clean.get_root() != tampered.get_root()

    def test_order_matters(self, merkle_cls):
        a = _tree_with(merkle_cls, ["x", "y"])
        b = _tree_with(merkle_cls, ["y", "x"])
        assert a.get_root() != b.get_root()

    def test_empty_tree_has_no_root(self, merkle_cls):
        assert merkle_cls().get_root() is None


class TestTamperEvidenceSurvivesCheckpointFolding:
    """叶子超上限后会折叠成 checkpoint —— 折叠【之前】的历史仍须影响最终根。"""

    def test_history_before_folding_still_affects_root(self, merkle_cls):
        # 两棵树只有第 1 条(早已被折叠进 checkpoint 的那条)不同,
        # 若折叠丢掉了历史,两者的根会相同 —— 那就等于篡改早期日志不可见。
        n = 200
        a = merkle_cls()
        a.MAX_LEAVES = 16
        b = merkle_cls()
        b.MAX_LEAVES = 16
        a.add_leaf("original_first_entry")
        b.add_leaf("TAMPERED_first_entry")
        for i in range(n):
            a.add_leaf(f"log{i}")
            b.add_leaf(f"log{i}")
        assert a.get_root() != b.get_root()

    def test_leaves_stay_bounded(self, merkle_cls):
        t = merkle_cls()
        t.MAX_LEAVES = 32
        for i in range(2000):
            t.add_leaf(f"log{i}")
        assert len(t.leaves) <= t.MAX_LEAVES

    def test_root_available_after_folding(self, merkle_cls):
        t = merkle_cls()
        t.MAX_LEAVES = 8
        for i in range(100):
            t.add_leaf(f"log{i}")
        assert t.get_root() is not None


class TestLazyRootDoesNotChangeSemantics:
    """惰性算根只是把计算推迟到读取时,可见结果必须与逐次重算一致。"""

    def test_root_reflects_latest_leaf(self, merkle_cls):
        t = merkle_cls()
        t.add_leaf("first")
        r1 = t.get_root()
        t.add_leaf("second")
        r2 = t.get_root()
        assert r1 != r2

    def test_repeated_reads_are_stable(self, merkle_cls):
        t = _tree_with(merkle_cls, ["a", "b", "c"])
        assert t.get_root() == t.get_root()

    def test_add_leaf_returns_leaf_hash(self, merkle_cls):
        t = merkle_cls()
        h = t.add_leaf("payload")
        assert isinstance(h, str) and len(h) == 64  # sha256 hexdigest
        assert t.verify("payload", h) is True
        assert t.verify("other", h) is False
