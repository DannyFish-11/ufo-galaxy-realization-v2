"""
tests/test_pr88_capability_device.py
======================================
PR-88 验收测试：能力总线强制使用、MCP/Skill 热加载协议校验、设备注册→能力同步

覆盖需求：
  1. CapabilityRegistry 是执行必经路径（ExecutionPlanner 强制刷新并注入 tool_schemas）
  2. MCP/Skill hot-reload 端点可用，协议 schema 校验正确
  3. 设备注册事件立即同步到 CapabilityRegistry
  4. Dashboard 可观测状态（loaded/validated/errors/tool_count）
"""

import asyncio
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ──────────────────────────────────────────────────────────────────────────────
# 1. CapabilityRegistry 基础功能
# ──────────────────────────────────────────────────────────────────────────────


class TestCapabilityRegistryBase(unittest.IsolatedAsyncioTestCase):
    """CapabilityRegistry 基础 API 测试（不依赖外部服务）。"""

    def setUp(self):
        # 每次测试使用独立实例（重置单例）
        from core.agent.capability_registry import CapabilityRegistry
        CapabilityRegistry._instance = None
        self.reg = CapabilityRegistry.get_instance()

    def test_singleton(self):
        from core.agent.capability_registry import CapabilityRegistry
        r1 = CapabilityRegistry.get_instance()
        r2 = CapabilityRegistry.get_instance()
        self.assertIs(r1, r2, "CapabilityRegistry 必须是单例")

    def test_register_and_list(self):
        from core.agent.capability_registry import CapabilityItem
        item = CapabilityItem(name="test_tool", description="A test tool", source="mcp")
        self.reg.register(item)
        tools = self.reg.list_tools()
        names = [t.name for t in tools]
        self.assertIn("test_tool", names)

    def test_get(self):
        from core.agent.capability_registry import CapabilityItem
        item = CapabilityItem(name="find_me", description="desc", source="skill")
        self.reg.register(item)
        found = self.reg.get("find_me")
        self.assertIsNotNone(found)
        self.assertEqual(found.name, "find_me")

    def test_find(self):
        from core.agent.capability_registry import CapabilityItem
        self.reg.register(CapabilityItem(name="alpha_tool", description="does alpha work", source="mcp"))
        results = self.reg.find("alpha")
        self.assertTrue(len(results) >= 1)

    def test_to_tool_schemas(self):
        from core.agent.capability_registry import CapabilityItem
        self.reg.register(CapabilityItem(name="schema_tool", description="test", source="mcp"))
        schemas = self.reg.to_tool_schemas()
        self.assertIsInstance(schemas, list)
        for s in schemas:
            self.assertIn("type", s)
            self.assertIn("function", s)

    def test_get_load_status_initial(self):
        status = self.reg.get_load_status()
        self.assertIn("loaded", status)
        self.assertIn("tool_count", status)
        self.assertIn("validated", status)
        self.assertIn("errors", status)
        self.assertIn("by_source", status)


# ──────────────────────────────────────────────────────────────────────────────
# 2. MCP/Skill 协议 schema 校验
# ──────────────────────────────────────────────────────────────────────────────


class TestProtocolSchemaValidation(unittest.TestCase):
    """validate_mcp_tool_schema / validate_skill_manifest 校验逻辑测试。"""

    def setUp(self):
        from core.agent.capability_registry import CapabilityRegistry
        CapabilityRegistry._instance = None
        self.reg = CapabilityRegistry.get_instance()

    # MCP tool schema

    def test_mcp_schema_valid(self):
        ok, err = self.reg.validate_mcp_tool_schema({
            "name": "my_tool",
            "description": "does stuff",
            "inputSchema": {"type": "object", "properties": {}},
        })
        self.assertTrue(ok, f"应通过校验，错误: {err}")
        self.assertEqual(err, "")

    def test_mcp_schema_missing_name(self):
        ok, err = self.reg.validate_mcp_tool_schema({
            "description": "no name",
            "inputSchema": {},
        })
        self.assertFalse(ok)
        self.assertIn("name", err)

    def test_mcp_schema_invalid_name_type(self):
        ok, err = self.reg.validate_mcp_tool_schema({"name": 123, "description": "bad"})
        self.assertFalse(ok)

    def test_mcp_schema_no_input_schema_is_ok(self):
        # inputSchema is optional — absence should not fail
        ok, err = self.reg.validate_mcp_tool_schema({"name": "tool", "description": "ok"})
        self.assertTrue(ok, f"缺少 inputSchema 不应失败: {err}")

    def test_mcp_schema_bad_input_schema_type(self):
        ok, err = self.reg.validate_mcp_tool_schema({
            "name": "tool",
            "description": "ok",
            "inputSchema": "not-a-dict",
        })
        self.assertFalse(ok)

    # Skill manifest

    def test_skill_manifest_valid(self):
        ok, err = self.reg.validate_skill_manifest({
            "id": "weather_skill",
            "name": "Weather",
            "description": "Get weather",
        })
        self.assertTrue(ok, f"应通过: {err}")

    def test_skill_manifest_missing_id(self):
        ok, err = self.reg.validate_skill_manifest({"name": "NoId", "description": "x"})
        self.assertFalse(ok)
        self.assertIn("id", err)

    def test_skill_manifest_missing_name(self):
        ok, err = self.reg.validate_skill_manifest({"id": "s1", "description": "x"})
        self.assertFalse(ok)
        self.assertIn("name", err)

    def test_skill_manifest_with_skill_id_alias(self):
        ok, err = self.reg.validate_skill_manifest({
            "skill_id": "alias_skill",
            "name": "AliasSkill",
        })
        self.assertTrue(ok, f"skill_id 别名应被接受: {err}")

    def test_skill_manifest_not_dict(self):
        ok, err = self.reg.validate_skill_manifest("not-a-dict")
        self.assertFalse(ok)


# ──────────────────────────────────────────────────────────────────────────────
# 3. 设备注册 → CapabilityRegistry 即时同步
# ──────────────────────────────────────────────────────────────────────────────


class TestDeviceCapabilitySync(unittest.TestCase):
    """sync_device() 将新设备能力立即写入注册表，无需完整刷新。"""

    def setUp(self):
        from core.agent.capability_registry import CapabilityRegistry
        CapabilityRegistry._instance = None
        self.reg = CapabilityRegistry.get_instance()

    def test_sync_device_adds_capabilities(self):
        added = self.reg.sync_device(
            device_id="android_01",
            device_name="MyPhone",
            capabilities=["screen", "camera"],
        )
        self.assertEqual(added, 2, "应新增 2 项能力")

        tools = self.reg.list_tools(source="gateway")
        names = [t.name for t in tools]
        self.assertIn("gateway__android_01__screen", names)
        self.assertIn("gateway__android_01__camera", names)

    def test_sync_device_no_duplicate(self):
        self.reg.sync_device("dev_x", "DevX", ["touch"])
        added2 = self.reg.sync_device("dev_x", "DevX", ["touch", "gps"])
        # "touch" 已存在，只加 "gps"
        self.assertEqual(added2, 1)

    def test_sync_device_updates_load_status(self):
        self.reg.sync_device("dev_z", "DevZ", ["screen"])
        status = self.reg.get_load_status()
        self.assertGreaterEqual(status["by_source"].get("gateway", 0), 1)
        self.assertGreaterEqual(status["tool_count"], 1)

    def test_sync_device_empty_capabilities(self):
        added = self.reg.sync_device("empty_dev", "EmptyDev", [])
        self.assertEqual(added, 0)

    def test_synced_device_appears_in_tool_schema(self):
        self.reg.sync_device("schema_dev", "SchemaDevice", ["screenshot"])
        schemas = self.reg.to_tool_schemas()
        schema_names = [s["function"]["name"] for s in schemas]
        self.assertIn("gateway__schema_dev__screenshot", schema_names)


# ──────────────────────────────────────────────────────────────────────────────
# 4. CapabilityRegistry.refresh() 带 load_status 更新
# ──────────────────────────────────────────────────────────────────────────────


class TestCapabilityRegistryRefresh(unittest.IsolatedAsyncioTestCase):
    """refresh() 正确更新 load_status，含 mocked 外部依赖。"""

    def setUp(self):
        from core.agent.capability_registry import CapabilityRegistry
        CapabilityRegistry._instance = None
        self.reg = CapabilityRegistry.get_instance()

    async def test_refresh_updates_loaded_flag(self):
        """刷新后 loaded 标志应为 True。"""
        # 无需真实 MCP/Skill，依赖容错降级
        await self.reg.refresh(force=True)
        status = self.reg.get_load_status()
        self.assertTrue(status["loaded"], "刷新后 loaded 应为 True")

    async def test_refresh_updates_tool_count(self):
        """注册表为空时 tool_count 应为 0。"""
        await self.reg.refresh(force=True)
        status = self.reg.get_load_status()
        self.assertIsInstance(status["tool_count"], int)
        self.assertGreaterEqual(status["tool_count"], 0)

    async def test_refresh_errors_list(self):
        """errors 字段是列表。"""
        await self.reg.refresh(force=True)
        status = self.reg.get_load_status()
        self.assertIsInstance(status["errors"], list)

    async def test_refresh_validated_dict(self):
        """validated 字段包含 mcp/skill 键。"""
        await self.reg.refresh(force=True)
        status = self.reg.get_load_status()
        validated = status.get("validated", {})
        self.assertIn("mcp", validated)
        self.assertIn("skill", validated)

    async def test_refresh_ttl_skips_second_call(self):
        """在 TTL 内第二次调用不应触发二次刷新（通过 last_refresh_ts 判断）。"""
        await self.reg.refresh(force=True)
        ts1 = self.reg.get_load_status()["last_refresh_ts"]
        await self.reg.refresh()  # no force — should be skipped
        ts2 = self.reg.get_load_status()["last_refresh_ts"]
        self.assertAlmostEqual(ts1, ts2, places=3, msg="TTL 内不应二次刷新")


# ──────────────────────────────────────────────────────────────────────────────
# 5. ExecutionPlanner 强制使用 CapabilityRegistry
# ──────────────────────────────────────────────────────────────────────────────


class TestExecutionPlannerCapabilityEnforcement(unittest.IsolatedAsyncioTestCase):
    """ExecutionPlanner.execute() 必须刷新 CapabilityRegistry 并注入 tool_schemas。"""

    def setUp(self):
        from core.agent.capability_registry import CapabilityRegistry
        CapabilityRegistry._instance = None

    async def test_planner_refreshes_registry(self):
        """ExecutionPlanner 执行时必须调用 CapabilityRegistry.refresh()。"""
        from core.agent.execution_planner import ExecutionPlanner, ExecutionPlan
        from core.agent.capability_registry import CapabilityRegistry
        from core.agent.intent_router import IntentResult

        registry = CapabilityRegistry.get_instance()
        refresh_called = {"called": False}
        original_refresh = registry.refresh

        async def mock_refresh(force=False):
            refresh_called["called"] = True
            await original_refresh(force=force)

        registry.refresh = mock_refresh

        plan = ExecutionPlan(
            message="test task",
            intent=IntentResult(mode="task_execute"),
        )

        planner = ExecutionPlanner()
        # 仅测试 registry 调用，不关心执行结果（无 LLM 可能失败）
        try:
            await planner.execute(plan)
        except Exception:
            pass

        self.assertTrue(refresh_called["called"], "ExecutionPlanner 必须调用 CapabilityRegistry.refresh()")

    async def test_planner_injects_tool_schemas_into_context(self):
        """执行后 plan.context 应包含 __tool_schemas__ 条目。"""
        from core.agent.execution_planner import ExecutionPlanner, ExecutionPlan
        from core.agent.capability_registry import CapabilityRegistry, CapabilityItem
        from core.agent.intent_router import IntentResult

        registry = CapabilityRegistry.get_instance()
        registry.register(CapabilityItem(name="ctx_tool", description="for ctx test", source="mcp"))

        plan = ExecutionPlan(
            message="inject context test",
            intent=IntentResult(mode="task_execute"),
        )

        planner = ExecutionPlanner()
        try:
            await planner.execute(plan)
        except Exception:
            pass

        roles = [c.get("role") for c in plan.context]
        self.assertIn("__tool_schemas__", roles, "plan.context 必须包含 __tool_schemas__ 条目")

    async def test_planner_does_not_inject_schemas_twice(self):
        """重复调用不应向 plan.context 追加多个 __tool_schemas__ 条目。"""
        from core.agent.execution_planner import ExecutionPlanner, ExecutionPlan
        from core.agent.intent_router import IntentResult

        plan = ExecutionPlan(
            message="no duplicate schemas",
            intent=IntentResult(mode="task_execute"),
        )

        planner = ExecutionPlanner()
        for _ in range(2):
            try:
                await planner.execute(plan)
            except Exception:
                pass

        count = sum(1 for c in plan.context if c.get("role") == "__tool_schemas__")
        self.assertEqual(count, 1, "__tool_schemas__ 条目不应重复注入")


# ──────────────────────────────────────────────────────────────────────────────
# 6. Capability 路由模块可导入
# ──────────────────────────────────────────────────────────────────────────────


class TestCapabilitiesRouteModule(unittest.TestCase):
    """确认 core/routes/capabilities.py 模块结构正确。"""

    def test_module_importable(self):
        try:
            from core.routes import capabilities
            self.assertTrue(True)
        except ImportError as e:
            self.fail(f"capabilities 路由模块导入失败: {e}")

    def test_create_router_callable(self):
        from core.routes.capabilities import create_router
        self.assertTrue(callable(create_router))

    def test_router_has_capability_routes(self):
        from core.routes.capabilities import create_router
        router = create_router()
        paths = [route.path for route in router.routes]
        self.assertIn("/api/v1/capabilities/reload", paths)
        self.assertIn("/api/v1/capabilities/status", paths)
        self.assertIn("/api/v1/capabilities/tools", paths)
        self.assertIn("/api/v1/capabilities/mcp/load", paths)
        self.assertIn("/api/v1/capabilities/skill/load", paths)


# ──────────────────────────────────────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────────────────────────────────────


def run_tests():
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in [        TestCapabilityRegistryBase,
        TestProtocolSchemaValidation,
        TestDeviceCapabilitySync,
        TestCapabilityRegistryRefresh,
        TestExecutionPlannerCapabilityEnforcement,
        TestCapabilitiesRouteModule,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    print("""
╔═══════════════════════════════════════════════════════════════╗
║   PR-88 能力与设备验收测试                                    ║
║   Capability Bus & Device Registration Tests                  ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    sys.exit(run_tests())
