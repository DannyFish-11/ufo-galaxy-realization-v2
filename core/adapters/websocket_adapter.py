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
        """取 WebSocketManager 实例 —— 只认构造时显式注入的那个。

        这里【刻意不做】任何隐式兜底解析:

        1. 原代码兜底 import 的是 ``galaxy_gateway.connection_manager``,这个模块
           根本不存在(实测 ImportError),异常还被静默吞掉。也就是说这条兜底自古
           以来就没生效过,适配器在不显式注入时一直是完全惰性的 —— 现在的行为与
           那时【一致】,只是不再靠一个必然失败的 import 去实现。
        2. 真正发布实例的位置是 bootstrap/lifecycle.py:94/102,但接上它没有意义:
           WebSocketManager.connect() 的唯一调用方是同文件的 handle_connection(),
           而 handle_connection() 全仓无人调用,所以 manager.connections 恒为空,
           这条传输永远投递不出去。给一个收不到任何连接的 manager 建立隐式连线,
           只会让调用方误以为 websocket 这条路可用。

        因此:要用这条传输,请在构造时显式传入 ws_manager(调用方自己清楚它是否
        真的能投递);不显式传就保持惰性。
        """
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
