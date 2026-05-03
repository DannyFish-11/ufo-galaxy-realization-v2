"""
core/unified/exceptions.py
===========================
Galaxy 系统统一异常体系。

所有统一模块必须通过此文件中定义的异常类报告错误，禁止直接抛出裸异常。

设计说明
--------
``GalaxyError`` 继承自 ``core.error_framework.GalaxyError``，统一了两套错误体系：

- ``core.error_framework.GalaxyError``：框架层，携带 category/severity/recovery 元数据
- 本文件的 ``GalaxyError``：unified 层包装，额外携带结构化的 ``code`` 字段和
  ``extra`` 关键字参数，供设备管理和 LLM 路由等高层模块使用

任何 ``isinstance(err, core.error_framework.GalaxyError)`` 检查对本文件中的所有
异常类同样成立，不再存在双重定义。
"""

from __future__ import annotations

from ..error_framework import GalaxyError as _FrameworkGalaxyError


# ============================================================================
# 基础异常
# ============================================================================


class GalaxyError(_FrameworkGalaxyError):
    """Galaxy 系统顶级异常（unified 层）

    在 ``core.error_framework.GalaxyError`` 之上增加了 ``code``（结构化错误代码）
    和 ``extra``（任意关键字上下文）字段，以满足设备管理、LLM 路由等模块的分类需求。
    """

    def __init__(self, message: str, code: str = "GALAXY_ERROR", **extra: object) -> None:
        # 调用框架基类，使用默认的 category/severity/recovery。
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

    def __init__(self, message: str, device_id: str = "", code: str = "CONNECTION_ERROR", **extra: object) -> None:
        super().__init__(message, code=code, **extra)
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

    def __init__(self, message: str, code: str = "DEVICE_MANAGER_ERROR", **extra: object) -> None:
        super().__init__(message, code=code, **extra)


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
