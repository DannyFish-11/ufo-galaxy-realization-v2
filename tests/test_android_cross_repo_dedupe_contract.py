from core.reliability_contract import (
    ANDROID_UPLINK_RECONCILIATION_DEDUP_KEY,
    ANDROID_UPLINK_REPLAY_DEDUP_KEY,
    ANDROID_UPLINK_RESULT_DEDUP_KEY,
)


def test_android_result_dedup_key_is_enforced_and_stable() -> None:
    assert ANDROID_UPLINK_RESULT_DEDUP_KEY.enforced is True
    assert ANDROID_UPLINK_RESULT_DEDUP_KEY.fields == [
        "task_id",
        "idempotency_key",
        "completion_emission_id",
    ]
    assert ANDROID_UPLINK_RESULT_DEDUP_KEY.composition == ("<task_id>:<idempotency_key>:<completion_emission_id>")


def test_android_reconciliation_dedup_key_documents_layered_identity() -> None:
    assert ANDROID_UPLINK_RECONCILIATION_DEDUP_KEY.enforced is False
    assert ANDROID_UPLINK_RECONCILIATION_DEDUP_KEY.fields == [
        "contract_id|session_id",
        "reconciliation_id|signal_id|handoff_id",
    ]


def test_android_replay_dedup_key_requires_queue_identity_and_ordering() -> None:
    assert ANDROID_UPLINK_REPLAY_DEDUP_KEY.enforced is True
    assert ANDROID_UPLINK_REPLAY_DEDUP_KEY.fields == [
        "replay_session_id",
        "replay_item_id",
        "replay_seq",
    ]
