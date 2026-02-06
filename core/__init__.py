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

# 延迟导入其他模块（避免循环依赖）
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
    
    # 工厂函数
    'get_device_agent_manager',
    'get_device_status_api',
    'get_microsoft_ufo_integration',
    'get_system_load_monitor',
]

__version__ = '2.0.0'
