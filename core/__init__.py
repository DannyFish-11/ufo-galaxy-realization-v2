#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UFO Galaxy Core 模块
====================

核心模块导出，提供统一的导入接口。

模块列表：
- node_registry: 节点注册表和服务发现
- node_protocol: 节点通信协议
- node_communication: 节点间通信
- device_agent_manager: 设备 Agent 管理
- device_status_api: 设备状态 API
- microsoft_ufo_integration: 微软 UFO 集成
- system_load_monitor: 系统负载监控
- cache: 统一缓存层 (Redis / 内存降级)
- monitoring: 监控告警 (熔断器 / 健康聚合 / 告警 / 指标)
- performance: 性能优化层 (压缩 / 限流 / 缓存 / 计时)
- command_router: 命令路由引擎 (并行/串行/重试/缓存)
- ai_intent: AI 意图理解 (解析 / 记忆 / 推荐 / 搜索)
- startup: 系统启动引导
- event_bridge: 事件总线桥接
"""

from .node_registry import (
    NodeRegistry,
    BaseNode,
    NodeMetadata,
    NodeCapability,
    NodeStatus,
    NodeCategory,
    get_registry,
    register_node,
    call_node,
    call_capability,
    get_node,
    get_all_nodes,
)

from .node_protocol import (
    Message,
    MessageHeader,
    MessageType,
    MessagePriority,
    Request,
    Response,
    Event,
    StreamMessage,
    StreamSession,
    MessageRouter,
    ProtocolAdapter,
)

# ============================================================================
# 延迟导入工厂函数（避免循环依赖 + 按需加载）
# ============================================================================

# --- 基础设施 ---

def get_device_agent_manager():
    from .device_agent_manager import DeviceAgentManager
    return DeviceAgentManager()

def get_device_status_api():
    from .device_status_api import app as device_status_app
    return device_status_app

def get_microsoft_ufo_integration():
    from .microsoft_ufo_integration import UFOIntegrationService
    return UFOIntegrationService()

def get_system_load_monitor():
    from .system_load_monitor import SystemLoadMonitor
    return SystemLoadMonitor()

def get_vision_pipeline(config=None):
    from .vision_pipeline import get_vision_pipeline as _get
    return _get(config)

# --- 新增核心子系统 ---

async def get_cache_manager(redis_url: str = ""):
    """获取全局缓存管理器实例（异步初始化）"""
    from .cache import get_cache
    return await get_cache(redis_url)

def get_monitoring():
    """获取全局监控管理器"""
    from .monitoring import get_monitoring_manager
    return get_monitoring_manager()

def get_performance_monitor():
    """获取全局性能监控器"""
    from .performance import PerformanceMonitor
    return PerformanceMonitor.instance()

def get_command_router(**kwargs):
    """获取全局命令路由器"""
    from .command_router import get_command_router as _get
    return _get(**kwargs)

def get_intent_parser():
    """获取 AI 意图解析器"""
    from .ai_intent import get_intent_parser as _get
    return _get()

def get_conversation_memory(**kwargs):
    """获取对话记忆"""
    from .ai_intent import get_conversation_memory as _get
    return _get(**kwargs)

def get_smart_recommender(**kwargs):
    """获取智能推荐器"""
    from .ai_intent import get_smart_recommender as _get
    return _get(**kwargs)


__all__ = [
    # 节点注册表
    'NodeRegistry',
    'BaseNode',
    'NodeMetadata',
    'NodeCapability',
    'NodeStatus',
    'NodeCategory',
    'get_registry',
    'register_node',
    'call_node',
    'call_capability',
    'get_node',
    'get_all_nodes',

    # 节点协议
    'Message',
    'MessageHeader',
    'MessageType',
    'MessagePriority',
    'Request',
    'Response',
    'Event',
    'StreamMessage',
    'StreamSession',
    'MessageRouter',
    'ProtocolAdapter',

    # 基础设施工厂
    'get_device_agent_manager',
    'get_device_status_api',
    'get_microsoft_ufo_integration',
    'get_system_load_monitor',
    'get_vision_pipeline',

    # 核心子系统工厂
    'get_cache_manager',
    'get_monitoring',
    'get_performance_monitor',
    'get_command_router',
    'get_intent_parser',
    'get_conversation_memory',
    'get_smart_recommender',
]

__version__ = '3.0.0'
