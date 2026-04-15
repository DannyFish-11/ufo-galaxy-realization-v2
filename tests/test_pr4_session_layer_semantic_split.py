from core.attached_runtime_session import AttachedRuntimeSessionRecord, attach_runtime_session
from core.canonical_session_truth import CanonicalSessionTruthRecord, record_session_truth
from core.delegated_runtime_handoff_contract import DelegatedHandoffContractIdentity
from core.session_manager import Session
from contracts.runtime_session_snapshot import (
    build_runtime_session_snapshot,
    from_target_takeover_result,
)


def test_conversation_session_alias_maps_to_session_manager_identity() -> None:
    session = Session(id="conv_001", user_id="u1")
    assert session.conversation_session_id == "conv_001"


def test_canonical_session_truth_prefers_runtime_attachment_session_alias() -> None:
    record = record_session_truth(
        session_id="legacy_session",
        runtime_attachment_session_id="rt_attach_001",
        result_units=[],
    )
    assert record.session_id == "rt_attach_001"
    assert record.runtime_attachment_session_id == "rt_attach_001"


def test_attached_runtime_accepts_runtime_attachment_session_alias() -> None:
    rec = attach_runtime_session(
        "dev_001",
        source_runtime_posture="join_runtime",
        runtime_attachment_session_id="rt_attach_002",
    )
    assert rec.session_id == "rt_attach_002"
    assert rec.runtime_attachment_session_id == "rt_attach_002"


def test_attached_runtime_record_from_dict_accepts_runtime_attachment_session_id() -> None:
    rec = AttachedRuntimeSessionRecord.from_dict(
        {"device_id": "dev_001", "runtime_attachment_session_id": "rt_attach_003"}
    )
    assert rec.session_id == "rt_attach_003"


def test_handoff_identity_accepts_delegation_transfer_session_alias() -> None:
    identity = DelegatedHandoffContractIdentity.from_dict(
        {"delegation_transfer_session_id": "xfer_001", "device_id": "dev_02"}
    )
    assert identity.session_id == "xfer_001"
    assert identity.delegation_transfer_session_id == "xfer_001"


def test_runtime_session_snapshot_accepts_runtime_attachment_session_alias() -> None:
    snap = build_runtime_session_snapshot(runtime_attachment_session_id="rt_attach_004")
    assert snap.session_id == "rt_attach_004"
    assert snap.runtime_attachment_session_id == "rt_attach_004"

    takeover_snap = from_target_takeover_result({"runtime_attachment_session_id": "rt_attach_005"})
    assert takeover_snap.session_id == "rt_attach_005"


def test_canonical_session_truth_record_alias_property() -> None:
    rec = CanonicalSessionTruthRecord(session_id="rt_attach_006")
    assert rec.runtime_attachment_session_id == "rt_attach_006"
