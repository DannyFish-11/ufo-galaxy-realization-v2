#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
能力管理器 (Capability Manager)
================================

OpenClaw 风格的能力注册、发现和调用系统
与现有 node_registry 集成，提供统一的能力索引

功能：
1. 能力注册和注销
2. 能力发现和查询
3. 能力状态跟踪（在线/离线）
4. 持久化能力索引到 JSON

作者：Manus AI (Round 2 - R-4)
日期：2026-02-11
"""

import json
import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Set, Optional, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum

logger = logging.getLogger("CapabilityManager")


# ============================================================================
# 能力状态定义
# ============================================================================

class CapabilityStatus(Enum):
    """能力状态"""
    UNKNOWN = "unknown"
    ONLINE = "online"
    OFFLINE = "offline"
    ERROR = "error"


# ============================================================================
# 能力数据模型
# ============================================================================

@dataclass
class Capability:
    """能力定义"""
    name: str
    description: str
    node_id: str
    node_name: str
    category: str = "general"
    input_schema: Dict[str, Any] = field(default_factory=dict)
    output_schema: Dict[str, Any] = field(default_factory=dict)
    status: CapabilityStatus = CapabilityStatus.UNKNOWN
    last_updated: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        data = asdict(self)
        data['status'] = self.status.value
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Capability':
        """从字典创建"""
        if 'status' in data and isinstance(data['status'], str):
            data['status'] = CapabilityStatus(data['status'])
        return cls(**data)


# ============================================================================
# 能力管理器
# ============================================================================

class CapabilityManager:
    """
    能力管理器 - OpenClaw 风格的能力注册和发现
    
    与 NodeRegistry 集成，提供更高层次的能力抽象
    """
    
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, config_dir: Optional[Path] = None):
        if self._initialized:
            return
        
        self.config_dir = config_dir or Path(__file__).parent.parent / "config"
        self.config_file = self.config_dir / "capabilities.json"
        
        # 能力索引：capability_name -> Capability
        self.capabilities: Dict[str, Capability] = {}
        
        # 节点能力映射：node_id -> Set[capability_name]
        self.node_capabilities: Dict[str, Set[str]] = {}
        
        # 分类索引：category -> Set[capability_name]
        self.category_index: Dict[str, Set[str]] = {}
        
        self._lock = asyncio.Lock()
        self._initialized = True
        
        # 加载已保存的能力
        self._load_capabilities()
        
        logger.info("能力管理器已初始化")
    
    # ========================================================================
    # 能力注册
    # ========================================================================
    
    async def register_capability(
        self,
        name: str,
        description: str,
        node_id: str,
        node_name: str,
        category: str = "general",
        input_schema: Optional[Dict[str, Any]] = None,
        output_schema: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        注册能力
        
        Args:
            name: 能力名称（唯一标识）
            description: 能力描述
            node_id: 提供此能力的节点ID
            node_name: 节点名称
            category: 能力分类
            input_schema: 输入参数模式
            output_schema: 输出结果模式
            
        Returns:
            是否注册成功
        """
        async with self._lock:
            capability = Capability(
                name=name,
                description=description,
                node_id=node_id,
                node_name=node_name,
                category=category,
                input_schema=input_schema or {},
                output_schema=output_schema or {},
                status=CapabilityStatus.ONLINE
            )
            
            # 注册能力
            self.capabilities[name] = capability
            
            # 更新节点能力映射
            if node_id not in self.node_capabilities:
                self.node_capabilities[node_id] = set()
            self.node_capabilities[node_id].add(name)
            
            # 更新分类索引
            if category not in self.category_index:
                self.category_index[category] = set()
            self.category_index[category].add(name)
            
            logger.info(f"能力已注册: {name} (节点: {node_name})")
            
            # 持久化
            await self._save_capabilities()
            
            return True
    
    async def unregister_capability(self, name: str) -> bool:
        """
        注销能力
        
        Args:
            name: 能力名称
            
        Returns:
            是否注销成功
        """
        async with self._lock:
            if name not in self.capabilities:
                return False
            
            capability = self.capabilities[name]
            node_id = capability.node_id
            category = capability.category
            
            # 从索引中移除
            if node_id in self.node_capabilities:
                self.node_capabilities[node_id].discard(name)
                if not self.node_capabilities[node_id]:
                    del self.node_capabilities[node_id]
            
            if category in self.category_index:
                self.category_index[category].discard(name)
                if not self.category_index[category]:
                    del self.category_index[category]
            
            # 删除能力
            del self.capabilities[name]
            
            logger.info(f"能力已注销: {name}")
            
            # 持久化
            await self._save_capabilities()
            
            return True
    
    async def update_capability_status(
        self,
        name: str,
        status: CapabilityStatus
    ) -> bool:
        """
        更新能力状态
        
        Args:
            name: 能力名称
            status: 新状态
            
        Returns:
            是否更新成功
        """
        async with self._lock:
            if name not in self.capabilities:
                return False
            
            self.capabilities[name].status = status
            self.capabilities[name].last_updated = datetime.now().isoformat()
            
            logger.debug(f"能力状态已更新: {name} -> {status.value}")
            
            # 持久化
            await self._save_capabilities()
            
            return True
    
    async def update_node_status(
        self,
        node_id: str,
        status: CapabilityStatus
    ) -> int:
        """
        批量更新节点的所有能力状态
        
        Args:
            node_id: 节点ID
            status: 新状态
            
        Returns:
            更新的能力数量
        """
        count = 0
        if node_id in self.node_capabilities:
            for cap_name in self.node_capabilities[node_id]:
                if await self.update_capability_status(cap_name, status):
                    count += 1
        
        return count
    
    # ========================================================================
    # 能力发现
    # ========================================================================
    
    def discover_capabilities(
        self,
        category: Optional[str] = None,
        status: Optional[CapabilityStatus] = None,
        node_id: Optional[str] = None
    ) -> List[Capability]:
        """
        发现能力
        
        Args:
            category: 按分类筛选
            status: 按状态筛选
            node_id: 按节点筛选
            
        Returns:
            能力列表
        """
        results = list(self.capabilities.values())
        
        if category:
            results = [c for c in results if c.category == category]
        
        if status:
            results = [c for c in results if c.status == status]
        
        if node_id:
            results = [c for c in results if c.node_id == node_id]
        
        return results
    
    def get_capability(self, name: str) -> Optional[Capability]:
        """
        获取能力
        
        Args:
            name: 能力名称
            
        Returns:
            能力对象，不存在返回 None
        """
        return self.capabilities.get(name)
    
    def get_online_capabilities(self) -> List[Capability]:
        """获取所有在线能力"""
        return self.discover_capabilities(status=CapabilityStatus.ONLINE)
    
    def get_node_capabilities(self, node_id: str) -> List[Capability]:
        """获取节点的所有能力"""
        return self.discover_capabilities(node_id=node_id)
    
    def get_capabilities_by_category(self, category: str) -> List[Capability]:
        """按分类获取能力"""
        return self.discover_capabilities(category=category)
    
    def find_capability_by_keyword(self, keyword: str) -> List[Capability]:
        """
        通过关键字搜索能力
        
        Args:
            keyword: 搜索关键字（匹配名称或描述）
            
        Returns:
            匹配的能力列表
        """
        keyword_lower = keyword.lower()
        return [
            cap for cap in self.capabilities.values()
            if keyword_lower in cap.name.lower() or keyword_lower in cap.description.lower()
        ]
    
    # ========================================================================
    # 统计和状态
    # ========================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取能力统计信息
        
        Returns:
            统计数据字典
        """
        total = len(self.capabilities)
        online = len(self.discover_capabilities(status=CapabilityStatus.ONLINE))
        offline = len(self.discover_capabilities(status=CapabilityStatus.OFFLINE))
        
        categories = {}
        for category, cap_names in self.category_index.items():
            categories[category] = len(cap_names)
        
        return {
            "total_capabilities": total,
            "online": online,
            "offline": offline,
            "unknown": total - online - offline,
            "categories": categories,
            "nodes_with_capabilities": len(self.node_capabilities)
        }
    
    def get_status_summary(self) -> Dict[str, Any]:
        """
        获取完整状态摘要
        
        Returns:
            状态摘要
        """
        stats = self.get_stats()
        
        capabilities_list = []
        for cap in self.capabilities.values():
            capabilities_list.append({
                "name": cap.name,
                "description": cap.description,
                "node_id": cap.node_id,
                "node_name": cap.node_name,
                "category": cap.category,
                "status": cap.status.value,
                "last_updated": cap.last_updated
            })
        
        return {
            "stats": stats,
            "capabilities": capabilities_list,
            "timestamp": datetime.now().isoformat()
        }
    
    # ========================================================================
    # 持久化
    # ========================================================================
    
    def _load_capabilities(self):
        """从文件加载能力"""
        if not self.config_file.exists():
            logger.info("能力配置文件不存在，将创建新文件")
            return
        
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            capabilities_data = data.get('capabilities', [])
            for cap_data in capabilities_data:
                cap = Capability.from_dict(cap_data)
                self.capabilities[cap.name] = cap
                
                # 重建索引
                node_id = cap.node_id
                if node_id not in self.node_capabilities:
                    self.node_capabilities[node_id] = set()
                self.node_capabilities[node_id].add(cap.name)
                
                category = cap.category
                if category not in self.category_index:
                    self.category_index[category] = set()
                self.category_index[category].add(cap.name)
            
            logger.info(f"已加载 {len(self.capabilities)} 个能力")
            
        except Exception as e:
            logger.error(f"加载能力配置失败: {e}")
    
    async def _save_capabilities(self):
        """保存能力到文件"""
        try:
            self.config_dir.mkdir(exist_ok=True, parents=True)
            
            capabilities_list = [cap.to_dict() for cap in self.capabilities.values()]
            
            data = {
                "version": "1.0.0",
                "timestamp": datetime.now().isoformat(),
                "capabilities": capabilities_list
            }
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            logger.debug(f"已保存 {len(capabilities_list)} 个能力到配置文件")
            
        except Exception as e:
            logger.error(f"保存能力配置失败: {e}")


# ============================================================================
# 全局实例
# ============================================================================

_capability_manager: Optional[CapabilityManager] = None


def get_capability_manager() -> CapabilityManager:
    """获取全局能力管理器实例"""
    global _capability_manager
    if _capability_manager is None:
        _capability_manager = CapabilityManager()
    return _capability_manager


# ============================================================================
# 便捷函数
# ============================================================================

async def register_capability(
    name: str,
    description: str,
    node_id: str,
    node_name: str,
    category: str = "general",
    **kwargs
) -> bool:
    """注册能力（便捷函数）"""
    manager = get_capability_manager()
    return await manager.register_capability(
        name, description, node_id, node_name, category, **kwargs
    )


def discover_capabilities(**filters) -> List[Capability]:
    """发现能力（便捷函数）"""
    manager = get_capability_manager()
    return manager.discover_capabilities(**filters)


def get_capability(name: str) -> Optional[Capability]:
    """获取能力（便捷函数）"""
    manager = get_capability_manager()
    return manager.get_capability(name)
