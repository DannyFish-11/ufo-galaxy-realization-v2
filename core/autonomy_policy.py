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
import re
import threading
import time
from dataclasses import dataclass
from enum import Enum
from fnmatch import fnmatch
from typing import Any, Dict, List, Optional

from core.atomic_json import atomic_write_json

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
    "get_*",
    "list_*",
    "find_*",
    "locate*",
    "screenshot",
    "status",
    "health",
    "help",
    "devices",
    "device_info",
    "connected_devices",
    "current_device",
    "adb_path",
    "packages",
    "position",
    "screen_size",
    "get",
    "list",
    "states",  # 读 Home Assistant 实体状态(Node_27)
]


def is_read_action(action: str) -> bool:
    a = (action or "").strip()
    return any(a == p or fnmatch(a, p) for p in _READ_ACTION_PATTERNS)


# ── 授权记录(仅此次/本会话/永久,永久持久化且可撤销)──────────────────────────
class GrantScope(str, Enum):
    ONCE = "once"
    SESSION = "session"
    ALWAYS = "always"


#: 旧位置:仓库根目录下的隐藏文件(不认 GALAXY_DATA_DIR)。那里已有的「一直允许」照认,新装的落数据目录。
_LEGACY_GRANTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".galaxy_grants.json")


def _grants_path() -> str:
    from core.data_paths import data_path_or_legacy

    return data_path_or_legacy("approval_grants.json", _LEGACY_GRANTS)


def _grant_key(node_id: str, action: str, params: Any = None) -> str:
    """节点动作的授权键 —— 与 :func:`core.approval_gate.node_key` 同一个(工具门与节点门对得上)。"""
    from core.approval_gate import node_key

    return node_key(node_id, action, params)


_LEGACY_KEY = re.compile(r"^(Node_\d+[^:]*):([^:@]+)$")


def _migrate_key(key: str) -> str:
    """旧格式「Node_36_UIAWindows:click」→「node:36:click」。认不出的照原样。"""
    m = _LEGACY_KEY.match(key or "")
    return _grant_key(m.group(1), m.group(2)) if m else key


def _full(key: str, target: str) -> str:
    return f"{key}@{target}" if target else key


class GrantStore:
    """三档授权,按「动作 × 对象」记:

    * ``once`` —— 用一次就没了;
    * ``session`` —— 这一段对话里有效(绑对话 id;没有对话 id 的,如 REST 直调,退回进程存活期);
    * ``always`` —— 持久化在数据目录,面板上能撤。

    一条授权说的对象为空,就是对「这个动作」本身 —— 不论对哪个对象都算(旧的「节点:动作」永久授权就是这样)。
    """

    def __init__(self, path: Optional[str] = None):
        self._path = path or _grants_path()
        self._lock = threading.Lock()
        self._once: set = set()
        #: 键 → 在哪些对话里有效("" = 进程存活期)
        self._session: Dict[str, set] = {}
        self._always: Dict[str, Dict[str, Any]] = self._load_always()

    def _load_always(self) -> Dict[str, Dict[str, Any]]:
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
            raw = dict(data.get("always", {}))
        except Exception:  # noqa: BLE001 — 无文件/损坏 → 空
            return {}
        return {_migrate_key(k): v for k, v in raw.items()}

    def _save_always(self) -> None:
        try:
            parent = os.path.dirname(self._path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            atomic_write_json(self._path, {"always": self._always}, ensure_ascii=False, indent=2)
        except Exception as exc:  # noqa: BLE001
            logger.warning("授权记录持久化失败(session 内仍生效): %s", exc)

    # ---- 按授权键(core.approval_gate 用) ----------------------------------

    def grant_key(
        self,
        key: str,
        scope: Any,
        *,
        target: str = "",
        session_id: str = "",
        operator: str = "",
    ) -> str:
        scope = scope if isinstance(scope, GrantScope) else GrantScope(str(scope))
        full = _full(key, target)
        with self._lock:
            if scope is GrantScope.ONCE:
                self._once.add(full)
            elif scope is GrantScope.SESSION:
                self._session.setdefault(full, set()).add(session_id or "")
            else:
                self._always[full] = {
                    "key": key,
                    "target": target,
                    "granted_at": time.time(),
                    "operator": operator or "user",
                }
                self._save_always()
        logger.info("授权记录 %s scope=%s session=%s", full, scope.value, session_id or "-")
        return full

    def _session_hit(self, full: str, session_id: str) -> bool:
        sessions = self._session.get(full)
        return bool(sessions) and ("" in sessions or (bool(session_id) and session_id in sessions))

    def check_key(self, key: str, target: str = "", session_id: str = "", *, consume: bool = True) -> Optional[str]:
        """有对得上的授权返回其档位(``once`` 会被用掉,除非 ``consume=False``);没有返回 None。"""
        candidates = [_full(key, target)] + ([key] if target else [])
        with self._lock:
            for full in candidates:
                if full in self._always:
                    return GrantScope.ALWAYS.value
            for full in candidates:
                if self._session_hit(full, session_id):
                    return GrantScope.SESSION.value
            for full in candidates:
                if full in self._once:
                    if consume:
                        self._once.discard(full)  # 仅此次:用后即焚
                    return GrantScope.ONCE.value
        return None

    # ---- 按节点动作(旧调用方式,键由 node_id/action 算出) ---------------------

    def grant(
        self,
        node_id: str,
        action: str,
        scope: GrantScope,
        *,
        operator: str = "",
        target: str = "",
        session_id: str = "",
        params: Any = None,
    ) -> str:
        return self.grant_key(
            _grant_key(node_id, action, params), scope, target=target, session_id=session_id, operator=operator
        )

    def revoke(self, key: str) -> bool:
        """撤销一条授权(任意档)。``key`` 是 :meth:`list_grants` 里列出来的那个。"""
        key = _migrate_key(key)
        with self._lock:
            hit = False
            if key in self._always:
                del self._always[key]
                self._save_always()
                hit = True
            if key in self._session:
                del self._session[key]
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
    grant_used: str = ""  # 命中的授权档位(once/session/always),有则免审批

    def to_dict(self) -> Dict[str, Any]:
        return {
            "needs_approval": self.needs_approval,
            "level": self.level,
            "node_id": self.node_id,
            "action": self.action,
            "reason": self.reason,
            "grant_used": self.grant_used,
        }


def _declared(node_id: str) -> bool:
    """这个节点声明了动作白名单吗(敏感节点)。``Node_36_UIAWindows`` / ``36`` 都认。"""
    from core.approval_gate import _canon_node
    from core.node_action_permissions import _load_permissions

    canon = _canon_node(node_id)
    return canon.isdigit() and int(canon) in _load_permissions()


def _decide(node_id: str, action: str, params: Any, target: str, session_id: str, *, consume: bool) -> AutonomyDecision:
    level = autonomy_level()

    if level is AutonomyLevel.AUTONOMOUS:
        return AutonomyDecision(False, level.value, node_id, action, "autonomous 档:不逐步问人")

    # v1 范围:只对声明了权限白名单的敏感节点生效
    try:
        declared = _declared(node_id)
    except Exception:  # noqa: BLE001 — 权限模块不可用则不拦
        declared = False
    if not declared:
        return AutonomyDecision(False, level.value, node_id, action, "非敏感节点(未声明权限),不弹审批")

    if level is AutonomyLevel.GUIDED and is_read_action(action):
        return AutonomyDecision(False, level.value, node_id, action, "guided 档:读操作自动放行")

    # safe 档任何动作 / guided 档写操作 → 查授权,无授权则要审批
    used = get_grant_store().check_key(_grant_key(node_id, action, params), target, session_id, consume=consume)
    if used:
        return AutonomyDecision(False, level.value, node_id, action, f"已有授权({used})", grant_used=used)
    what = "任何动作" if level is AutonomyLevel.SAFE else "写操作"
    return AutonomyDecision(True, level.value, node_id, action, f"{level.value} 档:敏感节点{what}需人工审批")


def evaluate_autonomy(
    node_id: str, action: str, *, params: Any = None, target: str = "", session_id: str = ""
) -> AutonomyDecision:
    """这次调用要不要先问人。见模块 docstring 的档位语义。命中「只这一次」的授权会把它用掉。"""
    return _decide(node_id, action, params, target, session_id, consume=True)


def would_ask(node_id: str, action: str, *, params: Any = None, session_id: str = "") -> bool:
    """只读:这次调用会不会停下来问人(不消费任何授权)。给工具超时预算用。"""
    from core.approval_gate import approval_target

    target = approval_target(params) if isinstance(params, dict) else ""
    return _decide(node_id, action, params, target, session_id, consume=False).needs_approval


# ── 审批请求(复用 ApprovalRegistry;去重,排队不跳过)───────────────────────────
def ensure_approval_request(node_id: str, action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """确保存在一条针对 (node_id, action, 对象) 的 pending 审批;返回请求摘要。

    这是**没有人在等**的调用(REST 直调、后台)走的路:排进队列,面板上看得见;人批了之后调用方重试即通过。
    有人在等的调用(智能体的工具调用)不走这里,由 :func:`core.approval_gate.request_approval` 当场问。
    已有同目标 pending → 复用(重试不刷屏)。"""
    from core.approval_gate import GRANT_CHOICES, approval_target, post_approval_card, publish_pending
    from core.control_plane._globals import get_approval_registry
    from core.control_plane.security_interceptor import ApprovalRequest, RiskLevel

    registry = get_approval_registry()
    name = f"{node_id}.{action}"
    key = _grant_key(node_id, action, params)
    obj = approval_target(params or {})
    for req in registry.list_pending():
        ctx = req.context or {}
        if req.action == name and ctx.get("approval_key", key) == key and ctx.get("target", obj) == obj:
            return {"request_id": req.request_id, "action": name, "reused": True}

    req = ApprovalRequest(
        action=name,
        risk_level=RiskLevel.MEDIUM if is_read_action(action) else RiskLevel.HIGH,
        requestor="node_invocation.autonomy_gate",
        context={
            "node_id": node_id,
            "node_action": action,
            "approval_key": key,
            "target": obj,
            "what": f"{name}" + (f"({obj})" if obj else ""),
            "surface": "desktop",
            "waited": False,
            "params_preview": {k: str(v)[:120] for k, v in (params or {}).items()},
            "grant_choices": list(GRANT_CHOICES),
        },
    )
    registry._register(req)  # noqa: SLF001 — 与 SecurityInterceptor 同一入册路径
    post_approval_card(req.request_id, req.context["what"])
    publish_pending()
    logger.info("审批请求已排队 %s request_id=%s", name, req.request_id)
    return {"request_id": req.request_id, "action": name, "reused": False}
