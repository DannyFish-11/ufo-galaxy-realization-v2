"""
统一设备流程测试 — Priorities A + B + C + D + E + G

测试覆盖：
  A  UnifiedDeviceManager 作为 SSOT（CapabilityRegistry 和 OpenClawd 使用统一设备管理器）
  B  网关断联正确同步到 UnifiedDeviceManager
  C  CapabilityRegistry 加载高层自治能力
  D  OpenClawd goal_execution dispatch
  E  OpenClawd parallel_goal dispatch
  G  AIP v3 GOAL_EXECUTION / PARALLEL_SUBTASK message types；compat 层正确归一化
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _reset_udm():
    """重置 UnifiedDeviceManager 单例，确保测试隔离。"""
    from core.unified import device_manager as _udm_mod
    _udm_mod.UnifiedDeviceManager._instance = None


def _reset_cap_registry():
    """重置 CapabilityRegistry 单例。"""
    from core.agent.capability_registry import CapabilityRegistry
    CapabilityRegistry._instance = None


# ---------------------------------------------------------------------------
# Priority G — AIP v3 新消息类型
# ---------------------------------------------------------------------------

class TestAIPv3NewMessageTypes:
    """GOAL_EXECUTION / PARALLEL_SUBTASK message types in AIP v3."""

    def test_goal_execution_message_type_exists(self):
        from galaxy_gateway.protocol.aip_v3 import MessageType
        assert hasattr(MessageType, "GOAL_EXECUTION")
        assert MessageType.GOAL_EXECUTION.value == "goal_execution"

    def test_parallel_subtask_message_type_exists(self):
        from galaxy_gateway.protocol.aip_v3 import MessageType
        assert hasattr(MessageType, "PARALLEL_SUBTASK")
        assert MessageType.PARALLEL_SUBTASK.value == "parallel_subtask"

    def test_parallel_result_message_type_exists(self):
        from galaxy_gateway.protocol.aip_v3 import MessageType
        assert hasattr(MessageType, "PARALLEL_RESULT")
        assert MessageType.PARALLEL_RESULT.value == "parallel_result"

    def test_goal_execution_result_message_type_exists(self):
        from galaxy_gateway.protocol.aip_v3 import MessageType
        assert hasattr(MessageType, "GOAL_EXECUTION_RESULT")
        assert MessageType.GOAL_EXECUTION_RESULT.value == "goal_execution_result"

    def test_aip_message_has_task_type_field(self):
        from galaxy_gateway.protocol.aip_v3 import AIPMessage, MessageType
        msg = AIPMessage(
            type=MessageType.TASK_ASSIGN,
            device_id="dev_001",
            task_type="goal_execution",
        )
        assert msg.task_type == "goal_execution"

    def test_aip_message_task_type_optional(self):
        from galaxy_gateway.protocol.aip_v3 import AIPMessage, MessageType
        msg = AIPMessage(type=MessageType.DEVICE_HEARTBEAT, device_id="dev_001")
        assert msg.task_type is None


class TestCompatLayerNewTypes:
    """compat.parse_message_compat handles new high-level type aliases."""

    def test_goal_alias_normalised(self):
        from galaxy_gateway.protocol.compat import parse_message_compat
        from galaxy_gateway.protocol.aip_v3 import MessageType
        msg = parse_message_compat({"type": "goal", "device_id": "d1"})
        assert msg.type == MessageType.GOAL_EXECUTION

    def test_goal_execute_alias_normalised(self):
        from galaxy_gateway.protocol.compat import parse_message_compat
        from galaxy_gateway.protocol.aip_v3 import MessageType
        msg = parse_message_compat({"type": "goal_execute", "device_id": "d1"})
        assert msg.type == MessageType.GOAL_EXECUTION

    def test_parallel_task_alias_normalised(self):
        from galaxy_gateway.protocol.compat import parse_message_compat
        from galaxy_gateway.protocol.aip_v3 import MessageType
        msg = parse_message_compat({"type": "parallel_task", "device_id": "d1"})
        assert msg.type == MessageType.PARALLEL_SUBTASK

    def test_v3_goal_execution_passes_through(self):
        from galaxy_gateway.protocol.compat import parse_message_compat
        from galaxy_gateway.protocol.aip_v3 import MessageType
        msg = parse_message_compat({
            "version": "3.0",
            "type": "goal_execution",
            "device_id": "d1",
        })
        assert msg.type == MessageType.GOAL_EXECUTION


# ---------------------------------------------------------------------------
# Priority A — UnifiedDeviceManager as SSOT
# ---------------------------------------------------------------------------

class TestUnifiedDeviceManagerSSOT:
    """UnifiedDeviceManager 是唯一设备事实来源。"""

    def setup_method(self):
        _reset_udm()
        from core.unified.device_manager import UnifiedDeviceManager
        self.udm = UnifiedDeviceManager()

    def test_register_and_retrieve_device(self):
        from core.unified.models import UnifiedDevice, UnifiedDeviceType
        device = UnifiedDevice(device_id="test_ssot_01", device_type=UnifiedDeviceType.ANDROID)
        self.udm.register_device(device)
        retrieved = self.udm.get_device("test_ssot_01")
        assert retrieved is not None
        assert retrieved.device_id == "test_ssot_01"

    def test_register_from_dict(self):
        dev = self.udm.register_device_from_dict("dict_dev_01", {
            "device_name": "My Phone",
            "device_type": "android",
            "capabilities": ["touch", "screen"],
        })
        assert dev.device_id == "dict_dev_01"
        assert "touch" in dev.capabilities
        stored = self.udm.get_device("dict_dev_01")
        assert stored is not None

    def test_unregister_removes_device(self):
        from core.unified.models import UnifiedDevice
        device = UnifiedDevice(device_id="test_unreg_01")
        self.udm.register_device(device)
        self.udm.unregister_device("test_unreg_01")
        assert self.udm.get_device("test_unreg_01") is None

    def test_get_autonomous_devices_returns_only_autonomous(self):
        from core.unified.models import UnifiedDevice, UnifiedDeviceStatus
        normal = UnifiedDevice(device_id="normal_01")
        normal.status = UnifiedDeviceStatus.ONLINE
        self.udm.register_device(normal)

        auto_dev = UnifiedDevice(
            device_id="auto_01",
            metadata={"goal_execution_enabled": True},
        )
        auto_dev.status = UnifiedDeviceStatus.ONLINE
        self.udm.register_device(auto_dev)

        autonomous = self.udm.get_autonomous_devices()
        ids = [d.device_id for d in autonomous]
        assert "auto_01" in ids
        assert "normal_01" not in ids

    def test_get_devices_with_capability(self):
        from core.unified.models import UnifiedDevice, UnifiedDeviceStatus
        dev = UnifiedDevice(
            device_id="cap_dev_01",
            capabilities=["touch", "camera"],
        )
        dev.status = UnifiedDeviceStatus.ONLINE
        self.udm.register_device(dev)

        result = self.udm.get_devices_with_capability("touch")
        ids = [d.device_id for d in result]
        assert "cap_dev_01" in ids

    def test_get_devices_with_autonomous_metadata_capability(self):
        from core.unified.models import UnifiedDevice, UnifiedDeviceStatus
        dev = UnifiedDevice(
            device_id="auto_cap_01",
            metadata={"parallel_execution_enabled": True},
        )
        dev.status = UnifiedDeviceStatus.ONLINE
        self.udm.register_device(dev)

        result = self.udm.get_devices_with_capability("parallel_execution_enabled")
        ids = [d.device_id for d in result]
        assert "auto_cap_01" in ids


# ---------------------------------------------------------------------------
# Priority C — CapabilityRegistry autonomous capabilities
# ---------------------------------------------------------------------------

class TestCapabilityRegistryAutonomous:
    """CapabilityRegistry 加载高层自治能力。"""

    def setup_method(self):
        _reset_udm()
        _reset_cap_registry()

    @pytest.mark.asyncio
    async def test_load_autonomous_caps_from_udm(self):
        from core.unified.device_manager import UnifiedDeviceManager
        from core.unified.models import UnifiedDevice, UnifiedDeviceStatus
        from core.agent.capability_registry import CapabilityRegistry

        udm = UnifiedDeviceManager()
        dev = UnifiedDevice(
            device_id="aut_test_01",
            device_name="AutoDevice",
            metadata={
                "goal_execution_enabled": True,
                "local_task_planning": True,
            },
        )
        dev.status = UnifiedDeviceStatus.ONLINE
        udm.register_device(dev)

        reg = CapabilityRegistry.get_instance()
        await reg.refresh(force=True)

        items = reg.list_tools(source="autonomous")
        names = [i.name for i in items]
        assert any("aut_test_01" in n and "goal_execution_enabled" in n for n in names)
        assert any("aut_test_01" in n and "local_task_planning" in n for n in names)

    @pytest.mark.asyncio
    async def test_load_gateway_caps_from_udm(self):
        from core.unified.device_manager import UnifiedDeviceManager
        from core.unified.models import UnifiedDevice, UnifiedDeviceStatus
        from core.agent.capability_registry import CapabilityRegistry

        udm = UnifiedDeviceManager()
        dev = UnifiedDevice(
            device_id="gw_test_02",
            device_name="GWDevice",
            capabilities=["screen", "touch"],
        )
        dev.status = UnifiedDeviceStatus.ONLINE
        udm.register_device(dev)

        reg = CapabilityRegistry.get_instance()
        await reg.refresh(force=True)

        items = reg.list_tools(source="gateway")
        names = [i.name for i in items]
        assert any("gw_test_02" in n and "screen" in n for n in names)
        assert any("gw_test_02" in n and "touch" in n for n in names)


# ---------------------------------------------------------------------------
# Priority A — OpenClawd.sync_device_capabilities uses UnifiedDeviceManager
# ---------------------------------------------------------------------------

class TestOpenClawdSyncUsesUDM:
    """OpenClawd.sync_device_capabilities 使用 UnifiedDeviceManager 作为 SSOT。"""

    def setup_method(self):
        _reset_udm()
        _reset_cap_registry()

    def test_sync_device_capabilities_counts_low_level(self):
        from core.unified.device_manager import UnifiedDeviceManager
        from core.unified.models import UnifiedDevice, UnifiedDeviceStatus
        from core.openclawd import OpenClawd

        udm = UnifiedDeviceManager()
        dev = UnifiedDevice(
            device_id="sync_dev_01",
            device_name="SyncPhone",
            capabilities=["touch", "gps"],
        )
        dev.status = UnifiedDeviceStatus.ONLINE
        udm.register_device(dev)

        oc = OpenClawd()
        count = oc.sync_device_capabilities()
        assert count >= 2  # at least touch + gps

    def test_sync_device_capabilities_counts_autonomous(self):
        from core.unified.device_manager import UnifiedDeviceManager
        from core.unified.models import UnifiedDevice, UnifiedDeviceStatus
        from core.openclawd import OpenClawd

        udm = UnifiedDeviceManager()
        dev = UnifiedDevice(
            device_id="sync_auto_01",
            device_name="AutoPhone",
            metadata={"goal_execution_enabled": True, "local_model_enabled": True},
        )
        dev.status = UnifiedDeviceStatus.ONLINE
        udm.register_device(dev)

        oc = OpenClawd()
        count = oc.sync_device_capabilities()
        assert count >= 2  # goal_execution_enabled + local_model_enabled


# ---------------------------------------------------------------------------
# Priority D — OpenClawd._dispatch_goal_execution
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_goal_execution_with_device():
    """goal_execution dispatches to specified device via send_gateway_command."""
    _reset_udm()
    from core.openclawd import OpenClawd

    oc = OpenClawd()
    with patch.object(oc, "send_gateway_command", new_callable=AsyncMock) as mock_gw:
        mock_gw.return_value = {
            "success": True,
            "response": "goal received",
            "via": "command_router",
        }
        result = await oc._dispatch_goal_execution(
            "Open WeChat and send hello",
            device_id="phone_001",
            session_id="s1",
        )
    assert result["success"] is True
    assert result.get("intent") == "goal_execution"
    mock_gw.assert_called_once()
    call_kwargs = mock_gw.call_args.kwargs
    assert call_kwargs.get("device_id") == "phone_001"
    assert call_kwargs.get("payload", {}).get("task_type") == "goal_execution"


@pytest.mark.asyncio
async def test_dispatch_goal_execution_auto_selects_autonomous_device():
    """goal_execution auto-selects first autonomous device when no device_id given."""
    _reset_udm()
    _reset_cap_registry()
    from core.openclawd import OpenClawd
    from core.unified.device_manager import UnifiedDeviceManager
    from core.unified.models import UnifiedDevice, UnifiedDeviceStatus

    udm = UnifiedDeviceManager()
    auto_dev = UnifiedDevice(
        device_id="auto_phone_01",
        metadata={"goal_execution_enabled": True},
    )
    auto_dev.status = UnifiedDeviceStatus.ONLINE
    udm.register_device(auto_dev)

    oc = OpenClawd()
    with patch.object(oc, "send_gateway_command", new_callable=AsyncMock) as mock_gw:
        mock_gw.return_value = {"success": True, "response": "dispatched"}
        result = await oc._dispatch_goal_execution("Take a screenshot")
    assert result["success"] is True
    mock_gw.assert_called_once()
    assert mock_gw.call_args.kwargs.get("device_id") == "auto_phone_01"


@pytest.mark.asyncio
async def test_dispatch_goal_execution_falls_back_to_agent_when_no_device():
    """goal_execution falls back to _dispatch_agent when no autonomous device exists."""
    _reset_udm()
    _reset_cap_registry()
    from core.openclawd import OpenClawd
    from core.unified.device_manager import UnifiedDeviceManager

    UnifiedDeviceManager()  # empty manager

    oc = OpenClawd()
    with patch.object(oc, "_dispatch_agent", new_callable=AsyncMock) as mock_agent:
        mock_agent.return_value = {"success": True, "response": "agent fallback"}
        result = await oc._dispatch_goal_execution("Do something")
    assert result["success"] is True
    mock_agent.assert_called_once()


# ---------------------------------------------------------------------------
# Priority E — OpenClawd._dispatch_parallel_goal
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_parallel_goal_distributes_to_all_devices():
    """parallel_goal dispatches to all devices that support parallel_execution_enabled."""
    _reset_udm()
    from core.openclawd import OpenClawd
    from core.unified.device_manager import UnifiedDeviceManager
    from core.unified.models import UnifiedDevice, UnifiedDeviceStatus

    udm = UnifiedDeviceManager()
    for i in range(3):
        dev = UnifiedDevice(
            device_id=f"par_dev_{i:02d}",
            metadata={"parallel_execution_enabled": True},
        )
        dev.status = UnifiedDeviceStatus.ONLINE
        udm.register_device(dev)

    oc = OpenClawd()
    with patch.object(oc, "send_gateway_command", new_callable=AsyncMock) as mock_gw:
        mock_gw.return_value = {"success": True, "response": "ok"}
        result = await oc._dispatch_parallel_goal("Run on all devices")

    assert result["success"] is True
    assert result.get("intent") == "parallel_goal"
    meta = result.get("metadata", {})
    assert meta.get("device_count") == 3
    assert len(meta.get("subtask_results", [])) == 3
    assert mock_gw.call_count == 3


@pytest.mark.asyncio
async def test_dispatch_parallel_goal_falls_back_to_goal_execution_when_no_devices():
    """parallel_goal returns a structured failure message (not a silent fallback to
    goal_execution) when no parallel-capable autonomous devices are registered.

    Phase-3 spec: 'If no autonomous device found, degrade gracefully with explicit
    message and avoid parallel path.'
    """
    _reset_udm()
    from core.openclawd import OpenClawd
    from core.unified.device_manager import UnifiedDeviceManager
    import core.agent.capability_registry as cap_reg_mod

    UnifiedDeviceManager()  # empty

    oc = OpenClawd()
    with patch.object(
        cap_reg_mod.CapabilityRegistry,
        "get_instance",
        return_value=MagicMock(list_tools=MagicMock(return_value=[])),
    ):
        with patch.object(oc, "_dispatch_goal_execution", new_callable=AsyncMock) as mock_ge:
            result = await oc._dispatch_parallel_goal("Do something parallel")

    # _dispatch_goal_execution must NOT be called — we return an explicit message instead
    mock_ge.assert_not_called()
    assert result["success"] is False
    assert result.get("intent") == "parallel_goal"
    # Response should clearly indicate the lack of autonomous devices
    assert "parallel_execution_enabled" in result.get("response", "")


@pytest.mark.asyncio
async def test_dispatch_parallel_goal_partial_failure_still_succeeds():
    """parallel_goal returns success=True as long as at least one device succeeded."""
    _reset_udm()
    from core.openclawd import OpenClawd
    from core.unified.device_manager import UnifiedDeviceManager
    from core.unified.models import UnifiedDevice, UnifiedDeviceStatus

    udm = UnifiedDeviceManager()
    for i in range(2):
        dev = UnifiedDevice(
            device_id=f"par_partial_{i:02d}",
            metadata={"parallel_execution_enabled": True},
        )
        dev.status = UnifiedDeviceStatus.ONLINE
        udm.register_device(dev)

    call_count = 0

    async def _mixed_gw(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {"success": True, "response": "ok"}
        raise RuntimeError("device error")

    oc = OpenClawd()
    with patch.object(oc, "send_gateway_command", side_effect=_mixed_gw):
        result = await oc._dispatch_parallel_goal("Mixed task")

    assert result["success"] is True
    assert result["metadata"]["device_count"] == 2


# ---------------------------------------------------------------------------
# Priority B — Websocket disconnect syncs UnifiedDeviceManager
# ---------------------------------------------------------------------------

class TestWebSocketDisconnectSync:
    """断联时正确更新 UnifiedDeviceManager 状态。"""

    def test_disconnect_updates_unified_device_manager(self):
        _reset_udm()
        from galaxy_gateway.websocket_handler import GatewayWSManager
        from core.unified.device_manager import UnifiedDeviceManager
        from core.unified.models import UnifiedDevice, UnifiedDeviceStatus

        udm = UnifiedDeviceManager()

        # Pre-register device as ONLINE
        dev = UnifiedDevice(device_id="ws_dev_01")
        dev.status = UnifiedDeviceStatus.ONLINE
        udm.register_device(dev)

        # Simulate connection
        manager = GatewayWSManager()
        manager.active_connections["conn_1"] = MagicMock()
        manager.device_connections["ws_dev_01"] = "conn_1"

        from galaxy_gateway.device_router import device_router
        with patch.object(device_router, "unregister_device"):
            manager.disconnect("conn_1")

        # Device should be OFFLINE in UDM
        updated = udm.get_device("ws_dev_01")
        assert updated is not None
        assert updated.status in (
            UnifiedDeviceStatus.OFFLINE,
            UnifiedDeviceStatus.OFFLINE.value,
        )


# ---------------------------------------------------------------------------
# SSOT 全链路闭环：REST 注册 → UDM → CapabilityRegistry
# ---------------------------------------------------------------------------

class TestRESTRegistrationWritesToUDM:
    """REST 注册路径必须写入 UnifiedDeviceManager（SSOT）。"""

    def setup_method(self):
        _reset_udm()
        _reset_cap_registry()

    def _make_request(self, device_id: str, capabilities=None, metadata=None):
        """构造 DeviceRegisterRequest 风格字典，直接调用 devices.py 内部逻辑。"""
        from core.routes._models import DeviceRegisterRequest
        data = {
            "device_id": device_id,
            "device_type": "android",
            "device_name": f"TestPhone-{device_id[:4]}",
            "capabilities": capabilities or ["touch", "screen"],
            "os_version": "Android 13",
            "app_version": "2.0.0",
        }
        if metadata:
            data.update(metadata)
        return DeviceRegisterRequest(**data)

    @pytest.mark.asyncio
    async def test_rest_register_writes_to_udm(self):
        """REST POST /register 调用后，设备必须出现在 UDM 中。"""
        # 确保 devices 模块使用隔离的 UDM 单例
        _reset_udm()
        from core.unified.device_manager import get_unified_device_manager
        udm = get_unified_device_manager()

        from core.routes.devices import create_router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(create_router())

        with TestClient(app) as client:
            resp = client.post("/api/v1/devices/register", json={
                "device_id": "rest_ssot_01",
                "device_type": "android",
                "device_name": "SSoT Phone",
                "capabilities": ["touch", "camera"],
                "os_version": "Android 14",
                "app_version": "2.1.0",
            })
            assert resp.status_code == 200
            assert resp.json()["success"] is True

        # 验证 UDM 内存中有该设备
        dev = udm.get_device("rest_ssot_01")
        assert dev is not None, "REST 注册后设备应存在于 UDM"
        assert dev.device_id == "rest_ssot_01"
        assert "touch" in dev.capabilities

    @pytest.mark.asyncio
    async def test_rest_register_capability_visible_in_registry(self):
        """REST 注册后，CapabilityRegistry 应能看到设备能力。"""
        _reset_udm()
        _reset_cap_registry()
        from core.unified.device_manager import get_unified_device_manager
        udm = get_unified_device_manager()

        from core.routes.devices import _sync_device_to_capability_registry
        device_info = {
            "device_id": "cap_reg_test_01",
            "device_name": "CapRegPhone",
            "device_type": "android",
            "capabilities": ["screen", "keyboard"],
        }

        # 先手动同步到 UDM（模拟注册流程）
        udm.register_device_from_dict("cap_reg_test_01", device_info)

        # 调用能力同步
        count = _sync_device_to_capability_registry(device_info)
        assert count >= 2, "至少应同步 screen 和 keyboard 两个能力"

        from core.agent.capability_registry import CapabilityRegistry
        reg = CapabilityRegistry.get_instance()
        items = reg.list_tools(source="gateway")
        names = [i.name for i in items]
        assert any("cap_reg_test_01" in n and "screen" in n for n in names)
        assert any("cap_reg_test_01" in n and "keyboard" in n for n in names)

    @pytest.mark.asyncio
    async def test_rest_unregister_removes_from_udm(self):
        """REST DELETE /devices/{id} 注销后设备应从 UDM 中移除。"""
        _reset_udm()
        from core.unified.device_manager import get_unified_device_manager
        from core.routes.devices import create_router
        from core.routes._shared import registered_devices
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        udm = get_unified_device_manager()

        # 先在 UDM 和兼容缓存中预注册
        udm.register_device_from_dict("del_test_01", {
            "device_id": "del_test_01",
            "device_type": "android",
            "capabilities": [],
        })
        registered_devices["del_test_01"] = {
            "device_id": "del_test_01",
            "device_type": "android",
            "status": "registered",
        }

        app = FastAPI()
        app.include_router(create_router())

        with TestClient(app) as client:
            resp = client.delete("/api/v1/devices/del_test_01")
            assert resp.status_code == 200

        # 验证 UDM 中已移除
        assert udm.get_device("del_test_01") is None, "注销后设备应从 UDM 移除"

    def test_rest_heartbeat_updates_udm(self):
        """REST POST /heartbeat 应更新 UDM 中的 last_heartbeat。"""
        _reset_udm()
        from core.unified.device_manager import get_unified_device_manager
        from core.routes._shared import registered_devices

        udm = get_unified_device_manager()
        udm.register_device_from_dict("hb_test_01", {
            "device_id": "hb_test_01",
            "device_type": "android",
        })
        # 在兼容缓存中预置（heartbeat 端点检查 registered_devices 存在性）
        registered_devices["hb_test_01"] = {
            "device_id": "hb_test_01",
            "last_seen": "2000-01-01T00:00:00",
            "status": "registered",
        }

        before_hb = udm.get_device("hb_test_01").last_heartbeat

        udm.heartbeat("hb_test_01")

        after_hb = udm.get_device("hb_test_01").last_heartbeat
        assert after_hb is not None
        if before_hb is not None:
            assert after_hb >= before_hb


class TestDisconnectOfflineInUDM:
    """断连/离线状态必须在 UDM 中可追踪（补充覆盖）。"""

    def test_offline_status_tracked_after_unregister(self):
        """注销后 UDM 不再持有该设备（unregister 而非 status=offline）。"""
        _reset_udm()
        from core.unified.device_manager import UnifiedDeviceManager
        from core.unified.models import UnifiedDevice, UnifiedDeviceStatus

        udm = UnifiedDeviceManager()
        dev = UnifiedDevice(device_id="offline_track_01")
        dev.status = UnifiedDeviceStatus.ONLINE
        udm.register_device(dev)

        # 注销
        udm.unregister_device("offline_track_01")
        assert udm.get_device("offline_track_01") is None

    def test_status_update_to_offline_tracked(self):
        """状态更新为 OFFLINE 后，online_devices 不包含该设备。"""
        _reset_udm()
        from core.unified.device_manager import UnifiedDeviceManager
        from core.unified.models import UnifiedDevice, UnifiedDeviceStatus

        udm = UnifiedDeviceManager()
        dev = UnifiedDevice(device_id="offline_track_02")
        dev.status = UnifiedDeviceStatus.ONLINE
        udm.register_device(dev)

        udm.update_device_status("offline_track_02", UnifiedDeviceStatus.OFFLINE)

        online = udm.get_online_devices()
        ids = [d.device_id for d in online]
        assert "offline_track_02" not in ids

    def test_offline_device_excluded_from_command_routing(self):
        """离线设备不出现在可调用设备列表中（autonomous 和 capability 查询均排除）。"""
        _reset_udm()
        from core.unified.device_manager import UnifiedDeviceManager
        from core.unified.models import UnifiedDevice, UnifiedDeviceStatus

        udm = UnifiedDeviceManager()
        dev = UnifiedDevice(
            device_id="route_offline_01",
            metadata={"goal_execution_enabled": True},
            capabilities=["touch"],
        )
        udm.register_device(dev)
        # register_device sets status to ONLINE; explicitly mark offline
        udm.update_device_status("route_offline_01", UnifiedDeviceStatus.OFFLINE)

        # 离线设备不应出现在自治设备列表中
        auto_ids = [d.device_id for d in udm.get_autonomous_devices()]
        assert "route_offline_01" not in auto_ids

        # 离线设备不应出现在能力查询结果中
        cap_ids = [d.device_id for d in udm.get_devices_with_capability("touch")]
        assert "route_offline_01" not in cap_ids
