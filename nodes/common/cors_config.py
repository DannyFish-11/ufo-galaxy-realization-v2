"""
Galaxy - CORS 配置
======================

从环境变量读取 CORS 允许的源、方法和请求头，
替代危险的 allow_methods=["*"] 和 allow_headers=["*"] 通配配置。

环境变量:
  CORS_ALLOWED_ORIGINS: 逗号分隔的允许源列表
  CORS_ALLOWED_METHODS: 逗号分隔的允许方法列表
  CORS_ALLOWED_HEADERS: 逗号分隔的允许请求头列表
"""

import os
from typing import List

# --- 默认配置 ---

# 安全兜底：硬编码默认端口，避免模块级调用导致 ImportError
_FALLBACK_ORIGINS = "http://localhost:8765,http://localhost:8766"

# 安全默认：仅允许常见 REST 方法，不包含 PATCH/OPTIONS
_DEFAULT_METHODS = "GET,POST,PUT,DELETE"

# 安全默认：仅允许必要的请求头
_DEFAULT_HEADERS = "Authorization,Content-Type,X-Request-ID"


def _default_origins() -> str:
    """延迟初始化：从 port_config 动态获取服务端口，避免模块级 ImportError."""
    try:
        from core.port_config import get_service_port
        return (
            f"http://localhost:{get_service_port('dashboard')},"
            f"http://localhost:{get_service_port('api_gateway')}"
        )
    except Exception:
        # 降级：port_config 未就绪时使用硬编码兜底
        return _FALLBACK_ORIGINS


def get_cors_origins() -> List[str]:
    """获取 CORS 允许的源列表。

    优先从环境变量读取；若未设置则延迟加载 port_config 获取动态端口；
    若 port_config 也未就绪则使用硬编码兜底值。
    """
    raw = os.environ.get("CORS_ALLOWED_ORIGINS")
    if raw is None:
        # 延迟初始化：仅在首次调用时访问 port_config
        raw = _default_origins()
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    return origins or ["http://localhost:8765"]


def get_cors_methods() -> List[str]:
    """
    获取 CORS 允许的 HTTP 方法列表。
    安全修复：返回显式方法列表，替代 allow_methods=["*"] 通配配置。
    """
    raw = os.environ.get("CORS_ALLOWED_METHODS", _DEFAULT_METHODS)
    methods = [m.strip().upper() for m in raw.split(",") if m.strip()]
    return methods or _DEFAULT_METHODS.split(",")


def get_cors_headers() -> List[str]:
    """
    获取 CORS 允许的请求头列表。
    安全修复：返回显式请求头列表，替代 allow_headers=["*"] 通配配置。
    """
    raw = os.environ.get("CORS_ALLOWED_HEADERS", _DEFAULT_HEADERS)
    headers = [h.strip() for h in raw.split(",") if h.strip()]
    return headers or _DEFAULT_HEADERS.split(",")
