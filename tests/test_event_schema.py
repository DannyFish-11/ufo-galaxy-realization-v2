"""
tests/test_event_schema.py
===========================

校验 M2 统一事件 Schema（contracts/event_schema.json）的完整性和示例有效性。

包含：
  A) JSON Schema 文件本身的结构校验
  B) 每种 M2 事件类型的合法示例校验（validate_m2_event + build_m2_event）
  C) 必填字段缺失时的校验失败断言
  D) publish_m2_event 接口的基本行为测试
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from typing import Any, Dict

import pytest

# ---------------------------------------------------------------------------
# 确保根目录在 sys.path 中（适配不同 CWD）
# ---------------------------------------------------------------------------
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from integration.event_bus import (
    build_m2_event,
    publish_m2_event,
    validate_m2_event,
)

# ---------------------------------------------------------------------------
# 路径常量
# ---------------------------------------------------------------------------
SCHEMA_PATH = os.path.join(_ROOT, "contracts", "event_schema.json")

# ---------------------------------------------------------------------------
# 合法 payload 示例（每种事件类型各一个）
# ---------------------------------------------------------------------------
VALID_PAYLOADS: Dict[str, Dict[str, Any]] = {
    "agent.state": {
        "agent_id": "agent_001",
        "state": "running",
        "previous_state": "idle",
        "reason": "task_received",
    },
    "agent.emotion": {
        "agent_id": "agent_001",
        "emotion": "focused",
        "valence": 0.8,
        "arousal": 0.6,
        "confidence": 0.9,
    },
    "task.lifecycle": {
        "task_id": "task_abc123",
        "status": "running",
        "previous_status": "created",
        "task_type": "screen_click",
        "target_device": "android_device_01",
        "progress": 0.0,
    },
    "skill.invoke": {
        "skill_name": "web_search",
        "skill_version": "1.0.0",
        "args": {"query": "Galaxy AI system"},
        "invocation_id": "inv_001",
    },
    "perception.update": {
        "perception_type": "screen",
        "content_hash": "sha256:abcdef1234567890",
        "width": 1080,
        "height": 2340,
        "active_app": "com.example.app",
        "element_count": 42,
    },
    "action.command": {
        "command_id": "cmd_001",
        "command_type": "tap",
        "target_device": "android_device_01",
        "args": {"x": 540, "y": 960},
        "priority": 5,
    },
    "device.presence": {
        "device_id": "android_device_01",
        "device_type": "android",
        "presence": "online",
        "previous_presence": "offline",
        "capabilities": ["screen", "touch", "camera"],
    },
}


# ===========================================================================
# A) JSON Schema 文件结构校验
# ===========================================================================

class TestSchemaFile:
    """验证 contracts/event_schema.json 文件的结构完整性。"""

    def test_schema_file_exists(self):
        assert os.path.isfile(SCHEMA_PATH), f"Schema 文件不存在: {SCHEMA_PATH}"

    def test_schema_is_valid_json(self):
        with open(SCHEMA_PATH, "r", encoding="utf-8") as fh:
            schema = json.load(fh)
        assert isinstance(schema, dict)

    def test_schema_has_required_meta(self):
        with open(SCHEMA_PATH, "r", encoding="utf-8") as fh:
            schema = json.load(fh)
        assert schema.get("$schema", "").startswith("https://json-schema.org/draft/2020-12")
        assert "title" in schema
        assert schema.get("type") == "object"

    def test_schema_event_type_enum_contains_minimum_set(self):
        """event_type 枚举必须包含 M2 最小集所有类型。"""
        with open(SCHEMA_PATH, "r", encoding="utf-8") as fh:
            schema = json.load(fh)

        enum_values = schema["properties"]["event_type"]["enum"]
        required_types = {
            "agent.state",
            "agent.emotion",
            "task.lifecycle",
            "skill.invoke",
            "perception.update",
            "action.command",
            "device.presence",
        }
        missing = required_types - set(enum_values)
        assert not missing, f"event_type 枚举缺少以下类型: {missing}"

    def test_schema_required_fields(self):
        with open(SCHEMA_PATH, "r", encoding="utf-8") as fh:
            schema = json.load(fh)
        required = set(schema.get("required", []))
        assert {"event_id", "event_type", "timestamp", "source", "payload"} <= required

    def test_schema_source_requires_device_id(self):
        with open(SCHEMA_PATH, "r", encoding="utf-8") as fh:
            schema = json.load(fh)
        source_required = set(schema["properties"]["source"].get("required", []))
        assert "device_id" in source_required


# ===========================================================================
# B) 合法事件示例校验
# ===========================================================================

class TestValidExamples:
    """每种 M2 事件类型都应能通过 validate_m2_event 校验。"""

    @pytest.mark.parametrize("event_type", list(VALID_PAYLOADS.keys()))
    def test_valid_event_passes_validation(self, event_type: str):
        payload = VALID_PAYLOADS[event_type]
        evt = build_m2_event(
            event_type=event_type,
            device_id="test_device",
            payload=payload,
            node="test_node",
            task_id="task_test_001",
            span_id="span_test_001",
        )
        assert validate_m2_event(evt), f"合法 {event_type} 事件校验失败"

    @pytest.mark.parametrize("event_type", list(VALID_PAYLOADS.keys()))
    def test_build_m2_event_structure(self, event_type: str):
        """build_m2_event 应返回包含所有必填字段的字典。"""
        evt = build_m2_event(
            event_type=event_type,
            device_id="gw_001",
            payload=VALID_PAYLOADS[event_type],
        )
        assert "event_id" in evt
        assert evt["event_type"] == event_type
        assert "timestamp" in evt
        assert evt["source"]["device_id"] == "gw_001"
        assert isinstance(evt["payload"], dict)

    def test_build_m2_event_with_trace(self):
        evt = build_m2_event(
            "task.lifecycle",
            "gateway",
            {"task_id": "t1", "status": "running"},
            task_id="t1",
            span_id="s1",
        )
        assert evt["trace"]["task_id"] == "t1"
        assert evt["trace"]["span_id"] == "s1"

    def test_build_m2_event_without_trace(self):
        evt = build_m2_event(
            "device.presence",
            "gateway",
            {"device_id": "d1", "presence": "online"},
        )
        assert "trace" not in evt

    def test_build_m2_event_generates_unique_ids(self):
        evt1 = build_m2_event("agent.state", "dev", {"agent_id": "a", "state": "idle"})
        evt2 = build_m2_event("agent.state", "dev", {"agent_id": "a", "state": "idle"})
        assert evt1["event_id"] != evt2["event_id"]

    def test_build_m2_event_custom_event_id(self):
        custom_id = "custom-event-id-123"
        evt = build_m2_event(
            "agent.state", "dev",
            {"agent_id": "a", "state": "idle"},
            event_id=custom_id,
        )
        assert evt["event_id"] == custom_id


# ===========================================================================
# C) 必填字段缺失 → 校验失败
# ===========================================================================

class TestInvalidEvents:
    """缺少必填字段的事件应该被 validate_m2_event 拒绝。"""

    def _base_valid_event(self) -> dict:
        return build_m2_event(
            "task.lifecycle",
            "gateway",
            {"task_id": "t1", "status": "running"},
        )

    def test_missing_event_id_fails(self):
        evt = self._base_valid_event()
        del evt["event_id"]
        assert not validate_m2_event(evt)

    def test_missing_event_type_fails(self):
        evt = self._base_valid_event()
        del evt["event_type"]
        assert not validate_m2_event(evt)

    def test_missing_timestamp_fails(self):
        evt = self._base_valid_event()
        del evt["timestamp"]
        assert not validate_m2_event(evt)

    def test_missing_source_fails(self):
        evt = self._base_valid_event()
        del evt["source"]
        assert not validate_m2_event(evt)

    def test_missing_payload_fails(self):
        evt = self._base_valid_event()
        del evt["payload"]
        assert not validate_m2_event(evt)

    def test_source_missing_device_id_fails(self):
        evt = self._base_valid_event()
        evt["source"] = {"node": "some_node"}  # device_id 缺失
        assert not validate_m2_event(evt)

    def test_invalid_event_type_fails(self):
        """非法 event_type 应被 jsonschema 拒绝（如果 jsonschema 可用）。"""
        evt = self._base_valid_event()
        evt["event_type"] = "not.a.valid.type"
        # 如果 jsonschema 不可用，基础校验不检查枚举值，跳过
        try:
            import jsonschema
            jsonschema_available = True
        except ImportError:
            jsonschema_available = False

        if jsonschema_available:
            assert not validate_m2_event(evt)


# ===========================================================================
# D) publish_m2_event 接口行为
# ===========================================================================

class TestPublishM2Event:
    """publish_m2_event 基本行为测试。"""

    def test_publish_valid_event_returns_true(self):
        evt = build_m2_event(
            "device.presence",
            "gateway",
            {"device_id": "d1", "presence": "online"},
        )
        result = publish_m2_event(evt)
        assert result is True

    def test_publish_invalid_event_returns_false(self):
        bad_evt = {"event_type": "task.lifecycle"}  # 缺少必填字段
        result = publish_m2_event(bad_evt)
        assert result is False

    def test_publish_with_validation_disabled(self):
        """关闭校验时，即使缺少字段也应返回 True（不做校验）。"""
        bad_evt = {"event_type": "task.lifecycle"}
        result = publish_m2_event(bad_evt, validate=False)
        assert result is True

    def test_publish_all_event_types(self):
        """所有 M2 最小集事件类型均应能成功发布。"""
        for event_type, payload in VALID_PAYLOADS.items():
            evt = build_m2_event(event_type, "test_device", payload)
            assert publish_m2_event(evt), f"event_type={event_type} 发布失败"
