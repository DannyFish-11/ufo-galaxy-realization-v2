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

logger = logging.getLogger("Galaxy.InternalAuth")

__all__ = ["internal_auth_headers", "internal_token"]


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
