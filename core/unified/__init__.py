"""
core/unified/__init__.py
=========================
Galaxy 统一模块公开导出入口。

使用方式：
    from core.unified import (
        UnifiedDevice, UnifiedDeviceType, UnifiedDeviceStatus,
        UnifiedConnectionManager, get_unified_connection_manager,
        UnifiedDeviceManager, get_unified_device_manager,
        UnifiedConfigManager, get_unified_config_manager,
        UnifiedLLMRouter, get_unified_llm_router,
    )
"""

from .exceptions import (
    ConfigError,
    ConfigKeyNotFoundError,
    ConnectionError,
    DeviceAlreadyRegisteredError,
    DeviceManagerError,
    DeviceNotFoundError,
    DeviceRegistrationError,
    DeviceSendError,
    DeviceTimeoutError,
    GalaxyError,
    LLMProviderError,
    LLMRouterError,
    NoAvailableProviderError,
)
from .models import (
    DeviceCommand,
    DeviceCommandResult,
    LLMRequest,
    LLMResponse,
    LLMTaskType,
    UnifiedConnectionInfo,
    UnifiedConnectionState,
    UnifiedDevice,
    UnifiedDeviceStatus,
    UnifiedDeviceType,
    UnifiedMessage,
    UnifiedMessageType,
)
from .connection_manager import UnifiedConnectionManager, get_unified_connection_manager
from .device_manager import UnifiedDeviceManager, get_unified_device_manager
from .config_manager import UnifiedConfigManager, get_unified_config_manager
from .llm_router import UnifiedLLMRouter, get_unified_llm_router

__all__ = [
    # exceptions
    "GalaxyError",
    "ConnectionError",
    "DeviceNotFoundError",
    "DeviceSendError",
    "DeviceTimeoutError",
    "DeviceManagerError",
    "DeviceAlreadyRegisteredError",
    "DeviceRegistrationError",
    "ConfigError",
    "ConfigKeyNotFoundError",
    "LLMRouterError",
    "NoAvailableProviderError",
    "LLMProviderError",
    # models
    "UnifiedDeviceType",
    "UnifiedDeviceStatus",
    "UnifiedConnectionState",
    "UnifiedMessageType",
    "UnifiedDevice",
    "UnifiedConnectionInfo",
    "UnifiedMessage",
    "DeviceCommand",
    "DeviceCommandResult",
    "LLMTaskType",
    "LLMRequest",
    "LLMResponse",
    # managers
    "UnifiedConnectionManager",
    "get_unified_connection_manager",
    "UnifiedDeviceManager",
    "get_unified_device_manager",
    "UnifiedConfigManager",
    "get_unified_config_manager",
    "UnifiedLLMRouter",
    "get_unified_llm_router",
]
