"""
Node 04: Global Router
======================
内部节点路由与发现服务。
管理 64 个节点的网络拓扑、健康状态、负载均衡。

功能：
- 节点注册与发现
- 健康检查与状态追踪
- 负载均衡路由
- 服务网格管理
"""

import os
import json
import asyncio
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Set
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 04 - Global Router", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# Models
# =============================================================================

class NodeStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"

class NodeLayer(Enum):
    L0_KERNEL = "kernel"
    L1_GATEWAY = "gateway"
    L2_TOOLS = "tools"
    L3_PHYSICAL = "physical"

@dataclass
class NodeInfo:
    """节点信息"""
    id: str
    name: str
    layer: NodeLayer
    host: str
    port: int
    status: NodeStatus = NodeStatus.UNKNOWN
    last_heartbeat: datetime = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    load: float = 0.0  # 0-1
    capabilities: List[str] = field(default_factory=list)
    
    @property
    def endpoint(self) -> str:
        return f"http://{self.host}:{self.port}"

# =============================================================================
# Router Core
# =============================================================================

class GlobalRouter:
    """全局路由器"""
    
    def __init__(self):
        self.nodes: Dict[str, NodeInfo] = {}
        self.health_check_interval = 30  # seconds
        self._init_static_nodes()
        
    def _init_static_nodes(self):
        """初始化静态节点配置"""
        base_ip = os.getenv("GALAXY_NET_BASE", "10.88.0")
        
        # 64 节点的完整配置
        node_configs = [
            # Layer 0: Kernel
            ("00", "StateMachine", NodeLayer.L0_KERNEL, 8000, ["state", "lock"]),
            ("01", "OneAPI", NodeLayer.L0_KERNEL, 8001, ["llm", "chat"]),
            ("02", "Tasker", NodeLayer.L0_KERNEL, 8002, ["task", "dag"]),
            ("03", "SecretVault", NodeLayer.L0_KERNEL, 8003, ["secret", "credential"]),
            ("04", "Router", NodeLayer.L0_KERNEL, 8004, ["route", "discover"]),
            ("05", "Auth", NodeLayer.L0_KERNEL, 8005, ["auth", "jwt"]),
            ("64", "Telemetry", NodeLayer.L0_KERNEL, 8064, ["metrics", "monitor"]),
            ("65", "Logger", NodeLayer.L0_KERNEL, 8065, ["log", "audit"]),
            ("67", "HealthMonitor", NodeLayer.L0_KERNEL, 8067, ["health", "heal"]),
            ("68", "Security", NodeLayer.L0_KERNEL, 8068, ["security", "firewall"]),
            ("69", "Backup", NodeLayer.L0_KERNEL, 8069, ["backup", "restore"]),
            
            # Layer 1: Gateway
            ("50", "Transformer", NodeLayer.L1_GATEWAY, 8050, ["protocol", "hardware"]),
            ("51", "QuantumDispatcher", NodeLayer.L1_GATEWAY, 8051, ["quantum", "dispatch"]),
            ("52", "QiskitSimulator", NodeLayer.L1_GATEWAY, 8052, ["quantum", "simulate"]),
            ("53", "GraphLogic", NodeLayer.L1_GATEWAY, 8053, ["graph", "knowledge"]),
            ("54", "SymbolicMath", NodeLayer.L1_GATEWAY, 8054, ["math", "symbolic"]),
            ("55", "Simulation", NodeLayer.L1_GATEWAY, 8055, ["simulate", "monte_carlo"]),
            ("56", "AgentSwarm", NodeLayer.L1_GATEWAY, 8056, ["agent", "debate"]),
            ("57", "QuantumCloud", NodeLayer.L1_GATEWAY, 8057, ["quantum", "cloud"]),
            ("58", "ModelRouter", NodeLayer.L1_GATEWAY, 8058, ["model", "route"]),
            ("59", "CausalInference", NodeLayer.L1_GATEWAY, 8059, ["causal", "inference"]),
            ("60", "TemporalLogic", NodeLayer.L1_GATEWAY, 8060, ["temporal", "planning"]),
            ("61", "GeometricReasoning", NodeLayer.L1_GATEWAY, 8061, ["geometry", "spatial"]),
            ("62", "ProbabilisticProgramming", NodeLayer.L1_GATEWAY, 8062, ["probability", "bayesian"]),
            ("63", "GameTheory", NodeLayer.L1_GATEWAY, 8063, ["game", "strategy"]),
            
            # Layer 2: Tools
            ("06", "Filesystem", NodeLayer.L2_TOOLS, 8006, ["file", "read", "write"]),
            ("07", "Git", NodeLayer.L2_TOOLS, 8007, ["git", "version"]),
            ("08", "Fetch", NodeLayer.L2_TOOLS, 8008, ["http", "fetch"]),
            ("09", "Search", NodeLayer.L2_TOOLS, 8009, ["search", "web"]),
            ("10", "Slack", NodeLayer.L2_TOOLS, 8010, ["slack", "message"]),
            ("11", "GitHub", NodeLayer.L2_TOOLS, 8011, ["github", "api"]),
            ("12", "Postgres", NodeLayer.L2_TOOLS, 8012, ["postgres", "sql"]),
            ("13", "SQLite", NodeLayer.L2_TOOLS, 8013, ["sqlite", "database"]),
            ("14", "FFmpeg", NodeLayer.L2_TOOLS, 8014, ["ffmpeg", "video"]),
            ("15", "OCR", NodeLayer.L2_TOOLS, 8015, ["ocr", "text"]),
            ("16", "Email", NodeLayer.L2_TOOLS, 8016, ["email", "smtp"]),
            ("17", "EdgeTTS", NodeLayer.L2_TOOLS, 8017, ["tts", "speech"]),
            ("18", "DeepL", NodeLayer.L2_TOOLS, 8018, ["translate", "deepl"]),
            ("19", "Crypto", NodeLayer.L2_TOOLS, 8019, ["crypto", "hash"]),
            ("20", "Qdrant", NodeLayer.L2_TOOLS, 8020, ["vector", "memory"]),
            ("21", "Notion", NodeLayer.L2_TOOLS, 8021, ["notion", "sync"]),
            ("22", "BraveSearch", NodeLayer.L2_TOOLS, 8022, ["brave", "search"]),
            ("23", "Time", NodeLayer.L2_TOOLS, 8023, ["time", "clock"]),
            ("24", "Weather", NodeLayer.L2_TOOLS, 8024, ["weather", "forecast"]),
            ("25", "GoogleSearch", NodeLayer.L2_TOOLS, 8025, ["google", "search"]),
            
            # Layer 3: Physical
            ("33", "ADB", NodeLayer.L3_PHYSICAL, 8033, ["adb", "android"]),
            ("34", "Scrcpy", NodeLayer.L3_PHYSICAL, 8034, ["scrcpy", "screen"]),
            ("35", "AppleScript", NodeLayer.L3_PHYSICAL, 8035, ["applescript", "macos"]),
            ("36", "UIAWindows", NodeLayer.L3_PHYSICAL, 8036, ["uia", "windows"]),
            ("37", "LinuxDBus", NodeLayer.L3_PHYSICAL, 8037, ["dbus", "linux"]),
            ("38", "BLE", NodeLayer.L3_PHYSICAL, 8038, ["ble", "bluetooth"]),
            ("39", "SSH", NodeLayer.L3_PHYSICAL, 8039, ["ssh", "tunnel"]),
            ("40", "SFTP", NodeLayer.L3_PHYSICAL, 8040, ["sftp", "scp"]),
            ("41", "MQTT", NodeLayer.L3_PHYSICAL, 8041, ["mqtt", "iot"]),
            ("42", "CANbus", NodeLayer.L3_PHYSICAL, 8042, ["can", "vehicle"]),
            ("43", "MAVLink", NodeLayer.L3_PHYSICAL, 8043, ["mavlink", "drone"]),
            ("44", "NFC", NodeLayer.L3_PHYSICAL, 8044, ["nfc", "rfid"]),
            ("45", "DesktopAuto", NodeLayer.L3_PHYSICAL, 8045, ["desktop", "keyboard"]),
            ("46", "Camera", NodeLayer.L3_PHYSICAL, 8046, ["camera", "vision"]),
            ("47", "Audio", NodeLayer.L3_PHYSICAL, 8047, ["audio", "mic"]),
            ("48", "Serial", NodeLayer.L3_PHYSICAL, 8048, ["serial", "uart"]),
            ("49", "OctoPrint", NodeLayer.L3_PHYSICAL, 8049, ["octoprint", "3dprint"]),
        ]
        
        for node_id, name, layer, port, caps in node_configs:
            self.nodes[node_id] = NodeInfo(
                id=node_id,
                name=name,
                layer=layer,
                host=f"{base_ip}.{int(node_id)}",
                port=port,
                capabilities=caps
            )
            
    def register_node(
        self,
        node_id: str,
        host: str,
        port: int,
        metadata: Dict[str, Any] = None
    ) -> NodeInfo:
        """注册节点"""
        if node_id in self.nodes:
            node = self.nodes[node_id]
            node.host = host
            node.port = port
            node.last_heartbeat = datetime.now()
            node.status = NodeStatus.HEALTHY
            if metadata:
                node.metadata.update(metadata)
        else:
            # 动态注册的节点
            node = NodeInfo(
                id=node_id,
                name=metadata.get("name", f"Node_{node_id}") if metadata else f"Node_{node_id}",
                layer=NodeLayer.L2_TOOLS,  # 默认工具层
                host=host,
                port=port,
                status=NodeStatus.HEALTHY,
                last_heartbeat=datetime.now(),
                metadata=metadata or {}
            )
            self.nodes[node_id] = node
            
        return node
        
    def heartbeat(self, node_id: str, load: float = 0.0) -> bool:
        """节点心跳"""
        if node_id in self.nodes:
            self.nodes[node_id].last_heartbeat = datetime.now()
            self.nodes[node_id].load = load
            self.nodes[node_id].status = NodeStatus.HEALTHY
            return True
        return False
        
    async def check_health(self, node_id: str) -> NodeStatus:
        """检查节点健康状态"""
        node = self.nodes.get(node_id)
        if not node:
            return NodeStatus.UNKNOWN
            
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{node.endpoint}/health")
                if response.status_code == 200:
                    node.status = NodeStatus.HEALTHY
                    node.last_heartbeat = datetime.now()
                else:
                    node.status = NodeStatus.DEGRADED
        except Exception:
            node.status = NodeStatus.UNHEALTHY
            
        return node.status
        
    async def check_all_health(self) -> Dict[str, NodeStatus]:
        """检查所有节点健康状态"""
        tasks = [
            self.check_health(node_id)
            for node_id in self.nodes
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        return {
            node_id: (result if isinstance(result, NodeStatus) else NodeStatus.UNKNOWN)
            for node_id, result in zip(self.nodes.keys(), results)
        }
        
    def discover_by_capability(self, capability: str) -> List[NodeInfo]:
        """按能力发现节点"""
        return [
            node for node in self.nodes.values()
            if capability in node.capabilities and node.status == NodeStatus.HEALTHY
        ]
        
    def discover_by_layer(self, layer: NodeLayer) -> List[NodeInfo]:
        """按层级发现节点"""
        return [
            node for node in self.nodes.values()
            if node.layer == layer
        ]
        
    def route(self, capability: str) -> Optional[NodeInfo]:
        """路由到最佳节点 (负载均衡)"""
        candidates = self.discover_by_capability(capability)
        if not candidates:
            return None
            
        # 选择负载最低的节点
        return min(candidates, key=lambda n: n.load)
        
    def get_topology(self) -> Dict[str, Any]:
        """获取网络拓扑"""
        topology = {
            "layers": {},
            "total_nodes": len(self.nodes),
            "healthy_nodes": sum(1 for n in self.nodes.values() if n.status == NodeStatus.HEALTHY)
        }
        
        for layer in NodeLayer:
            nodes = self.discover_by_layer(layer)
            topology["layers"][layer.value] = {
                "count": len(nodes),
                "nodes": [
                    {
                        "id": n.id,
                        "name": n.name,
                        "status": n.status.value,
                        "endpoint": n.endpoint,
                        "load": n.load
                    }
                    for n in nodes
                ]
            }
            
        return topology

# =============================================================================
# Global Instance
# =============================================================================

router = GlobalRouter()

# =============================================================================
# API Endpoints
# =============================================================================

class RegisterRequest(BaseModel):
    node_id: str
    host: str
    port: int
    metadata: Dict[str, Any] = None

class HeartbeatRequest(BaseModel):
    node_id: str
    load: float = 0.0

@app.get("/health")
async def health():
    """健康检查"""
    return {
        "status": "healthy",
        "node_id": "04",
        "name": "Global Router",
        "total_nodes": len(router.nodes),
        "timestamp": datetime.now().isoformat()
    }

@app.post("/register")
async def register_node(request: RegisterRequest):
    """注册节点"""
    node = router.register_node(
        node_id=request.node_id,
        host=request.host,
        port=request.port,
        metadata=request.metadata
    )
    return {
        "status": "registered",
        "node_id": node.id,
        "endpoint": node.endpoint
    }

@app.post("/heartbeat")
async def heartbeat(request: HeartbeatRequest):
    """节点心跳"""
    if router.heartbeat(request.node_id, request.load):
        return {"status": "ok"}
    raise HTTPException(status_code=404, detail="Node not found")

@app.get("/nodes")
async def list_nodes():
    """列出所有节点"""
    return {
        "nodes": [
            {
                "id": n.id,
                "name": n.name,
                "layer": n.layer.value,
                "endpoint": n.endpoint,
                "status": n.status.value,
                "load": n.load,
                "capabilities": n.capabilities
            }
            for n in router.nodes.values()
        ]
    }

@app.get("/nodes/{node_id}")
async def get_node(node_id: str):
    """获取节点信息"""
    node = router.nodes.get(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return {
        "id": node.id,
        "name": node.name,
        "layer": node.layer.value,
        "endpoint": node.endpoint,
        "status": node.status.value,
        "load": node.load,
        "capabilities": node.capabilities,
        "last_heartbeat": node.last_heartbeat.isoformat() if node.last_heartbeat else None
    }

@app.get("/discover/{capability}")
async def discover(capability: str):
    """按能力发现节点"""
    nodes = router.discover_by_capability(capability)
    return {
        "capability": capability,
        "nodes": [
            {"id": n.id, "name": n.name, "endpoint": n.endpoint}
            for n in nodes
        ]
    }

@app.get("/route/{capability}")
async def route(capability: str):
    """路由到最佳节点"""
    node = router.route(capability)
    if not node:
        raise HTTPException(status_code=404, detail=f"No node found for capability: {capability}")
    return {
        "node_id": node.id,
        "name": node.name,
        "endpoint": node.endpoint
    }

@app.get("/topology")
async def get_topology():
    """获取网络拓扑"""
    return router.get_topology()

@app.post("/health-check")
async def trigger_health_check():
    """触发全局健康检查"""
    results = await router.check_all_health()
    return {
        "results": {k: v.value for k, v in results.items()}
    }

# =============================================================================
# MCP Tool Interface
# =============================================================================

@app.post("/mcp/call")
async def mcp_call(request: Dict[str, Any]):
    """MCP 工具调用接口"""
    tool = request.get("tool", "")
    params = request.get("params", {})
    
    if tool == "discover":
        nodes = router.discover_by_capability(params.get("capability", ""))
        return {"nodes": [n.id for n in nodes]}
    elif tool == "route":
        node = router.route(params.get("capability", ""))
        return {"endpoint": node.endpoint if node else None}
    elif tool == "topology":
        return router.get_topology()
    else:
        raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8004)
