# -*- coding: utf-8 -*-

"""
Node_96_SmartTransportRouter: 智能传输路由节点

该节点实现了一个智能路由服务，能够根据消息的属性（如优先级、大小）
动态选择最合适的传输协议（HTTP, WebSocket, MQTT）进行数据转发。
它通过 FastAPI 提供健康检查和状态查询的 API 接口。
"""

import asyncio
import logging
import json
import random
import time
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from typing import Dict, Any, Optional, List, Type

# 第三方库，需要预先安装：pip install fastapi uvicorn python-multipart
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel
import uvicorn

# RUF006: retain fire-and-forget create_task results so the event loop's weak
# reference can't let them be garbage-collected mid-execution.
_BACKGROUND_TASKS: set = set()

# --- 1. 日志配置 ---
# 配置日志记录器，用于输出程序运行信息和错误
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(message)s",
    handlers=[
        logging.StreamHandler()  # 输出到控制台
    ]
)
logger = logging.getLogger(__name__)


# --- 2. 枚举定义 ---
# 定义支持的传输协议类型
class Protocol(Enum):
    """传输协议枚举"""
    HTTP = auto()
    WEBSOCKET = auto()
    MQTT = auto()

# 定义节点的运行状态
class NodeStatus(Enum):
    """节点状态枚举"""
    INITIALIZING = auto()  # 初始化中
    RUNNING = auto()       # 运行中
    DEGRADED = auto()      # 降级运行（部分功能异常）
    STOPPED = auto()       # 已停止

# 定义消息的优先级
class MessagePriority(Enum):
    """消息优先级枚举"""
    LOW = 1
    MEDIUM = 2
    HIGH = 3


# --- 3. 配置类 (Dataclass) ---
# 使用 dataclass 定义路由规则，方便进行结构化配置
@dataclass
class RoutingRule:
    """
    定义了根据消息属性选择协议的规则。

    Attributes:
        priority_threshold (MessagePriority): 消息优先级必须达到此阈值
        max_size_kb (int): 消息体的最大允许大小（单位 KB）
        allowed_protocols (List[Protocol]): 符合此规则时允许选择的协议列表
    """
    priority_threshold: MessagePriority
    max_size_kb: int
    allowed_protocols: List[Protocol]

# 定义节点的整体配置
@dataclass
class NodeConfig:
    """
    节点的核心配置。

    Attributes:
        node_id (str): 节点的唯一标识符
        endpoints (Dict[Protocol, str]): 各协议对应的目标服务地址
        routing_rules (Dict[str, RoutingRule]): 路由规则名称到规则对象的映射
        log_level (str): 日志记录级别
        health_check_port (int): 健康检查服务监听的端口
    """
    node_id: str = "Node_96_SmartTransportRouter"
    endpoints: Dict[Protocol, str] = field(default_factory=dict)
    routing_rules: Dict[str, RoutingRule] = field(default_factory=dict)
    log_level: str = "INFO"
    health_check_port: int = 8096


# --- 4. 传输协议处理器 ---
# 定义所有传输协议处理器的基类
class BaseTransport:
    """传输协议处理器的抽象基类"""
    def __init__(self, protocol: Protocol):
        self.protocol = protocol

    async def send(self, endpoint: str, data: Dict[str, Any]) -> bool:
        """
        发送数据的抽象方法。

        Args:
            endpoint (str): 目标地址
            data (Dict[str, Any]): 要发送的数据

        Returns:
            bool: 发送成功返回 True，否则返回 False
        """
        raise NotImplementedError("子类必须实现 send 方法")

# HTTP 传输实现
class HttpTransport(BaseTransport):
    """HTTP 协议传输实现。

    修复:之前整个 send() 就是 sleep + random.random() < 0.95 掷骰子决定
    "成功"，从未真的发过一个字节——这个节点叫"智能传输路由"，调用方拿到
    return True 只会以为数据真的送到了。httpx 本来就是这个仓库到处在用的
    依赖，这里直接实现真实的 POST。
    """
    def __init__(self):
        super().__init__(Protocol.HTTP)

    async def send(self, endpoint: str, data: Dict[str, Any]) -> bool:
        logger.info(f"使用 HTTP 发送数据到 {endpoint}")
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(endpoint, json=data)
            if resp.status_code < 400:
                logger.info(f"HTTP 发送成功({resp.status_code}): {json.dumps(data, ensure_ascii=False)}")
                return True
            logger.error(f"HTTP 发送失败: status={resp.status_code} body={resp.text[:200]}")
            return False
        except Exception as e:
            logger.error(f"HTTP 传输异常: {e}")
            return False

# WebSocket 传输实现
class WebSocketTransport(BaseTransport):
    """WebSocket 协议传输实现。

    修复:之前只 sleep 一下就无条件 return True，从没真的连过。改为真实的
    一次性连接→发送→关闭(websockets 库已在 requirements.txt 里)。
    """
    def __init__(self):
        super().__init__(Protocol.WEBSOCKET)

    async def send(self, endpoint: str, data: Dict[str, Any]) -> bool:
        logger.info(f"使用 WebSocket 发送数据到 {endpoint}")
        try:
            import websockets
            async with websockets.connect(endpoint, open_timeout=10) as ws:
                await ws.send(json.dumps(data, ensure_ascii=False))
            logger.info(f"WebSocket 发送成功: {json.dumps(data, ensure_ascii=False)}")
            return True
        except Exception as e:
            logger.error(f"WebSocket 传输异常: {e}")
            return False

# MQTT 传输实现
class MqttTransport(BaseTransport):
    """MQTT 协议传输实现。

    尚未接真实的 paho-mqtt 客户端(MQTT 连接/发布语义跟本文件里 HTTP/WS 的
    一次性请求模型不一样，需要先确定连接复用策略，不在这轮盲目实现)——
    诚实地报"未实现"并返回失败，而不是像之前那样 sleep 一下就假装发布
    成功，让调用方误以为消息真的送到了 broker。
    """
    def __init__(self):
        super().__init__(Protocol.MQTT)

    async def send(self, endpoint: str, data: Dict[str, Any]) -> bool:
        topic = endpoint  # 在 MQTT 中，endpoint 通常是 topic
        logger.error(
            f"MQTT 传输尚未实现真实客户端(topic='{topic}')——拒绝假装发布成功，"
            "如需使用请先接入 paho-mqtt。"
        )
        return False


# --- 5. 主服务类 ---
class SmartTransportRouter:
    """
    智能传输路由核心服务类。
    """
    def __init__(self, config: NodeConfig):
        """
        初始化路由器。

        Args:
            config (NodeConfig): 节点的配置对象
        """
        self.config = config
        self.status = NodeStatus.INITIALIZING
        self.transports: Dict[Protocol, BaseTransport] = {
            Protocol.HTTP: HttpTransport(),
            Protocol.WEBSOCKET: WebSocketTransport(),
            Protocol.MQTT: MqttTransport(),
        }
        self.stats = {
            "start_time": time.time(),
            "messages_processed": 0,
            "messages_succeeded": 0,
            "messages_failed": 0,
            "errors": [],
        }
        logger.setLevel(self.config.log_level)
        logger.info(f"节点 {self.config.node_id} 初始化完成")

    async def _select_protocol(self, message: Dict[str, Any]) -> Optional[Protocol]:
        """
        根据消息属性和路由规则选择最合适的协议。

        Args:
            message (Dict[str, Any]): 待发送的消息体

        Returns:
            Optional[Protocol]: 返回选中的协议，如果没有合适的则返回 None
        """
        msg_priority = message.get("priority", MessagePriority.LOW)
        msg_size_kb = len(json.dumps(message).encode('utf-8')) / 1024

        logger.info(f"开始为消息选择协议 (优先级: {msg_priority.name}, 大小: {msg_size_kb:.2f} KB)")

        # 遍历所有规则，找到最匹配的一个
        # 规则可以设计的更复杂，例如按顺序匹配或评分制，这里使用简单遍历
        candidate_protocols = []
        for rule_name, rule in self.config.routing_rules.items():
            if msg_priority.value >= rule.priority_threshold.value and msg_size_kb <= rule.max_size_kb:
                logger.info(f"消息匹配规则 '{rule_name}'，候选协议: {[p.name for p in rule.allowed_protocols]}")
                candidate_protocols.extend(rule.allowed_protocols)
        
        if not candidate_protocols:
            logger.warning("没有找到匹配的路由规则，无法选择协议")
            return None

        # 从候选协议中随机选择一个（可以替换为更复杂的负载均衡策略）
        selected = random.choice(list(set(candidate_protocols)))
        logger.info(f"最终选择协议: {selected.name}")
        return selected

    async def route_message(self, message: Dict[str, Any]) -> bool:
        """
        接收消息，选择协议并进行路由。

        Args:
            message (Dict[str, Any]): 待发送的消息

        Returns:
            bool: 路由和发送成功返回 True，否则返回 False
        """
        self.stats["messages_processed"] += 1
        protocol = await self._select_protocol(message)

        if protocol is None:
            self.stats["messages_failed"] += 1
            self.stats["errors"].append(f"[{time.time()}] No suitable protocol found for message.")
            return False

        endpoint = self.config.endpoints.get(protocol)
        transport = self.transports.get(protocol)

        if not endpoint or not transport:
            logger.error(f"协议 {protocol.name} 的端点或处理器未配置")
            self.stats["messages_failed"] += 1
            self.stats["errors"].append(f"[{time.time()}] Endpoint or handler for {protocol.name} not configured.")
            return False

        success = await transport.send(endpoint, message)
        if success:
            self.stats["messages_succeeded"] += 1
        else:
            self.stats["messages_failed"] += 1
            self.stats["errors"].append(f"[{time.time()}] Failed to send message via {protocol.name}.")
        
        return success

    async def run(self):
        """
        节点主运行循环。
        """
        self.status = NodeStatus.RUNNING
        logger.info(f"节点 {self.config.node_id} 进入运行状态")
        # 对于服务型节点，主要逻辑由 API 调用触发，这里可以留空或执行周期性任务
        while self.status == NodeStatus.RUNNING:
            await asyncio.sleep(60) # 每分钟打印一次心跳日志
            logger.info("节点正在运行... 存活心跳")

    def get_status(self) -> Dict[str, Any]:
        """
        获取节点的当前状态和统计信息。

        Returns:
            Dict[str, Any]: 包含状态和统计数据的字典
        """
        return {
            "node_id": self.config.node_id,
            "status": self.status.name,
            "uptime": time.time() - self.stats["start_time"],
            "configuration": asdict(self.config),
            "statistics": self.stats
        }


# --- 6. Web 服务 (FastAPI) ---
app = FastAPI(title="Smart Transport Router Node", version="1.0.0")
router: Optional[SmartTransportRouter] = None

@app.on_event("startup")
async def startup_event():
    """FastAPI 应用启动时执行的事件"""
    global router
    # 创建默认配置
    default_config = NodeConfig(
        endpoints={
            Protocol.HTTP: "http://api.example.com/data",
            Protocol.WEBSOCKET: "ws://ws.example.com/events",
            Protocol.MQTT: "iot_device_data_topic"
        },
        routing_rules={
            "high_priority_realtime": RoutingRule(
                priority_threshold=MessagePriority.HIGH,
                max_size_kb=16, # 16KB 以下的高优先级消息
                allowed_protocols=[Protocol.WEBSOCKET]
            ),
            "medium_priority_reliable": RoutingRule(
                priority_threshold=MessagePriority.MEDIUM,
                max_size_kb=1024, # 1MB 以下的中优先级消息
                allowed_protocols=[Protocol.HTTP, Protocol.WEBSOCKET]
            ),
            "low_priority_bulk": RoutingRule(
                priority_threshold=MessagePriority.LOW,
                max_size_kb=5120, # 5MB 以下的低优先级消息
                allowed_protocols=[Protocol.HTTP, Protocol.MQTT]
            )
        }
    )
    router = SmartTransportRouter(config=default_config)
    # 在后台运行节点的主循环
    _bt = asyncio.create_task(router.run())
    _BACKGROUND_TASKS.add(_bt)
    _bt.add_done_callback(_BACKGROUND_TASKS.discard)
    logger.info("FastAPI 应用启动，路由器已初始化并运行")

@app.get("/health", summary="健康检查接口", tags=["Monitoring"])
async def health_check():
    """
    提供简单的健康检查，确认服务是否正在运行。
    """
    if router and router.status == NodeStatus.RUNNING:
        return {"status": "ok"}
    else:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Router is not running or not initialized."
        )

@app.get("/status", summary="获取节点详细状态", tags=["Monitoring"])
async def get_node_status():
    """
    返回节点的完整状态，包括配置和统计数据。
    """
    if router:
        return router.get_status()
    else:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Router not initialized."
        )

@app.post("/route", summary="路由新消息", tags=["Core Logic"])
async def route_new_message(message: Dict[str, Any]):
    """
    接收一个 JSON 格式的消息，并将其路由到合适的传输协议。
    消息体中应包含 `priority` (LOW/MEDIUM/HIGH) 和其他数据。
    """
    if not router:
        raise HTTPException(status_code=503, detail="Router not initialized.")

    # 将字符串优先级转换为枚举成员。message 是裸 dict(无 pydantic 校验),
    # priority 若给成非字符串(如 int 3)或 null,.upper() 直接 AttributeError → 500。
    # 强制转字符串后再规整。
    priority_str = str(message.get("priority") or "LOW").upper()
    try:
        message["priority"] = MessagePriority[priority_str]
    except KeyError:
        raise HTTPException(status_code=400, detail=f"Invalid priority: {priority_str}. Must be one of {list(MessagePriority.__members__.keys())}")

    success = await router.route_message(message)
    if success:
        return {"status": "message routed successfully"}
    else:
        raise HTTPException(status_code=500, detail="Failed to route message.")

# --- 7. 主程序入口 ---


class MCPCallRequest(BaseModel):
    tool: str
    params: dict = {}

@app.post("/mcp/call")
async def mcp_call(request: MCPCallRequest):
    """MCP tool call dispatcher"""
    if request.tool == "health":
        return {"success": True, "tool": request.tool, "result": {"status": "healthy", "node": "Node_96_SmartTransportRouter"}}
    raise HTTPException(status_code=404, detail=f"Unknown tool: {request.tool}")

if __name__ == "__main__":
    """
    主程序入口，启动 FastAPI 服务。
    """
    logger.info("启动智能传输路由节点服务...")
    # 假设配置是从 NodeConfig 的默认值加载的
    # 在实际应用中，这里会从文件或环境变量加载配置
    config = NodeConfig() 
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=config.health_check_port
    )
