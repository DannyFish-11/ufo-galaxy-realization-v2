"""core/node_action_permissions.py — 节点动作权限门禁(manifest 声明 · fail-closed)
=====================================================================================

借 Astrid 的"Manifest 门禁"思路(借魂不借壳):每个敏感节点在 SSOT
(``config/node_catalog.json``,由 scripts/gen_node_catalog.py 生成)里**声明**它允许
被调用的动作白名单;统一执行器(:mod:`core.node_invocation`)在治理资格门之后、加载
节点之前,按声明**强制校验**:

  - 节点【已声明】权限:动作不在白名单 → **拒绝执行**(fail-closed)。即使上游被
    prompt 注入,也无法越权调用未声明动作——白名单是独立于模型/编排的硬边界。
  - 节点【未声明】:legacy 放行 + debug 告警(增量收编,不一刀切断 100+ 未核实节点);
    设 ``GALAXY_PERM_STRICT=1`` 后未声明节点一律拒绝(白名单全量普及后收紧)。

与既有两道门的关系(三层各管一事,独立 fail-closed):
  1. 治理资格门(node_invocation_governance):这个节点【当前状态】可不可以被调?
     (archived/unhealthy/readiness-gap)
  2. **本门禁**:这个节点【被允许做】这个动作吗?(声明式能力边界)
  3. HITL 审批(approvals):这次高危操作【人】放不放行?

白名单条目支持 fnmatch 通配(如 ``get_*``)。
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Dict, List, Optional

logger = logging.getLogger("Galaxy.NodeActionPermissions")

_NODE_DIR_RE = re.compile(r"^Node_(\d+)(?:_|$)")


def _strict_mode() -> bool:
    return str(os.getenv("GALAXY_PERM_STRICT", "")).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class PermissionDecision:
    """一次动作权限判定的结构化结果(冻结,防事后篡改)。"""

    allowed: bool
    declared: bool  # 该节点是否有权限声明
    node_id: str = ""
    action: str = ""
    reason: str = ""
    matched_pattern: str = ""  # 命中的白名单条目(便于审计)

    def to_dict(self) -> Dict[str, object]:
        return {
            "allowed": self.allowed,
            "declared": self.declared,
            "node_id": self.node_id,
            "action": self.action,
            "reason": self.reason,
            "matched_pattern": self.matched_pattern,
        }


# ── 目录加载(缓存;测试可注入) ────────────────────────────────────────────────
_lock = threading.Lock()
_cache: Optional[Dict[int, List[str]]] = None


def _catalog_path() -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "config", "node_catalog.json")


def _load_permissions() -> Dict[int, List[str]]:
    """num → 动作白名单。仅含声明了 permissions.actions 的节点。"""
    global _cache
    if _cache is not None:
        return _cache
    with _lock:
        if _cache is not None:
            return _cache
        table: Dict[int, List[str]] = {}
        try:
            with open(_catalog_path(), encoding="utf-8") as f:
                data = json.load(f)
            for n in data.get("nodes", []):
                perms = n.get("permissions") or {}
                actions = perms.get("actions")
                if isinstance(actions, list) and actions:
                    table[int(n["num"])] = [str(a) for a in actions]
        except Exception as exc:  # noqa: BLE001 — 目录读不到≠执行系统瘫痪
            logger.warning("节点权限目录加载失败(门禁降级为 legacy 放行): %s", exc)
        _cache = table
        return table


def reset_cache() -> None:
    """测试用:清空缓存。"""
    global _cache
    with _lock:
        _cache = None


def _node_num(node_id: str) -> Optional[int]:
    """从节点目录名(Node_36_UIAWindows)解析编号;解析不出返回 None。"""
    m = _NODE_DIR_RE.match((node_id or "").strip())
    return int(m.group(1)) if m else None


def evaluate_action_permission(node_id: str, action: str) -> PermissionDecision:
    """判定 node_id 上是否允许调用 action。见模块 docstring 的三条语义。"""
    action = (action or "").strip()
    num = _node_num(node_id)
    table = _load_permissions()

    if num is None or num not in table:
        # 未声明节点:legacy 放行(strict 模式收紧为拒绝)
        if _strict_mode():
            return PermissionDecision(
                allowed=False,
                declared=False,
                node_id=node_id,
                action=action,
                reason="strict 模式:节点未声明动作权限,一律拒绝",
            )
        logger.debug("节点 %s 未声明动作权限,legacy 放行 action=%s", node_id, action)
        return PermissionDecision(
            allowed=True,
            declared=False,
            node_id=node_id,
            action=action,
            reason="节点未声明权限(legacy 放行)",
        )

    whitelist = table[num]
    for pattern in whitelist:
        if action == pattern or fnmatch(action, pattern):
            return PermissionDecision(
                allowed=True,
                declared=True,
                node_id=node_id,
                action=action,
                reason="动作在声明白名单内",
                matched_pattern=pattern,
            )
    return PermissionDecision(
        allowed=False,
        declared=True,
        node_id=node_id,
        action=action,
        reason=f"动作 {action!r} 不在节点声明的白名单内(fail-closed)",
    )
