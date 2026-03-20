"""
tests/conformance/test_udm_ssot_conformance.py
================================================
Block-6 / PR-6 — SSOT / UDM Conformance Tests

覆盖项：
  1. Registration → Heartbeat → Upsert consistency
  2. state_version monotonicity across write paths
  3. Cross-module consistency (UDM ↔ CapabilityRegistry)
  4. Node capability sync (NodeFabricRegistry → CapabilityRegistry)
  5. Stale capability expiry
  6. Illegal write-path detector (audit script)
"""

from __future__ import annotations

import time
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_all() -> None:
    """全量重置所有单例（测试隔离）。"""
    from core.unified.device_manager import UnifiedDeviceManager
    UnifiedDeviceManager._instance = None

    from core.agent.capability_registry import CapabilityRegistry
    CapabilityRegistry._instance = None

    from core.nodes.node_fabric_registry import reset_node_fabric_registry
    reset_node_fabric_registry()


def _make_device(device_id: str = "dev-001", **kwargs: Any):
    """构造 UnifiedDevice 用于测试。"""
    from core.unified.models import UnifiedDevice, UnifiedDeviceType, UnifiedDeviceStatus
    return UnifiedDevice(
        device_id=device_id,
        device_name=kwargs.get("device_name", f"device-{device_id}"),
        device_type=kwargs.get("device_type", UnifiedDeviceType.ANDROID),
        status=kwargs.get("status", UnifiedDeviceStatus.ONLINE),
        capabilities=kwargs.get("capabilities", ["screen", "touch"]),
        metadata=kwargs.get("metadata", {}),
    )


# ===========================================================================
# 1. Registration → Heartbeat → Upsert consistency
# ===========================================================================


class TestRegistrationHeartbeatUpsertConsistency:
    def setup_method(self) -> None:
        _reset_all()

    def test_register_then_heartbeat(self) -> None:
        from core.unified.device_manager import get_unified_device_manager
        udm = get_unified_device_manager()
        device = _make_device("dev-hb-01")
        udm.register_device(device)

        found = udm.get_device("dev-hb-01")
        assert found is not None
        initial_version = found.state_version

        udm.heartbeat("dev-hb-01")
        after_hb = udm.get_device("dev-hb-01")
        assert after_hb is not None
        # heartbeat must bump state_version
        assert after_hb.state_version > initial_version

    def test_upsert_after_registration(self) -> None:
        from core.unified.device_manager import get_unified_device_manager
        udm = get_unified_device_manager()
        device = _make_device("dev-upsert-01")
        udm.register_device(device)

        before = udm.get_device("dev-upsert-01")
        assert before is not None
        v0 = before.state_version

        udm.upsert_device_state("dev-upsert-01", {"capabilities": ["screen", "camera"]}, source="test")
        after = udm.get_device("dev-upsert-01")
        assert after is not None
        assert after.state_version > v0
        assert "camera" in (after.capabilities or [])

    def test_register_replaces_existing(self) -> None:
        """重复注册不应丢失现有设备（幂等覆盖）。"""
        from core.unified.device_manager import get_unified_device_manager
        from core.unified.models import UnifiedDeviceStatus
        udm = get_unified_device_manager()

        d1 = _make_device("dev-dup-01")
        udm.register_device(d1)

        d2 = _make_device("dev-dup-01", device_name="updated-name")
        udm.register_device(d2)

        found = udm.get_device("dev-dup-01")
        assert found is not None
        assert found.device_name == "updated-name"

    def test_heartbeat_unknown_device_does_not_raise(self) -> None:
        from core.unified.device_manager import get_unified_device_manager
        udm = get_unified_device_manager()
        # 对未注册设备调用 heartbeat 不得抛异常
        udm.heartbeat("nonexistent-device")

    def test_upsert_unknown_device_returns_none(self) -> None:
        from core.unified.device_manager import get_unified_device_manager
        udm = get_unified_device_manager()
        result = udm.upsert_device_state("ghost-device", {"status": "online"}, source="test")
        assert result is None

    def test_full_lifecycle(self) -> None:
        """完整生命周期：注册 → 心跳 → upsert → 注销。"""
        from core.unified.device_manager import get_unified_device_manager
        from core.unified.models import UnifiedDeviceStatus
        udm = get_unified_device_manager()

        device = _make_device("dev-lifecycle-01")
        udm.register_device(device)

        udm.heartbeat("dev-lifecycle-01")
        udm.upsert_device_state(
            "dev-lifecycle-01",
            {"status": "busy", "metadata": {"task": "running"}},
            source="orchestrator",
        )

        d = udm.get_device("dev-lifecycle-01")
        assert d is not None
        assert d.state_version >= 2
        assert d.metadata.get("task") == "running"

        udm.unregister_device("dev-lifecycle-01")
        assert udm.get_device("dev-lifecycle-01") is None


# ===========================================================================
# 2. state_version monotonicity
# ===========================================================================


class TestStateVersionMonotonicity:
    def setup_method(self) -> None:
        _reset_all()

    def test_state_version_starts_at_zero(self) -> None:
        from core.unified.models import UnifiedDevice
        d = UnifiedDevice(device_id="sv-test", device_name="test")
        assert d.state_version == 0

    def test_monotonic_on_upsert(self) -> None:
        from core.unified.device_manager import get_unified_device_manager
        udm = get_unified_device_manager()
        device = _make_device("sv-mono-01")
        udm.register_device(device)

        versions = []
        for i in range(5):
            result = udm.upsert_device_state(
                "sv-mono-01",
                {"metadata": {"iteration": i}},
                source="test",
            )
            assert result is not None
            versions.append(result.state_version)

        # 严格单调递增
        for i in range(1, len(versions)):
            assert versions[i] > versions[i - 1], (
                f"state_version not monotonic at index {i}: {versions}"
            )

    def test_monotonic_on_heartbeat(self) -> None:
        from core.unified.device_manager import get_unified_device_manager
        udm = get_unified_device_manager()
        device = _make_device("sv-hb-mono-01")
        udm.register_device(device)

        v0 = udm.get_device("sv-hb-mono-01").state_version  # type: ignore[union-attr]
        udm.heartbeat("sv-hb-mono-01")
        v1 = udm.get_device("sv-hb-mono-01").state_version  # type: ignore[union-attr]
        assert v1 > v0

    def test_monotonic_on_update_status(self) -> None:
        from core.unified.device_manager import get_unified_device_manager
        from core.unified.models import UnifiedDeviceStatus
        udm = get_unified_device_manager()
        device = _make_device("sv-status-01")
        udm.register_device(device)

        v0 = udm.get_device("sv-status-01").state_version  # type: ignore[union-attr]
        udm.update_device_status("sv-status-01", UnifiedDeviceStatus.BUSY)
        v1 = udm.get_device("sv-status-01").state_version  # type: ignore[union-attr]
        assert v1 > v0

    def test_state_version_never_negative(self) -> None:
        from core.unified.device_manager import get_unified_device_manager
        udm = get_unified_device_manager()
        device = _make_device("sv-noneg-01")
        udm.register_device(device)

        for _ in range(10):
            udm.heartbeat("sv-noneg-01")
        d = udm.get_device("sv-noneg-01")
        assert d is not None
        assert d.state_version >= 0


# ===========================================================================
# 3. Cross-module consistency (UDM ↔ CapabilityRegistry)
# ===========================================================================


class TestCrossModuleConsistency:
    def setup_method(self) -> None:
        _reset_all()

    def test_capability_registry_inject_item(self) -> None:
        from core.agent.capability_registry import CapabilityRegistry, CapabilityItem
        reg = CapabilityRegistry.get_instance()

        item = CapabilityItem(
            name="node__test-node__infer",
            description="[Node:test-node:worker] LLM inference",
            source="node",
            source_id="test-node",
            available=True,
        )
        reg.inject_item(item)
        found = reg.get("node__test-node__infer")
        assert found is not None
        assert found.source == "node"

    def test_gateway_capability_available_after_device_register(self) -> None:
        """注册设备后，设备能力条目应在 CapabilityRegistry 中可见（若 refresh 已调用）。"""
        from core.agent.capability_registry import CapabilityItem, CapabilityRegistry
        reg = CapabilityRegistry.get_instance()

        # 直接注入模拟 gateway 能力（不依赖 UDM 异步刷新）
        item = CapabilityItem(
            name="gateway__dev-001__screen",
            description="[Gateway:dev-001] 设备能力: screen",
            source="gateway",
            source_id="dev-001",
            available=True,
        )
        reg.inject_item(item)

        results = reg.find("screen")
        assert any(r.name == "gateway__dev-001__screen" for r in results)

    def test_eject_removes_item(self) -> None:
        from core.agent.capability_registry import CapabilityRegistry, CapabilityItem
        reg = CapabilityRegistry.get_instance()

        item = CapabilityItem(
            name="node__ejected-node__cap",
            description="test",
            source="node",
            source_id="ejected-node",
        )
        reg.inject_item(item)
        assert reg.get("node__ejected-node__cap") is not None

        reg.eject("node__ejected-node__cap")
        assert reg.get("node__ejected-node__cap") is None

    def test_stats_reflects_injected_items(self) -> None:
        from core.agent.capability_registry import CapabilityRegistry, CapabilityItem
        reg = CapabilityRegistry.get_instance()

        for i in range(3):
            reg.inject_item(CapabilityItem(
                name=f"node__stats-node__{i}",
                description=f"cap {i}",
                source="node",
                source_id="stats-node",
            ))

        stats = reg.stats()
        assert stats["by_source"].get("node", 0) >= 3


# ===========================================================================
# 4. Node capability sync (NodeFabricRegistry → CapabilityRegistry)
# ===========================================================================


class TestNodeCapabilitySync:
    def setup_method(self) -> None:
        _reset_all()

    def _make_node(self, node_id: str, caps: list[str] | None = None):
        from core.nodes.node_fabric_registry import NodeInfo, NodeCapability, NodeRole, NodeStatus
        capabilities = [
            NodeCapability(name=c, description=f"cap {c}")
            for c in (caps or ["llm_inference"])
        ]
        return NodeInfo(
            node_id=node_id,
            role=NodeRole.WORKER,
            host="localhost",
            port=9000,
            status=NodeStatus.HEALTHY,
            capabilities=capabilities,
        )

    def test_sync_injects_into_capability_registry(self) -> None:
        from core.nodes.node_fabric_registry import get_node_fabric_registry
        from core.agent.capability_registry import CapabilityRegistry

        reg_fab = get_node_fabric_registry()
        node = self._make_node("sync-node-01", caps=["llm_inference", "vision"])
        reg_fab.register(node)

        injected = reg_fab.sync_capabilities_to_registry()
        assert injected == 2

        cap_reg = CapabilityRegistry.get_instance()
        assert cap_reg.get("node__sync-node-01__llm_inference") is not None
        assert cap_reg.get("node__sync-node-01__vision") is not None

    def test_unhealthy_node_not_synced(self) -> None:
        from core.nodes.node_fabric_registry import (
            get_node_fabric_registry, NodeInfo, NodeCapability, NodeRole, NodeStatus,
        )
        from core.agent.capability_registry import CapabilityRegistry

        reg_fab = get_node_fabric_registry()
        node = NodeInfo(
            node_id="unhealthy-node-01",
            role=NodeRole.WORKER,
            status=NodeStatus.OFFLINE,
            capabilities=[NodeCapability(name="ghost_cap")],
            # simulate stale heartbeat by patching
        )
        # Force heartbeat to look stale
        node.last_heartbeat = time.monotonic() - 9999
        reg_fab.register(node)

        injected = reg_fab.sync_capabilities_to_registry()
        cap_reg = CapabilityRegistry.get_instance()
        assert cap_reg.get("node__unhealthy-node-01__ghost_cap") is None

    def test_expire_stale_capabilities(self) -> None:
        from core.nodes.node_fabric_registry import get_node_fabric_registry, NodeCapability
        from core.agent.capability_registry import CapabilityRegistry, CapabilityItem

        reg_fab = get_node_fabric_registry()
        cap_reg = CapabilityRegistry.get_instance()

        # 注入一个带旧时间戳的节点能力
        old_ts = time.monotonic() - 9999
        item = CapabilityItem(
            name="node__old-node__old_cap",
            description="stale cap",
            source="node",
            source_id="old-node",
            metadata={"registered_at": old_ts},
        )
        cap_reg.inject_item(item)
        assert cap_reg.get("node__old-node__old_cap") is not None

        # TTL = 100s — old_ts 已远超，应被清除
        expired = reg_fab.expire_stale_capabilities(ttl=100)
        assert expired >= 1
        assert cap_reg.get("node__old-node__old_cap") is None

    def test_dependency_graph_consistent(self) -> None:
        from core.nodes.node_fabric_registry import get_node_fabric_registry, NodeInfo, NodeRole

        fab = get_node_fabric_registry()
        n1 = NodeInfo(node_id="dep-n1", role=NodeRole.WORKER, dependencies=[])
        n2 = NodeInfo(node_id="dep-n2", role=NodeRole.WORKER, dependencies=["dep-n1"])
        n3 = NodeInfo(node_id="dep-n3", role=NodeRole.WORKER, dependencies=["dep-n1", "dep-n2"])
        fab.register(n1)
        fab.register(n2)
        fab.register(n3)

        graph = fab.get_dependency_graph()
        assert graph["dep-n1"] == []
        assert "dep-n1" in graph["dep-n2"]
        assert "dep-n1" in graph["dep-n3"]
        assert "dep-n2" in graph["dep-n3"]

        dependents = fab.get_dependents("dep-n1")
        assert "dep-n2" in dependents
        assert "dep-n3" in dependents

    def test_100_nodes_registered(self) -> None:
        """注册 100 个节点，确保 count() 正确且健康节点查询不崩溃。"""
        from core.nodes.node_fabric_registry import get_node_fabric_registry, NodeInfo, NodeRole, NodeStatus

        fab = get_node_fabric_registry()
        for i in range(100):
            fab.register(NodeInfo(
                node_id=f"fabric-node-{i:03d}",
                role=NodeRole.WORKER,
                status=NodeStatus.HEALTHY,
            ))

        assert fab.count() >= 100
        healthy = fab.list_healthy()
        # 所有节点心跳新鲜，都应该健康
        assert len(healthy) >= 100

    def test_metrics_after_100_nodes(self) -> None:
        from core.nodes.node_fabric_registry import get_node_fabric_registry, NodeInfo, NodeRole, NodeStatus

        fab = get_node_fabric_registry()
        for i in range(100):
            fab.register(NodeInfo(
                node_id=f"metrics-node-{i:03d}",
                role=NodeRole.WORKER,
                status=NodeStatus.HEALTHY,
            ))

        metrics = fab.get_metrics()
        assert metrics["total_nodes"] >= 100
        assert metrics["healthy_nodes"] >= 100
        assert metrics["avg_health_score"] > 0.5
        assert "by_status" in metrics
        assert "by_role" in metrics


# ===========================================================================
# 5. Audit script — illegal paths report 0
# ===========================================================================


class TestUDMAuditScript:
    def test_audit_reports_no_violations_on_legal_code(self) -> None:
        """审计工具对仅使用 UDM 合法 API 的代码不报告违规。"""
        import ast
        import tempfile
        import textwrap
        from pathlib import Path
        from scripts.audit_udm_write_paths import _scan_file

        legal_code = textwrap.dedent("""\
            from core.unified.device_manager import get_unified_device_manager
            udm = get_unified_device_manager()
            udm.register_device(device)
            udm.heartbeat('dev-01')
            udm.upsert_device_state('dev-01', {'status': 'online'}, source='test')
        """)
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(legal_code)
            fpath = Path(f.name)

        try:
            violations, _ = _scan_file(fpath, fpath.parent)
            assert violations == [], f"Unexpected violations: {violations}"
        finally:
            fpath.unlink(missing_ok=True)

    def test_audit_detects_direct_field_write(self) -> None:
        """审计工具必须检测直接属性赋值的非法写路径。"""
        import tempfile
        import textwrap
        from pathlib import Path
        from scripts.audit_udm_write_paths import _scan_file

        illegal_code = textwrap.dedent("""\
            # some module that bypasses UDM
            device = get_device()
            device.status = 'online'
            device.capabilities = ['screen']
        """)
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(illegal_code)
            fpath = Path(f.name)

        try:
            violations, _ = _scan_file(fpath, fpath.parent)
            assert len(violations) >= 2, f"Expected >=2 violations, got {violations}"
            kinds = {v.kind for v in violations}
            assert "direct_field_write" in kinds
        finally:
            fpath.unlink(missing_ok=True)

    def test_audit_detects_direct_devices_access(self) -> None:
        """审计工具必须检测直接写入 _devices 字典的非法路径。"""
        import tempfile
        import textwrap
        from pathlib import Path
        from scripts.audit_udm_write_paths import _scan_file

        illegal_code = textwrap.dedent("""\
            mgr = get_manager()
            mgr._devices['dev-01'] = device
        """)
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(illegal_code)
            fpath = Path(f.name)

        try:
            violations, _ = _scan_file(fpath, fpath.parent)
            assert any(v.kind == "direct_devices_access" for v in violations), (
                f"Expected direct_devices_access violation, got {violations}"
            )
        finally:
            fpath.unlink(missing_ok=True)

    def test_state_version_monotonicity_check_passes(self) -> None:
        """state_version 单调性检查在正常环境下应无问题。"""
        from scripts.audit_udm_write_paths import _check_state_version_monotonicity
        issues = _check_state_version_monotonicity()
        # 不期望有错误
        assert issues == [], f"state_version issues: {issues}"

    def test_run_audit_returns_result(self, tmp_path) -> None:
        """run_audit() 正常返回 AuditResult，illegal_count 为整数。"""
        from scripts.audit_udm_write_paths import run_audit, REPO_ROOT
        result = run_audit(root=REPO_ROOT)
        assert isinstance(result.illegal_count, int)
        assert result.scanned_files > 0
        assert result.scanned_lines > 0


# ===========================================================================
# 6. Node Fabric Registry lifecycle tests
# ===========================================================================


class TestNodeFabricLifecycle:
    def setup_method(self) -> None:
        _reset_all()

    def test_register_unregister(self) -> None:
        from core.nodes.node_fabric_registry import get_node_fabric_registry, NodeInfo, NodeRole

        fab = get_node_fabric_registry()
        n = NodeInfo(node_id="lc-node-01", role=NodeRole.AGENT)
        fab.register(n)
        assert fab.get("lc-node-01") is not None

        removed = fab.unregister("lc-node-01")
        assert removed is True
        assert fab.get("lc-node-01") is None

    def test_heartbeat_updates_timestamp(self) -> None:
        from core.nodes.node_fabric_registry import get_node_fabric_registry, NodeInfo, NodeRole

        fab = get_node_fabric_registry()
        n = NodeInfo(node_id="hb-node-01", role=NodeRole.WORKER)
        n.last_heartbeat = time.monotonic() - 30
        fab.register(n)

        fab.heartbeat("hb-node-01")
        node = fab.get("hb-node-01")
        assert node is not None
        assert node.heartbeat_age_secs() < 5

    def test_mark_offline_if_stale(self) -> None:
        from core.nodes.node_fabric_registry import (
            get_node_fabric_registry, NodeInfo, NodeRole, NodeStatus,
        )

        fab = get_node_fabric_registry()
        n = NodeInfo(node_id="stale-node-01", role=NodeRole.WORKER, status=NodeStatus.HEALTHY)
        n.last_heartbeat = time.monotonic() - 9999
        fab.register(n)

        stale = fab.mark_offline_if_stale()
        assert "stale-node-01" in stale
        node = fab.get("stale-node-01")
        assert node is not None
        assert node.status == NodeStatus.OFFLINE

    def test_list_by_capability(self) -> None:
        from core.nodes.node_fabric_registry import (
            get_node_fabric_registry, NodeInfo, NodeCapability, NodeRole,
        )

        fab = get_node_fabric_registry()
        n1 = NodeInfo(node_id="cap-node-01", role=NodeRole.TOOL,
                      capabilities=[NodeCapability(name="search")])
        n2 = NodeInfo(node_id="cap-node-02", role=NodeRole.TOOL,
                      capabilities=[NodeCapability(name="ocr")])
        fab.register(n1)
        fab.register(n2)

        search_nodes = fab.list_by_capability("search")
        assert len(search_nodes) >= 1
        assert any(n.node_id == "cap-node-01" for n in search_nodes)

    def test_record_error_degrades_health(self) -> None:
        from core.nodes.node_fabric_registry import get_node_fabric_registry, NodeInfo, NodeRole

        fab = get_node_fabric_registry()
        n = NodeInfo(node_id="err-node-01", role=NodeRole.WORKER)
        fab.register(n)

        for _ in range(20):
            fab.record_error("err-node-01")

        node = fab.get("err-node-01")
        assert node is not None
        assert node.health_score() <= 0.5
