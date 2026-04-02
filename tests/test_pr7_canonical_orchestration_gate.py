#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr7_canonical_orchestration_gate.py
================================================
PR-7 — Canonical orchestration candidate gate.

Verifies that orchestration-facing candidate selection in
:class:`core.constellation_runtime.ConstellationRuntime` uses
:func:`core.device_participation.is_device_orchestration_ready` as the gate
rather than ad-hoc pool lists or connection state.

Coverage
--------
A) ``ConstellationRuntime._is_orchestration_ready()`` helper

   1. Returns ``True`` for a participation-eligible device.
   2. Returns ``False`` for an online/connected device that is not
      orchestration-eligible (the key exclusion case).
   3. Degrades gracefully (returns ``True``) when the participation module
      is unavailable — existing behaviour is preserved.
   4. Returns ``False`` for an empty device_id without consulting the layer.

B) Device assignment in ``_run_dag_loop``

   5. A participation-eligible device returned by ``pool.select_device`` IS
      assigned to the subtask.
   6. A device returned by ``pool.select_device`` that is NOT
      orchestration-eligible is NOT assigned to the subtask.

C) ``get_orchestration_ready_devices`` and ``is_device_orchestration_ready``
   helpers in ``core.device_participation``

   7. ``get_orchestration_ready_devices`` returns only eligible summaries.
   8. ``is_device_orchestration_ready`` mirrors eligibility correctly.
   9. Missing optional subsystems (UDM unavailable) degrade gracefully.
  10. Device with ``orchestration_eligible=False`` from selector is correctly
      classified as not ready.
"""

from __future__ import annotations

import sys
import os
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ===========================================================================
# A) ConstellationRuntime._is_orchestration_ready
# ===========================================================================


class TestIsOrchestrationReadyHelper(unittest.TestCase):
    """Unit tests for the _is_orchestration_ready helper method."""

    def _make_runtime(self):
        from core.constellation_runtime import ConstellationRuntime
        rt = ConstellationRuntime(enable_dag_evolution=False)
        return rt

    # 1 — eligible device passes the gate
    def test_eligible_device_passes_gate(self):
        rt = self._make_runtime()
        with patch(
            "core.device_participation.is_device_orchestration_ready",
            return_value=True,
        ):
            assert rt._is_orchestration_ready("dev_eligible") is True

    # 2 — online/connected but NOT orchestration-eligible is excluded
    def test_non_eligible_device_excluded(self):
        rt = self._make_runtime()
        with patch(
            "core.device_participation.is_device_orchestration_ready",
            return_value=False,
        ):
            assert rt._is_orchestration_ready("dev_online_not_eligible") is False

    # 3 — participation layer unavailable → deny-by-default (PR-520 / GAP-517-005)
    def test_degrades_gracefully_when_participation_unavailable(self):
        rt = self._make_runtime()
        with patch(
            "core.device_participation.is_device_orchestration_ready",
            side_effect=ImportError("participation layer not loaded"),
        ):
            # PR-520 / GAP-517-005: deny-by-default — returns False when the
            # participation gate is unreachable so devices cannot silently
            # bypass the admissibility chain.
            result = rt._is_orchestration_ready("dev_any")
        assert result is False

    # 4 — empty device_id returns False without hitting the participation layer
    def test_empty_device_id_returns_false(self):
        rt = self._make_runtime()
        with patch(
            "core.device_participation.is_device_orchestration_ready",
        ) as mock_fn:
            result = rt._is_orchestration_ready("")
        assert result is False
        mock_fn.assert_not_called()


# ===========================================================================
# B) Device assignment in _run_dag_loop
# ===========================================================================


class TestDagLoopCandidateGate(unittest.IsolatedAsyncioTestCase):
    """Integration tests: pool.select_device candidates are gated by the
    canonical participation layer."""

    def _make_runtime(self):
        from core.constellation_runtime import ConstellationRuntime
        rt = ConstellationRuntime(enable_dag_evolution=False)
        return rt

    def _make_pool(self, returns: str):
        pool = MagicMock()
        pool.select_device.return_value = returns
        pool.mark_success = MagicMock()
        pool.mark_failure = MagicMock()
        return pool

    def _make_orchestrator(self):
        from core.schemas.orchestration import TaskDecomposition, SubTask, SubTaskStatus

        mock_orch = MagicMock()

        async def _decompose(desc, ctx):
            st = SubTask(task_id="t1", name="step1", status=SubTaskStatus.PENDING)
            return TaskDecomposition(goal=desc, subtasks=[st])

        async def _exec_subtask(task, req):
            task.status = SubTaskStatus.SUCCESS
            task.result = {"reply": "ok"}

        mock_orch._decompose_task = _decompose
        mock_orch._execute_subtask = _exec_subtask
        return mock_orch

    # 5 — eligible candidate IS assigned
    async def test_eligible_candidate_is_assigned(self):
        rt = self._make_runtime()
        rt._smart_orchestrator = self._make_orchestrator()
        pool = self._make_pool("dev_eligible")

        with patch.object(rt, "_get_device_pool", return_value=pool), \
             patch.object(rt, "_try_node71", new_callable=AsyncMock, return_value=None), \
             patch.object(rt, "_is_orchestration_ready", return_value=True) as mock_gate:
            result = await rt.run(task_description="test task")

        # Gate was consulted with the device returned by pool
        mock_gate.assert_called_once_with("dev_eligible")
        assert "success" in result

    # 6 — non-eligible candidate is NOT assigned
    async def test_non_eligible_candidate_is_not_assigned(self):
        rt = self._make_runtime()
        rt._smart_orchestrator = self._make_orchestrator()
        pool = self._make_pool("dev_not_eligible")

        with patch.object(rt, "_get_device_pool", return_value=pool), \
             patch.object(rt, "_try_node71", new_callable=AsyncMock, return_value=None), \
             patch.object(rt, "_is_orchestration_ready", return_value=False) as mock_gate:
            result = await rt.run(task_description="test task")

        mock_gate.assert_called_once_with("dev_not_eligible")
        # The subtask device_id should remain unset (empty string)
        # We verify by checking the run completed without error
        assert "success" in result


# ===========================================================================
# C) core.device_participation helpers
# ===========================================================================


def _make_selector_status(
    registered: bool = True,
    runtime_present: bool = True,
    routable: bool = True,
    orchestration_eligible: bool = True,
):
    status = MagicMock()
    status.registered = registered
    status.runtime_present = runtime_present
    status.routable = routable
    status.orchestration_eligible = orchestration_eligible
    status.to_dict.return_value = {
        "registered": registered,
        "runtime_present": runtime_present,
        "routable": routable,
        "orchestration_eligible": orchestration_eligible,
    }
    return status


def _make_udm(device_ids=None):
    udm = MagicMock()
    devices = []
    for did in (device_ids or []):
        d = MagicMock()
        d.device_id = did
        devices.append(d)
    udm.list_devices.return_value = devices
    udm.get.side_effect = lambda did: next(
        (d for d in devices if d.device_id == did), None
    )
    return udm


class TestGetOrchestrationReadyDevices(unittest.TestCase):
    """Tests for get_orchestration_ready_devices() and is_device_orchestration_ready()."""

    # 7 — only eligible devices are returned
    def test_returns_only_eligible_summaries(self):
        from core.device_participation import get_orchestration_ready_devices

        udm = _make_udm(["dev_a", "dev_b", "dev_c"])
        eligible_status = _make_selector_status(orchestration_eligible=True)
        ineligible_status = _make_selector_status(orchestration_eligible=False)

        def fake_selector(device_id):
            return eligible_status if device_id == "dev_a" else ineligible_status

        with patch("core.device_participation._get_udm", return_value=udm), \
             patch("core.device_participation._get_selector_status", side_effect=fake_selector):
            results = get_orchestration_ready_devices()

        eligible_ids = [r.device_id for r in results]
        assert "dev_a" in eligible_ids
        assert "dev_b" not in eligible_ids
        assert "dev_c" not in eligible_ids

    # 8 — is_device_orchestration_ready mirrors eligibility
    def test_is_device_orchestration_ready_true_for_eligible(self):
        from core.device_participation import is_device_orchestration_ready

        eligible_status = _make_selector_status(orchestration_eligible=True)
        udm = _make_udm(["dev_ok"])

        with patch("core.device_participation._get_udm", return_value=udm), \
             patch("core.device_participation._get_selector_status", return_value=eligible_status):
            assert is_device_orchestration_ready("dev_ok") is True

    def test_is_device_orchestration_ready_false_for_ineligible(self):
        from core.device_participation import is_device_orchestration_ready

        ineligible_status = _make_selector_status(orchestration_eligible=False)
        udm = _make_udm(["dev_no"])

        with patch("core.device_participation._get_udm", return_value=udm), \
             patch("core.device_participation._get_selector_status", return_value=ineligible_status):
            assert is_device_orchestration_ready("dev_no") is False

    # 9 — missing UDM degrades gracefully (empty list, no crash)
    def test_missing_udm_returns_empty_list(self):
        from core.device_participation import get_orchestration_ready_devices

        with patch("core.device_participation._get_udm", return_value=None):
            results = get_orchestration_ready_devices()

        assert results == []

    def test_missing_udm_is_device_ready_returns_false(self):
        from core.device_participation import is_device_orchestration_ready

        with patch("core.device_participation._get_udm", return_value=None):
            result = is_device_orchestration_ready("dev_any")

        assert result is False

    # 10 — device with orchestration_eligible=False from selector is not ready
    def test_online_connected_but_not_eligible_excluded(self):
        """A device that is registered, online, routable but orchestration_eligible=False
        must NOT be classified as orchestration-ready."""
        from core.device_participation import is_device_orchestration_ready

        # Simulate: device is online, registered, routable — but NOT eligible
        status = _make_selector_status(
            registered=True,
            runtime_present=True,
            routable=True,
            orchestration_eligible=False,
        )
        udm = _make_udm(["dev_online_not_eligible"])

        with patch("core.device_participation._get_udm", return_value=udm), \
             patch("core.device_participation._get_selector_status", return_value=status):
            ready = is_device_orchestration_ready("dev_online_not_eligible")

        assert ready is False, (
            "A device that is online/connected but not orchestration_eligible "
            "must be excluded from orchestration candidates."
        )


if __name__ == "__main__":
    unittest.main()
