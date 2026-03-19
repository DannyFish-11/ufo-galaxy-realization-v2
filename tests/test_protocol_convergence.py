"""
tests/test_protocol_convergence.py
=====================================

PR-6 Goal 4: Tests demonstrate legacy protocols are converted at ingress
and v3-only in business layer.

Covers:
  A) parse_message_compat() always produces AIPMessage v3 from v1 input
  B) parse_message_compat() always produces AIPMessage v3 from v2 input
  C) parse_message_compat() passes through v3 unchanged
  D) enforce_aip_v3() raises AIPVersionError for sub-v3 messages
  E) enforce_aip_v3() accepts v3.0+ messages
  F) normalise_to_v3_dict() always outputs version="3.0"
  G) Legacy type-string aliases are mapped to canonical v3 MessageType values
  H) core business-layer files do not import from enhancements.multidevice.device_protocol
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _imports_from(source: str, module_prefix: str) -> list:
    """Return list of import module paths that start with module_prefix."""
    tree = ast.parse(source)
    matches = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            full = node.module or ""
            if full.startswith(module_prefix):
                matches.append(full)
    return matches


def _source(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


# ===========================================================================
# A) parse_message_compat() from AIP v1 input → AIPMessage v3
# ===========================================================================

class TestParseMessageCompatV1:
    """All AIP v1 messages must be normalised to AIPMessage v3."""

    def _parse(self, data: dict):
        from galaxy_gateway.protocol.compat import parse_message_compat
        from galaxy_gateway.protocol.aip_v3 import AIPMessage
        msg = parse_message_compat(data)
        assert isinstance(msg, AIPMessage)
        return msg

    def test_v1_register_alias_becomes_device_register(self):
        """Legacy 'register' type maps to canonical 'device_register'."""
        msg = self._parse({"type": "register", "device_id": "dev_v1"})
        assert msg.type.value == "device_register"

    def test_v1_heartbeat_alias_maps(self):
        msg = self._parse({"type": "heartbeat", "device_id": "dev_v1"})
        assert msg.type.value == "heartbeat"

    def test_v1_task_execute_becomes_task_submit(self):
        msg = self._parse({"type": "task_execute", "device_id": "dev_v1"})
        assert msg.type.value == "task_submit"

    def test_v1_command_result_becomes_task_result(self):
        msg = self._parse({"type": "command_result", "device_id": "dev_v1"})
        assert msg.type.value == "task_result"

    def test_v1_status_update_becomes_device_status(self):
        msg = self._parse({"type": "status_update", "device_id": "dev_v1"})
        assert msg.type.value == "device_status"

    def test_v1_registration_alias_becomes_device_register(self):
        """'registration' (Android AIPClient legacy) must map correctly."""
        msg = self._parse({"type": "registration", "device_id": "dev_v1"})
        assert msg.type.value == "device_register"

    def test_v1_output_is_aip_message_instance(self):
        from galaxy_gateway.protocol.aip_v3 import AIPMessage
        msg = self._parse({"type": "heartbeat", "device_id": "x"})
        assert isinstance(msg, AIPMessage)


# ===========================================================================
# B) parse_message_compat() from AIP v2 input → AIPMessage v3
# ===========================================================================

class TestParseMessageCompatV2:
    """AIP v2.0 messages must be accepted and normalised to AIPMessage v3."""

    def _v2_payload(self, msg_type: str = "heartbeat", device_id: str = "dev_v2"):
        return {
            "version": "2.0",
            "type": msg_type,
            "device_id": device_id,
            "payload": {},
        }

    def test_v2_produces_aip_message(self):
        from galaxy_gateway.protocol.compat import parse_message_compat
        from galaxy_gateway.protocol.aip_v3 import AIPMessage
        msg = parse_message_compat(self._v2_payload("heartbeat"))
        assert isinstance(msg, AIPMessage)

    def test_v2_heartbeat_type_preserved(self):
        from galaxy_gateway.protocol.compat import parse_message_compat
        msg = parse_message_compat(self._v2_payload("heartbeat"))
        assert msg.type.value == "heartbeat"

    def test_v2_device_id_preserved(self):
        from galaxy_gateway.protocol.compat import parse_message_compat
        msg = parse_message_compat(self._v2_payload("heartbeat", "my_v2_device"))
        assert msg.device_id == "my_v2_device"


# ===========================================================================
# C) parse_message_compat() passes v3 messages through
# ===========================================================================

class TestParseMessageCompatV3Passthrough:
    """AIP v3 messages must pass through unmodified (type and fields intact)."""

    def _v3_payload(self, msg_type: str = "heartbeat", device_id: str = "dev_v3"):
        return {
            "version": "3.0",
            "type": msg_type,
            "device_id": device_id,
            "payload": {"ping": True},
        }

    def test_v3_returns_aip_message(self):
        from galaxy_gateway.protocol.compat import parse_message_compat
        from galaxy_gateway.protocol.aip_v3 import AIPMessage
        msg = parse_message_compat(self._v3_payload())
        assert isinstance(msg, AIPMessage)

    def test_v3_type_unchanged(self):
        from galaxy_gateway.protocol.compat import parse_message_compat
        msg = parse_message_compat(self._v3_payload("task_submit"))
        assert msg.type.value == "task_submit"

    def test_v3_json_string_input_accepted(self):
        import json
        from galaxy_gateway.protocol.compat import parse_message_compat
        from galaxy_gateway.protocol.aip_v3 import AIPMessage
        raw = json.dumps(self._v3_payload("heartbeat"))
        msg = parse_message_compat(raw)
        assert isinstance(msg, AIPMessage)


# ===========================================================================
# D) enforce_aip_v3() raises AIPVersionError for sub-v3
# ===========================================================================

class TestEnforceAIPV3Rejects:
    """Strict ingress enforcement must reject messages below v3.0."""

    def test_missing_version_raises(self):
        from galaxy_gateway.protocol.compat import enforce_aip_v3, AIPVersionError
        with pytest.raises(AIPVersionError):
            enforce_aip_v3({"type": "heartbeat", "device_id": "d1"})

    def test_version_1_raises(self):
        from galaxy_gateway.protocol.compat import enforce_aip_v3, AIPVersionError
        with pytest.raises(AIPVersionError):
            enforce_aip_v3({"version": "1.0", "type": "heartbeat", "device_id": "d1"})

    def test_version_2_raises(self):
        from galaxy_gateway.protocol.compat import enforce_aip_v3, AIPVersionError
        with pytest.raises(AIPVersionError):
            enforce_aip_v3({"version": "2.0", "type": "heartbeat", "device_id": "d1"})

    def test_version_2_9_raises(self):
        from galaxy_gateway.protocol.compat import enforce_aip_v3, AIPVersionError
        with pytest.raises(AIPVersionError):
            enforce_aip_v3({"version": "2.9", "type": "heartbeat"})


# ===========================================================================
# E) enforce_aip_v3() accepts v3.0+ messages
# ===========================================================================

class TestEnforceAIPV3Accepts:
    """Strict ingress enforcement must accept v3.0 and above."""

    def test_version_3_0_passes(self):
        from galaxy_gateway.protocol.compat import enforce_aip_v3
        # Should not raise
        enforce_aip_v3({"version": "3.0", "type": "heartbeat", "device_id": "d1"})

    def test_version_3_1_passes(self):
        from galaxy_gateway.protocol.compat import enforce_aip_v3
        enforce_aip_v3({"version": "3.1", "type": "heartbeat", "device_id": "d1"})


# ===========================================================================
# F) normalise_to_v3_dict() always outputs version="3.0"
# ===========================================================================

class TestNormaliseToV3Dict:
    """normalise_to_v3_dict() must output version='3.0' for any input version."""

    def test_v1_becomes_v3(self):
        from galaxy_gateway.protocol.compat import normalise_to_v3_dict
        result = normalise_to_v3_dict({"type": "heartbeat", "device_id": "x"})
        assert result["version"] == "3.0"

    def test_v2_becomes_v3(self):
        from galaxy_gateway.protocol.compat import normalise_to_v3_dict
        result = normalise_to_v3_dict({"version": "2.0", "type": "heartbeat", "device_id": "x"})
        assert result["version"] == "3.0"

    def test_v3_stays_v3(self):
        from galaxy_gateway.protocol.compat import normalise_to_v3_dict
        result = normalise_to_v3_dict({"version": "3.0", "type": "heartbeat", "device_id": "x"})
        assert result["version"] == "3.0"

    def test_extra_fields_preserved(self):
        """Application-level extra fields must survive normalisation."""
        from galaxy_gateway.protocol.compat import normalise_to_v3_dict
        result = normalise_to_v3_dict({
            "version": "1.0",
            "type": "heartbeat",
            "device_id": "x",
            "platform": "android",
            "os_version": "12",
        })
        assert result.get("platform") == "android"
        assert result.get("os_version") == "12"


# ===========================================================================
# G) Legacy type aliases map to canonical v3 MessageType
# ===========================================================================

class TestLegacyTypeAliasMapping:
    """Every legacy type-string alias must produce the correct canonical v3 type."""

    @pytest.mark.parametrize("legacy_type,expected_v3", [
        ("register",        "device_register"),
        ("agent_register",  "device_register"),
        ("device_register", "device_register"),
        ("registration",    "device_register"),
        ("heartbeat",       "heartbeat"),
        ("agent_heartbeat", "heartbeat"),
        ("device_heartbeat","heartbeat"),
        ("task_execute",    "task_submit"),
        ("command_result",  "task_result"),
        ("status_update",   "device_status"),
        ("update_status",   "device_status"),
    ])
    def test_alias_maps_correctly(self, legacy_type: str, expected_v3: str):
        from galaxy_gateway.protocol.compat import parse_message_compat
        msg = parse_message_compat({"type": legacy_type, "device_id": "test_device"})
        assert msg.type.value == expected_v3, (
            f"Legacy type {legacy_type!r} → expected {expected_v3!r}, got {msg.type.value!r}"
        )


# ===========================================================================
# H) Business-layer files must not import from enhancements.multidevice
# ===========================================================================

class TestCoreNoV2Imports:
    """Core business-layer files must import protocol types from aip_v3, not v2."""

    @pytest.mark.parametrize("rel_path", [
        "core/galaxy_core.py",
        "core/repo_coordinator.py",
    ])
    def test_no_enhancements_multidevice_import(self, rel_path: str):
        source = _source(rel_path)
        bad = _imports_from(source, "enhancements.multidevice.device_protocol")
        assert bad == [], (
            f"{rel_path} must not import from enhancements.multidevice.device_protocol; "
            f"found: {bad}"
        )

    @pytest.mark.parametrize("rel_path", [
        "core/galaxy_core.py",
        "core/repo_coordinator.py",
    ])
    def test_no_v2_protocol_types_in_business_layer(self, rel_path: str):
        """Business layer must not pull AIPMessage/MessageType from the v2 module."""
        source = _source(rel_path)
        v2_imports = _imports_from(source, "enhancements.multidevice")
        assert v2_imports == [], (
            f"{rel_path} still imports from enhancements.multidevice: {v2_imports}"
        )
