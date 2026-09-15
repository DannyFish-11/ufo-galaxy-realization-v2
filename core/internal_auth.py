"""core/internal_auth.py — 内部 HTTP 调用带上身份

节点 HTTP 面接上鉴权之后,仓内那些**直接打节点端点**的调用方必须跟着带令牌,
否则它们会在自己的系统里被 401 —— 安全没加上多少,先把功能打断了。

令牌从哪来
----------
``core.auth`` 的零配置自签令牌:``$GALAXY_DATA_DIR/`` 下那一份。compose 里
``galaxy-data`` 是各节点与 core 容器共享的卷,所以同一部署内大家读到同一个令牌,
不需要任何配置。显式配了 ``GALAXY_API_TOKEN`` / ``GALAXY_API_TOKENS`` 时优先用它。

**拿不到令牌时返回空 header,而不是抛。** 调用方随后会收到 401 —— 那是准确的
现象("这次调用没有身份"),而在这里抛异常会把它伪装成"调用方自己坏了"。
"""

from __future__ import annotations

import logging
from typing import Dict
from urllib.parse import urlparse

logger = logging.getLogger("Galaxy.InternalAuth")

__all__ = ["internal_auth_headers", "internal_headers_for", "internal_token", "is_internal_url"]


def internal_token() -> str:
    """本进程该用哪个令牌调别的内部服务。显式配置优先,其次本机自签。"""
    try:
        from core.auth import get_active_tokens, read_local_token  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        logger.debug("鉴权模块不可用,内部调用不带令牌: %s", exc)
        return ""

    try:
        active = get_active_tokens()
        if active:
            return str(active[0])
    except Exception as exc:  # noqa: BLE001
        logger.debug("读取共享令牌失败: %s", exc)

    try:
        return read_local_token() or ""
    except Exception as exc:  # noqa: BLE001
        logger.debug("读取本机自签令牌失败: %s", exc)
        return ""


def internal_auth_headers() -> Dict[str, str]:
    """内部调用要带的 header。没有令牌时是空字典 —— 见模块 docstring。"""
    token = internal_token()
    return {"Authorization": f"Bearer {token}"} if token else {}


#: 认得出来的"自己人"主机。令牌**只**发给这些地址。
#:
#: 为什么必须有这道判断:仓里同一个 httpx 客户端既打节点、也打 OpenAI / GitHub。
#: 在客户端构造处无条件挂上 Authorization,等于把内部令牌送给第三方 —— 那不是
#: 加固,是凭据外泄。所以按**目标地址**决定带不带,而不是按客户端。
_INTERNAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0", "host.docker.internal"})

#: compose 里的服务名形如 ``node-36-uiawindows`` / ``galaxy-gateway`` / ``galaxy-core``。
_INTERNAL_HOST_PREFIXES = ("node-", "galaxy-")


def is_internal_url(url: str) -> bool:
    """这个地址算不算"自己人"。判不准时返回 ``False`` —— 宁可不带令牌(调用方会收到
    401,是个明确现象),也不要把令牌发给一个没认出来的主机。"""
    try:
        host = (urlparse(str(url or "")).hostname or "").lower()
    except Exception:  # noqa: BLE001
        return False
    if not host:
        return False
    if host in _INTERNAL_HOSTS:
        return True
    return any(host.startswith(pfx) for pfx in _INTERNAL_HOST_PREFIXES)


def internal_headers_for(url: str) -> Dict[str, str]:
    """按目标地址决定要不要带令牌。外部地址一律不带。"""
    return internal_auth_headers() if is_internal_url(url) else {}
