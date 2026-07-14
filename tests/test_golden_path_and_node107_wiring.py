"""tests/test_golden_path_and_node107_wiring.py
===================================================

Two related wiring defects found by the omni-modal capability audit:

1. ``LocalNodeFacade.invoke()`` (the Golden Path entry,
   core/node_facade_local.py:117) calls ``resolver.resolve_by_node_id()`` —
   a method that never existed on ``DeviceNodeResolver``. Every invocation
   raised AttributeError, silently swallowed into a ``resolver_error``
   fallback: the Golden Path (direct in-process node facade) never worked
   for ANY node, and nothing in the logs said so.

2. ``Node_107_FunctionCalling`` (the OpenAI function-calling dispatcher) had
   only FastAPI routes — no module-level ``process``/``execute`` callable.
   Its generic fusion_entry probes for those names and found nothing, so the
   main invocation chain could never reach it: the system's only
   "LLM autonomously picks and executes a tool" capability sat orphaned.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestResolveByNodeId:
    def test_method_exists_and_resolves_mapped_node(self):
        from core.device_node_resolver import DeviceNodeResolver

        resolver = DeviceNodeResolver()
        mapping = resolver.resolve_by_node_id("Node_33_ADB")
        assert mapping is not None
        assert mapping["node"] == "Node_33_ADB"

    def test_short_id_prefix_matches_with_underscore_boundary(self):
        from core.device_node_resolver import DeviceNodeResolver

        resolver = DeviceNodeResolver()
        # 短 ID("Node_33")应命中 "Node_33_ADB"
        mapping = resolver.resolve_by_node_id("Node_33")
        assert mapping is not None
        assert mapping["node"] == "Node_33_ADB"

    def test_unmapped_node_returns_none_not_error(self):
        from core.device_node_resolver import DeviceNodeResolver

        resolver = DeviceNodeResolver()
        assert resolver.resolve_by_node_id("Node_107_FunctionCalling") is None
        assert resolver.resolve_by_node_id("") is None

    def test_local_facade_no_longer_hits_resolver_error(self):
        """Golden Path 的失败原因必须是语义性的(NO_MAPPING/加载失败),
        不能再是 resolver 自身的 AttributeError。"""
        from core.node_facade_local import LocalNodeFacade

        result = asyncio.run(
            LocalNodeFacade().invoke(
                node_id="Node_107_FunctionCalling",
                action="call",
                params={},
            )
        )
        assert not str(result.get("error", "")).startswith("resolver_error"), result
        # 未映射节点走 legacy 回退是预期行为
        assert result.get("error") == "NO_MAPPING"


def _load_node107_main():
    node_dir = REPO_ROOT / "nodes" / "Node_107_FunctionCalling"
    spec = importlib.util.spec_from_file_location(
        "Node_107_FunctionCalling.main",
        str(node_dir / "main.py"),
        submodule_search_locations=[str(node_dir)],
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestNode107InProcessEntry:
    def test_module_level_process_exists(self):
        mod = _load_node107_main()
        assert hasattr(mod, "process"), (
            "Node_107 main.py 缺少模块级 process() — fusion_entry 探测不到入口," "节点在主调用链里不可达"
        )

    def test_list_tools_works_in_process(self):
        mod = _load_node107_main()
        result = asyncio.run(mod.process("list_tools"))
        assert result["success"] is True
        assert result["count"] >= 4  # 内置工具:time/calculate/search_web/node_status

    def test_call_without_prompt_fails_cleanly(self):
        mod = _load_node107_main()
        result = asyncio.run(mod.process("call"))
        assert result == {"success": False, "error": "missing 'prompt'"}

    def test_fusion_entry_execute_reaches_process(self):
        """端到端:通过节点自己的 fusion_entry(主链的实际加载方式)调用。"""
        node_dir = REPO_ROOT / "nodes" / "Node_107_FunctionCalling"
        spec = importlib.util.spec_from_file_location(
            "Node_107_FunctionCalling.fusion_entry",
            str(node_dir / "fusion_entry.py"),
            submodule_search_locations=[str(node_dir)],
        )
        fe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fe)

        node = fe.get_node_instance()
        result = asyncio.run(node.execute("list_tools"))
        assert result["success"] is True, result
        assert result["data"]["count"] >= 4

    def test_http_exception_degrades_to_plain_error(self):
        """register_tool 缺参会触发 FastAPI 校验异常——进程内必须降级为
        普通错误 dict,不能向上抛。"""
        mod = _load_node107_main()
        result = asyncio.run(mod.process("register_tool"))
        assert result["success"] is False
        assert result["error"]
