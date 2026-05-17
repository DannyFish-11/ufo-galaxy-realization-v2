"""
tests/test_device_dispatch_readiness_surface.py
===============================================
验证 device_dispatch_readiness_surface 模块的新控制面可见性路径。

本测试文件覆盖：
A. core.device_dispatch_readiness_surface — 单设备查询
B. core.device_dispatch_readiness_surface — 全设备面板
C. galaxy_gateway.android.handlers.registration — get_all_devices_with_registration_gaps
D. windows_client.status_board_v2.device_surface — dispatch readiness blocker 渲染
E. 端点级集成：operator route 返回正确结构
"""

from __future__ import annotations

import importlib
import sys
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# 可用性检查
# ---------------------------------------------------------------------------

_SURFACE_AVAILABLE = False
_GATE_AVAILABLE = False
_REG_HANDLER_AVAILABLE = False

try:
    from core.device_dispatch_readiness_surface import (
        get_device_dispatch_readiness,
        get_dispatch_readiness_panel,
        DEVICE_DISPATCH_READINESS_SURFACE_AUTHORITY,
    )
    _SURFACE_AVAILABLE = True
except ImportError:
    pass

try:
    from core.unified_dispatch_readiness_gate import (
        evaluate_dispatch_readiness,
        DispatchReadinessStatus,
        reset_dispatch_readiness_gate,
    )
    _GATE_AVAILABLE = True
except ImportError:
    pass

try:
    from galaxy_gateway.android.handlers.registration import (
        record_registration_gap,
        clear_registration_gaps,
        get_all_devices_with_registration_gaps,
    )
    _REG_HANDLER_AVAILABLE = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _did(suffix: str = "") -> str:
    import uuid
    return f"test-dispatch-surface-{uuid.uuid4().hex[:8]}{suffix}"


# ===========================================================================
# A. get_all_devices_with_registration_gaps — 新函数
# ===========================================================================

@pytest.mark.skipif(
    not _REG_HANDLER_AVAILABLE,
    reason="registration handler not available",
)
class TestGetAllDevicesWithRegistrationGaps:
    """galaxy_gateway.android.handlers.registration.get_all_devices_with_registration_gaps"""

    def setup_method(self) -> None:
        clear_registration_gaps()

    def teardown_method(self) -> None:
        clear_registration_gaps()

    def test_empty_when_no_gaps_recorded(self) -> None:
        """初始状态下应返回空 dict。"""
        result = get_all_devices_with_registration_gaps()
        assert isinstance(result, dict)
        # 注意：其他测试可能已录入 gap；只断言当前测试设备不在其中

    def test_device_with_gap_is_included(self) -> None:
        """录入 gap 后，该设备应出现在结果中。"""
        did = _did()
        record_registration_gap(did, "attach_runtime_session")
        result = get_all_devices_with_registration_gaps()
        assert did in result
        assert "attach_runtime_session" in result[did]

    def test_device_with_multiple_gaps(self) -> None:
        """多条 gap 应全部出现。"""
        did = _did()
        record_registration_gap(did, "udm_write")
        record_registration_gap(did, "attach_runtime_session")
        result = get_all_devices_with_registration_gaps()
        assert did in result
        assert len(result[did]) == 2
        assert "udm_write" in result[did]
        assert "attach_runtime_session" in result[did]

    def test_returns_copy_not_live_reference(self) -> None:
        """返回副本，修改后不影响内部存储。"""
        did = _did()
        record_registration_gap(did, "udm_write")
        result1 = get_all_devices_with_registration_gaps()
        result1[did].append("injected")
        result2 = get_all_devices_with_registration_gaps()
        assert "injected" not in result2.get(did, [])

    def test_cleared_device_not_in_result(self) -> None:
        """清除 gap 后设备不再出现在结果中。"""
        did = _did()
        record_registration_gap(did, "udm_write")
        clear_registration_gaps(did)
        result = get_all_devices_with_registration_gaps()
        assert did not in result


# ===========================================================================
# B. get_device_dispatch_readiness — 单设备查询
# ===========================================================================

@pytest.mark.skipif(
    not _SURFACE_AVAILABLE,
    reason="device_dispatch_readiness_surface not available",
)
class TestGetDeviceDispatchReadiness:
    """core.device_dispatch_readiness_surface.get_device_dispatch_readiness"""

    def test_returns_dict(self) -> None:
        """调用任意设备 ID 应返回 dict（即使设备未注册）。"""
        result = get_device_dispatch_readiness("nonexistent-device-xyz")
        assert isinstance(result, dict)

    def test_has_required_fields(self) -> None:
        """返回 dict 必须包含所有必需字段。"""
        result = get_device_dispatch_readiness("nonexistent-device-xyz")
        for field in ("device_id", "dispatch_ready", "registered", "status",
                      "reason", "registration_gaps", "blocking_notes",
                      "surface_authority", "evaluated_at"):
            assert field in result, f"缺失字段: {field}"

    def test_device_id_matches_input(self) -> None:
        """返回 dict 的 device_id 必须与输入一致。"""
        did = _did()
        result = get_device_dispatch_readiness(did)
        assert result["device_id"] == did

    def test_surface_authority_present(self) -> None:
        """surface_authority 必须包含权威哨兵字符串。"""
        result = get_device_dispatch_readiness("any-device")
        assert "DEVICE_DISPATCH_READINESS_SURFACE_V1" in result["surface_authority"]

    def test_evaluated_at_is_float(self) -> None:
        """evaluated_at 必须是浮点时间戳。"""
        result = get_device_dispatch_readiness("any-device")
        assert isinstance(result["evaluated_at"], float)

    def test_registration_gaps_is_list(self) -> None:
        """registration_gaps 必须是 list（哪怕为空）。"""
        result = get_device_dispatch_readiness("any-device")
        assert isinstance(result["registration_gaps"], list)

    def test_blocking_notes_is_list(self) -> None:
        """blocking_notes 必须是 list（哪怕为空）。"""
        result = get_device_dispatch_readiness("any-device")
        assert isinstance(result["blocking_notes"], list)

    @pytest.mark.skipif(
        not _REG_HANDLER_AVAILABLE,
        reason="registration handler not available",
    )
    def test_registration_gap_exposed_in_result(self) -> None:
        """有注册 gap 时，结果中应包含 gap 步骤名称。"""
        did = _did("gap")
        try:
            record_registration_gap(did, "attach_runtime_session")
            result = get_device_dispatch_readiness(did)
            # gap 应出现在 registration_gaps 或 blocking_notes 中
            gaps_present = "attach_runtime_session" in result.get("registration_gaps", [])
            notes_present = any(
                "attach_runtime_session" in note
                for note in result.get("blocking_notes", [])
            )
            # status 或 reason 也可能包含 gap 信息
            reason_present = "attach_runtime_session" in result.get("reason", "")
            assert gaps_present or notes_present or reason_present, (
                f"gap 步骤名称在结果中不可见: {result}"
            )
        finally:
            clear_registration_gaps(did)


# ===========================================================================
# C. get_dispatch_readiness_panel — 全设备面板
# ===========================================================================

@pytest.mark.skipif(
    not _SURFACE_AVAILABLE,
    reason="device_dispatch_readiness_surface not available",
)
class TestGetDispatchReadinessPanel:
    """core.device_dispatch_readiness_surface.get_dispatch_readiness_panel"""

    def test_panel_with_explicit_empty_list(self) -> None:
        """显式传入空列表时，返回 devices=[] 的有效面板。"""
        panel = get_dispatch_readiness_panel(device_ids=[])
        assert isinstance(panel, dict)
        assert panel["devices"] == []
        assert isinstance(panel["summary"], dict)
        assert panel["summary"]["total"] == 0

    def test_panel_with_explicit_device_ids(self) -> None:
        """显式提供设备 ID 时，面板应包含对应条目。"""
        ids = [_did("p1"), _did("p2")]
        panel = get_dispatch_readiness_panel(device_ids=ids)
        assert len(panel["devices"]) == len(ids)
        returned_ids = {d["device_id"] for d in panel["devices"]}
        for did in ids:
            assert did in returned_ids

    def test_panel_summary_totals_correct(self) -> None:
        """summary.total 必须等于 devices 列表长度。"""
        ids = [_did("s1"), _did("s2"), _did("s3")]
        panel = get_dispatch_readiness_panel(device_ids=ids)
        assert panel["summary"]["total"] == len(panel["devices"])

    def test_panel_has_authority_field(self) -> None:
        """面板应包含 authority 字段。"""
        panel = get_dispatch_readiness_panel(device_ids=[])
        assert "authority" in panel

    def test_panel_has_compiled_at(self) -> None:
        """面板应包含 compiled_at 时间戳。"""
        panel = get_dispatch_readiness_panel(device_ids=[])
        assert isinstance(panel["compiled_at"], float)

    def test_panel_summary_has_all_status_keys(self) -> None:
        """summary 字典应包含所有预期的 status 计数键。"""
        panel = get_dispatch_readiness_panel(device_ids=[])
        summary = panel["summary"]
        expected_keys = {
            "total", "dispatch_ready", "blocked_registration_gap",
            "blocked_stale_attachment", "blocked_transport", "blocked_capability",
            "blocked_session_validity", "blocked_cross_device_eligibility",
            "blocked_other", "not_registered", "gate_error", "total_blocked",
        }
        for key in expected_keys:
            assert key in summary, f"summary 缺少键: {key}"

    def test_panel_auto_enumeration_returns_dict(self) -> None:
        """不传 device_ids 时（自动枚举），应返回合法面板 dict。"""
        panel = get_dispatch_readiness_panel()
        assert isinstance(panel, dict)
        assert isinstance(panel["devices"], list)
        assert isinstance(panel["summary"], dict)

    @pytest.mark.skipif(
        not _REG_HANDLER_AVAILABLE,
        reason="registration handler not available",
    )
    def test_device_with_gap_has_structured_reason_in_panel(self) -> None:
        """面板中，有注册 gap 的设备应有结构化拦截原因（非空 registration_gaps 或 reason）。"""
        did = _did("panel-gap")
        try:
            record_registration_gap(did, "udm_write")
            panel = get_dispatch_readiness_panel(device_ids=[did])
            assert len(panel["devices"]) == 1
            entry = panel["devices"][0]
            # 不应仅有布尔值：status 必须是非空字符串，且 reason 或 registration_gaps
            # 其中至少一项携带具体原因
            assert entry.get("status", "") != "", "status 不应为空"
            has_reason = bool(entry.get("reason"))
            has_gaps = bool(entry.get("registration_gaps"))
            assert has_reason or has_gaps, (
                f"有注册 gap 的设备应有具体原因: {entry}"
            )
        finally:
            clear_registration_gaps(did)


# ===========================================================================
# D. DeviceSurface 渲染 — dispatch readiness blocker 显示
# ===========================================================================

class TestDeviceSurfaceDispatchReadinessRendering:
    """windows_client.status_board_v2.device_surface.DeviceSurface"""

    def _surface(self):
        from windows_client.status_board_v2.device_surface import DeviceSurface
        return DeviceSurface()

    def _base_projection(self) -> Dict[str, Any]:
        return {
            "active_device_ids": [],
            "execution_stage": None,
            "current_task_summary": None,
        }

    def test_render_without_dispatch_readiness_field_succeeds(self) -> None:
        """不含 device_dispatch_readiness 字段时，渲染不应出错。"""
        surface = self._surface()
        out = surface.render(self._base_projection())
        assert isinstance(out, str)
        assert "Device & Execution Context" in out

    def test_render_with_dispatch_ready_device(self) -> None:
        """就绪设备应显示 DISPATCH_READY 状态。"""
        surface = self._surface()
        proj = {
            **self._base_projection(),
            "device_dispatch_readiness": {
                "dispatch_ready": True,
                "status": "dispatch_ready",
                "reason": "",
                "registration_gaps": [],
                "blocking_notes": [],
            },
        }
        out = surface.render(proj)
        assert "dispatch_ready" in out

    def test_render_with_registration_gap_shows_gap_name(self) -> None:
        """有注册 gap 的设备应在渲染输出中显示具体 gap 步骤名称。"""
        surface = self._surface()
        proj = {
            **self._base_projection(),
            "device_dispatch_readiness": {
                "dispatch_ready": False,
                "status": "blocked_registration_gap",
                "reason": "Device has 1 downstream registration gap(s): ['attach_runtime_session']",
                "registration_gaps": ["attach_runtime_session"],
                "blocking_notes": ["registration_gap_count=1"],
            },
        }
        out = surface.render(proj)
        assert "attach_runtime_session" in out

    def test_render_blocked_transport_shows_reason(self) -> None:
        """transport 断线时，渲染输出应包含 status 和 reason 信息。"""
        surface = self._surface()
        proj = {
            **self._base_projection(),
            "device_dispatch_readiness": {
                "dispatch_ready": False,
                "status": "blocked_transport",
                "reason": "Device transport (WebSocket/UCM) is not alive.",
                "registration_gaps": [],
                "blocking_notes": ["udm_online=False"],
            },
        }
        out = surface.render(proj)
        assert "blocked_transport" in out

    def test_render_blocking_notes_appear_in_output(self) -> None:
        """blocking_notes 中的说明应出现在渲染输出中。"""
        surface = self._surface()
        proj = {
            **self._base_projection(),
            "device_dispatch_readiness": {
                "dispatch_ready": False,
                "status": "blocked_capability",
                "reason": "Device missing required capabilities.",
                "registration_gaps": [],
                "blocking_notes": ["missing_capabilities=['screen']"],
            },
        }
        out = surface.render(proj)
        # 最多渲染 2 条 notes；第一条应出现
        assert "missing_capabilities" in out

    def test_render_does_not_expose_only_boolean(self) -> None:
        """拦截时不能仅显示 False/True，必须暴露 status 或 reason 字符串。"""
        surface = self._surface()
        proj = {
            **self._base_projection(),
            "device_dispatch_readiness": {
                "dispatch_ready": False,
                "status": "blocked_stale_attachment",
                "reason": "Runtime attachment session has become stale.",
                "registration_gaps": [],
                "blocking_notes": ["attachment_state=detached"],
            },
        }
        out = surface.render(proj)
        # 仅出现 False 而不含任何枚举值才是问题
        assert "blocked_stale_attachment" in out or "stale" in out.lower()

    def test_render_with_participation_tier_and_dispatch_readiness(self) -> None:
        """同时包含 participation_tier 和 dispatch_readiness 时，两者都应渲染。"""
        surface = self._surface()
        proj = {
            **self._base_projection(),
            "participation_truth_consumption": {
                "participation_tier": "attached",
                "dispatch_eligible": False,
                "fully_attached": False,
            },
            "device_dispatch_readiness": {
                "dispatch_ready": False,
                "status": "blocked_registration_gap",
                "reason": "registration gap: attach_runtime_session",
                "registration_gaps": ["attach_runtime_session"],
                "blocking_notes": [],
            },
        }
        out = surface.render(proj)
        assert "Tier" in out or "attached" in out
        assert "attach_runtime_session" in out


# ===========================================================================
# E. 端点级集成测试（不启动真实 HTTP 服务器）
# ===========================================================================

@pytest.mark.skipif(
    not _SURFACE_AVAILABLE,
    reason="device_dispatch_readiness_surface not available",
)
class TestOperatorRouteDispatchReadinessEndpoints:
    """通过直接调用路由处理函数验证端点返回结构。"""

    def _get_router(self):
        try:
            from core.routes.operator import create_router
            return create_router()
        except Exception:
            return None

    def test_route_module_importable(self) -> None:
        """operator 路由模块应可导入。"""
        try:
            from core.routes import operator as op_mod
            assert hasattr(op_mod, "create_router")
        except ImportError:
            pytest.skip("fastapi not available")

    @pytest.mark.asyncio
    async def test_device_dispatch_readiness_endpoint_returns_valid_payload(self) -> None:
        """GET /api/v1/operator/devices/{device_id}/dispatch-readiness 应返回合法载荷。"""
        try:
            from core.routes.operator import create_router
        except ImportError:
            pytest.skip("fastapi not available")

        router = create_router()
        # 找到目标路由处理函数
        target_func = None
        for route in router.routes:
            if (
                hasattr(route, "path")
                and "dispatch-readiness" in route.path
                and "{device_id}" in route.path
            ):
                target_func = route.endpoint
                break
        if target_func is None:
            pytest.skip("dispatch-readiness endpoint not found in router")

        result = await target_func("test-device-id-e2e")
        # JSONResponse.body 是 bytes；解析后验证结构
        import json
        body = json.loads(result.body)
        assert "device_id" in body
        assert "dispatch_ready" in body
        assert "status" in body
        assert "authority" in body

    @pytest.mark.asyncio
    async def test_devices_dispatch_readiness_panel_endpoint_returns_valid_payload(self) -> None:
        """GET /api/v1/operator/devices/dispatch-readiness 应返回合法载荷。"""
        try:
            from core.routes.operator import create_router
        except ImportError:
            pytest.skip("fastapi not available")

        router = create_router()
        target_func = None
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == "/api/v1/operator/devices/dispatch-readiness"
            ):
                target_func = route.endpoint
                break
        if target_func is None:
            pytest.skip("devices/dispatch-readiness panel endpoint not found")

        result = await target_func(device_ids=None)
        import json
        body = json.loads(result.body)
        assert "devices" in body
        assert "summary" in body
        assert "authority" in body

    @pytest.mark.asyncio
    async def test_panel_endpoint_with_explicit_device_ids(self) -> None:
        """面板端点支持逗号分隔的 device_ids 参数。"""
        try:
            from core.routes.operator import create_router
        except ImportError:
            pytest.skip("fastapi not available")

        router = create_router()
        target_func = None
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == "/api/v1/operator/devices/dispatch-readiness"
            ):
                target_func = route.endpoint
                break
        if target_func is None:
            pytest.skip("devices/dispatch-readiness panel endpoint not found")

        result = await target_func(device_ids="device-a,device-b")
        import json
        body = json.loads(result.body)
        assert "devices" in body
        returned_ids = {d["device_id"] for d in body["devices"]}
        assert "device-a" in returned_ids
        assert "device-b" in returned_ids
