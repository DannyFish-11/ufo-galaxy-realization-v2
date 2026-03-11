"""
Galaxy - 统一配置管理器
==========================

确保 WebUI 配置和主 UI 配置的一致性

功能：
1. 统一的配置存储
2. 配置热更新
3. 配置验证
4. 配置持久化

使用方法：
    from core.unified_config import config
    
    # 获取配置
    api_key = config.get("openai_api_key")
    
    # 设置配置
    config.set("openai_api_key", "sk-xxx")
    
    # 保存配置
    config.save()
"""

import os
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional
from dataclasses import dataclass, field
import threading

logger = logging.getLogger("Galaxy.Config")


@dataclass
class ConfigItem:
    """配置项"""
    key: str
    value: Any
    category: str = "general"
    description: str = ""
    sensitive: bool = False  # 是否敏感（如 API Key）


class UnifiedConfig:
    """
    Legacy 统一配置管理器（保留旧接口兼容性）

    内部委派至 `core.unified.config_manager.UnifiedConfigManager`（统一入口）。
    新代码请直接使用 `from core.unified import get_unified_config`。

    单例模式，确保全局配置一致。
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        # 委派至统一配置管理器
        from core.unified.config_manager import UnifiedConfigManager
        self._manager = UnifiedConfigManager()

        # 保留路径属性以兼容外部访问
        self.project_root = self._manager.project_root
        self.config_file = self._manager.config_file
        self.env_file = self._manager.env_file

        # 保留回调字典引用（委派至 manager 内部）
        self._callbacks: Dict[str, list] = self._manager._callbacks

        self._initialized = True
        logger.info("UnifiedConfig (legacy): 已委派至 UnifiedConfigManager")

    # ──────────────── 内部实现（委派）────────────────

    @property
    def _config(self) -> Dict[str, Any]:
        """只读视图：返回管理器内部配置字典（兼容旧代码直接访问）"""
        return self._manager._config

    @staticmethod
    def _is_placeholder(value: Any) -> bool:
        """检查值是否为占位符（如 'sk-YOUR_OPENAI_KEY_HERE'）"""
        if not isinstance(value, str):
            return False
        return "YOUR" in value.upper() and "KEY" in value.upper()

    def _load_config(self):
        """加载配置（委派至 UnifiedConfigManager）"""
        self._manager._load_config_json()

    def _load_env(self):
        """加载 .env（委派至 UnifiedConfigManager）"""
        self._manager._load_env()

    def _flatten_dict(self, d: Dict, parent_key: str = "", sep: str = "_") -> Dict:
        """展平字典（委派至 UnifiedConfigManager）"""
        from core.unified.config_manager import UnifiedConfigManager
        return UnifiedConfigManager._flatten_dict(d, parent_key, sep)

    def get(
        self,
        key: str,
        default: Any = None,
        category: str = None,
    ) -> Any:
        """获取配置（委派至 UnifiedConfigManager）"""
        return self._manager.get(key, default, category)

    def set(
        self,
        key: str,
        value: Any,
        category: str = "general",
        save: bool = True,
    ):
        """设置配置（委派至 UnifiedConfigManager）"""
        self._manager.set(key, value, category, save)
        logger.debug(
            "设置配置: %s = %s",
            key,
            "***" if "key" in key.lower() or "token" in key.lower() else value,
        )

    def _trigger_callbacks(self, key: str, old_value: Any, new_value: Any):
        """触发配置变更回调（委派至 UnifiedConfigManager）"""
        self._manager._trigger_callbacks(key, old_value, new_value)

    def on_change(self, key: str, callback):
        """注册配置变更回调（委派至 UnifiedConfigManager）"""
        self._manager.on_change(key, callback)

    def save(self):
        """保存配置到文件（委派至 UnifiedConfigManager）"""
        self._manager.save()

    def get_all(self, category: str = None) -> Dict[str, Any]:
        """获取所有配置（委派至 UnifiedConfigManager）"""
        return self._manager.get_all(category)

    def get_llm_config(self, model: str = None) -> Dict[str, Any]:
        """获取 LLM 配置（委派至 UnifiedConfigManager）"""
        return self._manager.get_llm_config(model)

    def get_mcp_servers(self) -> Dict[str, Dict]:
        """获取 MCP 服务器配置（委派至 UnifiedConfigManager）"""
        return self._manager.get_mcp_servers()

    def get_skills(self) -> Dict[str, Dict]:
        """获取技能配置（委派至 UnifiedConfigManager）"""
        return self._manager.get_skills()

    def reload(self):
        """重新加载配置（委派至 UnifiedConfigManager）"""
        self._manager.reload()
        logger.info("UnifiedConfig: 配置已重新加载")


# 全局实例
config = UnifiedConfig()
