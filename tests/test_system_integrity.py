"""
系统完整性测试 — 验证所有修复都已生效
"""

import os
import sys
import pytest

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Phase 1: Import crash protection ────────────────────

class TestPhase1ImportProtection:
    """All L4 modules should be importable without crashing."""

    def test_galaxy_main_loop_importable(self):
        import galaxy_main_loop_l4
        assert hasattr(galaxy_main_loop_l4, "GalaxyMainLoopL4")

    def test_module_availability_flags_exist(self):
        import galaxy_main_loop_l4 as g
        flags = [
            "_PERCEPTION_AVAILABLE",
            "_GOAL_DECOMPOSER_AVAILABLE",
            "_PLANNER_AVAILABLE",
            "_WORLD_MODEL_AVAILABLE",
            "_METACOGNITION_AVAILABLE",
            "_CODER_AVAILABLE",
            "_EXECUTOR_AVAILABLE",
            "_MONITOR_AVAILABLE",
            "_SAFETY_AVAILABLE",
            "_LEARNING_AVAILABLE",
        ]
        for flag in flags:
            assert hasattr(g, flag), f"Missing availability flag: {flag}"

    def test_module_status_method(self):
        from galaxy_main_loop_l4 import GalaxyMainLoopL4
        loop = GalaxyMainLoopL4()
        status = loop._module_status()
        assert isinstance(status, dict)
        assert len(status) >= 10

    def test_placeholder_api_keys_not_loaded(self):
        from core.unified_config import UnifiedConfig
        assert UnifiedConfig._is_placeholder("sk-YOUR_OPENAI_KEY_HERE") is True
        assert UnifiedConfig._is_placeholder("sk-real-key-abc123") is False
        assert UnifiedConfig._is_placeholder(42) is False


# ── Phase 2: Device subsystem fixes ────────────────────

class TestPhase2DeviceSubsystem:
    """Device subsystem fixes are in place."""

    def test_pyautogui_typewrite_used(self):
        """Verify pyautogui.write was replaced with typewrite."""
        import inspect
        from core.device_agent_manager import WindowsDeviceAgent
        source = inspect.getsource(WindowsDeviceAgent._execute_with_fallback)
        assert "typewrite" in source
        assert "pyautogui.write(" not in source

    def test_node08_fetch_uses_httpx_client(self):
        # Node_08_Fetch was refactored from aiohttp mock to httpx.AsyncClient.
        # Verify the current implementation uses httpx.AsyncClient.request().
        source_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "nodes", "Node_08_Fetch", "main.py",
        )
        with open(source_path) as f:
            content = f.read()
        assert "httpx" in content
        assert "AsyncClient" in content or "httpx.AsyncClient" in content

    def test_device_router_uses_asyncio_event(self):
        import inspect
        from galaxy_gateway.device_router import DeviceRouter
        source = inspect.getsource(DeviceRouter.dispatch_task)
        assert "asyncio.Event" in source or "asyncio.wait_for" in source
        assert "for _ in range(30)" not in source


# ── Phase 3: Agent execution + skills ────────────────────

class TestPhase3AgentSkills:
    """Agent factory reports simulated status; skills have handlers."""

    def test_skill_loader_available(self):
        from core.skill_loader import skill_loader
        # skill_loader 单例应可实例化且有 list_skills 方法
        skills = skill_loader.list_skills()
        assert isinstance(skills, list), "list_skills() should return a list"

    def test_fallback_action_not_none(self):
        from enhancements.reasoning.autonomous_planner import (
            AutonomousPlanner,
            Action,
        )
        planner = AutonomousPlanner()
        action = Action(
            id="test_action",
            subtask_id="st1",
            node_id="Node_01",
            device_id=None,
            command="test_cmd",
            parameters={},
            expected_duration=60,
            fallback_actions=[],
        )
        fallback = planner._generate_fallback_action(action)
        assert fallback is not None
        assert fallback.parameters.get("retry") is True


# ── Phase 4: Cross-device coordination ────────────────────

class TestPhase4CrossDevice:
    """Private method renamed; hardcoded URL replaced."""

    def test_dispatch_task_is_public(self):
        from galaxy_gateway.device_router import DeviceRouter
        assert hasattr(DeviceRouter, "dispatch_task")
        assert not hasattr(DeviceRouter, "_dispatch_single_device_task")

    def test_cross_device_coordinator_uses_public_method(self):
        source_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "galaxy_gateway", "cross_device_coordinator.py",
        )
        with open(source_path) as f:
            content = f.read()
        assert "_dispatch_single_device_task" not in content

    def test_node71_uses_registry_lookup(self):
        source_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "nodes", "Node_71_MultiDeviceCoordination", "main.py",
        )
        with open(source_path) as f:
            content = f.read()
        assert "_resolve_node_url" in content


# ── Phase 5: Reasoning + learning fakes ────────────────────

class TestPhase5ReasoningLearning:
    """Goal decomposer uses LLM path; experiment is real; confidence normalized."""

    def test_goal_decomposer_has_llm_path(self):
        import inspect
        from enhancements.reasoning.goal_decomposer import GoalDecomposer
        source = inspect.getsource(GoalDecomposer._generate_subtasks)
        assert "self.llm_client" in source
        assert "_generate_subtasks_with_llm" in source

    def test_experiment_stage_no_fake_sleep(self):
        source_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "enhancements", "learning", "autonomous_learning_engine.py",
        )
        with open(source_path) as f:
            content = f.read()
        # The fake "await asyncio.sleep(0.1)" pattern in _experiment_stage should be gone
        lines = content.split("\n")
        in_experiment = False
        for line in lines:
            if "_experiment_stage" in line and "async def" in line:
                in_experiment = True
            elif in_experiment and "async def " in line and "_experiment_stage" not in line:
                in_experiment = False
            if in_experiment and "asyncio.sleep(0.1)" in line:
                pytest.fail("Fake asyncio.sleep(0.1) still present in _experiment_stage")

    def test_confidence_formula_normalized(self):
        source_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "core", "ai_intent.py",
        )
        with open(source_path) as f:
            content = f.read()
        assert "min(0.3 + best_score * 0.2, 0.9)" not in content


# ── Phase 6: Security + configurability ────────────────────

class TestPhase6SecurityConfig:
    """STUN ID random; safety thresholds configurable; digital twin logs."""

    def test_stun_transaction_id_random(self):
        source_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "galaxy_gateway", "p2p_connector.py",
        )
        with open(source_path) as f:
            content = f.read()
        assert "os.urandom(12)" in content
        assert "b'\\x00' * 12" not in content

    def test_safety_thresholds_configurable(self):
        from enhancements.safety.safety_manager import SafetyManager, SafetyThresholds
        custom = SafetyThresholds(max_bed_temperature=100.0, max_nozzle_temperature=250.0)
        sm = SafetyManager(thresholds=custom)
        assert sm.thresholds.max_bed_temperature == 100.0
        assert sm.thresholds.max_nozzle_temperature == 250.0

    def test_digital_twin_logs_warning(self):
        import inspect
        from core.digital_twin_engine import DigitalTwin
        source = inspect.getsource(DigitalTwin._sync_from_physical)
        assert "logger.warning" in source

    def test_llm_router_weighted_classification(self):
        source_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "core", "multi_llm_router.py",
        )
        with open(source_path) as f:
            content = f.read()
        assert "weighted_patterns" in content


# ── Phase 7: Architecture improvements ────────────────────

class TestPhase7Architecture:
    """Result aggregation; A/B experiment dataclass."""

    def test_aggregate_results(self):
        from galaxy_gateway.device_router import DeviceRouter
        results = [
            {"success": True, "device_id": "dev1"},
            {"success": False, "device_id": "dev2", "error": "timeout"},
            {"success": True, "device_id": "dev3"},
        ]
        agg = DeviceRouter.aggregate_results(results)
        assert agg["total"] == 3
        assert agg["success_count"] == 2
        assert agg["failure_count"] == 1
        assert not agg["overall_success"]
        assert "dev1" in agg["results_by_device"]

    def test_ab_experiment_dataclass(self):
        pytest.importorskip("numpy", reason="numpy required for learning engine")
        from enhancements.learning.autonomous_learning_engine import ABExperiment
        exp = ABExperiment(
            id="test_ab",
            hypothesis="Treatment is better",
            control_group=[{"success": True}, {"success": False}, {"success": True}],
            treatment_group=[{"success": True}, {"success": True}, {"success": True}],
        )
        result = exp.run()
        assert result["winner"] == "treatment"
        assert exp.completed is True
        assert exp.treatment_metric > exp.control_metric
