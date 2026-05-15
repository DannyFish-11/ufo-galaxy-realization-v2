#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_device_lifecycle_state.py
======================================
统一设备生命周期状态机的测试（core/device_lifecycle_state.py）。

覆盖范围
--------
A.  模块可导入；权威常量非空。
B.  DeviceLifecycleStage 枚举值与顺序比较。
C.  DeviceLifecycleTransitionEvent 枚举值存在。
D.  derive_device_lifecycle_stage — 完整生命周期路径。
    D1.  unregistered: 无 WebSocket 连接。
    D2.  unregistered: WebSocket 连接但无注册 ack。
    D3.  registered: 注册 ack 成功，但有 gaps。
    D4.  registered: 注册 ack 成功，无 gaps，但 capability_visible=False。
    D5.  connected: 完全附加 + capability_visible=True，但 readiness_satisfied=False。
    D6.  ready: 所有就绪条件通过 + dispatch_gate_passed=True。
    D7.  participating: ready + execution_active=True。
    D8.  takeover_eligible: ready + takeover_eligible=True。
    D9.  operator_suspended 覆盖 → registered（若已注册）。
    D10. operator_suspended 覆盖 → unregistered（若未注册）。
    D11. blocking_reasons 在每个被阻止阶段中非空。
E.  transition_device_lifecycle — 事件驱动转换。
    E1.  websocket_connected + register_ack_sent → registered。
    E2.  registration_fully_attached → connected。
    E3.  readiness_satisfied → ready。
    E4.  execution_session_started → participating。
    E5.  takeover_eligibility_gained → takeover_eligible。
    E6.  websocket_disconnected 强制回退到 unregistered。
    E7.  readiness_lost 强制回退到 connected。
    E8.  execution_session_ended 从 participating 回退到 ready。
    E9.  operator_suspended 强制回退到 registered（若已注册）。
    E10. operator_suspension_lifted 重新推导阶段。
F.  完整生命周期路径：unregistered → registered → connected → ready →
    participating →（execution_session_ended）→ ready。
G.  record_lifecycle_state / get_stored_lifecycle_record 往返测试。
H.  reset_lifecycle_store 清除所有记录。
I.  get_lifecycle_record — 存储记录优先；无存储时降级到 unregistered。
J.  DeviceLifecycleRecord.to_dict() 可序列化且包含 lifecycle_stage 字段。
K.  stage_for_participation_tier / participation_tier_for_stage 映射一致性。
L.  DeviceLifecycleStage 顺序比较 (__ge__, __gt__, __le__, __lt__)。
M.  to_dict() 包含权威常量和合约版本字段。
N.  prior_stage 在转换记录中正确追踪。
"""

from __future__ import annotations

import sys
import os
from typing import Any, Dict, List

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ---------------------------------------------------------------------------
# 导入被测模块
# ---------------------------------------------------------------------------

from core.device_lifecycle_state import (
    DEVICE_LIFECYCLE_STATE_AUTHORITY,
    DEVICE_LIFECYCLE_CONTRACT_VERSION,
    LIFECYCLE_STAGE_SEMANTICS,
    ANDROID_SIDE_LIFECYCLE_CONTRACT,
    DeviceLifecycleStage,
    DeviceLifecycleTransitionEvent,
    DeviceLifecycleRecord,
    derive_device_lifecycle_stage,
    evaluate_device_lifecycle_stage,
    transition_device_lifecycle,
    get_lifecycle_record,
    record_lifecycle_state,
    get_stored_lifecycle_record,
    reset_lifecycle_store,
    stage_for_participation_tier,
    participation_tier_for_stage,
)


# ---------------------------------------------------------------------------
# 测试辅助 fixture
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_store():
    """每个测试前后清除生命周期存储，保证测试隔离。"""
    reset_lifecycle_store()
    yield
    reset_lifecycle_store()


# ---------------------------------------------------------------------------
# A. 模块导入与权威常量
# ---------------------------------------------------------------------------

class TestModuleImport:
    def test_authority_sentinel_nonempty(self):
        assert DEVICE_LIFECYCLE_STATE_AUTHORITY
        assert isinstance(DEVICE_LIFECYCLE_STATE_AUTHORITY, str)
        assert len(DEVICE_LIFECYCLE_STATE_AUTHORITY) > 20

    def test_contract_version_nonempty(self):
        assert DEVICE_LIFECYCLE_CONTRACT_VERSION
        assert "." in DEVICE_LIFECYCLE_CONTRACT_VERSION

    def test_lifecycle_stage_semantics_covers_all_stages(self):
        for stage in DeviceLifecycleStage:
            assert stage.value in LIFECYCLE_STAGE_SEMANTICS, (
                f"LIFECYCLE_STAGE_SEMANTICS 缺少阶段 {stage.value!r} 的语义描述"
            )

    def test_android_side_contract_nonempty(self):
        assert ANDROID_SIDE_LIFECYCLE_CONTRACT
        assert len(ANDROID_SIDE_LIFECYCLE_CONTRACT) > 50


# ---------------------------------------------------------------------------
# B. DeviceLifecycleStage 枚举值与顺序
# ---------------------------------------------------------------------------

class TestDeviceLifecycleStageEnum:
    def test_all_stages_present(self):
        expected = {
            "unregistered", "registered", "connected",
            "ready", "participating", "takeover_eligible",
        }
        actual = {s.value for s in DeviceLifecycleStage}
        assert actual == expected

    def test_ordinal_ordering(self):
        assert DeviceLifecycleStage.unregistered.ordinal() == 0
        assert DeviceLifecycleStage.registered.ordinal() == 1
        assert DeviceLifecycleStage.connected.ordinal() == 2
        assert DeviceLifecycleStage.ready.ordinal() == 3
        # participating 与 takeover_eligible 同级（均为 4）
        assert DeviceLifecycleStage.participating.ordinal() == 4
        assert DeviceLifecycleStage.takeover_eligible.ordinal() == 4

    def test_from_string_valid(self):
        assert DeviceLifecycleStage.from_string("ready") == DeviceLifecycleStage.ready
        assert DeviceLifecycleStage.from_string("CONNECTED") == DeviceLifecycleStage.connected

    def test_from_string_invalid_defaults_to_unregistered(self):
        assert DeviceLifecycleStage.from_string("invalid_stage") == DeviceLifecycleStage.unregistered
        assert DeviceLifecycleStage.from_string("") == DeviceLifecycleStage.unregistered


# ---------------------------------------------------------------------------
# C. DeviceLifecycleTransitionEvent 枚举值
# ---------------------------------------------------------------------------

class TestDeviceLifecycleTransitionEvent:
    def test_upward_events_present(self):
        upward = {
            "websocket_connected", "register_ack_sent", "registration_fully_attached",
            "readiness_satisfied", "execution_session_started", "takeover_eligibility_gained",
            "operator_suspension_lifted",
        }
        actual = {e.value for e in DeviceLifecycleTransitionEvent}
        for ev in upward:
            assert ev in actual, f"上升事件 {ev!r} 缺失"

    def test_downward_events_present(self):
        downward = {
            "websocket_disconnected", "registration_gap_detected", "readiness_lost",
            "execution_session_ended", "takeover_eligibility_lost",
            "operator_suspended", "attachment_break",
        }
        actual = {e.value for e in DeviceLifecycleTransitionEvent}
        for ev in downward:
            assert ev in actual, f"下降事件 {ev!r} 缺失"


# ---------------------------------------------------------------------------
# D. derive_device_lifecycle_stage — 完整生命周期路径
# ---------------------------------------------------------------------------

class TestDeriveDeviceLifecycleStage:
    """D. derive_device_lifecycle_stage 阶段推导测试。"""

    def _derive(self, **kwargs) -> DeviceLifecycleStage:
        """调用辅助：用默认 False 填充所有必填参数，可被 kwargs 覆盖。"""
        defaults = dict(
            websocket_connected=False,
            registration_ack_success=False,
            registration_fully_attached=False,
            registration_gaps=[],
            capability_visible=False,
            readiness_satisfied=False,
            dispatch_gate_passed=False,
            execution_active=False,
            takeover_eligible=False,
            operator_suspended=False,
        )
        defaults.update(kwargs)
        stage, _, _ = derive_device_lifecycle_stage(**defaults)
        return stage

    def test_D1_unregistered_no_websocket(self):
        assert self._derive(websocket_connected=False) == DeviceLifecycleStage.unregistered

    def test_D2_unregistered_websocket_no_ack(self):
        assert self._derive(websocket_connected=True, registration_ack_success=False) \
            == DeviceLifecycleStage.unregistered

    def test_D3_registered_with_gaps(self):
        stage = self._derive(
            websocket_connected=True,
            registration_ack_success=True,
            registration_fully_attached=False,
            registration_gaps=["attach_runtime_session"],
        )
        assert stage == DeviceLifecycleStage.registered

    def test_D4_registered_no_capability_visible(self):
        stage = self._derive(
            websocket_connected=True,
            registration_ack_success=True,
            registration_fully_attached=True,
            registration_gaps=[],
            capability_visible=False,
        )
        assert stage == DeviceLifecycleStage.registered

    def test_D5_connected_no_readiness(self):
        stage = self._derive(
            websocket_connected=True,
            registration_ack_success=True,
            registration_fully_attached=True,
            registration_gaps=[],
            capability_visible=True,
            readiness_satisfied=False,
        )
        assert stage == DeviceLifecycleStage.connected

    def test_D6_ready_all_conditions_met(self):
        stage = self._derive(
            websocket_connected=True,
            registration_ack_success=True,
            registration_fully_attached=True,
            registration_gaps=[],
            capability_visible=True,
            readiness_satisfied=True,
            dispatch_gate_passed=True,
        )
        assert stage == DeviceLifecycleStage.ready

    def test_D7_participating_execution_active(self):
        stage = self._derive(
            websocket_connected=True,
            registration_ack_success=True,
            registration_fully_attached=True,
            registration_gaps=[],
            capability_visible=True,
            readiness_satisfied=True,
            dispatch_gate_passed=True,
            execution_active=True,
        )
        assert stage == DeviceLifecycleStage.participating

    def test_D8_takeover_eligible(self):
        stage = self._derive(
            websocket_connected=True,
            registration_ack_success=True,
            registration_fully_attached=True,
            registration_gaps=[],
            capability_visible=True,
            readiness_satisfied=True,
            dispatch_gate_passed=True,
            takeover_eligible=True,
        )
        assert stage == DeviceLifecycleStage.takeover_eligible

    def test_D9_operator_suspended_with_registered(self):
        stage = self._derive(
            websocket_connected=True,
            registration_ack_success=True,
            registration_fully_attached=True,
            capability_visible=True,
            readiness_satisfied=True,
            dispatch_gate_passed=True,
            operator_suspended=True,
        )
        assert stage == DeviceLifecycleStage.registered

    def test_D10_operator_suspended_no_ws(self):
        stage = self._derive(
            websocket_connected=False,
            operator_suspended=True,
        )
        assert stage == DeviceLifecycleStage.unregistered

    def test_D11_blocking_reasons_nonempty_when_blocked(self):
        _, blocking, _ = derive_device_lifecycle_stage(
            websocket_connected=True,
            registration_ack_success=True,
            registration_fully_attached=True,
            registration_gaps=[],
            capability_visible=True,
            readiness_satisfied=False,
            dispatch_gate_passed=False,
        )
        assert len(blocking) > 0

    def test_dispatch_gate_fail_blocks_ready(self):
        """readiness_satisfied=True 但 dispatch_gate_passed=False → connected。"""
        stage = self._derive(
            websocket_connected=True,
            registration_ack_success=True,
            registration_fully_attached=True,
            capability_visible=True,
            readiness_satisfied=True,
            dispatch_gate_passed=False,
        )
        assert stage == DeviceLifecycleStage.connected


# ---------------------------------------------------------------------------
# E. transition_device_lifecycle — 事件驱动转换
# ---------------------------------------------------------------------------

class TestTransitionDeviceLifecycle:
    """E. transition_device_lifecycle 事件驱动转换。"""

    _device = "test-device-transitions"

    def test_E1_register_ack_sent_reaches_registered(self):
        rec = transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.register_ack_sent,
            websocket_connected=True,
            registration_ack_success=True,
        )
        assert rec.stage == DeviceLifecycleStage.registered

    def test_E2_registration_fully_attached_reaches_connected(self):
        # 先注册
        transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.register_ack_sent,
            websocket_connected=True,
            registration_ack_success=True,
        )
        rec = transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.registration_fully_attached,
            registration_fully_attached=True,
            registration_gaps=[],
            capability_visible=True,
        )
        assert rec.stage == DeviceLifecycleStage.connected

    def test_E3_readiness_satisfied_reaches_ready(self):
        transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.register_ack_sent,
            websocket_connected=True,
            registration_ack_success=True,
        )
        transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.registration_fully_attached,
            registration_fully_attached=True,
            capability_visible=True,
        )
        rec = transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.readiness_satisfied,
            readiness_satisfied=True,
            dispatch_gate_passed=True,
        )
        assert rec.stage == DeviceLifecycleStage.ready

    def test_E4_execution_session_started_reaches_participating(self):
        transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.register_ack_sent,
            websocket_connected=True,
            registration_ack_success=True,
        )
        transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.registration_fully_attached,
            registration_fully_attached=True,
            capability_visible=True,
        )
        transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.readiness_satisfied,
            readiness_satisfied=True,
            dispatch_gate_passed=True,
        )
        rec = transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.execution_session_started,
            execution_active=True,
        )
        assert rec.stage == DeviceLifecycleStage.participating

    def test_E5_takeover_eligibility_gained_reaches_takeover_eligible(self):
        transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.register_ack_sent,
            websocket_connected=True,
            registration_ack_success=True,
        )
        transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.registration_fully_attached,
            registration_fully_attached=True,
            capability_visible=True,
        )
        transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.readiness_satisfied,
            readiness_satisfied=True,
            dispatch_gate_passed=True,
        )
        rec = transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.takeover_eligibility_gained,
            takeover_eligible=True,
        )
        assert rec.stage == DeviceLifecycleStage.takeover_eligible

    def test_E6_websocket_disconnected_forces_unregistered(self):
        # 先让设备到达 ready 阶段
        transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.register_ack_sent,
            websocket_connected=True,
            registration_ack_success=True,
        )
        transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.registration_fully_attached,
            registration_fully_attached=True,
            capability_visible=True,
        )
        transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.readiness_satisfied,
            readiness_satisfied=True,
            dispatch_gate_passed=True,
        )
        rec = transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.websocket_disconnected,
        )
        assert rec.stage == DeviceLifecycleStage.unregistered
        assert rec.websocket_connected is False
        assert rec.registration_ack_success is False

    def test_E7_readiness_lost_falls_back_to_connected(self):
        transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.register_ack_sent,
            websocket_connected=True,
            registration_ack_success=True,
        )
        transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.registration_fully_attached,
            registration_fully_attached=True,
            capability_visible=True,
        )
        transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.readiness_satisfied,
            readiness_satisfied=True,
            dispatch_gate_passed=True,
        )
        rec = transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.readiness_lost,
        )
        assert rec.stage == DeviceLifecycleStage.connected

    def test_E8_execution_session_ended_returns_to_ready(self):
        transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.register_ack_sent,
            websocket_connected=True,
            registration_ack_success=True,
        )
        transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.registration_fully_attached,
            registration_fully_attached=True,
            capability_visible=True,
        )
        transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.readiness_satisfied,
            readiness_satisfied=True,
            dispatch_gate_passed=True,
        )
        transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.execution_session_started,
            execution_active=True,
        )
        rec = transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.execution_session_ended,
        )
        assert rec.stage == DeviceLifecycleStage.ready
        assert rec.execution_active is False

    def test_E9_operator_suspended_caps_at_registered(self):
        transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.register_ack_sent,
            websocket_connected=True,
            registration_ack_success=True,
        )
        transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.registration_fully_attached,
            registration_fully_attached=True,
            capability_visible=True,
        )
        transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.readiness_satisfied,
            readiness_satisfied=True,
            dispatch_gate_passed=True,
        )
        rec = transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.operator_suspended,
        )
        assert rec.stage == DeviceLifecycleStage.registered

    def test_E10_operator_suspension_lifted_rederives(self):
        transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.register_ack_sent,
            websocket_connected=True,
            registration_ack_success=True,
        )
        transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.registration_fully_attached,
            registration_fully_attached=True,
            capability_visible=True,
        )
        transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.readiness_satisfied,
            readiness_satisfied=True,
            dispatch_gate_passed=True,
        )
        transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.operator_suspended,
        )
        rec = transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.operator_suspension_lifted,
        )
        # 暂停解除后，应当从当前条件重新推导到 ready（保留了 readiness + dispatch_gate）
        assert rec.stage == DeviceLifecycleStage.ready
        assert rec.operator_suspended is False


# ---------------------------------------------------------------------------
# F. 完整生命周期往返路径
# ---------------------------------------------------------------------------

class TestFullLifecyclePath:
    """F. 完整生命周期路径测试。"""

    _device = "test-device-full-path"

    def test_full_lifecycle_from_unregistered_to_participating_and_back(self):
        # 1. unregistered: 初始状态
        rec = get_lifecycle_record(self._device)
        assert rec.stage == DeviceLifecycleStage.unregistered

        # 2. → registered: WebSocket + ack
        rec = transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.register_ack_sent,
            websocket_connected=True,
            registration_ack_success=True,
        )
        assert rec.stage == DeviceLifecycleStage.registered

        # 3. → connected: 完全附加 + 能力可见
        rec = transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.registration_fully_attached,
            registration_fully_attached=True,
            registration_gaps=[],
            capability_visible=True,
        )
        assert rec.stage == DeviceLifecycleStage.connected

        # 4. → ready: 就绪满足 + dispatch gate 通过
        rec = transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.readiness_satisfied,
            readiness_satisfied=True,
            dispatch_gate_passed=True,
        )
        assert rec.stage == DeviceLifecycleStage.ready

        # 5. → participating: 执行会话启动
        rec = transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.execution_session_started,
            execution_active=True,
        )
        assert rec.stage == DeviceLifecycleStage.participating

        # 6. → ready: 执行会话结束
        rec = transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.execution_session_ended,
        )
        assert rec.stage == DeviceLifecycleStage.ready

        # 7. → unregistered: 断线
        rec = transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.websocket_disconnected,
        )
        assert rec.stage == DeviceLifecycleStage.unregistered


# ---------------------------------------------------------------------------
# G. record_lifecycle_state / get_stored_lifecycle_record 往返
# ---------------------------------------------------------------------------

class TestStoreAndRetrieve:
    """G. 存储和检索测试。"""

    _device = "test-device-store"

    def test_record_then_retrieve(self):
        rec = DeviceLifecycleRecord(
            device_id=self._device,
            stage=DeviceLifecycleStage.ready,
            websocket_connected=True,
            registration_ack_success=True,
            registration_fully_attached=True,
            capability_visible=True,
            readiness_satisfied=True,
            dispatch_gate_passed=True,
        )
        record_lifecycle_state(rec)
        retrieved = get_stored_lifecycle_record(self._device)
        assert retrieved is not None
        assert retrieved.stage == DeviceLifecycleStage.ready
        assert retrieved.device_id == self._device

    def test_missing_device_returns_none(self):
        assert get_stored_lifecycle_record("nonexistent-device-xyz") is None

    def test_empty_device_id_is_noop(self):
        rec = DeviceLifecycleRecord(device_id="")
        record_lifecycle_state(rec)
        # 空 device_id 应被忽略
        assert get_stored_lifecycle_record("") is None


# ---------------------------------------------------------------------------
# H. reset_lifecycle_store 清除
# ---------------------------------------------------------------------------

class TestResetStore:
    """H. reset_lifecycle_store 清除测试。"""

    def test_reset_clears_all(self):
        for i in range(5):
            rec = DeviceLifecycleRecord(
                device_id=f"device-{i}",
                stage=DeviceLifecycleStage.registered,
            )
            record_lifecycle_state(rec)

        reset_lifecycle_store()

        for i in range(5):
            assert get_stored_lifecycle_record(f"device-{i}") is None


# ---------------------------------------------------------------------------
# I. get_lifecycle_record — 存储优先，降级到 unregistered
# ---------------------------------------------------------------------------

class TestGetLifecycleRecord:
    """I. get_lifecycle_record 优先级测试。"""

    _device = "test-device-get-record"

    def test_returns_stored_record_when_available(self):
        stored = DeviceLifecycleRecord(
            device_id=self._device,
            stage=DeviceLifecycleStage.connected,
        )
        record_lifecycle_state(stored)
        result = get_lifecycle_record(self._device)
        assert result.stage == DeviceLifecycleStage.connected

    def test_falls_back_to_runtime_derivation_when_no_stored(self):
        # 无存储 → 从运行时推导（无运行时依赖 → unregistered）
        result = get_lifecycle_record("device-no-store-no-runtime")
        assert result.stage == DeviceLifecycleStage.unregistered


# ---------------------------------------------------------------------------
# J. DeviceLifecycleRecord.to_dict()
# ---------------------------------------------------------------------------

class TestToDict:
    """J. DeviceLifecycleRecord.to_dict() 序列化测试。"""

    def test_to_dict_is_json_serializable(self):
        import json
        rec = DeviceLifecycleRecord(
            device_id="serialize-test",
            stage=DeviceLifecycleStage.ready,
            last_event=DeviceLifecycleTransitionEvent.readiness_satisfied,
            prior_stage=DeviceLifecycleStage.connected,
            websocket_connected=True,
            registration_ack_success=True,
            registration_fully_attached=True,
            capability_visible=True,
            readiness_satisfied=True,
            dispatch_gate_passed=True,
            blocking_reasons=[],
            stage_derivation_notes=["test note"],
        )
        d = rec.to_dict()
        # JSON 序列化不应抛出
        serialized = json.dumps(d)
        assert "serialize-test" in serialized
        assert "ready" in serialized

    def test_to_dict_contains_authority_fields(self):
        rec = DeviceLifecycleRecord(device_id="auth-test")
        d = rec.to_dict()
        assert "_authority" in d
        assert "_contract_version" in d
        assert d["_authority"] == DEVICE_LIFECYCLE_STATE_AUTHORITY
        assert d["_contract_version"] == DEVICE_LIFECYCLE_CONTRACT_VERSION

    def test_to_dict_stage_value_is_string(self):
        rec = DeviceLifecycleRecord(
            device_id="stage-str-test",
            stage=DeviceLifecycleStage.participating,
        )
        d = rec.to_dict()
        assert d["stage"] == "participating"
        assert isinstance(d["stage"], str)


# ---------------------------------------------------------------------------
# K. 参与层映射一致性
# ---------------------------------------------------------------------------

class TestMappingFunctions:
    """K. stage_for_participation_tier / participation_tier_for_stage 映射。"""

    def test_tier_to_stage_known_values(self):
        assert stage_for_participation_tier("local_only") == DeviceLifecycleStage.unregistered
        assert stage_for_participation_tier("control_only") == DeviceLifecycleStage.registered
        assert stage_for_participation_tier("cross_device_capable") == DeviceLifecycleStage.registered
        assert stage_for_participation_tier("cross_device_enabled") == DeviceLifecycleStage.connected
        assert stage_for_participation_tier("fully_attached") == DeviceLifecycleStage.connected
        assert stage_for_participation_tier("dispatch_eligible") == DeviceLifecycleStage.ready
        assert stage_for_participation_tier("distributed_participant") == DeviceLifecycleStage.participating

    def test_tier_to_stage_unknown_defaults_to_unregistered(self):
        assert stage_for_participation_tier("unknown_tier") == DeviceLifecycleStage.unregistered

    def test_stage_to_tier_round_trip(self):
        assert participation_tier_for_stage(DeviceLifecycleStage.unregistered) == "local_only"
        assert participation_tier_for_stage(DeviceLifecycleStage.registered) == "control_only"
        assert participation_tier_for_stage(DeviceLifecycleStage.connected) == "fully_attached"
        assert participation_tier_for_stage(DeviceLifecycleStage.ready) == "dispatch_eligible"
        assert participation_tier_for_stage(DeviceLifecycleStage.participating) == "distributed_participant"
        assert participation_tier_for_stage(DeviceLifecycleStage.takeover_eligible) == "dispatch_eligible"


# ---------------------------------------------------------------------------
# L. DeviceLifecycleStage 顺序比较
# ---------------------------------------------------------------------------

class TestStageComparisons:
    """L. 阶段顺序比较运算符。"""

    def test_ready_gt_connected(self):
        assert DeviceLifecycleStage.ready > DeviceLifecycleStage.connected

    def test_connected_lt_ready(self):
        assert DeviceLifecycleStage.connected < DeviceLifecycleStage.ready

    def test_registered_le_connected(self):
        assert DeviceLifecycleStage.registered <= DeviceLifecycleStage.connected

    def test_unregistered_lt_all_others(self):
        for stage in DeviceLifecycleStage:
            if stage != DeviceLifecycleStage.unregistered:
                assert DeviceLifecycleStage.unregistered < stage

    def test_participating_and_takeover_eligible_are_equal_ordinal(self):
        assert DeviceLifecycleStage.participating.ordinal() \
            == DeviceLifecycleStage.takeover_eligible.ordinal()

    def test_ready_le_participating(self):
        assert DeviceLifecycleStage.ready <= DeviceLifecycleStage.participating

    def test_same_stage_comparison(self):
        assert DeviceLifecycleStage.ready >= DeviceLifecycleStage.ready
        assert not (DeviceLifecycleStage.ready > DeviceLifecycleStage.ready)


# ---------------------------------------------------------------------------
# M. to_dict() 权威字段
# ---------------------------------------------------------------------------

class TestRecordToDictAuthority:
    """M. DeviceLifecycleRecord.to_dict() 包含必要的权威字段。"""

    def test_all_condition_fields_present(self):
        rec = DeviceLifecycleRecord(device_id="check-fields")
        d = rec.to_dict()
        required_fields = {
            "device_id", "stage", "last_event", "prior_stage",
            "websocket_connected", "registration_ack_success",
            "registration_fully_attached", "registration_gaps",
            "capability_visible", "readiness_satisfied", "dispatch_gate_passed",
            "execution_active", "takeover_eligible", "operator_suspended",
            "blocking_reasons", "stage_derivation_notes",
            "_authority", "_contract_version",
        }
        for f in required_fields:
            assert f in d, f"字段 {f!r} 缺失于 to_dict() 输出"


# ---------------------------------------------------------------------------
# N. prior_stage 追踪
# ---------------------------------------------------------------------------

class TestPriorStageTracking:
    """N. prior_stage 在转换记录中正确追踪。"""

    _device = "test-prior-stage"

    def test_prior_stage_tracked_across_transitions(self):
        rec1 = transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.register_ack_sent,
            websocket_connected=True,
            registration_ack_success=True,
        )
        assert rec1.prior_stage is not None
        # 第一次转换：prior_stage 来自初始派生值（unregistered）
        assert rec1.prior_stage == DeviceLifecycleStage.unregistered

        rec2 = transition_device_lifecycle(
            self._device,
            DeviceLifecycleTransitionEvent.registration_fully_attached,
            registration_fully_attached=True,
            capability_visible=True,
        )
        # 第二次转换：prior_stage 应该是 registered
        assert rec2.prior_stage == DeviceLifecycleStage.registered
        assert rec2.stage == DeviceLifecycleStage.connected
