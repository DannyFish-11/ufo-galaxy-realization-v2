"""
tests/test_current_state_backbone_audit.py
==========================================
Tests for core/current_state_backbone_audit.py

Validates the current-state backbone audit module:
- Authority sentinels and contract version
- ClosureState / ChainId / ModeId enum correctness
- ChainMap structure and all five chains present
- ModeMap structure and all six modes present
- BackboneSnapshot three-way separation (established/partial/open)
- build_system_backbone_snapshot() operator/board API
- Serialization (to_dict) round-trips
"""
from __future__ import annotations

import time
from typing import Any, Dict, List

import pytest

from core.current_state_backbone_audit import (
    ANDROID_AUDITED_REF,
    CURRENT_STATE_BACKBONE_AUDIT_AUTHORITY,
    CURRENT_STATE_BACKBONE_CONTRACT_VERSION,
    BackboneItem,
    BackboneSnapshot,
    ChainId,
    ChainMap,
    ChainSegment,
    ClosureState,
    ModeEntry,
    ModeId,
    ModeMap,
    build_backbone_snapshot,
    build_chain_map,
    build_mode_map,
    build_system_backbone_snapshot,
)


# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------


class TestAuthoritySentinels:
    def test_authority_string_non_empty(self):
        assert isinstance(CURRENT_STATE_BACKBONE_AUDIT_AUTHORITY, str)
        assert len(CURRENT_STATE_BACKBONE_AUDIT_AUTHORITY) > 20
        assert "CURRENT_STATE_BACKBONE_AUDIT" in CURRENT_STATE_BACKBONE_AUDIT_AUTHORITY

    def test_contract_version_format(self):
        assert isinstance(CURRENT_STATE_BACKBONE_CONTRACT_VERSION, str)
        parts = CURRENT_STATE_BACKBONE_CONTRACT_VERSION.split(".")
        assert len(parts) == 3
        for part in parts:
            assert part.isdigit()

    def test_android_audited_ref_format(self):
        assert isinstance(ANDROID_AUDITED_REF, str)
        assert len(ANDROID_AUDITED_REF) == 40
        assert all(c in "0123456789abcdef" for c in ANDROID_AUDITED_REF)


# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


class TestClosureStateEnum:
    def test_all_three_states_present(self):
        values = {s.value for s in ClosureState}
        assert "established" in values
        assert "partial" in values
        assert "open" in values

    def test_string_comparison(self):
        assert ClosureState.ESTABLISHED == "established"
        assert ClosureState.PARTIAL == "partial"
        assert ClosureState.OPEN == "open"


class TestChainIdEnum:
    def test_all_five_chains_present(self):
        expected = {
            "request_chain",
            "execution_chain",
            "result_backflow_chain",
            "closure_acceptance_chain",
            "projection_chain",
        }
        actual = {c.value for c in ChainId}
        assert expected == actual


class TestModeIdEnum:
    def test_all_six_modes_present(self):
        expected = {
            "local_mode",
            "cross_device_mode",
            "multi_device_participation",
            "delegated_execution",
            "takeover",
            "distributed_participant",
        }
        actual = {m.value for m in ModeId}
        assert expected == actual


# ---------------------------------------------------------------------------
# ChainSegment tests
# ---------------------------------------------------------------------------


class TestChainSegment:
    def _make_segment(self, state: ClosureState = ClosureState.ESTABLISHED) -> ChainSegment:
        return ChainSegment(
            name="测试环节",
            v2_anchor="core.test_module",
            android_anchor="test/Android.kt",
            closure_state=state,
            notes="测试说明",
        )

    def test_to_dict_has_required_keys(self):
        seg = self._make_segment()
        d = seg.to_dict()
        assert "name" in d
        assert "v2_anchor" in d
        assert "android_anchor" in d
        assert "closure_state" in d
        assert "notes" in d

    def test_closure_state_serializes_as_value(self):
        seg = self._make_segment(ClosureState.PARTIAL)
        assert seg.to_dict()["closure_state"] == "partial"


# ---------------------------------------------------------------------------
# build_chain_map() tests
# ---------------------------------------------------------------------------


class TestBuildChainMap:
    def setup_method(self):
        self.chain_map = build_chain_map()

    def test_returns_chain_map_instance(self):
        assert isinstance(self.chain_map, ChainMap)

    def test_all_five_chains_present(self):
        for chain_id in ChainId:
            assert chain_id.value in self.chain_map.chains, (
                f"Missing chain: {chain_id.value}"
            )

    def test_each_chain_has_at_least_two_segments(self):
        for chain_id in ChainId:
            segs = self.chain_map.chains[chain_id.value]
            assert len(segs) >= 2, (
                f"Chain {chain_id.value} has fewer than 2 segments"
            )

    def test_overall_closure_computed_for_all_chains(self):
        for chain_id in ChainId:
            assert chain_id.value in self.chain_map.overall_closure_by_chain
            val = self.chain_map.overall_closure_by_chain[chain_id.value]
            assert val in {"established", "partial", "open"}

    def test_request_chain_is_established(self):
        """请求链应为已成立（所有环节均已接通）。"""
        state = self.chain_map.overall_closure_by_chain[ChainId.REQUEST.value]
        assert state == ClosureState.ESTABLISHED.value

    def test_closure_acceptance_chain_is_established(self):
        """closure/acceptance 链应为已成立。"""
        state = self.chain_map.overall_closure_by_chain[ChainId.CLOSURE_ACCEPTANCE.value]
        assert state == ClosureState.ESTABLISHED.value

    def test_execution_chain_has_partial_segment(self):
        """执行链包含本地 LLM 半闭合环节。"""
        segs = self.chain_map.chains[ChainId.EXECUTION.value]
        states = {s.closure_state for s in segs}
        assert ClosureState.PARTIAL in states

    def test_chain_map_source_annotation(self):
        assert self.chain_map._source == CURRENT_STATE_BACKBONE_AUDIT_AUTHORITY

    def test_to_dict_serializable(self):
        d = self.chain_map.to_dict()
        assert isinstance(d, dict)
        assert "chains" in d
        assert "overall_closure_by_chain" in d
        assert "_source" in d
        for chain_id in ChainId:
            assert chain_id.value in d["chains"]
            assert isinstance(d["chains"][chain_id.value], list)


# ---------------------------------------------------------------------------
# build_mode_map() tests
# ---------------------------------------------------------------------------


class TestBuildModeMap:
    def setup_method(self):
        self.mode_map = build_mode_map()

    def test_returns_mode_map_instance(self):
        assert isinstance(self.mode_map, ModeMap)

    def test_all_six_modes_present(self):
        mode_ids = {m.mode_id for m in self.mode_map.modes}
        for mode_id in ModeId:
            assert mode_id in mode_ids, f"Missing mode: {mode_id.value}"

    def test_cross_device_mode_is_established(self):
        """跨设备模式应为已成立。"""
        for m in self.mode_map.modes:
            if m.mode_id == ModeId.CROSS_DEVICE:
                assert m.closure_state == ClosureState.ESTABLISHED
                return
        pytest.fail("CROSS_DEVICE mode not found")

    def test_local_mode_is_partial(self):
        """本地模式应为半闭合（依赖本地 LLM）。"""
        for m in self.mode_map.modes:
            if m.mode_id == ModeId.LOCAL:
                assert m.closure_state == ClosureState.PARTIAL
                return
        pytest.fail("LOCAL mode not found")

    def test_delegated_execution_is_established(self):
        """委托执行应为已成立。"""
        for m in self.mode_map.modes:
            if m.mode_id == ModeId.DELEGATED_EXECUTION:
                assert m.closure_state == ClosureState.ESTABLISHED
                return
        pytest.fail("DELEGATED_EXECUTION mode not found")

    def test_each_mode_has_description_zh(self):
        for m in self.mode_map.modes:
            assert m.description_zh, f"Mode {m.mode_id.value} missing description_zh"

    def test_each_mode_has_code_anchors(self):
        for m in self.mode_map.modes:
            assert m.v2_code_anchor or m.android_code_anchor, (
                f"Mode {m.mode_id.value} missing code anchors"
            )

    def test_to_dict_serializable(self):
        d = self.mode_map.to_dict()
        assert "modes" in d
        assert len(d["modes"]) == len(list(ModeId))
        for entry in d["modes"]:
            assert "mode_id" in entry
            assert "closure_state" in entry
            assert "description_zh" in entry


# ---------------------------------------------------------------------------
# build_backbone_snapshot() tests
# ---------------------------------------------------------------------------


class TestBuildBackboneSnapshot:
    def setup_method(self):
        self.snap = build_backbone_snapshot()

    def test_returns_backbone_snapshot_instance(self):
        assert isinstance(self.snap, BackboneSnapshot)

    def test_authority_metadata(self):
        assert self.snap.authority == CURRENT_STATE_BACKBONE_AUDIT_AUTHORITY
        assert self.snap.contract_version == CURRENT_STATE_BACKBONE_CONTRACT_VERSION
        assert self.snap.android_audited_ref == ANDROID_AUDITED_REF

    def test_generated_at_is_recent(self):
        now = time.time()
        assert abs(self.snap.generated_at - now) < 5.0

    def test_system_identity_non_empty_chinese(self):
        assert self.snap.system_identity_zh
        # Should contain Chinese characters and mention the system type
        assert "V2" in self.snap.system_identity_zh or "Android" in self.snap.system_identity_zh

    def test_overall_operability_mention(self):
        assert "partially_operable" in self.snap.overall_operability_zh

    def test_established_items_non_empty(self):
        assert len(self.snap.established) >= 5, (
            "Expected at least 5 established backbone items"
        )

    def test_partial_items_non_empty(self):
        assert len(self.snap.partial) >= 3, (
            "Expected at least 3 partial backbone items"
        )

    def test_open_items_non_empty(self):
        assert len(self.snap.open_items) >= 2, (
            "Expected at least 2 open backbone items"
        )

    def test_all_items_are_backbone_item_instances(self):
        all_items = (
            self.snap.established
            + self.snap.partial
            + self.snap.open_items
        )
        for item in all_items:
            assert isinstance(item, BackboneItem)

    def test_established_items_have_correct_state(self):
        for item in self.snap.established:
            assert item.closure_state == ClosureState.ESTABLISHED, (
                f"Item '{item.label}' in established list has wrong state: {item.closure_state}"
            )

    def test_partial_items_have_correct_state(self):
        for item in self.snap.partial:
            assert item.closure_state == ClosureState.PARTIAL, (
                f"Item '{item.label}' in partial list has wrong state: {item.closure_state}"
            )

    def test_open_items_have_correct_state(self):
        for item in self.snap.open_items:
            assert item.closure_state == ClosureState.OPEN, (
                f"Item '{item.label}' in open_items list has wrong state: {item.closure_state}"
            )

    def test_all_items_have_labels_and_anchors(self):
        all_items = (
            self.snap.established
            + self.snap.partial
            + self.snap.open_items
        )
        for item in all_items:
            assert item.label, f"BackboneItem missing label"
            assert item.v2_anchor or item.android_anchor, (
                f"BackboneItem '{item.label}' missing code anchors"
            )

    def test_transport_protocol_is_established(self):
        """WebSocket transport 协议应在已成立列表中。"""
        labels = [i.label for i in self.snap.established]
        found = any("WebSocket" in l or "transport" in l or "Transport" in l for l in labels)
        assert found, (
            f"Expected WebSocket transport in established items. Got: {labels}"
        )

    def test_local_llm_is_open_or_partial(self):
        """本地 LLM 相关项应在半闭合或未闭合列表中。"""
        partial_labels = [i.label for i in self.snap.partial]
        open_labels = [i.label for i in self.snap.open_items]
        all_labels = partial_labels + open_labels
        found = any("LLM" in l or "本地" in l or "local" in l.lower() for l in all_labels)
        assert found, (
            f"Expected local LLM in partial/open items. Got: {all_labels}"
        )

    def test_to_dict_serializable(self):
        d = self.snap.to_dict()
        assert isinstance(d, dict)
        required_keys = {
            "authority",
            "contract_version",
            "android_audited_ref",
            "generated_at",
            "system_identity_zh",
            "overall_operability_zh",
            "chain_map",
            "mode_map",
            "established",
            "partial",
            "open_items",
            "honesty_note_zh",
        }
        for key in required_keys:
            assert key in d, f"Missing key in to_dict: {key}"

    def test_to_dict_items_are_lists(self):
        d = self.snap.to_dict()
        assert isinstance(d["established"], list)
        assert isinstance(d["partial"], list)
        assert isinstance(d["open_items"], list)

    def test_to_dict_item_has_closure_state(self):
        d = self.snap.to_dict()
        for item in d["established"]:
            assert item["closure_state"] == "established"
        for item in d["partial"]:
            assert item["closure_state"] == "partial"
        for item in d["open_items"]:
            assert item["closure_state"] == "open"


# ---------------------------------------------------------------------------
# build_system_backbone_snapshot() (operator/board API) tests
# ---------------------------------------------------------------------------


class TestBuildSystemBackboneSnapshot:
    def setup_method(self):
        self.summary = build_system_backbone_snapshot()

    def test_returns_dict(self):
        assert isinstance(self.summary, dict)

    def test_required_keys_present(self):
        required_keys = {
            "authority",
            "contract_version",
            "android_audited_ref",
            "generated_at",
            "system_identity_zh",
            "overall_operability_zh",
            "chain_closure_summary",
            "mode_closure_summary",
            "established_count",
            "partial_count",
            "open_count",
            "top_open_items",
            "honesty_note_zh",
        }
        for key in required_keys:
            assert key in self.summary, f"Missing key: {key}"

    def test_authority_correct(self):
        assert self.summary["authority"] == CURRENT_STATE_BACKBONE_AUDIT_AUTHORITY

    def test_contract_version_correct(self):
        assert self.summary["contract_version"] == CURRENT_STATE_BACKBONE_CONTRACT_VERSION

    def test_android_audited_ref_correct(self):
        assert self.summary["android_audited_ref"] == ANDROID_AUDITED_REF

    def test_chain_closure_summary_has_all_chains(self):
        summary = self.summary["chain_closure_summary"]
        assert isinstance(summary, dict)
        for chain_id in ChainId:
            assert chain_id.value in summary, (
                f"Missing chain in closure summary: {chain_id.value}"
            )

    def test_chain_closure_values_are_valid(self):
        valid_states = {"established", "partial", "open"}
        for cid, state in self.summary["chain_closure_summary"].items():
            assert state in valid_states, (
                f"Invalid closure state for chain {cid}: {state}"
            )

    def test_mode_closure_summary_has_all_modes(self):
        summary = self.summary["mode_closure_summary"]
        assert isinstance(summary, dict)
        for mode_id in ModeId:
            assert mode_id.value in summary, (
                f"Missing mode in closure summary: {mode_id.value}"
            )

    def test_counts_are_positive_integers(self):
        assert isinstance(self.summary["established_count"], int)
        assert isinstance(self.summary["partial_count"], int)
        assert isinstance(self.summary["open_count"], int)
        assert self.summary["established_count"] > 0
        assert self.summary["partial_count"] > 0
        assert self.summary["open_count"] > 0

    def test_top_open_items_is_list(self):
        items = self.summary["top_open_items"]
        assert isinstance(items, list)
        assert len(items) > 0

    def test_top_open_items_have_label_and_detail(self):
        for item in self.summary["top_open_items"]:
            assert "label" in item
            assert "detail_zh" in item
            assert item["label"]

    def test_system_identity_mentions_v2_and_android(self):
        identity = self.summary["system_identity_zh"]
        assert "V2" in identity or "Android" in identity

    def test_operability_is_partially_operable(self):
        assert "partially_operable" in self.summary["overall_operability_zh"]

    def test_honesty_note_non_empty(self):
        assert self.summary["honesty_note_zh"]
        assert len(self.summary["honesty_note_zh"]) > 20

    def test_idempotent_calls(self):
        """两次调用应返回结构相同、内容等价的结果（generated_at 除外）。"""
        summary2 = build_system_backbone_snapshot()
        assert summary2["established_count"] == self.summary["established_count"]
        assert summary2["partial_count"] == self.summary["partial_count"]
        assert summary2["open_count"] == self.summary["open_count"]
        assert summary2["chain_closure_summary"] == self.summary["chain_closure_summary"]
        assert summary2["mode_closure_summary"] == self.summary["mode_closure_summary"]


# ---------------------------------------------------------------------------
# Cross-cutting structural integrity tests
# ---------------------------------------------------------------------------


class TestStructuralIntegrity:
    """跨模块结构完整性测试。"""

    def test_no_item_appears_in_multiple_closure_lists(self):
        """同一个骨架项不应同时出现在两个闭合状态列表中。"""
        snap = build_backbone_snapshot()
        established_labels = {i.label for i in snap.established}
        partial_labels = {i.label for i in snap.partial}
        open_labels = {i.label for i in snap.open_items}
        assert established_labels.isdisjoint(partial_labels), (
            f"Labels in both established and partial: "
            f"{established_labels & partial_labels}"
        )
        assert established_labels.isdisjoint(open_labels), (
            f"Labels in both established and open: "
            f"{established_labels & open_labels}"
        )
        assert partial_labels.isdisjoint(open_labels), (
            f"Labels in both partial and open: "
            f"{partial_labels & open_labels}"
        )

    def test_chain_overall_state_reflects_worst_segment(self):
        """链路整体状态应等于其最差环节状态。"""
        chain_map = build_chain_map()
        priority = {"open": 2, "partial": 1, "established": 0}
        for cid, segs in chain_map.chains.items():
            worst = max(priority[s.closure_state.value] for s in segs)
            worst_str = ["established", "partial", "open"][worst]
            overall = chain_map.overall_closure_by_chain[cid]
            assert overall == worst_str, (
                f"Chain {cid}: expected {worst_str}, got {overall}"
            )

    def test_backbone_snapshot_chain_and_mode_maps_consistent(self):
        """BackboneSnapshot 内的 chain_map 和 mode_map 应与单独调用结果一致。"""
        snap = build_backbone_snapshot()
        cm = build_chain_map()
        mm = build_mode_map()
        assert (
            snap.chain_map.overall_closure_by_chain
            == cm.overall_closure_by_chain
        )
        snap_mode_ids = {m.mode_id for m in snap.mode_map.modes}
        ref_mode_ids = {m.mode_id for m in mm.modes}
        assert snap_mode_ids == ref_mode_ids
