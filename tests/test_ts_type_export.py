"""tests/test_ts_type_export.py
==================================

前后端类型不漂移守卫:committed 的 ui_element.gen.ts 必须与当前 Pydantic 契约
(core.schemas.ui_element)一致。改了后端字段却没重跑 scripts/gen_ts_types.py →
本测试失败,逼你 `python3 scripts/gen_ts_types.py` 再生成。
"""

from __future__ import annotations

import importlib.util
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_GEN = os.path.join(_ROOT, "scripts", "gen_ts_types.py")
_TS = os.path.join(_ROOT, "electron", "renderer", "panel", "src", "types", "ui_element.gen.ts")

_spec = importlib.util.spec_from_file_location("gen_ts_types", _GEN)
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)


def test_generated_ts_matches_schema():
    with open(_TS, encoding="utf-8") as f:
        committed = f.read()
    assert committed == gen.build(), (
        "ui_element.gen.ts 与 Pydantic 契约漂移了 —— 请重跑 " "`python3 scripts/gen_ts_types.py` 并提交。"
    )


def test_key_types_present():
    ts = gen.build()
    assert "export type UISource" in ts
    assert "export type UIActionKind" in ts
    assert "export interface UIGraph" in ts
    assert "export interface UIElementNode" in ts
    # 递归子节点、可空 bounds 正确导出
    assert "children?: UIElementNode[];" in ts
    assert "bounds?: UIBounds | null;" in ts
