#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Galaxy Core 模块
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
    from .microsoft_ufo_integration import GalaxyIntegrationService
    return GalaxyIntegrationService()

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


# --- Agentic OS 子系统工厂 ---

def get_acl():
    """获取反腐败层 (ACL) 单例"""
    from .acl import acl
    return acl


def get_nats_bus():
    """获取 NATS JetStream 总线单例"""
    from .nats_bus import nats_bus
    return nats_bus


def get_master_brain():
    """获取 MasterBrain 控制面单例（未启用时返回 None）"""
    from .master_brain import get_master_brain as _get
    return _get()


def get_mcp_gateway():
    """获取 MCP 动态网关单例"""
    from .mcp_gateway import mcp_gateway
    return mcp_gateway


def get_constellation_runtime(config=None, enable_dag_evolution: bool = True):
    """获取 ConstellationRuntime 单例（统一规划→DAG→执行入口）"""
    from .constellation_runtime import get_constellation_runtime as _get
    return _get(config=config, enable_dag_evolution=enable_dag_evolution)


def get_device_pool_manager(strategy=None):
    """获取 DevicePoolManager 单例（统一设备池调度入口）"""
    from .device_pool_manager import get_device_pool_manager as _get, SchedulingStrategy
    kw = {}
    if strategy is not None:
        kw["strategy"] = strategy
    return _get(**kw)


def get_dag_evolver(max_replan_attempts: int = 3):
    """获取 DAGEvolver 实例（动态 DAG 演化）"""
    from .dag_evolver import DAGEvolver
    return DAGEvolver(max_replan_attempts=max_replan_attempts)


# --- 语音闭环工厂 (ASR + TTS) ---

def get_whisper_asr(model_size: str = ""):
    """获取 Whisper ASR 实例（语音识别）

    Args:
        model_size: 模型大小 (tiny/base/small/medium/large)，空字符串则自动选择。
    """
    from .asr import WhisperASR
    return WhisperASR(model_size=model_size or None)


def get_edge_tts_engine(voice: str = "zh-CN-XiaoxiaoNeural"):
    """获取 Edge TTS 引擎实例（语音合成）

    Args:
        voice: 声音ID，默认中文女声 XiaoxiaoNeural。
    """
    from .tts import EdgeTTSEngine
    return EdgeTTSEngine(voice=voice)


def get_voice_loop(galaxy_client, **kwargs):
    """获取 VoiceLoop 语音闭环实例

    Args:
        galaxy_client: Galaxy 客户端实例。
        **kwargs: 传递给 VoiceLoop 构造函数的参数。
    """
    from .voice_loop import VoiceLoop
    return VoiceLoop(galaxy_client, **kwargs)


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

    # Agentic OS 子系统工厂
    'get_acl',
    'get_nats_bus',
    'get_master_brain',
    'get_mcp_gateway',

    # Constellation / DAG / Device Pool (unified architecture)
    'get_constellation_runtime',
    'get_device_pool_manager',
    'get_dag_evolver',

    # 语音闭环 (ASR + TTS)
    'WhisperASR',
    'EdgeTTSEngine',
    'VoiceLoop',
]

__version__ = '3.0.0'
