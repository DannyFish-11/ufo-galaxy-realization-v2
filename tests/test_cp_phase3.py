"""
tests/test_cp_phase3.py
=======================

Control Plane Phase 3 tests: Distributed Swarm + Remote Agent Dispatch.

Covers:
  A) SwarmAgentManifest serialisation / round-trip.
  B) SwarmCoordinator manifest creation and device assignment (unit, mocked).
  C) SwarmCoordinator remote dispatch flow (mocked CommandRouter).
  D) Audit event emission: AGENT_DISPATCHED, AGENT_EXECUTED, AGENT_RESULT_RECEIVED.
  E) Windows AIP client — _execute_agent_task handles manifest context fields.
  F) Windows AIP client — _agent_execute_result_msg propagates manifest_id.
  G) No-device / router-unavailable failure paths.
  H) AGENT_EXECUTED event type exists in audit_ledger EventType enum.
"""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ===========================================================================
# A) SwarmAgentManifest serialisation
# ===========================================================================

class TestSwarmAgentManifestSerialization:
    """Verify that SwarmAgentManifest is fully JSON-serialisable and round-trips."""

    def test_basic_construction(self):
        from core.control_plane.swarm_manifest import SwarmAgentManifest

        m = SwarmAgentManifest(
            agent_id="agent_001",
            template="research",
            system_prompt="You are a research agent.",
            task="Summarise Q3 data",
            session_id="sess_abc",
            trace_id="trace_xyz",
            task_id="task_001",
        )
        assert m.agent_id == "agent_001"
        assert m.template == "research"
        assert m.manifest_id.startswith("swm_")
        assert m.tool_schemas == []
        assert m.memory_snapshot == {}

    def test_json_round_trip(self):
        from core.control_plane.swarm_manifest import SwarmAgentManifest

        original = SwarmAgentManifest(
            agent_id="agent_rtrip",
            template="data_analyst",
            system_prompt="Analyse the dataset.",
            tool_schemas=[{"name": "query_db", "description": "Query DB"}],
            memory_snapshot={"last_query": "SELECT *"},
            task="Full analysis",
            subtask="Step 1: fetch data",
            session_id="sess_rt",
            trace_id="trace_rt",
            task_id="task_rt_01",
            target_device_id="win_01",
            required_capabilities=["screen"],
            timeout_seconds=90.0,
            member_name="Analyst",
        )

        json_str = original.model_dump_json()
        restored = SwarmAgentManifest.model_validate_json(json_str)

        assert restored.agent_id == original.agent_id
        assert restored.template == original.template
        assert restored.system_prompt == original.system_prompt
        assert restored.tool_schemas == original.tool_schemas
        assert restored.memory_snapshot == original.memory_snapshot
        assert restored.task == original.task
        assert restored.subtask == original.subtask
        assert restored.session_id == original.session_id
        assert restored.trace_id == original.trace_id
        assert restored.task_id == original.task_id
        assert restored.target_device_id == original.target_device_id
        assert restored.required_capabilities == original.required_capabilities
        assert restored.timeout_seconds == original.timeout_seconds
        assert restored.member_name == original.member_name
        assert restored.manifest_id == original.manifest_id

    def test_model_dump_is_json_serialisable(self):
        import json
        from core.control_plane.swarm_manifest import SwarmAgentManifest

        m = SwarmAgentManifest(
            agent_id="a1",
            task="test",
            session_id="s1",
            trace_id="t1",
            task_id="tk1",
        )
        dumped = m.model_dump(mode="json")
        # Should not raise
        serialised = json.dumps(dumped)
        assert len(serialised) > 20

    def test_to_agent_execute_payload_uses_subtask(self):
        from core.control_plane.swarm_manifest import SwarmAgentManifest

        m = SwarmAgentManifest(
            agent_id="a2",
            task="Main task",
            subtask="Specific subtask",
            session_id="s2",
            trace_id="t2",
            task_id="tk2",
            system_prompt="You are specialised.",
            tool_schemas=[{"name": "tool_a"}],
            memory_snapshot={"key": "val"},
        )
        payload = m.to_agent_execute_payload()

        assert payload["agent_id"] == "a2"
        assert payload["task"] == "Specific subtask"  # subtask overrides task
        assert payload["session_id"] == "s2"
        assert payload["context"]["system_prompt"] == "You are specialised."
        assert payload["context"]["tool_schemas"] == [{"name": "tool_a"}]
        assert payload["context"]["memory_snapshot"] == {"key": "val"}
        assert payload["context"]["manifest_id"] == m.manifest_id

    def test_to_agent_execute_payload_falls_back_to_task(self):
        from core.control_plane.swarm_manifest import SwarmAgentManifest

        m = SwarmAgentManifest(
            agent_id="a3",
            task="Main task only",
            session_id="s3",
            trace_id="t3",
            task_id="tk3",
        )
        payload = m.to_agent_execute_payload()
        assert payload["task"] == "Main task only"

    def test_from_team_member_factory(self):
        from core.control_plane.swarm_manifest import SwarmAgentManifest
        from dataclasses import dataclass

        @dataclass
        class FakeMember:
            agent_id: str = "ag_fake"
            agent_name: str = "FakeAgent"
            provider: str = "openai"
            model: str = "gpt-4"
            role_in_team: str = "analyst"
            template: str = "data_analyst"

        member = FakeMember()
        manifest = SwarmAgentManifest.from_team_member(
            member,
            task="Analyse data",
            session_id="s_fm",
            trace_id="tr_fm",
            task_id="tk_fm",
            tool_schemas=[{"name": "search"}],
            memory_snapshot={"memo": 1},
        )

        assert manifest.agent_id == "ag_fake"
        assert manifest.template == "data_analyst"
        assert "FakeAgent" in manifest.system_prompt
        assert manifest.tool_schemas == [{"name": "search"}]
        assert manifest.memory_snapshot == {"memo": 1}
        assert manifest.member_name == "FakeAgent"

    def test_unique_manifest_ids(self):
        from core.control_plane.swarm_manifest import SwarmAgentManifest

        ids = {
            SwarmAgentManifest(agent_id=f"a{i}", task="t", session_id="s",
                               trace_id="tr", task_id=f"tk{i}").manifest_id
            for i in range(20)
        }
        assert len(ids) == 20, "manifest_id must be unique per instance"


# ===========================================================================
# B) SwarmCoordinator — manifest building and device assignment
# ===========================================================================

class TestSwarmCoordinatorManifestBuilding:
    """Unit tests for manifest creation and device assignment logic."""

    def _make_member(self, idx: int = 0):
        from dataclasses import dataclass

        @dataclass
        class M:
            agent_id: str = f"ag_{idx}"
            agent_name: str = f"Agent{idx}"
            provider: str = "openai"
            model: str = "gpt-4"
            role_in_team: str = "worker"
            template: str = "research"

        return M()

    def test_coordinator_instantiates(self):
        from core.swarm_coordinator import SwarmCoordinator
        coord = SwarmCoordinator()
        assert coord is not None

    @pytest.mark.asyncio
    async def test_dispatch_team_no_device_skips(self):
        """When no device candidates are provided, members get no device assigned."""
        from core.swarm_coordinator import SwarmCoordinator
        from core.control_plane.audit_ledger import AuditLedger, EventType

        ledger = AuditLedger()
        coord = SwarmCoordinator(
            command_router=None,  # will fallback to None → no dispatch
            audit_ledger=ledger,
        )
        members = [self._make_member(0), self._make_member(1)]
        result = await coord.dispatch_team(
            members=members,
            task="Test task",
            session_id="s_nd",
            trace_id="tr_nd",
            task_id="tk_nd",
            device_candidates=None,  # no candidates → no device
        )

        # All members should fail (no device)
        assert all(not mr.success for mr in result.member_results)
        # TASK_FAILED events emitted
        failed_events = ledger.query(event_type=EventType.TASK_FAILED)
        assert len(failed_events) == 2

    @pytest.mark.asyncio
    async def test_device_assignment_via_scoring_engine(self):
        """Best device is selected from candidates using the scoring engine."""
        from core.swarm_coordinator import SwarmCoordinator
        from core.control_plane.smart_scheduler import DeviceScoreInput, DeviceScoringEngine
        from core.control_plane.audit_ledger import AuditLedger

        # Create a custom scoring engine
        engine = DeviceScoringEngine(require_all_capabilities=False)
        ledger = AuditLedger()

        # Mock router that returns success
        mock_router = MagicMock()
        mock_router.dispatch_agent_remote = AsyncMock(return_value={
            "success": True,
            "output": "done",
            "agent_id": "ag_0",
            "trace_id": "tr_sa",
            "task_id": "tk_sa",
            "session_id": "s_sa",
            "latency_ms": 12.3,
        })

        coord = SwarmCoordinator(
            command_router=mock_router,
            scoring_engine=engine,
            audit_ledger=ledger,
        )

        candidates = [
            DeviceScoreInput(device_id="dev_fast", ping_latency_ms=10.0, load_pct=5.0),
            DeviceScoreInput(device_id="dev_slow", ping_latency_ms=500.0, load_pct=80.0),
        ]
        members = [self._make_member(0)]

        result = await coord.dispatch_team(
            members=members,
            task="Task SA",
            session_id="s_sa",
            trace_id="tr_sa",
            task_id="tk_sa",
            device_candidates=candidates,
        )

        # The fast device should have been chosen
        call_kwargs = mock_router.dispatch_agent_remote.call_args
        assert call_kwargs.kwargs["device_id"] == "dev_fast"
        assert len(result.member_results) == 1


# ===========================================================================
# C) SwarmCoordinator — remote dispatch flow (mocked)
# ===========================================================================

class TestSwarmCoordinatorDispatchFlow:
    """Integration-style tests with mocked CommandRouter."""

    def _make_member(self, idx: int = 0):
        from dataclasses import dataclass

        @dataclass
        class M:
            agent_id: str = f"ag_d{idx}"
            agent_name: str = f"DispatchAgent{idx}"
            provider: str = "openai"
            model: str = "gpt-4"
            role_in_team: str = "executor"
            template: str = "research"

        return M()

    def _make_device_candidates(self, count: int = 1):
        from core.control_plane.smart_scheduler import DeviceScoreInput
        return [
            DeviceScoreInput(
                device_id=f"dev_{i:02d}",
                ping_latency_ms=float(10 + i * 5),
                load_pct=float(5 + i * 10),
            )
            for i in range(count)
        ]

    @pytest.mark.asyncio
    async def test_successful_dispatch_aggregates_results(self):
        """Successful dispatch produces correct TeamResult."""
        from core.swarm_coordinator import SwarmCoordinator
        from core.control_plane.audit_ledger import AuditLedger

        ledger = AuditLedger()
        mock_router = MagicMock()
        mock_router.dispatch_agent_remote = AsyncMock(side_effect=[
            {
                "success": True,
                "output": "Result from member 0",
                "agent_id": "ag_d0",
                "trace_id": "tr_df",
                "task_id": "tk_df_ag_d0",
                "session_id": "s_df",
                "latency_ms": 50.0,
            },
            {
                "success": True,
                "output": "Result from member 1",
                "agent_id": "ag_d1",
                "trace_id": "tr_df",
                "task_id": "tk_df_ag_d1",
                "session_id": "s_df",
                "latency_ms": 60.0,
            },
        ])

        coord = SwarmCoordinator(
            command_router=mock_router,
            audit_ledger=ledger,
        )
        members = [self._make_member(0), self._make_member(1)]
        candidates = self._make_device_candidates(1)

        result = await coord.dispatch_team(
            members=members,
            task="Parallel research task",
            session_id="s_df",
            trace_id="tr_df",
            task_id="tk_df",
            device_candidates=candidates,
        )

        assert result.strategy == "swarm_remote"
        assert len(result.member_results) == 2
        assert all(mr.success for mr in result.member_results)
        assert mock_router.dispatch_agent_remote.call_count == 2

    @pytest.mark.asyncio
    async def test_partial_failure_preserves_successful_results(self):
        """When one member fails, successful results are still collected."""
        from core.swarm_coordinator import SwarmCoordinator
        from core.control_plane.audit_ledger import AuditLedger

        ledger = AuditLedger()
        mock_router = MagicMock()
        mock_router.dispatch_agent_remote = AsyncMock(side_effect=[
            {"success": True, "output": "OK", "agent_id": "ag_d0",
             "trace_id": "tr_pf", "task_id": "tk_pf_0", "session_id": "s_pf"},
            Exception("connection timeout"),
        ])

        coord = SwarmCoordinator(command_router=mock_router, audit_ledger=ledger)
        members = [self._make_member(0), self._make_member(1)]
        candidates = self._make_device_candidates(1)

        result = await coord.dispatch_team(
            members=members,
            task="Partial fail task",
            session_id="s_pf",
            trace_id="tr_pf",
            task_id="tk_pf",
            device_candidates=candidates,
        )

        assert len(result.member_results) == 2
        successes = [mr for mr in result.member_results if mr.success]
        failures = [mr for mr in result.member_results if not mr.success]
        assert len(successes) == 1
        assert len(failures) == 1

    @pytest.mark.asyncio
    async def test_dispatch_passes_manifest_fields_to_router(self):
        """Context fields (system_prompt, tool_schemas, memory_snapshot) reach the router."""
        from core.swarm_coordinator import SwarmCoordinator
        from core.control_plane.audit_ledger import AuditLedger

        ledger = AuditLedger()
        mock_router = MagicMock()
        mock_router.dispatch_agent_remote = AsyncMock(return_value={
            "success": True, "output": "done",
            "agent_id": "ag_d0", "trace_id": "tr_mf",
            "task_id": "tk_mf_ag_d0", "session_id": "s_mf",
        })

        coord = SwarmCoordinator(command_router=mock_router, audit_ledger=ledger)
        members = [self._make_member(0)]
        candidates = self._make_device_candidates(1)

        await coord.dispatch_team(
            members=members,
            task="Field propagation test",
            session_id="s_mf",
            trace_id="tr_mf",
            task_id="tk_mf",
            device_candidates=candidates,
            system_prompt_template="Custom prompt for {name}",
            tool_schemas=[{"name": "my_tool"}],
            memory_snapshot={"k": "v"},
        )

        call_kwargs = mock_router.dispatch_agent_remote.call_args.kwargs
        assert call_kwargs["context"]["tool_schemas"] == [{"name": "my_tool"}]
        assert call_kwargs["context"]["memory_snapshot"] == {"k": "v"}
        assert "manifest_id" in call_kwargs["context"]

    @pytest.mark.asyncio
    async def test_synthesize_combines_results(self):
        """Synthesized output joins successful member results."""
        from core.swarm_coordinator import SwarmCoordinator
        from core.control_plane.audit_ledger import AuditLedger

        ledger = AuditLedger()
        mock_router = MagicMock()
        mock_router.dispatch_agent_remote = AsyncMock(side_effect=[
            {"success": True, "output": "Part A", "agent_id": "ag_d0",
             "trace_id": "tr_syn", "task_id": "tk_syn_0", "session_id": "s_syn"},
            {"success": True, "output": "Part B", "agent_id": "ag_d1",
             "trace_id": "tr_syn", "task_id": "tk_syn_1", "session_id": "s_syn"},
        ])

        coord = SwarmCoordinator(command_router=mock_router, audit_ledger=ledger)
        members = [self._make_member(0), self._make_member(1)]
        candidates = self._make_device_candidates(1)

        result = await coord.dispatch_team(
            members=members, task="Syn task",
            session_id="s_syn", trace_id="tr_syn", task_id="tk_syn",
            device_candidates=candidates,
        )

        assert "Part A" in result.synthesized
        assert "Part B" in result.synthesized


# ===========================================================================
# D) Audit event emission
# ===========================================================================

class TestAuditEventEmission:
    """Verify that SwarmCoordinator emits the required audit events."""

    def _make_member(self, idx: int = 0):
        from dataclasses import dataclass

        @dataclass
        class M:
            agent_id: str = f"ag_ae{idx}"
            agent_name: str = f"AuditAgent{idx}"
            provider: str = "openai"
            model: str = "gpt-4"
            role_in_team: str = "executor"
            template: str = "research"

        return M()

    @pytest.mark.asyncio
    async def test_agent_dispatched_event_emitted(self):
        from core.swarm_coordinator import SwarmCoordinator
        from core.control_plane.audit_ledger import AuditLedger, EventType
        from core.control_plane.smart_scheduler import DeviceScoreInput

        ledger = AuditLedger()
        mock_router = MagicMock()
        mock_router.dispatch_agent_remote = AsyncMock(return_value={
            "success": True, "output": "ok",
            "agent_id": "ag_ae0", "trace_id": "tr_ae",
            "task_id": "tk_ae_ag_ae0", "session_id": "s_ae",
        })

        coord = SwarmCoordinator(command_router=mock_router, audit_ledger=ledger)
        candidates = [DeviceScoreInput(device_id="dev_ae", ping_latency_ms=10.0)]

        await coord.dispatch_team(
            members=[self._make_member(0)],
            task="Audit test task",
            session_id="s_ae",
            trace_id="tr_ae",
            task_id="tk_ae",
            device_candidates=candidates,
        )

        dispatched = ledger.query(event_type=EventType.AGENT_DISPATCHED)
        assert len(dispatched) == 1
        assert dispatched[0].agent_id == "ag_ae0"
        assert dispatched[0].device_id == "dev_ae"
        assert dispatched[0].trace_id == "tr_ae"

    @pytest.mark.asyncio
    async def test_agent_executed_event_emitted(self):
        from core.swarm_coordinator import SwarmCoordinator
        from core.control_plane.audit_ledger import AuditLedger, EventType
        from core.control_plane.smart_scheduler import DeviceScoreInput

        ledger = AuditLedger()
        mock_router = MagicMock()
        mock_router.dispatch_agent_remote = AsyncMock(return_value={
            "success": True, "output": "ok",
            "agent_id": "ag_ae1", "trace_id": "tr_aex",
            "task_id": "tk_aex_ag_ae1", "session_id": "s_aex",
        })

        coord = SwarmCoordinator(command_router=mock_router, audit_ledger=ledger)
        candidates = [DeviceScoreInput(device_id="dev_aex", ping_latency_ms=5.0)]

        await coord.dispatch_team(
            members=[self._make_member(1)],
            task="Executed event test",
            session_id="s_aex",
            trace_id="tr_aex",
            task_id="tk_aex",
            device_candidates=candidates,
        )

        executed = ledger.query(event_type=EventType.AGENT_EXECUTED)
        assert len(executed) == 1
        assert executed[0].agent_id == "ag_ae1"

    @pytest.mark.asyncio
    async def test_agent_result_received_event_emitted(self):
        from core.swarm_coordinator import SwarmCoordinator
        from core.control_plane.audit_ledger import AuditLedger, EventType
        from core.control_plane.smart_scheduler import DeviceScoreInput

        ledger = AuditLedger()
        mock_router = MagicMock()
        mock_router.dispatch_agent_remote = AsyncMock(return_value={
            "success": True, "output": "some result",
            "agent_id": "ag_ae2", "trace_id": "tr_rr",
            "task_id": "tk_rr_ag_ae2", "session_id": "s_rr",
        })

        coord = SwarmCoordinator(command_router=mock_router, audit_ledger=ledger)
        candidates = [DeviceScoreInput(device_id="dev_rr", ping_latency_ms=5.0)]

        await coord.dispatch_team(
            members=[self._make_member(2)],
            task="Result received test",
            session_id="s_rr",
            trace_id="tr_rr",
            task_id="tk_rr",
            device_candidates=candidates,
        )

        received = ledger.query(event_type=EventType.AGENT_RESULT_RECEIVED)
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_all_three_events_emitted_per_member(self):
        """Each successful member dispatch emits DISPATCHED + EXECUTED + RESULT_RECEIVED."""
        from core.swarm_coordinator import SwarmCoordinator
        from core.control_plane.audit_ledger import AuditLedger, EventType
        from core.control_plane.smart_scheduler import DeviceScoreInput

        ledger = AuditLedger()
        mock_router = MagicMock()
        mock_router.dispatch_agent_remote = AsyncMock(return_value={
            "success": True, "output": "ok",
            "agent_id": "ag_ae3", "trace_id": "tr_all",
            "task_id": "tk_all_ag_ae3", "session_id": "s_all",
        })

        coord = SwarmCoordinator(command_router=mock_router, audit_ledger=ledger)
        candidates = [DeviceScoreInput(device_id="dev_all")]

        await coord.dispatch_team(
            members=[self._make_member(3)],
            task="All events test",
            session_id="s_all",
            trace_id="tr_all",
            task_id="tk_all",
            device_candidates=candidates,
        )

        assert len(ledger.query(event_type=EventType.AGENT_DISPATCHED)) == 1
        assert len(ledger.query(event_type=EventType.AGENT_EXECUTED)) == 1
        assert len(ledger.query(event_type=EventType.AGENT_RESULT_RECEIVED)) == 1

    @pytest.mark.asyncio
    async def test_two_members_emit_three_events_each(self):
        """Two members together emit 6 audit events (3 per member)."""
        from core.swarm_coordinator import SwarmCoordinator
        from core.control_plane.audit_ledger import AuditLedger, EventType
        from core.control_plane.smart_scheduler import DeviceScoreInput

        ledger = AuditLedger()
        mock_router = MagicMock()
        mock_router.dispatch_agent_remote = AsyncMock(return_value={
            "success": True, "output": "ok",
            "agent_id": "ag_ae", "trace_id": "tr_2m",
            "task_id": "tk_2m", "session_id": "s_2m",
        })

        coord = SwarmCoordinator(command_router=mock_router, audit_ledger=ledger)
        candidates = [DeviceScoreInput(device_id="dev_2m")]
        members = [self._make_member(4), self._make_member(5)]

        await coord.dispatch_team(
            members=members, task="Two-member test",
            session_id="s_2m", trace_id="tr_2m", task_id="tk_2m",
            device_candidates=candidates,
        )

        assert len(ledger.query(event_type=EventType.AGENT_DISPATCHED)) == 2
        assert len(ledger.query(event_type=EventType.AGENT_EXECUTED)) == 2
        assert len(ledger.query(event_type=EventType.AGENT_RESULT_RECEIVED)) == 2

    @pytest.mark.asyncio
    async def test_dispatch_failure_emits_task_failed(self):
        """When dispatch raises, TASK_FAILED is emitted instead of AGENT_EXECUTED."""
        from core.swarm_coordinator import SwarmCoordinator
        from core.control_plane.audit_ledger import AuditLedger, EventType
        from core.control_plane.smart_scheduler import DeviceScoreInput

        ledger = AuditLedger()
        mock_router = MagicMock()
        mock_router.dispatch_agent_remote = AsyncMock(
            side_effect=RuntimeError("network error")
        )

        coord = SwarmCoordinator(command_router=mock_router, audit_ledger=ledger)
        candidates = [DeviceScoreInput(device_id="dev_fail")]

        await coord.dispatch_team(
            members=[self._make_member(9)],
            task="Fail task",
            session_id="s_fail",
            trace_id="tr_fail",
            task_id="tk_fail",
            device_candidates=candidates,
        )

        assert len(ledger.query(event_type=EventType.TASK_FAILED)) == 1
        assert len(ledger.query(event_type=EventType.AGENT_EXECUTED)) == 0


# ===========================================================================
# E) Windows AIP client — _execute_agent_task handles SwarmAgentManifest fields
# ===========================================================================

class TestWindowsAIPClientSwarmManifestFields:
    """Verify _execute_agent_task extracts and propagates PR158 manifest context."""

    def test_extracts_system_prompt_from_context(self):
        from windows_client.windows_aip_client import _execute_agent_task

        payload = {
            "agent_id": "a_sys",
            "task_id": "tk_sys",
            "trace_id": "tr_sys",
            "session_id": "s_sys",
            "task": "Do work",
            "agent_template": "research",
            "context": {
                "system_prompt": "Custom system prompt",
                "tool_schemas": [{"name": "search"}],
                "memory_snapshot": {"mem": "data"},
                "manifest_id": "swm_abc123",
            },
        }

        with patch(
            "windows_client.windows_aip_client._get_manager",
            return_value=None,  # no autonomy manager
        ):
            result = _execute_agent_task(payload)

        assert result["success"] is True
        assert result["agent_id"] == "a_sys"
        assert result["trace_id"] == "tr_sys"
        assert result["manifest_id"] == "swm_abc123"

    def test_manifest_id_preserved_in_result(self):
        from windows_client.windows_aip_client import _execute_agent_task

        payload = {
            "agent_id": "a_mid",
            "task_id": "tk_mid",
            "trace_id": "tr_mid",
            "session_id": "s_mid",
            "task": "Task with manifest",
            "context": {"manifest_id": "swm_deadbeef"},
        }

        with patch("windows_client.windows_aip_client._get_manager", return_value=None):
            result = _execute_agent_task(payload)

        assert result.get("manifest_id") == "swm_deadbeef"

    def test_manifest_id_absent_when_not_provided(self):
        from windows_client.windows_aip_client import _execute_agent_task

        payload = {
            "agent_id": "a_noid",
            "task_id": "tk_noid",
            "trace_id": "tr_noid",
            "session_id": "s_noid",
            "task": "No manifest",
            "context": {},
        }

        with patch("windows_client.windows_aip_client._get_manager", return_value=None):
            result = _execute_agent_task(payload)

        assert "manifest_id" not in result

    def test_passes_enriched_request_to_autonomy_manager(self):
        from windows_client.windows_aip_client import _execute_agent_task

        mock_mgr = MagicMock()
        mock_mgr.execute_agent_task.return_value = {
            "success": True, "output": "manager result"
        }

        payload = {
            "agent_id": "a_mgr",
            "task_id": "tk_mgr",
            "trace_id": "tr_mgr",
            "session_id": "s_mgr",
            "task": "Test task",
            "agent_template": "analyst",
            "context": {
                "system_prompt": "Analyse carefully",
                "tool_schemas": [{"name": "analyse"}],
                "memory_snapshot": {"prev": "data"},
                "manifest_id": "swm_mgr_001",
            },
        }

        with patch("windows_client.windows_aip_client._get_manager", return_value=mock_mgr):
            result = _execute_agent_task(payload)

        mock_mgr.execute_agent_task.assert_called_once()
        call_arg = mock_mgr.execute_agent_task.call_args[0][0]
        assert call_arg["system_prompt"] == "Analyse carefully"
        assert call_arg["tool_schemas"] == [{"name": "analyse"}]
        assert call_arg["memory_snapshot"] == {"prev": "data"}
        assert call_arg["manifest_id"] == "swm_mgr_001"
        assert result["manifest_id"] == "swm_mgr_001"


# ===========================================================================
# F) Windows AIP client — _agent_execute_result_msg propagates manifest_id
# ===========================================================================

class TestAgentExecuteResultMsg:
    """Verify _agent_execute_result_msg propagates manifest_id (PR158)."""

    def _make_client(self):
        from windows_client.windows_aip_client import WindowsAIPClient
        return WindowsAIPClient(host="127.0.0.1", port=9999, device_id="test_win")

    def test_manifest_id_from_result(self):
        client = self._make_client()
        result = {
            "success": True,
            "output": "done",
            "agent_id": "a1",
            "task_id": "tk1",
            "trace_id": "tr1",
            "session_id": "s1",
            "manifest_id": "swm_fromresult",
        }
        msg = client._agent_execute_result_msg("cmd1", {}, result)
        assert msg.get("manifest_id") == "swm_fromresult"

    def test_manifest_id_from_context(self):
        client = self._make_client()
        agent_payload = {
            "agent_id": "a2",
            "context": {"manifest_id": "swm_fromctx"},
        }
        result = {
            "success": True,
            "agent_id": "a2",
            "task_id": "tk2",
            "trace_id": "tr2",
            "session_id": "s2",
        }
        msg = client._agent_execute_result_msg("cmd2", agent_payload, result)
        assert msg.get("manifest_id") == "swm_fromctx"

    def test_no_manifest_id_when_absent(self):
        client = self._make_client()
        result = {
            "success": True,
            "agent_id": "a3",
            "task_id": "tk3",
            "trace_id": "tr3",
            "session_id": "s3",
        }
        msg = client._agent_execute_result_msg("cmd3", {}, result)
        assert "manifest_id" not in msg


# ===========================================================================
# G) No-device / router-unavailable failure paths
# ===========================================================================

class TestSwarmCoordinatorFailurePaths:
    """Ensure graceful failure when no device or no router is available."""

    def _make_member(self, idx: int = 0):
        from dataclasses import dataclass

        @dataclass
        class M:
            agent_id: str = f"ag_fp{idx}"
            agent_name: str = f"FPAgent{idx}"
            provider: str = "openai"
            model: str = "gpt-4"
            role_in_team: str = "executor"
            template: str = "research"

        return M()

    @pytest.mark.asyncio
    async def test_router_unavailable_returns_failure(self):
        """When CommandRouter is unavailable the dispatch should fail gracefully."""
        from core.swarm_coordinator import SwarmCoordinator
        from core.control_plane.audit_ledger import AuditLedger, EventType
        from core.control_plane.smart_scheduler import DeviceScoreInput

        ledger = AuditLedger()
        # Coordinator with no pre-set router; patch the lazy-getter too
        coord = SwarmCoordinator(audit_ledger=ledger)

        candidates = [DeviceScoreInput(device_id="dev_ru")]
        with patch.object(coord, "_get_router", return_value=None):
            result = await coord.dispatch_team(
                members=[self._make_member(0)],
                task="Router unavailable test",
                session_id="s_ru",
                trace_id="tr_ru",
                task_id="tk_ru",
                device_candidates=candidates,
            )

        assert not result.member_results[0].success
        failed = ledger.query(event_type=EventType.TASK_FAILED)
        assert len(failed) >= 1

    @pytest.mark.asyncio
    async def test_empty_members_list_produces_empty_result(self):
        """Empty member list returns an empty TeamResult."""
        from core.swarm_coordinator import SwarmCoordinator
        from core.control_plane.audit_ledger import AuditLedger

        ledger = AuditLedger()
        coord = SwarmCoordinator(audit_ledger=ledger)

        result = await coord.dispatch_team(
            members=[],
            task="Empty test",
            session_id="s_em",
            trace_id="tr_em",
            task_id="tk_em",
        )

        assert result.member_results == []
        assert result.total_latency_ms >= 0.0


# ===========================================================================
# H) AGENT_EXECUTED event type in audit_ledger
# ===========================================================================

class TestAgentExecutedEventType:
    """Validate that AGENT_EXECUTED is present in EventType and usable."""

    def test_agent_executed_in_event_type_enum(self):
        from core.control_plane.audit_ledger import EventType

        assert hasattr(EventType, "AGENT_EXECUTED")
        assert EventType.AGENT_EXECUTED == "agent_executed"

    def test_agent_executed_can_be_appended_to_ledger(self):
        from core.control_plane.audit_ledger import AuditLedger, EventType

        ledger = AuditLedger()
        eid = ledger.append(
            EventType.AGENT_EXECUTED,
            source="test",
            agent_id="a_ent",
            trace_id="tr_ent",
            payload={"latency_ms": 42.0},
        )

        events = ledger.query(event_type=EventType.AGENT_EXECUTED)
        assert len(events) == 1
        assert events[0].event_id == eid
        assert events[0].agent_id == "a_ent"

    def test_swarm_manifest_exported_from_control_plane(self):
        from core.control_plane import SwarmAgentManifest
        assert SwarmAgentManifest is not None
