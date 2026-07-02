"""tests/test_panel_feed_real_data.py
======================================
GET /api/v1/panel/feed(core/routes/panel.py::get_panel_feed)覆盖:全链路排查中
发现 openclawd_status/mesh_session 两段字段之前是"看起来像实时遥测,实际是写死
默认值"的问题:

1. openclawd_status:之前直接 st.get("runtime_state")/st.get("active_tasks") 等
   顶层键——但 get_openclawd().get_status() 实际返回的是嵌套结构
   {"openclawd": {...}, "agent_factory": {...}, ...},这些顶层键从不存在,永远
   落到硬编码默认值(RUNNING / 0 / 0.95 / 0s)。修复后应从真实嵌套字段取。
2. mesh_session.participants:之前无条件写死 []、barrierStatus 无条件写死
   "open"。修复后应读 BodyMeshRegistry 的真实注册条目。

本测试直接 mock 这两个真实数据源，断言 feed 里的值随 mock 数据变化而变化——
如果代码退化回读错误的顶层键/硬编码，这些测试会失败。
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch


class TestPanelFeedOpenClawdStatus(unittest.IsolatedAsyncioTestCase):
    async def _get_feed(self):
        from httpx import AsyncClient, ASGITransport
        from fastapi import FastAPI
        from core.routes.panel import create_router

        app = FastAPI()
        app.include_router(create_router())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/panel/feed")
        self.assertEqual(resp.status_code, 200)
        return resp.json()["feed"]

    async def test_runtime_state_reflects_real_initialized_flag(self):
        """initialized=False 的真实状态必须反映为 RESTARTING,而不是永远 RUNNING。"""
        mock_status = {
            "openclawd": {"initialized": False, "uptime_seconds": 0},
            "agent_factory": {"by_state": {}},
        }
        mock_oc = MagicMock()
        mock_oc.get_status = AsyncMock(return_value=mock_status)
        with patch("core.openclawd.get_openclawd", return_value=mock_oc):
            feed = await self._get_feed()
        self.assertEqual(feed["openclawd_status"]["runtimeState"], "RESTARTING")

    async def test_runtime_state_running_when_initialized(self):
        mock_status = {
            "openclawd": {"initialized": True, "uptime_seconds": 42},
            "agent_factory": {"by_state": {}},
        }
        mock_oc = MagicMock()
        mock_oc.get_status = AsyncMock(return_value=mock_status)
        with patch("core.openclawd.get_openclawd", return_value=mock_oc):
            feed = await self._get_feed()
        self.assertEqual(feed["openclawd_status"]["runtimeState"], "RUNNING")

    async def test_uptime_reads_real_nested_uptime_seconds(self):
        """之前读 st.get("uptime")(顶层,不存在)——真实字段是嵌套的 uptime_seconds。"""
        mock_status = {
            "openclawd": {"initialized": True, "uptime_seconds": 12345},
            "agent_factory": {"by_state": {}},
        }
        mock_oc = MagicMock()
        mock_oc.get_status = AsyncMock(return_value=mock_status)
        with patch("core.openclawd.get_openclawd", return_value=mock_oc):
            feed = await self._get_feed()
        self.assertEqual(feed["openclawd_status"]["uptime"], 12345)

    async def test_active_and_completed_tasks_derived_from_agent_factory_by_state(self):
        """activeTasks/completedTasks 必须随 agent_factory 的真实 by_state 分布变化。"""
        mock_status = {
            "openclawd": {"initialized": True, "uptime_seconds": 1},
            "agent_factory": {
                "by_state": {"working": 2, "waiting": 1, "completed": 5, "idle": 3},
            },
        }
        mock_oc = MagicMock()
        mock_oc.get_status = AsyncMock(return_value=mock_status)
        with patch("core.openclawd.get_openclawd", return_value=mock_oc):
            feed = await self._get_feed()
        self.assertEqual(feed["openclawd_status"]["activeTasks"], 3)  # working+waiting
        self.assertEqual(feed["openclawd_status"]["completedTasks"], 5)


class TestPanelFeedMeshParticipants(unittest.IsolatedAsyncioTestCase):
    async def _get_feed(self):
        from httpx import AsyncClient, ASGITransport
        from fastapi import FastAPI
        from core.routes.panel import create_router

        app = FastAPI()
        app.include_router(create_router())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/panel/feed")
        self.assertEqual(resp.status_code, 200)
        return resp.json()["feed"]

    async def test_participants_empty_when_registry_empty(self):
        mock_registry = MagicMock()
        mock_registry.list_entries.return_value = []
        with patch("core.mesh.body_mesh_registry.get_body_mesh_registry", return_value=mock_registry):
            feed = await self._get_feed()
        self.assertEqual(feed["mesh_session"]["participants"], [])
        self.assertEqual(feed["mesh_session"]["barrierStatus"], "n/a")

    async def test_participants_reflect_real_registry_entries(self):
        """之前 participants 无条件写死 []——修复后应反映 BodyMeshRegistry 的真实条目。"""
        from core.mesh.body_mesh_registry import BodyEntry, DeviceRole

        entry = BodyEntry(
            device_id="phone-1",
            roles={DeviceRole.PERCEPTION},
            session_id="sess-abc",
            registered_at=1700000000.0,
        )
        mock_registry = MagicMock()
        mock_registry.list_entries.return_value = [entry]
        with patch("core.mesh.body_mesh_registry.get_body_mesh_registry", return_value=mock_registry):
            feed = await self._get_feed()
        participants = feed["mesh_session"]["participants"]
        self.assertEqual(len(participants), 1)
        self.assertEqual(participants[0]["nodeId"], "phone-1")
        self.assertEqual(participants[0]["status"], "active")  # has session_id
        self.assertEqual(feed["mesh_session"]["barrierStatus"], "active")

    async def test_participant_status_idle_when_no_session(self):
        from core.mesh.body_mesh_registry import BodyEntry, DeviceRole

        entry = BodyEntry(device_id="watch-1", roles={DeviceRole.PRESENCE}, session_id=None)
        mock_registry = MagicMock()
        mock_registry.list_entries.return_value = [entry]
        with patch("core.mesh.body_mesh_registry.get_body_mesh_registry", return_value=mock_registry):
            feed = await self._get_feed()
        self.assertEqual(feed["mesh_session"]["participants"][0]["status"], "idle")


if __name__ == "__main__":
    unittest.main()
