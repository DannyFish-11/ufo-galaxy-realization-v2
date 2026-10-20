"""galaxy_gateway/bootstrap/transports.py — 一个进程装一次传输适配器(AIPTransport,跨设备整体方案阶段 6)。

一种消息(AIP v3)、多种传输、自动选路:``core.aip_transport`` 按消息需求与链路历史挑一条传输发出去。可这些传输
此前只在**独立运行网关**时(``lifecycle.lifespan`` 的 Phase 8)装上;桌面版(``main.py`` → 主 app 挂载网关)
刻意不跑那段 lifespan,于是**一个适配器都没有**:每次 ``get_aip_transport().send`` 都回「没有可用传输」,
调用方再自己直接写 WebSocket。TCP 直连、UDP、多跳 mesh、Tailscale 点对点在桌面版上都不存在。

现在两条启动路径都调这一个函数:

* 同一个进程只装一次(第二次调直接返回上次的结果),不会重复注册、重复绑端口;
* 「websocket」这条传输走规范设备入口上真的连接(``UnifiedConnectionManager``)。此前它接的是网关自己的
  ``WebSocketManager`` —— 那里从没有任何连接(见 ``core/adapters/websocket_adapter.py``),这条传输从没投递成功过;
* 端口被占(同一台机器上另一个 Galaxy 进程已经在听)时,那个适配器只发不收,日志里说清是哪个端口、怎么换
  (``GALAXY_AIP_TCP_PORT`` / ``GALAXY_AIP_UDP_PORT`` / ``GALAXY_MESH_PORT``),不让启动失败;
* MQTT 只在配了 ``MQTT_BROKER`` 时装(没配就是后台对着 localhost:1883 无休止地重连)。

NATS 不在这里:它是任务分发总线,和传输并列,不是一个传输。
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger("Galaxy.Gateway.Transports")

#: 本进程装好的结果(适配器 → 状态);装过就不再装。
_status: Dict[str, str] = {}


class CanonicalSockets:
    """把规范设备入口上真的连接包成 ``WebSocketAdapter`` 要的样子(``send_message`` / ``is_device_connected``)。"""

    @staticmethod
    def _ucm() -> Any:
        from core.unified.connection_manager import get_unified_connection_manager

        return get_unified_connection_manager()

    async def send_message(self, device_id: str, message: Any) -> bool:
        frame = message.model_dump(mode="json") if hasattr(message, "model_dump") else dict(message)
        # 选路用的内部标记(``_transport`` 等)不出现在 AIP v3 帧里;直接写 WebSocket 的那条兜底路径也从不带它们
        frame = {k: v for k, v in frame.items() if not str(k).startswith("_")}
        return bool(await self._ucm().send_to_device(device_id, frame))

    def is_device_connected(self, device_id: str) -> bool:
        return bool(self._ucm().is_device_connected(device_id))


def _port(name: str, default: str) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return int(default)


async def _listen(status: Dict[str, str], name: str, start: Any, port: int, env: str) -> bool:
    try:
        await start()
    except OSError as exc:
        status[name] = f"send-only: port {port} busy"
        logger.warning(
            "传输 %s 的端口 %d 被占(这台机器上可能还有一个 Galaxy 进程):只发不收。要两边都收,给其中一个设 %s=<别的端口>(%s)",
            name,
            port,
            env,
            exc,
        )
        return False
    status[name] = f"listening:{port}"
    return True


async def register_transport_adapters(message_handler: Optional[Any] = None) -> Dict[str, str]:
    """给本进程的 AIPTransport 装上全部传输适配器;返回每个适配器的状态。同一进程第二次调用直接返回上次的结果。

    ``message_handler``:网关的 ``MessageHandler``;TCP 直连与 mesh 终点收到的 AIP 帧交给它(没有就只发不收)。
    """
    if _status:
        return dict(_status)
    from core.adapters import (
        BLEAdapter,
        CANBusAdapter,
        DBusAdapter,
        MQTTAdapter,
        SerialAdapter,
        TCPAdapter,
        UDPAdapter,
        WebSocketAdapter,
    )
    from core.aip_transport import get_aip_transport

    transport = get_aip_transport()
    status: Dict[str, str] = {}

    transport.register_adapter(WebSocketAdapter(CanonicalSockets()))
    status["websocket"] = "registered"

    # Tailscale 点对点:在同一个 tailnet 里的设备不经网关直连
    try:
        from core.adapters.tailscale_p2p_adapter import TailscaleP2PAdapter

        ts = TailscaleP2PAdapter()
        if await ts.initialize():
            transport.register_adapter(ts)
            status["tailscale_p2p"] = "registered"
            try:
                await ts.start_server()
                status["tailscale_p2p"] = "listening"
            except Exception as exc:  # noqa: BLE001 — 只发不收
                logger.warning("Tailscale 点对点入站没起来(只发不收): %s", exc)
        else:
            status["tailscale_p2p"] = "skipped: tailscale not available"
    except Exception as exc:  # noqa: BLE001
        status["tailscale_p2p"] = f"skipped: {exc}"

    if os.environ.get("MQTT_BROKER", "").strip():
        transport.register_adapter(MQTTAdapter())
        status["mqtt"] = "registered"
    else:
        status["mqtt"] = "skipped: MQTT_BROKER not set"

    tcp_port = _port("GALAXY_AIP_TCP_PORT", "19421")
    tcp = TCPAdapter(local_port=tcp_port)
    udp_port = _port("GALAXY_AIP_UDP_PORT", "19422")
    udp = UDPAdapter(local_port=udp_port)
    for adapter in (tcp, udp, BLEAdapter(), SerialAdapter(), DBusAdapter(), CANBusAdapter()):
        transport.register_adapter(adapter)
        status[adapter.transport_type] = "registered"

    if await _listen(status, "tcp", tcp.start_server, tcp_port, "GALAXY_AIP_TCP_PORT"):
        # 在局域网里广播这个 TCP 入口(lan_discovery 按 _galaxy-aip3 找对端)。zeroconf 注册是阻塞的、
        # 这里要好几秒:放到后台线程,不卡住启动、也不卡住事件循环
        threading.Thread(target=tcp.register_local_service, args=("local",), daemon=True).start()
        if message_handler is not None:
            tcp.set_message_handler(_tcp_inbound(message_handler))
    await _listen(status, "udp", udp.start, udp_port, "GALAXY_AIP_UDP_PORT")

    # AODV 多跳 mesh:peers 来自局域网发现镜像进 UDM 的 mDNS 记录;没有 peers 时它不可用,单机部署下沉默
    try:
        from core.adapters.mesh_routing_adapter import MeshRoutingAdapter

        mesh_port = _port("GALAXY_MESH_PORT", "19422")
        mesh = MeshRoutingAdapter(node_id=os.getenv("GALAXY_MESH_NODE_ID", "gateway"), local_port=mesh_port)
        if await _listen(status, "mesh", mesh.start_server, mesh_port, "GALAXY_MESH_PORT"):
            mesh.refresh_neighbors_from_discovery()
            if message_handler is not None:
                mesh.set_message_handler(_mesh_inbound(message_handler))
            # 信封桥:发现型邻接指向对端普通 tcp 端口,mesh 信封帧会打到 tcp 适配器
            tcp.set_envelope_handler(mesh.handle_envelope)
        transport.register_adapter(mesh)
    except Exception as exc:  # noqa: BLE001
        status["mesh"] = f"skipped: {exc}"

    _status.update(status)
    logger.info("AIPTransport 传输适配器: %s(选路候选:%s)", status, transport.list_adapters())
    return dict(status)


def _tcp_inbound(message_handler: Any) -> Any:
    async def on_tcp_message(device_id: str, message: dict) -> Optional[dict]:
        from galaxy_gateway.protocol import parse_message

        if not str(message.get("type", "") or ""):
            return None  # 无类型帧(如探测)不进处理器
        try:
            parsed = parse_message(message)
        except Exception as exc:  # noqa: BLE001
            # 任何客户端都能对这个端口发垃圾 —— 每条刷一次 warning 等于把日志交给对端
            logger.debug("TCP 入站帧不符合 AIP v3,丢弃: %s", exc)
            return None
        response = await message_handler.handle_message(device_id or "tcp_unknown", parsed)
        if response is None:
            return None
        return response.model_dump(mode="json") if hasattr(response, "model_dump") else response

    return on_tcp_message


def _mesh_inbound(message_handler: Any) -> Any:
    async def on_mesh_message(aip: dict, meta: dict) -> None:
        from galaxy_gateway.protocol import parse_message

        await message_handler.handle_message(str(meta.get("src", "") or "mesh_unknown"), parse_message(aip))

    return on_mesh_message


async def close_transport_adapters() -> None:
    """关掉本进程装的适配器的监听(测试与进程退出用);之后可以再装一次。"""
    from core.aip_transport import get_aip_transport

    transport = get_aip_transport()
    for name in list(_status):
        adapter = transport.get_adapter(name)
        close = getattr(adapter, "close", None)
        if close is not None:
            try:
                await close()
            except Exception as exc:  # noqa: BLE001
                logger.debug("关传输 %s 失败: %s", name, exc)
        transport.unregister_adapter(name)
    _status.clear()
