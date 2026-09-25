"""core/meta/supply.py — 元层自己的模型供给通道，与 RSI API 空位（设计规格 §04H）。

路由是不是一套：是一套
======================
``UnifiedLLMRouter`` 与 ``MultiLLMRouter`` 各是一个进程单例，前者的执行后端就是后者 —— 两个类，
一条供给；策略也只有一份 ``config/llm_routing_policy.yaml``。区分维度只有 task_type 与 role，
**没有「谁在调用」这一维**：遥测桶与熔断器的键都只有 provider 名。

所以元层不能跑在同一个实例上
============================
理由不是洁癖，是一条反向控制通路：元层的提案调用（长上下文、量大、失败率天然更高）会把某家
provider 的成功率 / 延迟拉下去 → SLO 判红 → Agent 的路由被改掉了。这等于绕过了 G10「元层不得
进热路径」—— 不是通过 import，是通过统计量，而且没有任何一行代码是错的。

做法一句话：**事实共享，决策隔离。** provider 注册表与 ``core/model_catalog.py`` 的能力表两边
共享（都只读，是事实）；熔断器、调用历史、遥测各一份。成本很低 —— ``MultiLLMRouter.__init__``
只读配置与环境变量，不做网络探测。

RSI API 空位
============
RSI API 尚未出现，URL 与协议形状都未定。按冻结守则 R6.1「新协议类型必须有对应消费者；表示层
槽位只记意图、不落代码」，这里**只登记意图**：:data:`RSI_API_SLOT` 把与形状无关的部分定死，
与形状有关的部分标 ``None``（unknown，不猜）。

这一格可能根本不用建：面板上的「我的模型服务」（``core/routes/user_providers.py``）本来就是
「不改仓库就能加一家」—— 若 RSI API 最终是 OpenAI 兼容的 chat 端点，就是零代码；若不兼容，
那时才谈适配器，且仍挂在 :func:`meta_llm_router` 上。
"""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional

META_SUPPLY_IS_ISOLATED: str = (
    "META_SUPPLY::DECISIONS_ISOLATED: the meta layer calls models through its own "
    "MultiLLMRouter instance — separate circuit breakers, call history and telemetry — "
    "so proposal traffic can never degrade the routing that serves requests.  Facts "
    "(provider registry, model catalog) are shared read-only."
)

#: RSI API 槽位：只记意图，不落实现（R6.1）。``None`` 表示形状未定、不猜。
RSI_API_SLOT: Dict[str, Any] = {
    "status": "reserved",
    "consumer": "core.meta 算子的提案调用",
    "attach_to": "core.meta.supply.meta_llm_router（不是 get_unified_llm_router）",
    "config_entry": "core/routes/user_providers.py",
    "when_unconfigured": "skip",
    "secret_storage": "只存 vault 键名，值进 CredentialVault",
    "egress": "新地址须显式进 GALAXY_EGRESS_ALLOW（core/egress_guard.py）",
    "slot_id_rule": "槽位 id 不得与直连厂商重名（core/endpoint_admission.py）",
    "self_check_states": ("live", "declared", "unverified"),
    "url": None,
    "protocol": None,
    "auth": None,
}

_lock = threading.Lock()
_meta_router: Optional[Any] = None


def meta_llm_router() -> Any:
    """元层专用的路由实例。**永远不是**请求路径上的那个单例。"""
    global _meta_router
    with _lock:
        if _meta_router is None:
            from core.multi_llm_router import MultiLLMRouter

            _meta_router = MultiLLMRouter()
        return _meta_router


def meta_supply_status() -> Dict[str, Any]:
    """给 ``scripts/meta_rsi.py status`` 看：元层供给通道现在有哪些 provider、RSI 槽位是什么状态。"""
    router = meta_llm_router()
    return {
        "isolated": True,
        "providers": sorted(getattr(router, "providers", {}) or {}),
        "rsi_api_slot": {k: v for k, v in RSI_API_SLOT.items() if k in ("status", "url", "protocol", "auth")},
    }


__all__ = ["META_SUPPLY_IS_ISOLATED", "RSI_API_SLOT", "meta_llm_router", "meta_supply_status"]
