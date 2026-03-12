#!/usr/bin/env python3
"""
tests/test_e2e_capability_bus.py
====================================
端到端测试：MCP/Skill 加载 → 能力总线注入 → OpenClawd 工具收集 → 实际调用

验收条件（对应问题描述中的 4 个硬验收）：
  1. MCP/Skill 加载成功
  2. Schema 通过校验（Skill manifest 字段完整 / inputSchema 为 dict）
  3. 工具进入 Capability Bus（CapabilityRegistry）
  4. OpenClawd._collect_tools() 能返回该工具，_dispatch_tool_call() 可实际调用并返回真实结果
"""

import asyncio
import sys
from pathlib import Path

# 确保可以 import 仓库代码
sys.path.insert(0, str(Path(__file__).parent.parent))


# ──────────────────────────────────────────────────────────────────────────────
# 辅助 —— 重置单例，保证每个测试函数隔离
# ──────────────────────────────────────────────────────────────────────────────

def _reset_singletons():
    """重置 SkillLoader / CapabilityRegistry 单例，避免测试间状态污染。"""
    from core.skill_loader import SkillLoader
    from core.agent.capability_registry import CapabilityRegistry

    SkillLoader._instance = None
    CapabilityRegistry._instance = None


# ──────────────────────────────────────────────────────────────────────────────
# 测试 1：Skill 加载 & schema 校验
# ──────────────────────────────────────────────────────────────────────────────

async def test_skill_load_and_schema():
    """验收条件 1 + 2：hello_skill 加载成功，schema 字段完整。"""
    print("\n=== [1+2] Skill 加载 & Schema 校验 ===")
    _reset_singletons()

    from core.skill_loader import skill_loader, SkillStatus

    skill_path = Path(__file__).parent.parent / "skills" / "examples" / "hello_skill"
    assert skill_path.exists(), f"示例技能不存在: {skill_path}"

    result = await skill_loader.load(str(skill_path))

    # 验收 1：加载成功
    assert result.get("success"), f"Skill 加载失败: {result}"
    skill_id = result["skill_id"]
    print(f"  ✅ 加载成功: id={skill_id}, name={result['name']}")

    # 验收 2：Schema 字段完整
    mcp_schema = skill_loader.to_mcp_tool_schema(skill_id)
    assert mcp_schema is not None, "to_mcp_tool_schema 返回 None"
    assert "name" in mcp_schema, "缺少 name 字段"
    assert "description" in mcp_schema, "缺少 description 字段"
    assert "inputSchema" in mcp_schema, "缺少 inputSchema 字段"
    input_schema = mcp_schema["inputSchema"]
    assert isinstance(input_schema, dict), f"inputSchema 必须为 dict，实际: {type(input_schema)}"
    assert input_schema.get("type") == "object", "inputSchema.type 应为 object"
    assert "properties" in input_schema, "inputSchema 缺少 properties"
    print(f"  ✅ Schema 校验通过: {mcp_schema['name']}")

    # 技能状态应为 loaded（非 error）
    skill = skill_loader.skills.get(skill_id)
    assert skill is not None
    assert skill.status == SkillStatus.LOADED, f"期望 LOADED，实际 {skill.status}"
    print(f"  ✅ 状态: {skill.status.value}")

    return skill_id


# ──────────────────────────────────────────────────────────────────────────────
# 测试 2：Skill 自动注入能力总线
# ──────────────────────────────────────────────────────────────────────────────

async def test_skill_injected_into_capability_bus():
    """验收条件 3：Skill 加载后自动进入 CapabilityRegistry（能力总线）。"""
    print("\n=== [3] Skill 自动注入能力总线 ===")
    _reset_singletons()

    from core.skill_loader import skill_loader
    from core.agent.capability_registry import CapabilityRegistry

    skill_path = Path(__file__).parent.parent / "skills" / "examples" / "hello_skill"
    result = await skill_loader.load(str(skill_path))
    assert result.get("success"), f"加载失败: {result}"
    skill_id = result["skill_id"]

    reg = CapabilityRegistry.get_instance()

    # 总线中应包含该 skill
    item = reg.get(f"skill__{skill_id}")
    assert item is not None, f"skill__{skill_id} 未进入能力总线"
    assert item.source == "skill", f"来源错误: {item.source}"
    assert item.available, "能力条目应为 available"
    print(f"  ✅ skill__{skill_id} 已进入能力总线")

    # stats() 应可观测
    stats = reg.stats()
    assert stats["total"] >= 1
    assert stats["by_source"].get("skill", 0) >= 1
    assert "validation_errors" in stats
    print(f"  ✅ 能力总线状态: total={stats['total']}, by_source={stats['by_source']}")

    return skill_id


# ──────────────────────────────────────────────────────────────────────────────
# 测试 3：OpenClawd._collect_tools 从总线取工具
# ──────────────────────────────────────────────────────────────────────────────

async def test_collect_tools_uses_capability_bus():
    """验收条件 3+4（前半段）：_collect_tools() 从能力总线取到已注入的 Skill 工具。"""
    print("\n=== [3+4a] _collect_tools 通过能力总线 ===")
    _reset_singletons()

    from core.skill_loader import skill_loader
    from core.openclawd import OpenClawd

    skill_path = Path(__file__).parent.parent / "skills" / "examples" / "hello_skill"
    result = await skill_loader.load(str(skill_path))
    assert result.get("success"), f"加载失败: {result}"
    skill_id = result["skill_id"]

    # 构造一个最小的 OpenClawd 实例（不启动 LLM）
    oc = OpenClawd.__new__(OpenClawd)
    oc._initialized = False
    oc._tool_permission_checker = None
    oc._node_id_to_key = {}

    tools = oc._collect_tools()
    tool_names = [t["function"]["name"] for t in tools if "function" in t]

    assert f"skill__{skill_id}" in tool_names, (
        f"skill__{skill_id} 不在 _collect_tools 结果中: {tool_names[:10]}"
    )
    print(f"  ✅ skill__{skill_id} 已出现在 _collect_tools 返回值中")

    # 校验 schema 结构
    skill_tool = next(t for t in tools if t.get("function", {}).get("name") == f"skill__{skill_id}")
    fn = skill_tool["function"]
    assert "description" in fn, "缺少 description"
    assert "parameters" in fn, "缺少 parameters"
    assert isinstance(fn["parameters"], dict), f"parameters 应为 dict，实际 {type(fn['parameters'])}"
    print(f"  ✅ 工具 schema 结构正确")

    return skill_id


# ──────────────────────────────────────────────────────────────────────────────
# 测试 4：OpenClawd._dispatch_tool_call 真实调用 Skill
# ──────────────────────────────────────────────────────────────────────────────

async def test_dispatch_tool_call_real_execution():
    """验收条件 4（完整）：_dispatch_tool_call 实际调用 hello_skill 并返回真实结果（非 mock）。"""
    print("\n=== [4] _dispatch_tool_call 真实调用 ===")
    _reset_singletons()

    from core.skill_loader import skill_loader
    from core.openclawd import OpenClawd

    skill_path = Path(__file__).parent.parent / "skills" / "examples" / "hello_skill"
    result = await skill_loader.load(str(skill_path))
    assert result.get("success"), f"加载失败: {result}"
    skill_id = result["skill_id"]

    # 构造最小 OpenClawd 实例
    oc = OpenClawd.__new__(OpenClawd)
    oc._initialized = False
    oc._tool_permission_checker = None
    oc._node_id_to_key = {}

    # 调用工具
    call_result = await oc._dispatch_tool_call(
        tool_name=f"skill__{skill_id}",
        arguments={"name": "Galaxy"},
    )

    assert call_result.get("success"), f"工具调用失败: {call_result}"
    inner = call_result.get("result", {})
    # hello_skill.execute() 返回 {"success": True, "result": {...}}
    if isinstance(inner, dict) and "result" in inner:
        actual = inner["result"]
    else:
        actual = inner

    assert actual is not None, "调用结果为空"
    # 验证返回的消息包含预期内容
    result_str = str(actual)
    assert "Galaxy" in result_str, f"返回结果未包含 'Galaxy': {result_str}"
    print(f"  ✅ 真实调用成功，结果: {actual}")


# ──────────────────────────────────────────────────────────────────────────────
# 测试 5：schema 校验失败时不注入能力总线
# ──────────────────────────────────────────────────────────────────────────────

async def test_schema_validation_failure_not_injected():
    """验收：schema 校验失败时，有清晰错误日志，且不注入能力总线。"""
    print("\n=== [2] Schema 校验失败 → 不注入 ===")
    _reset_singletons()

    from core.agent.capability_registry import CapabilityRegistry

    reg = CapabilityRegistry.get_instance()
    initial_count = len(reg._items)

    # 尝试注入一个参数 schema 为非 dict 的工具（故意触发校验失败）
    reg.inject_skill(
        skill_id="bad_skill",
        skill_name="Bad Skill",
        description="schema 错误的技能",
        parameters="这不是一个 dict",  # type: ignore[arg-type]
    )

    # 不应该被注入
    assert reg.get("skill__bad_skill") is None, "schema 校验失败的技能不应被注入"
    # 应记录校验错误
    stats = reg.stats()
    errors = stats.get("validation_errors", [])
    assert any(e.get("id") == "bad_skill" for e in errors), (
        f"应记录 bad_skill 的校验错误，实际: {errors}"
    )
    print(f"  ✅ 非 dict schema 被拒绝，错误已记录: {errors}")


# ──────────────────────────────────────────────────────────────────────────────
# 测试 6：Skill 卸载后从总线移除
# ──────────────────────────────────────────────────────────────────────────────

async def test_skill_unload_ejects_from_bus():
    """验证 skill 卸载后从能力总线移除。"""
    print("\n=== [3] Skill 卸载 → 能力总线移除 ===")
    _reset_singletons()

    from core.skill_loader import skill_loader
    from core.agent.capability_registry import CapabilityRegistry

    skill_path = Path(__file__).parent.parent / "skills" / "examples" / "hello_skill"
    load_result = await skill_loader.load(str(skill_path))
    assert load_result.get("success"), f"加载失败: {load_result}"
    skill_id = load_result["skill_id"]

    reg = CapabilityRegistry.get_instance()
    assert reg.get(f"skill__{skill_id}") is not None, "加载后应在总线中"

    unload_result = await skill_loader.unload(skill_id)
    assert unload_result.get("success"), f"卸载失败: {unload_result}"
    assert reg.get(f"skill__{skill_id}") is None, "卸载后应从总线移除"
    print(f"  ✅ skill__{skill_id} 已从能力总线移除")


# ──────────────────────────────────────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────────────────────────────────────

async def main():
    print("=" * 65)
    print("E2E 验收测试：MCP/Skill → 能力总线 → OpenClawd 调用")
    print("=" * 65)

    tests = [
        ("Skill 加载 & Schema 校验", test_skill_load_and_schema),
        ("Skill 自动注入能力总线", test_skill_injected_into_capability_bus),
        ("_collect_tools 通过能力总线", test_collect_tools_uses_capability_bus),
        ("_dispatch_tool_call 真实执行", test_dispatch_tool_call_real_execution),
        ("Schema 校验失败不注入", test_schema_validation_failure_not_injected),
        ("Skill 卸载移除总线条目", test_skill_unload_ejects_from_bus),
    ]

    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            await fn()
            print(f"  PASS  {name}")
            passed += 1
        except Exception as exc:
            import traceback
            print(f"  FAIL  {name}: {exc}")
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 65)
    print(f"结果: {passed} 通过 / {failed} 失败 / {len(tests)} 总计")
    print("=" * 65)

    return failed == 0


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
