"""
core/unified/config_manager.py
================================
Galaxy 系统统一配置管理器（单例）。

委托 core.unified_config.UnifiedConfig 处理实际的配置读写，
提供强类型接口和结构化日志。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from .exceptions import ConfigError, ConfigKeyNotFoundError

logger = logging.getLogger("Galaxy.Unified.ConfigManager")


class UnifiedConfigManager:
    """
    统一配置管理器（进程级单例）。

    公开 API：
        get(key, default) -> Any
        set(key, value) -> None
        delete(key) -> None
        keys() -> List[str]
        save() -> None
        reload() -> None
    """

    _instance: Optional["UnifiedConfigManager"] = None

    def __new__(cls) -> "UnifiedConfigManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:  # type: ignore[has-type]
            return

        # 优先委托给 core.unified_config（已有稳定实现）
        self._backend = self._load_backend()
        self._initialized = True

        logger.info(
            "UnifiedConfigManager initialized",
            extra={"event": "init", "backend": type(self._backend).__name__},
        )

    # ------------------------------------------------------------------
    # 内部：加载后端实现
    # ------------------------------------------------------------------

    @staticmethod
    def _load_backend() -> Any:
        """加载后端配置实现（优先使用 core.unified_config.UnifiedConfig）。"""
        try:
            # 导入 UnifiedConfig 类（非单例变量）以避免循环导入
            from core.unified_config import UnifiedConfig  # type: ignore
            backend = UnifiedConfig()  # UnifiedConfig 是单例，返回同一实例
            logger.info(
                "Using core.unified_config.UnifiedConfig as config backend",
                extra={"event": "backend_loaded"},
            )
            return backend
        except Exception as exc:
            logger.warning(
                "core.unified_config not available, falling back to env-only config",
                extra={"event": "backend_fallback", "reason": str(exc)},
            )
            return _EnvFallbackConfig()

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值。若键不存在且未提供 default 则返回 None。"""
        try:
            value = self._backend.get(key, default)
        except Exception as exc:
            logger.warning(
                "Config get failed",
                extra={"event": "get_error", "key": key, "reason": str(exc)},
            )
            return default
        return value

    def get_required(self, key: str) -> Any:
        """获取必需配置值，键不存在时抛出 ConfigKeyNotFoundError。"""
        value = self.get(key)
        if value is None:
            raise ConfigKeyNotFoundError(key)
        return value

    def set(self, key: str, value: Any) -> None:
        """设置配置值。"""
        try:
            self._backend.set(key, value)
            logger.debug(
                "Config key set",
                extra={"event": "set", "key": key},
            )
        except Exception as exc:
            raise ConfigError(f"Failed to set config key '{key}': {exc}") from exc

    def delete(self, key: str) -> None:
        """删除配置键。"""
        try:
            # UnifiedConfig 使用 dict 存储，直接操作
            if hasattr(self._backend, "_config"):
                self._backend._config.pop(key, None)
            logger.debug("Config key deleted", extra={"event": "delete", "key": key})
        except Exception as exc:
            raise ConfigError(f"Failed to delete config key '{key}': {exc}") from exc

    def keys(self) -> List[str]:
        """返回所有配置键。"""
        try:
            if hasattr(self._backend, "_config"):
                return list(self._backend._config.keys())
            return []
        except Exception:
            return []

    def save(self) -> None:
        """持久化配置到磁盘。"""
        try:
            self._backend.save()
            logger.info("Config saved", extra={"event": "save"})
        except Exception as exc:
            raise ConfigError(f"Failed to save config: {exc}") from exc

    def reload(self) -> None:
        """从磁盘重新加载配置。"""
        try:
            if hasattr(self._backend, "_load_config"):
                self._backend._load_config()
            if hasattr(self._backend, "_load_env"):
                self._backend._load_env()
            logger.info("Config reloaded", extra={"event": "reload"})
        except Exception as exc:
            raise ConfigError(f"Failed to reload config: {exc}") from exc

    def to_dict(self, include_sensitive: bool = False) -> Dict[str, Any]:
        """导出为可序列化字典。"""
        try:
            if hasattr(self._backend, "to_dict"):
                return self._backend.to_dict(include_sensitive=include_sensitive)
            if hasattr(self._backend, "_config"):
                return dict(self._backend._config)
        except Exception:
            pass
        return {}


# ============================================================================
# 纯环境变量回退（当 core.unified_config 不可用时）
# ============================================================================


class _EnvFallbackConfig:
    """仅读取环境变量的轻量级配置后端（回退用途）。"""

    def __init__(self) -> None:
        self._config: Dict[str, Any] = dict(os.environ)

    def get(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._config[key] = value

    def save(self) -> None:
        pass  # 环境变量不持久化

    def to_dict(self, include_sensitive: bool = False) -> Dict[str, Any]:
        return dict(self._config)


# ============================================================================
# 进程级单例访问函数
# ============================================================================


_manager: Optional[UnifiedConfigManager] = None


def get_unified_config_manager() -> UnifiedConfigManager:
    """返回进程级 UnifiedConfigManager 单例。"""
    global _manager
    if _manager is None:
        _manager = UnifiedConfigManager()
    return _manager
