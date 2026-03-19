"""
PR-4: Protocol Convergence — guardrail tests
=============================================

Enforces:
1. core/galaxy_core.py and core/repo_coordinator.py do NOT import AIPMessage
   or MessageType from enhancements.multidevice.device_protocol (v2 layer).
   They must import from galaxy_gateway.protocol.aip_v3 instead.
2. Binary AIP v2 frames are converted through the canonical compat adapter
   (galaxy_gateway.protocol.compat.aip_v2_binary_to_v3) before entering
   business logic; the business layer only ever sees AIPMessage v3 objects.
3. parse_message_compat always produces AIPMessage v3 instances from v1/v2
   legacy inputs.
4. AIPVersionError is raised for strict-mode ingress rejecting sub-v3.
"""

from __future__ import annotations

import ast
import os
import struct
import zlib
import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent

# The AIP v2.0 binary magic must match AIPMessage._V2_MAGIC in device_protocol.py.
# It is read dynamically from the source to avoid silent drift.
def _get_v2_magic() -> int:
    """Read _V2_MAGIC from device_protocol source to avoid hardcoded duplication."""
    src = (REPO_ROOT / "enhancements/multidevice/device_protocol.py").read_text()
    for line in src.splitlines():
        line = line.strip()
        if line.startswith("_V2_MAGIC") and "=" in line:
            # e.g. _V2_MAGIC: int = 0x55464F47  # …
            val_part = line.split("=", 1)[1].split("#")[0].strip()
            return int(val_part, 0)
    raise RuntimeError("Could not parse _V2_MAGIC from device_protocol.py")


def _source(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


def _imports_from(source: str, module_prefix: str) -> list[str]:
    """Return all 'from <module> import ...' lines that match module_prefix."""
    matches = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            full = (node.module or "")
            if full.startswith(module_prefix):
                matches.append(full)
    return matches


# ---------------------------------------------------------------------------
# A. core/* must not import from enhancements.multidevice.device_protocol
# ---------------------------------------------------------------------------

class TestCoreNoV2Imports:
    """core/ files must obtain AIPMessage/MessageType from aip_v3, not enhancements."""

    @pytest.mark.parametrize("rel_path", [
        "core/galaxy_core.py",
        "core/repo_coordinator.py",
    ])
    def test_no_enhancements_multidevice_import(self, rel_path: str):
        source = _source(rel_path)
        bad_imports = _imports_from(source, "enhancements.multidevice.device_protocol")
        assert bad_imports == [], (
            f"{rel_path} must not import from enhancements.multidevice.device_protocol; "
            f"found: {bad_imports}"
        )

    @pytest.mark.parametrize("rel_path", [
        "core/galaxy_core.py",
        "core/repo_coordinator.py",
    ])
    def test_uses_aip_v3_for_protocol_types(self, rel_path: str):
        """AIPMessage and MessageType must come from galaxy_gateway.protocol.aip_v3."""
        source = _source(rel_path)
        # The file is allowed to import AIPMessage / MessageType from aip_v3 OR
        # to have them as None (optional import).  What's forbidden is sourcing
        # them from the enhancements.multidevice layer.
        v3_imports = _imports_from(source, "galaxy_gateway.protocol.aip_v3")
        enhancements_imports = _imports_from(source, "enhancements.multidevice")
        assert enhancements_imports == [], (
            f"{rel_path} still imports from enhancements.multidevice: {enhancements_imports}"
        )
        # If the file references AIPMessage/AIPMessageType at all they should
        # come from the v3 canonical source.
        if "AIPMessage" in source or "AIPMessageType" in source:
            assert v3_imports, (
                f"{rel_path} uses AIPMessage/AIPMessageType but does not import "
                "from galaxy_gateway.protocol.aip_v3"
            )


# ---------------------------------------------------------------------------
# B. compat layer: parse_message_compat always returns AIPMessage v3
# ---------------------------------------------------------------------------

class TestCompatIngressAlwaysV3:
    """parse_message_compat must produce AIPMessage v3 for all legacy inputs."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from galaxy_gateway.protocol.compat import parse_message_compat
        from galaxy_gateway.protocol.aip_v3 import AIPMessage, MessageType
        self.parse = parse_message_compat
        self.AIPMessage = AIPMessage
        self.MessageType = MessageType

    def test_v3_input_is_passthrough(self):
        msg = self.parse({"version": "3.0", "type": "heartbeat", "device_id": "d1"})
        assert isinstance(msg, self.AIPMessage)
        assert msg.version.startswith("3")

    def test_v2_input_normalised_to_v3(self):
        msg = self.parse({"version": "2.0", "type": "heartbeat", "device_id": "d2"})
        assert isinstance(msg, self.AIPMessage)
        assert msg.version.startswith("3")

    def test_v1_register_alias_normalised(self):
        msg = self.parse({"type": "register", "device_id": "d3"})
        assert isinstance(msg, self.AIPMessage)
        assert msg.type == self.MessageType.DEVICE_REGISTER
        assert msg.version.startswith("3")

    def test_v1_heartbeat_alias_normalised(self):
        msg = self.parse({"type": "heartbeat", "device_id": "d4"})
        assert isinstance(msg, self.AIPMessage)
        assert msg.version.startswith("3")

    def test_trace_id_injected_when_absent(self):
        from galaxy_gateway.protocol.compat import inject_trace_metadata
        import uuid as _uuid_mod
        out = inject_trace_metadata({"type": "heartbeat", "device_id": "d5"})
        assert "trace_id" in out, "trace_id must be injected when absent"
        # Must be a valid UUID
        _uuid_mod.UUID(out["trace_id"])

    def test_v1_task_execute_maps_to_task_submit(self):
        msg = self.parse({"type": "task_execute", "device_id": "d6"})
        assert msg.type == self.MessageType.TASK_SUBMIT


# ---------------------------------------------------------------------------
# C. binary v2 frames flow through compat adapter → produce v3 AIPMessage
# ---------------------------------------------------------------------------

def _build_v2_binary(msg_type_val: int, payload: dict) -> bytes:
    """Build a minimal AIP v2.0 binary frame matching device_protocol format."""
    _V2_MAGIC = _get_v2_magic()   # read from source — never stale
    _V2_VERSION = 0x0200
    payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    header = struct.pack(
        ">IHHII",
        _V2_MAGIC,
        _V2_VERSION,
        msg_type_val,
        len(payload_bytes),
        0,
    )
    checksum = zlib.crc32(payload_bytes) & 0xFFFF_FFFF
    footer = struct.pack(">II", checksum, 0)
    return header + payload_bytes + footer


def _is_legacy_multidevice_enabled() -> bool:
    """Return True when the legacy multi-device layer is enabled via env var."""
    import os
    return os.environ.get("GALAXY_ENABLE_LEGACY_MULTIDEVICE", "").lower() in ("1", "true", "yes")


_LEGACY_SKIP_REASON = "GALAXY_ENABLE_LEGACY_MULTIDEVICE not set — binary compat skipped"


class TestBinaryV2ThroughCompatAdapter:
    """aip_v2_binary_to_v3 must produce a v3 dict and parse_message_compat a v3 object.

    The binary round-trip tests require GALAXY_ENABLE_LEGACY_MULTIDEVICE=true;
    they are skipped automatically when the legacy layer is disabled.
    """

    def test_aip_v2_binary_to_v3_returns_dict(self):
        if not _is_legacy_multidevice_enabled():
            pytest.skip(_LEGACY_SKIP_REASON)

        from galaxy_gateway.protocol.compat import aip_v2_binary_to_v3

        raw = _build_v2_binary(0x03, {"source_device": "devX", "payload": {}})
        result = aip_v2_binary_to_v3(raw)
        assert result is not None, "aip_v2_binary_to_v3 must not return None for valid v2 frame"
        assert result.get("version") == "3.0"
        assert "type" in result

    def test_aip_v2_binary_round_trip_produces_aip_message(self):
        if not _is_legacy_multidevice_enabled():
            pytest.skip(_LEGACY_SKIP_REASON)

        from galaxy_gateway.protocol.compat import aip_v2_binary_to_v3, parse_message_compat
        from galaxy_gateway.protocol.aip_v3 import AIPMessage

        raw = _build_v2_binary(0x01, {"source_device": "devY", "payload": {"name": "Test"}})
        v3_dict = aip_v2_binary_to_v3(raw)
        assert v3_dict is not None
        v3_dict.setdefault("device_id", v3_dict.get("device_id") or "devY")
        msg = parse_message_compat(v3_dict)
        assert isinstance(msg, AIPMessage)
        assert msg.version.startswith("3")

    def test_invalid_binary_returns_none(self):
        from galaxy_gateway.protocol.compat import aip_v2_binary_to_v3

        result = aip_v2_binary_to_v3(b"\x00\x01\x02\x03bad_bytes")
        assert result is None, "aip_v2_binary_to_v3 must return None for invalid frames"


# ---------------------------------------------------------------------------
# D. device_coordinator uses compat adapter (no direct from_bytes in gateway layer)
# ---------------------------------------------------------------------------

class TestCoordinatorNoBytesInGateway:
    """device_coordinator must NOT call AIPMessage.from_bytes() directly in
    handle_websocket; it must route through galaxy_gateway.protocol.compat."""

    def test_handle_websocket_uses_compat_not_raw_from_bytes(self):
        source = _source("enhancements/multidevice/device_coordinator.py")
        # The compat import must be present somewhere in the file
        assert "aip_v2_binary_to_v3" in source, (
            "device_coordinator.py must import aip_v2_binary_to_v3 from "
            "galaxy_gateway.protocol.compat for binary ingress"
        )
        assert "parse_message_compat" in source, (
            "device_coordinator.py must use parse_message_compat for binary→v3 conversion"
        )

        # Use AST to extract the body of handle_websocket and verify it does
        # not contain any direct `.from_bytes(` call.
        tree = ast.parse(source)
        handle_ws_body: str | None = None
        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                if node.name == "handle_websocket":
                    # ast.get_source_segment requires the original source string
                    handle_ws_body = ast.get_source_segment(source, node)
                    break

        assert handle_ws_body is not None, (
            "handle_websocket method not found in device_coordinator.py"
        )
        assert "from_bytes" not in handle_ws_body, (
            "handle_websocket must not call AIPMessage.from_bytes() directly; "
            "binary frames must go through aip_v2_binary_to_v3 + parse_message_compat"
        )


# ---------------------------------------------------------------------------
# E. Strict mode raises AIPVersionError for sub-v3 ingress
# ---------------------------------------------------------------------------

class TestStrictIngress:
    """parse_message_strict must reject v1/v2 inputs."""

    def test_strict_rejects_v1(self):
        from galaxy_gateway.protocol.compat import parse_message_strict, AIPVersionError

        with pytest.raises(AIPVersionError):
            parse_message_strict({"type": "heartbeat", "device_id": "d1"})

    def test_strict_rejects_v2(self):
        from galaxy_gateway.protocol.compat import parse_message_strict, AIPVersionError

        with pytest.raises(AIPVersionError):
            parse_message_strict({"version": "2.0", "type": "heartbeat", "device_id": "d2"})

    def test_strict_accepts_v3(self):
        from galaxy_gateway.protocol.compat import parse_message_strict
        from galaxy_gateway.protocol.aip_v3 import AIPMessage

        msg = parse_message_strict({"version": "3.0", "type": "heartbeat", "device_id": "d3"})
        assert isinstance(msg, AIPMessage)
        assert msg.version.startswith("3")
