"""
Galaxy 统一智能体核心
====================

集成所有 108 个节点到一个统一的智能体入口

功能:
1. 节点注册和发现
2. 统一调用接口
3. Agent 分发
4. 多协议支持 (HTTP/WebSocket/AIP)

版本: v2.3.22
"""

import os
import sys
import json
import asyncio
import logging
import importlib
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
import httpx
import websockets

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("UnifiedAgentCore")


class NodeStatus(Enum):
    """节点状态"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"
    LOADING = "loading"


class ProtocolType(Enum):
    """协议类型"""
    HTTP = "http"
    WEBSOCKET = "websocket"
    AIP = "aip"  # Agent Interaction Protocol
    LOCAL = "local"  # 本地直接调用


@dataclass
class NodeInfo:
    """节点信息"""
    node_id: str
    name: str
    port: int
    status: NodeStatus = NodeStatus.INACTIVE
    protocol: ProtocolType = ProtocolType.HTTP
    capabilities: List[str] = field(default_factory=list)
    endpoint: str = ""
    last_heartbeat: datetime = None
    
    def __post_init__(self):
        if not self.endpoint:
            self.endpoint = f"http://localhost:{self.port}"


@dataclass
class AgentTask:
    """Agent 任务"""
    task_id: str
    task_type: str
    description: str
    target_device: str = ""
    target_node: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    priority: int = 1
    created_at: datetime = field(default_factory=datetime.now)
    status: str = "pending"
    result: Any = None


class UnifiedAgentCore:
    """
    统一智能体核心
    
    集成所有节点，提供统一调用接口
    """
    
    def __init__(self):
        self.nodes: Dict[str, NodeInfo] = {}
        self.node_modules: Dict[str, Any] = {}
        self.tasks: Dict[str, AgentTask] = {}
        self._http_client: httpx.AsyncClient = None
        self._ws_connections: Dict[str, websockets.WebSocketClientProtocol] = {}
        
        # 初始化所有节点
        self._init_all_nodes()
    
    def _init_all_nodes(self):
        """初始化所有 108 个节点"""
        
        # 节点配置 (ID, 名称, 端口, 能力)
        node_configs = [
            # Layer 0: 核心层
            ("00", "StateMachine", 8000, ["state", "lock", "persistence"]),
            ("01", "OneAPI", 8001, ["llm", "chat", "completion"]),
            ("02", "Tasker", 8002, ["task", "dag", "workflow"]),
            ("03", "SecretVault", 8003, ["secret", "credential", "encryption"]),
            ("04", "Router", 8004, ["route", "discover", "load_balance"]),
            ("05", "Auth", 8005, ["auth", "jwt", "permission"]),
            
            # Layer 1: 网关层
            ("50", "Transformer", 8050, ["nlu", "intent", "entity"]),
            ("51", "Perception", 8051, ["perception", "sense", "awareness"]),
            ("52", "Reasoning", 8052, ["reasoning", "logic", "inference"]),
            ("53", "Planning", 8053, ["planning", "goal", "strategy"]),
            ("54", "Execution", 8054, ["execution", "action", "control"]),
            ("55", "Memory", 8055, ["memory", "recall", "forget"]),
            ("56", "AgentSwarm", 8056, ["swarm", "multi_agent", "coordination"]),
            ("57", "QuantumCloud", 8057, ["quantum", "cloud", "distributed"]),
            ("58", "ModelRouter", 8058, ["model", "router", "selection"]),
            ("59", "CausalInference", 8059, ["causal", "inference", "analysis"]),
            
            # Layer 2: 工具层
            ("10", "Slack", 8010, ["slack", "messaging", "notification"]),
            ("11", "GitHub", 8011, ["github", "repo", "pr"]),
            ("12", "Postgres", 8012, ["postgres", "sql", "database"]),
            ("13", "SQLite", 8013, ["sqlite", "database", "storage"]),
            ("14", "Redis", 8014, ["redis", "cache", "queue"]),
            ("15", "OCR", 8015, ["ocr", "text", "recognition"]),
            ("16", "TTS", 8016, ["tts", "speech", "voice"]),
            ("17", "STT", 8017, ["stt", "speech", "recognition"]),
            ("18", "Image", 8018, ["image", "vision", "processing"]),
            ("19", "Video", 8019, ["video", "stream", "processing"]),
            ("20", "Qdrant", 8020, ["qdrant", "vector", "embedding"]),
            ("21", "Notion", 8021, ["notion", "notes", "docs"]),
            ("22", "Calendar", 8022, ["calendar", "schedule", "event"]),
            ("23", "Email", 8023, ["email", "mail", "smtp"]),
            
            # Layer 3: 物理层
            ("33", "ADB", 8033, ["adb", "android", "device"]),
            ("45", "DesktopAuto", 8045, ["desktop", "windows", "automation"]),
            ("71", "MultiDeviceCoordination", 8071, ["multi_device", "coordination", "sync"]),
            ("70", "AutonomousLearning", 8070, ["learning", "experience", "knowledge"]),
            ("72", "KnowledgeBase", 8072, ["knowledge", "storage", "retrieval"]),
            ("74", "DigitalTwin", 8074, ["twin", "simulation", "prediction"]),
            ("90", "MultimodalVision", 8090, ["vision", "ocr", "multimodal"]),
            ("92", "AutoControl", 8092, ["control", "automation", "device"]),
            ("95", "WebRTC", 8095, ["webrtc", "streaming", "video"]),
            ("100", "MemorySystem", 8100, ["memory", "profile", "context"]),
            ("101", "CodeEngine", 8101, ["code", "generation", "execution"]),
            ("102", "DebugOptimize", 8102, ["debug", "optimize", "profile"]),
            ("103", "KnowledgeGraph", 8103, ["graph", "knowledge", "relation"]),
            ("104", "AgentCPM", 8104, ["agentcpm", "mobile", "agent"]),
            ("105", "UnifiedKnowledgeBase", 8105, ["unified_kb", "knowledge"]),
            ("106", "GitHubFlow", 8106, ["github_flow", "ci", "cd"]),
            ("108", "MetaCognition", 8108, ["metacognition", "reflection", "self_aware"]),
            ("109", "ProactiveSensing", 8109, ["proactive", "sensing", "awareness"]),
            ("110", "SmartOrchestrator", 8110, ["orchestrator", "smart", "schedule"]),
            ("111", "ContextManager", 8111, ["context", "manager", "state"]),
            ("112", "SelfHealing", 8112, ["healing", "recovery", "resilience"]),
            ("113", "AndroidVLM", 8113, ["android_vlm", "vision", "language"]),
            ("116", "ExternalToolWrapper", 8116, ["external", "tool", "wrapper"]),
            ("117", "OpenCode", 8117, ["open_code", "ide", "editor"]),
            ("118", "NodeFactory", 8118, ["factory", "node", "create"]),
            
            # 更多节点...
            ("06", "Filesystem", 8006, ["file", "storage", "io"]),
            ("07", "Git", 8007, ["git", "version", "control"]),
            ("08", "Fetch", 8008, ["fetch", "http", "request"]),
            ("09", "Sandbox", 8009, ["sandbox", "secure", "isolate"]),
            ("24", "Contacts", 8024, ["contacts", "address", "book"]),
            ("25", "Location", 8025, ["location", "gps", "map"]),
            ("26", "Weather", 8026, ["weather", "forecast", "climate"]),
            ("27", "News", 8027, ["news", "feed", "article"]),
            ("28", "Search", 8028, ["search", "query", "index"]),
            ("29", "Translate", 8029, ["translate", "language", "i18n"]),
            ("30", "Summarize", 8030, ["summarize", "abstract", "condense"]),
            ("31", "Sentiment", 8031, ["sentiment", "emotion", "analysis"]),
            ("32", "NER", 8032, ["ner", "entity", "extraction"]),
            ("34", "Bluetooth", 8034, ["bluetooth", "wireless", "connect"]),
            ("35", "WiFi", 8035, ["wifi", "network", "connect"]),
            ("36", "USB", 8036, ["usb", "serial", "connect"]),
            ("37", "Camera", 8037, ["camera", "capture", "record"]),
            ("38", "Microphone", 8038, ["microphone", "audio", "record"]),
            ("39", "Speaker", 8039, ["speaker", "audio", "play"]),
            ("40", "Display", 8040, ["display", "screen", "render"]),
            ("41", "Keyboard", 8041, ["keyboard", "input", "type"]),
            ("42", "Mouse", 8042, ["mouse", "input", "click"]),
            ("43", "MAVLink", 8043, ["mavlink", "drone", "uav"]),
            ("44", "ROS", 8044, ["ros", "robot", "control"]),
            ("46", "MacOSAuto", 8046, ["macos", "automation", "apple"]),
            ("47", "LinuxAuto", 8047, ["linux", "automation", "x11"]),
            ("48", "Browser", 8048, ["browser", "web", "selenium"]),
            ("49", "Mobile", 8049, ["mobile", "appium", "test"]),
            
            # 监控和运维
            ("60", "Metrics", 8060, ["metrics", "monitor", "stats"]),
            ("61", "Logs", 8061, ["logs", "logging", "audit"]),
            ("62", "Traces", 8062, ["traces", "tracing", "span"]),
            ("63", "Alerts", 8063, ["alerts", "notification", "warning"]),
            ("64", "Telemetry", 8064, ["telemetry", "monitor", "observe"]),
            ("65", "Logger", 8065, ["logger", "log", "record"]),
            ("66", "Profiler", 8066, ["profiler", "profile", "performance"]),
            ("67", "HealthMonitor", 8067, ["health", "monitor", "check"]),
            ("68", "Backup", 8068, ["backup", "restore", "snapshot"]),
            ("69", "Recovery", 8069, ["recovery", "failover", "restore"]),
            
            # 其他节点
            ("73", "Workflow", 8073, ["workflow", "pipeline", "flow"]),
            ("75", "Scheduler", 8075, ["scheduler", "cron", "timer"]),
            ("76", "Queue", 8076, ["queue", "message", "broker"]),
            ("77", "Cache", 8077, ["cache", "memo", "store"]),
            ("78", "Config", 8078, ["config", "settings", "env"]),
            ("79", "Secrets", 8079, ["secrets", "vault", "secure"]),
            ("80", "MemorySystem", 8080, ["memory", "profile", "user"]),
            ("81", "Session", 8081, ["session", "state", "context"]),
            ("82", "Conversation", 8082, ["conversation", "chat", "dialog"]),
            ("83", "Feedback", 8083, ["feedback", "rating", "review"]),
            ("84", "Analytics", 8084, ["analytics", "stats", "report"]),
            ("85", "Experiment", 8085, ["experiment", "ab_test", "variant"]),
            ("86", "Feature", 8086, ["feature", "flag", "toggle"]),
            ("87", "Version", 8087, ["version", "release", "deploy"]),
            ("88", "Rollback", 8088, ["rollback", "revert", "undo"]),
            ("89", "Migration", 8089, ["migration", "upgrade", "schema"]),
            
            # AI 增强
            ("91", "PromptEngine", 8091, ["prompt", "template", "engine"]),
            ("93", "Embedding", 8093, ["embedding", "vector", "encode"]),
            ("94", "Rerank", 8094, ["rerank", "rank", "sort"]),
            ("96", "RAG", 8096, ["rag", "retrieval", "augment"]),
            ("97", "FineTune", 8097, ["finetune", "train", "adapt"]),
            ("98", "Evaluate", 8098, ["evaluate", "test", "benchmark"]),
            ("99", "Optimize", 8099, ["optimize", "tune", "improve"]),
        ]
        
        # 注册所有节点
        for node_id, name, port, capabilities in node_configs:
            node = NodeInfo(
                node_id=node_id,
                name=name,
                port=port,
                capabilities=capabilities,
                status=NodeStatus.INACTIVE
            )
            self.nodes[node_id] = node
        
        logger.info(f"已注册 {len(self.nodes)} 个节点")
    
    async def _get_http_client(self) -> httpx.AsyncClient:
        """获取 HTTP 客户端"""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=30.0)
        return self._http_client
    
    # =========================================================================
    # 节点管理
    # =========================================================================
    
    def get_node(self, node_id: str) -> Optional[NodeInfo]:
        """获取节点"""
        return self.nodes.get(node_id)
    
    def get_node_by_capability(self, capability: str) -> List[NodeInfo]:
        """根据能力获取节点"""
        return [
            node for node in self.nodes.values()
            if capability in node.capabilities
        ]
    
    def get_node_by_name(self, name: str) -> Optional[NodeInfo]:
        """根据名称获取节点"""
        for node in self.nodes.values():
            if node.name.lower() == name.lower():
                return node
        return None
    
    async def check_node_health(self, node_id: str) -> bool:
        """检查节点健康状态"""
        node = self.get_node(node_id)
        if not node:
            return False
        
        try:
            client = await self._get_http_client()
            response = await client.get(f"{node.endpoint}/health", timeout=5.0)
            if response.status_code == 200:
                node.status = NodeStatus.ACTIVE
                node.last_heartbeat = datetime.now()
                return True
        except Exception as e:
            logger.debug(f"Node {node_id} health check failed: {e}")
            node.status = NodeStatus.INACTIVE
        
        return False
    
    async def check_all_nodes_health(self) -> Dict[str, bool]:
        """检查所有节点健康状态"""
        results = {}
        tasks = [self.check_node_health(node_id) for node_id in self.nodes.keys()]
        health_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for node_id, result in zip(self.nodes.keys(), health_results):
            results[node_id] = result if not isinstance(result, Exception) else False
        
        active_count = sum(1 for v in results.values() if v)
        logger.info(f"节点健康检查: {active_count}/{len(results)} 活跃")
        
        return results
    
    # =========================================================================
    # 统一调用接口
    # =========================================================================
    
    async def call_node(
        self,
        node_id: str,
        action: str,
        params: Dict[str, Any] = None,
        protocol: ProtocolType = ProtocolType.HTTP
    ) -> Dict[str, Any]:
        """
        调用节点 - 统一接口
        
        支持多种协议:
        - HTTP: REST API 调用
        - WebSocket: 实时双向通信
        - AIP: Agent Interaction Protocol
        - LOCAL: 本地直接调用
        """
        node = self.get_node(node_id)
        if not node:
            return {"success": False, "error": f"Node {node_id} not found"}
        
        params = params or {}
        
        try:
            if protocol == ProtocolType.HTTP:
                return await self._call_http(node, action, params)
            elif protocol == ProtocolType.WEBSOCKET:
                return await self._call_websocket(node, action, params)
            elif protocol == ProtocolType.AIP:
                return await self._call_aip(node, action, params)
            elif protocol == ProtocolType.LOCAL:
                return await self._call_local(node, action, params)
            else:
                return await self._call_http(node, action, params)
        
        except Exception as e:
            logger.error(f"Call node {node_id} failed: {e}")
            return {"success": False, "error": str(e)}
    
    async def _call_http(self, node: NodeInfo, action: str, params: Dict) -> Dict:
        """HTTP 调用"""
        client = await self._get_http_client()
        
        # 根据动作构建端点
        endpoint = f"{node.endpoint}/{action}"
        
        response = await client.post(endpoint, json=params)
        return response.json()
    
    async def _call_websocket(self, node: NodeInfo, action: str, params: Dict) -> Dict:
        """WebSocket 调用"""
        ws_url = node.endpoint.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/ws"
        
        if node.node_id not in self._ws_connections:
            self._ws_connections[node.node_id] = await websockets.connect(ws_url)
        
        ws = self._ws_connections[node.node_id]
        
        message = json.dumps({
            "action": action,
            "params": params,
            "timestamp": datetime.now().isoformat()
        })
        
        await ws.send(message)
        response = await ws.recv()
        
        return json.loads(response)
    
    async def _call_aip(self, node: NodeInfo, action: str, params: Dict) -> Dict:
        """AIP (Agent Interaction Protocol) 调用"""
        # AIP 消息格式
        aip_message = {
            "header": {
                "message_id": f"msg_{datetime.now().timestamp()}",
                "message_type": "request",
                "timestamp": datetime.now().timestamp(),
                "source_node": "unified_core",
                "target_node": node.node_id,
                "protocol_version": "2.0"
            },
            "body": {
                "action": action,
                "params": params
            }
        }
        
        # 通过 HTTP 发送 AIP 消息
        client = await self._get_http_client()
        response = await client.post(
            f"{node.endpoint}/aip",
            json=aip_message
        )
        
        return response.json()
    
    async def _call_local(self, node: NodeInfo, action: str, params: Dict) -> Dict:
        """本地直接调用"""
        # 尝试加载节点模块
        if node.node_id not in self.node_modules:
            try:
                module_path = f"nodes.Node_{node.node_id}_{node.name}.main"
                self.node_modules[node.node_id] = importlib.import_module(module_path)
            except ImportError:
                return {"success": False, "error": f"Cannot load module for node {node.node_id}"}
        
        module = self.node_modules[node.node_id]
        
        # 调用模块中的函数
        if hasattr(module, action):
            func = getattr(module, action)
            if asyncio.iscoroutinefunction(func):
                return await func(**params)
            else:
                return func(**params)
        
        return {"success": False, "error": f"Action {action} not found in node {node.node_id}"}
    
    # =========================================================================
    # 智能调用 - 自动选择最佳节点和协议
    # =========================================================================
    
    async def smart_call(
        self,
        capability: str,
        action: str,
        params: Dict[str, Any] = None,
        prefer_local: bool = True
    ) -> Dict[str, Any]:
        """
        智能调用 - 自动选择最佳节点和协议
        
        1. 根据能力找到匹配的节点
        2. 检查节点健康状态
        3. 选择最佳协议 (本地优先或远程)
        4. 执行调用
        """
        # 找到匹配的节点
        nodes = self.get_node_by_capability(capability)
        if not nodes:
            return {"success": False, "error": f"No node with capability: {capability}"}
        
        # 选择最佳节点 (优先活跃的)
        active_nodes = [n for n in nodes if n.status == NodeStatus.ACTIVE]
        target_node = active_nodes[0] if active_nodes else nodes[0]
        
        # 选择协议
        if prefer_local and target_node.status == NodeStatus.ACTIVE:
            protocol = ProtocolType.HTTP
        else:
            protocol = ProtocolType.HTTP
        
        logger.info(f"Smart call: {capability}/{action} -> Node_{target_node.node_id} ({protocol.value})")
        
        return await self.call_node(target_node.node_id, action, params, protocol)
    
    # =========================================================================
    # Agent 分发
    # =========================================================================
    
    async def dispatch_agent(
        self,
        task_type: str,
        target_device: str,
        params: Dict[str, Any] = None,
        protocol: ProtocolType = ProtocolType.HTTP
    ) -> Dict[str, Any]:
        """
        分发 Agent 到目标设备
        
        支持本地轻量 Agent 和远处分发:
        - 本地: 直接调用节点
        - 远处: 通过 WebSocket/HTTP/AIP 分发
        """
        params = params or {}
        params["target_device"] = target_device
        
        # 根据任务类型选择节点
        task_node_map = {
            "open_app": "92",      # AutoControl
            "click": "92",         # AutoControl
            "input": "92",         # AutoControl
            "scroll": "92",        # AutoControl
            "screenshot": "90",    # MultimodalVision
            "ocr": "15",           # OCR
            "chat": "01",          # OneAPI
            "learn": "70",         # AutonomousLearning
            "think": "108",        # MetaCognition
            "code": "101",         # CodeEngine
            "knowledge": "72",     # KnowledgeBase
            "multi_device": "71",  # MultiDeviceCoordination
        }
        
        node_id = task_node_map.get(task_type, "50")  # 默认 Transformer
        
        logger.info(f"Dispatch agent: {task_type} -> Node_{node_id} -> {target_device}")
        
        return await self.call_node(node_id, task_type, params, protocol)
    
    # =========================================================================
    # 自主能力集成
    # =========================================================================
    
    async def autonomous_learn(
        self,
        experience: Dict[str, Any]
    ) -> Dict[str, Any]:
        """自主学习"""
        return await self.call_node("70", "record_experience", {
            "experience_type": experience.get("type", "observation"),
            "context": experience.get("context", {}),
            "action": experience.get("action", ""),
            "outcome": experience.get("outcome", {}),
            "reward": experience.get("reward", 0.0)
        })
    
    async def autonomous_think(
        self,
        goal: str,
        context: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """自主思考"""
        return await self.call_node("108", "reflect", {
            "goal": goal,
            "context": context or {}
        })
    
    async def autonomous_code(
        self,
        task: str,
        files: List[str] = None
    ) -> Dict[str, Any]:
        """自主编程"""
        return await self.call_node("101", "generate_code", {
            "task": task,
            "target_files": files or []
        })
    
    async def query_knowledge(
        self,
        query: str,
        top_k: int = 5
    ) -> Dict[str, Any]:
        """查询知识库"""
        return await self.call_node("72", "search", {
            "query": query,
            "top_k": top_k
        })
    
    async def store_knowledge(
        self,
        content: str,
        metadata: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """存储知识"""
        return await self.call_node("72", "add", {
            "content": content,
            "metadata": metadata or {}
        })
    
    # =========================================================================
    # 系统状态
    # =========================================================================
    
    def get_status(self) -> Dict[str, Any]:
        """获取系统状态"""
        active_count = sum(1 for n in self.nodes.values() if n.status == NodeStatus.ACTIVE)
        
        return {
            "total_nodes": len(self.nodes),
            "active_nodes": active_count,
            "inactive_nodes": len(self.nodes) - active_count,
            "protocols_supported": [p.value for p in ProtocolType],
            "capabilities": list(set(
                cap for node in self.nodes.values() for cap in node.capabilities
            )),
            "timestamp": datetime.now().isoformat()
        }


# 全局实例
unified_core = UnifiedAgentCore()
