from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_mesh_minimal_closed_loop_is_machine_verifiable() -> None:
    import core.mesh_coordinator as mesh_module
    import core.unified_result_ingress as result_ingress_module
    from core.routes.hybrid import create_router as create_hybrid_router
    from core.routes.projection import create_router as create_projection_router
    from core.unified_result_ingress import (
        NormalizedResultEvent,
        ResultSourceChannel,
        ingest_result,
    )

    async def _mock_relay_send(source: str, target: str, payload_type: str, payload: dict) -> dict:
        return {
            "status": "forwarded",
            "source": source,
            "target": target,
            "payload_type": payload_type,
            "payload": payload,
        }

    old_mesh_singleton = mesh_module._mesh_instance
    old_result_singleton = result_ingress_module._singleton
    mesh_module._mesh_instance = mesh_module.MeshCoordinator(relay_sender=_mock_relay_send)
    result_ingress_module._singleton = None

    try:
        app = FastAPI()
        app.include_router(create_hybrid_router())
        app.include_router(create_projection_router())
        client = TestClient(app)
        mesh_module.get_mesh_coordinator()._relay_send = _mock_relay_send

        task_id = f"task_mesh_loop_{uuid.uuid4().hex[:8]}"

        for device_id, local_ip in (("phone_a", "192.168.1.10"), ("phone_b", "192.168.1.11")):
            resp = client.post(
                "/api/v1/mesh/peer_announce",
                json={
                    "device_id": device_id,
                    "local_ip": local_ip,
                    "local_port": 19720,
                    "metadata": {"platform": "android"},
                },
            )
            assert resp.status_code == 200

        topology_before = client.get("/api/v1/mesh/topology")
        assert topology_before.status_code == 200
        topology_before_body = topology_before.json()
        assert topology_before_body["topology_readiness"] == "ready"
        assert topology_before_body["loop_baseline"]["overlay_coordination"]["authority"] == "mesh_overlay_coordination"
        assert topology_before_body["loop_baseline"]["canonical_closure"]["available"] is False

        send_resp = client.post(
            "/api/v1/mesh/send",
            json={
                "source_device": "phone_a",
                "target_device": "phone_b",
                "payload_type": "task",
                "payload": {"task_id": task_id, "instruction": "capture_screen"},
            },
        )
        assert send_resp.status_code == 200
        send_body = send_resp.json()
        assert send_body["success"] is True

        outcome = ingest_result(
            NormalizedResultEvent(
                task_id=task_id,
                device_id="phone_b",
                raw_message_type="mesh_result",
                normalized_result_kind="goal_execution_result",
                normalized_status="completed",
                source_channel=ResultSourceChannel.DELEGATED,
                payload={"task_id": task_id, "status": "completed", "result": {"ok": True}},
                trace_id=task_id,
            )
        )
        assert outcome.task_id == task_id

        topology_after = client.get("/api/v1/mesh/topology")
        assert topology_after.status_code == 200
        topology_after_body = topology_after.json()
        canonical_closure = topology_after_body["loop_baseline"]["canonical_closure"]
        assert canonical_closure["available"] is True
        assert canonical_closure["task_id"] == task_id
        assert canonical_closure["closure_authority"] == "canonical_result_ingress"
        assert "merged_result_summary" in canonical_closure
        assert (
            topology_after_body["loop_baseline"]["overlay_coordination"]["last_dispatch"]["success"]
            is True
        )

        projection_resp = client.get("/api/v1/projection/runtime/multi-device")
        assert projection_resp.status_code == 200
        projection_body = projection_resp.json()
        mesh_loop_baseline = projection_body["metadata"]["mesh_loop_baseline"]
        assert projection_body["metadata"]["mesh_topology_readiness"] == "ready"
        assert mesh_loop_baseline["overlay_coordination"]["authority"] == "mesh_overlay_coordination"
        assert mesh_loop_baseline["canonical_closure"]["closure_authority"] == "canonical_result_ingress"
        assert mesh_loop_baseline["canonical_closure"]["task_id"] == task_id
    finally:
        mesh_module._mesh_instance = old_mesh_singleton
        result_ingress_module._singleton = old_result_singleton
