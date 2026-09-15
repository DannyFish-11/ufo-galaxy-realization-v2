"""nodes/common/action_gate.py — 节点 HTTP 面的动作权限闸(共享,一份)

为什么要有这个模块
------------------
声明了动作白名单的节点有 9 个,它们都有两条入口:

    统一执行器 invoke_node → 治理门 + 动作权限门 + HITL,三道
    自己的 FastAPI 路由     → 一道都没有

``config/node_catalog.json`` 里的白名单是运维手上唯一能收紧这些节点的旋钮,
而它此前只对第一条路有效。把某个动作从白名单里删掉,``invoke_node`` 会拒,
HTTP 路由照常执行 —— **那个旋钮在这条路上是假的**。

Node 36 先单独修过一版,helper 写在它自己的 main.py 里。剩下 8 个节点要是各抄一份,
必然漂:某个节点改了 fail 方向、某个节点漏了 declared 检查,而且没有任何现象。
所以收成这一份。

为什么这里 fail-closed,而 ``node_invocation`` 那边 fail-open
------------------------------------------------------------
``node_invocation`` 在门禁自身抛异常时记一条 warning 然后放行。那在**那条路上**
合理:它前面还有治理门,后面还有 HITL 审批,权限门只是三层里的一层。

HTTP 这条路上**一层都没有**。拿不到门禁就放行,等于这个模块没写。所以相反:
拿不到门禁 → 503,不执行。

还有个更隐蔽的坑
----------------
``_load_permissions()`` 读不到目录时返回**空表**,于是 ``evaluate_action_permission``
把节点判成"未声明" → legacy **放行**。那个默认值是给还没收编的 100+ 个节点用的,
不是给一个已经声明了动作、又能操作设备的节点用的。

调用方传进来的节点是**确定声明了**的(否则不会用这个模块)。所以判定回来说它没声明,
只可能是目录没读进来 —— 那是门禁坏了,不是 manifest 允许。这条路上按拒绝处理。
"""

from __future__ import annotations

import logging

from fastapi import HTTPException

logger = logging.getLogger("Galaxy.NodeActionGate")

__all__ = ["require_action", "action_guard"]


def require_action(node_id: str, action: str) -> None:
    """不通过就抛 ``HTTPException``,通过则静默返回。

    三种情况都拒:门禁导入不了(503)、判定说未声明(503)、动作不在白名单(403)。
    403 和 503 分开是有意的 —— 前者是"你不该做这个",后者是"我现在没法判断",
    运维看到哪一个,该做的事完全不同。
    """
    try:
        from core.node_action_permissions import evaluate_action_permission
    except Exception as exc:  # noqa: BLE001 — 拿不到门禁就不执行,不是放行
        logger.error("动作权限闸不可用,拒绝执行 %s.%s: %s", node_id, action, exc)
        raise HTTPException(
            status_code=503,
            detail=f"action-permission gate unavailable; refusing to act: {exc}",
        ) from exc

    decision = evaluate_action_permission(node_id, action)
    if not decision.declared:
        logger.error("%s 应当已声明动作白名单,门禁却说未声明 —— 目录没读进来", node_id)
        raise HTTPException(
            status_code=503,
            detail=(
                f"{node_id} is known to declare its actions, but the gate reports it as "
                f"undeclared — the catalog failed to load. Refusing to act on action {action!r}."
            ),
        )
    if not decision.allowed:
        logger.warning("%s 拒绝动作 %r: %s", node_id, action, decision.reason)
        raise HTTPException(
            status_code=403,
            detail=f"action {action!r} denied by declared permission manifest: {decision.reason}",
        )


def action_guard(node_id: str):
    """给一个节点绑好 ``node_id`` 的 ``require_action``。

    节点里写 ``_require = action_guard("Node_45_DesktopAuto")``,路由里就只剩
    ``_require("click")`` 一行 —— 少一个每条路由都要重复、而且可能抄错的参数。
    """

    def _require(action: str) -> None:
        require_action(node_id, action)

    return _require
