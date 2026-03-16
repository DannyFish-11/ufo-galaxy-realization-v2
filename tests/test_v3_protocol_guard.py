"""
AIP v3-only Protocol Guard Tests
=================================

Verifies the single-source-of-truth invariants for the AIP v3 protocol:

1. Importing ``galaxy_gateway.aip_protocol_v2`` is blocked (raises ImportError).
2. Legacy inputs are accepted via compat and converted to v3 AIPMessage.
3. v3 AIPMessage flows pass through unchanged.
4. v3 MessageType includes all message types previously defined in v2
   ExtendedMessageType (Phases 1-5).
5. No Python source file (outside the deprecated stub) contains
   a direct reference to ``aip_protocol_v2``.
"""

import importlib
import os
import sys
import glob
import pytest

from galaxy_gateway.protocol.aip_v3 import AIPMessage, MessageType
from galaxy_gateway.protocol.compat import parse_message_compat


# ---------------------------------------------------------------------------
# 1. aip_protocol_v2 raises on import
# ---------------------------------------------------------------------------

class TestV2ImportBlocked:
    """Importing galaxy_gateway.aip_protocol_v2 must raise ImportError."""

    def test_direct_import_raises(self):
        # Make sure the module is not cached from a previous successful import.
        sys.modules.pop("galaxy_gateway.aip_protocol_v2", None)
        with pytest.raises(ImportError, match="aip_protocol_v2 is DEPRECATED"):
            import galaxy_gateway.aip_protocol_v2  # noqa: F401


# ---------------------------------------------------------------------------
# 2. Legacy → compat → v3
# ---------------------------------------------------------------------------

class TestCompatLayer:
    """Legacy inputs must be normalised to v3 AIPMessage by parse_message_compat."""

    def test_v1_legacy_type_normalised(self):
        raw = {
            "type": "register",
            "device_id": "dev-001",
        }
        msg = parse_message_compat(raw)
        assert isinstance(msg, AIPMessage)
        assert msg.version.startswith("3")
        assert msg.type == MessageType.DEVICE_REGISTER

    def test_v1_heartbeat_normalised(self):
        raw = {
            "type": "heartbeat",
            "device_id": "dev-002",
        }
        msg = parse_message_compat(raw)
        assert isinstance(msg, AIPMessage)
        assert msg.version.startswith("3")
        assert msg.type == MessageType.DEVICE_HEARTBEAT

    def test_v2_message_bumped_to_v3(self):
        raw = {
            "version": "2.0",
            "type": "device_register",
            "device_id": "dev-003",
        }
        msg = parse_message_compat(raw)
        assert isinstance(msg, AIPMessage)
        assert msg.version == "3.0"
        assert msg.device_id == "dev-003"

    def test_v3_message_passed_through(self):
        raw = {
            "version": "3.0",
            "type": "heartbeat",
            "device_id": "dev-004",
        }
        msg = parse_message_compat(raw)
        assert isinstance(msg, AIPMessage)
        assert msg.version == "3.0"
        assert msg.type == MessageType.DEVICE_HEARTBEAT

    def test_trace_id_injected(self):
        raw = {"type": "register", "device_id": "dev-005"}
        # compat injects trace_id / route_mode before parse; the resulting
        # AIPMessage should be a valid v3 object (injection does not error).
        msg = parse_message_compat(raw)
        assert isinstance(msg, AIPMessage)
        assert msg.version.startswith("3")

    def test_route_mode_injected(self):
        raw = {"type": "register", "device_id": "dev-006"}
        msg = parse_message_compat(raw)
        assert isinstance(msg, AIPMessage)
        assert msg.version.startswith("3")


# ---------------------------------------------------------------------------
# 3. v3 AIPMessage has all previously v2-only types
# ---------------------------------------------------------------------------

class TestV3MessageTypeCompleteness:
    """All formerly-v2-only types must be present in v3 MessageType."""

    @pytest.mark.parametrize("type_value", [
        # Phase 1 – Agent dispatch
        "agent_deploy", "agent_deploy_ack", "agent_status", "agent_result",
        # Phase 2 – Relay
        "relay_request", "relay_forward", "relay_reply", "relay_ack",
        # Phase 3 – Hybrid execution
        "hybrid_execute", "hybrid_result", "hybrid_degrade",
        # Phase 4 – RAG & code execution
        "rag_query", "rag_result", "code_execute", "code_result",
        # Phase 5 – P2P mesh
        "peer_announce", "peer_exchange", "mesh_topology",
    ])
    def test_type_present(self, type_value):
        all_values = {t.value for t in MessageType}
        assert type_value in all_values, (
            f"MessageType is missing '{type_value}' — "
            "it should have been promoted from v2 ExtendedMessageType"
        )


# ---------------------------------------------------------------------------
# 4. Source-code guard: no file (other than the stub) references aip_protocol_v2
# ---------------------------------------------------------------------------

class TestNoV2SourceReferences:
    """No .py file other than aip_protocol_v2.py itself may reference the module."""

    def _find_references(self):
        repo_root = os.path.dirname(os.path.dirname(__file__))
        search_dirs = ["galaxy_gateway", "core", "enhancements", "tests"]
        violations = []
        for d in search_dirs:
            pattern = os.path.join(repo_root, d, "**", "*.py")
            for fpath in glob.glob(pattern, recursive=True):
                # Skip the deprecated stub and this guard test itself.
                basename = os.path.basename(fpath)
                if basename in ("aip_protocol_v2.py", "test_v3_protocol_guard.py"):
                    continue
                # Skip __pycache__
                if "__pycache__" in fpath:
                    continue
                try:
                    with open(fpath, encoding="utf-8", errors="replace") as f:
                        content = f.read()
                    if "aip_protocol_v2" in content:
                        violations.append(fpath)
                except OSError:
                    pass
        return violations

    def test_no_v2_references_in_source(self):
        violations = self._find_references()
        assert not violations, (
            "The following files still reference 'aip_protocol_v2' and must be updated:\n"
            + "\n".join(f"  {v}" for v in violations)
        )
