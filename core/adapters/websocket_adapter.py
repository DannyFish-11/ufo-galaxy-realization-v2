"""
core/adapters/websocket_adapter.py — WebSocket 传输适配器
"""

import inspect
import logging
from typing import Any, Dict, Optional

from core.aip_transport import TransportAdapter

logger = logging.getLogger("Galaxy.Adapter.WebSocket")


class WebSocketAdapter(TransportAdapter):
    """WebSocket 传输适配器。

    始终在线的长连接，点对点双向通信。
    """

    @property
    def transport_type(self) -> str:
        return "websocket"

    def __init__(self, ws_manager: Optional[Any] = None) -> None:
        self._ws = ws_manager

    def _get_ws(self) -> Optional[Any]:
        """取 WebSocketManager 实例。

        原来这里 import 的是 ``galaxy_gateway.connection_manager`` —— 这个模块
        根本不存在(实测 ImportError),异常又被静默吞掉,于是任何不显式传
        ``ws_manager`` 构造出来的适配器都永远是"不可用"状态。真正发布实例的
        地方是 bootstrap/lifecycle.py:94/102:``app.state.websocket_manager``
        与模块级兼容全局 ``galaxy_gateway.app.websocket_manager``。
        """
        if self._ws is None:
            try:
                import galaxy_gateway.app as _gw_app

                self._ws = getattr(_gw_app, "websocket_manager", None)
            except Exception as exc:  # noqa: BLE001
                logger.debug("WebSocket manager 尚不可用: %s", exc)
        return self._ws

    async def send(self, message: Dict[str, Any], target: str) -> Dict[str, Any]:
        ws = self._get_ws()
        if ws is None:
            return {"success": False, "error": "WebSocket manager not available"}

        try:
            # WebSocketManager.send_message 的签名是 async -> bool
            # (transport/websocket_server.py:158),False 表示【没投递出去】
            # (设备不在线/socket 已断)。此前这里只 await、不看返回值,一律
            # 回 success=True —— 投递失败被当成成功,上层于是不再重试、也不
            # 走别的传输,消息就这么无声丢了。
            ok = await ws.send_message(target, message)
            if not ok:
                logger.warning("WS send to %s not delivered (device offline or socket closed)", target)
                return {"success": False, "error": "WS not delivered: target unreachable"}
            return {"success": True, "via": "websocket"}
        except Exception as e:
            logger.warning("WS send to %s failed: %s", target, e)
            return {"success": False, "error": f"WS failed: {e}"}

    async def is_available(self, target: str) -> bool:
        ws = self._get_ws()
        if ws is None:
            return False
        try:
            # is_device_connected 是【同步】方法(transport/websocket_server.py:337)。
            # 之前写成 await ws.is_device_connected(...),await 一个 bool 会抛
            # TypeError: object bool can't be used in 'await' expression,再被下面
            # 的 except 吞成 False —— 于是无论设备在不在线,websocket 传输都永远
            # 报"不可用",选路时被直接跳过。
            result = ws.is_device_connected(target)
            if inspect.isawaitable(result):  # 兼容将来改成 async 的实现
                result = await result
            return bool(result)
        except Exception:
            return False
