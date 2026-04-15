#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PR-51: Canonical concept model alignment checks (low-risk/additive)."""

from __future__ import annotations

from pathlib import Path

from core.schemas.ugcp import (
    UGCP_CANONICAL_CONCEPT_VOCABULARY_ALIGNMENT_PR51_SENTINEL,
    normalize_conversation_session_id,
    normalize_delegation_transfer_session_id,
    normalize_graph_node_id,
    normalize_runtime_attachment_session_id,
    normalize_runtime_participant_id,
)


def test_pr51_sentinel_present() -> None:
    assert UGCP_CANONICAL_CONCEPT_VOCABULARY_ALIGNMENT_PR51_SENTINEL.startswith(
        "UGCP_CANONICAL_CONCEPT_VOCABULARY_ALIGNMENT_PR51_SENTINEL::"
    )
    assert "participant_device_runtime_capability" in UGCP_CANONICAL_CONCEPT_VOCABULARY_ALIGNMENT_PR51_SENTINEL


def test_normalize_runtime_participant_and_graph_node_ids() -> None:
    payload = {"participant_id": "p-1", "graph_node_id": "g-1", "node_id": "legacy-node"}
    assert normalize_runtime_participant_id(payload) == "p-1"
    assert normalize_graph_node_id(payload) == "g-1"


def test_normalize_session_helpers_keep_semantics_separate() -> None:
    payload = {
        "conversation_session_id": "conv-1",
        "runtime_attachment_session_id": "rt-attach-1",
        "delegation_transfer_session_id": "xfer-1",
        "session_id": "legacy-session",
        "runtime_session_id": "legacy-runtime-session",
        "transfer_session_id": "legacy-transfer-session",
    }
    assert normalize_conversation_session_id(payload) == "conv-1"
    assert normalize_runtime_attachment_session_id(payload) == "rt-attach-1"
    assert normalize_delegation_transfer_session_id(payload) == "xfer-1"


def test_canonical_concept_docs_cover_required_vocabulary() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    architecture_doc = repo_root / "docs" / "architecture" / "CANONICAL_CONCEPT_MODEL_V1.md"
    ugcp_vocab_doc = repo_root / "docs" / "ugcp" / "UGCP_CANONICAL_VOCABULARY_V1.md"
    android_alignment_doc = repo_root / "docs" / "ugcp" / "UGCP_ANDROID_ALIGNMENT_NOTES_V1.md"

    architecture_text = architecture_doc.read_text(encoding="utf-8").lower()
    vocab_text = ugcp_vocab_doc.read_text(encoding="utf-8").lower()
    android_text = android_alignment_doc.read_text(encoding="utf-8").lower()

    required_terms = [
        "participant",
        "device",
        "runtime",
        "capability",
        "conversation session",
        "runtime attachment session",
        "delegation transfer session",
        "posture",
        "coordination role",
    ]
    for term in required_terms:
        assert term in architecture_text
        assert term in vocab_text

    assert "dannyfish-11/ufo-galaxy-realization-v2" in architecture_text
    assert "dannyfish-11/ufo-galaxy-android" in architecture_text
    assert "runtime host participant" in android_text
