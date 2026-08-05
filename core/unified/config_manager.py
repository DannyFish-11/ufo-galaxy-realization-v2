"""
core/unified/config_manager.py
================================
Galaxy 系统统一配置管理器（单例）—  [COMPATIBILITY FACADE]

This module is a **compatibility facade**.  It is NOT a configuration authority.

Delegation chain
----------------
    UnifiedConfigManager
        └── _load_backend() → UnifiedConfig (core.unified_config)
                └── _load_config()            → config.json (static app config)
                └── _load_from_config_store() → runtime/config.json (canonical, via ConfigStore)
                                              → runtime/secrets.env  (canonical, via ConfigStore)
                └── _load_env()               → .env (legacy), then os.environ (highest priority)

Config source precedence (high → low)
--------------------------------------
1. os.environ                       — CLI / Docker / CI overrides
2. runtime/secrets.env              — written by ConfigService (canonical secrets)
3. runtime/config.json              — written by ConfigService (canonical non-secret config)
4. .env                             — legacy user-managed secrets file
5. config.json (root)               — static application defaults

The canonical config stack is:
    core.config_schema → core.config_store → core.config_service → core.config_preflight

See docs/CONFIGURATION_AUTHORITY.md for the full authority model.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from .exceptions import ConfigError, ConfigKeyNotFoundError

logger = logging.getLogger("Galaxy.Unified.ConfigManager")

# ---------------------------------------------------------------------------
# Authority sentinel — this module is a COMPATIBILITY FACADE, not an authority
# ---------------------------------------------------------------------------
UNIFIED_CONFIG_MANAGER_AUTHORITY: str = "UnifiedConfigManager.CompatibilityFacade"


class UnifiedConfigManager:
    """
    统一配置管理器（进程级单例）— [COMPATIBILITY FACADE].

    Delegates all reads/writes to UnifiedConfig (core.unified_config), which
    now merges config from the canonical ConfigStore (runtime/config.json +
    runtime/secrets.env) on top of the legacy config.json and .env sources.

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
        """从磁盘重新加载配置。

        真 bug 修复(面板 API-key 排查):此前漏了 `_load_from_config_store()`
        这一步 —— 它是 runtime/secrets.env(面板保存密钥的落盘位置)真正被读回
        Dashboard 层的地方。少了它,一次实时 reload() 不会把刚保存的密钥反映到
        `UnifiedConfig._config`,此前全靠 core/routes/config.py 里紧跟着的
        `os.environ.update()` 巧合掩盖(任何只走 Dashboard 层、不兜底
        os.environ 的调用方都会读不到)。顺序须与 UnifiedConfig.__init__ 一致
        (config.json → runtime store → .env/环境变量,后者优先级更高)。

        第二个真 bug:这里原先**只调那三个 loader,不清空**。
        ------------------------------------------------------
        而 loader 都是"往 dict 里写",于是 reload() 实际是 **merge 而不是 reload**:
        值**改了**能反映出来(后写覆盖前值),值**没了**却永远不消失 —— 面板上删掉
        一个配置项、或把它从 .env 里去掉,进程内那份仍旧照着旧值工作,直到重启。
        只影响删除、不影响修改,所以它安静且能活很久。

        ``UnifiedConfig.reload()`` 自己是对的(先 ``_config.clear()`` 再按同样顺序
        load)。这里的三步是把它**抄了一遍却漏了第一步** —— 典型的第二份实现漂移。
        所以现在优先**委托给后端自己的 reload()**,不再维护第二份顺序;只有后端没有
        reload() 时才退回手工三步(那种后端也就没有 _config 可清)。
        """
        try:
            backend_reload = getattr(self._backend, "reload", None)
            if callable(backend_reload):
                backend_reload()
            else:
                # 后端没有 reload():按 UnifiedConfig.__init__ 的顺序手工加载。
                # 这条分支下的后端(如 EnvConfigBackend)没有可清空的快照。
                if hasattr(self._backend, "_load_config"):
                    self._backend._load_config()
                if hasattr(self._backend, "_load_from_config_store"):
                    self._backend._load_from_config_store()
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
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)
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
