"""tests/test_result_ingress_continuity_legality.py
====================================================
PR-V1-RESULT: Tests for the canonical V1 continuity legality pre-check
wired into ``galaxy_gateway/android/handlers/task_lifecycle.handle_task_result``.

These tests prove that:

  AC1  Valid participant results still enter the canonical truth chain.
  AC2  Invalid/stale/revoked/detached continuity states are rejected before
       truth ingestion (truth-chain must not run).
  AC3  Result ingress rejection does not silently degrade into truth
       pollution (truth-chain call must be skipped on rejection).
  AC4  Existing valid delegated / handoff / grouped result flows remain
       compatible (non-rejected messages are unaffected).
  AC5  When the V1 authority module is unavailable the handler falls back
       to allow-through (backward-compat graceful degradation).
  AC6  Policy sentinel is present in the module.
  AC7  Helper function ``_check_result_ingress_continuity_legality`` is
       exported from the module and callable.
  AC8  ``_check_result_ingress_continuity_legality`` returns ("allow", False)
       when authority is unavailable.
  AC9  ``_check_result_ingress_continuity_legality`` returns ("reject", True)
       when authority returns REJECT.
  AC10 ``_check_result_ingress_continuity_legality`` returns
       ("require_review", True) when authority returns REQUIRE_REVIEW.
  AC11 ``_check_result_ingress_continuity_legality`` returns ("allow", False)
       when authority returns ALLOW.
  AC12 ``_check_result_ingress_continuity_legality`` extracts continuity
       fields from the raw message dict (device_id, runtime_session_id,
       runtime_attachment_session_id, durable_session_id, contract_id,
       flow_id).
  AC13 Exceptions raised inside the authority call are caught; helper
       returns ("allow", False) without propagating.
  AC14 handle_task_result completes normally (future resolved, device state
       cleared) when continuity verdict is "allow".
  AC15 handle_task_result returns early without resolving any future when
       continuity is rejected.

Coverage groups
---------------
Group A — RESULT_INGRESS_CONTINUITY_LEGALITY_POLICY sentinel.
Group B — _check_result_ingress_continuity_legality helper: unit-level.
Group C — handle_task_result: valid continuity → truth chain runs (AC1/AC4).
Group D — handle_task_result: rejected continuity → truth chain skipped (AC2/AC3).
Group E — handle_task_result: require_review → truth chain skipped (AC2/AC3).
Group F — handle_task_result: authority unavailable → allow-through (AC5).
Group G — handle_task_result: delegated / contract_id flows unaffected (AC4).
Group H — handle_task_result: future not resolved on rejection (AC15).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Module availability guard
# ---------------------------------------------------------------------------

try:
    import galaxy_gateway.android.handlers.task_lifecycle as _tl

    _MODULE_AVAILABLE = True
except ImportError:
    _MODULE_AVAILABLE = False

_SKIP = pytest.mark.skipif(not _MODULE_AVAILABLE, reason="task_lifecycle unavailable")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bridge() -> Any:
    """Minimal mock bridge suitable for handler calls."""
    bridge = MagicMock()
    bridge._pending_responses = {}
    bridge._lock = asyncio.Lock()
    bridge._devices = {}
    return bridge


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _make_report(verdict_str: str) -> Any:
    """Return a minimal ContinuityLegalityReport-like mock."""
    report = MagicMock()
    report.verdict.value = verdict_str
    # is_rejected: True for "reject" or "require_review"
    report.is_rejected = verdict_str in ("reject", "require_review")
    return report


def _make_message(
    task_id: str = "t-test",
    device_id: str = "dev-test",
    status: str = "completed",
    **extra: Any,
) -> Dict[str, Any]:
    return {"task_id": task_id, "device_id": device_id, "status": status, **extra}


# ---------------------------------------------------------------------------
# Group A — RESULT_INGRESS_CONTINUITY_LEGALITY_POLICY sentinel
# ---------------------------------------------------------------------------


@_SKIP
class TestGroupA_PolicySentinel:
    def test_a1_sentinel_present(self) -> None:
        """AC6: RESULT_INGRESS_CONTINUITY_LEGALITY_POLICY must be defined."""
        assert hasattr(_tl, "RESULT_INGRESS_CONTINUITY_LEGALITY_POLICY")

    def test_a2_sentinel_is_non_empty_string(self) -> None:
        """AC6: Policy sentinel must be a non-empty string."""
        assert isinstance(_tl.RESULT_INGRESS_CONTINUITY_LEGALITY_POLICY, str)
        assert len(_tl.RESULT_INGRESS_CONTINUITY_LEGALITY_POLICY) > 0

    def test_a3_sentinel_references_terminal_result_ingestion(self) -> None:
        """AC6: Sentinel must mention the canonical path name."""
        assert "TERMINAL_RESULT_INGESTION" in _tl.RESULT_INGRESS_CONTINUITY_LEGALITY_POLICY


# ---------------------------------------------------------------------------
# Group B — _check_result_ingress_continuity_legality helper unit-level
# ---------------------------------------------------------------------------


@_SKIP
class TestGroupB_CheckHelper:
    def test_b1_helper_exists_and_callable(self) -> None:
        """AC7: _check_result_ingress_continuity_legality must exist and be callable."""
        assert hasattr(_tl, "_check_result_ingress_continuity_legality")
        assert callable(_tl._check_result_ingress_continuity_legality)

    def test_b2_unavailable_authority_returns_allow(self) -> None:
        """AC8: authority absent → ("allow", False)."""
        with patch.object(_tl, "_evaluate_continuity_legality", None):
            verdict, rejected = _tl._check_result_ingress_continuity_legality(
                _make_message()
            )
        assert verdict == "allow"
        assert rejected is False

    def test_b3_reject_verdict_returns_rejected_true(self) -> None:
        """AC9: REJECT verdict → ("reject", True)."""
        with patch.object(
            _tl, "_evaluate_continuity_legality", return_value=_make_report("reject")
        ):
            verdict, rejected = _tl._check_result_ingress_continuity_legality(
                _make_message()
            )
        assert verdict == "reject"
        assert rejected is True

    def test_b4_require_review_verdict_returns_rejected_true(self) -> None:
        """AC10: REQUIRE_REVIEW verdict → ("require_review", True)."""
        with patch.object(
            _tl,
            "_evaluate_continuity_legality",
            return_value=_make_report("require_review"),
        ):
            verdict, rejected = _tl._check_result_ingress_continuity_legality(
                _make_message()
            )
        assert verdict == "require_review"
        assert rejected is True

    def test_b5_allow_verdict_returns_rejected_false(self) -> None:
        """AC11: ALLOW verdict → ("allow", False)."""
        with patch.object(
            _tl, "_evaluate_continuity_legality", return_value=_make_report("allow")
        ):
            verdict, rejected = _tl._check_result_ingress_continuity_legality(
                _make_message()
            )
        assert verdict == "allow"
        assert rejected is False

    def test_b6_exception_in_authority_returns_allow(self) -> None:
        """AC13: exceptions inside authority call → ("allow", False), no raise."""

        def _raise(*_a: Any, **_kw: Any) -> Any:
            raise RuntimeError("simulated authority crash")

        with patch.object(_tl, "_evaluate_continuity_legality", _raise):
            verdict, rejected = _tl._check_result_ingress_continuity_legality(
                _make_message()
            )
        assert verdict == "allow"
        assert rejected is False

    def test_b7_continuity_fields_extracted_from_message(self) -> None:
        """AC12: helper passes device_id, runtime_session_id, contract_id etc. to authority."""
        captured_ctx: list = []

        def _capture_evaluate(path: Any, ctx: Any) -> Any:
            captured_ctx.append(ctx)
            return _make_report("allow")

        msg = _make_message(
            device_id="dev-b7",
            runtime_session_id="rsid-b7",
            runtime_attachment_session_id="raid-b7",
            durable_session_id="dsid-b7",
            contract_id="cid-b7",
            flow_id="fid-b7",
        )
        with patch.object(_tl, "_evaluate_continuity_legality", _capture_evaluate):
            _tl._check_result_ingress_continuity_legality(msg)

        assert captured_ctx, "evaluate must have been called"
        ctx = captured_ctx[0]
        assert ctx.device_id == "dev-b7"
        assert ctx.runtime_session_id == "rsid-b7"
        assert ctx.runtime_attachment_session_id == "raid-b7"
        assert ctx.durable_session_id == "dsid-b7"
        assert ctx.contract_id == "cid-b7"
        assert ctx.flow_id == "fid-b7"

    def test_b8_continuity_fields_extracted_from_payload(self) -> None:
        """AC12: helper also reads continuity fields from nested payload dict."""
        captured_ctx: list = []

        def _capture(path: Any, ctx: Any) -> Any:
            captured_ctx.append(ctx)
            return _make_report("allow")

        msg = {
            "task_id": "t-b8",
            "device_id": "dev-b8",
            "status": "completed",
            "payload": {
                "runtime_session_id": "rsid-b8",
                "durable_session_id": "dsid-b8",
                "contract_id": "cid-b8",
            },
        }
        with patch.object(_tl, "_evaluate_continuity_legality", _capture):
            _tl._check_result_ingress_continuity_legality(msg)

        assert captured_ctx
        ctx = captured_ctx[0]
        assert ctx.runtime_session_id == "rsid-b8"
        assert ctx.durable_session_id == "dsid-b8"
        assert ctx.contract_id == "cid-b8"

    def test_b9_terminal_result_ingestion_path_used(self) -> None:
        """AC12: helper invokes authority with TERMINAL_RESULT_INGESTION path."""
        captured_path: list = []

        def _capture(path: Any, ctx: Any) -> Any:
            captured_path.append(path)
            return _make_report("allow")

        with patch.object(_tl, "_evaluate_continuity_legality", _capture):
            _tl._check_result_ingress_continuity_legality(_make_message())

        assert captured_path
        # Accept both the enum member and its string value for robustness.
        path_val = (
            captured_path[0].value
            if hasattr(captured_path[0], "value")
            else str(captured_path[0])
        )
        assert path_val == "terminal_result_ingestion"


# ---------------------------------------------------------------------------
# Group C — handle_task_result: valid continuity → truth chain runs
# ---------------------------------------------------------------------------


@_SKIP
class TestGroupC_ValidContinuityTruthChainRuns:
    def test_c1_truth_chain_runs_when_allowed(self) -> None:
        """AC1: _run_task_result_truth_chain is called when V1 verdict is allow."""
        bridge = _make_bridge()
        msg = _make_message(task_id="t-c1", device_id="dev-c1")
        ttc_calls: list = []

        def _fake_ttc(m: Any, *, task_id: Any, result_status: Any) -> Any:
            ttc_calls.append(task_id)
            return MagicMock(is_truth_chain_complete=True, incomplete_reason="")

        with patch.object(
            _tl, "_evaluate_continuity_legality", return_value=_make_report("allow")
        ):
            with patch.object(_tl, "_run_task_result_truth_chain", _fake_ttc):
                with patch.object(_tl, "store_task_result", None):
                    _run(_tl.handle_task_result(bridge, None, msg))

        assert "t-c1" in ttc_calls, "truth chain must run for valid continuity"

    def test_c2_valid_flow_does_not_raise(self) -> None:
        """AC1: handle_task_result completes without raising for allowed result."""
        bridge = _make_bridge()
        msg = _make_message(task_id="t-c2")

        with patch.object(
            _tl, "_evaluate_continuity_legality", return_value=_make_report("allow")
        ):
            with patch.object(_tl, "_run_task_result_truth_chain", None):
                with patch.object(_tl, "store_task_result", None):
                    _run(_tl.handle_task_result(bridge, None, msg))  # must not raise

    def test_c3_future_resolved_for_valid_result(self) -> None:
        """AC14: pending future is resolved when continuity is valid."""
        resolved: list = []

        async def _inner() -> None:
            bridge = _make_bridge()
            loop = asyncio.get_running_loop()
            fut: asyncio.Future = loop.create_future()
            bridge._pending_responses["t-c3"] = fut
            msg = _make_message(task_id="t-c3", device_id="dev-c3")

            with patch.object(
                _tl, "_evaluate_continuity_legality", return_value=_make_report("allow")
            ):
                with patch.object(_tl, "_run_task_result_truth_chain", None):
                    with patch.object(_tl, "store_task_result", None):
                        await _tl.handle_task_result(bridge, None, msg)

            resolved.append(fut.done())

        _run(_inner())
        assert resolved[0], "future must be resolved for a valid result"

    def test_c4_device_state_cleared_for_valid_result(self) -> None:
        """AC14: device state is cleared to None when continuity is valid."""

        async def _inner() -> Any:
            bridge = _make_bridge()
            bridge._devices["dev-c4"] = MagicMock()
            bridge._devices["dev-c4"].current_task_id = "t-c4"
            msg = _make_message(task_id="t-c4", device_id="dev-c4")

            with patch.object(
                _tl,
                "_evaluate_continuity_legality",
                return_value=_make_report("allow"),
            ):
                with patch.object(_tl, "_run_task_result_truth_chain", None):
                    with patch.object(_tl, "store_task_result", None):
                        await _tl.handle_task_result(bridge, None, msg)

            return bridge._devices["dev-c4"].current_task_id

        result = _run(_inner())
        assert result is None, "device current_task_id must be cleared"


# ---------------------------------------------------------------------------
# Group D — handle_task_result: REJECT → truth chain skipped
# ---------------------------------------------------------------------------


@_SKIP
class TestGroupD_RejectedContinuityTruthChainSkipped:
    def test_d1_truth_chain_skipped_on_reject(self) -> None:
        """AC2/AC3: truth chain must NOT run when V1 returns REJECT."""
        bridge = _make_bridge()
        msg = _make_message(task_id="t-d1", device_id="dev-d1")
        ttc_calls: list = []

        def _fake_ttc(m: Any, *, task_id: Any, result_status: Any) -> Any:
            ttc_calls.append(task_id)
            return MagicMock(is_truth_chain_complete=True, incomplete_reason="")

        with patch.object(
            _tl, "_evaluate_continuity_legality", return_value=_make_report("reject")
        ):
            with patch.object(_tl, "_run_task_result_truth_chain", _fake_ttc):
                with patch.object(_tl, "store_task_result", None):
                    _run(_tl.handle_task_result(bridge, None, msg))

        assert not ttc_calls, "truth chain must be skipped when continuity is rejected"

    def test_d2_reconcile_skipped_on_reject(self) -> None:
        """AC2/AC3: reconciler must NOT run when V1 returns REJECT."""
        bridge = _make_bridge()
        msg = _make_message(
            task_id="t-d2", device_id="dev-d2", session_id="s-d2"
        )
        reconcile_calls: list = []

        def _fake_reconcile(m: Any) -> Any:
            reconcile_calls.append(True)
            return MagicMock(was_updated=False, reject_reason="", envelope=None, record=None)

        with patch.object(
            _tl, "_evaluate_continuity_legality", return_value=_make_report("reject")
        ):
            with patch.object(_tl, "_reconcile_inbound_message", _fake_reconcile):
                with patch.object(_tl, "_run_task_result_truth_chain", None):
                    with patch.object(_tl, "store_task_result", None):
                        _run(_tl.handle_task_result(bridge, None, msg))

        assert not reconcile_calls, "reconciler must not be called on rejection"

    def test_d3_participant_truth_ingest_skipped_on_reject(self) -> None:
        """AC2/AC3: participant truth ingest must NOT run when V1 returns REJECT."""
        bridge = _make_bridge()
        msg = _make_message(task_id="t-d3", device_id="dev-d3")
        ingest_calls: list = []

        def _fake_ingest(m: Any, **_kw: Any) -> Any:
            ingest_calls.append(True)
            return MagicMock(was_reconciled=False, reject_reason="", envelope=None)

        with patch.object(
            _tl, "_evaluate_continuity_legality", return_value=_make_report("reject")
        ):
            with patch.object(_tl, "_ingest_participant_truth", _fake_ingest):
                with patch.object(_tl, "_run_task_result_truth_chain", None):
                    with patch.object(_tl, "store_task_result", None):
                        _run(_tl.handle_task_result(bridge, None, msg))

        assert not ingest_calls, "participant truth ingest must not be called on rejection"

    def test_d4_memory_backflow_skipped_on_reject(self) -> None:
        """AC3: memory backflow must NOT run when V1 returns REJECT."""
        bridge = _make_bridge()
        msg = _make_message(task_id="t-d4", device_id="dev-d4")
        backflow_calls: list = []

        async def _fake_backflow(**_kw: Any) -> None:
            backflow_calls.append(True)

        with patch.object(
            _tl, "_evaluate_continuity_legality", return_value=_make_report("reject")
        ):
            with patch.object(_tl, "_run_task_result_truth_chain", None):
                with patch.object(_tl, "store_task_result", _fake_backflow):
                    _run(_tl.handle_task_result(bridge, None, msg))

        assert not backflow_calls, "memory backflow must not run on rejection"

    def test_d5_handle_does_not_raise_on_reject(self) -> None:
        """AC3: rejection must not propagate as an exception."""
        bridge = _make_bridge()
        msg = _make_message(task_id="t-d5")

        with patch.object(
            _tl, "_evaluate_continuity_legality", return_value=_make_report("reject")
        ):
            with patch.object(_tl, "_run_task_result_truth_chain", None):
                with patch.object(_tl, "store_task_result", None):
                    _run(_tl.handle_task_result(bridge, None, msg))  # must not raise


# ---------------------------------------------------------------------------
# Group E — handle_task_result: require_review → truth chain skipped
# ---------------------------------------------------------------------------


@_SKIP
class TestGroupE_RequireReviewTruthChainSkipped:
    def test_e1_truth_chain_skipped_on_require_review(self) -> None:
        """AC2/AC3: truth chain must NOT run when V1 returns REQUIRE_REVIEW."""
        bridge = _make_bridge()
        msg = _make_message(task_id="t-e1")
        ttc_calls: list = []

        def _fake_ttc(m: Any, *, task_id: Any, result_status: Any) -> Any:
            ttc_calls.append(task_id)
            return MagicMock(is_truth_chain_complete=True, incomplete_reason="")

        with patch.object(
            _tl,
            "_evaluate_continuity_legality",
            return_value=_make_report("require_review"),
        ):
            with patch.object(_tl, "_run_task_result_truth_chain", _fake_ttc):
                with patch.object(_tl, "store_task_result", None):
                    _run(_tl.handle_task_result(bridge, None, msg))

        assert not ttc_calls, "truth chain must be skipped on require_review"

    def test_e2_does_not_raise_on_require_review(self) -> None:
        """AC3: require_review rejection must not raise."""
        bridge = _make_bridge()
        msg = _make_message(task_id="t-e2")

        with patch.object(
            _tl,
            "_evaluate_continuity_legality",
            return_value=_make_report("require_review"),
        ):
            with patch.object(_tl, "_run_task_result_truth_chain", None):
                with patch.object(_tl, "store_task_result", None):
                    _run(_tl.handle_task_result(bridge, None, msg))  # must not raise


# ---------------------------------------------------------------------------
# Group F — handle_task_result: authority unavailable → allow-through
# ---------------------------------------------------------------------------


@_SKIP
class TestGroupF_AuthorityUnavailableAllowThrough:
    def test_f1_truth_chain_runs_when_authority_absent(self) -> None:
        """AC5: when authority module is absent, truth chain must still run."""
        bridge = _make_bridge()
        msg = _make_message(task_id="t-f1")
        ttc_calls: list = []

        def _fake_ttc(m: Any, *, task_id: Any, result_status: Any) -> Any:
            ttc_calls.append(task_id)
            return MagicMock(is_truth_chain_complete=True, incomplete_reason="")

        # Simulate authority unavailable by setting evaluate to None.
        with patch.object(_tl, "_evaluate_continuity_legality", None):
            with patch.object(_tl, "_run_task_result_truth_chain", _fake_ttc):
                with patch.object(_tl, "store_task_result", None):
                    _run(_tl.handle_task_result(bridge, None, msg))

        assert "t-f1" in ttc_calls, "truth chain must run when authority is absent"

    def test_f2_handler_does_not_raise_when_authority_absent(self) -> None:
        """AC5: handler completes normally when authority is unavailable."""
        bridge = _make_bridge()
        msg = _make_message(task_id="t-f2")

        with patch.object(_tl, "_evaluate_continuity_legality", None):
            with patch.object(_tl, "_run_task_result_truth_chain", None):
                with patch.object(_tl, "store_task_result", None):
                    _run(_tl.handle_task_result(bridge, None, msg))  # must not raise

    def test_f3_truth_chain_runs_when_authority_raises(self) -> None:
        """AC5: when authority raises an exception, truth chain must still run."""
        bridge = _make_bridge()
        msg = _make_message(task_id="t-f3")
        ttc_calls: list = []

        def _fake_ttc(m: Any, *, task_id: Any, result_status: Any) -> Any:
            ttc_calls.append(task_id)
            return MagicMock(is_truth_chain_complete=True, incomplete_reason="")

        def _raising(*_a: Any, **_kw: Any) -> Any:
            raise RuntimeError("authority crash")

        with patch.object(_tl, "_evaluate_continuity_legality", _raising):
            with patch.object(_tl, "_run_task_result_truth_chain", _fake_ttc):
                with patch.object(_tl, "store_task_result", None):
                    _run(_tl.handle_task_result(bridge, None, msg))

        assert "t-f3" in ttc_calls, "truth chain must run when authority raises"


# ---------------------------------------------------------------------------
# Group G — handle_task_result: delegated / contract_id flows unaffected
# ---------------------------------------------------------------------------


@_SKIP
class TestGroupG_DelegatedHandoffFlowsCompatible:
    def test_g1_delegated_flow_with_contract_id_allowed(self) -> None:
        """AC4: results carrying contract_id (delegated flow) pass when allowed."""
        bridge = _make_bridge()
        msg = _make_message(
            task_id="t-g1",
            device_id="dev-g1",
            contract_id="contract-g1",
            session_id="sess-g1",
        )
        ttc_calls: list = []

        def _fake_ttc(m: Any, *, task_id: Any, result_status: Any) -> Any:
            ttc_calls.append(task_id)
            return MagicMock(is_truth_chain_complete=True, incomplete_reason="")

        with patch.object(
            _tl, "_evaluate_continuity_legality", return_value=_make_report("allow")
        ):
            with patch.object(_tl, "_run_task_result_truth_chain", _fake_ttc):
                with patch.object(_tl, "store_task_result", None):
                    _run(_tl.handle_task_result(bridge, None, msg))

        assert "t-g1" in ttc_calls, "delegated flow must enter truth chain when allowed"

    def test_g2_handoff_flow_with_runtime_attachment_session_allowed(self) -> None:
        """AC4: results carrying runtime_attachment_session_id (handoff) pass when allowed."""
        bridge = _make_bridge()
        msg = _make_message(
            task_id="t-g2",
            device_id="dev-g2",
            runtime_attachment_session_id="att-g2",
        )
        ttc_calls: list = []

        def _fake_ttc(m: Any, *, task_id: Any, result_status: Any) -> Any:
            ttc_calls.append(task_id)
            return MagicMock(is_truth_chain_complete=True, incomplete_reason="")

        with patch.object(
            _tl, "_evaluate_continuity_legality", return_value=_make_report("allow")
        ):
            with patch.object(_tl, "_run_task_result_truth_chain", _fake_ttc):
                with patch.object(_tl, "store_task_result", None):
                    _run(_tl.handle_task_result(bridge, None, msg))

        assert "t-g2" in ttc_calls, "handoff flow must enter truth chain when allowed"

    def test_g3_grouped_flow_with_session_id_allowed(self) -> None:
        """AC4: results from grouped execution (durable_session_id) pass when allowed."""
        bridge = _make_bridge()
        msg = _make_message(
            task_id="t-g3",
            device_id="dev-g3",
            durable_session_id="durable-g3",
        )
        ttc_calls: list = []

        def _fake_ttc(m: Any, *, task_id: Any, result_status: Any) -> Any:
            ttc_calls.append(task_id)
            return MagicMock(is_truth_chain_complete=True, incomplete_reason="")

        with patch.object(
            _tl, "_evaluate_continuity_legality", return_value=_make_report("allow")
        ):
            with patch.object(_tl, "_run_task_result_truth_chain", _fake_ttc):
                with patch.object(_tl, "store_task_result", None):
                    _run(_tl.handle_task_result(bridge, None, msg))

        assert "t-g3" in ttc_calls, "grouped flow must enter truth chain when allowed"

    def test_g4_message_without_continuity_fields_allowed(self) -> None:
        """AC4: minimal message (no identity fields) should be allowed through."""
        bridge = _make_bridge()
        # Minimal message — no session/runtime/attachment fields.
        msg = {"task_id": "t-g4", "device_id": "dev-g4", "status": "completed"}
        ttc_calls: list = []

        def _fake_ttc(m: Any, *, task_id: Any, result_status: Any) -> Any:
            ttc_calls.append(task_id)
            return MagicMock(is_truth_chain_complete=True, incomplete_reason="")

        # Authority returns ALLOW for empty identity context (no evidence to reject on).
        with patch.object(
            _tl, "_evaluate_continuity_legality", return_value=_make_report("allow")
        ):
            with patch.object(_tl, "_run_task_result_truth_chain", _fake_ttc):
                with patch.object(_tl, "store_task_result", None):
                    _run(_tl.handle_task_result(bridge, None, msg))

        assert "t-g4" in ttc_calls, "minimal message must enter truth chain when allowed"


# ---------------------------------------------------------------------------
# Group H — handle_task_result: future not resolved on rejection
# ---------------------------------------------------------------------------


@_SKIP
class TestGroupH_FutureNotResolvedOnRejection:
    def test_h1_future_not_resolved_when_rejected(self) -> None:
        """AC15: pending future must NOT be resolved when continuity is rejected."""

        async def _inner() -> bool:
            bridge = _make_bridge()
            loop = asyncio.get_running_loop()
            fut: asyncio.Future = loop.create_future()
            bridge._pending_responses["t-h1"] = fut
            msg = _make_message(task_id="t-h1", device_id="dev-h1")

            with patch.object(
                _tl,
                "_evaluate_continuity_legality",
                return_value=_make_report("reject"),
            ):
                with patch.object(_tl, "_run_task_result_truth_chain", None):
                    with patch.object(_tl, "store_task_result", None):
                        await _tl.handle_task_result(bridge, None, msg)

            return fut.done()

        resolved = _run(_inner())
        assert not resolved, "future must NOT be resolved when result ingress is rejected"

    def test_h2_future_not_resolved_when_require_review(self) -> None:
        """AC15: pending future must NOT be resolved when verdict is require_review."""

        async def _inner() -> bool:
            bridge = _make_bridge()
            loop = asyncio.get_running_loop()
            fut: asyncio.Future = loop.create_future()
            bridge._pending_responses["t-h2"] = fut
            msg = _make_message(task_id="t-h2", device_id="dev-h2")

            with patch.object(
                _tl,
                "_evaluate_continuity_legality",
                return_value=_make_report("require_review"),
            ):
                with patch.object(_tl, "_run_task_result_truth_chain", None):
                    with patch.object(_tl, "store_task_result", None):
                        await _tl.handle_task_result(bridge, None, msg)

            return fut.done()

        resolved = _run(_inner())
        assert not resolved, (
            "future must NOT be resolved when require_review rejects result ingress"
        )
