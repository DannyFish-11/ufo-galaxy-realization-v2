"""tests/test_audit_hash_chain.py
====================================

审计账本防篡改哈希链:每条哈希【自身内容 + 前一条 entry_hash】,改任意一条 → 链断。
"""
from __future__ import annotations

from core.control_plane.audit_ledger import AuditLedger, EventType


def _ledger(n: int = 5) -> AuditLedger:
    lg = AuditLedger()
    et = list(EventType)[0]
    for i in range(n):
        lg.append(et, message=f"event-{i}", payload={"i": i})
    return lg


class TestHashChain:
    def test_fresh_chain_intact(self):
        v = _ledger().verify_chain()
        assert v["intact"] and v["count"] == 5 and v["broken_at"] is None

    def test_seq_and_prev_hash_linked(self):
        lg = _ledger(3)
        evs = lg._events
        assert [e.seq for e in evs] == [0, 1, 2]
        assert evs[0].prev_hash == "0" * 64            # 创世
        assert evs[1].prev_hash == evs[0].entry_hash    # 链接
        assert evs[2].prev_hash == evs[1].entry_hash

    def test_tamper_message_breaks_chain(self):
        lg = _ledger(5)
        lg._events[2] = lg._events[2].model_copy(update={"message": "TAMPERED"})
        v = lg.verify_chain()
        assert not v["intact"] and v["broken_at"] == 2

    def test_tamper_payload_breaks_chain(self):
        lg = _ledger(4)
        lg._events[1] = lg._events[1].model_copy(update={"payload": {"i": 999}})
        assert lg.verify_chain()["broken_at"] == 1

    def test_delete_event_breaks_chain(self):
        lg = _ledger(5)
        del lg._events[2]                               # 删一条 → 后续 prev_hash 对不上
        v = lg.verify_chain()
        assert not v["intact"] and v["broken_at"] == 2

    def test_empty_ledger_intact(self):
        assert AuditLedger().verify_chain()["intact"]

    def test_entry_hash_is_deterministic_content_hash(self):
        lg = _ledger(1)
        e = lg._events[0]
        assert e.entry_hash == e.compute_hash() and len(e.entry_hash) == 64
