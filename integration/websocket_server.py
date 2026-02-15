"""
UFO Galaxy WebSocket服务器
处理Android客户端和Windows客户端的连接
实现UI与L4主循环的双向通信
"""

import asyncio
import json
import logging
import websockets
from typing import Dict, Any, Optional, Set
from datetime import datetime

# 导入L4主循环和事件总线
import sys
sys.path.insert(0, '/mnt/okcomputer/output/ufo_galaxy_integration')
from core.galaxy_main_loop_l4_enhanced import get_galaxy_loop, GalaxyMainLoopL4Enhanced
from integration.event_bus import (
    EventBus, EventType, UIGalaxyEvent, event_bus
)


# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("WebSocketServer")


class ConnectionManager:
    """WebSocket连接管理器"""
    
    def __init__(self):
        self.active_connections: Set[websockets.WebSocketServerProtocol] = set()
        self.client_info: Dict[websockets.WebSocketServerProtocol, Dict[str, Any]] = {}
    
    async def connect(self, websocket: websockets.WebSocketServerProtocol, client_type: str = "unknown"):
        """接受新连接"""
        self.active_connections.add(websocket)
        self.client_info[websocket] = {
            "client_type": client_type,
            "connected_at": datetime.now().isoformat(),
            "message_count": 0
        }
        logger.info(f"客户端连接: {client_type} ({websocket.remote_address})")
    
    def disconnect(self, websocket: websockets.WebSocketServerProtocol):
        """断开连接"""
        self.active_connections.discard(websocket)
        info = self.client_info.pop(websocket, {})
        logger.info(f"客户端断开: {info.get('client_type', 'unknown')}")
    
    async def send_to_client(self, websocket: websockets.WebSocketServerProtocol, message: Dict[str, Any]):
        """发送消息给特定客户端"""
        try:
            await websocket.send(json.dumps(message))
            if websocket in self.client_info:
                self.client_info[websocket]["message_count"] += 1
        except Exception as e:
            logger.error(f"发送消息失败: {e}")
    
    async def broadcast(self, message: Dict[str, Any], exclude: websockets.WebSocketServerProtocol = None):
        """广播消息给所有客户端"""
        disconnected = []
        for connection in self.active_connections:
            if connection != exclude:
                try:
                    await connection.send(json.dumps(message))
                except Exception as e:
                    logger.error(f"广播消息失败: {e}")
                    disconnected.append(connection)
        
        # 清理断开的连接
        for conn in disconnected:
            self.disconnect(conn)
    
    async def broadcast_to_type(self, client_type: str, message: Dict[str, Any]):
        """广播消息给特定类型的客户端"""
        disconnected = []
        for connection in self.active_connections:
            info = self.client_info.get(connection, {})
            if info.get("client_type") == client_type:
                try:
                    await connection.send(json.dumps(message))
                except Exception as e:
                    logger.error(f"广播消息失败: {e}")
                    disconnected.append(connection)
        
        for conn in disconnected:
            self.disconnect(conn)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取连接统计"""
        client_types = {}
        for info in self.client_info.values():
            client_type = info.get("client_type", "unknown")
            client_types[client_type] = client_types.get(client_type, 0) + 1
        
        return {
            "total_connections": len(self.active_connections),
            "client_types": client_types
        }


class GalaxyWebSocketServer:
    """
    UFO Galaxy WebSocket服务器
    处理客户端连接和L4主循环的集成
    """
    
    def __init__(self, host: str = "0.0.0.0", port: int = 8080):
        self.host = host
        self.port = port
        self.connection_manager = ConnectionManager()
        self.galaxy_loop: Optional[GalaxyMainLoopL4Enhanced] = None
        self._running = False
        self._server = None
        
        # 订阅事件总线
        self._subscribe_to_events()
    
    def _subscribe_to_events(self):
        """订阅事件总线事件"""
        # 订阅L4相关事件，转发给客户端
        event_bus.subscribe(EventType.GOAL_DECOMPOSITION_STARTED, self._on_decomposition_started, async_callback=True)
        event_bus.subscribe(EventType.GOAL_DECOMPOSITION_COMPLETED, self._on_decomposition_completed, async_callback=True)
        event_bus.subscribe(EventType.PLAN_GENERATION_STARTED, self._on_plan_started, async_callback=True)
        event_bus.subscribe(EventType.PLAN_GENERATION_COMPLETED, self._on_plan_completed, async_callback=True)
        event_bus.subscribe(EventType.ACTION_EXECUTION_STARTED, self._on_action_started, async_callback=True)
        event_bus.subscribe(EventType.ACTION_EXECUTION_PROGRESS, self._on_action_progress, async_callback=True)
        event_bus.subscribe(EventType.ACTION_EXECUTION_COMPLETED, self._on_action_completed, async_callback=True)
        event_bus.subscribe(EventType.TASK_COMPLETED, self._on_task_completed, async_callback=True)
        event_bus.subscribe(EventType.ERROR_OCCURRED, self._on_error, async_callback=True)
    
    async def _on_decomposition_started(self, event: UIGalaxyEvent):
        """目标分解开始事件处理"""
        await self.connection_manager.broadcast({
            "event_type": "GOAL_DECOMPOSITION_STARTED",
            "data": event.data,
            "timestamp": event.timestamp.isoformat()
        })
    
    async def _on_decomposition_completed(self, event: UIGalaxyEvent):
        """目标分解完成事件处理"""
        await self.connection_manager.broadcast({
            "event_type": "GOAL_DECOMPOSITION_COMPLETED",
            "data": event.data,
            "timestamp": event.timestamp.isoformat()
        })
    
    async def _on_plan_started(self, event: UIGalaxyEvent):
        """计划生成开始事件处理"""
        await self.connection_manager.broadcast({
            "event_type": "PLAN_GENERATION_STARTED",
            "data": event.data,
            "timestamp": event.timestamp.isoformat()
        })
    
    async def _on_plan_completed(self, event: UIGalaxyEvent):
        """计划生成完成事件处理"""
        await self.connection_manager.broadcast({
            "event_type": "PLAN_GENERATION_COMPLETED",
            "data": event.data,
            "timestamp": event.timestamp.isoformat()
        })
    
    async def _on_action_started(self, event: UIGalaxyEvent):
        """动作执行开始事件处理"""
        await self.connection_manager.broadcast({
            "event_type": "ACTION_EXECUTION_STARTED",
            "data": event.data,
            "timestamp": event.timestamp.isoformat()
        })
    
    async def _on_action_progress(self, event: UIGalaxyEvent):
        """动作执行进度事件处理"""
        await self.connection_manager.broadcast({
            "event_type": "ACTION_EXECUTION_PROGRESS",
            "data": event.data,
            "timestamp": event.timestamp.isoformat()
        })
    
    async def _on_action_completed(self, event: UIGalaxyEvent):
        """动作执行完成事件处理"""
        await self.connection_manager.broadcast({
            "event_type": "ACTION_EXECUTION_COMPLETED",
            "data": event.data,
            "timestamp": event.timestamp.isoformat()
        })
    
    async def _on_task_completed(self, event: UIGalaxyEvent):
        """任务完成事件处理"""
        await self.connection_manager.broadcast({
            "event_type": "TASK_COMPLETED",
            "data": event.data,
            "timestamp": event.timestamp.isoformat()
        })
    
    async def _on_error(self, event: UIGalaxyEvent):
        """错误事件处理"""
        await self.connection_manager.broadcast({
            "event_type": "ERROR_OCCURRED",
            "data": event.data,
            "timestamp": event.timestamp.isoformat()
        })
    
    async def handle_client(self, websocket: websockets.WebSocketServerProtocol, path: str):
        """处理客户端连接"""
        client_type = "unknown"
        
        try:
            # 等待客户端发送身份验证/类型信息
            auth_message = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            auth_data = json.loads(auth_message)
            client_type = auth_data.get("client_type", "unknown")
            
            # 接受连接
            await self.connection_manager.connect(websocket, client_type)
            
            # 发送欢迎消息
            await self.connection_manager.send_to_client(websocket, {
                "type": "welcome",
                "message": "Connected to UFO Galaxy Server",
                "server_time": datetime.now().isoformat()
            })
            
            # 处理客户端消息
            async for message in websocket:
                try:
                    data = json.loads(message)
                    await self._handle_message(websocket, data)
                except json.JSONDecodeError:
                    await self.connection_manager.send_to_client(websocket, {
                        "type": "error",
                        "message": "Invalid JSON format"
                    })
                except Exception as e:
                    logger.error(f"处理消息错误: {e}")
                    await self.connection_manager.send_to_client(websocket, {
                        "type": "error",
                        "message": str(e)
                    })
        
        except asyncio.TimeoutError:
            logger.warning("客户端认证超时")
        except websockets.exceptions.ConnectionClosed:
            logger.info("客户端连接关闭")
        except Exception as e:
            logger.error(f"客户端处理错误: {e}")
        finally:
            self.connection_manager.disconnect(websocket)
    
    async def _handle_message(self, websocket: websockets.WebSocketServerProtocol, data: Dict[str, Any]):
        """处理客户端消息"""
        msg_type = data.get("type", "unknown")
        
        if msg_type == "goal_submit":
            # 处理目标提交（UI → L4 集成点）
            await self._handle_goal_submit(websocket, data)
        
        elif msg_type == "command":
            # 处理命令
            await self._handle_command(websocket, data)
        
        elif msg_type == "ping":
            # 心跳检测
            await self.connection_manager.send_to_client(websocket, {
                "type": "pong",
                "timestamp": datetime.now().isoformat()
            })
        
        elif msg_type == "get_status":
            # 获取状态
            await self._handle_get_status(websocket)
        
        else:
            await self.connection_manager.send_to_client(websocket, {
                "type": "error",
                "message": f"Unknown message type: {msg_type}"
            })
    
    async def _handle_goal_submit(self, websocket: websockets.WebSocketServerProtocol, data: Dict[str, Any]):
        """
        处理目标提交（UI → L4 集成点）
        
        Args:
            websocket: WebSocket连接
            data: 消息数据
        """
        description = data.get("description", "")
        intent = data.get("intent", {})
        
        if not description:
            await self.connection_manager.send_to_client(websocket, {
                "type": "error",
                "message": "Goal description is required"
            })
            return
        
        logger.info(f"收到目标提交: {description}")
        
        # 提交到L4主循环
        if self.galaxy_loop:
            goal_id = self.galaxy_loop.receive_goal(description)
            
            await self.connection_manager.send_to_client(websocket, {
                "type": "goal_accepted",
                "goal_id": goal_id,
                "description": description,
                "message": "Goal submitted successfully"
            })
        else:
            await self.connection_manager.send_to_client(websocket, {
                "type": "error",
                "message": "L4 main loop not available"
            })
    
    async def _handle_command(self, websocket: websockets.WebSocketServerProtocol, data: Dict[str, Any]):
        """处理命令"""
        command = data.get("command", "")
        params = data.get("params", {})
        
        logger.info(f"收到命令: {command}")
        
        # 处理各种命令
        if command == "wakeup":
            # 唤醒系统
            from system_integration.state_machine_ui_integration import wakeup_system
            success = wakeup_system("websocket")
            await self.connection_manager.send_to_client(websocket, {
                "type": "command_result",
                "command": command,
                "success": success
            })
        
        elif command == "get_stats":
            # 获取统计信息
            stats = self.connection_manager.get_stats()
            if self.galaxy_loop:
                stats["l4_status"] = self.galaxy_loop.get_status()
            
            await self.connection_manager.send_to_client(websocket, {
                "type": "command_result",
                "command": command,
                "data": stats
            })
        
        else:
            await self.connection_manager.send_to_client(websocket, {
                "type": "error",
                "message": f"Unknown command: {command}"
            })
    
    async def _handle_get_status(self, websocket: websockets.WebSocketServerProtocol):
        """处理获取状态请求"""
        status = {
            "server": {
                "connections": self.connection_manager.get_stats()
            }
        }
        
        if self.galaxy_loop:
            status["l4"] = self.galaxy_loop.get_status()
        
        await self.connection_manager.send_to_client(websocket, {
            "type": "status",
            "data": status
        })
    
    async def start(self):
        """启动WebSocket服务器"""
        self._running = True
        
        # 启动L4主循环
        self.galaxy_loop = get_galaxy_loop({
            "cycle_interval": 2.0,
            "auto_scan_interval": 300.0
        })
        
        # 在后台启动L4主循环
        asyncio.create_task(self.galaxy_loop.start())
        
        # 启动WebSocket服务器
        self._server = await websockets.serve(
            self.handle_client,
            self.host,
            self.port
        )
        
        logger.info(f"WebSocket服务器已启动: ws://{self.host}:{self.port}")
        
        # 保持运行
        await self._server.wait_closed()
    
    async def stop(self):
        """停止WebSocket服务器"""
        self._running = False
        
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
        
        logger.info("WebSocket服务器已停止")


# HTTP API服务器（用于备选通信）
from aiohttp import web


class GalaxyHTTPServer:
    """HTTP API服务器"""
    
    def __init__(self, port: int = 8081):
        self.port = port
        self.app = web.Application()
        self.galaxy_loop: Optional[GalaxyMainLoopL4Enhanced] = None
        
        # 设置路由
        self._setup_routes()
    
    def _setup_routes(self):
        """设置路由"""
        self.app.router.add_post("/api/goals", self.handle_goal_submit)
        self.app.router.add_get("/api/status", self.handle_get_status)
        self.app.router.add_get("/api/tasks", self.handle_get_tasks)
        self.app.router.add_get("/api/events", self.handle_get_events)
    
    async def handle_goal_submit(self, request: web.Request) -> web.Response:
        """
        处理目标提交（UI → L4 集成点）
        
        POST /api/goals
        {
            "description": "目标描述",
            "priority": 0
        }
        """
        try:
            data = await request.json()
            description = data.get("description", "")
            
            if not description:
                return web.json_response({
                    "error": "Goal description is required"
                }, status=400)
            
            if self.galaxy_loop:
                goal_id = self.galaxy_loop.receive_goal(description)
                return web.json_response({
                    "goal_id": goal_id,
                    "description": description,
                    "status": "accepted"
                })
            else:
                return web.json_response({
                    "error": "L4 main loop not available"
                }, status=503)
        
        except Exception as e:
            return web.json_response({
                "error": str(e)
            }, status=500)
    
    async def handle_get_status(self, request: web.Request) -> web.Response:
        """获取系统状态"""
        status = {}
        
        if self.galaxy_loop:
            status["l4"] = self.galaxy_loop.get_status()
        
        return web.json_response(status)
    
    async def handle_get_tasks(self, request: web.Request) -> web.Response:
        """获取任务列表"""
        if self.galaxy_loop:
            tasks = self.galaxy_loop.get_task_history(limit=20)
            return web.json_response({"tasks": tasks})
        
        return web.json_response({"tasks": []})
    
    async def handle_get_events(self, request: web.Request) -> web.Response:
        """获取事件历史"""
        event_type = request.query.get("type")
        limit = int(request.query.get("limit", 100))
        
        from integration.event_bus import event_bus
        
        if event_type:
            events = event_bus.get_event_history(
                EventType[event_type] if event_type in EventType._member_names_ else None,
                limit
            )
        else:
            events = event_bus.get_event_history(limit=limit)
        
        return web.json_response({
            "events": [e.to_dict() for e in events]
        })
    
    async def start(self):
        """启动HTTP服务器"""
        self.galaxy_loop = get_galaxy_loop()
        
        runner = web.AppRunner(self.app)
        await runner.setup()
        
        site = web.TCPSite(runner, "0.0.0.0", self.port)
        await site.start()
        
        logger.info(f"HTTP服务器已启动: http://0.0.0.0:{self.port}")
    
    async def stop(self):
        """停止HTTP服务器"""
        logger.info("HTTP服务器已停止")


async def main():
    """主入口"""
    # 启动事件总线
    await event_bus.start()
    
    # 创建服务器
    ws_server = GalaxyWebSocketServer(host="0.0.0.0", port=8080)
    http_server = GalaxyHTTPServer(port=8081)
    
    # 同时启动WebSocket和HTTP服务器
    await asyncio.gather(
        ws_server.start(),
        http_server.start()
    )


if __name__ == "__main__":
    asyncio.run(main())
