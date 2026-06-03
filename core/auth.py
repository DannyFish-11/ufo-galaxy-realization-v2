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

Gateway Bearer auth:
  - GALAXY_AUTH_ENABLED=true enables Bearer token enforcement on the
    gateway's REST and WebSocket endpoints.
  - Defaults to false (disabled) for backward compatibility.
  - When enabled, unauthorized requests are rejected with HTTP 401.

Key rotation:
  - GALAXY_API_TOKENS supports a comma-separated list of active tokens
    to allow zero-downtime rotation with an overlap window.
  - GALAXY_API_TOKEN (single) is still supported for backward compatibility;
    it is combined with GALAXY_API_TOKENS at validation time.
  - GALAXY_API_TOKEN_EXPIRY (ISO-8601 UTC) sets expiry for GALAXY_API_TOKEN.
  - GALAXY_REVOKED_TOKENS is a comma-separated list of tokens to reject even
    if they appear in the active token list, enabling instant revocation.
  - See docs/KEY_ROTATION.md for the recommended rotation procedure.

Author: Copilot
Date: 2026-02-12
"""

import hmac
import os
import logging
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import Header, HTTPException, status

logger = logging.getLogger("Galaxy.Auth")

# Module-level flags: warnings issued at most once per process
_dev_mode_warning_issued: bool = False
_no_token_warning_issued: bool = False

# ---------------------------------------------------------------------------
# Gateway auth-enabled flag
# ---------------------------------------------------------------------------

def is_auth_enabled() -> bool:
    """Return True when GALAXY_AUTH_ENABLED=true is explicitly set.

    Defaults to False so that existing deployments are not broken by the
    new security hardening.  Set ``GALAXY_AUTH_ENABLED=true`` in production
    to enforce Bearer token validation on all gateway endpoints.
    """
    return os.getenv("GALAXY_AUTH_ENABLED", "false").strip().lower() in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# Key rotation helpers
# ---------------------------------------------------------------------------

def _parse_token_list(env_value: str) -> List[str]:
    """Split a comma-separated token list, dropping empty entries."""
    return [t.strip() for t in env_value.split(",") if t.strip()]


def _is_token_expired(expiry_str: str) -> bool:
    """Return True when the ISO-8601 UTC expiry time has passed.

    Args:
        expiry_str: ISO-8601 timestamp string, e.g. ``2026-06-01T00:00:00Z``.

    Returns:
        True  — expiry time is in the past (token has expired).
        False — expiry is still in the future, or the string cannot be parsed.
    """
    try:
        expiry_dt = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
        return datetime.now(tz=timezone.utc) >= expiry_dt
    except (ValueError, AttributeError):
        logger.warning("Could not parse GALAXY_API_TOKEN_EXPIRY=%r; treating as not expired", expiry_str)
        return False


def get_active_tokens() -> List[str]:
    """Return the list of currently valid (non-expired, non-revoked) tokens.

    Resolution order (all sources are combined):
    1. ``GALAXY_API_TOKEN``  — the classic single-token variable.
       Excluded when ``GALAXY_API_TOKEN_EXPIRY`` is set and has passed.
    2. ``GALAXY_API_TOKENS`` — comma-separated list for rotation overlap.

    Tokens that appear in ``GALAXY_REVOKED_TOKENS`` are always excluded.

    Returns:
        List of accepted token strings (may be empty).
    """
    revoked_raw = os.getenv("GALAXY_REVOKED_TOKENS", "")
    revoked = set(_parse_token_list(revoked_raw))

    active: List[str] = []

    # Legacy single-token variable
    single = os.getenv("GALAXY_API_TOKEN", "").strip()
    if single:
        expiry_str = os.getenv("GALAXY_API_TOKEN_EXPIRY", "").strip()
        if expiry_str and _is_token_expired(expiry_str):
            logger.warning(
                "GALAXY_API_TOKEN has expired (GALAXY_API_TOKEN_EXPIRY=%s); "
                "it will not be accepted.",
                expiry_str,
            )
        else:
            active.append(single)

    # Multi-token rotation list (no per-entry expiry — manage via revocation)
    multi_raw = os.getenv("GALAXY_API_TOKENS", "").strip()
    if multi_raw:
        active.extend(_parse_token_list(multi_raw))

    # Deduplicate while preserving insertion order
    seen: Set[str] = set()
    deduplicated: List[str] = []
    for t in active:
        if t not in seen:
            seen.add(t)
            deduplicated.append(t)

    # Remove revoked tokens
    valid = [t for t in deduplicated if t not in revoked]

    return valid


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


def _warn_no_token_once():
    """Emit a one-time warning when no API token is configured."""
    global _no_token_warning_issued
    if not _no_token_warning_issued:
        _no_token_warning_issued = True
        logger.warning(
            "GALAXY_API_TOKEN is not set and GALAXY_DEV_MODE is not enabled. "  # M7 fixed
            "Authentication is disabled. Set GALAXY_API_TOKEN for production "  # M7 fixed
            "or GALAXY_DEV_MODE=1 to suppress this warning."  # M7 fixed
        )


def verify_api_token(token: str) -> bool:
    """
    验证 API Token，支持多 Token 轮换（key rotation）。

    Checks the supplied token against every entry returned by
    ``get_active_tokens()``.  This makes both the legacy single-token
    (``GALAXY_API_TOKEN``) and the multi-token rotation list
    (``GALAXY_API_TOKENS``) work transparently.

    Args:
        token: API Token 字符串

    Returns:
        bool: Token 是否有效
    """
    active = get_active_tokens()

    if not active:
        if _is_dev_mode():
            _warn_dev_mode_once()
            logger.debug("No active tokens configured; skipping token auth (dev mode)")
            return True
        # Production: no token set and not dev mode → refuse
        logger.warning("No active API tokens configured and GALAXY_DEV_MODE is not enabled — token validation failed")
        return False

    for expected in active:
        if hmac.compare_digest(token, expected):
            return True

    logger.warning("Invalid API token presented")
    return False


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

    Auth enforcement is gated by the ``GALAXY_AUTH_ENABLED`` flag.
    When auth is disabled (the default) this function returns immediately
    so that existing clients are not broken.

    Key rotation: validates against all active tokens returned by
    ``get_active_tokens()``, so multiple keys can coexist during a
    rotation overlap window.

    Args:
        authorization: Authorization header (Bearer token)
        x_device_id: X-Device-ID header

    Returns:
        dict: 包含认证信息的字典

    Raises:
        HTTPException: 鉴权失败时抛出 401 异常
    """
    # Gateway-level auth flag — default off for backward compatibility
    if not is_auth_enabled():
        return {"authenticated": True, "device_id": x_device_id, "auth_enabled": False}

    active_tokens = get_active_tokens()

    # Dev mode: no active tokens AND GALAXY_DEV_MODE=1 → allow through with warning
    if not active_tokens and _is_dev_mode():
        _warn_dev_mode_once()
        logger.debug("No active tokens configured; skipping auth (dev mode)")
        return {
            "authenticated": True,
            "device_id": x_device_id,
            "dev_mode": True
        }

    # Production guard: no active tokens and NOT in dev mode → refuse
    if not active_tokens:
        logger.error(
            "Protected endpoint accessed but no active API tokens are configured "
            "and GALAXY_DEV_MODE is not enabled. Set GALAXY_API_TOKEN or GALAXY_API_TOKENS, "
            "or set GALAXY_DEV_MODE=1 for local development."
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
            detail="Invalid or expired API token",
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
