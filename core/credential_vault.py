"""
UFO Galaxy - 集中凭证管理模块（Credential Vault）
================================================

功能：
1. 统一读写 API Key（支持 OpenAI/Anthropic/DeepSeek/Groq/OneAPI/Ollama 等）
2. 按 Worker/Device 发放短期 token（内存 token + 过期时间）
3. 访问审计（记录谁在何时请求了哪个凭证，写入日志）

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
"""

import logging
import os
import secrets
import time
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("UFO-Galaxy.CredentialVault")

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


class CredentialVault:
    """
    集中凭证管理器

    - 内存存储凭证（覆盖环境变量）
    - 发放短期 token 给 Worker/Device
    - 记录访问审计日志
    """

    def __init__(self):
        # 内存凭证存储: key_name -> value
        self._credentials: Dict[str, str] = {}
        # token 存储: token -> {device_id, expires_at, scopes}
        self._tokens: Dict[str, Dict] = {}
        # 审计日志列表（最近 1000 条）
        self._audit_log: List[Dict] = []

    # ================================================================
    # 凭证管理
    # ================================================================

    def set_credential(self, key_name: str, value: str) -> None:
        """写入或更新凭证"""
        self._credentials[key_name] = value
        self._record_audit("set", key_name, actor="admin", token=None)
        logger.info(f"Credential '{key_name}' updated")

    def get_credential(self, key_name: str, actor: str = "system") -> Optional[str]:
        """
        读取凭证。
        优先从 Vault 内存获取；若未设置则回退到环境变量。
        """
        # 1. 内存 Vault
        if key_name in self._credentials:
            value = self._credentials[key_name]
            self._record_audit("get", key_name, actor=actor, token=None)
            return value

        # 2. 环境变量回退
        env_key = _ENV_MAPPING.get(key_name, "")
        if env_key:
            value = os.environ.get(env_key, "")
            if value and not value.startswith("your-"):
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
                    if os.environ.get(v, "") and not os.environ.get(v, "").startswith("your-")]
        all_keys = sorted(set(vault_keys + env_keys))
        return all_keys

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


def get_vault() -> CredentialVault:
    global _vault_instance
    if _vault_instance is None:
        _vault_instance = CredentialVault()
    return _vault_instance
