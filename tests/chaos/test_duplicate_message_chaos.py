"""
tests/chaos/test_duplicate_message_chaos.py
=============================================
Block-5 Chaos: Duplicate Message / Idempotency Scenarios

Verifies that duplicate commands (same idempotency_key) do NOT produce
duplicate side-effects, and that conflicting payloads are correctly rejected.
"""

from __future__ import annotations

import pytest


def _reset() -> None:
    from core.unified.idempotency import reset_idempotency_store
    from core.unified.release_gate import reset_release_gate

    reset_idempotency_store()
    reset_release_gate()


# ---------------------------------------------------------------------------
# 1. Basic dedup
# ---------------------------------------------------------------------------


class TestDuplicateCommandDedup:
    def setup_method(self):
        _reset()

    def test_first_submission_allowed(self):
        from core.unified.idempotency import check_idempotency, make_payload_hash

        h = make_payload_hash({"action": "open_app", "app": "wechat"})
        entry = check_idempotency("key-001", h, raise_on_duplicate=False)
        assert entry is None  # new key → no entry

    def test_completed_key_raises_duplicate(self):
        from core.unified.idempotency import (
            check_idempotency,
            record_idempotency,
            make_payload_hash,
            DuplicateCommandError,
        )

        h = make_payload_hash({"action": "send_message"})
        record_idempotency("key-002", h, result={"status": "ok"})

        with pytest.raises(DuplicateCommandError) as exc_info:
            check_idempotency("key-002", h, raise_on_duplicate=True)
        assert exc_info.value.key == "key-002"
        assert exc_info.value.cached_result == {"status": "ok"}

    def test_duplicate_returns_cached_result(self):
        from core.unified.idempotency import (
            check_idempotency,
            record_idempotency,
            make_payload_hash,
            DuplicateCommandError,
        )

        h = make_payload_hash({"action": "take_screenshot"})
        record_idempotency("key-003", h, result={"path": "/tmp/screen.png"})

        try:
            check_idempotency("key-003", h)
        except DuplicateCommandError as e:
            assert e.cached_result["path"] == "/tmp/screen.png"

    def test_failed_key_allows_resubmission(self):
        from core.unified.idempotency import (
            check_idempotency,
            get_idempotency_store,
            make_payload_hash,
            IdempotencyStatus,
        )

        h = make_payload_hash({"action": "download_file"})
        store = get_idempotency_store()
        store.record_in_flight("key-004", h)
        store.record_failed("key-004")

        # FAILED key should NOT raise DuplicateCommandError
        entry = check_idempotency("key-004", h, raise_on_duplicate=True)
        assert entry is not None
        assert entry.status == IdempotencyStatus.FAILED

    def test_in_flight_key_does_not_raise(self):
        from core.unified.idempotency import (
            check_idempotency,
            get_idempotency_store,
            make_payload_hash,
            IdempotencyStatus,
        )

        h = make_payload_hash({"action": "process"})
        store = get_idempotency_store()
        store.record_in_flight("key-005", h)

        entry = check_idempotency("key-005", h, raise_on_duplicate=True)
        assert entry is not None
        assert entry.status == IdempotencyStatus.IN_FLIGHT


# ---------------------------------------------------------------------------
# 2. Conflict detection
# ---------------------------------------------------------------------------


class TestIdempotencyConflict:
    def setup_method(self):
        _reset()

    def test_different_payload_same_key_raises_conflict(self):
        from core.unified.idempotency import (
            check_idempotency,
            record_idempotency,
            make_payload_hash,
            IdempotencyConflictError,
        )

        h1 = make_payload_hash({"action": "open_app", "app": "maps"})
        h2 = make_payload_hash({"action": "open_app", "app": "calendar"})

        record_idempotency("key-006", h1, result={"ok": True})

        with pytest.raises(IdempotencyConflictError) as exc_info:
            check_idempotency("key-006", h2, raise_on_conflict=True)
        assert exc_info.value.stored_hash == h1
        assert exc_info.value.received_hash == h2

    def test_conflict_no_raise_mode(self):
        from core.unified.idempotency import (
            check_idempotency,
            record_idempotency,
            make_payload_hash,
        )

        h1 = make_payload_hash({"cmd": "A"})
        h2 = make_payload_hash({"cmd": "B"})
        record_idempotency("key-007", h1, result={})

        # Should not raise
        entry = check_idempotency("key-007", h2, raise_on_conflict=False, raise_on_duplicate=False)
        assert entry is not None


# ---------------------------------------------------------------------------
# 3. Payload hash stability
# ---------------------------------------------------------------------------


class TestPayloadHash:
    def test_same_dict_same_hash(self):
        from core.unified.idempotency import make_payload_hash

        h1 = make_payload_hash({"b": 2, "a": 1})
        h2 = make_payload_hash({"a": 1, "b": 2})
        assert h1 == h2

    def test_different_dict_different_hash(self):
        from core.unified.idempotency import make_payload_hash

        h1 = make_payload_hash({"x": 1})
        h2 = make_payload_hash({"x": 2})
        assert h1 != h2

    def test_none_payload_hashes(self):
        from core.unified.idempotency import make_payload_hash

        h = make_payload_hash(None)
        assert isinstance(h, str) and len(h) == 32

    def test_nested_payload_hashes(self):
        from core.unified.idempotency import make_payload_hash

        h = make_payload_hash({"nested": {"deep": [1, 2, 3]}})
        assert isinstance(h, str)


# ---------------------------------------------------------------------------
# 4. Store stats and capacity
# ---------------------------------------------------------------------------


class TestIdempotencyStoreStats:
    def setup_method(self):
        _reset()

    def test_stats_track_hits_and_misses(self):
        from core.unified.idempotency import (
            check_idempotency,
            record_idempotency,
            get_idempotency_store,
            make_payload_hash,
            DuplicateCommandError,
        )

        h = make_payload_hash({"op": "test"})
        check_idempotency("stat-key-1", h, raise_on_duplicate=False)  # miss
        record_idempotency("stat-key-1", h)
        try:
            check_idempotency("stat-key-1", h)  # hit → duplicate
        except DuplicateCommandError:
            pass

        s = get_idempotency_store().stats()
        assert s["misses"] >= 1
        assert s["hits"] >= 1

    def test_store_size_tracked(self):
        from core.unified.idempotency import (
            record_idempotency,
            get_idempotency_store,
            make_payload_hash,
        )

        for i in range(5):
            record_idempotency(f"sz-key-{i}", make_payload_hash(i))

        s = get_idempotency_store().stats()
        assert s["store_size"] >= 5
