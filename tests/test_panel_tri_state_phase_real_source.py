"""tests/test_panel_tri_state_phase_real_source.py
=====================================================
三态系统稳定性排查(用户要求"再全部排查一遍")定位到的严重 bug:

core/unified_panel_aggregation.py::_fill_from_runtime_projection() 读
DesktopPresenceRuntime 单例的 _continuum_state 属性——但该属性只在每次请求
新建的临时 RuntimeSession 上被赋值，单例自身从未被赋值过，恒为 None，必然
走到 _get_continuum_state_fallback()；而后者 import 的
"core.cognitive_field_engine" 模块路径本身就不存在(真实路径是
"core.cognitive.cognitive_field_engine")，ModuleNotFoundError 被静默吞掉，
最终硬编码返回 ContinuumState(phase=SILENT)。

后果:GET /api/v1/panel/feed 的 tri_state_phase 字段【永远是 "silent"】，
跟桌面覆盖层(走 GalaxyPresenceBridge 的独立、正确通道)实际显示的相位完全
脱节。WS 断线重连期间(App.tsx 会退回到这个 IPC feed，最长可达 30 秒)，
面板因此被错误拉回"待机"，即便 AI 其实还在 LIMINAL/MANIFEST。

修复:core.lumiv_websocket_bridge 新增 get_current_phase()，直接读
GalaxyPresenceBridge._current_mode(驱动桌面覆盖层的同一份实时状态)；
core/routes/panel.py::get_panel_feed() 用它覆盖掉聚合层算出的死值。

本文件验证:
1. get_current_phase() 本身随 GalaxyPresenceBridge._current_mode 变化。
2. GET /api/v1/panel/feed 的 tri_state_phase 确实反映 GalaxyPresenceBridge
   的真实状态，而不是恒为 "silent"（回归测试：故意让聚合层的死路径继续
   返回 silent，验证最终响应仍然被 bridge 的真实值覆盖）。
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch


class TestGetCurrentPhase(unittest.TestCase):
    def test_static_mode_maps_to_silent(self):
        from core.lumiv_websocket_bridge import GalaxyPresenceBridge, get_current_phase

        bridge = GalaxyPresenceBridge.get_instance()
        bridge._current_mode = "static"
        self.assertEqual(get_current_phase(), "silent")

    def test_liminal_mode_passthrough(self):
        from core.lumiv_websocket_bridge import GalaxyPresenceBridge, get_current_phase

        bridge = GalaxyPresenceBridge.get_instance()
        bridge._current_mode = "liminal"
        self.assertEqual(get_current_phase(), "liminal")

    def test_manifest_mode_passthrough(self):
        from core.lumiv_websocket_bridge import GalaxyPresenceBridge, get_current_phase

        bridge = GalaxyPresenceBridge.get_instance()
        bridge._current_mode = "manifest"
        self.assertEqual(get_current_phase(), "manifest")


class TestPanelFeedReflectsRealPhase(unittest.IsolatedAsyncioTestCase):
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

    async def test_feed_reflects_manifest_even_when_aggregation_layer_says_silent(self):
        """回归测试的核心:即使 build_unified_panel_payload() 那条死路径仍然
        算出 "silent"（真机上它确实恒为 silent），最终 feed 里的 tri_state_phase
        也必须是 bridge 的真实值 "manifest"，不能被死路径覆盖回去。"""
        from core.lumiv_websocket_bridge import GalaxyPresenceBridge

        bridge = GalaxyPresenceBridge.get_instance()
        bridge._current_mode = "manifest"

        mock_payload = MagicMock()
        mock_payload.to_dict.return_value = {"tri_state_phase": "silent", "presence_intensity": 0.0, "coherence": 0.0}
        with patch("core.unified_panel_aggregation.build_unified_panel_payload", return_value=mock_payload):
            feed = await self._get_feed()

        self.assertEqual(
            feed["tri_state_phase"], "manifest",
            "面板 feed 的相位必须反映 GalaxyPresenceBridge 的真实状态，"
            "不能被聚合层那条恒为 silent 的死路径覆盖",
        )

    async def test_feed_reflects_liminal(self):
        from core.lumiv_websocket_bridge import GalaxyPresenceBridge

        bridge = GalaxyPresenceBridge.get_instance()
        bridge._current_mode = "liminal"

        mock_payload = MagicMock()
        mock_payload.to_dict.return_value = {"tri_state_phase": "silent"}
        with patch("core.unified_panel_aggregation.build_unified_panel_payload", return_value=mock_payload):
            feed = await self._get_feed()

        self.assertEqual(feed["tri_state_phase"], "liminal")


if __name__ == "__main__":
    unittest.main()
