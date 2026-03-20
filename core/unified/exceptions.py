"""
core/unified/exceptions.py
===========================
Galaxy 系统统一异常体系。

所有统一模块必须通过此文件中定义的异常类报告错误，禁止直接抛出裸异常。
"""

from __future__ import annotations


# ============================================================================
# 基础异常
# ============================================================================


class GalaxyError(Exception):
    """Galaxy 系统顶级异常"""

    def __init__(self, message: str, code: str = "GALAXY_ERROR", **extra: object) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.extra = extra

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(code={self.code!r}, message={self.message!r})"


# ============================================================================
# 连接相关异常
# ============================================================================


class ConnectionError(GalaxyError):
    """连接层通用异常"""

    def __init__(self, message: str, device_id: str = "", **extra: object) -> None:
        super().__init__(message, code="CONNECTION_ERROR", **extra)
        self.device_id = device_id


class DeviceNotFoundError(ConnectionError):
    """目标设备未注册或已下线"""

    def __init__(self, device_id: str) -> None:
        super().__init__(
            f"Device '{device_id}' not found or offline",
            device_id=device_id,
            code="DEVICE_NOT_FOUND",
        )


class DeviceSendError(ConnectionError):
    """消息发送失败"""

    def __init__(self, device_id: str, reason: str = "") -> None:
        super().__init__(
            f"Failed to send message to device '{device_id}': {reason}",
            device_id=device_id,
            code="DEVICE_SEND_ERROR",
        )


class DeviceTimeoutError(ConnectionError):
    """设备命令超时"""

    def __init__(self, device_id: str, command_id: str = "", timeout: float = 0.0) -> None:
        super().__init__(
            f"Command '{command_id}' to device '{device_id}' timed out after {timeout}s",
            device_id=device_id,
            code="DEVICE_TIMEOUT",
        )


# ============================================================================
# 设备管理相关异常
# ============================================================================


class DeviceManagerError(GalaxyError):
    """设备管理器通用异常"""

    def __init__(self, message: str, **extra: object) -> None:
        super().__init__(message, code="DEVICE_MANAGER_ERROR", **extra)


class DeviceAlreadyRegisteredError(DeviceManagerError):
    """设备已注册（重复注册场景）"""

    def __init__(self, device_id: str) -> None:
        super().__init__(
            f"Device '{device_id}' is already registered",
            code="DEVICE_ALREADY_REGISTERED",
        )


class DeviceRegistrationError(DeviceManagerError):
    """设备注册失败"""

    def __init__(self, device_id: str, reason: str = "") -> None:
        super().__init__(
            f"Failed to register device '{device_id}': {reason}",
            code="DEVICE_REGISTRATION_ERROR",
        )


# ============================================================================
# 配置相关异常
# ============================================================================


class ConfigError(GalaxyError):
    """配置管理器通用异常"""

    def __init__(self, message: str, code: str = "CONFIG_ERROR", **extra: object) -> None:
        super().__init__(message, code=code, **extra)


class ConfigKeyNotFoundError(ConfigError):
    """配置键不存在"""

    def __init__(self, key: str) -> None:
        super().__init__(f"Config key '{key}' not found", code="CONFIG_KEY_NOT_FOUND")


# ============================================================================
# LLM 路由相关异常
# ============================================================================


class LLMRouterError(GalaxyError):
    """LLM 路由器通用异常"""

    def __init__(self, message: str, code: str = "LLM_ROUTER_ERROR", **extra: object) -> None:
        super().__init__(message, code=code, **extra)


class NoAvailableProviderError(LLMRouterError):
    """没有可用的 LLM 提供商"""

    def __init__(self, task_type: str = "") -> None:
        super().__init__(
            f"No available LLM provider for task type '{task_type}'",
            code="NO_AVAILABLE_PROVIDER",
        )


class LLMProviderError(LLMRouterError):
    """LLM 提供商调用失败"""

    def __init__(self, provider: str, reason: str = "") -> None:
        super().__init__(
            f"LLM provider '{provider}' failed: {reason}",
            code="LLM_PROVIDER_ERROR",
        )
