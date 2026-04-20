"""
PR-8 验收测试 — 长尾兼容面分类与高价值多设备流处理
========================================================

验收清单：
  1. long_tail_compat_surface 模块可导入，哨兵存在
  2. 目录覆盖所有已知的 generic-forward 长尾路径
  3. 最高价值流（file_transfer, peer_announce, peer_exchange, mesh_topology）
     标记为 CANONICAL + is_closed_loop=True
  4. 剩余 generic-forward 路径标记为 GENERIC_FORWARD + is_closed_loop=False
  5. build_catalog_summary() 数据一致
  6. handle_file_transfer 返回带有 lifecycle_state 的结构化 ACK
  7. handle_peer_announce 集成 MeshCoordinator 并返回 peer_exchange 响应
  8. handle_peer_exchange 返回带 peer_count 的 peer_exchange 响应
  9. handle_mesh_topology 返回带有拓扑数据的结构化响应
  10. android_bridge 为最高价值类型使用规范处理器而非 generic-forward
  11. projection.py 包含 LONG_TAIL_COMPAT_SURFACE_ALIGNED_PR8 哨兵
  12. get_paths_by_tier / get_generic_forward_paths / get_closed_loop_paths 查询正确
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Availability guards for optional dependencies
# ---------------------------------------------------------------------------

try:
    import pydantic  # noqa: F401
    _PYDANTIC_AVAILABLE = True
except ImportError:
    _PYDANTIC_AVAILABLE = False

try:
    import fastapi  # noqa: F401
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False


# ──────────────────────────────────────────────────────────────────────────────
# 1. 模块可导入 + 哨兵
# ──────────────────────────────────────────────────────────────────────────────


class TestModuleSentinels:
    def test_import_and_authority_sentinel(self):
        from core.long_tail_compat_surface import (
            LONG_TAIL_COMPAT_SURFACE_IS_AUTHORITY,
            LONG_TAIL_COMPAT_SURFACE_PR8_SENTINEL,
        )
        assert "IS_CANONICAL_AUTHORITY_PR8" in LONG_TAIL_COMPAT_SURFACE_IS_AUTHORITY
        assert "PR8_SENTINEL" in LONG_TAIL_COMPAT_SURFACE_PR8_SENTINEL

    def test_policy_sentinels_present(self):
        from core.long_tail_compat_surface import (
            GENERIC_FORWARD_IS_TRANSITIONAL_POLICY,
            MINIMAL_COMPAT_PATHS_MUST_BE_CATALOGUED_POLICY,
            HIGHEST_VALUE_FLOWS_REQUIRE_STATEFUL_HANDLING_POLICY,
            LONG_TAIL_HONESTY_POLICY,
        )
        assert "TRANSITIONAL" in GENERIC_FORWARD_IS_TRANSITIONAL_POLICY
        assert "CATALOGUED" in MINIMAL_COMPAT_PATHS_MUST_BE_CATALOGUED_POLICY
        assert "HIGHEST_VALUE" in HIGHEST_VALUE_FLOWS_REQUIRE_STATEFUL_HANDLING_POLICY
        assert "HONESTY" in LONG_TAIL_HONESTY_POLICY


# ──────────────────────────────────────────────────────────────────────────────
# 2. 目录覆盖所有 generic-forward 路径
# ──────────────────────────────────────────────────────────────────────────────


class TestCatalogCoverage:
    def test_catalog_is_non_empty(self):
        from core.long_tail_compat_surface import get_long_tail_catalog
        catalog = get_long_tail_catalog()
        assert len(catalog) >= 12, f"Expected ≥12 entries, got {len(catalog)}"

    def test_all_expected_message_types_present(self):
        from core.long_tail_compat_surface import get_long_tail_catalog
        catalog = get_long_tail_catalog()
        types_in_catalog = {r.message_type for r in catalog}
        expected = {
            "file_transfer",
            "peer_announce",
            "peer_exchange",
            "mesh_topology",
            "ui_tree_request",
            "action_execute",
            "action_sequence_execute",
            "app_start",
            "app_stop",
            "system_command",
            "task_cancel",
            "task_status",
            "agent_config_update",
            "agent_restart",
        }
        missing = expected - types_in_catalog
        assert not missing, f"Message types missing from catalog: {missing}"


# ──────────────────────────────────────────────────────────────────────────────
# 3. 最高价值流标记为 CANONICAL + is_closed_loop
# ──────────────────────────────────────────────────────────────────────────────


class TestHighestValueFlows:
    _HIGHEST_VALUE_TYPES = {
        "file_transfer",
        "peer_announce",
        "peer_exchange",
        "mesh_topology",
    }

    def test_highest_value_flows_are_canonical(self):
        from core.long_tail_compat_surface import (
            get_long_tail_catalog,
            LongTailTransitionStatus,
            LongTailValueTier,
        )
        catalog = {r.message_type: r for r in get_long_tail_catalog()}
        for mt in self._HIGHEST_VALUE_TYPES:
            assert mt in catalog, f"Missing: {mt}"
            record = catalog[mt]
            assert record.value_tier == LongTailValueTier.HIGHEST, (
                f"{mt} should have tier=HIGHEST, got {record.value_tier}"
            )
            assert record.transition_status == LongTailTransitionStatus.CANONICAL, (
                f"{mt} should be CANONICAL, got {record.transition_status}"
            )
            assert record.is_closed_loop, f"{mt} should be is_closed_loop=True"
            assert record.canonical_handler, f"{mt} should have a canonical_handler"

    def test_highest_value_flows_have_pr8_handler_paths(self):
        from core.long_tail_compat_surface import get_long_tail_catalog
        catalog = {r.message_type: r for r in get_long_tail_catalog()}
        assert "file_transfer" in catalog[
            "file_transfer"].canonical_handler
        assert "peer_exchange" in catalog["peer_announce"].canonical_handler
        assert "peer_exchange" in catalog["peer_exchange"].canonical_handler
        assert "mesh_topology" in catalog["mesh_topology"].canonical_handler


# ──────────────────────────────────────────────────────────────────────────────
# 4. 剩余路径标记为 GENERIC_FORWARD
# ──────────────────────────────────────────────────────────────────────────────


class TestTransitionalPaths:
    _TRANSITIONAL_TYPES = {
        "ui_tree_request",
        "action_execute",
        "action_sequence_execute",
        "app_start",
        "app_stop",
        "system_command",
        "agent_config_update",
        "agent_restart",
    }

    def test_transitional_paths_are_generic_forward(self):
        from core.long_tail_compat_surface import (
            get_long_tail_catalog,
            LongTailTransitionStatus,
        )
        catalog = {r.message_type: r for r in get_long_tail_catalog()}
        for mt in self._TRANSITIONAL_TYPES:
            assert mt in catalog, f"Missing: {mt}"
            record = catalog[mt]
            assert (
                record.transition_status == LongTailTransitionStatus.GENERIC_FORWARD
            ), f"{mt} should be GENERIC_FORWARD, got {record.transition_status}"
            assert not record.is_closed_loop, (
                f"{mt} should be is_closed_loop=False"
            )

    def test_transitional_paths_have_notes(self):
        from core.long_tail_compat_surface import get_long_tail_catalog
        catalog = {r.message_type: r for r in get_long_tail_catalog()}
        for mt in self._TRANSITIONAL_TYPES:
            assert catalog[mt].notes, f"{mt} should have non-empty notes"


# ──────────────────────────────────────────────────────────────────────────────
# 4b. task_cancel / task_status — 已升级为 CANONICAL closed-loop
# ──────────────────────────────────────────────────────────────────────────────


class TestTaskLifecycleCanonicalPaths:
    """task_cancel and task_status are now CANONICAL closed-loop handlers."""

    _CANONICAL_TYPES = {"task_cancel", "task_status"}

    def test_task_lifecycle_paths_are_canonical(self):
        from core.long_tail_compat_surface import (
            get_long_tail_catalog,
            LongTailTransitionStatus,
        )
        catalog = {r.message_type: r for r in get_long_tail_catalog()}
        for mt in self._CANONICAL_TYPES:
            assert mt in catalog, f"Missing: {mt}"
            record = catalog[mt]
            assert record.transition_status == LongTailTransitionStatus.CANONICAL, (
                f"{mt} should be CANONICAL, got {record.transition_status}"
            )
            assert record.is_closed_loop, f"{mt} should be is_closed_loop=True"
            assert record.canonical_handler, f"{mt} should have a canonical_handler"

    def test_task_lifecycle_canonical_handler_paths(self):
        from core.long_tail_compat_surface import get_long_tail_catalog
        catalog = {r.message_type: r for r in get_long_tail_catalog()}
        assert "handle_task_cancel" in catalog["task_cancel"].canonical_handler
        assert "handle_task_status" in catalog["task_status"].canonical_handler


# ──────────────────────────────────────────────────────────────────────────────
# 5. build_catalog_summary 数据一致
# ──────────────────────────────────────────────────────────────────────────────


class TestCatalogSummary:
    def test_summary_counts_match_catalog(self):
        from core.long_tail_compat_surface import (
            build_catalog_summary,
            get_long_tail_catalog,
            LongTailTransitionStatus,
        )
        catalog = get_long_tail_catalog()
        summary = build_catalog_summary()

        assert summary.total == len(catalog)
        assert summary.closed_loop_count == sum(1 for r in catalog if r.is_closed_loop)
        assert summary.generic_forward_count == sum(
            1 for r in catalog
            if r.transition_status == LongTailTransitionStatus.GENERIC_FORWARD
        )

    def test_summary_highest_tier_count(self):
        from core.long_tail_compat_surface import (
            build_catalog_summary,
            LongTailValueTier,
        )
        summary = build_catalog_summary()
        assert summary.by_tier.get(LongTailValueTier.HIGHEST.value, 0) == 4

    def test_summary_canonical_types_include_highest_value(self):
        from core.long_tail_compat_surface import build_catalog_summary
        summary = build_catalog_summary()
        for mt in ("file_transfer", "peer_announce", "peer_exchange", "mesh_topology"):
            assert mt in summary.canonical_message_types, (
                f"{mt} should be in canonical_message_types"
            )


# ──────────────────────────────────────────────────────────────────────────────
# 6. handle_file_transfer — 结构化 ACK
# ──────────────────────────────────────────────────────────────────────────────


class TestHandleFileTransfer:
    @pytest.mark.skipif(not _PYDANTIC_AVAILABLE, reason="pydantic not installed")
    @pytest.mark.asyncio
    async def test_basic_ack_structure(self):
        from galaxy_gateway.android.handlers.file_transfer import handle_file_transfer

        bridge = MagicMock()
        ws = MagicMock()
        msg = {
            "type": "file_transfer",
            "device_id": "dev-01",
            "message_id": "msg-abc",
            "payload": {
                "file_name": "photo.jpg",
                "file_size": 2048,
                "checksum": "abc123",
            },
        }

        result = await handle_file_transfer(bridge, ws, msg)

        assert result["type"] == "file_transfer_ack"
        assert result["device_id"] == "dev-01"
        assert result["file_name"] == "photo.jpg"
        assert result["file_size"] == 2048
        assert result["checksum"] == "abc123"
        assert result["lifecycle_state"] == "transfer_accepted"
        assert result["transfer_id"]
        assert result["correlation_id"] == "msg-abc"

    @pytest.mark.skipif(not _PYDANTIC_AVAILABLE, reason="pydantic not installed")
    @pytest.mark.asyncio
    async def test_transfer_id_generated_when_absent(self):
        from galaxy_gateway.android.handlers.file_transfer import handle_file_transfer

        bridge = MagicMock()
        ws = MagicMock()
        msg = {"type": "file_transfer", "device_id": "dev-01"}

        result = await handle_file_transfer(bridge, ws, msg)
        assert result.get("transfer_id"), "transfer_id should be auto-generated"

    @pytest.mark.skipif(not _PYDANTIC_AVAILABLE, reason="pydantic not installed")
    @pytest.mark.asyncio
    async def test_orchestrated_transfer_success(self):
        """When source/target/path are provided, delegates to DeviceOrchestrator."""
        from galaxy_gateway.android.handlers.file_transfer import handle_file_transfer

        bridge = MagicMock()
        ws = MagicMock()
        msg = {
            "type": "file_transfer",
            "device_id": "dev-01",
            "payload": {
                "source_device": "phone-1",
                "target_device": "laptop-1",
                "file_path": "/sdcard/photo.jpg",
            },
        }

        mock_orch = MagicMock()
        mock_orch.transfer_file = AsyncMock(return_value={
            "status": "success",
            "elapsed_ms": 120.5,
        })

        with patch(
            "galaxy_gateway.android.handlers.file_transfer.DeviceOrchestrator",
            return_value=mock_orch,
        ):
            result = await handle_file_transfer(bridge, ws, msg)

        assert result["status"] == "success"
        assert result["lifecycle_state"] == "transfer_complete"
        assert result["source_device"] == "phone-1"
        assert result["target_device"] == "laptop-1"
        assert result["elapsed_ms"] == 120.5

    @pytest.mark.skipif(not _PYDANTIC_AVAILABLE, reason="pydantic not installed")
    @pytest.mark.asyncio
    async def test_orchestrated_transfer_falls_back_on_import_error(self):
        """Falls back to announcement ACK when DeviceOrchestrator not available."""
        from galaxy_gateway.android.handlers.file_transfer import handle_file_transfer

        bridge = MagicMock()
        ws = MagicMock()
        msg = {
            "type": "file_transfer",
            "device_id": "dev-01",
            "payload": {
                "source_device": "phone-1",
                "target_device": "laptop-1",
                "file_path": "/sdcard/photo.jpg",
            },
        }

        with patch(
            "galaxy_gateway.android.handlers.file_transfer.DeviceOrchestrator",
            side_effect=ImportError("not available"),
        ):
            result = await handle_file_transfer(bridge, ws, msg)

        # Should still return a valid ACK
        assert result["type"] == "file_transfer_ack"
        assert result["lifecycle_state"] == "transfer_accepted"


# ──────────────────────────────────────────────────────────────────────────────
# 7. handle_peer_announce — MeshCoordinator 集成
# ──────────────────────────────────────────────────────────────────────────────


class TestHandlePeerAnnounce:
    @pytest.mark.skipif(not _PYDANTIC_AVAILABLE, reason="pydantic not installed")
    @pytest.mark.asyncio
    async def test_returns_peer_exchange_type(self):
        from galaxy_gateway.android.handlers.peer_exchange import handle_peer_announce

        bridge = MagicMock()
        ws = MagicMock()
        msg = {
            "type": "peer_announce",
            "device_id": "dev-02",
            "message_id": "msg-123",
            "payload": {"local_ip": "192.168.1.10", "local_port": 8080},
        }

        # No MeshCoordinator available
        with patch(
            "galaxy_gateway.android.handlers.peer_exchange._get_mesh_coordinator",
            return_value=None,
        ):
            result = await handle_peer_announce(bridge, ws, msg)

        assert result["type"] == "peer_exchange"
        assert result["device_id"] == "dev-02"
        assert result["lifecycle_state"] == "peer_registered"
        assert isinstance(result["peers"], list)
        assert result["coordinator_available"] is False

    @pytest.mark.skipif(not _PYDANTIC_AVAILABLE, reason="pydantic not installed")
    @pytest.mark.asyncio
    async def test_with_mesh_coordinator(self):
        from galaxy_gateway.android.handlers.peer_exchange import handle_peer_announce

        bridge = MagicMock()
        ws = MagicMock()
        msg = {
            "type": "peer_announce",
            "device_id": "dev-02",
            "message_id": "msg-456",
        }

        mock_peer = MagicMock()
        mock_peer.to_dict.return_value = {"device_id": "dev-02", "local_ip": "10.0.0.1"}

        mock_mesh = MagicMock()
        mock_mesh.handle_peer_announce.return_value = mock_peer
        mock_mesh.build_peer_exchange.return_value = [
            {"device_id": "dev-03", "local_ip": "10.0.0.2"}
        ]

        with patch(
            "galaxy_gateway.android.handlers.peer_exchange._get_mesh_coordinator",
            return_value=mock_mesh,
        ):
            result = await handle_peer_announce(bridge, ws, msg)

        assert result["coordinator_available"] is True
        assert result["peer_count"] == 1
        assert result["peers"][0]["device_id"] == "dev-03"
        assert result["your_peer"]["device_id"] == "dev-02"


# ──────────────────────────────────────────────────────────────────────────────
# 8. handle_peer_exchange — peer_count 字段
# ──────────────────────────────────────────────────────────────────────────────


class TestHandlePeerExchange:
    @pytest.mark.skipif(not _PYDANTIC_AVAILABLE, reason="pydantic not installed")
    @pytest.mark.asyncio
    async def test_returns_peer_count_field(self):
        from galaxy_gateway.android.handlers.peer_exchange import handle_peer_exchange

        bridge = MagicMock()
        ws = MagicMock()
        msg = {"type": "peer_exchange", "device_id": "dev-03"}

        mock_mesh = MagicMock()
        mock_mesh.build_peer_exchange.return_value = [
            {"device_id": "dev-01"},
            {"device_id": "dev-02"},
        ]

        with patch(
            "galaxy_gateway.android.handlers.peer_exchange._get_mesh_coordinator",
            return_value=mock_mesh,
        ):
            result = await handle_peer_exchange(bridge, ws, msg)

        assert result["type"] == "peer_exchange"
        assert result["peer_count"] == 2
        assert result["lifecycle_state"] == "peers_refreshed"
        assert result["coordinator_available"] is True

    @pytest.mark.skipif(not _PYDANTIC_AVAILABLE, reason="pydantic not installed")
    @pytest.mark.asyncio
    async def test_graceful_when_no_coordinator(self):
        from galaxy_gateway.android.handlers.peer_exchange import handle_peer_exchange

        bridge = MagicMock()
        ws = MagicMock()
        msg = {"type": "peer_exchange", "device_id": "dev-03"}

        with patch(
            "galaxy_gateway.android.handlers.peer_exchange._get_mesh_coordinator",
            return_value=None,
        ):
            result = await handle_peer_exchange(bridge, ws, msg)

        assert result["peers"] == []
        assert result["peer_count"] == 0
        assert result["coordinator_available"] is False


# ──────────────────────────────────────────────────────────────────────────────
# 9. handle_mesh_topology — 拓扑数据
# ──────────────────────────────────────────────────────────────────────────────


class TestHandleMeshTopology:
    @pytest.mark.skipif(not _PYDANTIC_AVAILABLE, reason="pydantic not installed")
    @pytest.mark.asyncio
    async def test_returns_topology_dict(self):
        from galaxy_gateway.android.handlers.mesh_topology import handle_mesh_topology

        bridge = MagicMock()
        ws = MagicMock()
        msg = {"type": "mesh_topology", "device_id": "dev-04"}

        mock_mesh = MagicMock()
        mock_mesh.get_topology.return_value = {
            "peers": {"dev-01": {}, "dev-02": {}},
            "relay_count": 1,
        }

        with patch(
            "galaxy_gateway.android.handlers.mesh_topology._get_mesh_coordinator",
            return_value=mock_mesh,
        ):
            result = await handle_mesh_topology(bridge, ws, msg)

        assert result["type"] == "mesh_topology"
        assert result["topology"]["relay_count"] == 1
        assert result["peer_count"] == 2
        assert result["lifecycle_state"] == "topology_returned"
        assert result["coordinator_available"] is True

    @pytest.mark.skipif(not _PYDANTIC_AVAILABLE, reason="pydantic not installed")
    @pytest.mark.asyncio
    async def test_graceful_when_no_coordinator(self):
        from galaxy_gateway.android.handlers.mesh_topology import handle_mesh_topology

        bridge = MagicMock()
        ws = MagicMock()
        msg = {"type": "mesh_topology", "device_id": "dev-04"}

        with patch(
            "galaxy_gateway.android.handlers.mesh_topology._get_mesh_coordinator",
            return_value=None,
        ):
            result = await handle_mesh_topology(bridge, ws, msg)

        assert result["topology"] == {}
        assert result["peer_count"] == 0
        assert result["coordinator_available"] is False
        assert result["lifecycle_state"] == "topology_returned"


# ──────────────────────────────────────────────────────────────────────────────
# 10. android_bridge dispatch table — 最高价值类型使用规范处理器
# ──────────────────────────────────────────────────────────────────────────────


class TestAndroidBridgeDispatch:
    def test_file_transfer_handler_is_not_generic_forward(self):
        """FILE_TRANSFER must not be routed through handle_generic_forward."""
        import pathlib
        src = pathlib.Path(__file__).parent.parent / "galaxy_gateway" / "android_bridge.py"
        text = src.read_text(encoding="utf-8")
        # The dispatch line for FILE_TRANSFER must reference handle_file_transfer
        assert "handle_file_transfer" in text, (
            "android_bridge.py should use handle_file_transfer for FILE_TRANSFER"
        )

    def test_peer_announce_handler_is_not_generic_forward(self):
        import pathlib
        src = pathlib.Path(__file__).parent.parent / "galaxy_gateway" / "android_bridge.py"
        text = src.read_text(encoding="utf-8")
        assert "handle_peer_announce" in text, (
            "android_bridge.py should use handle_peer_announce for PEER_ANNOUNCE"
        )

    def test_peer_exchange_handler_is_not_generic_forward(self):
        import pathlib
        src = pathlib.Path(__file__).parent.parent / "galaxy_gateway" / "android_bridge.py"
        text = src.read_text(encoding="utf-8")
        assert "handle_peer_exchange" in text, (
            "android_bridge.py should use handle_peer_exchange for PEER_EXCHANGE"
        )

    def test_mesh_topology_handler_is_not_generic_forward(self):
        import pathlib
        src = pathlib.Path(__file__).parent.parent / "galaxy_gateway" / "android_bridge.py"
        text = src.read_text(encoding="utf-8")
        assert "handle_mesh_topology" in text, (
            "android_bridge.py should use handle_mesh_topology for MESH_TOPOLOGY"
        )

    def test_dispatch_wiring_in_source(self):
        """Verify the dispatch table uses canonical handlers for the 4 types.

        Checks are done via AST inspection of the source to avoid brittle
        exact-string-format dependencies.
        """
        import ast
        import pathlib

        src_path = pathlib.Path(__file__).parent.parent / "galaxy_gateway" / "android_bridge.py"
        source = src_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        # Collect all assignment targets of the form:
        #   self._message_handlers[MessageType.XYZ] = _wrap(some_handler)
        # Build a mapping: message_type_attr → wrapped_function_name
        dispatch_map: dict[str, str] = {}

        for node in ast.walk(tree):
            # Look for: self._message_handlers[...] = _wrap(...)
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if not (isinstance(target, ast.Subscript) and
                        isinstance(target.value, ast.Attribute) and
                        target.value.attr == "_message_handlers"):
                    continue
                # Extract key: MessageType.FILE_TRANSFER → "FILE_TRANSFER"
                key_node = target.slice
                if isinstance(key_node, ast.Attribute):
                    type_attr = key_node.attr  # e.g. "FILE_TRANSFER"
                else:
                    continue
                # Extract value: _wrap(handle_file_transfer) → "handle_file_transfer"
                val_node = node.value
                if (isinstance(val_node, ast.Call) and
                        isinstance(val_node.func, ast.Name) and
                        val_node.func.id == "_wrap" and
                        val_node.args):
                    arg0 = val_node.args[0]
                    if isinstance(arg0, ast.Name):
                        dispatch_map[type_attr] = arg0.id

        expected = {
            "FILE_TRANSFER": "handle_file_transfer",
            "PEER_ANNOUNCE": "handle_peer_announce",
            "PEER_EXCHANGE": "handle_peer_exchange",
            "MESH_TOPOLOGY": "handle_mesh_topology",
        }
        for msg_type, expected_handler in expected.items():
            actual = dispatch_map.get(msg_type)
            assert actual == expected_handler, (
                f"MessageType.{msg_type} should be dispatched to"
                f" {expected_handler}, got {actual!r}"
            )


# ──────────────────────────────────────────────────────────────────────────────
# 11. projection.py 哨兵
# ──────────────────────────────────────────────────────────────────────────────


class TestProjectionSentinel:
    @pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
    def test_projection_aligned_sentinel_present(self):
        from core.routes.projection import LONG_TAIL_COMPAT_SURFACE_ALIGNED_PR8
        assert "PR8" in LONG_TAIL_COMPAT_SURFACE_ALIGNED_PR8
        assert "UNAVAILABLE" not in LONG_TAIL_COMPAT_SURFACE_ALIGNED_PR8, (
            "LONG_TAIL_COMPAT_SURFACE_ALIGNED_PR8 should not be the UNAVAILABLE fallback"
        )

    @pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
    def test_projection_sentinel_mentions_canonical_flows(self):
        from core.routes.projection import LONG_TAIL_COMPAT_SURFACE_ALIGNED_PR8
        for flow in ("file_transfer", "peer_announce", "peer_exchange", "mesh_topology"):
            assert flow in LONG_TAIL_COMPAT_SURFACE_ALIGNED_PR8, (
                f"Sentinel should mention {flow}"
            )


# ──────────────────────────────────────────────────────────────────────────────
# 12. query helpers
# ──────────────────────────────────────────────────────────────────────────────


class TestQueryHelpers:
    def test_get_paths_by_tier_highest(self):
        from core.long_tail_compat_surface import (
            get_paths_by_tier,
            LongTailValueTier,
        )
        highest = get_paths_by_tier(LongTailValueTier.HIGHEST)
        types = {r.message_type for r in highest}
        assert types == {"file_transfer", "peer_announce", "peer_exchange", "mesh_topology"}

    def test_get_generic_forward_paths(self):
        from core.long_tail_compat_surface import get_generic_forward_paths
        gf = get_generic_forward_paths()
        types = {r.message_type for r in gf}
        # Canonical paths should NOT appear in generic-forward list
        for mt in ("file_transfer", "peer_announce", "peer_exchange", "mesh_topology"):
            assert mt not in types, f"{mt} should not be in generic-forward list"
        # Transitional paths should appear
        assert "ui_tree_request" in types
        assert "action_execute" in types

    def test_get_closed_loop_paths(self):
        from core.long_tail_compat_surface import get_closed_loop_paths
        cl = get_closed_loop_paths()
        types = {r.message_type for r in cl}
        for mt in ("file_transfer", "peer_announce", "peer_exchange", "mesh_topology"):
            assert mt in types, f"{mt} should be in closed-loop list"

    def test_get_transitional_paths(self):
        from core.long_tail_compat_surface import get_transitional_paths
        tr = get_transitional_paths()
        types = {r.message_type for r in tr}
        for mt in ("file_transfer", "peer_announce", "peer_exchange", "mesh_topology"):
            assert mt not in types, f"{mt} should not be in transitional list"

    def test_get_path_record_returns_correct_record(self):
        from core.long_tail_compat_surface import get_path_record, LongTailValueTier
        record = get_path_record("file_transfer")
        assert record is not None
        assert record.value_tier == LongTailValueTier.HIGHEST

    def test_get_path_record_returns_none_for_unknown(self):
        from core.long_tail_compat_surface import get_path_record
        assert get_path_record("nonexistent_type") is None
