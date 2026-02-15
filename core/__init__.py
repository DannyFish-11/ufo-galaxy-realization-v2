#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UFO Galaxy Core 模块
====================

核心模块导出，提供统一的导入接口。
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
)

from .node_communication import (
    UniversalCommunicator,
    SecureCommunicator,
    NodeIdentity,
    NodeType,
    RouteEntry,
    RoutingTable,
    create_communicator,
)

from .cache import (
    CacheManager,
    get_cache,
)

from .monitoring import (
    MonitoringManager,
    CircuitBreaker,
    HealthAggregator,
    AlertManager,
    MetricsCollector,
)

from .performance import (
    RateLimiter,
    RateLimitMiddleware,
    CachingMiddleware,
)

from .command_router import (
    CommandRouter,
    CommandResult,
)

from .ai_intent import (
    AIIntentEngine,
    IntentResult,
)

from .startup import (
    bootstrap_subsystems,
)

from .api_routes import (
    create_api_routes,
    create_websocket_routes,
)

# 版本信息
__version__ = "2.0.0"

__all__ = [
    # Node Registry
    "NodeRegistry",
    "BaseNode",
    "NodeMetadata",
    "NodeCapability",
    "NodeStatus",
    "NodeCategory",
    "get_registry",
    "register_node",
    "call_node",
    "call_capability",
    "get_node",
    "get_all_nodes",
    # Node Protocol
    "Message",
    "MessageHeader",
    "MessageType",
    "MessagePriority",
    "Request",
    "Response",
    "Event",
    "StreamMessage",
    "StreamSession",
    # Node Communication
    "UniversalCommunicator",
    "SecureCommunicator",
    "NodeIdentity",
    "NodeType",
    "RouteEntry",
    "RoutingTable",
    "create_communicator",
    # Cache
    "CacheManager",
    "get_cache",
    # Monitoring
    "MonitoringManager",
    "CircuitBreaker",
    "HealthAggregator",
    "AlertManager",
    "MetricsCollector",
    # Performance
    "RateLimiter",
    "RateLimitMiddleware",
    "CachingMiddleware",
    # Command Router
    "CommandRouter",
    "CommandResult",
    # AI Intent
    "AIIntentEngine",
    "IntentResult",
    # Startup
    "bootstrap_subsystems",
    # API Routes
    "create_api_routes",
    "create_websocket_routes",
]

# 安全模块
from .safe_eval import SafeEval, SafeEvalError, safe_eval, safe_literal_eval
from .secure_config import (
    SecureConfig, APIKeys, DatabaseConfig, SecurityConfig,
    get_config, get_api_key, get_database_url
)

__all__.extend([
    # Safe Eval
    "SafeEval", "SafeEvalError", "safe_eval", "safe_literal_eval",
    # Secure Config
    "SecureConfig", "APIKeys", "DatabaseConfig", "SecurityConfig",
    "get_config", "get_api_key", "get_database_url",
])
