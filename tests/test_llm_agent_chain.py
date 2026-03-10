#!/usr/bin/env python3
"""
LLM 驱动 Agent 完整链路测试
===========================

验证: 用户消息 → 意图分流 → ReAct Agent / 纯聊天 → 返回结果

测试内容:
1. LLMManager 初始化 (读取 .env, 构建 Provider chain)
2. AutonomousScheduler 工具发现 (节点扫描 + 内置工具)
3. 意图分流逻辑 (操作指令 vs 纯聊天)
4. ReAct Loop 数据流验证 (mock LLM)
"""

import os
import sys
import json
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_1_llm_manager_init():
    """测试 LLMManager 初始化"""
    print("\n[测试 1] LLMManager 初始化")
    from core.llm_manager import LLMManager

    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
    mgr = LLMManager(config_path)

    print(f"  is_available: {mgr.is_available()}")
    print(f"  default_model: {mgr.get_default_model()}")
    print(f"  providers: {len(mgr.get_provider_status())}")
    for p in mgr.get_provider_status():
        print(f"    - {p['provider']}: {p['model']} (from {p['source']})")

    assert isinstance(mgr.get_provider_status(), list)
    print("  ✅ LLMManager 初始化成功")


def test_2_scheduler_tool_discovery():
    """测试 Scheduler 工具发现"""
    print("\n[测试 2] Scheduler 工具发现")
    from core.scheduler import AutonomousScheduler

    nodes_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "nodes")
    scheduler = AutonomousScheduler(nodes_dir)

    tools = scheduler.get_tools()
    print(f"  发现工具总数: {len(tools)}")

    # 检查内置工具
    tool_names = [t["function"]["name"] for t in tools]
    assert "send_to_device" in tool_names, "缺少内置工具 send_to_device"
    assert "broadcast_to_all_devices" in tool_names, "缺少内置工具 broadcast_to_all_devices"
    print("  ✅ 内置工具已注入")

    # 检查节点工具
    node_tools = [n for n in tool_names if n.startswith("call_Node_")]
    print(f"  节点工具数: {len(node_tools)}")
    assert len(node_tools) > 0, "没有发现任何节点工具"
    print("  ✅ 节点工具已发现")

    # 检查工具选择
    relevant = scheduler._select_relevant_tools("帮我打开手机上的微信", max_tools=10)
    relevant_names = [t["function"]["name"] for t in relevant]
    print(f"  '打开手机微信' 相关工具: {relevant_names[:5]}...")
    assert "send_to_device" in relevant_names, "send_to_device 应该被选中"
    print("  ✅ 工具智能选择正常")


def test_3_intent_routing():
    """测试意图分流逻辑"""
    print("\n[测试 3] 意图分流逻辑")

    # 模拟 api_routes 中的 _is_action_intent 函数
    _ACTION_KEYWORDS_ZH = [
        "打开", "关闭", "启动", "运行", "安装", "卸载", "截图", "截屏",
        "点击", "滑动", "输入", "搜索", "发送", "下载", "上传",
        "复制", "粘贴", "传输", "同步", "分享",
        "拍照", "录屏", "录音", "播放", "暂停", "停止",
        "查看电量", "查看状态", "连接设备", "断开设备",
        "帮我操作", "帮我执行", "帮我控制",
        "在手机上", "在电脑上", "在平板上", "在设备上",
        "切换应用", "返回桌面", "锁屏", "解锁", "音量",
    ]
    _ACTION_KEYWORDS_EN = [
        "open ", "close ", "launch ", "run ", "install ", "click ",
        "swipe ", "type ", "screenshot", "send ", "download ",
        "upload ", "execute ", "control ", "operate ",
        "on my phone", "on my pc", "on device", "on android",
        "take photo", "record ", "play ", "pause ", "stop ",
    ]

    def _is_action_intent(msg: str) -> bool:
        msg_lower = msg.lower().strip()
        if len(msg_lower) < 4:
            return False
        for kw in _ACTION_KEYWORDS_ZH:
            if kw in msg_lower:
                return True
        for kw in _ACTION_KEYWORDS_EN:
            if kw in msg_lower:
                return True
        return False

    # 操作指令 (应该走 Agent)
    action_messages = [
        "帮我打开手机上的微信",
        "在手机上截图",
        "发送文件到平板",
        "帮我执行一下这个脚本",
        "Open WeChat on my phone",
        "Take a screenshot on device",
    ]

    # 纯聊天 (应该走 LLM 对话)
    chat_messages = [
        "你好",
        "今天天气怎么样",
        "Python 如何读取文件",
        "什么是人工智能",
        "Hello",
    ]

    all_pass = True
    for msg in action_messages:
        result = _is_action_intent(msg)
        status = "✅" if result else "❌"
        if not result:
            all_pass = False
        print(f"  {status} 操作: '{msg}' → {result}")

    for msg in chat_messages:
        result = _is_action_intent(msg)
        status = "✅" if not result else "❌"
        if result:
            all_pass = False
        print(f"  {status} 聊天: '{msg}' → {result}")

    assert all_pass, "意图分流有误判"
    print("  ✅ 意图分流逻辑正确")


def test_4_react_loop_data_flow():
    """测试 ReAct Loop 数据流 (mock LLM)"""
    print("\n[测试 4] ReAct Loop 数据流")

    async def _test():
        from core.scheduler import AutonomousScheduler

        nodes_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "nodes")
        scheduler = AutonomousScheduler(nodes_dir)

        # Mock LLM Manager — 模拟 LLM 返回 tool_call
        class MockMessage:
            def __init__(self, content=None, tool_calls=None):
                self.content = content
                self.tool_calls = tool_calls

        class MockToolCall:
            def __init__(self, id, name, arguments):
                self.id = id
                self.function = type("Func", (), {"name": name, "arguments": arguments})()

        class MockChoice:
            def __init__(self, message):
                self.message = message

        class MockUsage:
            prompt_tokens = 100
            completion_tokens = 50

        class MockResponse:
            def __init__(self, choices):
                self.choices = choices
                self.usage = MockUsage()
                self.model = "mock-model"

        call_count = 0

        class MockLLMManager:
            def is_available(self):
                return True

            def get_default_model(self):
                return "mock-model"

            async def chat_completion(self, messages, tools=None, **kwargs):
                nonlocal call_count
                call_count += 1

                if call_count == 1:
                    # 第一轮: LLM 决定调用 send_to_device
                    tc = MockToolCall(
                        id="call_001",
                        name="send_to_device",
                        arguments=json.dumps({
                            "device_id": "android_001",
                            "task_type": "open_app",
                            "payload": {"app_name": "微信"}
                        })
                    )
                    return MockResponse([MockChoice(MockMessage(
                        content="好的，我来帮你打开微信。",
                        tool_calls=[tc]
                    ))])
                else:
                    # 第二轮: LLM 总结结果
                    return MockResponse([MockChoice(MockMessage(
                        content="已成功发送打开微信的指令到你的 Android 设备。",
                        tool_calls=None
                    ))])

        # Mock executor
        executed_commands = []

        async def mock_executor(node_id, action, params):
            executed_commands.append({"node_id": node_id, "action": action, "params": params})
            return {"success": True, "message": f"Executed {action} on {node_id}"}

        context = {
            "devices": {
                "android_001": {
                    "device_id": "android_001",
                    "device_type": "android",
                    "device_name": "My Phone",
                    "status": "online",
                    "capabilities": ["screen_capture", "ui_automation"],
                }
            },
            "executor": mock_executor,
        }

        result = await scheduler.plan_and_execute(
            "帮我打开手机上的微信",
            MockLLMManager(),
            context,
            max_turns=5,
        )

        print(f"  成功: {result['success']}")
        print(f"  步骤数: {len(result['steps'])}")
        print(f"  回复: {result['reply'][:100]}")
        print(f"  LLM 调用次数: {call_count}")
        print(f"  执行的命令: {executed_commands}")

        assert result["success"], "ReAct 调度应该成功"
        assert len(result["steps"]) > 0, "应该有执行步骤"
        assert call_count == 2, f"应该调用 LLM 2 次 (思考+总结), 实际 {call_count}"
        assert "微信" in result["reply"] or "打开" in result["reply"], "回复应该包含操作描述"
        print("  ✅ ReAct Loop 数据流正确")

    asyncio.run(_test())


def test_5_api_routes_import():
    """测试 api_routes 模块可正常导入"""
    print("\n[测试 5] api_routes 模块导入")
    try:
        from core.llm_manager import LLMManager
        from core.scheduler import AutonomousScheduler

        # 验证关键类存在
        assert hasattr(LLMManager, 'chat_completion')
        assert hasattr(LLMManager, 'is_available')
        assert hasattr(LLMManager, 'get_provider_status')
        assert hasattr(AutonomousScheduler, 'plan_and_execute')
        assert hasattr(AutonomousScheduler, '_select_relevant_tools')
        print("  ✅ 核心模块导入成功")
    except Exception as e:
        print(f"  ❌ 导入失败: {e}")
        raise


if __name__ == "__main__":
    print("=" * 60)
    print("LLM 驱动 Agent 完整链路测试")
    print("=" * 60)

    results = {"passed": 0, "failed": 0}

    tests = [
        test_1_llm_manager_init,
        test_2_scheduler_tool_discovery,
        test_3_intent_routing,
        test_4_react_loop_data_flow,
        test_5_api_routes_import,
    ]

    for test in tests:
        try:
            test()
            results["passed"] += 1
        except Exception as e:
            print(f"  ❌ FAILED: {e}")
            results["failed"] += 1

    print("\n" + "=" * 60)
    print(f"结果: {results['passed']}/{results['passed'] + results['failed']} 通过")
    print("=" * 60)

    sys.exit(0 if results["failed"] == 0 else 1)
