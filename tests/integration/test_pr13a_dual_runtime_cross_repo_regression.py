"""PR-13A dual-runtime cross-repo regression entry points (V2-side)."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Tuple
from unittest.mock import AsyncMock, MagicMock

from core.android_device_state_store import (
    get_device_state_snapshot,
    list_recent_execution_events,
    reset_android_device_state_store,
)
from galaxy_gateway.android_bridge import AndroidBridge

from ._dual_runtime_cross_repo_harness import (
    extract_canonical_android_runtime_messages,
    evidence_declares_real_android_runtime,
    evidence_declares_v2_runtime_participation,
    load_evidence_or_skip,
)


def _make_ws() -> MagicMock:
    ws = MagicMock()
    ws.send_json = AsyncMock()
    ws.send = AsyncMock()
    return ws


def test_cross_repo_evidence_declares_true_dual_runtime_participation() -> None:
    evidence = load_evidence_or_skip()
    assert evidence_declares_real_android_runtime(evidence), (
        "Cross-repo dual-runtime evidence must declare real Android runtime "
        "participation (real_device marker or equivalent)."
    )
    assert evidence_declares_v2_runtime_participation(evidence), (
        "Cross-repo dual-runtime evidence must also prove V2 runtime participation "
        "(explicit dual-runtime marker or V2 ACK evidence)."
    )


async def _replay_canonical_messages(
    bridge: AndroidBridge, ws: Any, messages: list[Dict[str, Any]]
) -> Tuple[str, Dict[str, Dict[str, Any]]]:
    acks: Dict[str, Dict[str, Any]] = {}
    device_id = ""
    for msg in messages:
        device_id = str(msg["device_id"])
        response = await bridge.handle_message(ws, msg)
        if response is not None:
            acks[msg["type"]] = response
    return device_id, acks


def test_cross_repo_evidence_replays_canonical_android_paths_against_v2_runtime() -> None:
    evidence = load_evidence_or_skip()
    messages = extract_canonical_android_runtime_messages(evidence)

    reset_android_device_state_store()
    try:
        bridge = AndroidBridge()
        ws = _make_ws()
        device_id, acks = asyncio.run(_replay_canonical_messages(bridge, ws, messages))

        assert acks["device_register"]["type"] == "device_register_ack"
        assert acks["capability_report"]["type"] == "capability_report_ack"
        assert acks["device_state_snapshot"]["type"] == "device_state_snapshot_ack"
        assert acks["device_execution_event"]["type"] == "device_execution_event_ack"

        state_snapshot = get_device_state_snapshot(device_id)
        assert state_snapshot is not None, (
            "Canonical dual-runtime replay must populate android_device_state_store "
            "with Android-originated runtime snapshot."
        )

        execution_events = list_recent_execution_events(device_id=device_id, limit=1)
        assert execution_events, (
            "Canonical dual-runtime replay must absorb Android execution events "
            "into V2 runtime state."
        )
    finally:
        reset_android_device_state_store()
