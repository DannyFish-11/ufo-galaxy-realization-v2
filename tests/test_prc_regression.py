"""
PR-C 回归测试 — 网关 trace + 可观测性验收
==========================================

覆盖内容：
  1. route_command 路径包含完整 trace ID（request_id/task_id/command_id/device_id）
  2. 协议信封验证（空 device_id / command / command_id / task_id / 非 dict payload）
  3. 超时错误通过 COMMAND_TIMEOUT 代码传播回 OpenClawd
  4. 断连/连接错误通过 DISCONNECT 代码传播
  5. GatewayTraceStore 记录、按 command_id 查询、按 task_id 查询
  6. 可观测接口 Schema 验证（model-route / gateway / recent-calls / trace / stats）
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ============================================================================
# 1. route_command — 完整 trace ID
# ============================================================================


class TestGatewayRouteCommandTraceIDs:
    """route_command 必须在返回结果中携带完整 trace 四元组。"""

    @pytest.mark.asyncio
    async def test_route_command_returns_all_trace_ids(self):
        """成功路径：返回值中必须包含 request_id / task_id / command_id / device_id。"""
        from core.command_router import CommandRouter

        async def mock_executor(device_id, command, params):
            return {"ok": True}

        cr = CommandRouter(executor=mock_executor)
        result = await cr.route_command(
            device_id="phone_001",
            command="screenshot",
            payload={},
            command_id="cmd_abc",
            task_id="task_xyz",
        )

        assert "request_id" in result, "返回值必须包含 request_id"
        assert result["task_id"] == "task_xyz", "task_id 必须原样返回"
        assert result["command_id"] == "cmd_abc", "command_id 必须原样返回"
        assert result["device_id"] == "phone_001", "device_id 必须原样返回"
        assert result["via"] == "command_router", "via 必须为 'command_router'"

    @pytest.mark.asyncio
    async def test_route_command_success_flag(self):
        """executor 正常返回时 success 必须为 True。"""
        from core.command_router import CommandRouter

        async def mock_executor(device_id, command, params):
            return "done"

        cr = CommandRouter(executor=mock_executor)
        result = await cr.route_command(
            device_id="d1", command="tap", payload={"x": 10},
            command_id="c1", task_id="t1",
        )
        assert result["success"] is True
        assert result["error_code"] is None

    @pytest.mark.asyncio
    async def test_route_command_no_bypass_envelope_always_checked(self):
        """即使 executor 可用，信封校验也必须先于执行器调用。"""
        from core.command_router import CommandRouter, GatewayErrorCode

        called = []

        async def mock_executor(device_id, command, params):
            called.append("executor_called")
            return "should_not_reach"

        cr = CommandRouter(executor=mock_executor)
        # 信封不合法（空 command）
        result = await cr.route_command(
            device_id="d1", command="",  # 无效
            payload={}, command_id="c1", task_id="t1",
        )

        assert result["success"] is False
        assert result["error_code"] == GatewayErrorCode.INVALID_ENVELOPE.value
        assert not called, "信封非法时不应调用 executor"


# ============================================================================
# 2. 协议信封验证
# ============================================================================


class TestProtocolEnvelopeValidation:
    """validate_command_envelope 对各类缺失字段抛出 INVALID_ENVELOPE。"""

    def _validate(self, **kwargs):
        from core.command_router import validate_command_envelope, GatewayError
        try:
            validate_command_envelope(**kwargs)
            return None
        except GatewayError as exc:
            return exc

    def _default_kwargs(self, **overrides):
        base = dict(
            device_id="dev",
            command="tap",
            payload={},
            command_id="cid",
            task_id="tid",
        )
        base.update(overrides)
        return base

    def test_valid_envelope_no_error(self):
        err = self._validate(**self._default_kwargs())
        assert err is None, "合法信封不应触发错误"

    def test_empty_device_id_raises(self):
        from core.command_router import GatewayErrorCode
        err = self._validate(**self._default_kwargs(device_id=""))
        assert err is not None
        assert err.code == GatewayErrorCode.INVALID_ENVELOPE

    def test_empty_command_raises(self):
        from core.command_router import GatewayErrorCode
        err = self._validate(**self._default_kwargs(command=""))
        assert err is not None
        assert err.code == GatewayErrorCode.INVALID_ENVELOPE

    def test_empty_command_id_raises(self):
        from core.command_router import GatewayErrorCode
        err = self._validate(**self._default_kwargs(command_id=""))
        assert err is not None
        assert err.code == GatewayErrorCode.INVALID_ENVELOPE

    def test_empty_task_id_raises(self):
        from core.command_router import GatewayErrorCode
        err = self._validate(**self._default_kwargs(task_id=""))
        assert err is not None
        assert err.code == GatewayErrorCode.INVALID_ENVELOPE

    def test_non_dict_payload_raises(self):
        from core.command_router import GatewayErrorCode
        err = self._validate(**self._default_kwargs(payload="bad"))
        assert err is not None
        assert err.code == GatewayErrorCode.INVALID_ENVELOPE

    @pytest.mark.asyncio
    async def test_route_command_propagates_envelope_error(self):
        """route_command 在信封非法时直接返回，不调用 executor。"""
        from core.command_router import CommandRouter, GatewayErrorCode

        cr = CommandRouter()
        result = await cr.route_command(
            device_id="",  # 空 device_id
            command="screenshot",
            payload={},
            command_id="c1",
            task_id="t1",
        )
        assert result["success"] is False
        assert result["error_code"] == GatewayErrorCode.INVALID_ENVELOPE.value
        assert result["command_id"] == "c1"
        assert result["task_id"] == "t1"


# ============================================================================
# 3. 超时错误传播
# ============================================================================


class TestTimeoutErrorPropagation:
    """超时错误必须以 COMMAND_TIMEOUT 代码传回，含完整 trace。"""

    @pytest.mark.asyncio
    async def test_timeout_returns_command_timeout_code(self):
        """executor 超时时 error_code 必须为 COMMAND_TIMEOUT。"""
        from core.command_router import CommandRouter, GatewayErrorCode

        async def slow_executor(device_id, command, params):
            await asyncio.sleep(10)  # 远超 timeout
            return "never_reached"

        cr = CommandRouter(executor=slow_executor)
        result = await cr.route_command(
            device_id="slow_device",
            command="heavy_task",
            payload={},
            command_id="cmd_timeout",
            task_id="task_timeout",
            timeout=0.05,  # 50ms
        )

        assert result["success"] is False
        assert result["error_code"] == GatewayErrorCode.COMMAND_TIMEOUT.value
        assert "command_id" in result
        assert "task_id" in result
        assert "device_id" in result

    @pytest.mark.asyncio
    async def test_timeout_trace_ids_preserved(self):
        """超时结果中 trace ID 必须与输入完全一致。"""
        from core.command_router import CommandRouter

        async def slow_executor(*_):
            await asyncio.sleep(100)

        cr = CommandRouter(executor=slow_executor)
        result = await cr.route_command(
            device_id="dev_timeout",
            command="tap",
            payload={},
            command_id="cmd_trace_timeout",
            task_id="task_trace_timeout",
            timeout=0.05,
        )

        assert result["command_id"] == "cmd_trace_timeout"
        assert result["task_id"] == "task_trace_timeout"
        assert result["device_id"] == "dev_timeout"


# ============================================================================
# 4. 断连错误传播
# ============================================================================


class TestDisconnectErrorPropagation:
    """ConnectionError 必须以 DISCONNECT 代码传回，含完整 trace。"""

    @pytest.mark.asyncio
    async def test_connection_error_returns_disconnect_code(self):
        """executor 抛出 ConnectionError 时 error_code 必须为 DISCONNECT。"""
        from core.command_router import CommandRouter, GatewayErrorCode

        async def disconnected_executor(device_id, command, params):
            raise ConnectionError("设备连接丢失")

        cr = CommandRouter(executor=disconnected_executor)
        result = await cr.route_command(
            device_id="disconnected_device",
            command="screenshot",
            payload={},
            command_id="cmd_dc",
            task_id="task_dc",
        )

        assert result["success"] is False
        assert result["error_code"] == GatewayErrorCode.DISCONNECT.value
        assert "设备连接丢失" in result["error_message"]

    @pytest.mark.asyncio
    async def test_os_error_returns_disconnect_code(self):
        """executor 抛出 OSError 时 error_code 必须为 DISCONNECT。"""
        from core.command_router import CommandRouter, GatewayErrorCode

        async def os_error_executor(*_):
            raise OSError("网络中断")

        cr = CommandRouter(executor=os_error_executor)
        result = await cr.route_command(
            device_id="os_err_dev", command="cmd", payload={},
            command_id="c2", task_id="t2",
        )

        assert result["error_code"] == GatewayErrorCode.DISCONNECT.value

    @pytest.mark.asyncio
    async def test_generic_error_returns_executor_error_code(self):
        """executor 抛出普通 Exception 时 error_code 必须为 EXECUTOR_ERROR。"""
        from core.command_router import CommandRouter, GatewayErrorCode

        async def broken_executor(*_):
            raise RuntimeError("未知内部错误")

        cr = CommandRouter(executor=broken_executor)
        result = await cr.route_command(
            device_id="d", command="c", payload={},
            command_id="cx", task_id="tx",
        )

        assert result["success"] is False
        assert result["error_code"] == GatewayErrorCode.EXECUTOR_ERROR.value

    @pytest.mark.asyncio
    async def test_disconnect_trace_ids_preserved(self):
        """断连结果中 trace ID 必须与输入完全一致。"""
        from core.command_router import CommandRouter

        async def dc_executor(*_):
            raise ConnectionError("断连")

        cr = CommandRouter(executor=dc_executor)
        result = await cr.route_command(
            device_id="dev_dc",
            command="tap",
            payload={},
            command_id="cmd_dc_trace",
            task_id="task_dc_trace",
        )

        assert result["command_id"] == "cmd_dc_trace"
        assert result["task_id"] == "task_dc_trace"
        assert result["device_id"] == "dev_dc"


# ============================================================================
# 5. GatewayTraceStore
# ============================================================================


class TestGatewayTraceStore:
    """GatewayTraceStore 记录、按 command_id / task_id 查询。"""

    def _make_store(self):
        from core.command_router import GatewayTraceStore
        return GatewayTraceStore()

    def test_record_and_lookup_by_command_id(self):
        store = self._make_store()
        entry = {
            "command_id": "cid_1",
            "task_id": "tid_a",
            "device_id": "dev",
            "command": "screenshot",
            "success": True,
        }
        store.record(entry)
        found = store.lookup_by_command_id("cid_1")
        assert found is not None
        assert found["command_id"] == "cid_1"
        assert found["task_id"] == "tid_a"

    def test_lookup_missing_command_id_returns_none(self):
        store = self._make_store()
        assert store.lookup_by_command_id("nonexistent") is None

    def test_record_and_lookup_by_task_id(self):
        store = self._make_store()
        for i in range(3):
            store.record({
                "command_id": f"cid_{i}",
                "task_id": "shared_task",
                "device_id": "dev",
                "command": f"cmd_{i}",
                "success": True,
            })
        results = store.lookup_by_task_id("shared_task")
        assert len(results) == 3
        assert all(r["task_id"] == "shared_task" for r in results)

    def test_lookup_missing_task_id_returns_empty_list(self):
        store = self._make_store()
        assert store.lookup_by_task_id("nonexistent") == []

    def test_recent_returns_latest_first(self):
        store = self._make_store()
        for i in range(5):
            store.record({"command_id": f"c{i}", "task_id": "t", "success": True})
        recent = store.recent(3)
        assert len(recent) == 3
        assert recent[0]["command_id"] == "c4"  # 最新的排在前面

    def test_stats_counts(self):
        store = self._make_store()
        store.record({"command_id": "c1", "task_id": "t1", "success": True})
        store.record({"command_id": "c2", "task_id": "t1", "success": False})
        stats = store.stats()
        assert stats["total_recorded"] == 2
        assert stats["total_success"] == 1
        assert stats["total_failed"] == 1
        assert stats["unique_command_ids"] == 2
        assert stats["unique_task_ids"] == 1

    def test_max_entries_eviction(self):
        """超出 MAX_ENTRIES 后应淘汰最旧条目。"""
        from core.command_router import GatewayTraceStore
        store = GatewayTraceStore()
        store._MAX_ENTRIES = 5
        for i in range(7):
            store.record({"command_id": f"c{i}", "task_id": "t", "success": True})
        assert len(store._entries) <= 6  # 至多 MAX_ENTRIES + 1 被淘汰前大小
        # 最旧的 c0 应已被淘汰
        assert store.lookup_by_command_id("c0") is None

    @pytest.mark.asyncio
    async def test_route_command_auto_records_to_trace_store(self):
        """route_command 成功后，GatewayTraceStore 中应有对应记录。"""
        from core.command_router import CommandRouter, get_gateway_trace_store

        # 使用独立的 CommandRouter 实例，但 trace store 是全局单例
        async def ok_executor(device_id, command, params):
            return "ok"

        cr = CommandRouter(executor=ok_executor)
        cid = "cmd_record_test"
        await cr.route_command(
            device_id="dev_record",
            command="tap",
            payload={},
            command_id=cid,
            task_id="tid_record",
        )

        store = get_gateway_trace_store()
        entry = store.lookup_by_command_id(cid)
        assert entry is not None, "route_command 必须自动写入 GatewayTraceStore"
        assert entry["success"] is True


# ============================================================================
# 6. 可观测性接口 Schema 验证
# ============================================================================


class TestObservabilityEndpointSchemas:
    """验证可观测性端点返回结构符合预期 schema。"""

    def _make_client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from core.routes.observability import create_router
        app = FastAPI()
        app.include_router(create_router())
        return TestClient(app)

    def test_model_route_endpoint_schema(self):
        """GET /api/v1/observability/model-route 必须返回规定字段。"""
        client = self._make_client()
        resp = client.get("/api/v1/observability/model-route")
        assert resp.status_code == 200
        data = resp.json()
        assert "default_model" in data, "必须包含 default_model"
        assert "providers" in data, "必须包含 providers"
        assert "fallbacks" in data, "必须包含 fallbacks"
        assert isinstance(data["providers"], list)
        assert isinstance(data["fallbacks"], list)

    def test_gateway_status_endpoint_schema(self):
        """GET /api/v1/observability/gateway 必须返回规定字段。"""
        client = self._make_client()
        resp = client.get("/api/v1/observability/gateway")
        assert resp.status_code == 200
        data = resp.json()
        assert "websocket_active_devices" in data
        assert "registered_devices" in data
        assert "online_count" in data
        assert isinstance(data["websocket_active_devices"], list)
        assert isinstance(data["registered_devices"], list)
        assert isinstance(data["online_count"], int)

    def test_recent_calls_endpoint_schema(self):
        """GET /api/v1/observability/recent-calls 必须返回 count + calls 列表。"""
        client = self._make_client()
        resp = client.get("/api/v1/observability/recent-calls")
        assert resp.status_code == 200
        data = resp.json()
        assert "count" in data
        assert "calls" in data
        assert isinstance(data["calls"], list)

    def test_recent_calls_limit_param(self):
        """GET /api/v1/observability/recent-calls?limit=5 应尊重限制。"""
        client = self._make_client()
        resp = client.get("/api/v1/observability/recent-calls?limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["calls"]) <= 5

    def test_trace_lookup_missing_id_returns_404_or_not_found(self):
        """未知 trace_id 应返回 found=False（404 或 200+found=False）。"""
        client = self._make_client()
        resp = client.get("/api/v1/observability/trace/nonexistent_id_xyz")
        # 可能是 404 或 200 with found=False
        if resp.status_code == 200:
            data = resp.json()
            assert data.get("found") is False or data.get("count", 0) == 0
        else:
            assert resp.status_code in (404, 200)

    def test_trace_lookup_by_command_id_returns_schema(self):
        """先写入 trace，再按 command_id 查询，验证返回 schema。"""
        from core.command_router import get_gateway_trace_store
        store = get_gateway_trace_store()
        store.record({
            "command_id": "test_schema_cmd",
            "task_id": "test_schema_task",
            "device_id": "dev",
            "command": "tap",
            "success": True,
        })

        client = self._make_client()
        resp = client.get(
            "/api/v1/observability/trace/test_schema_cmd",
            params={"id_type": "command_id"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("found") is True
        assert "trace" in data
        assert data["trace"]["command_id"] == "test_schema_cmd"

    def test_trace_lookup_by_task_id_returns_schema(self):
        """先写入多条 trace，再按 task_id 查询，验证返回 schema。"""
        from core.command_router import get_gateway_trace_store
        store = get_gateway_trace_store()
        for i in range(2):
            store.record({
                "command_id": f"schema_task_cmd_{i}",
                "task_id": "schema_task_xxx",
                "device_id": "dev",
                "command": "tap",
                "success": True,
            })

        client = self._make_client()
        resp = client.get(
            "/api/v1/observability/trace/schema_task_xxx",
            params={"id_type": "task_id"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("found") is True
        assert "traces" in data
        assert data["count"] >= 2

    def test_observability_stats_endpoint_schema(self):
        """GET /api/v1/observability/stats 必须返回规定统计字段。"""
        client = self._make_client()
        resp = client.get("/api/v1/observability/stats")
        assert resp.status_code == 200
        data = resp.json()
        for key in ("total_recorded", "total_success", "total_failed",
                    "unique_command_ids", "unique_task_ids"):
            assert key in data, f"stats 必须包含字段: {key}"
        assert isinstance(data["total_recorded"], int)


# ============================================================================
# 7. OpenClawd 使用 route_command 时仍传播错误
# ============================================================================


class TestOpenClawdErrorPropagation:
    """OpenClawd.send_gateway_command 在 command_router 失败时需传回 error 信息。"""

    @pytest.mark.asyncio
    async def test_openclawd_propagates_timeout_from_command_router(self):
        """command_router.route_command 超时时 send_gateway_command 仍含 trace IDs。"""
        from core.openclawd import OpenClawd
        from core.command_router import GatewayErrorCode

        async def timeout_route_command(**kwargs):
            return {
                "success": False,
                "error_code": GatewayErrorCode.COMMAND_TIMEOUT.value,
                "error_message": "超时",
                "command_id": kwargs.get("command_id", ""),
                "task_id": kwargs.get("task_id", ""),
                "device_id": kwargs.get("device_id", ""),
                "request_id": "req_test",
                "via": "command_router",
                "latency_ms": 5000.0,
            }

        oc = OpenClawd()
        mock_cr = MagicMock()
        mock_cr.route_command = AsyncMock(side_effect=timeout_route_command)

        # get_command_router is imported locally inside send_gateway_command,
        # so we patch it at the source module.
        with patch("core.command_router.get_command_router", return_value=mock_cr):
            result = await oc.send_gateway_command(
                device_id="slow_dev",
                command="screenshot",
                payload={},
                task_id="task_propagate",
            )

        assert "command_id" in result, "send_gateway_command 结果必须含 command_id"
        assert "task_id" in result, "send_gateway_command 结果必须含 task_id"

    @pytest.mark.asyncio
    async def test_openclawd_propagates_disconnect_from_command_router(self):
        """command_router 断连错误时 send_gateway_command 成功返回（含 trace）。"""
        from core.openclawd import OpenClawd
        from core.command_router import GatewayErrorCode

        async def dc_route_command(**kwargs):
            return {
                "success": False,
                "error_code": GatewayErrorCode.DISCONNECT.value,
                "error_message": "断连",
                "command_id": kwargs.get("command_id", ""),
                "task_id": kwargs.get("task_id", ""),
                "device_id": kwargs.get("device_id", ""),
                "request_id": "req_dc",
                "via": "command_router",
                "latency_ms": 10.0,
            }

        oc = OpenClawd()
        mock_cr = MagicMock()
        mock_cr.route_command = AsyncMock(side_effect=dc_route_command)

        with patch("core.command_router.get_command_router", return_value=mock_cr):
            result = await oc.send_gateway_command(
                device_id="dc_dev",
                command="tap",
                payload={},
                task_id="task_dc_prop",
            )

        assert "command_id" in result
        assert "task_id" in result
