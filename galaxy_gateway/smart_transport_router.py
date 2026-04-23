"""
galaxy_gateway/smart_transport_router.py — Smart Transport Router
  (Legacy Compatibility Module — PR-M)

.. deprecated:: PR-M
    This module (``galaxy_gateway.smart_transport_router``) is a **legacy
    compatibility surface** retained for backward compatibility only.

    ``SmartTransportRouter`` is a pre-canonical transport-selection helper
    that chooses between WebRTC, Scrcpy, ADB, and HTTP outside the
    canonical ``DeviceRouter → galaxy_gateway.routing.dispatch`` pipeline.
    It does not produce a ``TaskEnvelope`` and does not route through
    ``CommandRouter.route_envelope()``, making it a parallel authority
    that can silently bypass canonical dispatch decisions.

    Canonical replacement::

        galaxy_gateway.device_router.DeviceRouter.route_task()
        → galaxy_gateway.routing.dispatch.dispatch_to_websocket()

    New code must not instantiate ``SmartTransportRouter`` as a primary
    transport-selection authority.  Route through ``DeviceRouter.route_task``
    which delegates to the canonical ``galaxy_gateway.routing`` layer.

    See ``core.orchestration_authority.legacy_paths`` for the registry entry
    (``galaxy_gateway.smart_transport_router.SmartTransportRouter``).

SmartTransportRouter - 智能传输路由（Legacy Compat — 仅保留向后兼容性）

功能：
1. 根据任务类型、网络状况和设备状态，自动选择最佳的屏幕内容传输方式
2. 支持多种传输协议：WebRTC、Scrcpy、ADB、HTTP
3. 支持多种网络层：Tailscale、直连
4. 支持多种控制信令：MQTT、WebSocket、HTTP

版本：1.0.0
日期：2026-01-22
作者：Manus AI
"""

import logging
import os
import asyncio
import httpx
from typing import Callable, List, Optional, Dict, Any, Literal
from enum import Enum
from pydantic import BaseModel
from core.port_config import get_service_port
from core.multimodal.multimodal_events import TransportFallbackEvent, MultimodalEvent

logger = logging.getLogger(__name__)

# ============================================================================
# 传输方式枚举
# ============================================================================

class TransportMethod(str, Enum):
    """传输方式"""
    WEBRTC = "webrtc"           # 实时视频流（低延迟、高质量）
    SCRCPY = "scrcpy"           # 高帧率屏幕镜像（需要 ADB）
    ADB_SCREENSHOT = "adb"      # ADB 截图（低功耗、静态）
    HTTP_SCREENSHOT = "http"    # HTTP 截图（通用、简单）
    
class NetworkLayer(str, Enum):
    """网络层"""
    TAILSCALE = "tailscale"     # Tailscale VPN
    DIRECT = "direct"           # 直连（局域网或公网）
    
class SignalMethod(str, Enum):
    """控制信令方式"""
    MQTT = "mqtt"               # MQTT（轻量级、低功耗）
    WEBSOCKET = "websocket"     # WebSocket（双向、实时）
    HTTP = "http"               # HTTP（简单、通用）

# ============================================================================
# 数据模型
# ============================================================================

class TransportRequest(BaseModel):
    """传输请求"""
    device_id: str                                  # 设备 ID
    task_type: Literal["static", "dynamic", "interactive"]  # 任务类型
    quality: Literal["low", "medium", "high"] = "medium"    # 质量要求
    realtime: bool = False                          # 是否需要实时
    preferred_method: Optional[TransportMethod] = None      # 首选方式
    use_gateway: bool = False                       # 当 True 且 method=webrtc 时返回网关 WS 信令 URL
    
class TransportResponse(BaseModel):
    """传输响应"""
    success: bool
    method: TransportMethod
    network: NetworkLayer
    signal: SignalMethod
    endpoint: str
    metadata: Dict[str, Any] = {}

# ============================================================================
# SmartTransportRouter 核心
# ============================================================================

class SmartTransportRouter:
    """Legacy compatibility transport-selection helper (PR-M).

    .. deprecated:: PR-M
        ``SmartTransportRouter`` is a LEGACY COMPAT TRANSPORT SELECTOR.
        It selects between WebRTC, Scrcpy, ADB, and HTTP outside the
        canonical DeviceRouter → galaxy_gateway.routing.dispatch pipeline.
        New code must route through ``DeviceRouter.route_task()`` which
        delegates to ``galaxy_gateway.routing.dispatch.dispatch_to_websocket``.

    智能传输路由（legacy compat — 仅保留向后兼容性）
    """
    
    def __init__(self):
        try:
            from core.orchestration_authority.legacy_paths import emit_legacy_guardrail
            emit_legacy_guardrail(
                "galaxy_gateway.smart_transport_router.SmartTransportRouter"
            )
        except Exception:
            pass
        # 节点端点配置
        self.nodes = {
            "webrtc": os.getenv("NODE_95_URL", "http://localhost:8095"),
            "scrcpy": os.getenv("NODE_34_URL", "http://localhost:8034"),
            "adb": os.getenv("NODE_33_URL", "http://localhost:8033"),
            "mqtt": os.getenv("NODE_41_URL", "http://localhost:8041"),
        }
        
        # Tailscale 配置
        self.tailscale_enabled = os.getenv("TAILSCALE_ENABLED", "false").lower() == "true"
        self.tailscale_domain = os.getenv("TAILSCALE_DOMAIN", "")

        # 可选传输通道开关（只有在明确启用时才返回直连 Node 端点）
        self.webrtc_enabled = os.getenv("GALAXY_ENABLE_WEBRTC", "false").lower() == "true"
        self.scrcpy_enabled = os.getenv("GALAXY_ENABLE_SCRCPY", "false").lower() == "true"
        self.mqtt_enabled = os.getenv("GALAXY_ENABLE_MQTT", "false").lower() == "true"

        # 统一 Gateway WS 入口（AIP v3）
        self.gateway_url = os.getenv(
            "GALAXY_GATEWAY_URL",
            os.getenv("GATEWAY_URL", f"http://localhost:{get_service_port('state_machine')}")
        ).rstrip("/")
        
        # 设备状态缓存
        self.device_status = {}

        # PR-7: event listeners for fallback / transport events
        self._event_listeners: List[Callable[[MultimodalEvent], None]] = []
        
    def add_event_listener(
        self, listener: Callable[[MultimodalEvent], None]
    ) -> None:
        """Register a listener for transport :class:`MultimodalEvent` objects.

        Listeners receive :class:`TransportFallbackEvent` when WebRTC is
        unavailable and the router falls back to a screenshot-based method.
        """
        self._event_listeners.append(listener)

    async def route(self, request: TransportRequest) -> TransportResponse:
        """
        智能路由：根据请求选择最佳传输方式
        
        默认路由返回 Gateway WS 端点（AIP v3）。
        仅当对应通道被明确启用（GALAXY_ENABLE_WEBRTC/SCRCPY/MQTT）时，
        才返回直连 Node 端点。

        PR-7: WebRTC is preferred for real-time/interactive tasks when
        available.  A :class:`TransportFallbackEvent` is emitted whenever
        the router degrades from WebRTC to a screenshot-based method.
        """
        
        # PR-7: When WebRTC is the preferred method for real-time tasks but is
        # unavailable, determine the intended method before selection so a
        # fallback event can be emitted.
        prefer_webrtc: bool = (
            self.webrtc_enabled and request.task_type in ("dynamic", "interactive")
        )

        method = await self._select_transport_method(request)

        # Emit a fallback event when WebRTC was the intended method but was
        # not selected (e.g., node unreachable or channel disabled).
        if prefer_webrtc and method != TransportMethod.WEBRTC:
            self._emit_event(
                TransportFallbackEvent(
                    from_method="webrtc",
                    to_method=method.value,
                    reason="webrtc_unavailable_or_unreachable",
                    device_id=request.device_id,
                )
            )
            logger.info(
                "TransportRouter: WebRTC unavailable for device=%s; falling back to %s",
                request.device_id,
                method.value,
            )
        
        # 2. 确定网络层
        network = await self._select_network_layer(request.device_id)
        
        # 3. 确定控制信令
        signal = await self._select_signal_method(request.task_type)
        
        # 4. 构建端点
        endpoint = await self._build_endpoint(method, request.device_id, network, request.use_gateway)
        
        # 5. 返回响应
        return TransportResponse(
            success=True,
            method=method,
            network=network,
            signal=signal,
            endpoint=endpoint,
            metadata={
                "device_id": request.device_id,
                "task_type": request.task_type,
                "quality": request.quality,
                "realtime": request.realtime
            }
        )

    def _emit_event(self, event: MultimodalEvent) -> None:
        """Dispatch a :class:`MultimodalEvent` to all registered listeners."""
        for listener in list(self._event_listeners):
            try:
                listener(event)
            except Exception as exc:
                logger.debug("TransportRouter event listener error: %s", exc)
    
    async def _select_transport_method(self, request: TransportRequest) -> TransportMethod:
        """选择传输方式
        
        默认回退到 HTTP_SCREENSHOT（通过 Gateway）。
        仅当对应通道已启用且节点可达时才选择 WebRTC/Scrcpy。
        """
        
        # 如果用户指定了首选方式，先检查该通道是否已启用
        if request.preferred_method:
            if self._is_channel_enabled(request.preferred_method) and \
               await self._is_method_available(request.preferred_method, request.device_id):
                return request.preferred_method
        
        # 根据任务类型和需求自动选择（仅当通道已启用时）
        if request.task_type == "dynamic" and request.realtime:
            if self.webrtc_enabled and await self._is_method_available(TransportMethod.WEBRTC, request.device_id):
                return TransportMethod.WEBRTC
            if self.scrcpy_enabled and await self._is_method_available(TransportMethod.SCRCPY, request.device_id):
                return TransportMethod.SCRCPY
            
        elif request.task_type == "dynamic":
            if self.scrcpy_enabled and await self._is_method_available(TransportMethod.SCRCPY, request.device_id):
                return TransportMethod.SCRCPY
            
        elif request.task_type == "interactive":
            if self.webrtc_enabled and await self._is_method_available(TransportMethod.WEBRTC, request.device_id):
                return TransportMethod.WEBRTC
            
        elif request.task_type == "static" and request.quality == "high":
            if self.scrcpy_enabled and await self._is_method_available(TransportMethod.SCRCPY, request.device_id):
                return TransportMethod.SCRCPY
        
        # 默认：通过 Gateway 的 HTTP 截图（无需直连 Node，最通用）
        return TransportMethod.HTTP_SCREENSHOT

    def _is_channel_enabled(self, method: TransportMethod) -> bool:
        """检查传输通道是否已通过环境变量明确启用"""
        if method == TransportMethod.WEBRTC:
            return self.webrtc_enabled
        if method == TransportMethod.SCRCPY:
            return self.scrcpy_enabled
        if method == TransportMethod.ADB_SCREENSHOT:
            return True  # ADB 始终允许（本地操作）
        if method == TransportMethod.HTTP_SCREENSHOT:
            return True  # HTTP 截图始终允许（通用）
        return False
    
    async def _is_method_available(self, method: TransportMethod, device_id: str) -> bool:
        """检查传输方式是否可用"""
        try:
            node_url = self.nodes.get(method.value)
            if not node_url:
                return False
            
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(f"{node_url}/health")
                if response.status_code == 200:
                    data = response.json()
                    return data.get("status") in ["healthy", "ok"]
        except Exception:
            pass
        
        return False
    
    async def _select_network_layer(self, device_id: str) -> NetworkLayer:
        """选择网络层"""
        if self.tailscale_enabled:
            return NetworkLayer.TAILSCALE
        return NetworkLayer.DIRECT
    
    async def _select_signal_method(self, task_type: str) -> SignalMethod:
        """选择控制信令方式"""
        if task_type in ["dynamic", "interactive"]:
            # 动态/交互式任务使用 WebSocket（实时双向）
            return SignalMethod.WEBSOCKET
        elif task_type == "static":
            # 静态任务使用 MQTT（轻量级）
            return SignalMethod.MQTT
        return SignalMethod.HTTP
    
    async def _build_endpoint(self, method: TransportMethod, device_id: str, network: NetworkLayer, use_gateway: bool = False) -> str:
        """构建端点

        WebRTC/Scrcpy 通道如未启用，始终返回 Gateway WS 端点（AIP v3）。
        当通道已启用时，才返回直连 Node 端点。
        """
        # 对于 HTTP_SCREENSHOT，始终通过 Gateway
        if method == TransportMethod.HTTP_SCREENSHOT:
            ws_url = self.gateway_url.replace("https://", "wss://").replace("http://", "ws://")
            return f"{ws_url}/ws/device/{device_id}"

        if method == TransportMethod.WEBRTC:
            if use_gateway or not self.webrtc_enabled:
                # Return the gateway WebSocket signaling URL (AIP v3)
                ws_url = self.gateway_url.replace("https://", "wss://").replace("http://", "ws://")
                return f"{ws_url}/ws/device/{device_id}"
            # WebRTC 通道明确启用时返回 Node_95 直连端点
            node_url = self.nodes.get("webrtc", "")
            if network == NetworkLayer.TAILSCALE and self.tailscale_domain:
                node_url = node_url.replace("localhost", self.tailscale_domain)
            return f"{node_url}/capture?device_id={device_id}"

        base_url = self.nodes.get(method.value, "")
        
        if network == NetworkLayer.TAILSCALE and self.tailscale_domain:
            # 使用 Tailscale 域名
            base_url = base_url.replace("localhost", self.tailscale_domain)
        
        return f"{base_url}/capture?device_id={device_id}"

# ============================================================================
# FastAPI 接口
# ============================================================================

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from nodes.common.cors_config import get_cors_origins

app = FastAPI(title="SmartTransportRouter", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

router = SmartTransportRouter()

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "SmartTransportRouter",
        "version": "1.0.0"
    }

@app.post("/route", response_model=TransportResponse)
async def route_transport(request: TransportRequest):
    """智能路由接口"""
    try:
        return await router.route(request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/methods")
async def list_methods():
    """列出所有支持的传输方式"""
    return {
        "methods": [m.value for m in TransportMethod],
        "networks": [n.value for n in NetworkLayer],
        "signals": [s.value for s in SignalMethod]
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8096)
