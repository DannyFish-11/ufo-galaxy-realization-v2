"""
Galaxy WebSocket服务器
处理Android客户端和Windows客户端的连接
实现UI与L4主循环的双向通信
"""

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

try:
    import aiohttp
    from aiohttp import web
    AIOHTTP_AVAILABLE = True
except ImportError:
    aiohttp = None  # type: ignore
    web = None  # type: ignore
    AIOHTTP_AVAILABLE = False

try:
    import websockets
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    websockets = None  # type: ignore
    WEBSOCKETS_AVAILABLE = False

# 导入L4主循环和事件总线
import sys
import os as _os
_PROJECT_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

from core.galaxy_main_loop_l4_enhanced import GalaxyMainLoopL4Enhanced, get_galaxy_loop
from integration.event_bus import EventBus, EventType, UIGalaxyEvent, event_bus
from integration.event_bus import safe_json_dumps

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOG_FORMAT: str = "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
DEFAULT_LOG_LEVEL: str = os.environ.get("INTEGRATION_LOG_LEVEL", "INFO")

# WebSocket heartbeat interval in seconds (from env var)
WS_HEARTBEAT_INTERVAL_SECONDS: int = int(os.environ.get("INTEGRATION_WS_HEARTBEAT_INTERVAL", "30"))

# Maximum number of concurrent WebSocket connections
WS_MAX_CONNECTIONS: int = int(os.environ.get("INTEGRATION_WS_MAX_CONNECTIONS", "100"))

# Connection rate limit: maximum new connections per minute
WS_RATE_LIMIT_PER_MINUTE: int = int(os.environ.get("INTEGRATION_WS_RATE_LIMIT", "60"))

# L4 main loop configuration
L4_CYCLE_INTERVAL_SECONDS: float = float(os.environ.get("INTEGRATION_L4_CYCLE_INTERVAL", "2.0"))
L4_AUTO_SCAN_INTERVAL_SECONDS: float = float(os.environ.get("INTEGRATION_L4_AUTO_SCAN_INTERVAL", "300.0"))
L4_READY_TIMEOUT_SECONDS: float = float(os.environ.get("INTEGRATION_L4_READY_TIMEOUT", "10.0"))

# Config hot-reload check interval in seconds
CONFIG_RELOAD_INTERVAL_SECONDS: int = int(os.environ.get("INTEGRATION_CONFIG_RELOAD_INTERVAL", "10"))
CONFIG_WATCH_PATHS: List[str] = _os.environ.get(
    "INTEGRATION_CONFIG_WATCH_PATHS",
    "config/config.json,config/topology.json"
).split(",")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=getattr(logging, DEFAULT_LOG_LEVEL.upper(), logging.INFO),
    format=LOG_FORMAT
)
logger = logging.getLogger("WebSocketServer")


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def generate_request_id() -> str:
    """Generate a unique request ID for tracking requests across services.

    Returns:
        A unique request identifier string.
    """
    return f"req_{uuid.uuid4().hex[:16]}"


def make_error_response(message: str, status_code: int = 400, request_id: str = "") -> Dict[str, Any]:
    """Create a standardized error response with request_id.

    Args:
        message: Error message.
        status_code: HTTP status code.
        request_id: Request tracking ID (auto-generated if empty).

    Returns:
        Error response dictionary including request_id.
    """
    return {
        "type": "error",
        "message": message,
        "status_code": status_code,
        "request_id": request_id or generate_request_id(),
        "timestamp": datetime.now().isoformat()
    }


# ---------------------------------------------------------------------------
# IntegrationWSManager
# ---------------------------------------------------------------------------

class IntegrationWSManager:
    """WebSocket连接管理器 - 管理活跃连接、客户端信息和连接限制"""

    def __init__(
        self,
        max_connections: int = WS_MAX_CONNECTIONS,
        heartbeat_interval: int = WS_HEARTBEAT_INTERVAL_SECONDS
    ) -> None:
        self.max_connections: int = max_connections
        self.heartbeat_interval: int = heartbeat_interval
        self.active_connections: Set[websockets.WebSocketServerProtocol] = set()
        self.client_info: Dict[websockets.WebSocketServerProtocol, Dict[str, Any]] = {}
        self._connection_count: int = 0
        self._rate_limit_window: List[float] = []

    async def connect(
        self,
        websocket: websockets.WebSocketServerProtocol,
        client_type: str = "unknown"
    ) -> bool:
        """接受新连接，如果超过最大连接数则拒绝。

        Args:
            websocket: WebSocket server protocol instance.
            client_type: Type of the connecting client.

        Returns:
            True if connection was accepted, False if rejected.
        """
        # Check max connections limit
        if len(self.active_connections) >= self.max_connections:
            logger.warning("Connection rejected: max connections (%d) reached", self.max_connections)
            await websocket.close(code=1013, reason="Server overloaded: max connections reached")
            return False

        # Check rate limit
        now: float = time.time()
        self._rate_limit_window = [
            t for t in self._rate_limit_window if now - t < 60.0
        ]
        if len(self._rate_limit_window) >= WS_RATE_LIMIT_PER_MINUTE:
            logger.warning("Connection rejected: rate limit exceeded")
            await websocket.close(code=1013, reason="Rate limit exceeded")
            return False

        self._rate_limit_window.append(now)
        self.active_connections.add(websocket)
        self.client_info[websocket] = {
            "client_type": client_type,
            "connected_at": datetime.now().isoformat(),
            "message_count": 0,
            "request_id": generate_request_id()
        }
        self._connection_count += 1
        logger.info("Client connected: %s (%s)", client_type, websocket.remote_address)
        return True

    def disconnect(self, websocket: websockets.WebSocketServerProtocol) -> None:
        """断开连接"""
        self.active_connections.discard(websocket)
        info: Dict[str, Any] = self.client_info.pop(websocket, {})
        logger.info("Client disconnected: %s", info.get("client_type", "unknown"))

    async def send_to_client(
        self,
        websocket: websockets.WebSocketServerProtocol,
        message: Dict[str, Any]
    ) -> None:
        """发送消息给特定客户端（使用安全序列化）"""
        try:
            await websocket.send(safe_json_dumps(message))
            if websocket in self.client_info:
                self.client_info[websocket]["message_count"] += 1
        except Exception as exc:
            logger.error("Send message failed: %s", exc)

    async def broadcast(
        self,
        message: Dict[str, Any],
        exclude: Optional[websockets.WebSocketServerProtocol] = None
    ) -> None:
        """广播消息给所有客户端（使用安全序列化）"""
        disconnected: List[websockets.WebSocketServerProtocol] = []
        for connection in list(self.active_connections):
            if connection != exclude:
                try:
                    await connection.send(safe_json_dumps(message))
                except Exception as exc:
                    logger.error("Broadcast message failed: %s", exc)
                    disconnected.append(connection)

        # 清理断开的连接
        for conn in disconnected:
            self.disconnect(conn)

    async def broadcast_to_type(self, client_type: str, message: Dict[str, Any]) -> None:
        """广播消息给特定类型的客户端（使用安全序列化）"""
        disconnected: List[websockets.WebSocketServerProtocol] = []
        for connection in list(self.active_connections):
            info: Dict[str, Any] = self.client_info.get(connection, {})
            if info.get("client_type") == client_type:
                try:
                    await connection.send(safe_json_dumps(message))
                except Exception as exc:
                    logger.error("Broadcast to type failed: %s", exc)
                    disconnected.append(connection)

        for conn in disconnected:
            self.disconnect(conn)

    async def send_heartbeat(self) -> None:
        """Send periodic heartbeat ping to all connected clients."""
        if not self.heartbeat_interval or self.heartbeat_interval <= 0:
            return
        while True:
            await asyncio.sleep(self.heartbeat_interval)
            heartbeat_msg: Dict[str, Any] = {
                "type": "heartbeat",
                "timestamp": datetime.now().isoformat()
            }
            await self.broadcast(heartbeat_msg)

    def get_stats(self) -> Dict[str, Any]:
        """获取连接统计"""
        client_types: Dict[str, int] = {}
        for info in self.client_info.values():
            client_type: str = info.get("client_type", "unknown")
            client_types[client_type] = client_types.get(client_type, 0) + 1

        return {
            "total_connections": len(self.active_connections),
            "max_connections": self.max_connections,
            "total_accepted": self._connection_count,
            "client_types": client_types
        }


# ---------------------------------------------------------------------------
# GalaxyWebSocketServer
# ---------------------------------------------------------------------------

class GalaxyWebSocketServer:
    """
    Galaxy WebSocket服务器
    处理客户端连接和L4主循环的集成
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8080,
        heartbeat_interval: int = WS_HEARTBEAT_INTERVAL_SECONDS,
        max_connections: int = WS_MAX_CONNECTIONS
    ) -> None:
        self.host: str = host
        self.port: int = port
        self.heartbeat_interval: int = heartbeat_interval
        self.connection_manager: IntegrationWSManager = IntegrationWSManager(
            max_connections=max_connections,
            heartbeat_interval=heartbeat_interval
        )
        self.galaxy_loop: Optional[GalaxyMainLoopL4Enhanced] = None
        self._running: bool = False
        self._server: Optional[Any] = None
        self._heartbeat_task: Optional[asyncio.Task] = None

        # 订阅事件总线
        self._subscribe_to_events()

    def _subscribe_to_events(self) -> None:
        """订阅事件总线事件"""
        event_bus.subscribe(EventType.GOAL_DECOMPOSITION_STARTED, self._on_decomposition_started, async_callback=True)
        event_bus.subscribe(EventType.GOAL_DECOMPOSITION_COMPLETED, self._on_decomposition_completed, async_callback=True)
        event_bus.subscribe(EventType.PLAN_GENERATION_STARTED, self._on_plan_started, async_callback=True)
        event_bus.subscribe(EventType.PLAN_GENERATION_COMPLETED, self._on_plan_completed, async_callback=True)
        event_bus.subscribe(EventType.ACTION_EXECUTION_STARTED, self._on_action_started, async_callback=True)
        event_bus.subscribe(EventType.ACTION_EXECUTION_PROGRESS, self._on_action_progress, async_callback=True)
        event_bus.subscribe(EventType.ACTION_EXECUTION_COMPLETED, self._on_action_completed, async_callback=True)
        event_bus.subscribe(EventType.TASK_COMPLETED, self._on_task_completed, async_callback=True)
        event_bus.subscribe(EventType.ERROR_OCCURRED, self._on_error, async_callback=True)

    async def _on_decomposition_started(self, event: UIGalaxyEvent) -> None:
        """目标分解开始事件处理"""
        await self.connection_manager.broadcast({
            "event_type": "GOAL_DECOMPOSITION_STARTED",
            "data": event.data,
            "timestamp": event.timestamp.isoformat()
        })

    async def _on_decomposition_completed(self, event: UIGalaxyEvent) -> None:
        """目标分解完成事件处理"""
        await self.connection_manager.broadcast({
            "event_type": "GOAL_DECOMPOSITION_COMPLETED",
            "data": event.data,
            "timestamp": event.timestamp.isoformat()
        })

    async def _on_plan_started(self, event: UIGalaxyEvent) -> None:
        """计划生成开始事件处理"""
        await self.connection_manager.broadcast({
            "event_type": "PLAN_GENERATION_STARTED",
            "data": event.data,
            "timestamp": event.timestamp.isoformat()
        })

    async def _on_plan_completed(self, event: UIGalaxyEvent) -> None:
        """计划生成完成事件处理"""
        await self.connection_manager.broadcast({
            "event_type": "PLAN_GENERATION_COMPLETED",
            "data": event.data,
            "timestamp": event.timestamp.isoformat()
        })

    async def _on_action_started(self, event: UIGalaxyEvent) -> None:
        """动作执行开始事件处理"""
        await self.connection_manager.broadcast({
            "event_type": "ACTION_EXECUTION_STARTED",
            "data": event.data,
            "timestamp": event.timestamp.isoformat()
        })

    async def _on_action_progress(self, event: UIGalaxyEvent) -> None:
        """动作执行进度事件处理"""
        await self.connection_manager.broadcast({
            "event_type": "ACTION_EXECUTION_PROGRESS",
            "data": event.data,
            "timestamp": event.timestamp.isoformat()
        })

    async def _on_action_completed(self, event: UIGalaxyEvent) -> None:
        """动作执行完成事件处理"""
        await self.connection_manager.broadcast({
            "event_type": "ACTION_EXECUTION_COMPLETED",
            "data": event.data,
            "timestamp": event.timestamp.isoformat()
        })

    async def _on_task_completed(self, event: UIGalaxyEvent) -> None:
        """任务完成事件处理"""
        await self.connection_manager.broadcast({
            "event_type": "TASK_COMPLETED",
            "data": event.data,
            "timestamp": event.timestamp.isoformat()
        })

    async def _on_error(self, event: UIGalaxyEvent) -> None:
        """错误事件处理"""
        await self.connection_manager.broadcast({
            "event_type": "ERROR_OCCURRED",
            "data": event.data,
            "timestamp": event.timestamp.isoformat()
        })

    async def handle_client(
        self,
        websocket: websockets.WebSocketServerProtocol,
        path: str
    ) -> None:
        """处理客户端连接"""
        client_type: str = "unknown"

        try:
            # 等待客户端发送身份验证/类型信息
            auth_message = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            auth_data: Dict[str, Any] = json.loads(auth_message)
            client_type = auth_data.get("client_type", "unknown")

            # 接受连接 (with max connection limit check)
            accepted: bool = await self.connection_manager.connect(websocket, client_type)
            if not accepted:
                return

            # 发送欢迎消息
            await self.connection_manager.send_to_client(websocket, {
                "type": "welcome",
                "message": "Connected to Galaxy Server",
                "server_time": datetime.now().isoformat(),
                "request_id": generate_request_id()
            })

            # 处理客户端消息
            async for message in websocket:
                try:
                    data: Dict[str, Any] = json.loads(message)
                    request_id: str = data.get("request_id") or generate_request_id()
                    await self._handle_message(websocket, data, request_id)
                except json.JSONDecodeError:
                    await self.connection_manager.send_to_client(
                        websocket, make_error_response("Invalid JSON format", status_code=400)
                    )
                except Exception as exc:
                    logger.error("Message handling error: %s", exc)
                    await self.connection_manager.send_to_client(
                        websocket, make_error_response(str(exc), status_code=500)
                    )

        except asyncio.TimeoutError:
            logger.warning("Client authentication timeout")
        except websockets.exceptions.ConnectionClosed:
            logger.info("Client connection closed")
        except Exception as exc:
            logger.error("Client handling error: %s", exc)
        finally:
            self.connection_manager.disconnect(websocket)

    async def _handle_message(
        self,
        websocket: websockets.WebSocketServerProtocol,
        data: Dict[str, Any],
        request_id: str
    ) -> None:
        """处理客户端消息，包含 request_id 追踪"""
        msg_type: str = data.get("type", "unknown")

        if msg_type == "goal_submit":
            # 处理目标提交（UI → L4 集成点）
            await self._handle_goal_submit(websocket, data, request_id)

        elif msg_type == "command":
            # 处理命令
            await self._handle_command(websocket, data, request_id)

        elif msg_type == "ping":
            # 心跳检测
            await self.connection_manager.send_to_client(websocket, {
                "type": "pong",
                "timestamp": datetime.now().isoformat(),
                "request_id": request_id
            })

        elif msg_type == "get_status":
            # 获取状态
            await self._handle_get_status(websocket, request_id)

        else:
            await self.connection_manager.send_to_client(
                websocket,
                make_error_response(f"Unknown message type: {msg_type}", status_code=400, request_id=request_id)
            )

    async def _handle_goal_submit(
        self,
        websocket: websockets.WebSocketServerProtocol,
        data: Dict[str, Any],
        request_id: str
    ) -> None:
        """
        处理目标提交（UI → L4 集成点）

        Args:
            websocket: WebSocket连接
            data: 消息数据
            request_id: 请求追踪ID
        """
        description: str = data.get("description", "")
        intent: Dict[str, Any] = data.get("intent", {})

        if not description:
            await self.connection_manager.send_to_client(
                websocket,
                make_error_response("Goal description is required", status_code=400, request_id=request_id)
            )
            return

        logger.info("Received goal submit: %s", description)

        # 提交到L4主循环
        if self.galaxy_loop:
            goal_id: str = self.galaxy_loop.receive_goal(description)

            await self.connection_manager.send_to_client(websocket, {
                "type": "goal_accepted",
                "goal_id": goal_id,
                "description": description,
                "message": "Goal submitted successfully",
                "request_id": request_id
            })
        else:
            await self.connection_manager.send_to_client(
                websocket,
                make_error_response("L4 main loop not available", status_code=503, request_id=request_id)
            )

    async def _handle_command(
        self,
        websocket: websockets.WebSocketServerProtocol,
        data: Dict[str, Any],
        request_id: str
    ) -> None:
        """处理命令"""
        command: str = data.get("command", "")
        params: Dict[str, Any] = data.get("params", {})

        logger.info("Received command: %s", command)

        # 处理各种命令
        if command == "wakeup":
            # 唤醒系统
            from system_integration.state_machine_ui_integration import wakeup_system
            success: bool = wakeup_system("websocket")
            await self.connection_manager.send_to_client(websocket, {
                "type": "command_result",
                "command": command,
                "success": success,
                "request_id": request_id
            })

        elif command == "get_stats":
            # 获取统计信息
            stats: Dict[str, Any] = self.connection_manager.get_stats()
            if self.galaxy_loop:
                stats["l4_status"] = self.galaxy_loop.get_status()

            await self.connection_manager.send_to_client(websocket, {
                "type": "command_result",
                "command": command,
                "data": stats,
                "request_id": request_id
            })

        else:
            await self.connection_manager.send_to_client(
                websocket,
                make_error_response(f"Unknown command: {command}", status_code=400, request_id=request_id)
            )

    async def _handle_get_status(
        self,
        websocket: websockets.WebSocketServerProtocol,
        request_id: str
    ) -> None:
        """处理获取状态请求"""
        status: Dict[str, Any] = {
            "server": {
                "connections": self.connection_manager.get_stats()
            }
        }

        if self.galaxy_loop:
            status["l4"] = self.galaxy_loop.get_status()

        await self.connection_manager.send_to_client(websocket, {
            "type": "status",
            "data": status,
            "request_id": request_id
        })

    async def start(self) -> None:
        """启动WebSocket服务器"""
        self._running = True

        # 启动L4主循环
        self.galaxy_loop = get_galaxy_loop({
            "cycle_interval": L4_CYCLE_INTERVAL_SECONDS,
            "auto_scan_interval": L4_AUTO_SCAN_INTERVAL_SECONDS
        })

        # 在后台启动L4主循环
        asyncio.create_task(self.galaxy_loop.start())

        # 等待L4主循环就绪（最多等待10秒）
        await self._wait_for_galaxy_loop_ready(timeout_sec=L4_READY_TIMEOUT_SECONDS)

        # 启动heartbeat sender
        if self.heartbeat_interval > 0:
            self._heartbeat_task = asyncio.create_task(self.connection_manager.send_heartbeat())

        # 启动WebSocket服务器
        self._server = await websockets.serve(
            self.handle_client,
            self.host,
            self.port
        )

        logger.info("WebSocket server started: ws://%s:%d", self.host, self.port)

        # 保持运行
        await self._server.wait_closed()

    async def _wait_for_galaxy_loop_ready(self, timeout_sec: float = 10.0) -> None:
        """等待L4主循环就绪，超时则记录警告但继续启动"""
        deadline: float = time.time() + timeout_sec
        while time.time() < deadline:
            if getattr(self.galaxy_loop, 'running', False):
                logger.info("L4 main loop ready")
                return
            await asyncio.sleep(0.1)
        logger.warning("L4 main loop ready timeout, continuing WebSocket server startup")

    async def stop(self) -> None:
        """停止WebSocket服务器"""
        self._running = False

        # 取消heartbeat任务
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        # 取消订阅事件总线，防止重复启停导致重复注册
        self._unsubscribe_from_events()

        # 关闭所有连接
        for connection in list(self.connection_manager.active_connections):
            await connection.close()

        # 停止L4主循环
        if self.galaxy_loop:
            await self.galaxy_loop.stop()

        # 关闭服务器
        if self._server:
            self._server.close()
            await self._server.wait_closed()

        logger.info("WebSocket server stopped")

    def _unsubscribe_from_events(self) -> None:
        """取消订阅事件总线事件"""
        event_bus.unsubscribe(EventType.GOAL_DECOMPOSITION_STARTED, self._on_decomposition_started, async_callback=True)
        event_bus.unsubscribe(EventType.GOAL_DECOMPOSITION_COMPLETED, self._on_decomposition_completed, async_callback=True)
        event_bus.unsubscribe(EventType.PLAN_GENERATION_STARTED, self._on_plan_started, async_callback=True)
        event_bus.unsubscribe(EventType.PLAN_GENERATION_COMPLETED, self._on_plan_completed, async_callback=True)
        event_bus.unsubscribe(EventType.ACTION_EXECUTION_STARTED, self._on_action_started, async_callback=True)
        event_bus.unsubscribe(EventType.ACTION_EXECUTION_PROGRESS, self._on_action_progress, async_callback=True)
        event_bus.unsubscribe(EventType.ACTION_EXECUTION_COMPLETED, self._on_action_completed, async_callback=True)
        event_bus.unsubscribe(EventType.TASK_COMPLETED, self._on_task_completed, async_callback=True)
        event_bus.unsubscribe(EventType.ERROR_OCCURRED, self._on_error, async_callback=True)


# ---------------------------------------------------------------------------
# GalaxyHTTPServer
# ---------------------------------------------------------------------------

if AIOHTTP_AVAILABLE:
    class GalaxyHTTPServer:
        """HTTP API服务器 - 包含健康检查端点和配置热重载"""

        def __init__(self, port: int = 8081) -> None:
            self.port: int = port
            self.app: web.Application = web.Application()
            self.galaxy_loop: Optional[GalaxyMainLoopL4Enhanced] = None
            self._config_mtimes: Dict[str, float] = {}
            self._reload_task: Optional[asyncio.Task] = None

            # 设置路由
            self._setup_routes()

        def _setup_routes(self) -> None:
            """设置路由，包括健康检查端点"""
            self.app.router.add_post("/api/goals", self.handle_goal_submit)
            self.app.router.add_get("/api/status", self.handle_get_status)
            self.app.router.add_get("/api/tasks", self.handle_get_tasks)
            self.app.router.add_get("/api/events", self.handle_get_events)
            self.app.router.add_get("/health", self.handle_health_check)
            self.app.router.add_get("/health/live", self.handle_liveness_probe)
            self.app.router.add_get("/health/ready", self.handle_readiness_probe)

        async def handle_health_check(self, request: web.Request) -> web.Response:
            """
            健康检查端点 /health
            返回服务整体健康状态
            """
            request_id: str = generate_request_id()
            health_status: Dict[str, Any] = {
                "status": "healthy",
                "request_id": request_id,
                "timestamp": datetime.now().isoformat(),
                "components": {
                    "websocket_server": "up",
                    "http_server": "up",
                    "event_bus": "up" if event_bus._running else "down"
                }
            }

            if self.galaxy_loop:
                health_status["components"]["l4_loop"] = (
                    "up" if getattr(self.galaxy_loop, 'running', False) else "down"
                )

            # Determine overall status
            component_statuses: List[str] = [
                v for v in health_status["components"].values()
            ]
            if "down" in component_statuses:
                health_status["status"] = "degraded" if "up" in component_statuses else "unhealthy"
                status_code: int = 503 if health_status["status"] == "unhealthy" else 200
            else:
                status_code = 200

            return web.json_response(health_status, status=status_code)

        async def handle_liveness_probe(self, request: web.Request) -> web.Response:
            """
            Kubernetes liveness probe endpoint /health/live
            Returns 200 if the process is alive
            """
            return web.json_response({
                "status": "alive",
                "request_id": generate_request_id(),
                "timestamp": datetime.now().isoformat()
            }, status=200)

        async def handle_readiness_probe(self, request: web.Request) -> web.Response:
            """
            Kubernetes readiness probe endpoint /health/ready
            Returns 200 if the service is ready to accept traffic
            """
            is_ready: bool = (
                self.galaxy_loop is not None
                and getattr(self.galaxy_loop, 'running', False)
            )
            status_code: int = 200 if is_ready else 503
            return web.json_response({
                "status": "ready" if is_ready else "not_ready",
                "request_id": generate_request_id(),
                "timestamp": datetime.now().isoformat()
            }, status=status_code)

        async def handle_goal_submit(self, request: web.Request) -> web.Response:
            """
            处理目标提交（UI → L4 集成点）

            POST /api/goals
            {
                "description": "目标描述",
                "priority": 0
            }
            """
            request_id: str = generate_request_id()
            try:
                data: Dict[str, Any] = await request.json()
                description: str = data.get("description", "")

                if not description:
                    return web.json_response(
                        make_error_response("Goal description is required", status_code=400, request_id=request_id),
                        status=400
                    )

                if self.galaxy_loop:
                    goal_id: str = self.galaxy_loop.receive_goal(description)
                    return web.json_response({
                        "goal_id": goal_id,
                        "description": description,
                        "status": "accepted",
                        "request_id": request_id
                    })
                else:
                    return web.json_response(
                        make_error_response("L4 main loop not available", status_code=503, request_id=request_id),
                        status=503
                    )

            except Exception as exc:
                logger.error("Goal submit error: %s", exc)
                return web.json_response(
                    make_error_response(str(exc), status_code=500, request_id=request_id),
                    status=500
                )

        async def handle_get_status(self, request: web.Request) -> web.Response:
            """获取系统状态"""
            request_id: str = generate_request_id()
            status: Dict[str, Any] = {"request_id": request_id}

            if self.galaxy_loop:
                status["l4"] = self.galaxy_loop.get_status()

            return web.json_response(status)

        async def handle_get_tasks(self, request: web.Request) -> web.Response:
            """获取任务列表"""
            request_id: str = generate_request_id()
            if self.galaxy_loop:
                tasks: List[Any] = self.galaxy_loop.get_task_history(limit=20)
                return web.json_response({"tasks": tasks, "request_id": request_id})

            return web.json_response({"tasks": [], "request_id": request_id})

        async def handle_get_events(self, request: web.Request) -> web.Response:
            """获取事件历史"""
            request_id: str = generate_request_id()
            event_type_str: Optional[str] = request.query.get("type")
            limit: int = int(request.query.get("limit", 100))

            if event_type_str:
                event_type: Optional[EventType] = (
                    EventType[event_type_str]
                    if event_type_str in EventType._member_names_
                    else None
                )
                events: List[UIGalaxyEvent] = event_bus.get_event_history(event_type, limit)
            else:
                events = event_bus.get_event_history(limit=limit)

            return web.json_response({
                "events": [e.to_dict() for e in events],
                "request_id": request_id
            })

        async def _watch_config_files(self) -> None:
            """Watch configuration files for changes and trigger hot reload."""
            # Initialize mtimes
            for path_str in CONFIG_WATCH_PATHS:
                full_path: str = _os.path.join(_PROJECT_ROOT, path_str.strip())
                try:
                    self._config_mtimes[full_path] = _os.path.getmtime(full_path)
                except OSError:
                    self._config_mtimes[full_path] = 0.0

            logger.info("Config file watcher started, watching: %s", CONFIG_WATCH_PATHS)

            while True:
                await asyncio.sleep(CONFIG_RELOAD_INTERVAL_SECONDS)
                for path_str in CONFIG_WATCH_PATHS:
                    full_path = _os.path.join(_PROJECT_ROOT, path_str.strip())
                    try:
                        current_mtime: float = _os.path.getmtime(full_path)
                        if current_mtime > self._config_mtimes.get(full_path, 0.0):
                            logger.info("Config file changed: %s, triggering reload", full_path)
                            self._config_mtimes[full_path] = current_mtime
                            await self._reload_config(full_path)
                    except OSError:
                        pass

        async def _reload_config(self, changed_path: str) -> None:
            """Reload configuration when a watched file changes.

            Args:
                changed_path: Path to the changed configuration file.
            """
            logger.info("Reloading configuration from %s", changed_path)
            # Note: Actual reload logic depends on the specific config file type
            # and would integrate with the system's config management.
            # For now, we log the event so downstream systems can react.
            event_bus.publish_sync(
                EventType.STATE_TRANSITION,
                "config_watcher",
                {"event": "config_reloaded", "path": changed_path}
            )

        async def start(self) -> None:
            """启动HTTP服务器"""
            self.galaxy_loop = get_galaxy_loop()

            # Start config file watcher for hot reload
            self._reload_task = asyncio.create_task(self._watch_config_files())

            runner: web.AppRunner = web.AppRunner(self.app)
            await runner.setup()

            site: web.TCPSite = web.TCPSite(runner, "0.0.0.0", self.port)
            await site.start()

            logger.info("HTTP server started: http://0.0.0.0:%d", self.port)

        async def stop(self) -> None:
            """停止HTTP服务器"""
            if self._reload_task:
                self._reload_task.cancel()
                try:
                    await self._reload_task
                except asyncio.CancelledError:
                    pass
            logger.info("HTTP server stopped")

else:
    # Fallback when aiohttp is not available
    class GalaxyHTTPServer:
        """Fallback HTTP server when aiohttp is not available."""

        def __init__(self, port: int = 8081) -> None:
            self.port: int = port
            self.galaxy_loop: Optional[GalaxyMainLoopL4Enhanced] = None
            logger.warning("aiohttp not available, HTTP server disabled")

        async def start(self) -> None:
            """HTTP server is disabled due to missing aiohttp."""
            logger.error("Cannot start HTTP server: aiohttp is not installed")

        async def stop(self) -> None:
            """No-op stop."""
            pass


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    """主入口"""
    # 启动事件总线
    await event_bus.start()

    # 创建服务器（端口从 PortConfig 读取，回退到默认值）
    try:
        from core.port_config import get_service_port
        _ws_port: int = get_service_port("websocket")
        _http_port: int = get_service_port("websocket_http")
    except Exception:
        _ws_port, _http_port = 8080, 8081

    ws_server: GalaxyWebSocketServer = GalaxyWebSocketServer(
        host="0.0.0.0",
        port=_ws_port,
        heartbeat_interval=WS_HEARTBEAT_INTERVAL_SECONDS,
        max_connections=WS_MAX_CONNECTIONS
    )
    http_server: GalaxyHTTPServer = GalaxyHTTPServer(port=_http_port)

    # 同时启动WebSocket和HTTP服务器
    await asyncio.gather(
        ws_server.start(),
        http_server.start()
    )


if __name__ == "__main__":
    asyncio.run(main())
