#!/usr/bin/env python3
"""
Agent 迁移闭环测试 — Phase 1 Matrix OS
======================================

模拟完整流程:
1. 服务端创建 AgentManifest
2. 序列化为 JSON
3. 通过模拟 WS 传输
4. 端侧 LocalAgentRuntime 反序列化
5. 端侧执行 Thought/Action/Observation 循环
6. 日志回传验证
"""

import os
import sys
import json
import asyncio
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_1_manifest_serialization():
    """测试 AgentManifest 序列化/反序列化"""
    print("\n[测试 1] AgentManifest 序列化/反序列化")

    from core.agent_manifest import AgentManifest, ToolDeclaration, TaskItem

    # 创建 Manifest
    manifest = AgentManifest.create_device_control_agent(
        target_device="android_001",
        instruction="打开微信并发送消息给张三",
        source_device="server",
    )

    # 序列化
    json_str = manifest.to_json()
    checksum = manifest.checksum()
    print(f"  Manifest ID: {manifest.manifest_id[:8]}")
    print(f"  JSON 大小: {len(json_str)} bytes")
    print(f"  校验和: {checksum}")
    print(f"  工具数: {len(manifest.tools)}")
    print(f"  任务数: {len(manifest.tasks)}")

    assert len(json_str) > 100, "JSON 序列化太短"
    assert len(checksum) == 16, "校验和长度应为 16"

    # 反序列化
    restored = AgentManifest.from_json(json_str)
    assert restored.manifest_id == manifest.manifest_id
    assert restored.agent_name == manifest.agent_name
    assert restored.target_device == "android_001"
    assert restored.source_device == "server"
    assert len(restored.tools) == len(manifest.tools)
    assert restored.checksum() == checksum  # 校验和一致

    print("  ✅ 序列化/反序列化一致性验证通过")


def test_2_ws_transport_simulation():
    """模拟 WebSocket 传输"""
    print("\n[测试 2] WebSocket 传输模拟")

    from core.agent_manifest import AgentManifest

    manifest = AgentManifest.create_device_control_agent(
        target_device="android_001",
        instruction="截图并发送到电脑",
    )

    # 模拟 WS 消息封装
    ws_message = {
        "type": "agent_deploy",
        "manifest": manifest.to_dict(),
        "checksum": manifest.checksum(),
    }

    # 模拟网络传输 (JSON encode → decode)
    wire_data = json.dumps(ws_message, ensure_ascii=False)
    received = json.loads(wire_data)

    print(f"  传输数据大小: {len(wire_data)} bytes")
    print(f"  消息类型: {received['type']}")

    # 校验完整性
    restored_manifest = AgentManifest.from_dict(received["manifest"])
    assert restored_manifest.checksum() == received["checksum"], "校验和不匹配！传输损坏"
    assert restored_manifest.manifest_id == manifest.manifest_id
    assert received["type"] == "agent_deploy"

    print("  ✅ WebSocket 传输模拟 + 校验和验证通过")


def test_3_sequential_execution():
    """测试 LocalAgentRuntime 顺序执行模式"""
    print("\n[测试 3] LocalAgentRuntime 顺序执行")

    async def _test():
        from core.local_agent_runtime import LocalAgentRuntime
        from core.agent_manifest import AgentManifest, TaskItem

        # 记录执行的工具调用
        executed_tools = []
        reported_steps = []

        async def mock_tool_executor(tool_name, params):
            executed_tools.append({"tool": tool_name, "params": params})
            return {"success": True, "tool": tool_name, "result": "ok"}

        async def mock_status_reporter(manifest_id, step):
            reported_steps.append(step)

        runtime = LocalAgentRuntime(
            tool_executor=mock_tool_executor,
            status_reporter=mock_status_reporter,
        )

        # 创建多步骤 Manifest
        manifest = AgentManifest.create_multi_step_agent(
            agent_name="test_sequential",
            steps=[
                {"instruction": "打开微信", "action": "open_app", "params": {"app_name": "微信"}},
                {"instruction": "等待加载", "action": "screenshot", "params": {}},
                {"instruction": "输入消息", "action": "type_text", "params": {"text": "你好"}},
            ],
            target_device="android_001",
        )

        result = await runtime.execute(manifest.to_dict())

        print(f"  成功: {result.success}")
        print(f"  总步骤: {result.total_steps}")
        print(f"  耗时: {result.duration_ms:.1f}ms")
        print(f"  执行的工具: {[t['tool'] for t in executed_tools]}")
        print(f"  上报的步骤: {len(reported_steps)}")

        assert result.success, "顺序执行应该成功"
        assert result.total_steps == 3, f"应该有 3 步, 实际 {result.total_steps}"
        assert len(executed_tools) == 3, f"应该执行 3 个工具, 实际 {len(executed_tools)}"
        assert executed_tools[0]["tool"] == "open_app"
        assert executed_tools[1]["tool"] == "screenshot"
        assert executed_tools[2]["tool"] == "type_text"
        assert len(reported_steps) > 0, "应该有状态上报"

        print("  ✅ 顺序执行模式正确")

    asyncio.get_event_loop().run_until_complete(_test())


def test_4_react_execution():
    """测试 LocalAgentRuntime ReAct 执行模式"""
    print("\n[测试 4] LocalAgentRuntime ReAct 执行")

    async def _test():
        from core.local_agent_runtime import LocalAgentRuntime
        from core.agent_manifest import AgentManifest

        executed_tools = []
        reported_steps = []
        llm_call_count = 0

        async def mock_tool_executor(tool_name, params):
            executed_tools.append({"tool": tool_name, "params": params})
            if tool_name == "screenshot":
                return {"success": True, "image": "base64_screenshot_data"}
            return {"success": True, "result": f"{tool_name} executed"}

        async def mock_status_reporter(manifest_id, step):
            reported_steps.append(step)

        async def mock_llm_chat(messages, tools):
            nonlocal llm_call_count
            llm_call_count += 1

            if llm_call_count == 1:
                # 第一轮: LLM 决定先截图
                return {
                    "content": "Let me first take a screenshot to see the current screen.",
                    "tool_calls": [{"name": "screenshot", "arguments": {}}],
                }
            elif llm_call_count == 2:
                # 第二轮: 看到截图后决定打开微信
                return {
                    "content": "I can see the home screen. Now opening WeChat.",
                    "tool_calls": [{"name": "open_app", "arguments": {"app_name": "微信"}}],
                }
            else:
                # 第三轮: 完成
                return {
                    "content": "微信已成功打开。任务完成。",
                    "tool_calls": None,
                }

        runtime = LocalAgentRuntime(
            tool_executor=mock_tool_executor,
            status_reporter=mock_status_reporter,
            llm_chat=mock_llm_chat,
        )

        manifest = AgentManifest.create_device_control_agent(
            target_device="android_001",
            instruction="打开微信",
        )

        result = await runtime.execute(manifest.to_dict())

        print(f"  成功: {result.success}")
        print(f"  总步骤: {result.total_steps}")
        print(f"  LLM 调用: {llm_call_count}")
        print(f"  工具调用: {[t['tool'] for t in executed_tools]}")
        print(f"  最终输出: {result.final_output[:80]}")

        assert result.success, "ReAct 执行应该成功"
        assert llm_call_count == 3, f"LLM 应该调用 3 次, 实际 {llm_call_count}"
        assert len(executed_tools) == 2, f"应该执行 2 个工具, 实际 {len(executed_tools)}"
        assert executed_tools[0]["tool"] == "screenshot"
        assert executed_tools[1]["tool"] == "open_app"
        assert "微信" in result.final_output

        print("  ✅ ReAct 执行模式正确")

    asyncio.get_event_loop().run_until_complete(_test())


def test_5_full_migration_e2e():
    """完整端到端迁移测试: 服务端打包 → 传输 → 端侧执行 → 结果回传"""
    print("\n[测试 5] 完整 Agent 迁移 E2E")

    async def _test():
        from core.agent_manifest import AgentManifest
        from core.local_agent_runtime import LocalAgentRuntime

        # ── 服务端: 创建 Manifest ──
        print("  [服务端] 创建 AgentManifest...")
        manifest = AgentManifest.create_device_control_agent(
            target_device="android_001",
            instruction="截图当前屏幕, 然后打开设置应用",
        )

        # ── 服务端: 序列化 + 封装 WS 消息 ──
        ws_message = {
            "type": "agent_deploy",
            "manifest": manifest.to_dict(),
            "checksum": manifest.checksum(),
        }
        wire_data = json.dumps(ws_message, ensure_ascii=False)
        print(f"  [服务端] 封装完成, 数据量: {len(wire_data)} bytes")

        # ── 模拟网络传输 ──
        received = json.loads(wire_data)

        # ── 端侧: 校验 + 反序列化 ──
        print("  [端侧] 接收到 agent_deploy 消息")
        received_manifest = AgentManifest.from_dict(received["manifest"])
        assert received_manifest.checksum() == received["checksum"], "校验和不匹配!"
        print(f"  [端侧] 校验通过, Agent: {received_manifest.agent_name}")

        # ── 端侧: 发送 ACK ──
        ack_message = {
            "type": "agent_deploy_ack",
            "manifest_id": received_manifest.manifest_id,
            "status": "accepted",
        }
        print(f"  [端侧] 发送 ACK: {ack_message['type']}")

        # ── 端侧: 在 LocalAgentRuntime 中执行 ──
        execution_log = []

        async def device_tool_executor(tool_name, params):
            log_entry = {"tool": tool_name, "params": params, "timestamp": time.time()}
            execution_log.append(log_entry)
            return {"success": True, "device": "android_001", "tool": tool_name}

        status_reports = []

        async def report_back(manifest_id, step):
            status_reports.append({
                "type": "agent_status",
                "manifest_id": manifest_id,
                "step": step,
            })

        llm_turn = 0

        async def mock_llm(messages, tools):
            nonlocal llm_turn
            llm_turn += 1
            if llm_turn == 1:
                return {
                    "content": "First, I'll take a screenshot.",
                    "tool_calls": [{"name": "screenshot", "arguments": "{}"}],
                }
            elif llm_turn == 2:
                return {
                    "content": "Now opening Settings app.",
                    "tool_calls": [{"name": "open_app", "arguments": json.dumps({"app_name": "Settings"})}],
                }
            else:
                return {
                    "content": "Done! Screenshot taken and Settings app opened successfully.",
                    "tool_calls": None,
                }

        runtime = LocalAgentRuntime(
            tool_executor=device_tool_executor,
            status_reporter=report_back,
            llm_chat=mock_llm,
        )

        print("  [端侧] 启动 LocalAgentRuntime...")
        result = await runtime.execute(received_manifest.to_dict())

        # ── 端侧: 发送结果 ──
        result_message = {
            "type": "agent_result",
            "manifest_id": received_manifest.manifest_id,
            "result": result.to_dict(),
        }
        print(f"  [端侧] 执行完成, 发送结果回服务端")

        # ── 验证 ──
        print(f"\n  === 验证 ===")
        print(f"  Manifest ID 一致: {manifest.manifest_id == received_manifest.manifest_id}")
        print(f"  执行成功: {result.success}")
        print(f"  总步骤: {result.total_steps}")
        print(f"  工具调用: {[e['tool'] for e in execution_log]}")
        print(f"  状态上报: {len(status_reports)} 条")
        print(f"  最终输出: {result.final_output[:100]}")
        print(f"  耗时: {result.duration_ms:.1f}ms")

        assert manifest.manifest_id == received_manifest.manifest_id
        assert result.success
        assert result.total_steps >= 2
        assert len(execution_log) == 2
        assert execution_log[0]["tool"] == "screenshot"
        assert execution_log[1]["tool"] == "open_app"
        assert len(status_reports) > 0
        assert result_message["type"] == "agent_result"

        print("\n  ✅ 完整 E2E 迁移验证通过!")
        print("     服务端打包 → WS传输 → 端侧校验 → ACK → ReAct执行 → 状态上报 → 结果回传")

    asyncio.get_event_loop().run_until_complete(_test())


def test_6_aip_protocol_types():
    """验证 AIP v3 协议 Agent 消息类型（已从 v2 迁移到 v3 MessageType）"""
    print("\n[测试 6] AIP v3 协议 Agent 消息类型")

    from galaxy_gateway.protocol.aip_v3 import MessageType

    required_types = ["agent_deploy", "agent_deploy_ack", "agent_status", "agent_result"]

    all_types = [t.value for t in MessageType]
    for rt in required_types:
        assert rt in all_types, f"缺少消息类型: {rt}"
        print(f"  ✅ {rt}")

    print("  ✅ AIP v3 协议 Agent 消息类型完整")


if __name__ == "__main__":
    print("=" * 60)
    print("Agent 迁移闭环测试 — Phase 1 Matrix OS")
    print("=" * 60)

    results = {"passed": 0, "failed": 0}

    tests = [
        test_1_manifest_serialization,
        test_2_ws_transport_simulation,
        test_3_sequential_execution,
        test_4_react_execution,
        test_5_full_migration_e2e,
        test_6_aip_protocol_types,
    ]

    for test in tests:
        try:
            test()
            results["passed"] += 1
        except Exception as e:
            print(f"  ❌ FAILED: {e}")
            import traceback
            traceback.print_exc()
            results["failed"] += 1

    print("\n" + "=" * 60)
    print(f"结果: {results['passed']}/{results['passed'] + results['failed']} 通过")
    print("=" * 60)

    sys.exit(0 if results["failed"] == 0 else 1)
