"""
Phase 2/3/4 综合测试
====================

测试覆盖:
1. ProxyRelay: 设备间中继转发
2. HybridExecutionArbiter: A2A → GUI → VLM 降级链
3. RAGMemory: 经验记录/检索/Pattern检测
4. SafeExecutor: 安全代码执行 + 安全检查
5. AIP v2 协议扩展消息类型
6. Scheduler 新增工具集成
7. E2E: Agent ReAct + RAG + SafeExecutor 联动
"""

import asyncio
import json
import os
import sys
import time
import tempfile
import shutil
import pytest

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ============================================================================
# Test 1: ProxyRelay 基础中继
# ============================================================================

@pytest.mark.asyncio
async def test_1_proxy_relay_basic():
    """测试 ProxyRelay 基础中继功能"""
    from core.proxy_relay import ProxyRelay, RelayRequest, RelayStatus

    # 模拟 WS sender
    sent_messages = []

    async def mock_sender(device_id: str, message: dict) -> bool:
        sent_messages.append({"device_id": device_id, "message": message})
        return True

    relay = ProxyRelay(
        device_sender=mock_sender,
        get_online_devices=lambda: ["device_a", "device_b", "device_c"],
    )

    # 基础中继 (无需回复)
    req = RelayRequest(
        source_device="device_a",
        target_device="device_b",
        payload_type="task",
        payload={"task_type": "open_app", "app_name": "WeChat"},
        expect_reply=False,
    )
    result = await relay.relay(req)

    assert result.status == RelayStatus.FORWARDED
    assert len(sent_messages) == 1
    assert sent_messages[0]["device_id"] == "device_b"
    assert sent_messages[0]["message"]["type"] == "relay_forward"
    assert sent_messages[0]["message"]["source_device"] == "device_a"

    # 统计
    stats = relay.get_stats()
    assert stats["total"] == 1
    assert stats["success"] == 1

    print("✓ Test 1: ProxyRelay basic relay passed")


# ============================================================================
# Test 2: ProxyRelay 带回复的中继
# ============================================================================

@pytest.mark.asyncio
async def test_2_proxy_relay_with_reply():
    """测试 ProxyRelay 带回复的中继"""
    from core.proxy_relay import ProxyRelay, RelayRequest, RelayStatus

    async def mock_sender(device_id: str, message: dict) -> bool:
        return True

    relay = ProxyRelay(device_sender=mock_sender)

    # 发起带回复的中继
    req = RelayRequest(
        source_device="device_a",
        target_device="device_b",
        payload_type="command",
        payload={"command": "get_battery"},
        expect_reply=True,
        timeout_seconds=2.0,
    )

    # 在后台模拟回复
    async def simulate_reply():
        await asyncio.sleep(0.3)
        await relay.handle_relay_reply(
            req.relay_id, {"battery": 85, "charging": True}
        )

    asyncio.create_task(simulate_reply())
    result = await relay.relay(req)

    assert result.status == RelayStatus.REPLIED
    assert result.reply_payload["battery"] == 85

    print("✓ Test 2: ProxyRelay with reply passed")


# ============================================================================
# Test 3: ProxyRelay 广播
# ============================================================================

@pytest.mark.asyncio
async def test_3_proxy_relay_broadcast():
    """测试 ProxyRelay 广播"""
    from core.proxy_relay import ProxyRelay

    sent_to = []

    async def mock_sender(device_id: str, message: dict) -> bool:
        sent_to.append(device_id)
        return True

    relay = ProxyRelay(
        device_sender=mock_sender,
        get_online_devices=lambda: ["device_a", "device_b", "device_c"],
    )

    results = await relay.relay_broadcast(
        source_device="device_a",
        payload_type="task",
        payload={"task_type": "screenshot"},
    )

    assert len(results) == 2  # b and c (not a)
    assert "device_b" in results
    assert "device_c" in results
    assert "device_a" not in results

    print("✓ Test 3: ProxyRelay broadcast passed")


# ============================================================================
# Test 4: HybridExecutionArbiter 降级链
# ============================================================================

@pytest.mark.asyncio
async def test_4_hybrid_arbiter_degradation():
    """测试 Hybrid Execution Arbiter 降级链"""
    from core.hybrid_executor import (
        HybridExecutionArbiter, ExecutionLevel, ExecutionStatus,
    )

    call_log = []

    # A2A 执行器 — 模拟失败
    async def mock_a2a(app_id, action, params, device_id):
        call_log.append(("a2a", app_id, action))
        return {"success": False, "error": "No A2A API available"}

    # GUI 执行器 — 模拟成功
    async def mock_gui(device_id, action, params):
        call_log.append(("gui", device_id, action))
        return {"success": True, "action": action, "via": "gui_automation"}

    # VLM 执行器 — 不应被调用
    async def mock_vlm(device_id, instruction, screenshot):
        call_log.append(("vlm", device_id, instruction))
        return {"success": True, "via": "vlm"}

    arbiter = HybridExecutionArbiter(
        a2a_executor=mock_a2a,
        gui_executor=mock_gui,
        vlm_executor=mock_vlm,
    )

    result = await arbiter.execute(
        device_id="phone_1",
        app_id="com.tencent.mm",
        action="send_message",
        params={"text": "hello"},
    )

    # A2A 失败 → GUI 成功
    assert result.success is True
    assert result.final_level == ExecutionLevel.GUI
    assert len(result.attempts) == 2  # A2A(fail) + GUI(success)
    assert call_log[0][0] == "a2a"
    assert call_log[1][0] == "gui"

    # 统计
    stats = arbiter.get_stats()
    assert stats["gui_success"] == 1
    assert stats["all_failed"] == 0

    print("✓ Test 4: HybridExecutionArbiter degradation chain passed")


# ============================================================================
# Test 5: HybridExecutionArbiter 强制级别
# ============================================================================

@pytest.mark.asyncio
async def test_5_hybrid_force_level():
    """测试强制指定执行级别"""
    from core.hybrid_executor import (
        HybridExecutionArbiter, ExecutionLevel,
    )

    async def mock_vlm(device_id, instruction, screenshot):
        return {"success": True, "via": "vlm", "instruction": instruction}

    arbiter = HybridExecutionArbiter(vlm_executor=mock_vlm)

    result = await arbiter.execute(
        device_id="phone_1",
        app_id="any_app",
        action="complex_task",
        instruction="Find the search bar and type hello",
        force_level=ExecutionLevel.VLM,
    )

    assert result.success is True
    assert result.final_level == ExecutionLevel.VLM
    assert len(result.attempts) == 1  # VLM only

    print("✓ Test 5: Hybrid force level passed")


# ============================================================================
# Test 6: RAGMemory 经验记录与检索
# ============================================================================

def test_6_rag_memory_experience():
    """测试 RAG 经验记录与检索"""
    from core.rag_memory import RAGMemory

    # 使用临时目录
    tmp_dir = tempfile.mkdtemp()
    try:
        rag = RAGMemory(data_dir=tmp_dir)

        # 记录经验
        rag.log_experience(
            agent_name="test_agent",
            instruction="打开微信发送消息",
            steps=[
                {"thought": "Need to open WeChat", "action": "open_app", "observation": "App opened"},
                {"thought": "Send message", "action": "type_text", "observation": "Message sent"},
            ],
            final_output="Successfully sent message via WeChat",
            success=True,
            device_id="phone_1",
            tags=["wechat", "message"],
        )

        rag.log_experience(
            agent_name="test_agent",
            instruction="打开浏览器搜索天气",
            steps=[
                {"thought": "Open browser", "action": "open_app", "observation": "Chrome opened"},
            ],
            final_output="Weather search completed",
            success=True,
        )

        # 检索相似经验
        similar = rag.recall_similar("打开微信发消息给朋友", top_k=2)
        assert len(similar) > 0
        assert "微信" in similar[0].instruction

        # Few-shot context
        ctx = rag.format_few_shot_context("帮我打开微信")
        assert "Past Experience" in ctx

        # 统计
        stats = rag.get_stats()
        assert stats["experiences_total"] == 2

        # 持久化验证
        rag2 = RAGMemory(data_dir=tmp_dir)
        assert len(rag2._experiences) == 2

        print("✓ Test 6: RAGMemory experience log/recall passed")
    finally:
        shutil.rmtree(tmp_dir)


# ============================================================================
# Test 7: RAGMemory Pattern 检测
# ============================================================================

def test_7_rag_pattern_detection():
    """测试 RAG Pattern 检测"""
    from core.rag_memory import RAGMemory

    tmp_dir = tempfile.mkdtemp()
    try:
        rag = RAGMemory(data_dir=tmp_dir)

        # 记录 5 次相似指令 (触发 pattern)
        for i in range(5):
            rag.log_experience(
                agent_name="scheduler",
                instruction=f"打开微信 然后发送消息给用户{i}",
                steps=[{"action": "open_app"}, {"action": "type_text"}],
                final_output="done",
                success=True,
            )

        patterns = rag.get_learned_patterns()
        assert len(patterns) >= 1
        assert "打开" in patterns[0].get("prefix", "")
        assert patterns[0]["count"] >= 3

        print("✓ Test 7: RAGMemory pattern detection passed")
    finally:
        shutil.rmtree(tmp_dir)


# ============================================================================
# Test 8: SafeExecutor 安全检查
# ============================================================================

def test_8_safe_executor_security():
    """测试 SafeExecutor 安全检查"""
    from core.safe_executor import check_code_safety

    # 安全代码
    assert check_code_safety("print('hello')", "python") is None
    assert check_code_safety("console.log('hi')", "javascript") is None
    assert check_code_safety("echo hello", "bash") is None

    # 危险代码
    assert check_code_safety("os.system('rm -rf /')", "python") is not None
    assert check_code_safety("import subprocess; subprocess.call(['ls'])", "python") is not None
    assert check_code_safety("rm -rf /", "bash") is not None
    assert check_code_safety("dd if=/dev/zero of=/dev/sda", "bash") is not None
    assert check_code_safety("require('child_process')", "javascript") is not None

    print("✓ Test 8: SafeExecutor security check passed")


# ============================================================================
# Test 9: SafeExecutor 代码执行
# ============================================================================

@pytest.mark.asyncio
async def test_9_safe_executor_run():
    """测试 SafeExecutor 安全代码执行"""
    from core.safe_executor import SafeExecutor

    executor = SafeExecutor()

    # Python 执行
    result = await executor.execute("print(2 + 3)", "python")
    assert result.success is True
    assert "5" in result.stdout

    # 安全违规阻止
    result = await executor.execute("import subprocess; subprocess.run(['ls'])", "python")
    assert result.success is False
    assert result.safety_check_passed is False

    # Bash 执行
    result = await executor.execute("echo 'hello world'", "bash")
    assert result.success is True
    assert "hello world" in result.stdout

    # 不允许的语言
    result = await executor.execute("fn main() {}", "rust")
    assert result.success is False

    # 统计
    stats = executor.get_stats()
    assert stats["total"] == 4
    assert stats["blocked"] >= 2  # security + language
    assert stats["success"] >= 1

    print("✓ Test 9: SafeExecutor code execution passed")


# ============================================================================
# Test 10: AIP v2 协议扩展
# ============================================================================

def test_10_aip_v2_extended_types():
    """测试 AIP v3 统一消息类型（之前的 v2 ExtendedMessageType 已合并进 v3 MessageType）"""
    from galaxy_gateway.protocol.aip_v3 import MessageType

    # Phase 1 types
    assert MessageType.AGENT_DEPLOY.value == "agent_deploy"
    assert MessageType.AGENT_RESULT.value == "agent_result"

    # Phase 2 types
    assert MessageType.RELAY_REQUEST.value == "relay_request"
    assert MessageType.RELAY_FORWARD.value == "relay_forward"
    assert MessageType.RELAY_REPLY.value == "relay_reply"
    assert MessageType.RELAY_ACK.value == "relay_ack"

    # Phase 3 types
    assert MessageType.HYBRID_EXECUTE.value == "hybrid_execute"
    assert MessageType.HYBRID_RESULT.value == "hybrid_result"
    assert MessageType.HYBRID_DEGRADE.value == "hybrid_degrade"

    # Phase 4 types
    assert MessageType.RAG_QUERY.value == "rag_query"
    assert MessageType.RAG_RESULT.value == "rag_result"
    assert MessageType.CODE_EXECUTE.value == "code_execute"

    print("✓ Test 10: AIP v3 unified message types passed")


# ============================================================================
# Test 11: Scheduler 新增工具
# ============================================================================

def test_11_scheduler_new_tools():
    """测试 Scheduler 新增 relay_to_device 和 execute_code 工具"""
    from core.scheduler import AutonomousScheduler

    nodes_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "nodes")
    scheduler = AutonomousScheduler(nodes_dir)
    tools = scheduler.get_tools()
    tool_names = [t["function"]["name"] for t in tools]

    assert "send_to_device" in tool_names
    assert "broadcast_to_all_devices" in tool_names
    assert "relay_to_device" in tool_names
    assert "execute_code" in tool_names

    print(f"✓ Test 11: Scheduler has {len(tools)} tools including relay + execute_code")


# ============================================================================
# Test 12: E2E — Agent ReAct + RAG + SafeExecutor
# ============================================================================

@pytest.mark.asyncio
async def test_12_e2e_rag_safe_executor():
    """E2E: Agent 使用 RAG 增强 + SafeExecutor"""
    from core.rag_memory import RAGMemory
    from core.safe_executor import SafeExecutor

    tmp_dir = tempfile.mkdtemp()
    try:
        # 1. 建立经验库
        rag = RAGMemory(data_dir=tmp_dir)
        rag.log_experience(
            agent_name="math_agent",
            instruction="计算 fibonacci 数列第 10 项",
            steps=[
                {"thought": "Need to compute fibonacci", "action": "execute_code",
                 "observation": "55"},
            ],
            final_output="fibonacci(10) = 55",
            success=True,
        )

        # 2. RAG 增强: 检索相似经验
        context = await rag.enhance_agent_prompt("计算 fibonacci 第 20 项")
        assert "Past Experience" in context
        assert "fibonacci" in context.lower()

        # 3. SafeExecutor: 实际执行代码
        executor = SafeExecutor()
        code = """
def fib(n):
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a

print(fib(20))
"""
        result = await executor.execute(code, "python")
        assert result.success is True
        assert "6765" in result.stdout

        # 4. 记录新经验
        rag.log_experience(
            agent_name="math_agent",
            instruction="计算 fibonacci 第 20 项",
            steps=[{"thought": "Execute fib code", "action": "execute_code",
                     "observation": result.stdout.strip()}],
            final_output=f"fibonacci(20) = {result.stdout.strip()}",
            success=True,
        )

        # 5. 验证经验累积
        assert len(rag._experiences) == 2
        stats = rag.get_stats()
        assert stats["experiences_total"] == 2

        print("✓ Test 12: E2E Agent + RAG + SafeExecutor passed")
    finally:
        shutil.rmtree(tmp_dir)


# ============================================================================
# Test 13: CapabilityRegistry
# ============================================================================

def test_13_capability_registry():
    """测试应用能力注册表"""
    from core.hybrid_executor import CapabilityRegistry, ExecutionLevel, AppCapability

    registry = CapabilityRegistry()

    # 默认注册的应用
    apps = registry.list_apps()
    assert len(apps) >= 3

    # shell 应有 A2A 首选
    levels = registry.get_preferred_levels("system_shell")
    assert levels[0] == ExecutionLevel.A2A

    # 未注册的应用使用默认三级链
    levels = registry.get_preferred_levels("com.unknown.app")
    assert levels == [ExecutionLevel.A2A, ExecutionLevel.GUI, ExecutionLevel.VLM]

    # 注册新应用
    registry.register(AppCapability(
        app_id="com.custom.app",
        a2a_endpoint="http://localhost:9999",
        a2a_actions=["do_thing"],
    ))
    assert registry.get("com.custom.app") is not None
    levels = registry.get_preferred_levels("com.custom.app")
    assert ExecutionLevel.A2A in levels

    print("✓ Test 13: CapabilityRegistry passed")


# ============================================================================
# Test 14: ProxyRelay 链式转发
# ============================================================================

@pytest.mark.asyncio
async def test_14_proxy_relay_chain():
    """测试链式转发 A → B → C"""
    from core.proxy_relay import ProxyRelay, RelayRequest, RelayStatus

    chain_log = []

    async def mock_sender(device_id: str, message: dict) -> bool:
        chain_log.append(device_id)
        return True

    relay = ProxyRelay(device_sender=mock_sender)

    req = RelayRequest(
        source_device="device_a",
        target_device="device_b",
        payload_type="task",
        payload={"task": "sync_file"},
        chain=["device_c"],
        expect_reply=False,
    )
    result = await relay.relay(req)

    # 应该先发给 B, 再发给 C
    assert result.status == RelayStatus.FORWARDED
    assert "device_b" in chain_log
    assert "device_c" in chain_log

    print("✓ Test 14: ProxyRelay chain relay passed")


# ============================================================================
# Test 15: 模块导入完整性
# ============================================================================

def test_15_module_imports():
    """验证所有新模块可正常导入"""
    from core.proxy_relay import ProxyRelay, RelayRequest, RelayResult, get_proxy_relay
    from core.hybrid_executor import (
        HybridExecutionArbiter, ExecutionLevel, CapabilityRegistry, get_hybrid_arbiter,
    )
    from core.rag_memory import RAGMemory, ExperienceEntry, KnowledgeChunk, get_rag_memory
    from core.safe_executor import SafeExecutor, ExecutionResult, check_code_safety, get_safe_executor
    from galaxy_gateway.protocol.aip_v3 import MessageType  # v3-only source of truth

    # 单例可实例化
    assert get_proxy_relay() is not None
    assert get_hybrid_arbiter() is not None
    assert get_rag_memory() is not None
    assert get_safe_executor() is not None

    print("✓ Test 15: All module imports successful")
