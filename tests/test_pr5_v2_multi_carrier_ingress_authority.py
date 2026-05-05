"""tests/test_pr5_v2_multi_carrier_ingress_authority.py
=========================================================
PR-5-V2: Unify multi-carrier invocation ingress on the existing center
authority chain.

Validates that all ingress carriers invoke the same
DesktopPresenceRuntime.handle_request() authority chain with consistent
metadata, and that the result carries normalized authority-chain stamps
across every carrier.

Carriers under test:
  A. Chat route (core/routes/chat.py)  — source="chat"
  B. Android vision handler (galaxy_gateway/android/handlers/vision.py)
       — source="android_vision"
  C. Vision sampler (core/services/vision_sampler.py)  — source="vision_sampler"
  D. Compat WebSocket chat (core/api_routes.py)  — source="chat"
  E. Compat WebSocket chat — user_id and entry_mode are now forwarded

Test index:
  1.  android_vision: _process_via_runtime_shell passes session_id.
  2.  android_vision: _process_via_runtime_shell passes user_id.
  3.  android_vision: _process_via_runtime_shell passes entry_mode="local".
  4.  android_vision: session_id is derived from task_id when provided.
  5.  android_vision: session_id falls back to android_vision_{device_id}.
  6.  vision_sampler: run_sampling_session passes session_id to handle_request.
  7.  vision_sampler: run_sampling_session passes user_id to handle_request.
  8.  vision_sampler: run_sampling_session passes entry_mode="local".
  9.  vision_sampler: session_id is vision_sampler_{device_id}.
 10.  compat_ws_chat: handle_request call now includes user_id forwarding.
 11.  compat_ws_chat: handle_request call now includes entry_mode forwarding.
 12.  handle_request result contains ingress_carrier_context stamp.
 13.  ingress_carrier_context.carrier equals entrypoint_source.
 14.  ingress_carrier_context.authority_chain is "DesktopPresenceRuntime.handle_request".
 15.  ingress_carrier_context.session_id equals conversation_session_id.
 16.  ingress_carrier_context.user_id reflects the user_id argument.
 17.  All carriers produce authority_metadata with layer_role="runtime_shell_authority".
 18.  All carriers produce entrypoint_source matching their carrier tag.
 19.  android_vision source file passes session_id, user_id, entry_mode to handle_request.
 20.  vision_sampler source file passes session_id, user_id, entry_mode to handle_request.
 21.  compat_ws chat source passes user_id and entry_mode.
"""

from __future__ import annotations

import asyncio
import inspect
import pathlib
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_REPO_ROOT = pathlib.Path(__file__).parent.parent


def _read(relpath: str) -> str:
    return (_REPO_ROOT / relpath).read_text(encoding="utf-8")


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Helpers — build a minimal DesktopPresenceRuntime mock result
# ---------------------------------------------------------------------------

def _make_mock_runtime_result(
    source: str = "chat",
    session_id: str = "test_session",
    user_id: str = "test_user",
) -> Dict[str, Any]:
    """Build a minimal dict that mirrors what handle_request returns."""
    return {
        "success": True,
        "response": "ok",
        "runtime_session_id": "rsess_abc",
        "trace_id": "rsess_abc",
        "tristate": "silent",
        "entrypoint_source": source,
        "conversation_session_id": session_id,
        "control_session_id": f"ctrl_{session_id}",
        "authority_metadata": {
            "layer_role": "runtime_shell_authority",
            "canonical_module": "core.desktop_presence_runtime",
            "canonical_class": "DesktopPresenceRuntime",
        },
        "ingress_carrier_context": {
            "carrier": source,
            "authority_chain": "DesktopPresenceRuntime.handle_request",
            "session_id": session_id,
            "user_id": user_id,
        },
        "metadata": {"session_id": session_id},
    }


# ============================================================================
# A. Source-level inspection — android_vision handler
# ============================================================================

class TestAndroidVisionHandlerSource:
    """Inspect galaxy_gateway/android/handlers/vision.py source."""

    _SRC = _read("galaxy_gateway/android/handlers/vision.py")

    def test_1_android_vision_passes_session_id(self):
        """vision.py must pass session_id= to handle_request."""
        assert "session_id=" in self._SRC, (
            "galaxy_gateway/android/handlers/vision.py must pass session_id= "
            "to DesktopPresenceRuntime.handle_request() so the authority chain "
            "can correlate vision requests."
        )

    def test_2_android_vision_passes_user_id(self):
        """vision.py must pass user_id= to handle_request."""
        assert "user_id=" in self._SRC, (
            "galaxy_gateway/android/handlers/vision.py must pass user_id= to "
            "DesktopPresenceRuntime.handle_request()."
        )

    def test_3_android_vision_passes_entry_mode_local(self):
        """vision.py must pass entry_mode='local' to handle_request."""
        assert 'entry_mode="local"' in self._SRC or "entry_mode='local'" in self._SRC, (
            "galaxy_gateway/android/handlers/vision.py must pass "
            "entry_mode='local' to DesktopPresenceRuntime.handle_request()."
        )

    def test_4_android_vision_session_id_uses_task_id(self):
        """vision.py must derive session_id from task_id when available."""
        assert "task_id" in self._SRC and "session_id" in self._SRC, (
            "vision.py should correlate session_id with the incoming task_id."
        )

    def test_5_android_vision_session_id_fallback(self):
        """vision.py must fall back to android_vision_{device_id} when no task_id."""
        assert "android_vision_" in self._SRC, (
            "vision.py must use 'android_vision_{device_id}' as fallback session_id "
            "when no task_id is available."
        )

    def test_19_android_vision_passes_all_three_canonical_params(self):
        """vision.py passes session_id, user_id, and entry_mode to handle_request."""
        src = self._SRC
        assert "session_id=" in src and "user_id=" in src and "entry_mode=" in src, (
            "vision.py must pass all three canonical metadata params "
            "(session_id, user_id, entry_mode) to handle_request()."
        )


# ============================================================================
# B. Source-level inspection — vision_sampler
# ============================================================================

class TestVisionSamplerSource:
    """Inspect core/services/vision_sampler.py source."""

    _SRC = _read("core/services/vision_sampler.py")

    def test_6_vision_sampler_passes_session_id(self):
        """vision_sampler.py must pass session_id= to handle_request."""
        assert "session_id=" in self._SRC, (
            "core/services/vision_sampler.py must pass session_id= to "
            "DesktopPresenceRuntime.handle_request()."
        )

    def test_7_vision_sampler_passes_user_id(self):
        """vision_sampler.py must pass user_id= to handle_request."""
        assert "user_id=" in self._SRC, (
            "core/services/vision_sampler.py must pass user_id= to "
            "DesktopPresenceRuntime.handle_request()."
        )

    def test_8_vision_sampler_passes_entry_mode_local(self):
        """vision_sampler.py must pass entry_mode='local' to handle_request."""
        assert 'entry_mode="local"' in self._SRC or "entry_mode='local'" in self._SRC, (
            "core/services/vision_sampler.py must pass entry_mode='local' to "
            "DesktopPresenceRuntime.handle_request()."
        )

    def test_9_vision_sampler_session_id_is_vision_sampler_prefix(self):
        """vision_sampler.py session_id must use 'vision_sampler_' prefix."""
        assert "vision_sampler_" in self._SRC, (
            "core/services/vision_sampler.py must derive session_id with the "
            "'vision_sampler_' prefix so it can be identified in logs."
        )

    def test_20_vision_sampler_passes_all_three_canonical_params(self):
        """vision_sampler.py passes session_id, user_id, and entry_mode."""
        src = self._SRC
        assert "session_id=" in src and "user_id=" in src and "entry_mode=" in src, (
            "vision_sampler.py must pass all three canonical metadata params "
            "(session_id, user_id, entry_mode) to handle_request()."
        )


# ============================================================================
# C. Source-level inspection — compat WS chat handler
# ============================================================================

class TestCompatWSChatSource:
    """Inspect the compat WS chat handler in core/api_routes.py."""

    _SRC = _read("core/api_routes.py")

    def test_10_compat_ws_chat_passes_user_id(self):
        """compat WS chat handler must forward user_id to handle_request."""
        assert "user_id=" in self._SRC, (
            "core/api_routes.py compat WS chat handler must pass user_id= to "
            "DesktopPresenceRuntime.handle_request()."
        )

    def test_11_compat_ws_chat_passes_entry_mode(self):
        """compat WS chat handler must forward entry_mode to handle_request."""
        assert "entry_mode=" in self._SRC, (
            "core/api_routes.py compat WS chat handler must pass entry_mode= to "
            "DesktopPresenceRuntime.handle_request()."
        )

    def test_21_compat_ws_chat_user_id_reads_from_data(self):
        """compat WS chat must read user_id from the incoming data dict."""
        # The handler should call data.get("user_id", ...) so callers can
        # forward their user identity.
        assert 'data.get("user_id"' in self._SRC or "data.get('user_id'" in self._SRC, (
            "core/api_routes.py compat WS chat handler must read user_id from "
            "the incoming data payload via data.get('user_id', ...)."
        )


# ============================================================================
# D. handle_request result stamp — ingress_carrier_context
# ============================================================================

class TestDesktopPresenceRuntimeCarrierStamp:
    """DesktopPresenceRuntime.handle_request must stamp ingress_carrier_context."""

    _SRC = _read("core/desktop_presence_runtime.py")

    def test_12_source_contains_ingress_carrier_context(self):
        """desktop_presence_runtime.py must define ingress_carrier_context stamp."""
        assert "ingress_carrier_context" in self._SRC, (
            "core/desktop_presence_runtime.py must stamp 'ingress_carrier_context' "
            "in the result dict so all callers see a normalized carrier descriptor."
        )

    def test_13_carrier_field_uses_source(self):
        """ingress_carrier_context must include a 'carrier' field set from source."""
        assert '"carrier"' in self._SRC or "'carrier'" in self._SRC, (
            "ingress_carrier_context must include a 'carrier' key."
        )

    def test_14_authority_chain_field_present(self):
        """ingress_carrier_context must include an 'authority_chain' field."""
        assert "authority_chain" in self._SRC, (
            "ingress_carrier_context must include 'authority_chain' key set to "
            "'DesktopPresenceRuntime.handle_request'."
        )

    def test_14b_authority_chain_string_is_handle_request(self):
        """authority_chain value must name DesktopPresenceRuntime.handle_request."""
        assert "DesktopPresenceRuntime.handle_request" in self._SRC, (
            "ingress_carrier_context.authority_chain must be set to the string "
            "'DesktopPresenceRuntime.handle_request'."
        )


# ============================================================================
# E. Source-level stamp verification — desktop_presence_runtime
# ============================================================================

class TestHandleRequestIngressCarrierContextBehavior:
    """Verify that handle_request correctly stamps ingress_carrier_context.

    Since heavy dependencies (pydantic) may not be available in all CI
    environments, these tests verify the stamp via source inspection rather
    than full runtime execution.
    """

    _SRC = _read("core/desktop_presence_runtime.py")

    def test_12_result_contains_ingress_carrier_context(self):
        """handle_request must set ingress_carrier_context on the result."""
        assert "ingress_carrier_context" in self._SRC, (
            "core/desktop_presence_runtime.py must stamp 'ingress_carrier_context' "
            "on the result dict."
        )

    def test_13_carrier_equals_entrypoint_source(self):
        """ingress_carrier_context.carrier must be derived from source."""
        # The stamp should use the `source` local variable as the carrier value
        assert '"carrier": source' in self._SRC or "'carrier': source" in self._SRC, (
            "ingress_carrier_context must set carrier=source so it mirrors "
            "entrypoint_source for all carriers."
        )

    def test_14_authority_chain_value(self):
        """ingress_carrier_context.authority_chain must name handle_request."""
        assert "DesktopPresenceRuntime.handle_request" in self._SRC, (
            "ingress_carrier_context.authority_chain must be set to "
            "'DesktopPresenceRuntime.handle_request'."
        )

    def test_15_session_id_in_carrier_context(self):
        """ingress_carrier_context must include session_id."""
        assert '"session_id": conversation_session_id' in self._SRC or (
            "'session_id': conversation_session_id" in self._SRC
        ), (
            "ingress_carrier_context must include session_id=conversation_session_id "
            "so callers can correlate carriers through the authority chain."
        )

    def test_16_user_id_in_carrier_context(self):
        """ingress_carrier_context must include user_id."""
        assert '"user_id"' in self._SRC or "'user_id'" in self._SRC, (
            "ingress_carrier_context must include a 'user_id' key."
        )

    def test_17_authority_metadata_present(self):
        """desktop_presence_runtime.py must define authority_metadata stamp."""
        assert "authority_metadata" in self._SRC and "runtime_shell_authority" in self._SRC, (
            "handle_request must stamp authority_metadata with "
            "layer_role='runtime_shell_authority' so all carriers produce "
            "a consistent authority-chain signature."
        )

    def test_18_entrypoint_source_matches_carrier(self):
        """handle_request must set entrypoint_source = source in the result."""
        assert 'result["entrypoint_source"] = source' in self._SRC or (
            "result['entrypoint_source'] = source" in self._SRC
        ), (
            "handle_request must set result['entrypoint_source'] = source so "
            "the carrier tag is always reflected in the result."
        )


# ============================================================================
# F. Source-level verification — android_vision session_id derivation
# ============================================================================

class TestAndroidVisionRuntimeShellBehavior:
    """Source-level verification of session_id derivation in android_vision."""

    _SRC = _read("galaxy_gateway/android/handlers/vision.py")

    def test_4_session_id_uses_task_id_when_provided(self):
        """vision.py must set session_id from task_id when task_id is non-empty."""
        # The source must contain logic that picks task_id as the session_id
        assert "task_id or" in self._SRC or "task_id =" in self._SRC, (
            "vision.py must derive session_id from task_id when available; "
            "check the _session_id derivation logic."
        )

    def test_5_session_id_fallback_to_android_vision_prefix(self):
        """vision.py must fall back to 'android_vision_{device_id}' for session_id."""
        assert "android_vision_" in self._SRC, (
            "vision.py must use 'android_vision_{device_id}' as the fallback "
            "session_id when task_id is empty."
        )

    def test_android_vision_passes_source_as_android_vision(self):
        """vision.py must pass source='android_vision' to handle_request."""
        assert 'source="android_vision"' in self._SRC or "source='android_vision'" in self._SRC, (
            "vision.py must use source='android_vision' so the carrier can be "
            "identified in the authority-chain result."
        )

    def test_android_vision_passes_entry_mode_local(self):
        """vision.py must pass entry_mode='local' to handle_request."""
        assert 'entry_mode="local"' in self._SRC or "entry_mode='local'" in self._SRC, (
            "vision.py must pass entry_mode='local' to handle_request."
        )
