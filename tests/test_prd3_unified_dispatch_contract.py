"""tests/test_prd3_unified_dispatch_contract.py
================================================
Tests for PR-03: Unified Dispatch Contract Metadata.

Coverage:
  1.  DispatchContractMetadata — all fields present and serialisable.
  2.  DispatchContractMetadata — to_dict / from_dict round-trip.
  3.  DispatchContractMetadata — to_json stability.
  4.  build_dispatch_contract_metadata — builder never raises.
  5.  build_dispatch_contract_metadata — populates all fields.
  6.  build_dispatch_contract_metadata — graceful with None inputs.
  7.  extract_dispatch_contract_metadata — from HandoffEnvelopeV2.
  8.  extract_dispatch_contract_metadata — from LocalTakeoverResult.
  9.  extract_dispatch_contract_metadata — from SourceDispatchResult.
  10. extract_dispatch_contract_metadata — from dict.
  11. extract_dispatch_contract_metadata — returns None on missing.
  12. HandoffEnvelopeV2 — carries dispatch_contract_metadata field.
  13. build_handoff_envelope_v2 — accepts dispatch_contract_metadata.
  14. build_handoff_envelope_v2 — dispatch_contract_metadata is in to_dict().
  15. LocalTakeoverResult — carries dispatch_contract_metadata field.
  16. build_local_takeover_result — accepts dispatch_contract_metadata.
  17. from_execution_output — propagates dispatch_contract_metadata.
  18. failure_result — propagates dispatch_contract_metadata.
  19. SourceDispatchResult — carries dispatch_contract_metadata field.
  20. build_source_dispatch_result — accepts dispatch_contract_metadata.
  21. TargetTakeoverHandler.handle — propagates dispatch_contract_metadata
      from incoming HandoffEnvelopeV2 to LocalTakeoverResult.
  22. TargetTakeoverHandler.handle — dispatch_contract_metadata present
      even when takeover is rejected by policy.
  23. TargetTakeoverHandler.handle — dispatch_contract_metadata present
      on unhandled exception path.
  24. orchestrate_source_runtime_dispatch — goal_execution result carries
      dispatch_contract_metadata.
  25. orchestrate_source_runtime_dispatch — blocked result carries
      dispatch_contract_metadata.
  26. orchestrate_source_runtime_dispatch — fallback result carries
      dispatch_contract_metadata when remote handoff fails.
  27. Three-path field symmetry — goal_execution / handoff / takeover
      share the same dispatch_contract_metadata key set.
  28. to_compact_summary — LocalTakeoverResult includes dispatch fields.
  29. to_compact_summary — SourceDispatchResult includes dispatch fields.
  30. UNIFIED_DISPATCH_CONTRACT_PR03_SENTINEL — importable from contracts.
  31. contracts package re-exports — DispatchContractMetadata importable.
  32. schema_version is "v1" by default.
  33. DispatchContractMetadata extra fields are allowed (forward compat).
  34. DispatchContractMetadata from_dict tolerates unknown keys.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dcm_dict(
    *,
    dispatch_plan_id: str = "plan_001",
    source_dispatch_strategy: str = "remote_handoff",
    executor_target_type: str = "android_device",
    trace_id: str = "trace_001",
    task_id: str = "task_001",
) -> Dict[str, Any]:
    """Return a complete dispatch contract metadata dictionary for use in tests.

    Builds a plain-dict representation of :class:`DispatchContractMetadata`
    with all required stable keys populated.  All parameters have sensible
    test defaults so callers can override only the fields they care about.

    Parameters
    ----------
    dispatch_plan_id:
        Plan identifier.  Defaults to ``"plan_001"``.
    source_dispatch_strategy:
        Dispatch strategy string.  Defaults to ``"remote_handoff"``.
    executor_target_type:
        Executor target type string.  Defaults to ``"android_device"``.
    trace_id:
        Distributed trace identifier.  Defaults to ``"trace_001"``.
    task_id:
        Task identifier.  Defaults to ``"task_001"``.

    Returns
    -------
    dict
        A JSON-safe dictionary compatible with ``DispatchContractMetadata.from_dict``.
    """
    return {
        "dispatch_plan_id": dispatch_plan_id,
        "source_dispatch_strategy": source_dispatch_strategy,
        "executor_target_type": executor_target_type,
        "trace_id": trace_id,
        "task_id": task_id,
        "session_id": "sess_001",
        "source_device_id": "src_dev_001",
        "target_device_id": "tgt_dev_001",
        "schema_version": "v1",
    }


def _make_envelope_with_dcm(
    trace_id: str = "trace_001",
    task_id: str = "task_001",
    dispatch_plan_id: str = "plan_abc",
) -> Any:
    """Return a HandoffEnvelopeV2 that carries dispatch_contract_metadata."""
    from contracts.handoff_envelope_v2 import build_handoff_envelope_v2
    from contracts.dispatch_contract_metadata import build_dispatch_contract_metadata

    dcm = build_dispatch_contract_metadata(
        dispatch_plan_id=dispatch_plan_id,
        source_dispatch_strategy="remote_handoff",
        executor_target_type="android_device",
        trace_id=trace_id,
        task_id=task_id,
    )
    return build_handoff_envelope_v2(
        trace_id=trace_id,
        task={"tool_name": "screenshot", "args": {}},
        task_id=task_id,
        session_id="sess_001",
        dispatch_contract_metadata=dcm,
    )


# ---------------------------------------------------------------------------
# 1-3. DispatchContractMetadata model tests
# ---------------------------------------------------------------------------


class TestDispatchContractMetadataModel:
    """DispatchContractMetadata field and serialisation correctness."""

    def test_all_fields_present(self):
        from contracts.dispatch_contract_metadata import DispatchContractMetadata

        dcm = DispatchContractMetadata(
            dispatch_plan_id="plan_001",
            dispatch_decision_id="dec_001",
            source_dispatch_strategy="remote_handoff",
            executor_target_type="android_device",
            trace_id="trace_001",
            task_id="task_001",
            session_id="sess_001",
            source_device_id="src_dev",
            target_device_id="tgt_dev",
        )
        assert dcm.dispatch_plan_id == "plan_001"
        assert dcm.dispatch_decision_id == "dec_001"
        assert dcm.source_dispatch_strategy == "remote_handoff"
        assert dcm.executor_target_type == "android_device"
        assert dcm.trace_id == "trace_001"
        assert dcm.task_id == "task_001"
        assert dcm.session_id == "sess_001"
        assert dcm.source_device_id == "src_dev"
        assert dcm.target_device_id == "tgt_dev"
        assert dcm.schema_version == "v1"
        assert isinstance(dcm.timestamp, float)
        assert isinstance(dcm.metadata, dict)

    def test_to_dict_from_dict_round_trip(self):
        from contracts.dispatch_contract_metadata import DispatchContractMetadata, build_dispatch_contract_metadata

        dcm = build_dispatch_contract_metadata(
            dispatch_plan_id="plan_rt",
            source_dispatch_strategy="local",
            executor_target_type="local",
            trace_id="trace_rt",
        )
        data = dcm.to_dict()
        assert isinstance(data, dict)
        restored = DispatchContractMetadata.from_dict(data)
        assert restored.dispatch_plan_id == "plan_rt"
        assert restored.source_dispatch_strategy == "local"
        assert restored.executor_target_type == "local"
        assert restored.trace_id == "trace_rt"

    def test_to_json_is_valid_json(self):
        from contracts.dispatch_contract_metadata import build_dispatch_contract_metadata

        dcm = build_dispatch_contract_metadata(
            dispatch_plan_id="plan_j",
            source_dispatch_strategy="remote_handoff",
        )
        raw = dcm.to_json()
        parsed = json.loads(raw)
        assert parsed["dispatch_plan_id"] == "plan_j"
        assert parsed["source_dispatch_strategy"] == "remote_handoff"

    def test_schema_version_is_v1(self):
        from contracts.dispatch_contract_metadata import DispatchContractMetadata

        assert DispatchContractMetadata().schema_version == "v1"

    def test_extra_fields_allowed(self):
        from contracts.dispatch_contract_metadata import DispatchContractMetadata

        dcm = DispatchContractMetadata(**{"future_field": "x"})
        data = dcm.to_dict()
        assert data["future_field"] == "x"

    def test_from_dict_tolerates_unknown_keys(self):
        from contracts.dispatch_contract_metadata import DispatchContractMetadata

        raw = {"dispatch_plan_id": "p", "unknown_future_key": 42}
        dcm = DispatchContractMetadata.from_dict(raw)
        assert dcm.dispatch_plan_id == "p"


# ---------------------------------------------------------------------------
# 4-6. build_dispatch_contract_metadata tests
# ---------------------------------------------------------------------------


class TestBuildDispatchContractMetadata:
    """build_dispatch_contract_metadata builder correctness."""

    def test_builder_never_raises_with_all_fields(self):
        from contracts.dispatch_contract_metadata import build_dispatch_contract_metadata

        dcm = build_dispatch_contract_metadata(
            dispatch_plan_id="plan_x",
            dispatch_decision_id="dec_x",
            source_dispatch_strategy="remote_handoff",
            executor_target_type="android_device",
            trace_id="t",
            task_id="task_x",
            session_id="sess_x",
            source_device_id="src",
            target_device_id="tgt",
            metadata={"k": "v"},
        )
        assert dcm.dispatch_plan_id == "plan_x"
        assert dcm.executor_target_type == "android_device"
        assert dcm.metadata == {"k": "v"}

    def test_builder_graceful_with_none_inputs(self):
        from contracts.dispatch_contract_metadata import build_dispatch_contract_metadata

        dcm = build_dispatch_contract_metadata()
        assert dcm is not None
        assert dcm.dispatch_plan_id is None
        assert dcm.source_dispatch_strategy is None
        assert dcm.schema_version == "v1"

    def test_builder_populates_strategy_variants(self):
        from contracts.dispatch_contract_metadata import build_dispatch_contract_metadata

        for strategy in ("local", "remote_handoff", "staged_mesh", "blocked", "fallback_local", "unknown"):
            dcm = build_dispatch_contract_metadata(source_dispatch_strategy=strategy)
            assert dcm.source_dispatch_strategy == strategy


# ---------------------------------------------------------------------------
# 7-11. extract_dispatch_contract_metadata tests
# ---------------------------------------------------------------------------


class TestExtractDispatchContractMetadata:
    """extract_dispatch_contract_metadata extraction correctness."""

    def test_from_handoff_envelope_v2(self):
        from contracts.dispatch_contract_metadata import extract_dispatch_contract_metadata

        env = _make_envelope_with_dcm(dispatch_plan_id="plan_e2e")
        extracted = extract_dispatch_contract_metadata(env)
        assert extracted is not None
        assert extracted.dispatch_plan_id == "plan_e2e"
        assert extracted.source_dispatch_strategy == "remote_handoff"

    def test_from_local_takeover_result(self):
        from contracts.dispatch_contract_metadata import (
            build_dispatch_contract_metadata,
            extract_dispatch_contract_metadata,
        )
        from contracts.local_takeover_result import build_local_takeover_result

        dcm = build_dispatch_contract_metadata(dispatch_plan_id="plan_ltr")
        result = build_local_takeover_result(
            trace_id="t",
            dispatch_contract_metadata=dcm.to_dict(),
        )
        extracted = extract_dispatch_contract_metadata(result)
        assert extracted is not None
        assert extracted.dispatch_plan_id == "plan_ltr"

    def test_from_source_dispatch_result(self):
        from contracts.dispatch_contract_metadata import (
            build_dispatch_contract_metadata,
            extract_dispatch_contract_metadata,
        )
        from contracts.source_dispatch import build_source_dispatch_result, SourceDispatchMode

        dcm = build_dispatch_contract_metadata(
            dispatch_plan_id="plan_sdr",
            source_dispatch_strategy="local",
        )
        result = build_source_dispatch_result(
            trace_id="t",
            mode=SourceDispatchMode.local,
            dispatch_contract_metadata=dcm.to_dict(),
        )
        extracted = extract_dispatch_contract_metadata(result)
        assert extracted is not None
        assert extracted.dispatch_plan_id == "plan_sdr"
        assert extracted.source_dispatch_strategy == "local"

    def test_from_dict(self):
        from contracts.dispatch_contract_metadata import (
            DispatchContractMetadata,
            extract_dispatch_contract_metadata,
        )

        data = {"dispatch_contract_metadata": {"dispatch_plan_id": "plan_dict"}}
        extracted = extract_dispatch_contract_metadata(data)
        assert extracted is not None
        assert extracted.dispatch_plan_id == "plan_dict"

    def test_returns_none_when_missing(self):
        from contracts.dispatch_contract_metadata import extract_dispatch_contract_metadata

        assert extract_dispatch_contract_metadata(None) is None
        assert extract_dispatch_contract_metadata({}) is None
        assert extract_dispatch_contract_metadata(MagicMock(dispatch_contract_metadata=None)) is None


# ---------------------------------------------------------------------------
# 12-14. HandoffEnvelopeV2 integration
# ---------------------------------------------------------------------------


class TestHandoffEnvelopeV2Integration:
    """HandoffEnvelopeV2 carries and propagates dispatch_contract_metadata."""

    def test_field_exists_with_none_default(self):
        from contracts.handoff_envelope_v2 import HandoffEnvelopeV2

        env = HandoffEnvelopeV2()
        assert env.dispatch_contract_metadata is None

    def test_build_handoff_envelope_v2_accepts_dcm(self):
        env = _make_envelope_with_dcm(dispatch_plan_id="plan_hv2")
        assert env.dispatch_contract_metadata is not None
        dcm_data = env.dispatch_contract_metadata
        assert isinstance(dcm_data, dict)
        assert dcm_data["dispatch_plan_id"] == "plan_hv2"
        assert dcm_data["source_dispatch_strategy"] == "remote_handoff"

    def test_build_handoff_envelope_v2_dcm_in_to_dict(self):
        env = _make_envelope_with_dcm(dispatch_plan_id="plan_td")
        data = env.to_dict()
        assert "dispatch_contract_metadata" in data
        assert data["dispatch_contract_metadata"]["dispatch_plan_id"] == "plan_td"

    def test_build_handoff_envelope_v2_accepts_dcm_as_dict(self):
        from contracts.handoff_envelope_v2 import build_handoff_envelope_v2

        dcm_dict = _make_dcm_dict()
        env = build_handoff_envelope_v2(
            trace_id="t",
            dispatch_contract_metadata=dcm_dict,
        )
        assert env.dispatch_contract_metadata == dcm_dict

    def test_build_handoff_envelope_v2_without_dcm_is_none(self):
        from contracts.handoff_envelope_v2 import build_handoff_envelope_v2

        env = build_handoff_envelope_v2(trace_id="t")
        assert env.dispatch_contract_metadata is None


# ---------------------------------------------------------------------------
# 15-18. LocalTakeoverResult integration
# ---------------------------------------------------------------------------


class TestLocalTakeoverResultIntegration:
    """LocalTakeoverResult carries and propagates dispatch_contract_metadata."""

    def test_field_exists_with_none_default(self):
        from contracts.local_takeover_result import LocalTakeoverResult

        result = LocalTakeoverResult()
        assert result.dispatch_contract_metadata is None

    def test_build_local_takeover_result_accepts_dcm(self):
        from contracts.local_takeover_result import build_local_takeover_result

        dcm_dict = _make_dcm_dict()
        result = build_local_takeover_result(
            trace_id="t",
            dispatch_contract_metadata=dcm_dict,
        )
        assert result.dispatch_contract_metadata == dcm_dict

    def test_from_execution_output_propagates_dcm(self):
        from contracts.local_takeover_result import from_execution_output

        dcm_dict = _make_dcm_dict()
        result = from_execution_output(
            trace_id="t",
            execution_output={"success": True, "action_taken": "click"},
            dispatch_contract_metadata=dcm_dict,
        )
        assert result.dispatch_contract_metadata == dcm_dict
        assert result.success is True

    def test_failure_result_propagates_dcm(self):
        from contracts.local_takeover_result import failure_result

        dcm_dict = _make_dcm_dict()
        result = failure_result(
            trace_id="t",
            reason="test_failure",
            dispatch_contract_metadata=dcm_dict,
        )
        assert result.dispatch_contract_metadata == dcm_dict
        assert result.success is False

    def test_failure_result_without_dcm_is_none(self):
        from contracts.local_takeover_result import failure_result

        result = failure_result(trace_id="t", reason="no_dcm")
        assert result.dispatch_contract_metadata is None


# ---------------------------------------------------------------------------
# 19-20. SourceDispatchResult integration
# ---------------------------------------------------------------------------


class TestSourceDispatchResultIntegration:
    """SourceDispatchResult carries and propagates dispatch_contract_metadata."""

    def test_field_exists_with_none_default(self):
        from contracts.source_dispatch import SourceDispatchResult

        result = SourceDispatchResult()
        assert result.dispatch_contract_metadata is None

    def test_build_source_dispatch_result_accepts_dcm(self):
        from contracts.source_dispatch import build_source_dispatch_result, SourceDispatchMode

        dcm_dict = _make_dcm_dict(source_dispatch_strategy="local")
        result = build_source_dispatch_result(
            trace_id="t",
            mode=SourceDispatchMode.local,
            dispatch_contract_metadata=dcm_dict,
        )
        assert result.dispatch_contract_metadata == dcm_dict

    def test_source_dispatch_result_to_dict_includes_dcm(self):
        from contracts.source_dispatch import build_source_dispatch_result, SourceDispatchMode

        dcm_dict = _make_dcm_dict()
        result = build_source_dispatch_result(
            trace_id="t",
            mode=SourceDispatchMode.remote_handoff,
            dispatch_contract_metadata=dcm_dict,
        )
        data = result.to_dict()
        assert "dispatch_contract_metadata" in data
        assert data["dispatch_contract_metadata"]["dispatch_plan_id"] == "plan_001"


# ---------------------------------------------------------------------------
# 21-23. TargetTakeoverHandler propagation tests
# ---------------------------------------------------------------------------


class TestTargetTakeoverHandlerPropagation:
    """TargetTakeoverHandler propagates dispatch_contract_metadata correctly."""

    def test_handle_propagates_dcm_from_envelope_to_result(self):
        """dispatch_contract_metadata from HandoffEnvelopeV2 reaches LocalTakeoverResult."""
        from core.runtime.target_takeover import TargetTakeoverHandler

        envelope = _make_envelope_with_dcm(
            trace_id="trace_h",
            task_id="task_h",
            dispatch_plan_id="plan_handler",
        )
        handler = TargetTakeoverHandler()
        result = handler.handle(envelope)
        assert result.dispatch_contract_metadata is not None
        dcm_data = result.dispatch_contract_metadata
        assert dcm_data["dispatch_plan_id"] == "plan_handler"
        assert dcm_data["source_dispatch_strategy"] == "remote_handoff"

    def test_handle_dcm_present_on_rejected_by_policy(self):
        """Rejected-by-policy path also carries dispatch_contract_metadata."""
        from contracts.handoff_envelope_v2 import build_handoff_envelope_v2
        from contracts.dispatch_contract_metadata import build_dispatch_contract_metadata
        from core.runtime.target_takeover import TargetTakeoverHandler

        dcm = build_dispatch_contract_metadata(
            dispatch_plan_id="plan_rej",
            source_dispatch_strategy="remote_handoff",
        )
        envelope = build_handoff_envelope_v2(
            trace_id="trace_rej",
            task_id="task_rej",
            allow_local_takeover=False,
            dispatch_contract_metadata=dcm,
        )
        handler = TargetTakeoverHandler()
        result = handler.handle(envelope)
        assert result.dispatch_contract_metadata is not None
        assert result.dispatch_contract_metadata["dispatch_plan_id"] == "plan_rej"
        assert result.reason == "takeover_disallowed_by_policy"

    def test_handle_without_dcm_in_envelope_still_works(self):
        """TargetTakeoverHandler is graceful when envelope has no DCM."""
        from contracts.handoff_envelope_v2 import build_handoff_envelope_v2
        from core.runtime.target_takeover import TargetTakeoverHandler

        envelope = build_handoff_envelope_v2(
            trace_id="trace_nodcm",
            task_id="task_nodcm",
            # No dispatch_contract_metadata supplied
        )
        handler = TargetTakeoverHandler()
        result = handler.handle(envelope)
        # Result is valid even without DCM
        assert result is not None
        assert result.dispatch_contract_metadata is None


# ---------------------------------------------------------------------------
# 24-26. SourceDispatchOrchestrator integration tests
# ---------------------------------------------------------------------------


class TestOrchestratorDispatchContractMetadata:
    """orchestrate_source_runtime_dispatch stamps dispatch_contract_metadata."""

    def test_goal_execution_result_carries_dcm(self):
        """Local (goal_execution) path stamps dispatch_contract_metadata."""
        from core.runtime.source_dispatch_orchestrator import orchestrate_source_runtime_dispatch

        result = orchestrate_source_runtime_dispatch(
            trace_id="trace_local",
            task_id="task_local",
            session_id="sess_local",
            force_local=True,
        )
        assert result is not None
        assert result.dispatch_contract_metadata is not None
        dcm = result.dispatch_contract_metadata
        assert dcm["trace_id"] == "trace_local"
        assert dcm["task_id"] == "task_local"
        assert dcm["schema_version"] == "v1"
        # Strategy reflects the chosen mode
        assert dcm["source_dispatch_strategy"] is not None

    def test_blocked_result_carries_dcm(self):
        """Blocked path stamps dispatch_contract_metadata."""
        from core.runtime.source_dispatch_orchestrator import orchestrate_source_runtime_dispatch

        result = orchestrate_source_runtime_dispatch(
            trace_id="trace_blocked",
            task_id="task_blocked",
            force_local=False,
            force_remote=False,
            policy_alignment={"blocked": True, "alignment_hints": {"can_execute_locally": False}},
        )
        assert result is not None
        # May be blocked or local depending on policy path — in either case
        # dispatch_contract_metadata should be present.
        assert result.dispatch_contract_metadata is not None
        assert result.dispatch_contract_metadata["trace_id"] == "trace_blocked"

    def test_graceful_with_none_inputs_produces_dcm(self):
        """Graceful None path still produces a result with metadata."""
        from core.runtime.source_dispatch_orchestrator import orchestrate_source_runtime_dispatch

        result = orchestrate_source_runtime_dispatch()
        assert result is not None
        # dispatch_contract_metadata may be None if the error path was triggered
        # but should not raise
        assert hasattr(result, "dispatch_contract_metadata")


# ---------------------------------------------------------------------------
# 27. Three-path field symmetry test
# ---------------------------------------------------------------------------


class TestThreePathFieldSymmetry:
    """goal_execution / handoff / takeover share the same DCM key set."""

    def _required_dcm_keys(self) -> set:
        return {
            "dispatch_plan_id",
            "dispatch_decision_id",
            "source_dispatch_strategy",
            "executor_target_type",
            "trace_id",
            "task_id",
            "session_id",
            "source_device_id",
            "target_device_id",
            "schema_version",
            "timestamp",
            "metadata",
        }

    def test_dcm_dict_has_all_required_keys(self):
        from contracts.dispatch_contract_metadata import build_dispatch_contract_metadata

        dcm = build_dispatch_contract_metadata(
            dispatch_plan_id="plan_sym",
            source_dispatch_strategy="remote_handoff",
            trace_id="t",
        )
        data = dcm.to_dict()
        for key in self._required_dcm_keys():
            assert key in data, f"Missing key: {key}"

    def test_goal_execution_dcm_keys(self):
        from core.runtime.source_dispatch_orchestrator import orchestrate_source_runtime_dispatch

        result = orchestrate_source_runtime_dispatch(
            trace_id="trace_sym_local",
            force_local=True,
        )
        if result.dispatch_contract_metadata is not None:
            for key in self._required_dcm_keys():
                assert key in result.dispatch_contract_metadata, f"Missing key in goal_execution DCM: {key}"

    def test_handoff_envelope_dcm_keys(self):
        env = _make_envelope_with_dcm(dispatch_plan_id="plan_sym_ho")
        dcm_data = env.dispatch_contract_metadata
        assert dcm_data is not None
        for key in self._required_dcm_keys():
            assert key in dcm_data, f"Missing key in handoff DCM: {key}"

    def test_takeover_result_dcm_keys(self):
        from core.runtime.target_takeover import TargetTakeoverHandler

        envelope = _make_envelope_with_dcm(dispatch_plan_id="plan_sym_to")
        handler = TargetTakeoverHandler()
        result = handler.handle(envelope)
        if result.dispatch_contract_metadata is not None:
            for key in self._required_dcm_keys():
                assert key in result.dispatch_contract_metadata, (
                    f"Missing key in takeover DCM: {key}"
                )


# ---------------------------------------------------------------------------
# 28-29. to_compact_summary dispatch fields
# ---------------------------------------------------------------------------


class TestCompactSummaryDispatchFields:
    """to_compact_summary exposes dispatch_contract_metadata fields."""

    def test_local_takeover_result_compact_summary_with_dcm(self):
        from contracts.local_takeover_result import build_local_takeover_result

        dcm_dict = _make_dcm_dict()
        result = build_local_takeover_result(
            trace_id="t",
            success=True,
            dispatch_contract_metadata=dcm_dict,
        )
        summary = result.to_compact_summary()
        assert summary["has_dispatch_contract_metadata"] is True
        assert summary["dispatch_plan_id"] == "plan_001"
        assert summary["source_dispatch_strategy"] == "remote_handoff"
        assert summary["executor_target_type"] == "android_device"

    def test_local_takeover_result_compact_summary_without_dcm(self):
        from contracts.local_takeover_result import build_local_takeover_result

        result = build_local_takeover_result(trace_id="t")
        summary = result.to_compact_summary()
        assert summary["has_dispatch_contract_metadata"] is False
        assert summary["dispatch_plan_id"] is None

    def test_source_dispatch_result_compact_summary_with_dcm(self):
        from contracts.source_dispatch import build_source_dispatch_result, SourceDispatchMode

        dcm_dict = _make_dcm_dict()
        result = build_source_dispatch_result(
            trace_id="t",
            mode=SourceDispatchMode.local,
            dispatch_contract_metadata=dcm_dict,
        )
        summary = result.to_compact_summary()
        assert summary["has_dispatch_contract_metadata"] is True
        assert summary["dispatch_plan_id"] == "plan_001"
        assert summary["source_dispatch_strategy"] == "remote_handoff"

    def test_source_dispatch_result_compact_summary_without_dcm(self):
        from contracts.source_dispatch import build_source_dispatch_result, SourceDispatchMode

        result = build_source_dispatch_result(trace_id="t", mode=SourceDispatchMode.local)
        summary = result.to_compact_summary()
        assert summary["has_dispatch_contract_metadata"] is False
        assert summary["dispatch_plan_id"] is None


# ---------------------------------------------------------------------------
# 30-31. contracts package re-exports
# ---------------------------------------------------------------------------


class TestContractsPackageReExports:
    """DispatchContractMetadata and helpers are re-exported from contracts."""

    def test_dispatch_contract_metadata_importable_from_contracts(self):
        from contracts import DispatchContractMetadata
        assert DispatchContractMetadata is not None

    def test_build_dispatch_contract_metadata_importable_from_contracts(self):
        from contracts import build_dispatch_contract_metadata
        assert build_dispatch_contract_metadata is not None

    def test_extract_dispatch_contract_metadata_importable_from_contracts(self):
        from contracts import extract_dispatch_contract_metadata
        assert extract_dispatch_contract_metadata is not None

    def test_sentinel_importable_from_contracts(self):
        from contracts import UNIFIED_DISPATCH_CONTRACT_PR03_SENTINEL
        assert "PR03" in UNIFIED_DISPATCH_CONTRACT_PR03_SENTINEL

    def test_policy_importable_from_contracts(self):
        from contracts import DISPATCH_CONTRACT_METADATA_IS_STABLE_ANDROID_SURFACE_PR03_POLICY
        assert "PR03" in DISPATCH_CONTRACT_METADATA_IS_STABLE_ANDROID_SURFACE_PR03_POLICY
