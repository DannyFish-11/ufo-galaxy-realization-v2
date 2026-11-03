"""危险操作的批准不按设备种类写死:设备自己说「我能回答批准」就问它;发起的那台答不了,就由能批的去批(第 15 轮)。

所有者 2026-11-02:「危险操作需授权,就发给那个设备,或者由哪个设备来授权;接受各种生态识别的设备,
不用每一次都要自己加一种设备。」

改之前:「能问谁」是两张写死的种类表 —— 新生态的设备(别家的手表、平板、车机、家居面板)要改代码加进去;
表里的手机其实不会答(安卓 App 不处理 ``decision_request``,第 14 轮只读核对安卓仓),手机发起的危险动作问过去没人显示、白等一个超时。
"""

from __future__ import annotations

import asyncio
import logging
import types
import uuid

import pytest

import core.approval_gate as gate
import core.approvers as approvers
import core.interaction.pending_decision_registry as pdr


def _uid(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _register(device_id, *, device_type="unknown", metadata=None):
    from core.unified.device_manager import get_unified_device_manager
    from core.unified.models import UnifiedDevice, UnifiedDeviceStatus, UnifiedDeviceType

    try:
        utype = UnifiedDeviceType(device_type)
    except ValueError:
        utype = UnifiedDeviceType.UNKNOWN
    get_unified_device_manager().register_device(
        UnifiedDevice(
            device_id=device_id,
            device_name=device_id,
            device_type=utype,
            status=UnifiedDeviceStatus.ONLINE,
            capabilities=[],
            metadata=dict(metadata or {}),
            source="test",
        )
    )


# ── 设备自己的声明 ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "frame, said",
    [
        ({"approvals": True}, True),
        ({"payload": {"approvals": "hitl/1"}}, True),
        ({"metadata": {"approvals": "true"}}, True),
        ({"payload": {"metadata": {"approvals": 1}}}, True),
        ({"approvals": False}, False),
        ({"approvals": "no"}, False),
        ({"supported_actions": ["notify"]}, None),
        ({}, None),
    ],
)
def test_a_device_says_it_in_its_own_words(frame, said):
    assert approvers.declared(frame) is said


@pytest.mark.parametrize("kind", ["harmonyos_watch", "car_head_unit", "ha_panel", "some_new_ecosystem_tablet"])
def test_any_ecosystem_that_declares_is_asked_without_adding_its_kind(kind):
    did = _uid("dev")
    _register(did, metadata={"participant_kind": kind})
    assert approvers.remember(did, {"approvals": True}, source="test") is True
    assert approvers.answers_approvals(did) is True


def test_a_device_that_says_it_cannot_is_not_asked_even_if_it_is_a_watch():
    did = _uid("watch")
    _register(did, metadata={"participant_kind": "wearos"})
    approvers.remember(did, {"approvals": False}, source="test")
    assert approvers.approval_capability(did) is False


def test_without_a_declaration_only_the_shipped_watch_client_counts(monkeypatch):
    monkeypatch.setattr(approvers, "_metadata", lambda did: {})
    monkeypatch.setattr(approvers, "_raw_type", lambda did: "")
    assert approvers.approval_capability("w", "wearos") is True, "已经发出去的手表客户端一直会答"
    assert approvers.approval_capability("p", "android") is False, "现在的手机 App 不处理 decision_request"
    assert approvers.approval_capability("x", "") is None, "一无所知:说不清"
    assert approvers.approval_capability("y", "unknown") is None


def test_participant_registration_records_the_declaration(monkeypatch):
    import core.auth as auth
    from core.participant_admission import ParticipantDescriptor, admit_participant

    monkeypatch.setattr(auth, "get_active_tokens", lambda: ["ADMIN"])
    monkeypatch.setattr(auth, "verify_api_token", lambda t: t == "ADMIN")
    did = _uid("panel")
    message = {"device_id": did, "device_type": "ha_panel", "name": "门口的面板", "approvals": True, "token": "ADMIN"}
    admission = admit_participant(ParticipantDescriptor.from_message(message), message=message)
    assert admission.admitted, admission.to_dict()
    assert approvers.answers_approvals(did) is True


def test_a_rejected_registration_records_nothing(monkeypatch):
    import core.auth as auth
    from core.participant_admission import ParticipantDescriptor, admit_participant

    monkeypatch.setattr(auth, "get_active_tokens", lambda: ["ADMIN"])
    monkeypatch.setattr(auth, "verify_api_token", lambda t: t == "ADMIN")
    did = _uid("intruder")
    message = {"device_id": did, "device_type": "ha_panel", "approvals": True, "token": "wrong"}
    assert not admit_participant(ParticipantDescriptor.from_message(message), message=message).admitted
    assert approvers.approval_capability(did) is None, "没接入的设备说什么都不算"


def test_a_capability_report_records_the_declaration():
    from galaxy_gateway.android.handlers.capability_report import handle_capability_report

    did = _uid("tablet")
    _register(did, metadata={"participant_kind": "harmonyos_tablet"})
    frame = {"type": "capability_report", "device_id": did, "supported_actions": ["notify"], "approvals": True}
    asyncio.run(handle_capability_report(None, None, frame))
    assert approvers.answers_approvals(did) is True


# ── 去问谁 ──────────────────────────────────────────────────────────────


def test_discovery_finds_whoever_declared_and_skips_a_phone_that_cannot_answer(monkeypatch):
    new_kind, phone = _uid("tablet"), _uid("phone")
    _register(new_kind, metadata={"participant_kind": "harmonyos_tablet"})
    approvers.remember(new_kind, {"approvals": True}, source="test")
    _register(phone, metadata={"participant_kind": "android"})

    class _UCM:
        def get_presence_view(self):
            return {d: {"online": True, "routable": True} for d in (new_kind, phone)}

        def get_connection(self, did):
            return types.SimpleNamespace(
                metadata={"device_type": {new_kind: "harmonyos_tablet", phone: "android"}[did]}
            )

    import core.unified.connection_manager as cm

    monkeypatch.setattr(cm, "get_unified_connection_manager", lambda: _UCM())

    class _Legacy:
        async def get_connected_devices(self):
            return []

    monkeypatch.setattr(pdr.upper_ports, "resolve", lambda name: _Legacy())
    found = asyncio.run(pdr._discover_target_devices())
    assert new_kind in found, "新生态的设备说了能批,就问它 —— 不用把它的种类加进代码"
    assert phone not in found, "答不了的不问"


# ── 发起的设备答不了:由能批的去批,并告诉它去哪儿批 ───────────────────────────


@pytest.fixture()
def _isolated(tmp_path, monkeypatch):
    import core.autonomy_policy as ap

    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(ap, "_LEGACY_GRANTS", str(tmp_path / "legacy_grants.json"))
    ap.reset_grant_store()
    monkeypatch.setattr(gate, "publish_pending", lambda: None)
    yield
    ap.reset_grant_store()


def _bind(origin):
    from core.liminal_activity import bind_runtime_session

    return bind_runtime_session(
        types.SimpleNamespace(desktop_originated=False, origin_device_id=origin, runtime_session_id="rt-15")
    )


def _no_confirm_on(origin):
    from core.interaction import high_risk_confirmation as hrc

    asked = []

    async def confirm(**kw):
        asked.append(kw)
        assert origin not in (kw.get("devices") or []), "答不了的那台不该再被问"
        return hrc.ConfirmationOutcome(True, "用户已明确批准", "dec-15", "watch")

    return hrc, confirm, asked


def test_a_phone_request_is_asked_on_the_computer_and_the_phone_is_told(_isolated, monkeypatch):
    phone = _uid("phone")
    told = []
    monkeypatch.setattr(approvers, "approval_capability", lambda did, t="": False if did == phone else None)
    monkeypatch.setattr(gate, "desktop_reachable", lambda: True)
    monkeypatch.setattr(gate, "_tell_origin", lambda did, text: told.append((did, text)))

    async def desktop(key, target, what, risk, sid, params, wait_s):
        return gate.ApprovalOutcome(True, "面板上批了", "desktop", "", "session")

    monkeypatch.setattr(gate, "_ask_desktop", desktop)
    hrc, confirm, asked = _no_confirm_on(phone)
    monkeypatch.setattr(hrc, "confirm_high_risk_tool", confirm)

    async def run():
        _bind(phone)
        return await gate.request_approval(key="node:6:delete", target="/a.txt", what="删 /a.txt")

    out = asyncio.run(run())
    assert out.approved and out.source == "desktop"
    assert asked == [], "答不了的手机不发、不白等一个超时"
    assert told and told[0][0] == phone and "电脑面板" in told[0][1], "告诉手机去哪儿批"


def test_with_no_computer_it_goes_to_another_device_that_can_answer(_isolated, monkeypatch):
    phone = _uid("phone")
    monkeypatch.setattr(approvers, "approval_capability", lambda did, t="": False if did == phone else None)
    monkeypatch.setattr(gate, "desktop_reachable", lambda: False)
    told = []
    monkeypatch.setattr(gate, "_tell_origin", lambda did, text: told.append(text))
    monkeypatch.setattr(pdr, "_discover_target_devices", _async_value(["screen-1"]))
    hrc, confirm, asked = _no_confirm_on(phone)
    monkeypatch.setattr(hrc, "confirm_high_risk_tool", confirm)

    async def run():
        _bind(phone)
        return await gate.request_approval(key="node:6:delete", target="/b.txt", what="删 /b.txt")

    out = asyncio.run(run())
    assert out.approved and out.source == "device"
    assert asked and asked[0]["devices"] is None, "交给发现:问那些声明了能批的设备"
    assert told and "别的能批的设备" in told[0]


def test_with_nowhere_to_ask_it_is_not_done_and_the_origin_hears_why(_isolated, monkeypatch):
    """电脑没开、也没有别的能批的设备在线:不白等、不执行,照实告诉发起的设备 —— 不说「已发到别的设备」。"""
    phone = _uid("phone")
    monkeypatch.setattr(approvers, "approval_capability", lambda did, t="": False if did == phone else None)
    monkeypatch.setattr(gate, "desktop_reachable", lambda: False)
    told = []
    monkeypatch.setattr(gate, "_tell_origin", lambda did, text: told.append(text))
    monkeypatch.setattr(pdr, "_discover_target_devices", _async_value([]))
    hrc, confirm, asked = _no_confirm_on(phone)
    monkeypatch.setattr(hrc, "confirm_high_risk_tool", confirm)

    async def run():
        _bind(phone)
        return await gate.request_approval(key="node:6:delete", target="/c.txt", what="删 /c.txt")

    out = asyncio.run(run())
    assert not out.approved and out.source == "unreachable"
    assert asked == [], "没人可问就不发"
    assert told and "先不做" in told[0] and "已发到" not in told[0]


def _async_value(value):
    async def _f():
        return list(value)

    return _f


def test_an_origin_nobody_knows_anything_about_is_still_asked_there(_isolated, monkeypatch):
    """说不清的照原来的路:在发起的那台上问(所有者定的「从哪发起就在哪批」不因为缺信息就改)。"""
    monkeypatch.setattr(approvers, "approval_capability", lambda did, t="": None)
    monkeypatch.setattr(gate, "desktop_reachable", lambda: True)
    from core.interaction import high_risk_confirmation as hrc

    asked = []

    async def confirm(**kw):
        asked.append(kw)
        return hrc.ConfirmationOutcome(True, "用户已明确批准", "dec-x", "watch")

    monkeypatch.setattr(hrc, "confirm_high_risk_tool", confirm)

    async def run():
        _bind("mystery-1")
        return await gate.request_approval(key="tool:x", what="做 x")

    assert asyncio.run(run()).source == "device" and asked[0]["devices"] == ["mystery-1"]


def test_telling_the_origin_never_blocks_or_raises_without_a_bridge():
    from core.phone_bridge import note_to_device

    assert note_to_device(_uid("nobody"), "x") is False


# ── 设备种类是开放的:每个生态用自己的叫法 ───────────────────────────────────


def test_an_ecosystem_name_is_recorded_but_not_warned_about(caplog):
    from core.protocol_drift_registry import drift_entries
    from galaxy_gateway.android.models import AndroidDevice

    with caplog.at_level(logging.INFO, logger="core.protocol_drift_registry"):
        AndroidDevice.from_registration(
            {"device_id": _uid("w"), "platform": "harmonyos", "device_type": "harmonyos_watch_r15"}
        )
    assert any(e["raw_value"] == "harmonyos_watch_r15" for e in drift_entries()), "照样登记:诊断面看得到见过哪些叫法"
    warned = [r for r in caplog.records if r.levelno >= logging.WARNING and "harmonyos" in r.getMessage()]
    assert warned == [], "每个生态用自己的叫法不是契约分叉,不报协议漂移"


def test_an_unapproved_device_cannot_approve_even_if_it_says_so(monkeypatch):
    """开了设备准入闸:没被主人批准的(降为 control_only)说「我能批」也不算 —— 不能替主人批危险动作。"""
    import core.attached_runtime_session_registry as reg

    did = _uid("stranger")
    _register(did, metadata={"participant_kind": "harmonyos_watch"})
    approvers.remember(did, {"approvals": True}, source="test")
    monkeypatch.setenv("GALAXY_REQUIRE_DEVICE_APPROVAL", "1")
    monkeypatch.setattr(reg, "lookup_session_by_device", lambda d, **k: types.SimpleNamespace(posture="control_only"))
    assert approvers.approval_capability(did) is False
    monkeypatch.setattr(reg, "lookup_session_by_device", lambda d, **k: types.SimpleNamespace(posture="join_runtime"))
    assert approvers.approval_capability(did) is True, "批准之后就能批"
    monkeypatch.setattr(reg, "lookup_session_by_device", lambda d, **k: None)
    assert approvers.approval_capability(did) is False, "闸开着、查不到它的会话:不问它"
    monkeypatch.delenv("GALAXY_REQUIRE_DEVICE_APPROVAL")
    monkeypatch.setattr(reg, "lookup_session_by_device", lambda d, **k: types.SimpleNamespace(posture="control_only"))
    assert approvers.approval_capability(did) is True, "准入闸关着(默认):拿着有效令牌接进来的就是成员"


def test_the_card_says_what_a_new_kind_of_device_calls_itself():
    """分类认不出(别家生态、新种类):设备卡上照它自己报的原话,不是一个 ``unknown`` —— 模型看得出它是什么。"""
    from core.device_onboarding.service import _type_of
    from core.unified.device_manager import get_unified_device_manager
    from galaxy_gateway.android_bridge import AndroidBridge

    did = _uid("screen")
    frame = {"device_id": did, "device_type": "harmonyos_smart_screen", "platform": "harmonyos"}
    AndroidBridge._write_registration_to_udm(types.SimpleNamespace(), did, frame)
    device = get_unified_device_manager().get_device(did)
    assert device is not None and device.aip_device_type in ("", "unknown")
    assert _type_of(device) == "harmonyos_smart_screen"
    assert approvers.approval_capability(did) is False, "没声明、也不是会答的旧客户端:不问它"


def test_a_device_that_says_it_in_its_registration_frame_is_recorded():
    """登记帧里就说了(还没报能力)也算 —— 声明在哪一帧里说都一样。"""
    from galaxy_gateway.android_bridge import AndroidBridge

    did = _uid("car")
    frame = {"device_id": did, "device_type": "vehicle_head_unit", "platform": "linux", "approvals": True}
    AndroidBridge._write_registration_to_udm(types.SimpleNamespace(), did, frame)
    assert approvers.approval_capability(did) is True
