"""tests/test_unwired_placement.py — 未接线函数的「去处表」必须和清单一一对得上。

``config/unwired_placement.json`` 写着安卓以外每个未接线函数该放在哪里（接到哪个调用点、挂到哪个端点、
被什么取代所以该删……），``docs/UNWIRED_CODE_INVENTORY.md`` 由它渲染。这张表只有保持对账才有用：

- 清单里冒出一条新的非安卓未接线函数，表里却没有它的去处 —— 失败；
- 表里某一条已经不在清单里（接上了、删掉了、改名了），却还留在表里 —— 失败。
  否则文档会继续告诉读者「这个函数该接到哪」，而它早就接上了。

后面几个用例是**反向断言**：构造确实缺去处 / 确实过期 / 类别不认识的输入，要求核对函数**必须**报出来。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
_SPEC = importlib.util.spec_from_file_location("unwired_inventory", REPO_ROOT / "scripts" / "unwired_inventory.py")
assert _SPEC and _SPEC.loader
inv = importlib.util.module_from_spec(_SPEC)
sys.modules["unwired_inventory"] = inv
_SPEC.loader.exec_module(inv)


@pytest.fixture(scope="module")
def current_rows():
    return inv.collect(reachability=False)["rows"]


def _row(path: str, name: str, owner: str = "", theme: str = "platform") -> dict:
    return {"path": path, "name": name, "owner": owner, "theme": theme}


class TestPlacementTableMatchesInventory:
    def test_every_non_android_function_has_a_placement(self, current_rows):
        report = inv.check_placement(current_rows, inv.load_placement())
        assert (
            report["missing"] == []
        ), "这些非安卓未接线函数在 config/unwired_placement.json 里没有去处，补上（接 / 挂 / 删 / 随对象 / 测试钩子 / 框架回调 / 产品决定）：\n" + "\n".join(
            report["missing"]
        )

    def test_no_stale_or_malformed_entries(self, current_rows):
        report = inv.check_placement(current_rows, inv.load_placement())
        assert report["bad"] == [], "格式或类别不对：\n" + "\n".join(report["bad"])
        assert (
            report["stale"] == []
        ), "这些条目已不在未接线清单里（接上 / 删掉 / 改名了），从 config/unwired_placement.json 删掉：\n" + "\n".join(
            report["stale"]
        )

    def test_android_part_is_deferred_not_placed(self, current_rows):
        table = inv.load_placement()
        android_paths = {r["path"] for r in current_rows if r["theme"] in inv.DEFERRED_THEMES}
        assert android_paths, "清单里应当仍有安卓部分（所有者安排暂缓）"
        assert not android_paths & set(table), "安卓部分按所有者安排暂缓，不应出现在去处表里"


class TestCheckPlacementReallyReports:
    def test_missing_placement_is_reported(self):
        report = inv.check_placement([_row("core/a.py", "do_it")], {})
        assert report["missing"] == ["core/a.py::do_it"]

    def test_stale_entry_is_reported(self):
        table = {"core/a.py": {"gone": ["delete", "被 b 取代"], "do_it": ["wire", "x 处"]}}
        report = inv.check_placement([_row("core/a.py", "do_it")], table)
        assert report["stale"] == ["core/a.py::gone"]
        assert report["missing"] == []

    def test_unused_wildcard_is_stale(self):
        table = {"core/a.py": {"do_it": ["wire", "x 处"], "*": ["delete", "其余"]}}
        report = inv.check_placement([_row("core/a.py", "do_it")], table)
        assert report["stale"] == ["core/a.py::*"]

    def test_unknown_category_is_reported(self):
        table = {"core/a.py": {"do_it": ["maybe", "再说"]}}
        report = inv.check_placement([_row("core/a.py", "do_it")], table)
        assert report["bad"] == ["core/a.py::do_it"]

    def test_empty_where_text_is_reported(self):
        table = {"core/a.py": {"do_it": ["wire", "  "]}}
        report = inv.check_placement([_row("core/a.py", "do_it")], table)
        assert report["bad"] == ["core/a.py::do_it"]

    def test_method_key_then_bare_name_then_wildcard(self):
        table = {
            "core/a.py": {
                "Thing.run": ["wire", "按类名.方法名"],
                "stop": ["delete", "按裸名"],
                "*": ["object", "其余"],
            }
        }
        assert inv.resolve_placement(_row("core/a.py", "run", owner="Thing"), table) == ("wire", "按类名.方法名")
        assert inv.resolve_placement(_row("core/a.py", "stop", owner="Thing"), table) == ("delete", "按裸名")
        assert inv.resolve_placement(_row("core/a.py", "peek", owner="Thing"), table) == ("object", "其余")
        assert inv.resolve_placement(_row("core/b.py", "peek"), table) is None

    def test_deferred_theme_needs_no_placement(self):
        report = inv.check_placement([_row("galaxy_gateway/android/x.py", "sync", theme="android")], {})
        assert report == {"missing": [], "bad": [], "stale": []}


def test_malformed_value_is_reported_not_crashing():
    table = {"core/a.py": {"do_it": "wire"}}
    report = inv.check_placement([_row("core/a.py", "do_it")], table)
    assert report["bad"] == ["core/a.py::do_it"]
    assert report["missing"] == []
