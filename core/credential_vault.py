"""
Galaxy - 集中凭证管理模块（Credential Vault）
================================================

功能：
1. 统一读写 API Key（支持 OpenAI/Anthropic/DeepSeek/Groq/OneAPI/Ollama 等）
2. 按 Worker/Device 发放短期 token（内存 token + 过期时间）
3. 访问审计（记录谁在何时请求了哪个凭证，写入日志）

Secrets backend selection (PR-G3)
----------------------------------
The vault supports three back-ends, selected by the ``GALAXY_SECRET_BACKEND``
environment variable:

  env    (default) — read from environment variables; store in memory.
  vault            — delegate get/set to Node_03 SecretVault HTTP API.
                     Requires SECRETVAULT_URL (default: http://localhost:8003)
                     and optionally SECRETVAULT_MASTER_KEY for the node.
  kms              — future placeholder; falls back to "env" with a warning.

使用方法：
    from core.credential_vault import get_vault

    vault = get_vault()

    # 写入凭证
    vault.set_credential("openai", "sk-xxx")

    # 读取凭证
    key = vault.get_credential("openai")

    # 为 worker 颁发短期 token
    token = vault.issue_token("device-001", ttl=300)

    # Worker 用 token 拉取凭证
    key = vault.get_credential_by_token(token, "openai")

Migration from plain ENV to SecretVault
-----------------------------------------
See docs/CONFIG_GOVERNANCE.md § "Migrating secrets to SecretVault" for a
step-by-step guide.  Quick summary:

    1. Start Node_03 (SecretVault) and set SECRETVAULT_MASTER_KEY.
    2. Set GALAXY_SECRET_BACKEND=vault in .env.
    3. Run the one-shot migration helper:
         python -c "from core.credential_vault import migrate_env_to_vault; migrate_env_to_vault()"
    4. Remove plain-text secrets from .env (keep only non-sensitive vars).
"""

import logging
import os
import secrets
import time
from typing import Dict, List, Optional, Tuple

# Optional HTTP client — used only when GALAXY_SECRET_BACKEND=vault
try:
    import urllib.request
    import urllib.error
    import json as _json
    _HAS_HTTP = True
except ImportError:  # pragma: no cover
    _HAS_HTTP = False

logger = logging.getLogger("Galaxy.CredentialVault")

# ---------------------------------------------------------------------------
# Back-end constants
# ---------------------------------------------------------------------------

#: Name of the env var that selects the secrets back-end.
BACKEND_ENV_VAR = "GALAXY_SECRET_BACKEND"
#: Default Node_03 SecretVault base URL.
_DEFAULT_VAULT_URL = "http://localhost:8003"

#: Value prefixes that indicate a placeholder (not a real secret).
#: Exported so that other modules (e.g. config_preflight) can share the same
#: detection logic without duplicating the list.
PLACEHOLDER_PREFIXES: tuple = ("your_", "your-", "change_me", "todo", "<", "example", "xxx")

# 支持的凭证键名 -> 对应的环境变量名
_ENV_MAPPING: Dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "openai_base": "OPENAI_API_BASE",
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "groq": "GROQ_API_KEY",
    "ollama": "OLLAMA_URL",
    "oneapi": "ONEAPI_API_KEY",
    "oneapi_url": "ONEAPI_URL",
}


# ---------------------------------------------------------------------------
# Optional Node_03 SecretVault HTTP back-end
# ---------------------------------------------------------------------------

class _SecretVaultBackend:
    """
    Thin HTTP client for Node_03 (SecretVault).

    Only instantiated when ``GALAXY_SECRET_BACKEND=vault``.
    All methods degrade gracefully if the vault node is unreachable —
    the caller falls back to the in-memory / ENV layer.
    """

    def __init__(self, base_url: str = "") -> None:
        self._base_url = (base_url or os.environ.get("SECRETVAULT_URL", _DEFAULT_VAULT_URL)).rstrip("/")
        logger.info("SecretVault HTTP backend initialised at %s", self._base_url)

    def get(self, key_name: str) -> Optional[str]:
        """Fetch a secret from Node_03; returns None on error."""
        if not _HAS_HTTP:
            return None  # pragma: no cover
        url = f"{self._base_url}/secrets/{key_name}"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                data = _json.loads(resp.read())
                return data.get("value")
        except Exception as exc:
            logger.debug("SecretVault GET '%s' failed: %s", key_name, exc)
            return None

    def set(self, key_name: str, value: str) -> bool:
        """Store a secret in Node_03; returns True on success."""
        if not _HAS_HTTP:
            return False  # pragma: no cover
        url = f"{self._base_url}/secrets"
        payload = _json.dumps({"key": key_name, "value": value, "encrypted": True}).encode()
        try:
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=2):
                pass
            return True
        except Exception as exc:
            logger.debug("SecretVault SET '%s' failed: %s", key_name, exc)
            return False

    def health(self) -> bool:
        """Return True if Node_03 responds to /health."""
        if not _HAS_HTTP:
            return False  # pragma: no cover
        try:
            req = urllib.request.Request(f"{self._base_url}/health", method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                return resp.status == 200
        except Exception:
            return False


class CredentialVault:
    """
    集中凭证管理器

    - 内存存储凭证（覆盖环境变量）
    - 发放短期 token 给 Worker/Device
    - 记录访问审计日志
    - 可选的 Node_03 SecretVault HTTP 后端（GALAXY_SECRET_BACKEND=vault）
    """

    def __init__(self, backend: Optional["_SecretVaultBackend"] = None) -> None:
        # 内存凭证存储: key_name -> value
        self._credentials: Dict[str, str] = {}
        # token 存储: token -> {device_id, expires_at, scopes}
        self._tokens: Dict[str, Dict] = {}
        # 审计日志列表（最近 1000 条）
        self._audit_log: List[Dict] = []
        # Optional remote back-end (None → env/memory only)
        self._backend: Optional[_SecretVaultBackend] = backend

    # ================================================================
    # 凭证管理
    # ================================================================

    def set_credential(self, key_name: str, value: str, actor: str = "admin") -> None:
        """写入或更新凭证。若启用了 SecretVault 后端，同步写入远端。"""
        self._credentials[key_name] = value
        self._record_audit("set", key_name, actor=actor, token=None)
        logger.info(f"Credential '{key_name}' updated")
        # Propagate to remote backend (best-effort; never blocks startup)
        if self._backend is not None:
            ok = self._backend.set(key_name, value)
            if not ok:
                logger.warning(
                    "SecretVault backend: failed to persist '%s'; "
                    "credential retained in memory only.",
                    key_name,
                )

    def get_credential(self, key_name: str, actor: str = "system") -> Optional[str]:
        """
        读取凭证。优先级：
          1. 内存 Vault（in-process cache）
          2. SecretVault HTTP backend（若 GALAXY_SECRET_BACKEND=vault）
          3. 环境变量回退
        """
        # 1. 内存 Vault
        if key_name in self._credentials:
            value = self._credentials[key_name]
            self._record_audit("get", key_name, actor=actor, token=None)
            return value

        # 2. Remote SecretVault backend
        if self._backend is not None:
            remote = self._backend.get(key_name)
            if remote:
                # Cache locally for subsequent calls
                self._credentials[key_name] = remote
                self._record_audit("get_vault", key_name, actor=actor, token=None)
                return remote

        # 3. 环境变量回退
        env_key = _ENV_MAPPING.get(key_name, "")
        if env_key:
            value = os.environ.get(env_key, "")
            if value and not value.lower().startswith(PLACEHOLDER_PREFIXES):
                self._record_audit("get_env", key_name, actor=actor, token=None)
                return value

        return None

    def delete_credential(self, key_name: str) -> bool:
        """删除 Vault 内存中的凭证（不影响环境变量）"""
        if key_name in self._credentials:
            del self._credentials[key_name]
            self._record_audit("delete", key_name, actor="admin", token=None)
            return True
        return False

    def list_credential_keys(self) -> List[str]:
        """列出所有已存储的凭证键名（不返回值）"""
        vault_keys = list(self._credentials.keys())
        env_keys = [k for k, v in _ENV_MAPPING.items()
                    if os.environ.get(v, "") and not os.environ.get(v, "").lower().startswith(PLACEHOLDER_PREFIXES)]
        all_keys = sorted(set(vault_keys + env_keys))
        return all_keys

    @property
    def backend_name(self) -> str:
        """Returns the active back-end name: 'vault', 'kms', or 'env'."""
        backend_env = os.environ.get(BACKEND_ENV_VAR, "env").lower().strip()
        if self._backend is not None:
            return "vault"
        if backend_env == "kms":
            return "kms"
        return "env"

    # ================================================================
    # Token 管理
    # ================================================================

    def issue_token(
        self,
        device_id: str,
        ttl: int = 300,
        scopes: Optional[List[str]] = None,
    ) -> str:
        """
        为 Worker/Device 颁发短期 token

        Args:
            device_id: 设备或 Worker ID
            ttl: token 有效期（秒），默认 300 秒
            scopes: 允许访问的凭证键名列表，None 表示所有

        Returns:
            token 字符串
        """
        token = secrets.token_urlsafe(32)
        self._tokens[token] = {
            "device_id": device_id,
            "issued_at": time.time(),
            "expires_at": time.time() + ttl,
            "scopes": scopes,  # None = 全部
        }
        self._record_audit("issue_token", f"device={device_id}", actor=device_id, token=token)
        logger.info(f"Token issued for device '{device_id}', ttl={ttl}s")
        return token

    def revoke_token(self, token: str) -> bool:
        """撤销 token"""
        if token in self._tokens:
            device_id = self._tokens[token].get("device_id", "")
            del self._tokens[token]
            self._record_audit("revoke_token", f"device={device_id}", actor="admin", token=token)
            return True
        return False

    def validate_token(self, token: str) -> Tuple[bool, Optional[str]]:
        """
        验证 token 是否有效

        Returns:
            (valid, device_id)
        """
        info = self._tokens.get(token)
        if not info:
            return False, None
        if time.time() > info["expires_at"]:
            del self._tokens[token]
            return False, None
        return True, info["device_id"]

    def get_credential_by_token(self, token: str, key_name: str) -> Optional[str]:
        """
        Worker 用 token 拉取凭证

        Args:
            token: 由 issue_token 颁发的 token
            key_name: 凭证键名

        Returns:
            凭证值，若 token 无效或无权访问则返回 None
        """
        info = self._tokens.get(token)
        if not info:
            logger.warning(f"get_credential_by_token: unknown token")
            return None
        if time.time() > info["expires_at"]:
            del self._tokens[token]
            logger.warning(f"get_credential_by_token: token expired for device '{info.get('device_id')}'")
            return None

        # 检查 scope
        scopes = info.get("scopes")
        if scopes is not None and key_name not in scopes:
            logger.warning(
                f"get_credential_by_token: device '{info['device_id']}' has no scope for '{key_name}'"
            )
            return None

        device_id = info["device_id"]
        self._record_audit("get_by_token", key_name, actor=device_id, token=token)
        return self.get_credential(key_name, actor=device_id)

    def cleanup_expired_tokens(self) -> int:
        """清理过期 token，返回清理数量"""
        now = time.time()
        expired = [t for t, info in self._tokens.items() if now > info["expires_at"]]
        for t in expired:
            del self._tokens[t]
        if expired:
            logger.debug(f"Cleaned up {len(expired)} expired tokens")
        return len(expired)

    # ================================================================
    # 审计
    # ================================================================

    def _record_audit(
        self, action: str, resource: str, actor: str, token: Optional[str]
    ) -> None:
        """记录审计日志"""
        entry = {
            "timestamp": time.time(),
            "action": action,
            "resource": resource,
            "actor": actor,
            "token_prefix": token[:min(8, len(token))] + "..." if token else None,
        }
        self._audit_log.append(entry)
        # 只保留最近 1000 条
        if len(self._audit_log) > 1000:
            self._audit_log = self._audit_log[-1000:]
        logger.debug(f"Audit: {action} '{resource}' by '{actor}'")

    def get_audit_log(self, limit: int = 100) -> List[Dict]:
        """获取最近 N 条审计记录"""
        return self._audit_log[-limit:]

    def get_health_metrics(self) -> Dict:
        """返回 Vault 健康指标（token 数量、凭证键数量、审计条目数）"""
        return {
            "token_count": len(self._tokens),
            "credential_key_count": len(self._credentials),
            "audit_entries": len(self._audit_log),
        }

    def get_token_info(self, token: str) -> Optional[Dict]:
        """获取 token 元信息（不含凭证值）"""
        info = self._tokens.get(token)
        if not info:
            return None
        return {
            "device_id": info["device_id"],
            "issued_at": info["issued_at"],
            "expires_at": info["expires_at"],
            "expires_in": max(0, info["expires_at"] - time.time()),
            "scopes": info["scopes"],
        }


# ============================================================================
# 单例
# ============================================================================

_vault_instance: Optional[CredentialVault] = None


def _build_backend() -> Optional[_SecretVaultBackend]:
    """
    Instantiate the appropriate secrets back-end based on GALAXY_SECRET_BACKEND.

    Returns None when the back-end is 'env' (default) or 'kms' (not yet
    implemented — falls back to env with a warning).
    """
    name = os.environ.get(BACKEND_ENV_VAR, "env").lower().strip()
    if name == "vault":
        return _SecretVaultBackend()
    if name == "kms":
        logger.warning(
            "GALAXY_SECRET_BACKEND=kms is not yet implemented; "
            "falling back to 'env' back-end.  "
            "Contributions welcome — see docs/CONFIG_GOVERNANCE.md."
        )
    return None


def get_vault() -> CredentialVault:
    """Return (or create) the process-level CredentialVault singleton."""
    global _vault_instance
    if _vault_instance is None:
        backend = _build_backend()
        _vault_instance = CredentialVault(backend=backend)
    return _vault_instance


def reset_vault() -> None:
    """Reset the singleton (intended for testing only)."""
    global _vault_instance
    _vault_instance = None


# ============================================================================
# Migration helper
# ============================================================================

def migrate_env_to_vault(dry_run: bool = False) -> Dict[str, bool]:
    """
    One-shot migration: read all known API keys from environment variables
    and write them into the active secrets back-end.

    This is a **no-op** when GALAXY_SECRET_BACKEND=env (the default) because
    the vault already reads from ENV anyway.

    Returns a dict mapping key_name -> success.

    Usage::

        from core.credential_vault import migrate_env_to_vault
        results = migrate_env_to_vault(dry_run=False)
        print(results)
    """
    vault = get_vault()
    results: Dict[str, bool] = {}

    for key_name, env_var in _ENV_MAPPING.items():
        value = os.environ.get(env_var, "").strip()
        if not value or value.lower().startswith(PLACEHOLDER_PREFIXES):
            results[key_name] = False
            continue
        if dry_run:
            logger.info("migrate_env_to_vault [dry_run]: would store '%s'", key_name)
            results[key_name] = True
            continue
        vault.set_credential(key_name, value, actor="migrate_env_to_vault")
        results[key_name] = True
        logger.info("migrate_env_to_vault: stored '%s'", key_name)

    return results
