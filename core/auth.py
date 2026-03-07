"""
Galaxy - 统一鉴权模块
========================

提供 API Token 和 Device ID 鉴权机制。

Production safety:
  - GALAXY_API_TOKEN must be set in production.
  - GALAXY_DEV_MODE=1 explicitly enables permissive dev-mode behaviour
    (no token required). A prominent warning is logged at startup.
  - If neither GALAXY_API_TOKEN nor GALAXY_DEV_MODE=1 is set, protected
    endpoints raise HTTP 401 to prevent accidental open access.

Author: Copilot
Date: 2026-02-12
"""

import hmac
import os
import logging
from typing import Optional
from fastapi import Header, HTTPException, status

logger = logging.getLogger("Galaxy.Auth")

# Module-level flag: dev-mode warning has been issued at most once per process
_dev_mode_warning_issued: bool = False

# ---------------------------------------------------------------------------
# Dev-mode detection & startup warning
# ---------------------------------------------------------------------------

def _is_dev_mode() -> bool:
    """Return True when GALAXY_DEV_MODE=1 is explicitly set."""
    return os.getenv("GALAXY_DEV_MODE", "").strip() == "1"


def _warn_dev_mode_once():
    """Emit a one-time warning when the server runs in dev mode."""
    global _dev_mode_warning_issued
    if not _dev_mode_warning_issued:
        _dev_mode_warning_issued = True
        logger.warning(
            "⚠️  Galaxy is running in DEV MODE (GALAXY_DEV_MODE=1). "
            "Authentication is DISABLED. Do NOT use this mode in production."
        )


def verify_api_token(token: str) -> bool:
    """
    验证 API Token

    Args:
        token: API Token 字符串

    Returns:
        bool: Token 是否有效
    """
    expected_token = os.getenv("GALAXY_API_TOKEN")

    if not expected_token:
        if _is_dev_mode():
            _warn_dev_mode_once()
            logger.debug("GALAXY_API_TOKEN 未设置，跳过 Token 鉴权（开发模式）")
            return True
        # Production: no token set and not dev mode → refuse
        logger.warning("GALAXY_API_TOKEN 未配置且未启用 GALAXY_DEV_MODE — Token 验证失败")
        return False

    is_valid = hmac.compare_digest(token, expected_token)
    if not is_valid:
        logger.warning("无效的 API Token")
    return is_valid


def verify_device_id(device_id: str) -> bool:
    """
    验证 Device ID

    Args:
        device_id: 设备 ID

    Returns:
        bool: Device ID 是否有效
    """
    if not device_id or len(device_id) < 3:
        logger.warning(f"无效的 Device ID: {device_id}")
        return False
    return True


async def require_auth(
    authorization: Optional[str] = Header(None),
    x_device_id: Optional[str] = Header(None, alias="X-Device-ID")
) -> dict:
    """
    FastAPI 依赖函数，用于端点鉴权

    Args:
        authorization: Authorization header (Bearer token)
        x_device_id: X-Device-ID header

    Returns:
        dict: 包含认证信息的字典

    Raises:
        HTTPException: 鉴权失败时抛出 401 异常
    """
    expected_token = os.getenv("GALAXY_API_TOKEN")

    # Dev mode: token not set AND GALAXY_DEV_MODE=1 → allow through with warning
    if not expected_token and _is_dev_mode():
        _warn_dev_mode_once()
        logger.debug("GALAXY_API_TOKEN 未设置，跳过鉴权（开发模式）")
        return {
            "authenticated": True,
            "device_id": x_device_id,
            "dev_mode": True
        }

    # Production guard: token not set and NOT in dev mode → refuse
    if not expected_token:
        logger.error(
            "Protected endpoint accessed but GALAXY_API_TOKEN is not configured "
            "and GALAXY_DEV_MODE is not enabled. Set GALAXY_API_TOKEN or GALAXY_DEV_MODE=1."
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Server is not configured for authentication. "
                "Set GALAXY_API_TOKEN environment variable, "
                "or set GALAXY_DEV_MODE=1 for local development."
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Normal auth flow: validate Bearer token
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format. Expected: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = parts[1]

    if not verify_api_token(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if x_device_id and not verify_device_id(x_device_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Device ID"
        )

    logger.info(f"认证成功: device_id={x_device_id}")

    return {
        "authenticated": True,
        "device_id": x_device_id,
        "dev_mode": False
    }
