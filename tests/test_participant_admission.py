"""tests/test_participant_admission.py — 参与方接入通用化（R7 · 架构冻结计划 P3）。

验收判据（改良书 R7）：**一台非安卓设备能完成注册 + 提交任务 + 进 mesh，全程不经过
任何安卓命名的模块。** 最后那半句在一个全新的解释器里用 ``sys.setprofile`` 逐帧验 ——
同进程里别的测试早已把安卓模块导入，查 ``sys.modules`` 什么也证明不了。

另外钉住：

* 真相链第 1 步调的是通用入口；不声明族的消息照旧落到安卓实现（行为逐位不变）；
* 安卓的每一种真相都有通用对应；安卓实现满足通用协议；
* 鉴权与准入闸与安卓注册路径是**同一份**代码（不是复制品）；
* 参与方提交的任务不是电脑发起的：入口分流判为不进桌面三态；
* 附着记录、心跳、断开写的是安卓路径写的同一批模块，全程同样不经安卓命名模块。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from core import participant_admission as pa
from core import participant_truth_ingress as pti

REPO_ROOT = Path(__file__).resolve().parent.parent


def _token() -> str:
    return os.environ.get("GALAXY_API_TOKEN", "")


def _device(prefix: str = "ipad") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# 真相入口的通用接口
# ---------------------------------------------------------------------------


def test_every_android_truth_kind_has_a_generic_counterpart():
    from core.android_participant_truth_ingress import AndroidParticipantTruthKind

    generic = {k.value for k in pti.ParticipantTruthKind}
    assert {k.value for k in AndroidParticipantTruthKind} <= generic
    assert pti.ParticipantTruthKind.from_string(" RESULT ") is pti.ParticipantTruthKind.result
    assert pti.ParticipantTruthKind.from_string("nonsense") is pti.ParticipantTruthKind.unknown


def test_android_implementation_conforms_to_the_protocol():
    impl = pti.resolve_participant_truth_ingress("android")
    assert isinstance(impl, pti.ParticipantTruthIngressProtocol)
    assert impl.participant_family == "android"


def test_truth_chain_step_one_calls_the_generic_entry():
    import core.task_result_canonical_truth_chain as ttc

    assert ttc._ingest_participant_truth is pti.ingest_participant_truth_message


@pytest.mark.parametrize("message", [{"task_id": "t"}, {"task_id": "t", "participant_family": "ios"}])
def test_messages_without_a_dedicated_family_still_reach_the_android_implementation(message):
    sentinel = object()
    with patch(
        "core.android_participant_truth_ingress.ingest_android_participant_truth_message", return_value=sentinel
    ) as android:
        assert pti.ingest_participant_truth_message(message) is sentinel
    android.assert_called_once_with(message, runtime=None, registry=None)


def test_a_registered_family_gets_its_own_implementation(monkeypatch):
    seen = []

    class _Ios:
        participant_family = "ios"

        def ingest(self, message, *, runtime=None, registry=None):
            seen.append(message)
            return "ios-outcome"

    monkeypatch.setitem(pti.PARTICIPANT_TRUTH_INGRESS, "ios", _Ios)
    with patch("core.android_participant_truth_ingress.ingest_android_participant_truth_message") as android:
        assert pti.ingest_participant_truth_message({"payload": {"participant_family": "iOS"}}) == "ios-outcome"
    android.assert_not_called()
    assert len(seen) == 1


# ---------------------------------------------------------------------------
# 鉴权与准入闸：与安卓注册路径同一份
# ---------------------------------------------------------------------------


def test_android_registration_uses_the_same_gate_code():
    from galaxy_gateway.android.handlers import registration

    assert registration._evaluate_ingress_authentication is pa.evaluate_ingress_authentication
    assert registration._evaluate_ingress_identity is pa.evaluate_ingress_identity
    assert registration._should_gate_unapproved is pa.should_gate_unapproved


def test_descriptor_parses_payload_and_derives_roles():
    d = pa.ParticipantDescriptor.from_message(
        {"payload": {"device_id": " x1 ", "device_type": "iOS", "capabilities": ["Camera", "screen", "touch"]}}
    )
    assert (d.device_id, d.device_type) == ("x1", "ios")
    assert d.body_mesh_roles() == ["perception", "action", "presence"]
    assert pa.ParticipantDescriptor(device_id="y", device_type="linux").body_mesh_roles() == ["action"]
    bad_posture = pa.ParticipantDescriptor.from_message({"device_id": "z", "runtime_posture": "admin"})
    assert bad_posture.runtime_posture == "join_runtime"


def test_missing_token_is_rejected_when_auth_is_enforced(monkeypatch):
    import core.auth as auth

    monkeypatch.setattr(auth, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(auth, "get_active_tokens", lambda: ["ADMIN"])
    monkeypatch.setattr(auth, "verify_api_token", lambda t: t == "ADMIN")
    descriptor = pa.ParticipantDescriptor(device_id=_device(), device_type="ios")

    rejected = pa.admit_participant(descriptor)
    assert rejected.admitted is False and rejected.error_code == "INGRESS_AUTHENTICATION_FAILED"
    assert pa.admitted_participant(descriptor.device_id) is None, "被拒的设备不得写进事实来源"

    stolen = pa.admit_participant(descriptor, message={"token": "someone-elses-token"})
    assert stolen.error_code == "INGRESS_AUTHENTICATION_FAILED"


def test_identity_mismatch_is_rejected():
    descriptor = pa.ParticipantDescriptor(device_id=_device(), device_type="ios")
    outcome = pa.admit_participant(descriptor, message={"token": _token()}, websocket_device_id="another")
    assert outcome.error_code == "INGRESS_IDENTITY_MISMATCH"


def test_unapproved_device_is_demoted_to_control_only(monkeypatch):
    import core.auth as auth

    monkeypatch.setenv("GALAXY_REQUIRE_DEVICE_APPROVAL", "1")
    monkeypatch.setattr(auth, "is_auth_enabled", lambda: False)
    outcome = pa.admit_participant(pa.ParticipantDescriptor(device_id=_device("box"), device_type="linux"))
    assert outcome.admitted is True and outcome.runtime_posture == "control_only"


# ---------------------------------------------------------------------------
# 接入 + 进 mesh + 提交任务
# ---------------------------------------------------------------------------


def test_a_non_android_device_joins_the_mesh():
    from core.mesh.body_mesh_registry import get_body_mesh_registry
    from core.mesh.mesh_session_lifecycle import reset_lifecycle_coordinator
    from core.mesh_coordinator import get_mesh_coordinator

    reset_lifecycle_coordinator()
    device_id = _device()
    descriptor = pa.ParticipantDescriptor(
        device_id=device_id,
        device_type="ios",
        name="iPad",
        capabilities=("camera", "screen", "touch"),
        tailscale_ip="100.64.0.9",
    )
    outcome = pa.admit_participant(descriptor, message={"token": _token()})

    assert outcome.admitted and outcome.fully_attached, outcome.to_dict()
    assert set(outcome.steps) == {
        "udm",
        "mesh_peer",
        "mesh_session",
        "runtime_session",
        "body_mesh",
        "capability_assimilation",
        "lifecycle_event",
    }
    record = pa.admitted_participant(device_id)
    assert record is not None and record.metadata["participant_kind"] == "ios"
    assert device_id in get_mesh_coordinator()._peers
    assert get_body_mesh_registry().get(device_id) is not None
    assert outcome.mesh_session_id and outcome.runtime_session_id


def test_participant_tasks_are_decided_as_a_remote_body():
    from core.presence_line import decide_presence_line

    decision = decide_presence_line(pa.PARTICIPANT_TASK_SOURCE, "ipad-1")
    assert decision.host_bound is False and decision.reason == "remote_source"


def test_raw_kind_outside_the_udm_enum_is_still_recognised_as_remote():
    from core.presence_line import is_local_body

    device_id = _device("watch")
    assert pa.admit_participant(
        pa.ParticipantDescriptor(device_id=device_id, device_type="wear_os"), message={"token": _token()}
    ).admitted
    assert is_local_body(device_id) is False


def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.routes.participants import create_router

    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app)


def test_routes_register_submit_and_list():
    client = _client()
    device_id = _device()
    headers = {"Authorization": f"Bearer {_token()}"}

    reg = client.post(
        "/api/v1/participants/register",
        json={"device_id": device_id, "device_type": "ios", "capabilities": ["screen"]},
        headers=headers,
    )
    assert reg.status_code == 200 and reg.json()["admitted"] is True

    fake = AsyncMock(return_value={"success": True, "response": "ok"})
    with patch("core.desktop_presence_runtime.DesktopPresenceRuntime.handle_request", fake):
        task = client.post(f"/api/v1/participants/{device_id}/tasks", json={"message": "查快递"}, headers=headers)
        stranger = client.post(f"/api/v1/participants/{_device()}/tasks", json={"message": "x"}, headers=headers)
        empty = client.post(f"/api/v1/participants/{device_id}/tasks", json={"message": " "}, headers=headers)
    assert task.status_code == 200 and task.json()["success"] is True
    kwargs = fake.await_args.kwargs
    assert kwargs["source"] == pa.PARTICIPANT_TASK_SOURCE and kwargs["device_id"] == device_id
    assert stranger.status_code == 404 and stranger.json()["error_code"] == "PARTICIPANT_NOT_ADMITTED"
    assert empty.status_code == 400

    listed = client.get("/api/v1/participants", headers=headers)
    assert listed.status_code == 200
    assert device_id in {p["device_id"] for p in listed.json()["participants"]}


def test_routes_reject_a_registration_without_credentials(monkeypatch):
    import core.auth as auth

    monkeypatch.setattr(auth, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(auth, "get_active_tokens", lambda: ["ADMIN"])
    monkeypatch.setattr(auth, "verify_api_token", lambda t: t == "ADMIN")
    resp = _client().post("/api/v1/participants/register", json={"device_id": _device(), "device_type": "ios"})
    assert resp.status_code == 401 and resp.json()["error_code"] == "INGRESS_AUTHENTICATION_FAILED"


def test_participant_routes_are_mounted_on_the_device_group():
    from fastapi import FastAPI

    from core.routes import devices

    app = FastAPI()
    app.include_router(devices.create_router())
    paths = set(app.openapi()["paths"])
    assert {
        "/api/v1/participants/register",
        "/api/v1/participants/{device_id}/tasks",
        "/api/v1/participants/{device_id}/heartbeat",
        "/api/v1/participants/{device_id}/disconnect",
    } <= paths


def _admit(device_id: str, **kw):
    descriptor = pa.ParticipantDescriptor(device_id=device_id, device_type=kw.pop("device_type", "ios"), **kw)
    admission = pa.admit_participant(descriptor, message={"token": _token()})
    assert admission.admitted, admission.to_dict()
    return admission


def test_admission_writes_the_same_attach_records_as_the_android_path():
    """registry 铸身份，生命周期投影接收同一个 id —— 状态面读的是投影，通用参与方不能缺席。"""
    from core.attached_runtime_session import get_attached_runtime_session
    from core.attached_runtime_session_registry import lookup_session_by_device

    device_id = _device()
    assert _admit(device_id).steps["runtime_session"] is True
    entry = lookup_session_by_device(device_id)
    record = get_attached_runtime_session(device_id)
    assert entry is not None and record is not None
    assert record.attach_reason == pa.ADMISSION_SOURCE
    assert record.session_id == entry.runtime_attachment_session_id != ""


def test_heartbeat_and_disconnect_move_the_same_facts():
    from core.attached_runtime_session_registry import lookup_session_by_device
    from core.unified.device_manager import get_unified_device_manager

    device_id = _device()
    _admit(device_id)
    creds = {"token": _token()}
    assert pa.participant_heartbeat(device_id, credentials=creds)["success"] is True
    assert get_unified_device_manager().get_device(device_id).last_heartbeat is not None

    left = pa.participant_disconnect(device_id, credentials=creds)
    assert left["success"] is True and left["steps"]["udm"] and left["steps"]["runtime_session"]
    status = get_unified_device_manager().get_device(device_id).status
    assert str(getattr(status, "value", status)) == "disconnected", "断开是标状态，不删身份"
    assert lookup_session_by_device(device_id) is None, "附着会话已摘除"

    pa.participant_heartbeat(device_id, credentials=creds)
    status = get_unified_device_manager().get_device(device_id).status
    assert str(getattr(status, "value", status)) == "online", "回来发心跳就恢复在线"


def test_heartbeat_and_disconnect_refuse_strangers_and_bad_tokens(monkeypatch):
    stranger = _device()
    assert pa.participant_heartbeat(stranger)["error_code"] == "PARTICIPANT_NOT_ADMITTED"
    assert pa.participant_disconnect(stranger)["error_code"] == "PARTICIPANT_NOT_ADMITTED"

    device_id = _device()
    _admit(device_id)
    import core.auth as auth

    monkeypatch.setattr(auth, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(auth, "get_active_tokens", lambda: ["ADMIN"])
    monkeypatch.setattr(auth, "verify_api_token", lambda t: t == "ADMIN")
    assert pa.participant_disconnect(device_id, credentials={"token": "wrong"})["error_code"] == (
        "INGRESS_AUTHENTICATION_FAILED"
    )
    assert pa.participant_heartbeat(device_id, credentials={"token": "ADMIN"})["success"] is True


def test_heartbeat_and_disconnect_routes():
    client = _client()
    device_id = _device()
    headers = {"Authorization": f"Bearer {_token()}"}
    client.post("/api/v1/participants/register", json={"device_id": device_id, "device_type": "linux"}, headers=headers)
    assert client.post(f"/api/v1/participants/{device_id}/heartbeat", headers=headers).status_code == 200
    assert client.post(f"/api/v1/participants/{device_id}/disconnect", headers=headers).json()["success"] is True
    assert client.post(f"/api/v1/participants/{_device()}/heartbeat", headers=headers).status_code == 404


_TRACE_SCRIPT = textwrap.dedent("""
    import asyncio, json, os, sys, uuid
    sys.path.insert(0, {root!r})
    touched = set()

    def _profile(frame, event, arg):
        if event == "call":
            name = frame.f_code.co_filename.replace(os.sep, "/")
            if name.startswith({root!r}) and "android" in name[len({root!r}):].lower():
                touched.add(name[len({root!r}) + 1:])

    import core.desktop_presence_runtime as dpr

    async def _fake_handle_request(self, **kwargs):
        return {{"success": True, "source": kwargs["source"]}}

    dpr.DesktopPresenceRuntime.handle_request = _fake_handle_request

    sys.setprofile(_profile)
    from core.participant_admission import ParticipantDescriptor, admit_participant, submit_participant_task

    device_id = "ipad_" + uuid.uuid4().hex[:8]
    token = os.environ.get("GALAXY_API_TOKEN", "")
    admission = admit_participant(
        ParticipantDescriptor(device_id=device_id, device_type="ios", capabilities=("screen", "touch"),
                              tailscale_ip="100.64.0.7"),
        message={{"token": token}},
    )
    result = asyncio.run(submit_participant_task(device_id, "hello", credentials={{"token": token}}))
    from core.participant_admission import participant_disconnect, participant_heartbeat

    beat = participant_heartbeat(device_id, credentials={{"token": token}})
    left = participant_disconnect(device_id, credentials={{"token": token}})
    sys.setprofile(None)
    print(json.dumps({{"admission": admission.to_dict(), "result": result, "beat": beat, "left": left,
                      "touched": sorted(touched)}}))
    """)


def test_the_whole_flow_never_touches_an_android_named_module(tmp_path):
    """验收判据本身：新解释器里从零导入，逐帧记录执行过的文件。"""
    script = tmp_path / "trace_participant.py"
    script.write_text(_TRACE_SCRIPT.format(root=str(REPO_ROOT)), encoding="utf-8")
    env = dict(os.environ, GALAXY_API_TOKEN=_token() or "galaxy-test-token")
    proc = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, timeout=300, cwd=str(tmp_path), env=env
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    report = json.loads(proc.stdout.strip().splitlines()[-1])
    assert report["admission"]["admitted"] is True, report["admission"]
    assert "mesh_peer" in report["admission"]["steps"] and not report["admission"]["gaps"], report["admission"]
    assert report["result"] == {"success": True, "source": "participant_task"}
    assert report["beat"]["success"] is True
    assert report["left"]["success"] is True and not report["left"]["gaps"], report["left"]
    assert report["touched"] == [], f"通用接入路径经过了安卓命名的模块: {report['touched']}"
