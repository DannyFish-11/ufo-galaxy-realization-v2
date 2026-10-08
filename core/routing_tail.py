"""偏好表没列、但已经配好且可用的厂商 —— 路由的最后一档备选。

## 被修的问题

``TASK_ROUTING_PREFERENCES`` 只列**我们核实过的直连厂商**。于是有两类**已注册、已验过、可用**的
提供商，在智能路由里是「不存在」的：

* **用户在面板上自己加的端点**（``source_type="user"``）与 **OneAPI 聚合网关** —— 它们根本不可能
  出现在一张写死在代码里的表上。面板那一段的说明写的是「通了才让它参与选路」，实际上它们只会在
  「所有列出来的厂商都不可用」时，被「任选一个」那条兜底碰到，而且不排序、没有备选。
* **配了 Key、却没被列进某个任务类型的直连厂商**（如只配了 Groq 的人做推理任务）—— 别的厂商一旦
  失败，故障转移链里没有它。那把 Key 白填了，也没有任何报错。

和上一次「agnes / moonshot / openrouter 注册了却没进任何偏好表、从未被自动选中」是同一类漏配，
只是这次漏的是**不可能进表的那一批**。

## 规则

1. 偏好表里列出的，照旧：按偏好 + 打分（本模块不碰）。
2. 没列、但已注册且可用的，排在它们**后面**，按同一个打分（``_order_cloud_by_fit``）排序，
   作为失败转移的后几档。**永远在列出来的后面** —— 偏好表是我们核实过的，用户端点是他自己声明的。
3. **有意不自动参与选路的不进这一档**：不在任何任务偏好表里的直连厂商（智谱编码套餐 —— 订阅制、
   仅编码场景，见 ``provider_registry`` 里那段说明）。它们只在「没有别的可用」时才作最后兜底，
   与原先「任选一个可用」的语义一致。

纯函数式、不碰网络、不改路由器状态。
"""

from __future__ import annotations

from typing import Any, List, Set


def _opt_in_names() -> Set[str]:
    """不在任何任务偏好表里的直连厂商 + 从未真正注册过的本地占位 —— 它们是有意不自动参与选路的。"""
    from core.multi_llm_router import PROVIDER_REGISTRY, TASK_ROUTING_PREFERENCES

    listed = {p for names in TASK_ROUTING_PREFERENCES.values() for p in names}
    return {e["name"] for e in PROVIDER_REGISTRY if e["name"] not in listed} | {"hf_local"}


def unlisted_available(router: Any, listed: List[str], task_type: Any, complexity: float, purpose: Any) -> List[str]:
    """已注册、可用、但 ``listed`` 里没有的厂商，按打分排好。有意不自动参与的不在其中。"""
    skip = set(listed) | _opt_in_names()
    names = [n for n, p in router.providers.items() if n not in skip and p.is_available()]
    return router._order_cloud_by_fit(names, task_type, complexity, purpose)


def last_resort(router: Any, listed: List[str]) -> List[str]:
    """什么都没有时的兜底：有意不自动参与的那几家里，可用的。保持原先「任选一个可用」的语义。"""
    skip = set(listed)
    return [
        n
        for n in sorted(_opt_in_names())
        if n not in skip and n in router.providers and router.providers[n].is_available()
    ]
