from __future__ import annotations

import time
import uuid

import pytest

try:
    from core.android_evaluator_artifact_ingress import (
        AndroidEvaluatorArtifactKind,
        get_evaluator_artifact_registry,
        reset_evaluator_artifact_registry,
    )
    from galaxy_gateway.android_bridge import AndroidBridge
    from galaxy_gateway.protocol.aip_v3 import MessageType

    _AVAILABLE = True
except (ImportError, ModuleNotFoundError):  # pragma: no cover
    _AVAILABLE = False

_skip_if_unavailable = pytest.mark.skipif(
    not _AVAILABLE, reason="android evaluator bridge ingress dependencies unavailable"
)


def _msg(msg_type: str, device_id: str, payload: dict) -> dict:
    return {
        "version": "3.0",
        "type": msg_type,
        "device_id": device_id,
        "timestamp": int(time.time()),
        "message_id": str(uuid.uuid4()),
        "payload": payload,
    }


@_skip_if_unavailable
def test_report_handlers_are_not_generic_forward() -> None:
    bridge = AndroidBridge()
    generic_handler = bridge._message_handlers[MessageType.AGENT_CONFIG_UPDATE]
    for mt in (
        MessageType.DEVICE_READINESS_REPORT,
        MessageType.DEVICE_GOVERNANCE_REPORT,
        MessageType.DEVICE_STRATEGY_REPORT,
    ):
        assert bridge._message_handlers[mt] is not generic_handler


@pytest.mark.asyncio
@_skip_if_unavailable
@pytest.mark.parametrize(
    ("msg_type", "kind"),
    [
        ("device_readiness_report", AndroidEvaluatorArtifactKind.readiness),
        ("device_governance_report", AndroidEvaluatorArtifactKind.governance),
        ("device_strategy_report", AndroidEvaluatorArtifactKind.strategy),
    ],
)
async def test_report_ingresses_to_evaluator_registry(msg_type: str, kind: AndroidEvaluatorArtifactKind) -> None:
    reset_evaluator_artifact_registry()
    bridge = AndroidBridge()
    device_id = f"dev-{msg_type}"
    payload = {
        "session_id": "s-1",
        "contract_id": "c-1",
        "trace_id": "t-1",
        "is_compliant": True,
        "verdict": "ok",
    }
    resp = await bridge.handle_message(None, _msg(msg_type, device_id, payload))

    assert resp is not None
    assert resp.get("type") == f"{msg_type}_ack"
    assert resp.get("evaluator_artifact_ingested") is True
    assert resp.get("evaluator_kind") == kind.value

    stored = get_evaluator_artifact_registry().get_latest_for_device_kind(device_id, kind)
    assert stored is not None
    assert stored.kind == kind
    assert stored.device_id == device_id


@pytest.mark.asyncio
@_skip_if_unavailable
async def test_acceptance_report_keeps_evidence_ingest_and_canonical_evaluator_ingress() -> None:
    reset_evaluator_artifact_registry()
    bridge = AndroidBridge()
    device_id = "dev-acceptance"
    resp = await bridge.handle_message(
        None,
        _msg(
            "device_acceptance_report",
            device_id,
            {
                "acceptance_tag": "device_accepted_for_graduation",
                "dimension_states": {"governance": "pass", "readiness": "pass"},
                "session_id": "s-acc",
                "contract_id": "c-acc",
                "trace_id": "t-acc",
                "is_compliant": True,
                "verdict": "accepted",
            },
        ),
    )

    assert resp is not None
    assert resp.get("acceptance_evidence_ingested") is True
    assert resp.get("evaluator_artifact_ingested") is True
    assert resp.get("evaluator_kind") == "acceptance"
    stored = get_evaluator_artifact_registry().get_latest_for_device_kind(
        device_id, AndroidEvaluatorArtifactKind.acceptance
    )
    assert stored is not None
