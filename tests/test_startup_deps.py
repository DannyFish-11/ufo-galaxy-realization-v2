"""启动依赖图验证 — 确保依赖声明一致且无循环"""

import pytest

from core.startup import _SUBSYSTEM_DEPS, _check_circular_deps


class TestDependencyGraph:
    """验证 _SUBSYSTEM_DEPS 依赖图的正确性"""

    def test_no_circular_deps(self):
        cycles = _check_circular_deps(_SUBSYSTEM_DEPS)
        assert cycles == [], f"Circular dependencies found: {cycles}"

    def test_device_router_declared(self):
        assert "device_router" in _SUBSYSTEM_DEPS
        assert "command_router" in _SUBSYSTEM_DEPS["device_router"]
        assert "event_bridge" in _SUBSYSTEM_DEPS["device_router"]

    def test_orchestrator_declared(self):
        assert "orchestrator" in _SUBSYSTEM_DEPS
        assert "device_router" in _SUBSYSTEM_DEPS["orchestrator"]

    def test_all_deps_reference_known_subsystems(self):
        """所有依赖目标应在依赖图中有声明"""
        all_subsystems = set(_SUBSYSTEM_DEPS.keys())
        for subsystem, deps in _SUBSYSTEM_DEPS.items():
            for dep in deps:
                assert dep in all_subsystems, (
                    f"Subsystem '{subsystem}' depends on '{dep}' "
                    f"which is not declared in _SUBSYSTEM_DEPS"
                )

    def test_command_router_declared(self):
        assert "command_router" in _SUBSYSTEM_DEPS

    def test_event_bridge_declared(self):
        assert "event_bridge" in _SUBSYSTEM_DEPS
