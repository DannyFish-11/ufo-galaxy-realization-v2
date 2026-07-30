"""core/peer_trust.py — 对端分级信任(blocked / unknown / ask / friend / trusted)

为什么需要这一层
----------------
本仓库此前有两种"信任",但都不是**对端信任**:

* ``trust_level`` 在 ``execution_governance_audit_authority`` 等处出现,含义是
  **数据源可信度**(high/medium/low),回答的是"这条真相该不该采信";
* ``core/governance/tool_governor.py`` 的风险分级,回答的是"这个**动作**危不危险"。

缺的是第三个问题:**"这台设备/这个智能体,我信到什么程度"**。没有它,HITL 只能在
"每次都问"和"全都不问"之间二选一 —— 一台刚扫码进来的陌生设备和自己的主力机
被一视同仁。

本模块补上这一层,并刻意与既有两层**正交**:
    风险分级(动作多危险) × 对端信任(这台设备多可信) → 放行 / 拒绝 / 要人确认

设计要点
--------
* 五级:``blocked`` < ``unknown`` < ``ask`` < ``friend`` < ``trusted``。
* ``friend`` 支持 ``auto_accept`` 通配模式(fnmatch,如 ``"messaging.*"``),
  只对匹配上的意图免确认,其余仍要人确认 —— 这是"只问该问的"的关键。
* ``blocked`` 是**硬拒绝**:不看意图、不看模式,直接 DENIED。
* 未登记的对端按 ``default_trust`` 处理(默认 ``ask``,即保守要人确认)。
  可用 ``GALAXY_PEER_DEFAULT_TRUST`` 覆盖。
* 落盘用"写临时文件 → flush → fsync → os.replace → fsync 目录"的原子序列;
  ``os.replace`` 的原子性只覆盖目录项,不覆盖数据块,所以 fsync 不能省。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from fnmatch import fnmatch
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.PeerTrust")


class TrustLevel(str, Enum):
    """对端信任级别(由低到高)。"""

    BLOCKED = "blocked"
    UNKNOWN = "unknown"
    ASK = "ask"
    FRIEND = "friend"
    TRUSTED = "trusted"


#: 由低到高的次序,用于比较(不要依赖 Enum 定义顺序做大小比较)。
_ORDER: Dict[str, int] = {
    TrustLevel.BLOCKED.value: 0,
    TrustLevel.UNKNOWN.value: 1,
    TrustLevel.ASK.value: 2,
    TrustLevel.FRIEND.value: 3,
    TrustLevel.TRUSTED.value: 4,
}


class PermissionResult(str, Enum):
    """一次意图检查的结论。"""

    ALLOWED = "allowed"
    DENIED = "denied"
    REQUIRE_APPROVAL = "require_approval"


def trust_rank(level: Any) -> int:
    """把任意信任级别表示折算成可比较的序数;不认识的按 UNKNOWN。"""
    raw = getattr(level, "value", level)
    return _ORDER.get(str(raw).strip().lower(), _ORDER[TrustLevel.UNKNOWN.value])


def coerce_trust(level: Any, default: TrustLevel = TrustLevel.UNKNOWN) -> TrustLevel:
    """把任意输入折算成 TrustLevel;不认识的返回 *default*。

    注意 TrustLevel 是 (str, Enum),``str(member)`` 得到的是 ``'TrustLevel.ASK'``
    而不是 ``'ask'`` —— 因此这里一律走 ``.value``。
    """
    raw = getattr(level, "value", level)
    key = str(raw).strip().lower()
    for member in TrustLevel:
        if member.value == key:
            return member
    return default


@dataclass
class PeerRecord:
    """一个已登记对端的信任档案。"""

    device_id: str
    name: str = ""
    trust: str = TrustLevel.UNKNOWN.value
    #: fnmatch 模式列表;仅在 trust >= friend 时参与自动放行
    auto_accept: List[str] = field(default_factory=list)
    #: 配对时对方名片声明的能力(仅作展示/审计,不作为授权依据)
    capabilities: List[str] = field(default_factory=list)
    paired_at: float = 0.0
    last_seen: float = 0.0
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _default_trust() -> TrustLevel:
    return coerce_trust(os.getenv("GALAXY_PEER_DEFAULT_TRUST", "").strip(), TrustLevel.ASK)


def _store_path() -> str:
    explicit = os.getenv("GALAXY_PEER_TRUST_PATH", "").strip()
    if explicit:
        return explicit
    base = os.getenv("GALAXY_DATA_DIR", "").strip() or os.path.join(os.getcwd(), "data")
    return os.path.join(base, "peer_trust.json")


class PeerTrustBook:
    """对端信任档案簿(进程内单例,见 get_peer_trust_book)。"""

    def __init__(self, path: Optional[str] = None) -> None:
        self._lock = threading.RLock()
        self._path = path or _store_path()
        self._peers: Dict[str, PeerRecord] = {}
        self._load()

    # ── 持久化 ────────────────────────────────────────────────────────────
    def _load(self) -> None:
        n_bad = 0
        try:
            if not os.path.exists(self._path):
                return
            with open(self._path, encoding="utf-8") as fh:
                raw = json.load(fh)
            for did, rec in (raw.get("peers") or {}).items():
                try:
                    self._peers[str(did)] = PeerRecord(
                        device_id=str(did),
                        name=str(rec.get("name", "") or ""),
                        trust=coerce_trust(rec.get("trust")).value,
                        auto_accept=[str(p) for p in (rec.get("auto_accept") or [])],
                        capabilities=[str(c) for c in (rec.get("capabilities") or [])],
                        paired_at=float(rec.get("paired_at", 0.0) or 0.0),
                        last_seen=float(rec.get("last_seen", 0.0) or 0.0),
                        note=str(rec.get("note", "") or ""),
                    )
                except Exception:  # noqa: BLE001 — 单条损坏不该拖垮整簿
                    n_bad += 1
            if n_bad:
                # 静默跳过会让"信任档案缺了一块"完全不可见 —— 而缺失的档案会让
                # 原本 trusted 的设备悄悄降级成 default_trust(多问几次尚可接受),
                # 或让原本 blocked 的设备**不再被拦**(不可接受)。必须告警。
                logger.warning(
                    "对端信任档案有 %d 条损坏已跳过(成功载入 %d 条):%s;" "被跳过的 blocked 条目将不再生效,请检查该文件",
                    n_bad,
                    len(self._peers),
                    self._path,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("对端信任档案载入失败(按空档案继续):%s: %s", self._path, exc)

    def _save_unlocked(self) -> None:
        payload = {
            "version": 1,
            "updated_at": time.time(),
            "peers": {did: rec.to_dict() for did, rec in self._peers.items()},
        }
        d = os.path.dirname(os.path.abspath(self._path))
        try:
            os.makedirs(d, exist_ok=True)
            tmp = f"{self._path}.tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self._path)
            # os.replace 只保证目录项原子替换,不保证数据块已落盘;
            # 目录本身也要 fsync,否则崩溃后可能看不到这次改名。
            try:
                dfd = os.open(d, os.O_RDONLY)
                try:
                    os.fsync(dfd)
                finally:
                    os.close(dfd)
            except OSError:
                pass
        except Exception as exc:  # noqa: BLE001
            logger.warning("对端信任档案落盘失败(内存内仍生效,重启后丢失):%s", exc)

    # ── 读 ────────────────────────────────────────────────────────────────
    def get(self, device_id: str) -> Optional[PeerRecord]:
        with self._lock:
            rec = self._peers.get(str(device_id))
            return PeerRecord(**rec.to_dict()) if rec else None

    def list_peers(self) -> List[PeerRecord]:
        with self._lock:
            return [PeerRecord(**r.to_dict()) for r in self._peers.values()]

    def trust_of(self, device_id: str) -> TrustLevel:
        """未登记对端返回 default_trust。"""
        with self._lock:
            rec = self._peers.get(str(device_id))
        return coerce_trust(rec.trust) if rec else _default_trust()

    # ── 写 ────────────────────────────────────────────────────────────────
    def upsert(
        self,
        device_id: str,
        *,
        name: Optional[str] = None,
        trust: Optional[Any] = None,
        auto_accept: Optional[List[str]] = None,
        capabilities: Optional[List[str]] = None,
        note: Optional[str] = None,
    ) -> PeerRecord:
        did = str(device_id)
        with self._lock:
            rec = self._peers.get(did)
            if rec is None:
                # 新建档案时的初始信任必须取 _default_trust(),不能用 PeerRecord
                # 的 dataclass 默认值(unknown)。两者是"未指定信任算几级"的两个
                # 不同真相源:未登记对端走 _default_trust()(默认 ask,可配),
                # 而 dataclass 默认是 unknown —— 比 ask 低。
                #
                # 后果:调 POST /api/v1/pair/trust 只传 device_id(比如只想改备注)
                # 就会把该对端从 default_trust 悄悄**降级**成 unknown。若部署方把
                # GALAXY_PEER_DEFAULT_TRUST 设成 friend,原本 allowed 的意图会变成
                # require_approval —— 只想加个备注却动了权限。已实测复现。
                rec = PeerRecord(device_id=did, trust=_default_trust().value, paired_at=time.time())
            if name is not None:
                rec.name = str(name)
            if trust is not None:
                rec.trust = coerce_trust(trust).value
            if auto_accept is not None:
                rec.auto_accept = [str(p) for p in auto_accept]
            if capabilities is not None:
                rec.capabilities = [str(c) for c in capabilities]
            if note is not None:
                rec.note = str(note)
            self._peers[did] = rec
            self._save_unlocked()
            out = PeerRecord(**rec.to_dict())
        logger.info("对端信任已更新:device_id=%s trust=%s auto_accept=%s", did, out.trust, out.auto_accept)
        return out

    def set_trust(self, device_id: str, trust: Any) -> PeerRecord:
        return self.upsert(device_id, trust=trust)

    def touch(self, device_id: str) -> None:
        """记录一次活动时间(不存在则不创建,避免陌生设备被隐式登记)。"""
        with self._lock:
            rec = self._peers.get(str(device_id))
            if rec is None:
                return
            rec.last_seen = time.time()
            self._save_unlocked()

    def remove(self, device_id: str) -> bool:
        with self._lock:
            existed = self._peers.pop(str(device_id), None) is not None
            if existed:
                self._save_unlocked()
        if existed:
            logger.info("对端已从信任档案移除:device_id=%s", device_id)
        return existed

    # ── 判定 ──────────────────────────────────────────────────────────────
    def check(self, device_id: str, intent: str = "") -> PermissionResult:
        """对 *device_id* 执行 *intent* 的放行判定。

        规则(自上而下,先命中先返回):
          1. blocked            → DENIED(硬拒绝,不看意图)
          2. trusted            → ALLOWED
          3. friend + 模式命中  → ALLOWED
          4. 其余(unknown/ask/friend 未命中) → REQUIRE_APPROVAL
        """
        level = self.trust_of(device_id)
        if level is TrustLevel.BLOCKED:
            return PermissionResult.DENIED
        if level is TrustLevel.TRUSTED:
            return PermissionResult.ALLOWED
        if level is TrustLevel.FRIEND and intent:
            rec = self.get(device_id)
            for pattern in (rec.auto_accept if rec else []):
                if fnmatch(intent, pattern):
                    return PermissionResult.ALLOWED
        return PermissionResult.REQUIRE_APPROVAL


# ── 进程级单例 ────────────────────────────────────────────────────────────
_book_lock = threading.Lock()
_book: Optional[PeerTrustBook] = None


def get_peer_trust_book() -> PeerTrustBook:
    global _book
    if _book is not None:
        return _book
    with _book_lock:
        if _book is None:
            _book = PeerTrustBook()
    return _book


def reset_peer_trust_book() -> None:
    """测试用:丢弃单例,下次重新从盘上载入。"""
    global _book
    with _book_lock:
        _book = None


# ── 便捷函数(供调用方少写两行)────────────────────────────────────────────
def trust_of(device_id: str) -> TrustLevel:
    return get_peer_trust_book().trust_of(device_id)


def is_blocked(device_id: str) -> bool:
    return get_peer_trust_book().trust_of(device_id) is TrustLevel.BLOCKED


def check_peer(device_id: str, intent: str = "") -> PermissionResult:
    return get_peer_trust_book().check(device_id, intent)
