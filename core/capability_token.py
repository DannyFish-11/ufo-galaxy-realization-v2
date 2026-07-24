"""core/capability_token.py — Mesh 能力令牌(作用域 · 过期 · 可撤销 · 签名)
==============================================================================

借鉴 Astrid 的能力令牌思路(借魂不借壳):Mesh 设备网络里,一台设备要跨设备调用
能力(或"永久允许"落成的长效授权),不再"入网即全信",而是**持一张签名令牌**,令牌
声明:
  - subject   —— 谁(设备/会话 id)
  - scopes    —— 能干什么(动作作用域,支持 globset/fnmatch,如 "node:Node_36_*:*"
                 或 "device:tap")
  - exp       —— 到什么时候(过期检查)
  - jti       —— 令牌唯一 id(全局可撤销:撤销表命中即失效)

签名选型(诚实说明)
------------------
Astrid 用 ed25519(跨方公钥验证)。本系统是**单一属主**的 Mesh——签发方=验证方
(同一把主密钥),故用 stdlib ``hmac`` + SHA-256 即可给到"作用域+过期+可撤销+防篡改",
零额外依赖、处处可跑。将来要做真正的多属主互信,再切 ed25519 公钥体系。

密钥来源:``GALAXY_MESH_SECRET`` 环境变量;缺省则在 ``.galaxy_mesh_key`` 生成并复用
(0600)。令牌格式:``v1.<payload_b64url>.<sig_b64url>``,均为无填充 base64url。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.CapabilityToken")

_TOKEN_PREFIX = "v1"


# ── 主密钥(单属主:签发=验证)────────────────────────────────────────────────
def _key_path() -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, ".galaxy_mesh_key")


_secret_lock = threading.Lock()
_secret_cache: Optional[bytes] = None


def _mesh_secret() -> bytes:
    global _secret_cache
    if _secret_cache is not None:
        return _secret_cache
    with _secret_lock:
        if _secret_cache is not None:
            return _secret_cache
        env = os.getenv("GALAXY_MESH_SECRET", "").strip()
        if env:
            _secret_cache = env.encode("utf-8")
            return _secret_cache
        path = _key_path()
        try:
            with open(path, "rb") as f:
                _secret_cache = f.read().strip()
                if _secret_cache:
                    return _secret_cache
        except Exception:  # noqa: BLE001 — 无文件 → 生成
            pass
        # 生成一把并落盘(0600);os.urandom 不可用时退回 uuid(测试环境足够)
        try:
            raw = os.urandom(32)
        except Exception:  # noqa: BLE001
            raw = (uuid.uuid4().hex + uuid.uuid4().hex).encode("utf-8")
        try:
            with open(path, "wb") as f:
                f.write(raw)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        except Exception as exc:  # noqa: BLE001 — 落盘失败仍可内存内用
            logger.warning("Mesh 主密钥落盘失败(本进程内存内仍可用): %s", exc)
        _secret_cache = raw
        return _secret_cache


def reset_secret_cache() -> None:
    """测试用。"""
    global _secret_cache
    with _secret_lock:
        _secret_cache = None


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _sign(payload_b64: str) -> str:
    sig = hmac.new(_mesh_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest()
    return _b64e(sig)


# ── 撤销表(jti 全局可撤销,持久化)────────────────────────────────────────────
def _revoked_path() -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, ".galaxy_revoked_tokens.json")


_revoked_lock = threading.Lock()
_revoked_cache: Optional[set] = None


def _load_revoked() -> set:
    global _revoked_cache
    if _revoked_cache is not None:
        return _revoked_cache
    with _revoked_lock:
        if _revoked_cache is not None:
            return _revoked_cache
        try:
            with open(_revoked_path(), encoding="utf-8") as f:
                _revoked_cache = set(json.load(f).get("revoked", []))
        except Exception:  # noqa: BLE001
            _revoked_cache = set()
        return _revoked_cache


def _save_revoked() -> None:
    try:
        with open(_revoked_path(), "w", encoding="utf-8") as f:
            json.dump({"revoked": sorted(_load_revoked())}, f, ensure_ascii=False, indent=2)
    except Exception as exc:  # noqa: BLE001
        logger.warning("撤销表持久化失败: %s", exc)


def revoke(jti: str) -> None:
    # 修复死锁:原来在持有 _revoked_lock(非重入)的情况下调 _load_revoked(),
    # 冷缓存(进程内首次访问)时 _load_revoked 会再次 with _revoked_lock → 卡死。
    # 先在锁外确保缓存加载(它自己拿锁),再持锁做纯内存修改。
    revoked = _load_revoked()
    with _revoked_lock:
        revoked.add(jti)
    _save_revoked()
    logger.info("能力令牌已撤销 jti=%s", jti)


def reset_revoked_cache() -> None:
    """测试用。"""
    global _revoked_cache
    with _revoked_lock:
        _revoked_cache = None


# ── 签发 / 验证 ───────────────────────────────────────────────────────────────
def issue_token(subject: str, scopes: List[str], *, ttl_s: float = 3600.0, now: Optional[float] = None) -> str:
    """签发一张能力令牌。``now`` 可注入(测试/确定性)。"""
    issued = float(now if now is not None else time.time())
    claims = {
        "jti": uuid.uuid4().hex[:16],
        "sub": subject,
        "scopes": list(scopes),
        "iat": issued,
        "exp": issued + float(ttl_s),
    }
    payload_b64 = _b64e(json.dumps(claims, sort_keys=True).encode("utf-8"))
    return f"{_TOKEN_PREFIX}.{payload_b64}.{_sign(payload_b64)}"


@dataclass(frozen=True)
class TokenVerdict:
    valid: bool
    reason: str = ""
    subject: str = ""
    jti: str = ""
    scopes: tuple = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "reason": self.reason,
            "subject": self.subject,
            "jti": self.jti,
            "scopes": list(self.scopes),
        }


def _scope_grants(scopes: List[str], required: str) -> bool:
    return any(required == s or fnmatch(required, s) for s in scopes)


def verify_token(token: str, *, required_scope: Optional[str] = None, now: Optional[float] = None) -> TokenVerdict:
    """验证令牌:格式 → 签名(防篡改)→ 过期 → 撤销 → 作用域。任一不过即 invalid。"""
    t = (token or "").strip()
    parts = t.split(".")
    if len(parts) != 3 or parts[0] != _TOKEN_PREFIX:
        return TokenVerdict(False, "格式非法")
    _, payload_b64, sig = parts
    # 常数时间比对签名,防篡改(改了 payload 或 sig 都过不了)
    if not hmac.compare_digest(sig, _sign(payload_b64)):
        return TokenVerdict(False, "签名不匹配(被篡改或非本 Mesh 签发)")
    try:
        claims = json.loads(_b64d(payload_b64))
    except Exception:  # noqa: BLE001
        return TokenVerdict(False, "载荷解析失败")

    jti = str(claims.get("jti", ""))
    subject = str(claims.get("sub", ""))
    scopes = [str(s) for s in claims.get("scopes", [])]
    exp = float(claims.get("exp", 0))
    cur = float(now if now is not None else time.time())

    if cur >= exp:
        return TokenVerdict(False, "已过期", subject, jti, tuple(scopes))
    if jti in _load_revoked():
        return TokenVerdict(False, "已撤销", subject, jti, tuple(scopes))
    if required_scope is not None and not _scope_grants(scopes, required_scope):
        return TokenVerdict(False, f"作用域不含 {required_scope!r}", subject, jti, tuple(scopes))
    return TokenVerdict(True, "ok", subject, jti, tuple(scopes))
