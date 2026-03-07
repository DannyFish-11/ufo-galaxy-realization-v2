#!/usr/bin/env python3
"""
UFO Galaxy - 智能唤醒路由、事件总线、会话漫游、融合唤醒决策 单元测试
=======================================================================
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


# =============================================================================
# 1. WakeRouter 测试
# =============================================================================

async def test_wake_router_basic():
    """测试 WakeRouter 基本路由功能"""
    print("\n=== 测试 WakeRouter 基本路由 ===")
    from galaxy_gateway.wake_router import WakeRouter, WakeEvent, WakeTaskType

    router = WakeRouter()

    # 注入两个测试设备
    now = time.time()
    router.inject_device_info("phone_1", {
        "capabilities": ["screen", "speaker", "microphone"],
        "last_heartbeat": now - 5,
        "last_message": now - 5,
        "screen_on": True,
        "last_interaction": now - 3,
    })
    router.inject_device_info("tv_1", {
        "capabilities": ["screen", "speaker"],
        "last_heartbeat": now - 60,
        "last_message": now - 60,
        "screen_on": False,
        "last_interaction": 0,
    })

    event = WakeEvent(
        event_id="evt_001",
        source_device_id="phone_1",
        wake_word="hey ufo",
        task_type=WakeTaskType.VOICE,
    )
    decision = await router.route(event)

    assert decision is not None, "应该返回路由决策"
    # phone_1 更活跃（心跳更近、屏幕亮），应被选中
    assert decision.selected_device_id == "phone_1", (
        f"期望 phone_1 被选中，实际选中 {decision.selected_device_id}"
    )
    print(f"  选中设备: {decision.selected_device_id} score={decision.score:.2f}")
    print("  ✅ WakeRouter 基本路由测试通过")
    return True


async def test_wake_router_dedup():
    """测试 WakeRouter 唤醒事件去重"""
    print("\n=== 测试 WakeRouter 去重 ===")
    from galaxy_gateway.wake_router import WakeRouter, WakeEvent, WakeTaskType

    router = WakeRouter()
    now = time.time()
    router.inject_device_info("dev_a", {
        "capabilities": ["speaker"],
        "last_heartbeat": now - 1,
        "last_message": now - 1,
        "screen_on": True,
        "last_interaction": now - 1,
    })

    evt1 = WakeEvent(event_id="dup_001", source_device_id="dev_a", wake_word="hey ufo")
    evt2 = WakeEvent(event_id="dup_002", source_device_id="dev_b", wake_word="hey ufo",
                     timestamp=now + 0.2)  # 200ms 后的相同唤醒词

    d1 = await router.route(evt1)
    d2 = await router.route(evt2)

    assert d1 is not None, "第一个事件应有路由决策"
    assert d2 is None, "200ms 内相同唤醒词应被去重"
    print("  ✅ WakeRouter 去重测试通过")
    return True


async def test_wake_router_capability_match():
    """测试 WakeRouter 能力匹配评分"""
    print("\n=== 测试 WakeRouter 能力匹配 ===")
    from galaxy_gateway.wake_router import WakeRouter, WakeEvent, WakeTaskType

    router = WakeRouter()
    now = time.time()
    # 两个设备活跃度相同，但能力不同
    router.inject_device_info("speaker_device", {
        "capabilities": ["speaker"],
        "last_heartbeat": now - 1,
        "last_message": now - 1,
        "screen_on": False,
        "last_interaction": 0,
    })
    router.inject_device_info("screen_device", {
        "capabilities": ["screen"],
        "last_heartbeat": now - 1,
        "last_message": now - 1,
        "screen_on": False,
        "last_interaction": 0,
    })

    voice_event = WakeEvent(
        event_id="cap_001",
        source_device_id="screen_device",
        wake_word="hey ufo",
        task_type=WakeTaskType.VOICE,
    )
    d = await router.route(voice_event)
    assert d is not None
    assert d.selected_device_id == "speaker_device", (
        f"语音任务应选 speaker_device，实际: {d.selected_device_id}"
    )
    print(f"  语音任务选中: {d.selected_device_id}")
    print("  ✅ WakeRouter 能力匹配测试通过")
    return True


# =============================================================================
# 2. WakeEventBus 测试
# =============================================================================

async def test_wake_event_bus_publish():
    """测试 WakeEventBus 事件发布与去重"""
    print("\n=== 测试 WakeEventBus 发布与去重 ===")
    from galaxy_gateway.wake_event_bus import WakeEventBus, RawWakeEvent

    bus = WakeEventBus()
    dispatched = []

    async def mock_subscriber(evt):
        dispatched.append(evt)

    bus.subscribe(mock_subscriber)

    # 模拟 3 个设备在 300ms 内同时检测到同一唤醒词
    now = time.time()
    events = [
        RawWakeEvent("dev_1", "hey ufo", timestamp=now),
        RawWakeEvent("dev_2", "hey ufo", timestamp=now + 0.1),
        RawWakeEvent("dev_3", "hey ufo", timestamp=now + 0.2),
    ]
    results = []
    for e in events:
        r = await bus.publish(e)
        results.append(r)

    assert results[0] is True, "第一个事件应分发"
    assert results[1] is False, "第二个事件（100ms内）应去重"
    assert results[2] is False, "第三个事件（200ms内）应去重"

    stats = bus.get_stats()
    print(f"  统计: {stats}")
    assert stats["total_dispatched"] == 1
    assert stats["total_deduplicated"] == 2
    print("  ✅ WakeEventBus 发布与去重测试通过")
    return True


async def test_wake_event_bus_websocket_message():
    """测试 WakeEventBus 处理 WebSocket WAKE_EVENT 消息"""
    print("\n=== 测试 WakeEventBus WebSocket 消息解析 ===")
    from galaxy_gateway.wake_event_bus import WakeEventBus

    bus = WakeEventBus()
    received = []
    bus.subscribe(lambda e: received.append(e))

    msg = {
        "type": "WAKE_EVENT",
        "timestamp": time.time(),
        "payload": {
            "wake_word": "ok galaxy",
            "task_type": "general",
            "confidence": 0.9,
        },
    }
    ok = await bus.handle_websocket_message("android_001", msg)
    assert ok is True, "应识别为 WAKE_EVENT"

    # 非唤醒消息应忽略
    ok2 = await bus.handle_websocket_message("android_001", {"type": "heartbeat"})
    assert ok2 is False, "非 WAKE_EVENT 消息应返回 False"

    print("  ✅ WakeEventBus WebSocket 消息解析测试通过")
    return True


# =============================================================================
# 3. SessionRoaming 测试
# =============================================================================

async def test_session_roaming_create_and_migrate():
    """测试会话创建与迁移"""
    print("\n=== 测试 SessionRoaming 创建与迁移 ===")
    from galaxy_gateway.session_roaming import SessionRoamingManager, SessionState

    mgr = SessionRoamingManager()

    # 创建会话
    session = mgr.create_session("phone_1", wake_word="hey ufo")
    assert session.device_id == "phone_1"
    assert session.state == SessionState.ACTIVE
    print(f"  会话创建: session_id={session.session_id} device={session.device_id}")

    # 添加对话
    mgr.add_turn(session.session_id, "user", "帮我查天气")
    mgr.add_turn(session.session_id, "assistant", "北京今天晴天，气温 20℃")
    assert len(session.context.history) == 2

    # 注入一个 mock send_command（不依赖真实 WebSocket）
    send_calls = []

    async def mock_send(device_id, action, params, timeout=10.0):
        send_calls.append((device_id, action))
        return {"success": True}

    # 通过 patch session_roaming._push_context_to_device 避免导入 fastapi
    original_push = mgr._push_context_to_device

    async def mock_push(device_id, session_id, ctx):
        send_calls.append((device_id, "session_restore"))
        return True

    mgr._push_context_to_device = mock_push

    try:
        # 迁移到 laptop_1
        ok = await mgr.migrate_session(session.session_id, "laptop_1")
        assert ok, "迁移应成功"
        assert session.device_id == "laptop_1"
        assert session.state == SessionState.ACTIVE
        print(f"  迁移后设备: {session.device_id}")
        assert ("laptop_1", "session_restore") in send_calls, "应向目标设备发送 session_restore"
    finally:
        mgr._push_context_to_device = original_push

    print("  ✅ SessionRoaming 创建与迁移测试通过")
    return True


async def test_session_roaming_auto_migrate():
    """测试注意力焦点自动迁移"""
    print("\n=== 测试 SessionRoaming 自动迁移 ===")
    from galaxy_gateway.session_roaming import SessionRoamingManager, SessionState

    mgr = SessionRoamingManager()
    session = mgr.create_session("phone_1")

    # mock _push_context_to_device 避免依赖 fastapi
    async def mock_push(device_id, session_id, ctx):
        return True

    mgr._push_context_to_device = mock_push

    # 手机锁屏（失去焦点），电脑获得焦点
    await mgr.auto_migrate_on_attention_shift({"phone_1": False, "laptop_1": True})
    assert session.device_id == "laptop_1", (
        f"应迁移到 laptop_1，实际: {session.device_id}"
    )
    print(f"  自动迁移后设备: {session.device_id}")
    print("  ✅ SessionRoaming 自动迁移测试通过")
    return True


# =============================================================================
# 4. FusedWakeDecision 测试
# =============================================================================

async def test_fused_wake_decision_voice_motion():
    """测试语音+运动触发的高置信度融合"""
    print("\n=== 测试 FusedWakeDecision 语音+运动融合 ===")
    from system_integration.fused_wake_decision import FusedWakeDecision

    try:
        from system_integration.hardware_trigger import TriggerType, TriggerEvent, TriggerPriority, PlatformType
    except ImportError:
        print("  ⚠️ hardware_trigger 不可用，跳过 FusedWakeDecision 测试")
        return True

    fused = FusedWakeDecision(wake_threshold=0.65)
    results = []
    fused.set_wake_callback(lambda r: results.append(r))

    voice_event = TriggerEvent(
        trigger_type=TriggerType.VOICE,
        source="microphone",
        data={"wake_word": "hey ufo", "confidence": 0.9},
    )
    motion_event = TriggerEvent(
        trigger_type=TriggerType.MOTION,
        source="accelerometer",
        data={"motion_type": "pickup"},
    )

    # 先发语音事件，再发运动事件（同一时间窗口）
    r1 = await fused.process_event(voice_event)
    r2 = await fused.process_event(motion_event)

    # 第二个事件应触发融合决策
    assert r2 is not None, "融合决策应在收到第二个事件后产生"
    assert r2.should_wake is True, f"语音+运动应触发唤醒，confidence={r2.confidence:.2f}"
    assert r2.confidence >= 0.9, f"置信度应 >= 0.9，实际 {r2.confidence:.2f}"
    print(f"  confidence={r2.confidence:.2f} rule='{r2.matched_rule}'")
    print("  ✅ FusedWakeDecision 语音+运动融合测试通过")
    return True


async def test_fused_wake_decision_voice_only_threshold():
    """测试仅语音触发时中等置信度，阈值高时不唤醒"""
    print("\n=== 测试 FusedWakeDecision 仅语音（阈值控制）===")
    from system_integration.fused_wake_decision import FusedWakeDecision

    try:
        from system_integration.hardware_trigger import TriggerType, TriggerEvent
    except ImportError:
        print("  ⚠️ hardware_trigger 不可用，跳过测试")
        return True

    # 高阈值（0.75），仅语音置信度 0.60 不应触发
    fused_high = FusedWakeDecision(window_seconds=2.0, wake_threshold=0.75)
    results_high = []
    fused_high.set_wake_callback(lambda r: results_high.append(r))

    voice_event = TriggerEvent(
        trigger_type=TriggerType.VOICE,
        source="microphone",
        data={"wake_word": "hey ufo", "confidence": 0.9},
    )
    r = await fused_high.process_event(voice_event)
    assert r is not None
    assert r.should_wake is False, (
        f"阈值 0.75 时仅语音不应触发唤醒，confidence={r.confidence:.2f}"
    )

    # 低阈值（0.50），仅语音应触发
    fused_low = FusedWakeDecision(window_seconds=2.0, wake_threshold=0.50)
    r2 = await fused_low.process_event(voice_event)
    assert r2 is not None
    assert r2.should_wake is True, "阈值 0.50 时仅语音应触发唤醒"

    print(f"  高阈值 should_wake={r.should_wake}, 低阈值 should_wake={r2.should_wake}")
    print("  ✅ FusedWakeDecision 阈值控制测试通过")
    return True


async def test_fused_wake_decision_false_positive():
    """测试防误唤醒（背景音源低置信度标记）"""
    print("\n=== 测试 FusedWakeDecision 防误唤醒 ===")
    from system_integration.fused_wake_decision import FusedWakeDecision

    try:
        from system_integration.hardware_trigger import TriggerType, TriggerEvent
    except ImportError:
        print("  ⚠️ hardware_trigger 不可用，跳过测试")
        return True

    fused = FusedWakeDecision(wake_threshold=0.65)

    # 背景音源：低置信度语音
    bg_voice = TriggerEvent(
        trigger_type=TriggerType.VOICE,
        source="microphone",
        data={"wake_word": "hey ufo", "confidence": 0.2, "source": "background_tv"},
    )
    r = await fused.process_event(bg_voice)
    assert r is not None
    assert r.should_wake is False, (
        f"背景音源应不触发唤醒，confidence={r.confidence:.2f}"
    )
    print(f"  背景音源 should_wake={r.should_wake} confidence={r.confidence:.2f}")
    print("  ✅ FusedWakeDecision 防误唤醒测试通过")
    return True


# =============================================================================
# 主测试入口
# =============================================================================

async def main():
    print("=" * 70)
    print("UFO Galaxy 智能唤醒系统单元测试")
    print("=" * 70)

    tests = [
        test_wake_router_basic,
        test_wake_router_dedup,
        test_wake_router_capability_match,
        test_wake_event_bus_publish,
        test_wake_event_bus_websocket_message,
        test_session_roaming_create_and_migrate,
        test_fused_wake_decision_voice_motion,
        test_fused_wake_decision_voice_only_threshold,
        test_fused_wake_decision_false_positive,
    ]

    passed = 0
    failed = 0
    for test_fn in tests:
        try:
            ok = await test_fn()
            if ok:
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"  ❌ {test_fn.__name__} 异常: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 70)
    print(f"测试结果: {passed} 通过 / {failed} 失败 / {len(tests)} 总计")
    print("=" * 70)
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
