#!/usr/bin/env python3
"""
Tests for the three autonomous loops added to UFO Galaxy:

Loop 1: Self-healing -> code fix (node_112_self_healing)
Loop 2: Learning -> planner strategy (galaxy_main_loop_l4 + autonomous_planner)
Loop 3: Capability gap -> auto expand (autonomous_coder._deploy_as_node)
"""

import sys
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Loop 1: Self-healing -> code fix
# ---------------------------------------------------------------------------

class TestSelfHealingCodeFix:
    """Loop 1: FixAction.CODE_FIX enum, _determine_action heuristic, _code_fix dispatch."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from nodes.node_112_self_healing.main import (
            FixAction, AutoFixer, DiagnosisResult, IssueType, HealthStatus,
            _CODE_FIX_KEYWORDS,
        )
        self.FixAction = FixAction
        self.AutoFixer = AutoFixer
        self.DiagnosisResult = DiagnosisResult
        self.IssueType = IssueType
        self.HealthStatus = HealthStatus
        self.CODE_FIX_KEYWORDS = _CODE_FIX_KEYWORDS

    def _diagnosis(self, issue_type=None, recommendation="继续监控"):
        return self.DiagnosisResult(
            issue_type=issue_type or self.IssueType.UNKNOWN,
            severity=self.HealthStatus.WARNING,
            description="测试诊断",
            affected_components=["test"],
            recommendation=recommendation,
        )

    def test_code_fix_enum_exists(self):
        """FixAction.CODE_FIX must be a member of the enum."""
        assert hasattr(self.FixAction, "CODE_FIX")
        assert self.FixAction.CODE_FIX.value == "code_fix"

    def test_code_fix_keywords_defined(self):
        """_CODE_FIX_KEYWORDS must be a non-empty tuple of strings."""
        assert isinstance(self.CODE_FIX_KEYWORDS, tuple)
        assert len(self.CODE_FIX_KEYWORDS) > 0
        for kw in self.CODE_FIX_KEYWORDS:
            assert isinstance(kw, str)

    def test_determine_action_returns_code_fix_for_keyword(self):
        """_determine_action returns CODE_FIX when recommendation contains a keyword."""
        fixer = self.AutoFixer()
        # Use a keyword from _CODE_FIX_KEYWORDS
        kw = self.CODE_FIX_KEYWORDS[0]
        diag = self._diagnosis(recommendation=f"需要{kw}处理")
        assert fixer._determine_action(diag) == self.FixAction.CODE_FIX

    def test_determine_action_no_false_positive(self):
        """_determine_action must NOT return CODE_FIX for generic recommendations."""
        fixer = self.AutoFixer()
        diag = self._diagnosis(recommendation="需要人工介入")
        assert fixer._determine_action(diag) == self.FixAction.NONE

    def test_determine_action_standard_issues_unchanged(self):
        """Standard issue types must still map to their original actions."""
        fixer = self.AutoFixer()
        cases = {
            self.IssueType.HIGH_CPU: self.FixAction.RESTART,
            self.IssueType.HIGH_MEMORY: self.FixAction.RESTART,
            self.IssueType.DISK_FULL: self.FixAction.CLEANUP,
            self.IssueType.SERVICE_DOWN: self.FixAction.RESTART,
            self.IssueType.NETWORK_ERROR: self.FixAction.RESET,
        }
        for issue_type, expected_action in cases.items():
            diag = self._diagnosis(issue_type=issue_type)
            assert fixer._determine_action(diag) == expected_action, (
                f"Expected {expected_action} for {issue_type}"
            )

    def test_fix_dispatches_to_code_fix(self):
        """AutoFixer.fix must invoke _code_fix when action is CODE_FIX."""
        fixer = self.AutoFixer()
        kw = self.CODE_FIX_KEYWORDS[0]
        diag = self._diagnosis(recommendation=f"{kw} fix needed")

        from nodes.node_112_self_healing.main import FixResult
        with patch.object(fixer, "_code_fix") as stub:
            stub.return_value = FixResult(
                action=self.FixAction.CODE_FIX,
                success=True,
                message="stub",
                timestamp="t",
            )
            result = fixer.fix(diag)
            stub.assert_called_once()
            assert result.action == self.FixAction.CODE_FIX


# ---------------------------------------------------------------------------
# Loop 2: Learning -> planner strategy
# ---------------------------------------------------------------------------

class TestLearningPlannerFeedback:
    """Loop 2: AutonomousPlanner.update_decision_weights and its call from _perform_optimization."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from enhancements.reasoning.autonomous_planner import (
            AutonomousPlanner, Resource, ResourceType,
        )
        self.AutonomousPlanner = AutonomousPlanner
        self.Resource = Resource
        self.ResourceType = ResourceType

    def _planner_with_resource(self, availability: float = 0.5):
        r = self.Resource(
            id="r1",
            type=self.ResourceType.NODE,
            name="TestNode",
            capabilities=[],
            availability=availability,
            metadata={},
        )
        return self.AutonomousPlanner(available_resources=[r])

    def test_update_decision_weights_method_exists(self):
        """AutonomousPlanner must expose update_decision_weights."""
        planner = self._planner_with_resource()
        assert callable(getattr(planner, "update_decision_weights", None))

    def test_high_success_rate_increases_availability(self):
        """High success rate (>0.8) should increase resource availability."""
        planner = self._planner_with_resource(availability=0.5)
        planner.update_decision_weights({"average_success_rate": 0.9})
        assert planner.available_resources[0].availability > 0.5

    def test_low_success_rate_decreases_availability(self):
        """Low success rate (<0.5) should decrease resource availability."""
        planner = self._planner_with_resource(availability=0.5)
        planner.update_decision_weights({"average_success_rate": 0.3})
        assert planner.available_resources[0].availability < 0.5

    def test_availability_bounded_above(self):
        """Availability must never exceed 1.0."""
        planner = self._planner_with_resource(availability=1.0)
        planner.update_decision_weights({"average_success_rate": 1.0})
        assert planner.available_resources[0].availability <= 1.0

    def test_availability_bounded_below(self):
        """Availability must not drop below 0.1."""
        planner = self._planner_with_resource(availability=0.1)
        planner.update_decision_weights({"average_success_rate": 0.0})
        assert planner.available_resources[0].availability >= 0.1

    def test_empty_metrics_safe(self):
        """update_decision_weights must not raise on empty/missing metrics."""
        planner = self._planner_with_resource()
        planner.update_decision_weights({})  # missing average_success_rate

    def test_galaxy_l4_calls_update_decision_weights(self):
        """_perform_optimization in galaxy_main_loop_l4 must call update_decision_weights."""
        import importlib.util
        import asyncio

        spec = importlib.util.spec_from_file_location(
            "gml4", str(PROJECT_ROOT / "galaxy_main_loop_l4.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        loop = mod.GalaxyMainLoopL4()

        # Replace planner and optimizer with mocks so no real IO happens.
        mock_optimizer = MagicMock()
        # Return a non-empty insight list so the early-return is not triggered.
        mock_optimizer.analyze_performance.return_value = [{"type": "test"}]
        mock_optimizer.generate_optimization_plan.return_value = []
        mock_optimizer.performance_metrics = {"average_success_rate": 0.85}
        loop.learning_optimizer = mock_optimizer

        mock_planner = MagicMock()
        loop.planner = mock_planner

        asyncio.run(loop._perform_optimization())

        mock_planner.update_decision_weights.assert_called_once_with(
            mock_optimizer.performance_metrics
        )


# ---------------------------------------------------------------------------
# Loop 3: Capability gap -> auto expand
# ---------------------------------------------------------------------------

class TestAutoExpandDeployAsNode:
    """Loop 3: _deploy_as_node registers node in NodeFactory and capability_manager."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from enhancements.reasoning.autonomous_coder import AutonomousCoder
        self.AutonomousCoder = AutonomousCoder

    def test_deploy_as_node_calls_node_factory_register(self, tmp_path):
        """_deploy_as_node must call NodeFactory.register_node when available."""
        from enhancements.reasoning.autonomous_coder import CodingTask

        coder = self.AutonomousCoder()
        task = CodingTask(
            requirement="print('hello')",
            language="python",
            target_type="node",
            constraints=[],
            expected_output=None,
            context_code=None,
        )
        mock_factory = MagicMock()
        nodes_dir = tmp_path / "nodes"
        nodes_dir.mkdir()
        orig_join = os.path.join

        def _join(*a):
            # Redirect the top-level nodes directory to tmp_path
            if len(a) == 4 and a[-1] == "nodes":
                return str(nodes_dir)
            return orig_join(*a)

        with patch(
            "nodes.node_118_node_factory.main.get_node_factory",
            return_value=mock_factory,
        ), patch(
            "core.capability_manager.get_capability_manager",
            side_effect=Exception("cap mgr unavailable"),
        ), patch("os.path.join", side_effect=_join):
            coder._deploy_as_node("print('hello')", task)

        mock_factory.register_node.assert_called()

    def test_deploy_as_node_node_factory_error_is_non_fatal(self, tmp_path):
        """NodeFactory failure must be swallowed; the method must not propagate it."""
        from enhancements.reasoning.autonomous_coder import CodingTask

        coder = self.AutonomousCoder()
        task = CodingTask(
            requirement="test",
            language="python",
            target_type="node",
            constraints=[],
            expected_output=None,
            context_code=None,
        )

        nodes_dir = tmp_path / "nodes"
        nodes_dir.mkdir()

        with patch(
            "nodes.node_118_node_factory.main.get_node_factory",
            side_effect=Exception("factory error"),
        ), patch(
            "core.capability_manager.get_capability_manager",
            side_effect=Exception("cap mgr error"),
        ):
            # Use real filesystem but redirect nodes dir to tmp_path
            orig_join = os.path.join

            def _join(*a):
                if len(a) == 4 and a[-1] == "nodes":
                    return str(nodes_dir)
                return orig_join(*a)

            with patch("os.path.join", side_effect=_join):
                # Should not raise even though both registries fail
                node_name, main_file = coder._deploy_as_node("print('x')", task)
            assert node_name.startswith("Node_")

    def test_deploy_as_node_calls_capability_manager_register(self, tmp_path):
        """_deploy_as_node must call capability_manager.register_capability when available."""
        from enhancements.reasoning.autonomous_coder import CodingTask
        import asyncio

        coder = self.AutonomousCoder()
        task = CodingTask(
            requirement="print('cap')",
            language="python",
            target_type="node",
            constraints=[],
            expected_output=None,
            context_code=None,
        )

        mock_cap_mgr = MagicMock()

        async def _fake_register(**kwargs):
            return True

        mock_cap_mgr.register_capability = MagicMock(
            return_value=_fake_register()
        )

        nodes_dir = tmp_path / "nodes"
        nodes_dir.mkdir()
        orig_join = os.path.join

        def _join(*a):
            if len(a) == 4 and a[-1] == "nodes":
                return str(nodes_dir)
            return orig_join(*a)

        with patch(
            "nodes.node_118_node_factory.main.get_node_factory",
            side_effect=Exception("factory unavailable"),
        ), patch(
            "core.capability_manager.get_capability_manager",
            return_value=mock_cap_mgr,
        ), patch("os.path.join", side_effect=_join):
            coder._deploy_as_node("print('cap')", task)

        mock_cap_mgr.register_capability.assert_called()

    def test_deploy_as_node_signature(self):
        """_deploy_as_node must accept (code, task) parameters."""
        import inspect
        coder = self.AutonomousCoder()
        sig = inspect.signature(coder._deploy_as_node)
        params = list(sig.parameters.keys())
        assert "code" in params
        assert "task" in params


# ---------------------------------------------------------------------------
# Loop 1 supplemental: SelfHealingEngine phase logging & verification
# ---------------------------------------------------------------------------

class TestSelfHealingPhaseLogging:
    """Loop 1: run_once() must emit phase-tagged log messages and run a verification step."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from nodes.node_112_self_healing.main import (
            SelfHealingEngine, HealthMetrics, HealthStatus, IssueType,
            DiagnosisResult, FixResult, FixAction, IncidentReport,
        )
        self.SelfHealingEngine = SelfHealingEngine
        self.HealthMetrics = HealthMetrics
        self.HealthStatus = HealthStatus
        self.IssueType = IssueType
        self.DiagnosisResult = DiagnosisResult
        self.FixResult = FixResult
        self.FixAction = FixAction
        self.IncidentReport = IncidentReport

    def _make_metrics(self, cpu=50.0, mem=50.0, disk=50.0, net=True):
        return self.HealthMetrics(
            cpu_percent=cpu, memory_percent=mem, disk_percent=disk,
            network_ok=net, timestamp="2026-01-01T00:00:00"
        )

    def test_run_once_emits_detection_log(self, caplog):
        """run_once must log [DETECTION] when anomalies are found."""
        import logging
        engine = self.SelfHealingEngine({"report_dir": "/tmp"})
        bad_metrics = self._make_metrics(cpu=95.0)  # triggers CRITICAL
        fix_result = self.FixResult(
            action=self.FixAction.RESTART, success=True,
            message="ok", timestamp="t"
        )
        diag = self.DiagnosisResult(
            issue_type=self.IssueType.HIGH_CPU,
            severity=self.HealthStatus.CRITICAL,
            description="cpu high",
            affected_components=["cpu"],
            recommendation="restart"
        )
        with patch.object(engine.detector, "collect_metrics", return_value=bad_metrics), \
             patch.object(engine.diagnoser, "diagnose", return_value=diag), \
             patch.object(engine.fixer, "fix", return_value=fix_result), \
             patch.object(engine.reporter, "generate_report") as mock_report, \
             caplog.at_level(logging.INFO, logger="SelfHealing"):
            mock_report.return_value = MagicMock()
            engine.run_once()
        assert any("[DETECTION]" in r.message for r in caplog.records)

    def test_run_once_emits_verification_log(self, caplog):
        """run_once must log [VERIFICATION] after attempting a fix."""
        import logging
        engine = self.SelfHealingEngine({"report_dir": "/tmp"})
        bad_metrics = self._make_metrics(mem=95.0)
        healthy_metrics = self._make_metrics()
        fix_result = self.FixResult(
            action=self.FixAction.RESTART, success=True,
            message="ok", timestamp="t"
        )
        diag = self.DiagnosisResult(
            issue_type=self.IssueType.HIGH_MEMORY,
            severity=self.HealthStatus.CRITICAL,
            description="mem high",
            affected_components=["memory"],
            recommendation="restart"
        )
        call_count = [0]

        def _metrics():
            call_count[0] += 1
            return bad_metrics if call_count[0] == 1 else healthy_metrics

        with patch.object(engine.detector, "collect_metrics", side_effect=_metrics), \
             patch.object(engine.diagnoser, "diagnose", return_value=diag), \
             patch.object(engine.fixer, "fix", return_value=fix_result), \
             patch.object(engine.reporter, "generate_report") as mock_report, \
             caplog.at_level(logging.INFO, logger="SelfHealing"):
            mock_report.return_value = MagicMock()
            engine.run_once()
        assert any("[VERIFICATION]" in r.message for r in caplog.records)
        assert any("restored" in r.message for r in caplog.records)

    def test_run_once_code_fix_logs_sandbox_and_commit(self, caplog):
        """When CODE_FIX succeeds, run_once must log [SANDBOX_TEST] and [COMMIT]."""
        import logging
        engine = self.SelfHealingEngine({"report_dir": "/tmp"})
        bad_metrics = self._make_metrics(cpu=95.0)
        code_fix_result = self.FixResult(
            action=self.FixAction.CODE_FIX, success=True,
            message="fixed", timestamp="t"
        )
        diag = self.DiagnosisResult(
            issue_type=self.IssueType.HIGH_CPU,
            severity=self.HealthStatus.CRITICAL,
            description="cpu high",
            affected_components=["cpu"],
            recommendation="code fix needed"
        )
        with patch.object(engine.detector, "collect_metrics", return_value=bad_metrics), \
             patch.object(engine.diagnoser, "diagnose", return_value=diag), \
             patch.object(engine.fixer, "fix", return_value=code_fix_result), \
             patch.object(engine.reporter, "generate_report") as mock_report, \
             caplog.at_level(logging.INFO, logger="SelfHealing"):
            mock_report.return_value = MagicMock()
            engine.run_once()
        messages = [r.message for r in caplog.records]
        assert any("[SANDBOX_TEST]" in m for m in messages)
        assert any("[COMMIT]" in m for m in messages)


# ---------------------------------------------------------------------------
# Loop 2 supplemental: forced weight update in _learn_from_execution
# ---------------------------------------------------------------------------

class TestForcedDecisionWeightUpdate:
    """Loop 2: _learn_from_execution must call update_decision_weights even without
    the full learning engine (e.g., when numpy is unavailable)."""

    def test_learn_from_execution_updates_weights_without_learning_engine(self):
        """Even when learning_optimizer is None, planner.update_decision_weights is called."""
        import importlib.util
        import asyncio

        spec = importlib.util.spec_from_file_location(
            "gml4_forced", str(PROJECT_ROOT / "galaxy_main_loop_l4.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        loop_obj = mod.GalaxyMainLoopL4()
        # Force learning engine to None to simulate numpy unavailable
        loop_obj.learning_optimizer = None

        mock_planner = MagicMock()
        loop_obj.planner = mock_planner

        execution_result = {
            "success": True,
            "summary": {
                "goal": "test",
                "total_duration": 1.0,
                "total_actions": 2,
                "success_rate": 0.9,
            },
        }

        asyncio.run(loop_obj._learn_from_execution(execution_result))

        mock_planner.update_decision_weights.assert_called_once()
        call_kwargs = mock_planner.update_decision_weights.call_args[0][0]
        assert "average_success_rate" in call_kwargs

    def test_forced_weight_update_affects_routing(self):
        """After _learn_from_execution, resource availability changes based on success rate."""
        import importlib.util
        import asyncio
        from enhancements.reasoning.autonomous_planner import (
            AutonomousPlanner, Resource, ResourceType,
        )

        spec = importlib.util.spec_from_file_location(
            "gml4_routing", str(PROJECT_ROOT / "galaxy_main_loop_l4.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        loop_obj = mod.GalaxyMainLoopL4()
        loop_obj.learning_optimizer = None

        resource = Resource(
            id="r1", type=ResourceType.NODE, name="TestNode",
            capabilities=[], availability=0.5, metadata={}
        )
        real_planner = AutonomousPlanner(available_resources=[resource])
        loop_obj.planner = real_planner

        # Low success rate → availability should decrease
        execution_result = {
            "success": False,
            "summary": {
                "goal": "test", "total_duration": 1.0,
                "total_actions": 1, "success_rate": 0.1,
            },
        }
        asyncio.run(loop_obj._learn_from_execution(execution_result))
        assert real_planner.available_resources[0].availability < 0.5


# ---------------------------------------------------------------------------
# Loop 1 supplemental: sandbox + commit gating for CODE_FIX
# ---------------------------------------------------------------------------

class TestCodeFixSandboxGating:
    """Loop 1: verify that the commit step is gated on sandbox success and that
    apply_code_fix() writes a real file to disk when auto_commit is enabled."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from nodes.node_112_self_healing.main import (
            SelfHealingEngine, AutoFixer, FixResult, FixAction,
            HealthMetrics, IssueType, HealthStatus, DiagnosisResult,
        )
        self.SelfHealingEngine = SelfHealingEngine
        self.AutoFixer = AutoFixer
        self.FixResult = FixResult
        self.FixAction = FixAction
        self.HealthMetrics = HealthMetrics
        self.IssueType = IssueType
        self.HealthStatus = HealthStatus
        self.DiagnosisResult = DiagnosisResult

    def _make_metrics(self, cpu=95.0):
        return self.HealthMetrics(
            cpu_percent=cpu, memory_percent=50.0, disk_percent=50.0,
            network_ok=True, timestamp="2026-01-01T00:00:00"
        )

    def _make_diag(self):
        return self.DiagnosisResult(
            issue_type=self.IssueType.HIGH_CPU,
            severity=self.HealthStatus.CRITICAL,
            description="cpu high",
            affected_components=["cpu"],
            recommendation="code fix needed",
        )

    def test_apply_code_fix_writes_file(self, tmp_path):
        """apply_code_fix() must write the last coding result's code to disk."""
        fixer = self.AutoFixer()
        # Simulate a successful _code_fix result by setting _last_coding_result
        from types import SimpleNamespace
        fixer._last_coding_result = SimpleNamespace(code="print('hello')")
        applied = fixer.apply_code_fix(target_dir=str(tmp_path))
        assert applied != ""
        assert Path(applied).exists()
        assert Path(applied).read_text(encoding="utf-8") == "print('hello')"

    def test_apply_code_fix_returns_empty_when_no_result(self, tmp_path):
        """apply_code_fix() returns empty string when no coding result is stored."""
        fixer = self.AutoFixer()
        applied = fixer.apply_code_fix(target_dir=str(tmp_path))
        assert applied == ""

    def test_auto_commit_calls_apply_on_success(self, tmp_path):
        """When auto_commit=True and CODE_FIX succeeds, apply_code_fix is invoked."""
        engine = self.SelfHealingEngine({
            "report_dir": str(tmp_path),
            "auto_commit": True,
            "applied_fixes_dir": str(tmp_path / "fixes"),
        })
        code_fix_result = self.FixResult(
            action=self.FixAction.CODE_FIX, success=True,
            message="fixed", timestamp="t"
        )
        with patch.object(engine.detector, "collect_metrics",
                          return_value=self._make_metrics()), \
             patch.object(engine.diagnoser, "diagnose",
                          return_value=self._make_diag()), \
             patch.object(engine.fixer, "fix", return_value=code_fix_result), \
             patch.object(engine.reporter, "generate_report",
                          return_value=MagicMock()), \
             patch.object(engine.fixer, "apply_code_fix",
                          return_value=str(tmp_path / "fixes" / "fix.py")) as mock_apply:
            engine.run_once()
        mock_apply.assert_called_once()

    def test_no_commit_when_fix_fails(self, tmp_path):
        """When CODE_FIX sandbox fails, apply_code_fix must NOT be called."""
        engine = self.SelfHealingEngine({
            "report_dir": str(tmp_path),
            "auto_commit": True,
            "applied_fixes_dir": str(tmp_path / "fixes"),
        })
        failed_result = self.FixResult(
            action=self.FixAction.CODE_FIX, success=False,
            message="sandbox failed", timestamp="t"
        )
        with patch.object(engine.detector, "collect_metrics",
                          return_value=self._make_metrics()), \
             patch.object(engine.diagnoser, "diagnose",
                          return_value=self._make_diag()), \
             patch.object(engine.fixer, "fix", return_value=failed_result), \
             patch.object(engine.reporter, "generate_report",
                          return_value=MagicMock()), \
             patch.object(engine.fixer, "apply_code_fix") as mock_apply:
            engine.run_once()
        mock_apply.assert_not_called()

    def test_no_commit_without_auto_commit_flag(self, tmp_path):
        """When auto_commit=False (default), apply_code_fix must NOT be called
        even when the sandbox passes."""
        engine = self.SelfHealingEngine({"report_dir": str(tmp_path)})
        assert engine.auto_commit is False
        code_fix_result = self.FixResult(
            action=self.FixAction.CODE_FIX, success=True,
            message="fixed", timestamp="t"
        )
        with patch.object(engine.detector, "collect_metrics",
                          return_value=self._make_metrics()), \
             patch.object(engine.diagnoser, "diagnose",
                          return_value=self._make_diag()), \
             patch.object(engine.fixer, "fix", return_value=code_fix_result), \
             patch.object(engine.reporter, "generate_report",
                          return_value=MagicMock()), \
             patch.object(engine.fixer, "apply_code_fix") as mock_apply:
            engine.run_once()
        mock_apply.assert_not_called()
