"""
Galaxy - 统一 API Key 管理服务
支持 OneAPI 统一网关 + 各节点独立 API Key 管理
"""

import os
import json
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from enum import Enum

logger = logging.getLogger(__name__)

# ============================================================================
# API Key 分类
# ============================================================================

class APIKeyType(str, Enum):
    """API Key 类型"""
    # LLM 相关 (通过 OneAPI 统一管理)
    LLM_OPENAI = "llm_openai"
    LLM_ANTHROPIC = "llm_anthropic"
    LLM_GOOGLE = "llm_google"
    LLM_DEEPSEEK = "llm_deepseek"
    LLM_GROQ = "llm_groq"
    LLM_OPENROUTER = "llm_openrouter"
    
    # OneAPI 统一网关
    ONEAPI = "oneapi"
    
    # 本地 LLM
    LOCAL_LLM = "local_llm"
    
    # 工具类 API (独立配置)
    WEATHER = "weather"           # OpenWeather
    SEARCH = "search"             # Brave Search
    EMAIL = "email"               # 邮件服务
    TRANSLATION = "translation"   # DeepL
    NOTION = "notion"             # Notion
    GITHUB = "github"             # GitHub
    QDRANT = "qdrant"             # 向量数据库
    REDIS = "redis"               # Redis
    
    # 媒体生成
    PIXVERSE = "pixverse"         # 视频生成
    NOVITA = "novita"             # OCR

@dataclass
class APIKeyConfig:
    """API Key 配置"""
    key_type: APIKeyType
    name: str                     # 显示名称
    key: str = ""                 # API Key
    url: str = ""                 # API URL (可选)
    enabled: bool = True
    description: str = ""
    required: bool = False        # 是否必需
    category: str = "other"       # 分类: llm, tool, storage
    
    # 元数据
    created_at: str = ""
    updated_at: str = ""
    last_used: str = ""

# ============================================================================
# 默认 API Key 配置
# ============================================================================

DEFAULT_API_KEYS: List[APIKeyConfig] = [
    # === OneAPI 统一网关 (推荐) ===
    APIKeyConfig(
        key_type=APIKeyType.ONEAPI,
        name="OneAPI 统一网关",
        description="配置 OneAPI 后，所有 LLM 请求通过统一网关，无需单独配置各 LLM API Key",
        required=False,
        category="llm"
    ),
    
    # === LLM 提供商 (如果不用 OneAPI，可单独配置) ===
    APIKeyConfig(
        key_type=APIKeyType.LLM_OPENAI,
        name="OpenAI API",
        url="https://api.openai.com/v1",
        description="OpenAI GPT 系列模型",
        required=False,
        category="llm"
    ),
    APIKeyConfig(
        key_type=APIKeyType.LLM_DEEPSEEK,
        name="DeepSeek API",
        url="https://api.deepseek.com/v1",
        description="DeepSeek 模型，性价比高",
        required=False,
        category="llm"
    ),
    APIKeyConfig(
        key_type=APIKeyType.LLM_ANTHROPIC,
        name="Anthropic Claude API",
        url="https://api.anthropic.com",
        description="Claude 系列模型",
        required=False,
        category="llm"
    ),
    APIKeyConfig(
        key_type=APIKeyType.LLM_GOOGLE,
        name="Google Gemini API",
        url="https://generativelanguage.googleapis.com",
        description="Google Gemini 模型",
        required=False,
        category="llm"
    ),
    APIKeyConfig(
        key_type=APIKeyType.LLM_GROQ,
        name="Groq API",
        url="https://api.groq.com/openai/v1",
        description="Groq 快速推理",
        required=False,
        category="llm"
    ),
    APIKeyConfig(
        key_type=APIKeyType.LLM_OPENROUTER,
        name="OpenRouter API",
        url="https://openrouter.ai/api/v1",
        description="OpenRouter 多模型网关",
        required=False,
        category="llm"
    ),
    
    # === 本地 LLM ===
    APIKeyConfig(
        key_type=APIKeyType.LOCAL_LLM,
        name="本地 LLM",
        url="http://localhost:8079",
        description="本地部署的 LLM (如 Ollama)",
        required=False,
        category="llm"
    ),
    
    # === 工具类 API ===
    APIKeyConfig(
        key_type=APIKeyType.WEATHER,
        name="OpenWeather API",
        url="https://api.openweathermap.org",
        description="天气查询服务",
        required=False,
        category="tool"
    ),
    APIKeyConfig(
        key_type=APIKeyType.SEARCH,
        name="Brave Search API",
        url="https://api.search.brave.com",
        description="Brave 搜索服务",
        required=False,
        category="tool"
    ),
    APIKeyConfig(
        key_type=APIKeyType.TRANSLATION,
        name="DeepL API",
        url="https://api.deepl.com",
        description="DeepL 翻译服务",
        required=False,
        category="tool"
    ),
    APIKeyConfig(
        key_type=APIKeyType.NOTION,
        name="Notion API",
        url="https://api.notion.com",
        description="Notion 集成",
        required=False,
        category="tool"
    ),
    APIKeyConfig(
        key_type=APIKeyType.GITHUB,
        name="GitHub API",
        url="https://api.github.com",
        description="GitHub 集成",
        required=False,
        category="tool"
    ),
    
    # === 存储类 ===
    APIKeyConfig(
        key_type=APIKeyType.QDRANT,
        name="Qdrant API",
        description="向量数据库",
        required=False,
        category="storage"
    ),
    APIKeyConfig(
        key_type=APIKeyType.REDIS,
        name="Redis",
        url="redis://localhost:6379",
        description="Redis 缓存",
        required=False,
        category="storage"
    ),
    
    # === 媒体生成 ===
    APIKeyConfig(
        key_type=APIKeyType.PIXVERSE,
        name="PixVerse API",
        description="视频生成服务",
        required=False,
        category="media"
    ),
]

# ============================================================================
# API Key 管理器
# ============================================================================

class APIKeyManager:
    """API Key 管理器"""
    
    def __init__(self, storage_path: str = "data/api_keys"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        self.config_file = self.storage_path / "api_keys.json"
        self.keys: Dict[str, APIKeyConfig] = {}
        
        # 加载配置
        self._load_config()
        
        # 从环境变量同步
        self._sync_from_env()
        
        logger.info(f"API Key 管理器初始化完成，已加载 {len(self.keys)} 个配置")
    
    def _load_config(self):
        """加载配置文件"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for item in data:
                        config = APIKeyConfig(**item)
                        self.keys[config.key_type.value] = config
                logger.info(f"从文件加载了 {len(self.keys)} 个 API Key 配置")
            except Exception as e:
                logger.error(f"加载配置文件失败: {e}")
        
        # 加载默认配置
        for default in DEFAULT_API_KEYS:
            key_type = default.key_type.value
            if key_type not in self.keys:
                self.keys[key_type] = default
    
    def _save_config(self):
        """保存配置文件"""
        try:
            data = [asdict(config) for config in self.keys.values()]
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"保存了 {len(self.keys)} 个 API Key 配置")
        except Exception as e:
            logger.error(f"保存配置文件失败: {e}")
    
    def _sync_from_env(self):
        """从环境变量同步"""
        env_mapping = {
            "ONEAPI_URL": (APIKeyType.ONEAPI, "url"),
            "ONEAPI_API_KEY": (APIKeyType.ONEAPI, "key"),
            "OPENAI_API_KEY": (APIKeyType.LLM_OPENAI, "key"),
            "OPENAI_API_BASE": (APIKeyType.LLM_OPENAI, "url"),
            "DEEPSEEK_API_KEY": (APIKeyType.LLM_DEEPSEEK, "key"),
            "DEEPSEEK_API_BASE": (APIKeyType.LLM_DEEPSEEK, "url"),
            "ANTHROPIC_API_KEY": (APIKeyType.LLM_ANTHROPIC, "key"),
            "GEMINI_API_KEY": (APIKeyType.LLM_GOOGLE, "key"),
            "GROQ_API_KEY": (APIKeyType.LLM_GROQ, "key"),
            "OPENROUTER_API_KEY": (APIKeyType.LLM_OPENROUTER, "key"),
            "LOCAL_LLM_URL": (APIKeyType.LOCAL_LLM, "url"),
            "OPENWEATHER_API_KEY": (APIKeyType.WEATHER, "key"),
            "BRAVE_API_KEY": (APIKeyType.SEARCH, "key"),
            "DEEPL_API_KEY": (APIKeyType.TRANSLATION, "key"),
            "NOTION_API_KEY": (APIKeyType.NOTION, "key"),
            "GITHUB_TOKEN": (APIKeyType.GITHUB, "key"),
            "QDRANT_API_KEY": (APIKeyType.QDRANT, "key"),
            "REDIS_URL": (APIKeyType.REDIS, "url"),
            "PIXVERSE_API_KEY": (APIKeyType.PIXVERSE, "key"),
        }
        
        for env_key, (key_type, field) in env_mapping.items():
            value = os.getenv(env_key, "")
            if value and value != f"your-{env_key.lower()}-here":
                key_type_str = key_type.value
                if key_type_str in self.keys:
                    setattr(self.keys[key_type_str], field, value)
                    self.keys[key_type_str].updated_at = datetime.now().isoformat()
    
    def get_key(self, key_type: APIKeyType) -> Optional[str]:
        """获取 API Key"""
        key_type_str = key_type.value
        if key_type_str in self.keys:
            config = self.keys[key_type_str]
            if config.enabled and config.key:
                config.last_used = datetime.now().isoformat()
                return config.key
        return None
    
    def get_url(self, key_type: APIKeyType) -> Optional[str]:
        """获取 API URL"""
        key_type_str = key_type.value
        if key_type_str in self.keys:
            return self.keys[key_type_str].url
        return None
    
    def get_config(self, key_type: APIKeyType) -> Optional[APIKeyConfig]:
        """获取完整配置"""
        return self.keys.get(key_type.value)
    
    def set_key(self, key_type: APIKeyType, key: str, url: str = None):
        """设置 API Key"""
        key_type_str = key_type.value
        if key_type_str in self.keys:
            self.keys[key_type_str].key = key
            self.keys[key_type_str].updated_at = datetime.now().isoformat()
            if url:
                self.keys[key_type_str].url = url
            self._save_config()
            logger.info(f"设置 API Key: {key_type_str}")
    
    def enable(self, key_type: APIKeyType, enabled: bool = True):
        """启用/禁用 API Key"""
        key_type_str = key_type.value
        if key_type_str in self.keys:
            self.keys[key_type_str].enabled = enabled
            self._save_config()
    
    def list_keys(self, category: str = None) -> List[APIKeyConfig]:
        """列出所有 API Key 配置"""
        if category:
            return [k for k in self.keys.values() if k.category == category]
        return list(self.keys.values())
    
    def get_status(self) -> Dict[str, Any]:
        """获取状态"""
        configured = sum(1 for k in self.keys.values() if k.key)
        enabled = sum(1 for k in self.keys.values() if k.enabled and k.key)
        
        return {
            "total": len(self.keys),
            "configured": configured,
            "enabled": enabled,
            "categories": {
                "llm": sum(1 for k in self.keys.values() if k.category == "llm" and k.key),
                "tool": sum(1 for k in self.keys.values() if k.category == "tool" and k.key),
                "storage": sum(1 for k in self.keys.values() if k.category == "storage" and k.key),
                "media": sum(1 for k in self.keys.values() if k.category == "media" and k.key),
            }
        }
    
    def export_to_env(self) -> Dict[str, str]:
        """导出为环境变量格式"""
        env_mapping = {
            APIKeyType.ONEAPI: ("ONEAPI_URL", "ONEAPI_API_KEY"),
            APIKeyType.LLM_OPENAI: ("OPENAI_API_BASE", "OPENAI_API_KEY"),
            APIKeyType.LLM_DEEPSEEK: ("DEEPSEEK_API_BASE", "DEEPSEEK_API_KEY"),
            APIKeyType.LLM_ANTHROPIC: (None, "ANTHROPIC_API_KEY"),
            APIKeyType.LLM_GOOGLE: (None, "GEMINI_API_KEY"),
            APIKeyType.LLM_GROQ: (None, "GROQ_API_KEY"),
            APIKeyType.LLM_OPENROUTER: (None, "OPENROUTER_API_KEY"),
            APIKeyType.LOCAL_LLM: ("LOCAL_LLM_URL", None),
            APIKeyType.WEATHER: (None, "OPENWEATHER_API_KEY"),
            APIKeyType.SEARCH: (None, "BRAVE_API_KEY"),
            APIKeyType.TRANSLATION: (None, "DEEPL_API_KEY"),
            APIKeyType.NOTION: (None, "NOTION_API_KEY"),
            APIKeyType.GITHUB: (None, "GITHUB_TOKEN"),
            APIKeyType.QDRANT: (None, "QDRANT_API_KEY"),
            APIKeyType.REDIS: ("REDIS_URL", None),
            APIKeyType.PIXVERSE: (None, "PIXVERSE_API_KEY"),
        }
        
        result = {}
        for key_type, (url_env, key_env) in env_mapping.items():
            config = self.keys.get(key_type.value)
            if config:
                if url_env and config.url:
                    result[url_env] = config.url
                if key_env and config.key:
                    result[key_env] = config.key
        
        return result

# ============================================================================
# 全局实例
# ============================================================================

_api_key_manager: Optional[APIKeyManager] = None

def get_api_key_manager() -> APIKeyManager:
    """获取全局 API Key 管理器"""
    global _api_key_manager
    if _api_key_manager is None:
        _api_key_manager = APIKeyManager()
    return _api_key_manager

def get_api_key(key_type: APIKeyType) -> Optional[str]:
    """便捷函数：获取 API Key"""
    return get_api_key_manager().get_key(key_type)

def get_api_url(key_type: APIKeyType) -> Optional[str]:
    """便捷函数：获取 API URL"""
    return get_api_key_manager().get_url(key_type)
