"""
core/device_token_registry.py — 每设备 token 注册表(配对发放的凭证底座)
======================================================================

背景 / 为什么要有它
-------------------
此前网关鉴权只认环境变量里**一个大家共用的** token(``core/auth.py`` 的
``GALAXY_API_TOKEN`` / ``GALAXY_API_TOKENS``),并且**没有任何发放路径**:没有
UI 能填、``/api/v1/config`` 也不吐 token,更没有"给某台设备发一个专属 token"的
端点。直接后果是——要么鉴权全关(谁连上谁就是自己人),要么一开就把所有设备
全挡在外面(没办法把共享 token 送到设备上)。

本模块补上"每设备一个可单独吊销的 token"这一层:配对批准后为设备**发放**一个
专属 token,设备之后凭它连接;可**按设备吊销**而不影响其它设备。共享 env token
仍由 ``core.auth`` 保留作管理员兜底,两者叠加生效。

安全取舍(单用户 / 局域网或 tailnet 场景)
------------------------------------------
- 文件里**只存 token 的 sha256 摘要,绝不存明文**——存储被读走也拿不到可用 token。
- 校验时对"呈递 token 的摘要"与"存储摘要"做**常量时间比较**(见 verify)。
- 原子落盘(临时文件 + os.replace),多进程/崩溃不会写坏半个文件。
- 存储路径默认在仓库【之外】(``~/.galaxy/device_tokens.json``),不进 git;可用
  ``GALAXY_DEVICE_TOKEN_STORE`` 覆盖。

本模块只管"凭证的发放/校验/吊销/枚举",不含配对流程/智能体准入(那是上层
端点的职责)——保持单一职责,便于单测。
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.DeviceTokenRegistry")

_STORE_SCHEMA_VERSION = 1


def _default_store_path() -> Path:
    """默认存储路径:仓库之外(不进 git),可用 GALAXY_DEVICE_TOKEN_STORE 覆盖。"""
    override = os.environ.get("GALAXY_DEVICE_TOKEN_STORE", "").strip()
    if override:
        return Path(override).expanduser()
    base = os.environ.get("GALAXY_DATA_DIR", "").strip()
    root = Path(base).expanduser() if base else (Path.home() / ".galaxy")
    return root / "device_tokens.json"


def _hash_token(token: str) -> str:
    """token → sha256 十六进制摘要(存储/比较用,绝不落明文)。"""
    return hashlib.sha256(token.encode("utf-8", errors="strict")).hexdigest()


class DeviceTokenRegistry:
    """文件落地的每设备 token 注册表(线程安全)。

    记录形状(内存 & 磁盘,均只含摘要不含明文)::

        {
          "token_sha256": "<hex>",
          "device_id": "<uuid/稳定身份>",
          "device_type": "android" | "wearos" | ...,
          "name": "小米17",              # 人类可读,用于批准/管理界面
          "issued_at": 1700000000.0,
          "last_seen": 1700000123.0,     # 最近一次成功校验
          "revoked": false,
          "revoked_at": null,
        }
    """

    def __init__(self, store_path: Optional[Path] = None) -> None:
        self._path = Path(store_path) if store_path else _default_store_path()
        self._lock = threading.RLock()
        # token_sha256 -> record
        self._by_hash: Dict[str, Dict[str, Any]] = {}
        self._load()

    # ── 持久化 ────────────────────────────────────────────────────────────
    def _load(self) -> None:
        with self._lock:
            self._by_hash = {}
            try:
                if not self._path.exists():
                    return
                import json

                data = json.loads(self._path.read_text(encoding="utf-8") or "{}")
            except Exception as exc:  # noqa: BLE001
                logger.warning("设备 token 存储读取失败(以空表启动): %s", exc)
                return
            for rec in data.get("tokens", []):
                h = rec.get("token_sha256")
                if isinstance(h, str) and h:
                    self._by_hash[h] = rec

    def _persist(self) -> None:
        """原子落盘:临时文件 + os.replace,避免写坏半个文件。"""
        import json

        with self._lock:
            payload = {
                "schema_version": _STORE_SCHEMA_VERSION,
                "tokens": list(self._by_hash.values()),
            }
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self._path.with_suffix(self._path.suffix + f".tmp.{os.getpid()}")
                tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                try:
                    os.chmod(tmp, 0o600)  # 尽量收紧权限(best-effort,Windows 上忽略)
                except OSError:
                    pass
                os.replace(tmp, self._path)
            except Exception as exc:  # noqa: BLE001
                logger.error("设备 token 存储落盘失败: %s", exc)

    # ── 发放 / 校验 / 吊销 / 枚举 ─────────────────────────────────────────
    def issue(
        self,
        device_id: str,
        *,
        device_type: Optional[str] = None,
        name: Optional[str] = None,
    ) -> str:
        """为设备发放一个新的专属 token,返回【明文 token(仅此一次可见)】。

        同一 device_id 再次发放会新增一条记录(轮换);旧记录不自动作废,需显式
        revoke(便于重装/换机的过渡窗口)。调用方(配对端点)应在**智能体准入
        批准之后**才调用本方法。
        """
        if not device_id or not str(device_id).strip():
            raise ValueError("device_id 不能为空")
        raw = secrets.token_urlsafe(32)
        rec = {
            "token_sha256": _hash_token(raw),
            "device_id": str(device_id).strip(),
            "device_type": device_type,
            "name": name,
            "issued_at": time.time(),
            "last_seen": None,
            "revoked": False,
            "revoked_at": None,
        }
        with self._lock:
            self._by_hash[rec["token_sha256"]] = rec
            self._persist()
        logger.info("为设备发放 token: device_id=%s type=%s name=%s", device_id, device_type, name)
        return raw

    def verify(self, token: str) -> Optional[Dict[str, Any]]:
        """校验呈递的 token;命中且未吊销则返回其设备记录(不含明文),否则 None。

        常量时间比较,避免时序侧信道;命中即刷新 last_seen。
        """
        if not token:
            return None
        try:
            presented = _hash_token(token)
        except Exception:  # noqa: BLE001
            return None
        with self._lock:
            match: Optional[Dict[str, Any]] = None
            for h, rec in self._by_hash.items():
                # 常量时间比较每个摘要(摘要等长,compare_digest 安全)
                if hmac.compare_digest(h, presented):
                    match = rec
                    break
            if match is None:
                return None
            if match.get("revoked"):
                return None
            match["last_seen"] = time.time()
            self._persist()
            # 返回副本,避免调用方改到内部状态
            return dict(match)

    def revoke_device(self, device_id: str) -> int:
        """吊销某设备名下的【全部】token,返回吊销条数。"""
        did = str(device_id).strip()
        n = 0
        with self._lock:
            for rec in self._by_hash.values():
                if rec.get("device_id") == did and not rec.get("revoked"):
                    rec["revoked"] = True
                    rec["revoked_at"] = time.time()
                    n += 1
            if n:
                self._persist()
        if n:
            logger.info("吊销设备 token: device_id=%s 条数=%d", did, n)
        return n

    def list_devices(self) -> List[Dict[str, Any]]:
        """枚举所有记录的**元数据**(绝不含明文/摘要),供管理/批准界面用。"""
        with self._lock:
            out = []
            for rec in self._by_hash.values():
                out.append(
                    {
                        "device_id": rec.get("device_id"),
                        "device_type": rec.get("device_type"),
                        "name": rec.get("name"),
                        "issued_at": rec.get("issued_at"),
                        "last_seen": rec.get("last_seen"),
                        "revoked": bool(rec.get("revoked")),
                    }
                )
            return out


# ── 进程级单例(默认路径) ────────────────────────────────────────────────
_registry: Optional[DeviceTokenRegistry] = None
_registry_lock = threading.Lock()


def get_device_token_registry() -> DeviceTokenRegistry:
    """返回默认存储路径的进程级单例。"""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = DeviceTokenRegistry()
    return _registry


def verify_device_token(token: str) -> Optional[Dict[str, Any]]:
    """便捷入口:用单例校验一个每设备 token。"""
    return get_device_token_registry().verify(token)
