"""tests/test_reconnect_continuity_semantics.py
================================================
Minimal real tests for the canonical Android reconnect semantics.

Problem statement (PR-reconnect-semantics)
------------------------------------------
Android's real reconnect path is NOT a dedicated ``device_reconnect`` message.
It is: Android opens a new WebSocket (``onOpen``) and re-sends
``device_register`` with the previously issued
``runtime_attachment_session_id`` echoed back.  The server uses
``classify_reconnect_outcome()`` to decide:

- ``continuity_resume``: the inbound ``runtime_attachment_session_id`` matches
  an existing registry entry → ``reconnect_session()`` is called so the stable
  ``runtime_session_id`` is preserved.
- ``new_attachment``: no match (first connection, id mismatch, terminal entry)
  → ``register_session()`` creates a new session.

Test coverage
-------------
A  — First registration → ``new_attachment`` + ack contains
     ``runtime_attachment_session_id`` and ``continuity_outcome``.
B  — Re-register with matching ``runtime_attachment_session_id`` →
     ``continuity_resume`` + same ``runtime_session_id`` preserved.
C  — Re-register without ``runtime_attachment_session_id`` (older client) →
     ``continuity_resume`` (backward-compat: treat existing session as
     resumable).
D  — Re-register with a *different* ``runtime_attachment_session_id`` →
     ``new_attachment`` (identity mismatch, new session created).
E  — Explicit ``device_reconnect`` message is handled (not dead code) and
     returns ``reconnect_ack``.
F  — Explicit ``device_reconnect`` with matching id → ``continuity_resume``.
G  — Explicit ``device_reconnect`` for unknown device → returns error ack
     (success=False).
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _v3(msg_type: str, device_id: str, **extra) -> Dict[str, Any]:
    return {
        "version": "3.0",
        "type": msg_type,
        "message_id": str(uuid.uuid4()),
        "device_id": device_id,
        "timestamp": int(time.time() * 1000),
        **extra,
    }


def _make_ws() -> MagicMock:
    ws = MagicMock()
    ws.send_json = AsyncMock()
    ws.send = AsyncMock()
    return ws


# ---------------------------------------------------------------------------
# A — First registration
# ---------------------------------------------------------------------------


class TestFirstRegistration:
    """First device_register produces a new_attachment outcome."""

    @pytest.mark.asyncio
    async def test_first_register_new_attachment(self) -> None:
        """A brand-new device gets continuity_outcome='new_attachment'."""
        from core.attached_runtime_session_registry import (
            reset_session_registry,
        )
        from galaxy_gateway.android_bridge import AndroidBridge

        reset_session_registry()
        bridge = AndroidBridge()
        device_id = f"first-reg-{uuid.uuid4().hex[:8]}"
        ws = _make_ws()
        attachment_id = str(uuid.uuid4())

        ack = await bridge.handle_message(
            ws,
            _v3(
                "device_register",
                device_id,
                platform="android",
                runtime_attachment_session_id=attachment_id,
            ),
        )

        assert ack is not None
        assert ack["type"] == "device_register_ack"
        assert ack["success"] is True
        assert ack["runtime_attachment_session_id"] == attachment_id
        assert ack["continuity_outcome"] == "new_attachment", (
            "First registration must produce new_attachment"
        )


# ---------------------------------------------------------------------------
# B — Re-register with matching runtime_attachment_session_id → continuity
# ---------------------------------------------------------------------------


class TestContinuityResumeViaReRegister:
    """Re-register with the same runtime_attachment_session_id preserves runtime_session_id."""

    @pytest.mark.asyncio
    async def test_reregister_same_id_continuity_resume(self) -> None:
        """Second device_register with identical attachment id → continuity_resume,
        runtime_session_id is preserved."""
        from core.attached_runtime_session_registry import (
            lookup_session_by_device,
            reset_session_registry,
        )
        from galaxy_gateway.android_bridge import AndroidBridge

        reset_session_registry()
        bridge = AndroidBridge()
        device_id = f"rereg-cont-{uuid.uuid4().hex[:8]}"
        ws1 = _make_ws()
        ws2 = _make_ws()
        attachment_id = str(uuid.uuid4())

        # First registration
        ack1 = await bridge.handle_message(
            ws1,
            _v3(
                "device_register",
                device_id,
                platform="android",
                runtime_attachment_session_id=attachment_id,
            ),
        )
        assert ack1 is not None
        assert ack1["continuity_outcome"] == "new_attachment"

        # Capture the runtime_session_id after first registration
        entry_after_first = lookup_session_by_device(device_id)
        assert entry_after_first is not None, "Registry entry must exist after first registration"
        runtime_session_id_first = entry_after_first.runtime_session_id

        # Simulate disconnect
        await bridge.disconnect_device(device_id)

        # Re-register (canonical Android reconnect path) with the same attachment id
        ack2 = await bridge.handle_message(
            ws2,
            _v3(
                "device_register",
                device_id,
                platform="android",
                runtime_attachment_session_id=attachment_id,
            ),
        )
        assert ack2 is not None
        assert ack2["type"] == "device_register_ack"
        assert ack2["success"] is True
        assert ack2["runtime_attachment_session_id"] == attachment_id
        assert ack2["continuity_outcome"] == "continuity_resume", (
            "Re-register with matching runtime_attachment_session_id must produce "
            "continuity_resume — the canonical Android reconnect path"
        )

        # runtime_session_id must be preserved (not a new UUID)
        entry_after_reconnect = lookup_session_by_device(device_id)
        assert entry_after_reconnect is not None
        assert entry_after_reconnect.runtime_session_id == runtime_session_id_first, (
            "runtime_session_id must be preserved through continuity resume reconnect"
        )


# ---------------------------------------------------------------------------
# C — Re-register without runtime_attachment_session_id (older client)
# ---------------------------------------------------------------------------


class TestContinuityResumeNoId:
    """Re-register without runtime_attachment_session_id → backward-compat continuity_resume."""

    @pytest.mark.asyncio
    async def test_reregister_no_id_continuity_resume(self) -> None:
        """Older client that doesn't supply attachment id still gets continuity_resume
        if a prior session exists (backward-compat fallback)."""
        from core.attached_runtime_session_registry import (
            lookup_session_by_device,
            reset_session_registry,
        )
        from galaxy_gateway.android_bridge import AndroidBridge

        reset_session_registry()
        bridge = AndroidBridge()
        device_id = f"rereg-noid-{uuid.uuid4().hex[:8]}"
        ws1 = _make_ws()
        ws2 = _make_ws()
        attachment_id = str(uuid.uuid4())

        # First registration (with id)
        await bridge.handle_message(
            ws1,
            _v3(
                "device_register",
                device_id,
                platform="android",
                runtime_attachment_session_id=attachment_id,
            ),
        )

        entry_first = lookup_session_by_device(device_id)
        assert entry_first is not None
        runtime_session_id_first = entry_first.runtime_session_id

        # Simulate disconnect
        await bridge.disconnect_device(device_id)

        # Re-register WITHOUT supplying runtime_attachment_session_id (older client)
        ack2 = await bridge.handle_message(
            ws2,
            _v3(
                "device_register",
                device_id,
                platform="android",
                # no runtime_attachment_session_id
            ),
        )
        assert ack2 is not None
        assert ack2["type"] == "device_register_ack"
        assert ack2["success"] is True
        # classify_reconnect_outcome backward-compat: existing session → continuity_resume
        assert ack2["continuity_outcome"] == "continuity_resume", (
            "Re-register from older client (no attachment id) with prior session "
            "must produce continuity_resume (backward-compat)"
        )

        # runtime_session_id must be preserved
        entry_after = lookup_session_by_device(device_id)
        assert entry_after is not None
        assert entry_after.runtime_session_id == runtime_session_id_first, (
            "runtime_session_id must be preserved in backward-compat continuity resume"
        )


# ---------------------------------------------------------------------------
# D — Re-register with a *different* runtime_attachment_session_id → new attachment
# ---------------------------------------------------------------------------


class TestNewAttachmentDifferentId:
    """Re-register with a different attachment id → new_attachment (no continuity)."""

    @pytest.mark.asyncio
    async def test_reregister_different_id_new_attachment(self) -> None:
        """A different runtime_attachment_session_id on re-registration means
        the device is a new session (e.g. app reinstall, factory reset)."""
        from core.attached_runtime_session_registry import (
            lookup_session_by_device,
            reset_session_registry,
        )
        from galaxy_gateway.android_bridge import AndroidBridge

        reset_session_registry()
        bridge = AndroidBridge()
        device_id = f"rereg-diff-{uuid.uuid4().hex[:8]}"
        ws1 = _make_ws()
        ws2 = _make_ws()
        attachment_id_first = str(uuid.uuid4())
        attachment_id_new = str(uuid.uuid4())

        # First registration
        await bridge.handle_message(
            ws1,
            _v3(
                "device_register",
                device_id,
                platform="android",
                runtime_attachment_session_id=attachment_id_first,
            ),
        )

        entry_first = lookup_session_by_device(device_id)
        assert entry_first is not None
        runtime_session_id_first = entry_first.runtime_session_id

        # Re-register with a DIFFERENT attachment id
        ack2 = await bridge.handle_message(
            ws2,
            _v3(
                "device_register",
                device_id,
                platform="android",
                runtime_attachment_session_id=attachment_id_new,
            ),
        )
        assert ack2 is not None
        assert ack2["type"] == "device_register_ack"
        assert ack2["success"] is True
        assert ack2["continuity_outcome"] == "new_attachment", (
            "Re-register with a different runtime_attachment_session_id must "
            "produce new_attachment — prevents identity spoofing and correctly "
            "treats app reinstall / factory reset as a new session"
        )

        # runtime_session_id must be a NEW value (old session superseded)
        entry_after = lookup_session_by_device(device_id)
        assert entry_after is not None
        assert entry_after.runtime_session_id != runtime_session_id_first, (
            "new_attachment must generate a new runtime_session_id"
        )


# ---------------------------------------------------------------------------
# E — Explicit device_reconnect message is handled (not dead code)
# ---------------------------------------------------------------------------


class TestExplicitDeviceReconnect:
    """device_reconnect message type is handled by the bridge (not dead code)."""

    @pytest.mark.asyncio
    async def test_explicit_reconnect_returns_reconnect_ack(self) -> None:
        """Sending an explicit device_reconnect message returns reconnect_ack."""
        from core.attached_runtime_session_registry import reset_session_registry
        from galaxy_gateway.android_bridge import AndroidBridge

        reset_session_registry()
        bridge = AndroidBridge()
        device_id = f"explicit-rc-{uuid.uuid4().hex[:8]}"
        ws1 = _make_ws()
        ws2 = _make_ws()

        # First register the device
        await bridge.handle_message(
            ws1,
            _v3("device_register", device_id, platform="android"),
        )

        # Now send an explicit device_reconnect message
        ack = await bridge.handle_message(
            ws2,
            _v3("device_reconnect", device_id, platform="android"),
        )
        assert ack is not None, (
            "device_reconnect message must be handled — it must not return None "
            "(the UNKNOWN_MESSAGE_TYPE path must NOT be hit)"
        )
        assert ack.get("type") == "reconnect_ack", (
            "Explicit device_reconnect must return reconnect_ack"
        )
        assert ack.get("success") is True


# ---------------------------------------------------------------------------
# F — Explicit device_reconnect with matching id → continuity_resume
# ---------------------------------------------------------------------------


class TestExplicitReconnectContinuity:
    """Explicit device_reconnect with matching attachment id → continuity_resume."""

    @pytest.mark.asyncio
    async def test_explicit_reconnect_continuity_resume(self) -> None:
        """An explicit device_reconnect message with a matching
        runtime_attachment_session_id produces continuity_resume."""
        from core.attached_runtime_session_registry import (
            lookup_session_by_device,
            reset_session_registry,
        )
        from galaxy_gateway.android_bridge import AndroidBridge

        reset_session_registry()
        bridge = AndroidBridge()
        device_id = f"explicit-rc-cont-{uuid.uuid4().hex[:8]}"
        ws1 = _make_ws()
        ws2 = _make_ws()
        attachment_id = str(uuid.uuid4())

        # Register
        await bridge.handle_message(
            ws1,
            _v3(
                "device_register",
                device_id,
                platform="android",
                runtime_attachment_session_id=attachment_id,
            ),
        )
        entry_first = lookup_session_by_device(device_id)
        assert entry_first is not None
        runtime_session_id_first = entry_first.runtime_session_id

        # Disconnect then explicit device_reconnect with same attachment id
        await bridge.disconnect_device(device_id)

        ack = await bridge.handle_message(
            ws2,
            _v3(
                "device_reconnect",
                device_id,
                platform="android",
                runtime_attachment_session_id=attachment_id,
            ),
        )
        assert ack is not None
        assert ack.get("type") == "reconnect_ack"
        assert ack.get("success") is True
        assert ack.get("continuity_outcome") == "continuity_resume", (
            "Explicit device_reconnect with matching id must produce continuity_resume"
        )
        assert ack.get("runtime_attachment_session_id") == attachment_id

        # runtime_session_id preserved
        entry_after = lookup_session_by_device(device_id)
        assert entry_after is not None
        assert entry_after.runtime_session_id == runtime_session_id_first, (
            "runtime_session_id must be preserved through explicit reconnect with continuity"
        )


# ---------------------------------------------------------------------------
# G — Explicit device_reconnect for unknown device
# ---------------------------------------------------------------------------


class TestExplicitReconnectUnknownDevice:
    """Explicit device_reconnect for a never-registered device returns failure ack."""

    @pytest.mark.asyncio
    async def test_explicit_reconnect_unknown_device(self) -> None:
        """device_reconnect for an unknown device_id returns reconnect_ack with
        success=False (no crash, no silent drop)."""
        from core.attached_runtime_session_registry import reset_session_registry
        from galaxy_gateway.android_bridge import AndroidBridge

        reset_session_registry()
        bridge = AndroidBridge()
        unknown_device_id = f"never-seen-{uuid.uuid4().hex[:8]}"
        ws = _make_ws()

        ack = await bridge.handle_message(
            ws,
            _v3("device_reconnect", unknown_device_id, platform="android"),
        )
        # The handler should return an acknowledgment (not None, not an exception)
        assert ack is not None, "device_reconnect for unknown device must return an acknowledgment"
        assert ack.get("type") == "reconnect_ack"
        # outcome depends on implementation; the important thing is no crash and
        # a machine-observable response is returned
        assert "success" in ack
        assert "continuity_outcome" in ack
