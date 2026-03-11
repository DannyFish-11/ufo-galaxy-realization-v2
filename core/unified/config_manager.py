"""
Galaxy - 统一 Config Manager
==============================

统一入口：`core.unified.config_manager.UnifiedConfigManager`

设计：
- `UnifiedConfigManager` 是配置管理的权威来源
- 读取 `.env` / `config.json` / `config/unified_ports.yaml`
- `core/unified_config.py` 中的 `UnifiedConfig` 委派至此处
- `launcher/config_manager.py` 的全局配置委派至此处
- `unified_launcher.py` 使用此类替代 `SystemConfig.load_from_env()`

使用方法：
    from core.unified.config_manager import UnifiedConfigManager, get_unified_config

    cfg = get_unified_config()
    api_key = cfg.get("openai_api_key")
    ports = cfg.get_ports()
"""

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("Galaxy.Unified.Config")


def _is_placeholder(value: Any) -> bool:
    """检查值是否为占位符（如 'sk-YOUR_OPENAI_KEY_HERE'）"""
    if not isinstance(value, str):
        return False
    placeholders = [
        "your-", "YOUR_", "sk-YOUR", "YOUR-", "<YOUR", "PLACEHOLDER",
        "CHANGE_ME", "REPLACE_ME", "example.com/replace",
    ]
    return any(value.startswith(p) for p in placeholders)


class UnifiedConfigManager:
    """
    统一配置管理器（权威来源）

    加载顺序（后者覆盖前者）：
      1. `config/unified_ports.yaml` — 端口分配
      2. `config.json` — 主配置（跳过占位符 API Key）
      3. `.env` — 环境变量覆盖

    单例模式，线程安全。
    """

    _instance: Optional["UnifiedConfigManager"] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> "UnifiedConfigManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._initialized = False
                    cls._instance = instance
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return

        self._config: Dict[str, Any] = {}
        self._ports: Dict[str, Any] = {}
        self._callbacks: Dict[str, List[Callable]] = {}

        self.project_root = Path(__file__).parent.parent.parent
        self.config_file = self.project_root / "config.json"
        self.env_file = self.project_root / ".env"
        self.ports_file = self.project_root / "config" / "unified_ports.yaml"

        self._load_ports()
        self._load_config_json()
        self._load_env()

        self._initialized = True
        logger.info(
            "UnifiedConfigManager 初始化完成 | config=%s | env=%s | ports=%s",
            self.config_file.exists(),
            self.env_file.exists(),
            self.ports_file.exists(),
        )

    # ──────────────────── 加载逻辑 ────────────────────

    def _load_ports(self) -> None:
        """加载 config/unified_ports.yaml（端口分配）"""
        if not self.ports_file.exists():
            return
        try:
            import yaml  # type: ignore

            with open(self.ports_file, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            self._ports = data
            logger.debug("已加载端口配置: %s", self.ports_file)
        except ImportError:
            logger.warning("PyYAML 未安装，跳过 unified_ports.yaml 加载")
        except Exception as exc:
            logger.error("加载 unified_ports.yaml 失败: %s", exc)

    def _load_config_json(self) -> None:
        """加载 config.json，跳过占位符 API Key"""
        if not self.config_file.exists():
            return
        try:
            with open(self.config_file, encoding="utf-8") as f:
                data = json.load(f)
            flat = self._flatten_dict(data)
            for k, v in flat.items():
                if _is_placeholder(v):
                    logger.debug("跳过占位符配置: %s", k)
                    continue
                self._config[k] = v
            logger.info("已加载配置文件: %s", self.config_file)
        except Exception as exc:
            logger.error("加载 config.json 失败: %s", exc)

    def _load_env(self) -> None:
        """加载 .env 文件到 os.environ（不覆盖已有值），并同步至内部配置"""
        if self.env_file.exists():
            try:
                with open(self.env_file, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip()
                        # 仅接受合法变量名（字母/数字/下划线），防止异常键注入
                        if k and k.replace("_", "").isalnum() and k not in os.environ:
                            os.environ[k] = v
                logger.info("已加载 .env: %s", self.env_file)
            except Exception as exc:
                logger.error("加载 .env 失败: %s", exc)
        else:
            logger.warning(".env 未找到，使用已有环境变量")

        # 将常用 env var 同步到内部配置（env 优先）
        env_key_map = {
            "OPENAI_API_KEY": "openai_api_key",
            "OPENAI_API_BASE": "openai_api_base",
            "ANTHROPIC_API_KEY": "anthropic_api_key",
            "GEMINI_API_KEY": "gemini_api_key",
            "DEEPSEEK_API_KEY": "deepseek_api_key",
            "GROQ_API_KEY": "groq_api_key",
            "OPENROUTER_API_KEY": "openrouter_api_key",
            "XAI_API_KEY": "xai_api_key",
            "ZHIPU_API_KEY": "zhipu_api_key",
            "DATABASE_URL": "database_url",
            "REDIS_URL": "redis_url",
            "QDRANT_URL": "qdrant_url",
            "LOG_LEVEL": "log_level",
        }
        for env_k, cfg_k in env_key_map.items():
            val = os.environ.get(env_k)
            if val:
                self._config[cfg_k] = val

    def reload_env(self) -> None:
        """公共接口：重新加载 .env 并同步至内部配置"""
        self._load_env()

    # ──────────────────── 工具方法 ────────────────────

    @staticmethod
    def _flatten_dict(d: Dict, parent_key: str = "", sep: str = "_") -> Dict:
        """展平嵌套字典"""
        items: Dict = {}
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.update(UnifiedConfigManager._flatten_dict(v, new_key, sep))
            else:
                items[new_key] = v
        return items

    # ──────────────────── 公共 API ────────────────────

    def get(self, key: str, default: Any = None, category: Optional[str] = None) -> Any:
        """
        获取配置值

        Args:
            key: 配置键名（支持 category_key 格式）
            default: 默认值
            category: 若提供，自动拼接 f"{category}_{key}"
        """
        if category:
            key = f"{category}_{key}"
        val = self._config.get(key)
        if val is None:
            val = os.environ.get(key.upper(), default)
        return val if val is not None else default

    def set(
        self,
        key: str,
        value: Any,
        category: str = "general",
        save: bool = True,
    ) -> None:
        """设置配置值并触发回调"""
        old_value = self._config.get(key)
        self._config[key] = value
        self._trigger_callbacks(key, old_value, value)
        if save:
            self.save()

    def get_all(self, category: Optional[str] = None) -> Dict[str, Any]:
        """返回所有配置（可按前缀过滤）"""
        if category:
            return {k: v for k, v in self._config.items() if k.startswith(category)}
        return dict(self._config)

    def get_ports(self) -> Dict[str, Any]:
        """返回从 unified_ports.yaml 读取的完整端口配置"""
        return dict(self._ports)

    def get_port(self, node_key: str, default: Optional[int] = None) -> Optional[int]:
        """
        从 unified_ports.yaml 查找节点端口

        Args:
            node_key: 节点键名，如 "Node_00_StateMachine"
            default: 未找到时的默认值
        """
        for layer in self._ports.values():
            if isinstance(layer, dict) and "nodes" in layer:
                nodes = layer["nodes"]
                if node_key in nodes:
                    return nodes[node_key].get("port", default)
        return default

    def get_llm_config(self, model: Optional[str] = None) -> Dict[str, Any]:
        """获取 LLM 配置"""
        model = model or self.get("default_llm_model", "gpt-4o")
        model_config = self.get(f"llm_models_{model}", {})
        if not model_config:
            model_config = {
                "model": model,
                "api_key": self.get(f"{model.replace('-', '_')}_api_key")
                or self.get("openai_api_key"),
                "base_url": self.get(f"{model.replace('-', '_')}_base_url")
                or self.get("openai_api_base"),
            }
        return model_config

    def get_mcp_servers(self) -> Dict[str, Dict]:
        """获取 MCP 服务器配置"""
        return self.get("mcp_servers", {}) or {}

    def get_skills(self) -> Dict[str, Dict]:
        """获取技能配置"""
        return self.get("skills", {}) or {}

    def save(self) -> None:
        """将当前配置持久化到 config.json"""
        try:
            existing: Dict[str, Any] = {}
            if self.config_file.exists():
                with open(self.config_file, encoding="utf-8") as f:
                    existing = json.load(f)

            config_data: Dict[str, Any] = {
                **existing,
                "web_ui_port": self.get("web_ui_port", 8099),
                "log_level": self.get("log_level", "INFO"),
                "default_llm_model": self.get("default_llm_model", "gpt-4o"),
            }

            mcp_servers = self.get("mcp_servers")
            if mcp_servers:
                config_data["mcp_servers"] = mcp_servers

            skills = self.get("skills")
            if skills:
                config_data["skills"] = skills

            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(config_data, f, ensure_ascii=False, indent=2)
            logger.info("配置已保存: %s", self.config_file)
        except Exception as exc:
            logger.error("保存配置失败: %s", exc)

    def reload(self) -> None:
        """重新从磁盘加载所有配置"""
        self._config.clear()
        self._ports.clear()
        self._load_ports()
        self._load_config_json()
        self._load_env()
        logger.info("UnifiedConfigManager 配置已重载")

    # ──────────────────── 回调 ────────────────────

    def on_change(self, key: str, callback: Callable) -> None:
        """注册配置变更回调（key="*" 监听所有变更）"""
        self._callbacks.setdefault(key, []).append(callback)

    def _trigger_callbacks(self, key: str, old_value: Any, new_value: Any) -> None:
        for cb in self._callbacks.get(key, []):
            try:
                cb(key, old_value, new_value)
            except Exception as exc:
                logger.error("配置回调执行失败 [%s]: %s", key, exc)
        for cb in self._callbacks.get("*", []):
            try:
                cb(key, old_value, new_value)
            except Exception as exc:
                logger.error("通配配置回调执行失败: %s", exc)


# ───────────────────── 全局单例 ─────────────────────

def get_unified_config() -> UnifiedConfigManager:
    """
    获取全局 UnifiedConfigManager 单例

    Returns:
        UnifiedConfigManager: 全局单例实例
    """
    return UnifiedConfigManager()
