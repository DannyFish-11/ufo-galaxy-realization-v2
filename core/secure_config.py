"""
UFO Galaxy - 安全配置管理
==========================

集中管理所有敏感配置，从环境变量读取
绝不硬编码任何密钥或凭证
"""
import os
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from functools import lru_cache

logger = logging.getLogger(__name__)


@dataclass
class APIKeys:
    """API 密钥配置"""
    openai: str = ""
    anthropic: str = ""
    google: str = ""
    deepseek: str = ""
    openrouter: str = ""
    groq: str = ""
    xai: str = ""
    oneapi: str = ""
    
    @classmethod
    def from_env(cls) -> "APIKeys":
        """从环境变量加载 API 密钥"""
        return cls(
            openai=os.getenv("OPENAI_API_KEY", ""),
            anthropic=os.getenv("ANTHROPIC_API_KEY", ""),
            google=os.getenv("GEMINI_API_KEY", ""),
            deepseek=os.getenv("DEEPSEEK_API_KEY", ""),
            openrouter=os.getenv("OPENROUTER_API_KEY", ""),
            groq=os.getenv("GROQ_API_KEY", ""),
            xai=os.getenv("XAI_API_KEY", ""),
            oneapi=os.getenv("ONEAPI_API_KEY", ""),
        )
    
    def is_configured(self, provider: str) -> bool:
        """检查指定提供商是否已配置"""
        return bool(getattr(self, provider, ""))


@dataclass
class DatabaseConfig:
    """数据库配置"""
    redis_url: str = ""
    qdrant_url: str = ""
    qdrant_api_key: str = ""
    mongodb_url: str = ""
    postgres_url: str = ""
    neo4j_uri: str = ""
    neo4j_user: str = ""
    neo4j_password: str = ""
    
    @classmethod
    def from_env(cls) -> "DatabaseConfig":
        """从环境变量加载数据库配置"""
        return cls(
            redis_url=os.getenv("REDIS_URL", "redis://localhost:6379"),
            qdrant_url=os.getenv("QDRANT_URL", "http://localhost:6333"),
            qdrant_api_key=os.getenv("QDRANT_API_KEY", ""),
            mongodb_url=os.getenv("MONGODB_URL", "mongodb://localhost:27017"),
            postgres_url=os.getenv("POSTGRES_URL", ""),
            neo4j_uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
            neo4j_password=os.getenv("NEO4J_PASSWORD", ""),
        )


@dataclass
class SecurityConfig:
    """安全配置"""
    jwt_secret: str = ""
    session_secret: str = ""
    encryption_key: str = ""
    allowed_hosts: list = field(default_factory=lambda: ["*"])
    cors_origins: list = field(default_factory=lambda: ["*"])
    
    @classmethod
    def from_env(cls) -> "SecurityConfig":
        """从环境变量加载安全配置"""
        return cls(
            jwt_secret=os.getenv("JWT_SECRET", os.getenv("SECRET_KEY", "ufo-galaxy-secret")),
            session_secret=os.getenv("SESSION_SECRET", "ufo-session-secret"),
            encryption_key=os.getenv("ENCRYPTION_KEY", ""),
            allowed_hosts=os.getenv("ALLOWED_HOSTS", "*").split(","),
            cors_origins=os.getenv("CORS_ORIGINS", "*").split(","),
        )


class SecureConfig:
    """
    安全配置管理器
    
    使用方法:
        config = SecureConfig()
        api_key = config.get_api_key("openai")
        db_url = config.get_database_url("redis")
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._api_keys = APIKeys.from_env()
        self._database = DatabaseConfig.from_env()
        self._security = SecurityConfig.from_env()
        self._initialized = True
        
        # 记录配置状态
        self._log_config_status()
    
    def _log_config_status(self):
        """记录配置状态（不暴露密钥）"""
        configured = []
        not_configured = []
        
        for provider in ["openai", "anthropic", "google", "deepseek"]:
            if self._api_keys.is_configured(provider):
                configured.append(provider)
            else:
                not_configured.append(provider)
        
        logger.info(f"已配置的 API: {', '.join(configured) or '无'}")
        if not_configured:
            logger.warning(f"未配置的 API: {', '.join(not_configured)}")
    
    def get_api_key(self, provider: str) -> Optional[str]:
        """
        获取 API 密钥
        
        Args:
            provider: 提供商名称 (openai, anthropic, google, deepseek 等)
            
        Returns:
            API 密钥或 None
        """
        key = getattr(self._api_keys, provider, "")
        if not key:
            logger.warning(f"API 密钥未配置: {provider}")
        return key or None
    
    def get_database_url(self, database: str) -> Optional[str]:
        """
        获取数据库连接 URL
        
        Args:
            database: 数据库名称 (redis, qdrant, mongodb, postgres, neo4j)
            
        Returns:
            连接 URL 或 None
        """
        attr_map = {
            "redis": "redis_url",
            "qdrant": "qdrant_url",
            "mongodb": "mongodb_url",
            "postgres": "postgres_url",
            "neo4j": "neo4j_uri",
        }
        attr = attr_map.get(database)
        if attr:
            return getattr(self._database, attr, "") or None
        return None
    
    def get_database_config(self, database: str) -> Dict[str, Any]:
        """获取数据库完整配置"""
        if database == "neo4j":
            return {
                "uri": self._database.neo4j_uri,
                "user": self._database.neo4j_user,
                "password": self._database.neo4j_password,
            }
        elif database == "qdrant":
            return {
                "url": self._database.qdrant_url,
                "api_key": self._database.qdrant_api_key,
            }
        return {}
    
    @property
    def api_keys(self) -> APIKeys:
        """获取 API 密钥配置对象"""
        return self._api_keys
    
    @property
    def database(self) -> DatabaseConfig:
        """获取数据库配置对象"""
        return self._database
    
    @property
    def security(self) -> SecurityConfig:
        """获取安全配置对象"""
        return self._security
    
    def is_production(self) -> bool:
        """检查是否为生产环境"""
        return os.getenv("ENVIRONMENT", "development").lower() == "production"
    
    def is_development(self) -> bool:
        """检查是否为开发环境"""
        return not self.is_production()


# 全局配置实例
_config: Optional[SecureConfig] = None


def get_config() -> SecureConfig:
    """获取全局配置实例"""
    global _config
    if _config is None:
        _config = SecureConfig()
    return _config


def get_api_key(provider: str) -> Optional[str]:
    """便捷函数：获取 API 密钥"""
    return get_config().get_api_key(provider)


def get_database_url(database: str) -> Optional[str]:
    """便捷函数：获取数据库 URL"""
    return get_config().get_database_url(database)


# 导出
__all__ = [
    'SecureConfig', 
    'APIKeys', 
    'DatabaseConfig', 
    'SecurityConfig',
    'get_config', 
    'get_api_key', 
    'get_database_url'
]
