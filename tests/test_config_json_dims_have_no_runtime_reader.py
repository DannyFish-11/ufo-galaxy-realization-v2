"""钉住一个复核出来的事实：``runtime/config.json`` 里那几维（provider 开关、原生多模态策略、网络地址、
安卓推理模式）在生产代码里**既没有写入方、也没有读取方**。

为什么要钉：``docs/PANEL_SURFACE_CONVERGENCE.md`` 原先把它们记成「面板失去的写能力」，要求「把两套写入
链路合成一套」。2026-09-28 复核后发现生效的只有一套（``POST /api/config``），这几维是座孤岛 —— 接到面板上
只会得到按了不起作用的按钮。

这组测试哪天红了，意思是**有人给孤岛接上了写入方或读取方**：那时这几维才真正生效，
``PANEL_SURFACE_CONVERGENCE.md`` 最后一节、``SYSTEM_STATUS.md`` 第 6.4 节与结论
``config-json-provider-dims-have-no-runtime-reader`` 都要跟着改 —— 这正是它该响的时候。
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterator, List, Set, Tuple

ROOT = Path(__file__).resolve().parent.parent
PRODUCTION = ("core", "galaxy_gateway", "launcher")

_WRITERS = {"set_toggle", "set_native_mm_policy", "set_network_url", "set_android_inference_mode", "set_oneapi"}
_READERS = {
    "build_inventory_from_config_authority",
    "merge_config_authority_into_inventory",
    "build_candidate_pool",
    "get_oneapi_candidate_state",
}
_HOMES = {"core/config_service.py", "core/model_topology/inventory_from_config.py"}


def _production_files() -> Iterator[Path]:
    for top in PRODUCTION:
        yield from (ROOT / top).rglob("*.py")
    yield ROOT / "main.py"


def _calls(names: Set[str]) -> List[Tuple[str, int, str]]:
    hits: List[Tuple[str, int, str]] = []
    for f in _production_files():
        rel = f.relative_to(ROOT).as_posix()
        if rel in _HOMES or "__pycache__" in rel:
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else fn.id if isinstance(fn, ast.Name) else ""
            if name in names:
                hits.append((rel, node.lineno, name))
    return hits


def test_nothing_in_production_writes_the_config_json_dims() -> None:
    assert _calls(_WRITERS) == [], "有人在生产代码里写 config.json 的这几维了 —— 见本文件头，文档要跟着改"


def test_nothing_in_production_reads_them_through_the_config_authority_inventory() -> None:
    assert _calls(_READERS) == [], "有人把 config.json 的 provider 维度接进运行时了 —— 见本文件头"


def test_the_live_write_path_is_the_one_the_panel_uses() -> None:
    """生效的那一条：POST /api/config，密钥经 ConfigService.set_secret / delete_secret 落 secrets.env。"""
    body = (ROOT / "core" / "routes" / "config.py").read_text(encoding="utf-8")
    assert "_cs.set_secret(" in body and "_cs.delete_secret(" in body
    assert "_write_env_file_with(final, exclude=_secrets_persisted)" in body
