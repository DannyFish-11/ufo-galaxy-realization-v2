"""core/autonomy_policy.py — 自治拨盘 + 审批分级授权(Astrid 借鉴 · P1)
========================================================================

一个用户可拨的**总档位**(面板「行为·在场」分类里的 GALAXY_AUTONOMY),统一回答
"哪些操作要先问人":

  safe        谨慎 —— 敏感节点上【任何】动作都先审批
  guided      引导(默认)—— 【读】(截图/查状态)自动放行,【写】(点击/输入/shell)先审批
  autonomous  自主 —— 不再逐步问人,只剩动作权限白名单与治理门两道硬边界

审批四选(经 /api/v1/approvals 路由):
  仅此次(once) / 本会话(session) / 永久允许(always,落成**可撤销**的授权记录) / 拒绝
人不在线 → 审批请求排队等(ApprovalRegistry pending),动作**不执行也不静默跳过**;
放行后由调用方重试执行。

作用范围(v1,诚实边界):只对【声明了动作权限白名单】的敏感节点生效
(见 core.node_action_permissions —— 8 个设备操作节点)。未声明节点不弹审批,
避免一刀切断 100+ 未收编节点;白名单普及后自然扩大覆盖。

三层门各管一事(均在统一执行器 core.node_invocation 内,顺序执行):
  治理门(节点状态可调否)→ 权限门(节点被允许做此动作否)→ 本门(这次要不要问人)
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from enum import Enum
from fnmatch import fnmatch
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.AutonomyPolicy")


class AutonomyLevel(str, Enum):
    SAFE = "safe"
    GUIDED = "guided"
    AUTONOMOUS = "autonomous"


def autonomy_level() -> AutonomyLevel:
    raw = str(os.getenv("GALAXY_AUTONOMY", "guided")).strip().lower()
    try:
        return AutonomyLevel(raw)
    except ValueError:
        return AutonomyLevel.GUIDED


# ── 读/写动作分类 ─────────────────────────────────────────────────────────────
# 读 = 只观察不改变设备状态(guided 档自动放行)。写 = 其余一切(点击/输入/shell…)。
# 模式与节点白名单同用 fnmatch;宁可把拿不准的动作当"写"(fail-safe 到要审批)。
_READ_ACTION_PATTERNS: List[str] = [
    "get_*", "list_*", "find_*", "locate*", "screenshot", "status", "health",
    "help", "devices", "device_info", "connected_devices", "current_device",
    "adb_path", "packages", "position", "screen_size", "get", "list",
]


def is_read_action(action: str) -> bool:
    a = (action or "").strip()
    return any(a == p or fnmatch(a, p) for p in _READ_ACTION_PATTERNS)


# ── 授权记录(仅此次/本会话/永久,永久持久化且可撤销)──────────────────────────
class GrantScope(str, Enum):
    ONCE = "once"
    SESSION = "session"
    ALWAYS = "always"


def _grants_path() -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, ".galaxy_grants.json")


def _grant_key(node_id: str, action: str) -> str:
    return f"{(node_id or '').strip()}:{(action or '').strip()}"


class GrantStore:
    """三档授权:once(一次性,用后即焚) / session(进程存活期) / always(持久化,可撤销)。"""

    def __init__(self, path: Optional[str] = None):
        self._path = path or _grants_path()
        self._lock = threading.Lock()
        self._once: set = set()
        self._session: set = set()
        self._always: Dict[str, Dict[str, Any]] = self._load_always()

    def _load_always(self) -> Dict[str, Dict[str, Any]]:
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
            return dict(data.get("always", {}))
        except Exception:  # noqa: BLE001 — 无文件/损坏 → 空
            return {}

    def _save_always(self) -> None:
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump({"always": self._always}, f, ensure_ascii=False, indent=2)
        except Exception as exc:  # noqa: BLE001
            logger.warning("授权记录持久化失败(session 内仍生效): %s", exc)

    def grant(self, node_id: str, action: str, scope: GrantScope, *, operator: str = "") -> str:
        key = _grant_key(node_id, action)
        with self._lock:
            if scope is GrantScope.ONCE:
                self._once.add(key)
            elif scope is GrantScope.SESSION:
                self._session.add(key)
            else:
                self._always[key] = {
                    "node_id": node_id, "action": action,
                    "granted_at": time.time(), "operator": operator or "user",
                }
                self._save_always()
        logger.info("授权记录 %s scope=%s", key, scope.value)
        return key

    def consume_or_check(self, node_id: str, action: str) -> Optional[str]:
        """有授权返回其档位(once 会被消费掉);无授权返回 None。"""
        key = _grant_key(node_id, action)
        with self._lock:
            if key in self._always:
                return GrantScope.ALWAYS.value
            if key in self._session:
                return GrantScope.SESSION.value
            if key in self._once:
                self._once.discard(key)  # 仅此次:用后即焚
                return GrantScope.ONCE.value
        return None

    def revoke(self, key: str) -> bool:
        """撤销一条授权(任意档)。"""
        with self._lock:
            hit = False
            if key in self._always:
                del self._always[key]
                self._save_always()
                hit = True
            if key in self._session:
                self._session.discard(key)
                hit = True
            if key in self._once:
                self._once.discard(key)
                hit = True
        if hit:
            logger.info("授权已撤销 %s", key)
        return hit

    def list_grants(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "always": dict(self._always),
                "session": sorted(self._session),
                "once_pending": sorted(self._once),
            }


_store: Optional[GrantStore] = None
_store_lock = threading.Lock()


def get_grant_store() -> GrantStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = GrantStore()
    return _store


def reset_grant_store() -> None:
    """测试用。"""
    global _store
    with _store_lock:
        _store = None


# ── 判定 ─────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class AutonomyDecision:
    needs_approval: bool
    level: str
    node_id: str = ""
    action: str = ""
    reason: str = ""
    grant_used: str = ""     # 命中的授权档位(once/session/always),有则免审批

    def to_dict(self) -> Dict[str, Any]:
        return {
            "needs_approval": self.needs_approval, "level": self.level,
            "node_id": self.node_id, "action": self.action,
            "reason": self.reason, "grant_used": self.grant_used,
        }


def evaluate_autonomy(node_id: str, action: str) -> AutonomyDecision:
    """这次调用要不要先问人。见模块 docstring 的档位语义。"""
    level = autonomy_level()

    if level is AutonomyLevel.AUTONOMOUS:
        return AutonomyDecision(False, level.value, node_id, action, "autonomous 档:不逐步问人")

    # v1 范围:只对声明了权限白名单的敏感节点生效
    try:
        from core.node_action_permissions import _load_permissions, _node_num
        num = _node_num(node_id)
        declared = num is not None and num in _load_permissions()
    except Exception:  # noqa: BLE001 — 权限模块不可用则不拦
        declared = False
    if not declared:
        return AutonomyDecision(False, level.value, node_id, action, "非敏感节点(未声明权限),不弹审批")

    if level is AutonomyLevel.GUIDED and is_read_action(action):
        return AutonomyDecision(False, level.value, node_id, action, "guided 档:读操作自动放行")

    # safe 档任何动作 / guided 档写操作 → 查授权,无授权则要审批
    used = get_grant_store().consume_or_check(node_id, action)
    if used:
        return AutonomyDecision(False, level.value, node_id, action,
                                f"已有授权({used})", grant_used=used)
    what = "任何动作" if level is AutonomyLevel.SAFE else "写操作"
    return AutonomyDecision(True, level.value, node_id, action,
                            f"{level.value} 档:敏感节点{what}需人工审批")


# ── 审批请求(复用 ApprovalRegistry;去重,排队不跳过)───────────────────────────
def ensure_approval_request(node_id: str, action: str,
                            params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """确保存在一条针对 (node_id, action) 的 pending 审批;返回请求摘要。

    已有同目标 pending → 复用(重试不刷屏)。人不在线就一直排在 pending 列表里,
    动作不执行、也不静默跳过。"""
    from core.control_plane._globals import get_approval_registry
    from core.control_plane.security_interceptor import ApprovalRequest, RiskLevel

    registry = get_approval_registry()
    target = f"{node_id}.{action}"
    for req in registry.list_pending():
        if req.action == target:
            return {"request_id": req.request_id, "action": target, "reused": True}

    req = ApprovalRequest(
        action=target,
        risk_level=RiskLevel.MEDIUM if is_read_action(action) else RiskLevel.HIGH,
        requestor="node_invocation.autonomy_gate",
        context={
            "node_id": node_id, "node_action": action,
            "params_preview": {k: str(v)[:120] for k, v in (params or {}).items()},
            "grant_choices": [s.value for s in GrantScope] + ["deny"],
        },
    )
    registry._register(req)  # noqa: SLF001 — 与 SecurityInterceptor 同一入册路径
    logger.info("审批请求已排队 %s request_id=%s", target, req.request_id)
    return {"request_id": req.request_id, "action": target, "reused": False}
