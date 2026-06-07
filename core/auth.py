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
  - Defaults to true (secure-by-default); set to false to disable.
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
from typing import List, Optional, Set
from fastapi import Header, HTTPException, status

logger = logging.getLogger("Galaxy.Auth")

# Module-level flags: warnings issued at most once per process
_dev_mode_warning_issued: bool = False
_no_token_warning_issued: bool = False

# ---------------------------------------------------------------------------
# Gateway auth-enabled flag
# ---------------------------------------------------------------------------

def is_auth_enabled() -> bool:
    """Return True when GALAXY_AUTH_ENABLED is not explicitly disabled.

    Defaults to True for secure-by-default behaviour.
    Production mode forces authentication enabled regardless of settings.
    Unknown values default to enabled (secure-by-default).
    """
    # Production environment: force auth enabled, ignore all other settings
    if os.environ.get("GALAXY_MODE", "").lower() == "production":
        return True

    dev_mode = os.environ.get("GALAXY_DEV_MODE", "").lower()
    if dev_mode in ("1", "true", "yes"):
        # DEV_MODE no longer bypasses authentication; only enables extra debug logging
        logger.warning(
            "GALAXY_DEV_MODE is deprecated for auth bypass. "
            "Use proper test tokens instead."
        )

    env = os.environ.get("GALAXY_AUTH_ENABLED", "true").strip().lower()
    if env in ("0", "false", "no", ""):
        return False
    if env in ("1", "true", "yes"):
        return True
    # Secure default: unknown values default to enabled
    logger.warning("Unknown GALAXY_AUTH_ENABLED value '%s', defaulting to enabled", env)
    return True


def validate_auth_config() -> None:
    """Startup validation: ensure auth configuration is consistent.

    Raises:
        RuntimeError: if auth is enabled but no API token is configured,
                     or if production mode requirements are not met.
    """
    mode = os.environ.get("GALAXY_MODE", "").lower()

    # Production mode: enforce strict auth requirements
    if mode == "production":
        token = os.environ.get("GALAXY_API_TOKEN", "")
        if not token or len(token) < 32:
            raise RuntimeError(
                "Production mode requires GALAXY_API_TOKEN with minimum 32 characters. "
                'Generate with: python3 -c "import secrets; print(secrets.token_urlsafe(32))"'
            )
        # Production mode: DEV_MODE not allowed
        if os.environ.get("GALAXY_DEV_MODE", "").lower() in ("1", "true", "yes"):
            raise RuntimeError(
                "GALAXY_DEV_MODE is not allowed in production mode"
            )
        # Production mode: auth cannot be disabled
        auth = os.environ.get("GALAXY_AUTH_ENABLED", "true").lower()
        if auth in ("0", "false", "no", ""):
            raise RuntimeError(
                "Cannot disable authentication in production mode"
            )

    if is_auth_enabled() and not os.getenv("GALAXY_API_TOKEN"):
        raise RuntimeError(
            "GALAXY_AUTH_ENABLED=true (default) but GALAXY_API_TOKEN is not set. "
            "Set a secure token or explicitly disable auth with GALAXY_AUTH_ENABLED=false"
        )


# Startup validation — called explicitly during launcher startup sequence.
# Do NOT run at import time to avoid blocking module loading before .env is read.
_auth_config_validated = False

def ensure_auth_config_validated() -> None:
    """Run auth validation once at startup. Idempotent."""
    global _auth_config_validated
    if not _auth_config_validated:
        validate_auth_config()
        _auth_config_validated = True


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
    """Return True when GALAXY_DEV_MODE=1 is explicitly set.

    Note: DEV_MODE no longer bypasses authentication. It only enables
    extra debug logging and development conveniences.
    """
    return os.getenv("GALAXY_DEV_MODE", "").strip() == "1"


def _warn_dev_mode_once():
    """Emit a one-time warning when the server runs in dev mode.

    DEV_MODE no longer disables authentication; it only enables extra debug logging.
    """
    global _dev_mode_warning_issued
    if not _dev_mode_warning_issued:
        _dev_mode_warning_issued = True
        logger.warning(
            "Galaxy is running in DEV MODE (GALAXY_DEV_MODE=1). "
            "Authentication is still REQUIRED. DEV_MODE only enables extra debug logging."
        )


def _warn_no_token_once():
    """Emit a one-time warning when no API token is configured."""
    global _no_token_warning_issued
    if not _no_token_warning_issued:
        _no_token_warning_issued = True
        logger.warning(
            "GALAXY_API_TOKEN is not set. "
            "Authentication is enabled by default. Set GALAXY_API_TOKEN for production."
        )


def verify_api_token(token: str) -> bool:
    """
    验证 API Token，支持多 Token 轮换（key rotation）。

    Checks the supplied token against every entry returned by
    ``get_active_tokens()``.  This makes both the legacy single-token
    (``GALAXY_API_TOKEN``) and the multi-token rotation list
    (``GALAXY_API_TOKENS``) work transparently.

    Round-4 HIGH: defends against Unicode DoS — non-ASCII tokens are
    rejected before ``hmac.compare_digest`` to avoid encoding exceptions.

    Args:
        token: API Token 字符串

    Returns:
        bool: Token 是否有效
    """
    # Defence: reject non-ASCII tokens to prevent Unicode DoS
    try:
        token_bytes = token.encode("ascii")
    except UnicodeEncodeError:
        logger.warning("Token contains non-ASCII characters, rejecting")
        return False

    active = get_active_tokens()

    if not active:
        # No tokens configured → refuse (dev mode bypass removed for security)
        logger.warning("No active API tokens configured — token validation failed")
        return False

    for expected in active:
        # Defence: constant-time comparison on ASCII-encoded bytes
        try:
            expected_bytes = expected.encode("ascii")
        except UnicodeEncodeError:
            # Skip invalid expected tokens rather than crash
            continue

        # Length check with constant-time fallback to mitigate timing attacks
        if len(token_bytes) != len(expected_bytes):
            hmac.compare_digest(b"0" * len(expected_bytes), expected_bytes)
            continue

        if hmac.compare_digest(token_bytes, expected_bytes):
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
    # Gateway-level auth flag — secure by default (enabled unless explicitly disabled)
    if not is_auth_enabled():
        return {"authenticated": True, "device_id": x_device_id, "auth_enabled": False}

    active_tokens = get_active_tokens()

    # Security: dev mode bypass removed — all requests require valid tokens
    if not active_tokens:
        logger.error(
            "Protected endpoint accessed but no active API tokens are configured. "
            "Set GALAXY_API_TOKEN or GALAXY_API_TOKENS."
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Server is not configured for authentication. "
                "Set GALAXY_API_TOKEN environment variable."
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
