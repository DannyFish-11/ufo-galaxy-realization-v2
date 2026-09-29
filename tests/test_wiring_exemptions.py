"""tests/test_wiring_exemptions.py — 「按文件 + 函数名」的接线豁免必须一直对得上真实代码。

``config/wiring_exemptions.json`` 让 ``scripts/check_wiring.py`` 不再把测试钩子与框架回调算作
「实现了但没人调」。豁免是在**关掉一道闸**，所以每一条都要经得起追问：

- 指向的定义必须真的存在于那个文件 —— 函数被删或改名后，豁免条目要一起删，否则它会
  悄悄豁免掉将来同名的新函数；
- 类别只能是 testhook / framework，理由不能空；
- 不能拿来豁免真实的运行时操作：``reset_bucket`` 这类名字像测试钩子、实为运行时操作的，
  check_wiring 的说明里专门点过名，这里钉住不让它回来。

后面两个用例是反向断言：豁免真的生效（确实从未接线名单里拿掉了），而且只作用于那一个文件。
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location("check_wiring", REPO_ROOT / "scripts" / "check_wiring.py")
assert _SPEC and _SPEC.loader
cw = importlib.util.module_from_spec(_SPEC)
sys.modules["check_wiring"] = cw
_SPEC.loader.exec_module(cw)

EXEMPTIONS = cw.load_file_exemptions()


def _defined_names(rel: str) -> set:
    tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
    return {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def test_every_exemption_points_at_a_real_definition():
    missing = []
    for rel, names in EXEMPTIONS.items():
        path = REPO_ROOT / rel
        if not path.exists():
            missing.extend(f"{rel}::{n}（文件已不存在）" for n in names)
            continue
        defined = _defined_names(rel)
        missing.extend(f"{rel}::{n}" for n in names if n not in defined)
    assert missing == [], "这些豁免已指不到真实定义，从 config/wiring_exemptions.json 删掉：\n" + "\n".join(missing)


def test_every_exemption_has_a_kind_and_a_reason():
    bad = [
        f"{rel}::{n}"
        for rel, names in EXEMPTIONS.items()
        for n, val in names.items()
        if not (isinstance(val, list) and len(val) == 2 and val[0] in cw.FILE_EXEMPTION_KINDS and str(val[1]).strip())
    ]
    assert bad == []


def test_runtime_operations_are_never_exempted():
    exempted = {n for names in EXEMPTIONS.values() for n in names}
    for name in ("reset_bucket", "reset_session", "reset_device"):
        assert name not in exempted, f"{name} 是真实的运行时操作，不能当测试钩子豁免"


def test_exemption_really_removes_the_definition_from_the_unwired_list(tmp_path, monkeypatch):
    src = tmp_path / "core" / "thing.py"
    src.parent.mkdir(parents=True)
    src.write_text("def reset_for_tests(x):\n    return x\n", encoding="utf-8")
    defs, count = cw.collect_definitions([src], root=tmp_path)
    assert ("reset_for_tests", "core/thing.py:1") in cw.find_unwired(defs, set(), count)
    monkeypatch.setattr(cw, "_FILE_EXEMPTIONS", {"core/thing.py": {"reset_for_tests": ["testhook", "测试用"]}})
    assert cw.find_unwired(defs, set(), count) == []


def test_exemption_is_scoped_to_its_file(tmp_path, monkeypatch):
    other = tmp_path / "core" / "other.py"
    other.parent.mkdir(parents=True)
    other.write_text("def reset_for_tests(x):\n    return x\n", encoding="utf-8")
    defs, count = cw.collect_definitions([other], root=tmp_path)
    monkeypatch.setattr(cw, "_FILE_EXEMPTIONS", {"core/thing.py": {"reset_for_tests": ["testhook", "测试用"]}})
    assert ("reset_for_tests", "core/other.py:1") in cw.find_unwired(defs, set(), count)


def test_exemption_file_is_valid_json_with_the_documented_shape():
    data = json.loads(cw.FILE_EXEMPTIONS_PATH.read_text(encoding="utf-8"))
    assert set(data) == {"_comment", "exemptions"}
