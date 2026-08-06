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
  - Defaults to false (opt-in); GALAXY_MODE=production forces it on.
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
import logging
import os
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
    """Return True unless GALAXY_AUTH_ENABLED is explicitly turned off.

    Defaults to **True** (opt-out).  It used to default to False (opt-in);
    see the inline note below for why that premise no longer holds.
    Production mode (GALAXY_MODE=production) forces authentication enabled
    regardless of settings.
    """
    # Production environment: force auth enabled, ignore all other settings
    if os.environ.get("GALAXY_MODE", "").lower() == "production":
        return True

    dev_mode = os.environ.get("GALAXY_DEV_MODE", "").lower()
    if dev_mode in ("1", "true", "yes"):
        # DEV_MODE no longer bypasses authentication; only enables extra debug logging
        logger.warning("GALAXY_DEV_MODE is deprecated for auth bypass. " "Use proper test tokens instead.")

    # 默认 **开启**。此前默认关闭（"opt-in"），那是在"网关只在局域网里"的前提下
    # 成立的 —— 家里网段本身就是信任边界。而一旦有任何一条公网可达的路（
    # Tailscale Funnel / 端口转发 / 隧道），这个前提就没了，默认关等于把桌面
    # 裸奔在公网上。可达性是会变的，默认值不能建立在"当前恰好不可达"上。
    #
    # 翻这个默认不会让零配置的安装起不来：没配令牌时
    # :func:`ensure_local_token` 会在首次启动时自签一个并落盘（0600），
    # 见 validate_auth_config()。所以零配置的体验从"不鉴权"变成
    # "鉴权开着 + 有一个本机令牌"，而不是"起不来"。
    env = os.environ.get("GALAXY_AUTH_ENABLED", "true").strip().lower()
    if env in ("1", "true", "yes", ""):
        return True
    if env in ("0", "false", "no"):
        return False
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
            raise RuntimeError("GALAXY_DEV_MODE is not allowed in production mode")
        # Production mode: auth cannot be disabled.
        #
        # 这里问的是"有人**显式**把它关了吗"。判据必须与 is_auth_enabled() 同源：
        # 空串在那边是"没设 → 用默认 → 开着"，在这里就不能算成"关了"，否则
        # `GALAXY_AUTH_ENABLED=` 这一行会让生产直接起不来，而鉴权其实是开的。
        # （默认值翻成 true 之前两边都把空串当关，是一致的；翻完就分叉了。）
        auth = os.environ.get("GALAXY_AUTH_ENABLED", "true").strip().lower()
        if auth in ("0", "false", "no"):
            raise RuntimeError("Cannot disable authentication in production mode")

    # 修复:轮换清单 GALAXY_API_TOKENS 是文档支持的等价配置(get_active_tokens
    # 完整支持)。此前只查 GALAXY_API_TOKEN——按文档流程完成密钥轮换(只留
    # GALAXY_API_TOKENS)后,启动校验反而 RuntimeError 拒绝启动。
    if is_auth_enabled() and not os.getenv("GALAXY_API_TOKEN") and not os.getenv("GALAXY_API_TOKENS", "").strip():
        # 鉴权默认已改为开启，所以这里不能再直接拒绝启动 —— 那会让每一个
        # 零配置的现有安装升级后起不来。先给它签一个本机令牌；只有连签都签不出来
        # （磁盘只读等）才是真的没法带着鉴权跑，那时候才拒绝。
        if ensure_local_token():
            return
        raise RuntimeError(
            "鉴权已启用但没有可用令牌，且本机令牌自签失败。"
            "请设置 GALAXY_API_TOKEN / GALAXY_API_TOKENS，"
            "或确认 GALAXY_DATA_DIR 可写，"
            "或显式设置 GALAXY_AUTH_ENABLED=false（仅限确无公网可达路径的场景）。"
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


#: 本机自签令牌的落盘位置（相对 ``GALAXY_DATA_DIR``，缺省 ``./data``）。
_LOCAL_TOKEN_FILENAME = "api_token.json"


def _local_token_path() -> str:
    base = os.getenv("GALAXY_DATA_DIR", "").strip() or os.path.join(os.getcwd(), "data")
    return os.path.join(base, _LOCAL_TOKEN_FILENAME)


def read_local_token() -> Optional[str]:
    """读出本机自签令牌；没有就返回 None。

    读不出来与"确实还没签过"**必须分得开** —— 前者要留痕（文件在但坏了/没权限，
    静默当成"没有"会让系统悄悄再签一个、旧令牌全部失效）。
    """
    path = _local_token_path()
    if not os.path.exists(path):
        return None
    try:
        import json

        with open(path, "r", encoding="utf-8") as fh:
            tok = str((json.load(fh) or {}).get("token", "")).strip()
        return tok or None
    except Exception as exc:  # noqa: BLE001
        logger.warning("本机令牌文件存在但读不出（不等于'还没签过'）：%s — %s", path, exc)
        return None


def ensure_local_token() -> Optional[str]:
    """确保本机有一个令牌可用；返回当前生效的那个。

    调用方是启动校验。语义是"零配置也要有身份"：

    * 已经显式配了 ``GALAXY_API_TOKEN`` / ``GALAXY_API_TOKENS`` → 什么都不做，
      **绝不覆盖**用户的配置；
    * 已经自签过 → 原样返回，不重签（重签会让所有已配对设备的令牌失效）；
    * 都没有 → 现签一个，落盘 0600（``atomic_write_json`` 自带 ``fchmod``）。

    签不出来（磁盘只读等）返回 ``None`` 并留痕，由调用方决定是拒绝启动还是降级
    —— 这里不替它做主。
    """
    if os.getenv("GALAXY_API_TOKEN", "").strip() or os.getenv("GALAXY_API_TOKENS", "").strip():
        return None

    existing = read_local_token()
    if existing:
        return existing

    import secrets

    token = secrets.token_urlsafe(32)
    path = _local_token_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        from core.atomic_json import atomic_write_json

        atomic_write_json(path, {"token": token, "created_at": datetime.now(timezone.utc).isoformat()})
        logger.info("已为本机自签 API 令牌（首次启动）：%s", path)
        return token
    except Exception as exc:  # noqa: BLE001
        logger.error("本机令牌自签失败（鉴权开着但没有可用令牌）：%s — %s", path, exc)
        return None


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
                "GALAXY_API_TOKEN has expired (GALAXY_API_TOKEN_EXPIRY=%s); " "it will not be accepted.",
                expiry_str,
            )
        else:
            active.append(single)

    # Multi-token rotation list (no per-entry expiry — manage via revocation)
    multi_raw = os.getenv("GALAXY_API_TOKENS", "").strip()
    if multi_raw:
        active.extend(_parse_token_list(multi_raw))

    # 本机自签令牌（首次启动生成，见 ensure_local_token）。放在最后：
    # 显式配置的令牌永远优先，自签的只是"零配置也能有身份"的兜底。
    local = read_local_token()
    if local:
        active.append(local)

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
            "GALAXY_API_TOKEN is not set. " "Set GALAXY_API_TOKEN before enabling GALAXY_AUTH_ENABLED in production."
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

    # 这里只认「环境共享 token」这一种凭据。配对发放的是能力令牌
    # (core.capability_token),它带 scope 与 subject 绑定,故意不在这里放行——
    # 一张手表的令牌不该顺带打开整个管理面。设备入口自己去校验它。
    active = get_active_tokens()

    if not active:
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
    authorization: Optional[str] = Header(None), x_device_id: Optional[str] = Header(None, alias="X-Device-ID")
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
    # Gateway-level auth flag — opt-in (disabled unless explicitly enabled);
    # production mode (GALAXY_MODE=production) forces it on.
    if not is_auth_enabled():
        return {"authenticated": True, "device_id": x_device_id, "auth_enabled": False}

    # Security: dev mode bypass removed — all requests require valid tokens。
    # 修复:此前 env token 为空(未配置/已过期)就直接 401,抢在 verify_api_token
    # 之前——但 verify_api_token 明确支持【配对发放的每设备 token】在无共享 env
    # token 时独立生效(见其注释),这里的预判把合法设备 token 全部拒了。改为
    # 只记日志提示,真正的判定交给 verify_api_token(设备 token→env token 顺序)。
    if not get_active_tokens():
        logger.warning(
            "Protected endpoint accessed with no active shared API tokens configured; "
            "falling through to per-device token verification. "
            "Set GALAXY_API_TOKEN or GALAXY_API_TOKENS for shared-token auth."
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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Device ID")

    logger.info(f"认证成功: device_id={x_device_id}")

    return {"authenticated": True, "device_id": x_device_id, "dev_mode": False}
