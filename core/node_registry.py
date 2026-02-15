#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
节点注册表和服务发现模块
========================

提供节点的统一注册、发现和调用机制：
1. 节点注册和元数据管理
2. 服务发现和健康检查
3. 节点间通信协调
4. 动态节点加载

作者：Manus AI
日期：2026-02-06
"""

import os
import sys
import json
import asyncio
import logging
import importlib
import importlib.util
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable, Type, Set
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum, auto
from abc import ABC, abstractmethod

logger = logging.getLogger("NodeRegistry")

# 延迟导入以避免循环依赖
def _get_capability_manager():
    from .capability_manager import get_capability_manager, CapabilityStatus
    return get_capability_manager(), CapabilityStatus

def _get_connection_manager():
    from .connection_manager import get_connection_manager
    return get_connection_manager()


# ============================================================================
# 节点状态和类型定义
# ============================================================================

class NodeStatus(Enum):
    """节点状态"""
    UNKNOWN = auto()
    REGISTERED = auto()
    INITIALIZING = auto()
    READY = auto()
    RUNNING = auto()
    PAUSED = auto()
    ERROR = auto()
    STOPPED = auto()


class NodeCategory(Enum):
    """节点类别"""
    CORE = "core"                   # 核心节点
    LLM = "llm"                     # LLM 相关
    COMMUNICATION = "communication" # 通信节点
    HARDWARE = "hardware"           # 硬件节点
    INTEGRATION = "integration"     # 集成节点
    UTILITY = "utility"             # 工具节点
    ADVANCED = "advanced"           # 高级节点
    RESERVED = "reserved"           # 保留节点


# ============================================================================
# 节点元数据
# ============================================================================

@dataclass
class NodeCapability:
    """节点能力"""
    name: str
    description: str
    input_schema: Dict[str, Any] = field(default_factory=dict)
    output_schema: Dict[str, Any] = field(default_factory=dict)
    async_support: bool = True
    requires_auth: bool = False


@dataclass
class NodeMetadata:
    """节点元数据"""
    node_id: str
    name: str
    version: str = "1.0.0"
    category: NodeCategory = NodeCategory.UTILITY
    description: str = ""
    author: str = "UFO Galaxy"
    
    # 依赖
    dependencies: List[str] = field(default_factory=list)
    python_packages: List[str] = field(default_factory=list)
    
    # 能力
    capabilities: List[NodeCapability] = field(default_factory=list)
    
    # 配置
    config_schema: Dict[str, Any] = field(default_factory=dict)
    default_config: Dict[str, Any] = field(default_factory=dict)
    
    # 运行时信息
    status: NodeStatus = NodeStatus.UNKNOWN
    health_score: float = 1.0
    last_health_check: Optional[datetime] = None
    error_message: Optional[str] = None
    
    # 统计
    call_count: int = 0
    success_count: int = 0
    avg_response_time: float = 0.0


# ============================================================================
# 节点基类
# ============================================================================

class BaseNode(ABC):
    """节点基类 - 所有节点必须继承此类"""
    
    def __init__(self, node_id: str, name: str):
        self.node_id = node_id
        self.name = name
        self.metadata = NodeMetadata(node_id=node_id, name=name)
        self.config: Dict[str, Any] = {}
        self.logger = logging.getLogger(f"Node.{name}")
        self._initialized = False
        
    @abstractmethod
    async def initialize(self) -> bool:
        """初始化节点"""
        pass
        
    @abstractmethod
    async def execute(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行节点操作"""
        pass
        
    @abstractmethod
    async def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        pass
        
    async def shutdown(self):
        """关闭节点"""
        self._initialized = False
        self.metadata.status = NodeStatus.STOPPED
        
    def get_capabilities(self) -> List[str]:
        """获取节点能力列表"""
        return [cap.name for cap in self.metadata.capabilities]
        
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "node_id": self.node_id,
            "name": self.name,
            "status": self.metadata.status.name,
            "capabilities": self.get_capabilities(),
            "health_score": self.metadata.health_score,
            "call_count": self.metadata.call_count
        }


# ============================================================================
# 节点注册表
# ============================================================================

class NodeRegistry:
    """节点注册表 - 管理所有节点的注册和发现"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
        
    def __init__(self):
        if self._initialized:
            return
            
        self.nodes: Dict[str, BaseNode] = {}
        self.metadata: Dict[str, NodeMetadata] = {}
        self.node_classes: Dict[str, Type[BaseNode]] = {}
        self.capability_index: Dict[str, Set[str]] = {}  # capability -> node_ids
        self.category_index: Dict[NodeCategory, Set[str]] = {}  # category -> node_ids
        
        self._lock = asyncio.Lock()
        self._health_check_interval = 30  # 秒
        self._health_check_task: Optional[asyncio.Task] = None
        
        self._initialized = True
        logger.info("节点注册表已初始化")
        
    # ========================================================================
    # 节点注册
    # ========================================================================
    
    async def register_node(self, node: BaseNode) -> bool:
        """注册节点"""
        async with self._lock:
            node_id = node.node_id
            
            if node_id in self.nodes:
                logger.warning(f"节点已存在，将覆盖: {node_id}")
                
            self.nodes[node_id] = node
            self.metadata[node_id] = node.metadata
            
            # 更新能力索引
            for cap in node.metadata.capabilities:
                if cap.name not in self.capability_index:
                    self.capability_index[cap.name] = set()
                self.capability_index[cap.name].add(node_id)
                
            # 更新类别索引
            category = node.metadata.category
            if category not in self.category_index:
                self.category_index[category] = set()
            self.category_index[category].add(node_id)
            
            node.metadata.status = NodeStatus.REGISTERED
            
            # ===== 集成：注册能力到能力管理器 =====
            try:
                capability_manager, CapabilityStatus = _get_capability_manager()
                for cap in node.metadata.capabilities:
                    await capability_manager.register_capability(
                        name=cap.name,
                        description=cap.description,
                        node_id=node_id,
                        node_name=node.name,
                        category=node.metadata.category.value,
                        input_schema=cap.input_schema,
                        output_schema=cap.output_schema
                    )
            except Exception as e:
                logger.warning(f"能力注册失败 (非致命): {e}")
            
            logger.info(f"节点已注册: {node_id} ({node.name})")
            return True
            
    async def unregister_node(self, node_id: str) -> bool:
        """注销节点"""
        async with self._lock:
            if node_id not in self.nodes:
                return False
                
            node = self.nodes[node_id]
            
            # 关闭节点
            await node.shutdown()
            
            # 从索引中移除
            for cap in node.metadata.capabilities:
                if cap.name in self.capability_index:
                    self.capability_index[cap.name].discard(node_id)
                    
            category = node.metadata.category
            if category in self.category_index:
                self.category_index[category].discard(node_id)
                
            del self.nodes[node_id]
            del self.metadata[node_id]
            
            logger.info(f"节点已注销: {node_id}")
            return True
            
    def register_node_class(self, node_id: str, node_class: Type[BaseNode]):
        """注册节点类（延迟实例化）"""
        self.node_classes[node_id] = node_class
        logger.debug(f"节点类已注册: {node_id}")
        
    # ========================================================================
    # 节点发现
    # ========================================================================
    
    def get_node(self, node_id: str) -> Optional[BaseNode]:
        """获取节点"""
        return self.nodes.get(node_id)
        
    def get_nodes_by_capability(self, capability: str) -> List[BaseNode]:
        """按能力获取节点"""
        node_ids = self.capability_index.get(capability, set())
        return [self.nodes[nid] for nid in node_ids if nid in self.nodes]
        
    def get_nodes_by_category(self, category: NodeCategory) -> List[BaseNode]:
        """按类别获取节点"""
        node_ids = self.category_index.get(category, set())
        return [self.nodes[nid] for nid in node_ids if nid in self.nodes]
        
    def get_all_nodes(self) -> List[BaseNode]:
        """获取所有节点"""
        return list(self.nodes.values())
        
    def get_ready_nodes(self) -> List[BaseNode]:
        """获取就绪的节点"""
        return [
            node for node in self.nodes.values()
            if node.metadata.status in [NodeStatus.READY, NodeStatus.RUNNING]
        ]
        
    def find_best_node_for_capability(self, capability: str) -> Optional[BaseNode]:
        """为能力找到最佳节点"""
        nodes = self.get_nodes_by_capability(capability)
        if not nodes:
            return None
            
        # 按健康分数和响应时间排序
        ready_nodes = [n for n in nodes if n.metadata.status in [NodeStatus.READY, NodeStatus.RUNNING]]
        if not ready_nodes:
            return nodes[0]  # 返回第一个可用的
            
        return max(ready_nodes, key=lambda n: (n.metadata.health_score, -n.metadata.avg_response_time))
        
    # ========================================================================
    # 节点调用
    # ========================================================================
    
    async def call_node(self, node_id: str, action: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """调用节点"""
        node = self.get_node(node_id)
        if not node:
            return {"success": False, "error": f"节点不存在: {node_id}"}
            
        if node.metadata.status not in [NodeStatus.READY, NodeStatus.RUNNING]:
            return {"success": False, "error": f"节点未就绪: {node.metadata.status.name}"}
            
        params = params or {}
        start_time = datetime.now()
        
        try:
            result = await node.execute(action, params)
            
            # 更新统计
            node.metadata.call_count += 1
            node.metadata.success_count += 1
            elapsed = (datetime.now() - start_time).total_seconds()
            node.metadata.avg_response_time = (
                node.metadata.avg_response_time * 0.9 + elapsed * 0.1
            )
            
            return {"success": True, "data": result}
            
        except Exception as e:
            node.metadata.call_count += 1
            logger.error(f"节点调用失败 {node_id}.{action}: {e}")
            return {"success": False, "error": str(e)}
            
    async def call_capability(self, capability: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """按能力调用（自动选择最佳节点）"""
        node = self.find_best_node_for_capability(capability)
        if not node:
            return {"success": False, "error": f"没有节点提供此能力: {capability}"}
            
        return await self.call_node(node.node_id, capability, params)
        
    # ========================================================================
    # 健康检查
    # ========================================================================
    
    async def check_node_health(self, node_id: str) -> Dict[str, Any]:
        """检查单个节点健康"""
        node = self.get_node(node_id)
        if not node:
            return {"healthy": False, "error": "节点不存在"}
            
        try:
            result = await asyncio.wait_for(node.health_check(), timeout=5.0)
            node.metadata.last_health_check = datetime.now()
            node.metadata.health_score = result.get("score", 1.0)
            node.metadata.error_message = None
            
            # ===== 集成：更新能力状态 =====
            try:
                capability_manager, CapabilityStatus = _get_capability_manager()
                status = CapabilityStatus.ONLINE if result.get("score", 0) > 0.5 else CapabilityStatus.ERROR
                await capability_manager.update_node_status(node_id, status)
            except Exception as e:
                logger.debug(f"能力状态更新失败 (非致命): {e}")
            
            return {"healthy": True, **result}
        except asyncio.TimeoutError:
            node.metadata.health_score = 0.0
            node.metadata.error_message = "健康检查超时"
            
            # ===== 集成：标记能力离线 =====
            try:
                capability_manager, CapabilityStatus = _get_capability_manager()
                await capability_manager.update_node_status(node_id, CapabilityStatus.OFFLINE)
            except Exception as e:
                logger.debug(f"能力状态更新失败 (非致命): {e}")
            
            return {"healthy": False, "error": "超时"}
        except Exception as e:
            node.metadata.health_score = 0.0
            node.metadata.error_message = str(e)
            
            # ===== 集成：标记能力错误 =====
            try:
                capability_manager, CapabilityStatus = _get_capability_manager()
                await capability_manager.update_node_status(node_id, CapabilityStatus.ERROR)
            except Exception as e:
                logger.debug(f"能力状态更新失败 (非致命): {e}")
            
            return {"healthy": False, "error": str(e)}
            
    async def check_all_health(self) -> Dict[str, Dict[str, Any]]:
        """检查所有节点健康"""
        results = {}
        for node_id in self.nodes:
            results[node_id] = await self.check_node_health(node_id)
        return results
        
    async def start_health_monitor(self):
        """启动健康监控"""
        if self._health_check_task:
            return
            
        async def monitor_loop():
            while True:
                await asyncio.sleep(self._health_check_interval)
                await self.check_all_health()
                
        self._health_check_task = asyncio.create_task(monitor_loop())
        logger.info("健康监控已启动")
        
    async def stop_health_monitor(self):
        """停止健康监控"""
        if self._health_check_task:
            self._health_check_task.cancel()
            self._health_check_task = None
            
    # ========================================================================
    # 节点加载
    # ========================================================================
    
    async def load_node_from_path(self, node_path: Path) -> Optional[BaseNode]:
        """从路径加载节点"""
        main_py = node_path / "main.py"
        if not main_py.exists():
            return None
            
        node_id = node_path.name
        
        try:
            # 动态加载模块
            spec = importlib.util.spec_from_file_location(f"node_{node_id}", main_py)
            module = importlib.util.module_from_spec(spec)
            sys.modules[f"node_{node_id}"] = module
            spec.loader.exec_module(module)
            
            # 查找节点类
            node_class = None
            for name, obj in vars(module).items():
                if (isinstance(obj, type) and 
                    issubclass(obj, BaseNode) and 
                    obj is not BaseNode):
                    node_class = obj
                    break
                    
            if node_class:
                node = node_class(node_id, node_id)
                await self.register_node(node)
                return node
            else:
                # 创建包装节点
                wrapper = self._create_wrapper_node(node_id, module)
                await self.register_node(wrapper)
                return wrapper
                
        except Exception as e:
            logger.error(f"加载节点失败 {node_id}: {e}")
            return None
            
    def _create_wrapper_node(self, node_id: str, module) -> BaseNode:
        """为旧式节点创建包装器"""
        
        class WrapperNode(BaseNode):
            def __init__(self, nid: str, name: str, mod):
                super().__init__(nid, name)
                self.module = mod
                
            async def initialize(self) -> bool:
                if hasattr(self.module, 'initialize'):
                    if asyncio.iscoroutinefunction(self.module.initialize):
                        await self.module.initialize()
                    else:
                        self.module.initialize()
                self._initialized = True
                self.metadata.status = NodeStatus.READY
                return True
                
            async def execute(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
                if hasattr(self.module, action):
                    func = getattr(self.module, action)
                    if asyncio.iscoroutinefunction(func):
                        return await func(**params)
                    else:
                        return func(**params)
                elif hasattr(self.module, 'execute'):
                    func = self.module.execute
                    if asyncio.iscoroutinefunction(func):
                        return await func(action, params)
                    else:
                        return func(action, params)
                else:
                    raise NotImplementedError(f"节点不支持操作: {action}")
                    
            async def health_check(self) -> Dict[str, Any]:
                return {"score": 1.0, "status": "ok"}
                
        return WrapperNode(node_id, node_id, module)
        
    async def load_all_nodes(self, nodes_dir: Path) -> Dict[str, bool]:
        """加载所有节点"""
        results = {}
        
        if not nodes_dir.exists():
            logger.warning(f"节点目录不存在: {nodes_dir}")
            return results
            
        for node_path in sorted(nodes_dir.iterdir()):
            if node_path.is_dir() and node_path.name.startswith("Node_"):
                node = await self.load_node_from_path(node_path)
                results[node_path.name] = node is not None
                
        logger.info(f"已加载 {sum(results.values())}/{len(results)} 个节点")
        return results
        
    # ========================================================================
    # 状态导出
    # ========================================================================
    
    def get_status(self) -> Dict[str, Any]:
        """获取注册表状态"""
        return {
            "total_nodes": len(self.nodes),
            "ready_nodes": len(self.get_ready_nodes()),
            "capabilities": list(self.capability_index.keys()),
            "categories": {
                cat.value: len(node_ids) 
                for cat, node_ids in self.category_index.items()
            },
            "nodes": {
                node_id: {
                    "name": node.name,
                    "status": node.metadata.status.name,
                    "health": node.metadata.health_score,
                    "calls": node.metadata.call_count
                }
                for node_id, node in self.nodes.items()
            }
        }
        
    def export_to_json(self) -> str:
        """导出为 JSON"""
        return json.dumps(self.get_status(), indent=2, ensure_ascii=False)


# ============================================================================
# 全局实例
# ============================================================================

_registry: Optional[NodeRegistry] = None


def get_registry() -> NodeRegistry:
    """获取全局注册表实例"""
    global _registry
    if _registry is None:
        _registry = NodeRegistry()
    return _registry


# ============================================================================
# 便捷函数
# ============================================================================

async def register_node(node: BaseNode) -> bool:
    """注册节点"""
    return await get_registry().register_node(node)


async def call_node(node_id: str, action: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
    """调用节点"""
    return await get_registry().call_node(node_id, action, params)


async def call_capability(capability: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
    """按能力调用"""
    return await get_registry().call_capability(capability, params)


def get_node(node_id: str) -> Optional[BaseNode]:
    """获取节点"""
    return get_registry().get_node(node_id)


def get_all_nodes() -> List[BaseNode]:
    """获取所有节点"""
    return get_registry().get_all_nodes()


# ============================================================================
# 测试
# ============================================================================

if __name__ == "__main__":
    async def test():
        registry = get_registry()
        
        # 创建测试节点
        class TestNode(BaseNode):
            async def initialize(self) -> bool:
                self.metadata.status = NodeStatus.READY
                self.metadata.capabilities.append(
                    NodeCapability(name="test", description="测试能力")
                )
                return True
                
            async def execute(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
                return {"action": action, "params": params}
                
            async def health_check(self) -> Dict[str, Any]:
                return {"score": 1.0, "status": "healthy"}
                
        # 注册测试节点
        node = TestNode("test_node", "测试节点")
        await node.initialize()
        await registry.register_node(node)
        
        # 调用节点
        result = await registry.call_node("test_node", "test", {"key": "value"})
        print(f"调用结果: {result}")
        
        # 打印状态
        print(f"注册表状态: {registry.export_to_json()}")
        
    asyncio.run(test())
