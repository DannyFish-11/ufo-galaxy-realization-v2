"""
tests/test_pr13_mesh_lifecycle_android_uplink.py
=================================================
PR-13 验收测试 — Android Mesh 生命周期上行链路闭环

验收清单：
  1. 协议枚举：MessageType 中包含 MESH_JOIN / MESH_RESULT / MESH_LEAVE
  2. android_bridge dispatch table 路由到专用处理器而非 generic_forward
  3. handle_mesh_join 返回结构化 ACK 并落盘至 android_mesh_lifecycle_store
  4. handle_mesh_result 返回结构化 ACK 并更新 session 状态为 ACTIVE
  5. handle_mesh_leave 返回结构化 ACK 并更新 session 状态为 LEFT
  6. android_mesh_lifecycle_store 线程安全写入与查询
  7. long_tail_compat_surface 包含三个 CANONICAL 目录条目
  8. /api/v1/mesh/android-lifecycle 端点存在且返回有效结构
  9. session_id 提取优先级：payload.session_id > payload.mesh_session_id > 自动生成
  10. 降级安全：store 异常时处理器仍返回有效 ACK
  11. build_android_lifecycle_truth 输出完整真值快照
  12. 完整生命周期序列：join → result → leave 状态流转
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# 可用性保护
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


# ===========================================================================
# 1. 协议枚举：MESH_JOIN / MESH_RESULT / MESH_LEAVE 存在于 MessageType
# ===========================================================================


class TestProtocolEnumeration:
    """PR-13：验证 MessageType 枚举包含三个 mesh 生命周期类型。"""

    def test_mesh_join_in_message_type(self):
        from galaxy_gateway.protocol.aip_v3 import MessageType
        assert MessageType.MESH_JOIN == "mesh_join"

    def test_mesh_result_in_message_type(self):
        from galaxy_gateway.protocol.aip_v3 import MessageType
        assert MessageType.MESH_RESULT == "mesh_result"

    def test_mesh_leave_in_message_type(self):
        from galaxy_gateway.protocol.aip_v3 import MessageType
        assert MessageType.MESH_LEAVE == "mesh_leave"

    def test_all_three_parseable_from_string(self):
        """MessageType('mesh_join') 等不再抛出 ValueError。"""
        from galaxy_gateway.protocol.aip_v3 import MessageType
        for wire_val in ("mesh_join", "mesh_result", "mesh_leave"):
            mt = MessageType(wire_val)
            assert mt.value == wire_val

    def test_unified_message_types_recognizes_lifecycle_types(self):
        from galaxy_gateway.protocol.aip_v3 import UnifiedMessageTypes
        for wire_val in ("mesh_join", "mesh_result", "mesh_leave"):
            assert UnifiedMessageTypes.is_valid(wire_val), (
                f"UnifiedMessageTypes.is_valid('{wire_val}') should be True"
            )


# ===========================================================================
# 2. android_bridge dispatch table 路由到专用处理器
# ===========================================================================


class TestAndroidBridgeDispatch:
    """PR-13：验证 dispatch table 路由三个 mesh 生命周期类型到专用处理器。"""

    def test_mesh_lifecycle_handlers_wired_in_bridge_source(self):
        """验证源码中 MESH_JOIN/RESULT/LEAVE 被路由到 handle_mesh_* 处理器。"""
        import ast
        import inspect
        from galaxy_gateway import android_bridge

        src = inspect.getsource(android_bridge)
        # 三个类型都应被路由
        for handler in ("handle_mesh_join", "handle_mesh_result", "handle_mesh_leave"):
            assert handler in src, (
                f"android_bridge.py 应导入并注册 {handler}"
            )

    def test_mesh_lifecycle_module_importable(self):
        from galaxy_gateway.android.handlers.mesh_lifecycle import (
            handle_mesh_join,
            handle_mesh_result,
            handle_mesh_leave,
            MESH_LIFECYCLE_HANDLER_IS_CANONICAL_PR13,
        )
        assert callable(handle_mesh_join)
        assert callable(handle_mesh_result)
        assert callable(handle_mesh_leave)
        assert "PR13" in MESH_LIFECYCLE_HANDLER_IS_CANONICAL_PR13

    def test_dispatch_map_mesh_lifecycle_types_not_generic(self):
        """bridge.dispatch_map 应将三种类型映射到专用处理器，而非 generic_forward。"""
        import ast
        import inspect
        from galaxy_gateway import android_bridge

        src = inspect.getsource(android_bridge)
        # generic_forward 不应出现在 MESH_JOIN/RESULT/LEAVE 附近的行
        lines = src.splitlines()
        for i, line in enumerate(lines):
            if "MESH_JOIN" in line or "MESH_RESULT" in line or "MESH_LEAVE" in line:
                snippet = "\n".join(lines[max(0, i - 2): i + 3])
                assert "handle_generic_forward" not in snippet, (
                    f"MESH_JOIN/RESULT/LEAVE 不应路由到 handle_generic_forward：\n{snippet}"
                )


# ===========================================================================
# 3. handle_mesh_join — 结构化 ACK + 落盘
# ===========================================================================


class TestHandleMeshJoin:
    @pytest.mark.asyncio
    async def test_basic_ack_structure(self):
        from galaxy_gateway.android.handlers.mesh_lifecycle import handle_mesh_join
        from core.mesh.android_mesh_lifecycle_store import reset_android_mesh_lifecycle_store
        reset_android_mesh_lifecycle_store()

        bridge = MagicMock()
        ws = MagicMock()
        msg = {
            "type": "mesh_join",
            "device_id": "dev-01",
            "message_id": "msg-join-001",
            "payload": {"session_id": "sess-abc"},
        }

        result = await handle_mesh_join(bridge, ws, msg)

        assert result["type"] == "mesh_join_ack"
        assert result["device_id"] == "dev-01"
        assert result["lifecycle_state"] == "joining"
        assert result["session_id"] == "sess-abc"
        assert result["correlation_id"] == "msg-join-001"

    @pytest.mark.asyncio
    async def test_session_id_auto_generated_when_absent(self):
        from galaxy_gateway.android.handlers.mesh_lifecycle import handle_mesh_join
        from core.mesh.android_mesh_lifecycle_store import reset_android_mesh_lifecycle_store
        reset_android_mesh_lifecycle_store()

        bridge = MagicMock()
        ws = MagicMock()
        msg = {"type": "mesh_join", "device_id": "dev-02"}

        result = await handle_mesh_join(bridge, ws, msg)

        assert result["session_id"], "session_id 应被自动生成"
        assert "dev-02" in result["session_id"]

    @pytest.mark.asyncio
    async def test_join_event_stored_in_lifecycle_store(self):
        from galaxy_gateway.android.handlers.mesh_lifecycle import handle_mesh_join
        from core.mesh.android_mesh_lifecycle_store import (
            reset_android_mesh_lifecycle_store,
            get_android_mesh_lifecycle_store,
            AndroidMeshSessionStatus,
        )
        reset_android_mesh_lifecycle_store()

        bridge = MagicMock()
        ws = MagicMock()
        msg = {
            "type": "mesh_join",
            "device_id": "dev-03",
            "payload": {"session_id": "sess-store-test"},
        }

        result = await handle_mesh_join(bridge, ws, msg)

        store = get_android_mesh_lifecycle_store()
        rec = store.get_session("sess-store-test")
        assert rec is not None, "join 事件应落盘至 store"
        assert rec.device_id == "dev-03"
        assert rec.status in (
            AndroidMeshSessionStatus.JOINING,
            AndroidMeshSessionStatus.ACTIVE,
        ), f"session 状态应为 JOINING 或 ACTIVE，实际：{rec.status}"
        assert rec.join_event is not None

    @pytest.mark.asyncio
    async def test_store_error_does_not_crash_handler(self):
        """store 异常时处理器仍应返回有效 ACK。"""
        from galaxy_gateway.android.handlers.mesh_lifecycle import handle_mesh_join
        import galaxy_gateway.android.handlers.mesh_lifecycle as _mod

        bridge = MagicMock()
        ws = MagicMock()
        msg = {"type": "mesh_join", "device_id": "dev-04"}

        with patch.object(_mod, "record_mesh_join", side_effect=RuntimeError("store exploded")):
            result = await handle_mesh_join(bridge, ws, msg)

        assert result["type"] == "mesh_join_ack"
        assert result["store_status"] == "store_error"


# ===========================================================================
# 4. handle_mesh_result — ACTIVE 状态 + result_count
# ===========================================================================


class TestHandleMeshResult:
    @pytest.mark.asyncio
    async def test_basic_ack_structure(self):
        from galaxy_gateway.android.handlers.mesh_lifecycle import handle_mesh_result
        from core.mesh.android_mesh_lifecycle_store import reset_android_mesh_lifecycle_store
        reset_android_mesh_lifecycle_store()

        bridge = MagicMock()
        ws = MagicMock()
        msg = {
            "type": "mesh_result",
            "device_id": "dev-01",
            "message_id": "msg-result-001",
            "payload": {"session_id": "sess-abc", "output": "done"},
        }

        result = await handle_mesh_result(bridge, ws, msg)

        assert result["type"] == "mesh_result_ack"
        assert result["device_id"] == "dev-01"
        assert result["lifecycle_state"] == "active"
        assert result["session_id"] == "sess-abc"
        assert result["correlation_id"] == "msg-result-001"

    @pytest.mark.asyncio
    async def test_session_status_becomes_active(self):
        from galaxy_gateway.android.handlers.mesh_lifecycle import handle_mesh_join, handle_mesh_result
        from core.mesh.android_mesh_lifecycle_store import (
            reset_android_mesh_lifecycle_store,
            get_android_mesh_lifecycle_store,
            AndroidMeshSessionStatus,
        )
        reset_android_mesh_lifecycle_store()

        bridge = MagicMock()
        ws = MagicMock()
        sid = "sess-result-test"

        await handle_mesh_join(bridge, ws, {
            "type": "mesh_join", "device_id": "dev-05",
            "payload": {"session_id": sid},
        })
        await handle_mesh_result(bridge, ws, {
            "type": "mesh_result", "device_id": "dev-05",
            "payload": {"session_id": sid, "output": "ok"},
        })

        store = get_android_mesh_lifecycle_store()
        rec = store.get_session(sid)
        assert rec is not None
        assert rec.status == AndroidMeshSessionStatus.ACTIVE
        assert len(rec.result_events) == 1

    @pytest.mark.asyncio
    async def test_result_count_in_ack(self):
        from galaxy_gateway.android.handlers.mesh_lifecycle import handle_mesh_result
        from core.mesh.android_mesh_lifecycle_store import reset_android_mesh_lifecycle_store
        reset_android_mesh_lifecycle_store()

        bridge = MagicMock()
        ws = MagicMock()
        sid = "sess-count-test"
        msg = {
            "type": "mesh_result",
            "device_id": "dev-06",
            "payload": {"session_id": sid},
        }

        r1 = await handle_mesh_result(bridge, ws, msg)
        r2 = await handle_mesh_result(bridge, ws, msg)

        assert r1["result_count"] == 1
        assert r2["result_count"] == 2


# ===========================================================================
# 5. handle_mesh_leave — LEFT 状态 + lifecycle_state=left
# ===========================================================================


class TestHandleMeshLeave:
    @pytest.mark.asyncio
    async def test_basic_ack_structure(self):
        from galaxy_gateway.android.handlers.mesh_lifecycle import handle_mesh_leave
        from core.mesh.android_mesh_lifecycle_store import reset_android_mesh_lifecycle_store
        reset_android_mesh_lifecycle_store()

        bridge = MagicMock()
        ws = MagicMock()
        msg = {
            "type": "mesh_leave",
            "device_id": "dev-01",
            "message_id": "msg-leave-001",
            "payload": {"session_id": "sess-abc"},
        }

        result = await handle_mesh_leave(bridge, ws, msg)

        assert result["type"] == "mesh_leave_ack"
        assert result["device_id"] == "dev-01"
        assert result["lifecycle_state"] == "left"
        assert result["session_id"] == "sess-abc"
        assert result["correlation_id"] == "msg-leave-001"

    @pytest.mark.asyncio
    async def test_session_status_becomes_left(self):
        from galaxy_gateway.android.handlers.mesh_lifecycle import (
            handle_mesh_join,
            handle_mesh_result,
            handle_mesh_leave,
        )
        from core.mesh.android_mesh_lifecycle_store import (
            reset_android_mesh_lifecycle_store,
            get_android_mesh_lifecycle_store,
            AndroidMeshSessionStatus,
        )
        reset_android_mesh_lifecycle_store()

        bridge = MagicMock()
        ws = MagicMock()
        sid = "sess-leave-test"

        await handle_mesh_join(bridge, ws, {
            "type": "mesh_join", "device_id": "dev-07",
            "payload": {"session_id": sid},
        })
        await handle_mesh_result(bridge, ws, {
            "type": "mesh_result", "device_id": "dev-07",
            "payload": {"session_id": sid},
        })
        await handle_mesh_leave(bridge, ws, {
            "type": "mesh_leave", "device_id": "dev-07",
            "payload": {"session_id": sid},
        })

        store = get_android_mesh_lifecycle_store()
        rec = store.get_session(sid)
        assert rec is not None
        assert rec.status == AndroidMeshSessionStatus.LEFT
        assert rec.leave_event is not None

    @pytest.mark.asyncio
    async def test_leave_without_prior_join_still_succeeds(self):
        """孤立 leave 事件不应导致崩溃，session 应被创建并标记为 LEFT。"""
        from galaxy_gateway.android.handlers.mesh_lifecycle import handle_mesh_leave
        from core.mesh.android_mesh_lifecycle_store import (
            reset_android_mesh_lifecycle_store,
            get_android_mesh_lifecycle_store,
            AndroidMeshSessionStatus,
        )
        reset_android_mesh_lifecycle_store()

        bridge = MagicMock()
        ws = MagicMock()
        msg = {
            "type": "mesh_leave",
            "device_id": "dev-orphan",
            "payload": {"session_id": "sess-orphan"},
        }

        result = await handle_mesh_leave(bridge, ws, msg)

        assert result["type"] == "mesh_leave_ack"
        store = get_android_mesh_lifecycle_store()
        rec = store.get_session("sess-orphan")
        assert rec is not None
        assert rec.status == AndroidMeshSessionStatus.LEFT


# ===========================================================================
# 6. AndroidMeshLifecycleStore — 存储与查询
# ===========================================================================


class TestAndroidMeshLifecycleStore:
    def setup_method(self):
        from core.mesh.android_mesh_lifecycle_store import reset_android_mesh_lifecycle_store
        reset_android_mesh_lifecycle_store()

    def test_authority_sentinel_present(self):
        from core.mesh.android_mesh_lifecycle_store import ANDROID_MESH_LIFECYCLE_STORE_IS_AUTHORITY
        assert "AUTHORITY" in ANDROID_MESH_LIFECYCLE_STORE_IS_AUTHORITY
        assert "PR-13" in ANDROID_MESH_LIFECYCLE_STORE_IS_AUTHORITY

    def test_record_join_creates_session(self):
        from core.mesh.android_mesh_lifecycle_store import (
            get_android_mesh_lifecycle_store,
            AndroidMeshSessionStatus,
        )
        store = get_android_mesh_lifecycle_store()
        store.record_join(device_id="d1", session_id="s1")

        rec = store.get_session("s1")
        assert rec is not None
        assert rec.device_id == "d1"
        assert rec.status == AndroidMeshSessionStatus.JOINING
        assert rec.join_event is not None

    def test_record_result_transitions_to_active(self):
        from core.mesh.android_mesh_lifecycle_store import (
            get_android_mesh_lifecycle_store,
            AndroidMeshSessionStatus,
        )
        store = get_android_mesh_lifecycle_store()
        store.record_join(device_id="d1", session_id="s1")
        store.record_result(device_id="d1", session_id="s1", payload={"out": "x"})

        rec = store.get_session("s1")
        assert rec.status == AndroidMeshSessionStatus.ACTIVE
        assert len(rec.result_events) == 1

    def test_record_leave_transitions_to_left(self):
        from core.mesh.android_mesh_lifecycle_store import (
            get_android_mesh_lifecycle_store,
            AndroidMeshSessionStatus,
        )
        store = get_android_mesh_lifecycle_store()
        store.record_join(device_id="d1", session_id="s1")
        store.record_result(device_id="d1", session_id="s1")
        store.record_leave(device_id="d1", session_id="s1")

        rec = store.get_session("s1")
        assert rec.status == AndroidMeshSessionStatus.LEFT
        assert rec.leave_event is not None

    def test_get_sessions_for_device(self):
        from core.mesh.android_mesh_lifecycle_store import get_android_mesh_lifecycle_store
        store = get_android_mesh_lifecycle_store()
        store.record_join(device_id="dA", session_id="sA1")
        store.record_join(device_id="dA", session_id="sA2")
        store.record_join(device_id="dB", session_id="sB1")

        sessions_a = store.get_sessions_for_device("dA")
        assert len(sessions_a) == 2
        assert all(s.device_id == "dA" for s in sessions_a)

        sessions_b = store.get_sessions_for_device("dB")
        assert len(sessions_b) == 1

    def test_get_all_active_sessions_excludes_left(self):
        from core.mesh.android_mesh_lifecycle_store import (
            get_android_mesh_lifecycle_store,
            AndroidMeshSessionStatus,
        )
        store = get_android_mesh_lifecycle_store()
        store.record_join(device_id="dC", session_id="active-s")
        store.record_result(device_id="dC", session_id="active-s")
        store.record_join(device_id="dC", session_id="left-s")
        store.record_leave(device_id="dC", session_id="left-s")

        active = store.get_all_active_sessions()
        session_ids = [s.session_id for s in active]
        assert "active-s" in session_ids
        assert "left-s" not in session_ids

    def test_session_count_and_active_count(self):
        from core.mesh.android_mesh_lifecycle_store import get_android_mesh_lifecycle_store
        store = get_android_mesh_lifecycle_store()
        store.record_join(device_id="dD", session_id="s1")
        store.record_join(device_id="dD", session_id="s2")
        store.record_leave(device_id="dD", session_id="s2")

        assert store.session_count() == 2
        assert store.active_session_count() == 1

    def test_session_id_extracted_from_payload_mesh_session_id(self):
        """payload.mesh_session_id 字段应作为 session_id 备用提取字段。"""
        from core.mesh.android_mesh_lifecycle_store import get_android_mesh_lifecycle_store
        store = get_android_mesh_lifecycle_store()
        store.record_join(
            device_id="dE",
            payload={"mesh_session_id": "from-mesh-session-id-field"},
        )
        rec = store.get_session("from-mesh-session-id-field")
        assert rec is not None

    def test_to_dict_serializable(self):
        from core.mesh.android_mesh_lifecycle_store import get_android_mesh_lifecycle_store
        store = get_android_mesh_lifecycle_store()
        store.record_join(device_id="dF", session_id="sF1")
        store.record_result(device_id="dF", session_id="sF1", payload={"r": 1})
        rec = store.get_session("sF1")
        d = rec.to_dict()
        assert d["session_id"] == "sF1"
        assert d["device_id"] == "dF"
        assert d["result_count"] == 1
        assert "status" in d


# ===========================================================================
# 7. long_tail_compat_surface — 三个 CANONICAL 目录条目
# ===========================================================================


class TestLongTailCatalogMeshLifecycle:
    """PR-13：验证 long_tail_compat_surface 正确收录三个 mesh 生命周期类型。"""

    def test_mesh_lifecycle_kind_defined(self):
        from core.long_tail_compat_surface import LongTailPathKind
        assert LongTailPathKind.MESH_LIFECYCLE == "mesh_lifecycle"

    def test_catalog_contains_mesh_join(self):
        from core.long_tail_compat_surface import (
            get_long_tail_catalog,
            LongTailTransitionStatus,
            LongTailValueTier,
        )
        catalog = {r.message_type: r for r in get_long_tail_catalog()}
        assert "mesh_join" in catalog, "mesh_join 应在目录中"
        rec = catalog["mesh_join"]
        assert rec.transition_status == LongTailTransitionStatus.CANONICAL
        assert rec.value_tier == LongTailValueTier.HIGHEST
        assert rec.is_closed_loop
        assert "mesh_lifecycle" in rec.canonical_handler

    def test_catalog_contains_mesh_result(self):
        from core.long_tail_compat_surface import (
            get_long_tail_catalog,
            LongTailTransitionStatus,
            LongTailValueTier,
        )
        catalog = {r.message_type: r for r in get_long_tail_catalog()}
        assert "mesh_result" in catalog
        rec = catalog["mesh_result"]
        assert rec.transition_status == LongTailTransitionStatus.CANONICAL
        assert rec.value_tier == LongTailValueTier.HIGHEST
        assert rec.is_closed_loop

    def test_catalog_contains_mesh_leave(self):
        from core.long_tail_compat_surface import (
            get_long_tail_catalog,
            LongTailTransitionStatus,
            LongTailValueTier,
        )
        catalog = {r.message_type: r for r in get_long_tail_catalog()}
        assert "mesh_leave" in catalog
        rec = catalog["mesh_leave"]
        assert rec.transition_status == LongTailTransitionStatus.CANONICAL
        assert rec.value_tier == LongTailValueTier.HIGHEST
        assert rec.is_closed_loop

    def test_catalog_summary_includes_mesh_lifecycle_in_canonical(self):
        from core.long_tail_compat_surface import build_catalog_summary
        summary = build_catalog_summary()
        for mt in ("mesh_join", "mesh_result", "mesh_leave"):
            assert mt in summary.canonical_message_types, (
                f"{mt} 应在 canonical_message_types 中"
            )

    def test_highest_tier_count_increased_to_seven(self):
        """最高价值流数量应从原来的 4 增加至 7（加入三个 mesh 生命周期类型）。"""
        from core.long_tail_compat_surface import build_catalog_summary, LongTailValueTier
        summary = build_catalog_summary()
        highest = summary.by_tier.get(LongTailValueTier.HIGHEST.value, 0)
        assert highest == 7, f"HIGHEST 级别条目应为 7，实际：{highest}"


# ===========================================================================
# 8. /api/v1/mesh/android-lifecycle 端点
# ===========================================================================


class TestAndroidLifecycleEndpoint:
    @pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
    def test_endpoint_returns_valid_structure(self):
        """直接调用 build_android_lifecycle_truth 验证输出结构。"""
        from core.mesh.android_mesh_lifecycle_store import (
            reset_android_mesh_lifecycle_store,
            build_android_lifecycle_truth,
            record_mesh_join,
            record_mesh_result,
        )
        reset_android_mesh_lifecycle_store()
        record_mesh_join("dev-truth", session_id="sess-t1")
        record_mesh_result("dev-truth", session_id="sess-t1")

        truth = build_android_lifecycle_truth()

        assert "active_session_count" in truth
        assert "total_session_count" in truth
        assert "active_sessions" in truth
        assert truth["active_session_count"] == 1
        assert isinstance(truth["active_sessions"], list)
        assert truth["active_sessions"][0]["session_id"] == "sess-t1"

    @pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
    def test_endpoint_source_key_present(self):
        from core.mesh.android_mesh_lifecycle_store import (
            reset_android_mesh_lifecycle_store,
            build_android_lifecycle_truth,
        )
        reset_android_mesh_lifecycle_store()
        truth = build_android_lifecycle_truth()
        assert "_source" in truth
        assert "android_mesh_lifecycle_store" in truth["_source"]

    @pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
    def test_endpoint_registered_in_projection(self):
        """验证 /api/v1/mesh/android-lifecycle 已在 projection.py 中注册。"""
        import inspect
        from core.routes import projection

        src = inspect.getsource(projection)
        assert "android-lifecycle" in src, (
            "/api/v1/mesh/android-lifecycle 端点应在 projection.py 中注册"
        )


# ===========================================================================
# 9. session_id 提取优先级
# ===========================================================================


class TestSessionIdExtraction:
    def setup_method(self):
        from core.mesh.android_mesh_lifecycle_store import reset_android_mesh_lifecycle_store
        reset_android_mesh_lifecycle_store()

    @pytest.mark.asyncio
    async def test_explicit_payload_session_id_preferred(self):
        from galaxy_gateway.android.handlers.mesh_lifecycle import handle_mesh_join

        bridge = MagicMock()
        ws = MagicMock()
        msg = {
            "type": "mesh_join",
            "device_id": "dX",
            "session_id": "outer-sid",
            "payload": {"session_id": "inner-sid"},
        }
        result = await handle_mesh_join(bridge, ws, msg)
        # payload.session_id 优先于顶层 session_id
        assert result["session_id"] == "inner-sid"

    @pytest.mark.asyncio
    async def test_payload_mesh_session_id_fallback(self):
        from galaxy_gateway.android.handlers.mesh_lifecycle import handle_mesh_join

        bridge = MagicMock()
        ws = MagicMock()
        msg = {
            "type": "mesh_join",
            "device_id": "dY",
            "payload": {"mesh_session_id": "mesh-sid-fallback"},
        }
        result = await handle_mesh_join(bridge, ws, msg)
        assert result["session_id"] == "mesh-sid-fallback"


# ===========================================================================
# 10. 降级安全：store 异常时处理器仍返回有效 ACK
# ===========================================================================


class TestDegradationSafety:
    @pytest.mark.asyncio
    async def test_mesh_result_store_error_non_fatal(self):
        from galaxy_gateway.android.handlers.mesh_lifecycle import handle_mesh_result
        import galaxy_gateway.android.handlers.mesh_lifecycle as _mod

        bridge = MagicMock()
        ws = MagicMock()
        msg = {"type": "mesh_result", "device_id": "dErr"}

        with patch.object(_mod, "record_mesh_result", side_effect=RuntimeError("store error")):
            result = await handle_mesh_result(bridge, ws, msg)

        assert result["type"] == "mesh_result_ack"
        assert result["store_status"] == "store_error"

    @pytest.mark.asyncio
    async def test_mesh_leave_store_error_non_fatal(self):
        from galaxy_gateway.android.handlers.mesh_lifecycle import handle_mesh_leave
        import galaxy_gateway.android.handlers.mesh_lifecycle as _mod

        bridge = MagicMock()
        ws = MagicMock()
        msg = {"type": "mesh_leave", "device_id": "dErr2"}

        with patch.object(_mod, "record_mesh_leave", side_effect=RuntimeError("store error")):
            result = await handle_mesh_leave(bridge, ws, msg)

        assert result["type"] == "mesh_leave_ack"
        assert result["store_status"] == "store_error"


# ===========================================================================
# 11. build_android_lifecycle_truth 输出完整真值快照
# ===========================================================================


class TestBuildAndroidLifecycleTruth:
    def setup_method(self):
        from core.mesh.android_mesh_lifecycle_store import reset_android_mesh_lifecycle_store
        reset_android_mesh_lifecycle_store()

    def test_empty_store_returns_valid_structure(self):
        from core.mesh.android_mesh_lifecycle_store import build_android_lifecycle_truth
        truth = build_android_lifecycle_truth()

        assert truth["active_session_count"] == 0
        assert truth["total_session_count"] == 0
        assert truth["active_sessions"] == []
        assert "_timestamp" in truth

    def test_active_sessions_included(self):
        from core.mesh.android_mesh_lifecycle_store import (
            build_android_lifecycle_truth,
            record_mesh_join,
        )
        record_mesh_join("d1", session_id="s1")

        truth = build_android_lifecycle_truth()
        assert truth["active_session_count"] == 1
        assert len(truth["active_sessions"]) == 1
        assert truth["active_sessions"][0]["session_id"] == "s1"

    def test_left_sessions_excluded_from_active(self):
        from core.mesh.android_mesh_lifecycle_store import (
            build_android_lifecycle_truth,
            record_mesh_join,
            record_mesh_leave,
        )
        record_mesh_join("d1", session_id="s-active")
        record_mesh_join("d1", session_id="s-left")
        record_mesh_leave("d1", session_id="s-left")

        truth = build_android_lifecycle_truth()
        assert truth["active_session_count"] == 1
        assert truth["total_session_count"] == 2
        active_ids = [s["session_id"] for s in truth["active_sessions"]]
        assert "s-active" in active_ids
        assert "s-left" not in active_ids


# ===========================================================================
# 12. 完整生命周期序列：join → result → leave 状态流转
# ===========================================================================


class TestFullLifecycleSequence:
    def setup_method(self):
        from core.mesh.android_mesh_lifecycle_store import reset_android_mesh_lifecycle_store
        reset_android_mesh_lifecycle_store()

    @pytest.mark.asyncio
    async def test_full_join_result_leave_sequence(self):
        from galaxy_gateway.android.handlers.mesh_lifecycle import (
            handle_mesh_join,
            handle_mesh_result,
            handle_mesh_leave,
        )
        from core.mesh.android_mesh_lifecycle_store import (
            get_android_mesh_lifecycle_store,
            AndroidMeshSessionStatus,
        )

        bridge = MagicMock()
        ws = MagicMock()
        sid = "full-seq-session"

        # 阶段 1：join
        r_join = await handle_mesh_join(bridge, ws, {
            "type": "mesh_join",
            "device_id": "full-dev",
            "payload": {"session_id": sid},
        })
        assert r_join["lifecycle_state"] == "joining"

        store = get_android_mesh_lifecycle_store()
        rec = store.get_session(sid)
        assert rec.status in (
            AndroidMeshSessionStatus.JOINING,
            AndroidMeshSessionStatus.ACTIVE,
        )

        # 阶段 2：result（两次）
        await handle_mesh_result(bridge, ws, {
            "type": "mesh_result",
            "device_id": "full-dev",
            "payload": {"session_id": sid, "subtask": "A", "output": "x"},
        })
        r_result2 = await handle_mesh_result(bridge, ws, {
            "type": "mesh_result",
            "device_id": "full-dev",
            "payload": {"session_id": sid, "subtask": "B", "output": "y"},
        })
        assert r_result2["result_count"] == 2

        rec = store.get_session(sid)
        assert rec.status == AndroidMeshSessionStatus.ACTIVE
        assert len(rec.result_events) == 2

        # 阶段 3：leave
        r_leave = await handle_mesh_leave(bridge, ws, {
            "type": "mesh_leave",
            "device_id": "full-dev",
            "payload": {"session_id": sid},
        })
        assert r_leave["lifecycle_state"] == "left"

        rec = store.get_session(sid)
        assert rec.status == AndroidMeshSessionStatus.LEFT
        assert rec.leave_event is not None
        assert rec.join_event is not None
        assert len(rec.result_events) == 2

    @pytest.mark.asyncio
    async def test_multiple_devices_independent_sessions(self):
        from galaxy_gateway.android.handlers.mesh_lifecycle import (
            handle_mesh_join,
            handle_mesh_leave,
        )
        from core.mesh.android_mesh_lifecycle_store import (
            get_android_mesh_lifecycle_store,
            AndroidMeshSessionStatus,
        )

        bridge = MagicMock()
        ws = MagicMock()

        # 两台设备各自独立的 session
        await handle_mesh_join(bridge, ws, {
            "type": "mesh_join", "device_id": "phone-1",
            "payload": {"session_id": "sess-phone-1"},
        })
        await handle_mesh_join(bridge, ws, {
            "type": "mesh_join", "device_id": "tablet-2",
            "payload": {"session_id": "sess-tablet-2"},
        })

        store = get_android_mesh_lifecycle_store()

        # 设备 1 离开
        await handle_mesh_leave(bridge, ws, {
            "type": "mesh_leave", "device_id": "phone-1",
            "payload": {"session_id": "sess-phone-1"},
        })

        rec1 = store.get_session("sess-phone-1")
        rec2 = store.get_session("sess-tablet-2")

        assert rec1.status == AndroidMeshSessionStatus.LEFT
        assert rec2.status in (
            AndroidMeshSessionStatus.JOINING,
            AndroidMeshSessionStatus.ACTIVE,
        ), "设备 2 的 session 不应受设备 1 离开的影响"
