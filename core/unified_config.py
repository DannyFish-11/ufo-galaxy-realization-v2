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
    统一配置管理器
    
    单例模式，确保全局配置一致
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
        
        # 配置存储
        self._config: Dict[str, Any] = {}
        
        # 配置文件路径
        self.project_root = Path(__file__).parent.parent
        self.config_file = self.project_root / "config.json"
        self.env_file = self.project_root / ".env"
        
        # 加载配置
        self._load_config()
        self._load_env()
        
        # 回调列表
        self._callbacks: Dict[str, list] = {}
        
        self._initialized = True
        logger.info("统一配置管理器初始化完成")
    
    @staticmethod
    def _is_placeholder(value: Any) -> bool:
        """检查值是否为占位符（如 'sk-YOUR_OPENAI_KEY_HERE'）"""
        if not isinstance(value, str):
            return False
        return "YOUR" in value.upper() and "KEY" in value.upper()

    def _load_config(self):
        """加载 config.json，跳过占位符 API Key"""
        if self.config_file.exists():
            try:
                with open(self.config_file, encoding="utf-8") as f:
                    data = json.load(f)
                    flat = self._flatten_dict(data)
                    # 过滤掉占位符值（如 sk-YOUR_OPENAI_KEY_HERE）
                    for k, v in flat.items():
                        if self._is_placeholder(v):
                            logger.debug(f"跳过占位符配置: {k}")
                            continue
                        self._config[k] = v
                logger.info(f"加载配置文件: {self.config_file}")
            except Exception as e:
                logger.error(f"加载配置文件失败: {e}")
    
    def _load_env(self):
        """加载 .env 文件"""
        if self.env_file.exists():
            try:
                with open(self.env_file, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, value = line.split("=", 1)
                            key = key.strip()
                            value = value.strip()
                            
                            # 移除引号
                            if value.startswith('"') and value.endswith('"'):
                                value = value[1:-1]
                            elif value.startswith("'") and value.endswith("'"):
                                value = value[1:-1]
                            
                            # 存储到配置
                            self._config[key.lower()] = value
                
                logger.info(f"加载环境变量文件: {self.env_file}")
            except Exception as e:
                logger.error(f"加载环境变量文件失败: {e}")
        
        # 同时加载系统环境变量
        for key, value in os.environ.items():
            if key.upper().startswith(("OPENAI", "ANTHROPIC", "GEMINI", "DEEPSEEK", "LLM", "API", "MCP")):
                self._config[key.lower()] = value
    
    def _flatten_dict(self, d: Dict, parent_key: str = "", sep: str = "_") -> Dict:
        """展平字典"""
        items = []
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(self._flatten_dict(v, new_key, sep).items())
            else:
                items.append((new_key, v))
        return dict(items)
    
    def get(
        self,
        key: str,
        default: Any = None,
        category: str = None,
    ) -> Any:
        """
        获取配置
        
        Args:
            key: 配置键
            default: 默认值
            category: 分类（可选）
        
        Returns:
            配置值
        """
        # 尝试多种键格式
        keys_to_try = [
            key,
            key.lower(),
            key.upper(),
            key.replace(".", "_"),
            key.replace("_", "."),
        ]
        
        for k in keys_to_try:
            if k in self._config:
                return self._config[k]
        
        return default
    
    def set(
        self,
        key: str,
        value: Any,
        category: str = "general",
        save: bool = True,
    ):
        """
        设置配置
        
        Args:
            key: 配置键
            value: 配置值
            category: 分类
            save: 是否立即保存
        """
        old_value = self._config.get(key)
        self._config[key] = value
        self._config[key.lower()] = value
        
        # 触发回调
        if old_value != value:
            self._trigger_callbacks(key, old_value, value)
        
        if save:
            self.save()
        
        logger.debug(f"设置配置: {key} = {'***' if 'key' in key.lower() or 'token' in key.lower() else value}")
    
    def _trigger_callbacks(self, key: str, old_value: Any, new_value: Any):
        """触发配置变更回调"""
        # 触发特定键的回调
        if key in self._callbacks:
            for callback in self._callbacks[key]:
                try:
                    callback(key, old_value, new_value)
                except Exception as e:
                    logger.error(f"配置回调失败: {e}")
        
        # 触发通配符回调
        if "*" in self._callbacks:
            for callback in self._callbacks["*"]:
                try:
                    callback(key, old_value, new_value)
                except Exception as e:
                    logger.error(f"配置回调失败: {e}")
    
    def on_change(self, key: str, callback):
        """
        注册配置变更回调
        
        Args:
            key: 配置键（使用 "*" 监听所有变更）
            callback: 回调函数 (key, old_value, new_value) -> None
        """
        if key not in self._callbacks:
            self._callbacks[key] = []
        self._callbacks[key].append(callback)
    
    def save(self):
        """保存配置到文件"""
        # 保存到 config.json
        try:
            # 构建结构化配置
            config_data = {
                "web_ui_port": self.get("web_ui_port", 8099),
                "log_level": self.get("log_level", "INFO"),
                "default_llm_model": self.get("default_llm_model", "gpt-4o"),
                "llm_models": {},
                "mcp_servers": {},
                "skills": {},
                "nodes": {},
            }
            
            # 提取 LLM 配置
            for key, value in self._config.items():
                if "llm" in key.lower() or "model" in key.lower():
                    if isinstance(value, dict):
                        config_data["llm_models"].update(value)
            
            # 提取 MCP 配置
            mcp_servers = self.get("mcp_servers", {})
            if mcp_servers:
                config_data["mcp_servers"] = mcp_servers
            
            # 提取技能配置
            skills = self.get("skills", {})
            if skills:
                config_data["skills"] = skills
            
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"配置已保存: {self.config_file}")
        except Exception as e:
            logger.error(f"保存配置失败: {e}")
        
        # 保存敏感配置到 .env
        try:
            env_lines = []
            sensitive_keys = ["api_key", "token", "secret", "password"]
            
            for key, value in self._config.items():
                if any(s in key.lower() for s in sensitive_keys):
                    if value and value != "your_" + key + "_here":
                        env_lines.append(f"{key.upper()}={value}")
            
            if env_lines:
                with open(self.env_file, "w", encoding="utf-8") as f:
                    f.write("# Galaxy 配置文件\n")
                    f.write("# 自动生成，请勿手动编辑\n\n")
                    f.write("\n".join(env_lines))
                
                logger.info(f"环境变量已保存: {self.env_file}")
        except Exception as e:
            logger.error(f"保存环境变量失败: {e}")
    
    def get_all(self, category: str = None) -> Dict[str, Any]:
        """获取所有配置"""
        if category:
            return {k: v for k, v in self._config.items() if k.startswith(category)}
        return self._config.copy()
    
    def get_llm_config(self, model: str = None) -> Dict[str, Any]:
        """获取 LLM 配置"""
        model = model or self.get("default_llm_model", "gpt-4o")
        
        # 尝试从配置中获取
        model_config = self.get(f"llm_models_{model}", {})
        
        if not model_config:
            # 尝试从环境变量获取
            model_config = {
                "model": model,
                "api_key": self.get(f"{model.replace('-', '_')}_api_key") or self.get("openai_api_key"),
                "base_url": self.get(f"{model.replace('-', '_')}_base_url") or self.get("openai_api_base"),
            }
        
        return model_config
    
    def get_mcp_servers(self) -> Dict[str, Dict]:
        """获取 MCP 服务器配置"""
        return self.get("mcp_servers", {})
    
    def get_skills(self) -> Dict[str, Dict]:
        """获取技能配置"""
        return self.get("skills", {})
    
    def reload(self):
        """重新加载配置"""
        self._config.clear()
        self._load_config()
        self._load_env()
        logger.info("配置已重新加载")


# 全局实例
config = UnifiedConfig()
