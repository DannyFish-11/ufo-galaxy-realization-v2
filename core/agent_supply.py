"""core/agent_supply.py — 模型与模态供给：Agent Factory 按各家模型的 API 造 Agent（R6）。

要解决什么
==========
工厂不是「没接上模型」—— 它持有 router，甚至能用模型生成 Agent 配置本身。断掉的是
「Agent 的身份」到「用哪个脑」这一段（设计规格 §04A，源码实测的四处断点）：

1. ``get_agent_factory()`` 是单例，只在首次调用时采纳 router —— 无参那个先到，工厂就永久
   ``llm_router=None``，所有任务走 simulated 分支，只留日志、不报失败；
2. ``AgentConfig`` 里没有一格是供给：造出来的 Agent 不携带「我该用哪个脑」；
3. ``_execute_single_task()`` 写死 ``task_type="agent_control"``：三种角色喂给路由的是同一个字面量；
4. 选脑结论（``select_brain_for_role()``）写在 ``TeamMember`` 上，同一个 Agent 被拆成两个
   互不可见的对象。

本模块是需求侧那三格与把两边接上的那一个对象。供给侧一行不动：``core/model_catalog.py``
的五个布尔能力字段、``negotiate()`` 的四维协商、``fit_detail()`` 的显存准入都是现成的事实。

需求是声明，不是供应商（G13）
=============================
``AgentConfig`` 新增三格，取值域全部是枚举：

* ``model_preference``  —— ``"" | dispatch | produce | gatekeep``（沿用 ``core.thinking_locus.ROUTE_TYPES``）
* ``modality_required`` —— ``vision_in / audio_in / audio_out / video_in`` 的子集
* ``locus_constraint``  —— ``"" | local_only | cloud_ok``

一旦 Agent 能点名 provider 或 model tag，``core/model_role_policy.py`` 那条「OpenClawd 是模型
选择的唯一权威」就当场作废。Agent 声明需求，路由满足需求，权威不变。

供不上就报，不静默降级（G14）
=============================
:class:`SupplyDecision` 在 Agent 造出来时算一次、按 ``agent_id`` 绑在 Agent 上。``unmet``
非空时 ``on`` 档拒绝开跑。``admission_provisional`` 是另一件事：供得上，但显存准入的 ok
压在一个没人量过的 KV 单价上 —— 照跑，但把前提一起报出来。

灰度：``GALAXY_AGENT_SUPPLY = off | shadow | on``，默认 ``on``（认不得的取值按 ``off``）
* ``off``    —— 三格不参与任何路径，行为与引入本模块前逐位一致；
* ``shadow`` —— 对**每个** Agent 都算、绑、记，但执行仍走原路径；算出来的与路由实际选中的不一致
  就记 divergence。这是显式打开的诊断档：它会为每个 Agent 调一次选脑（写路由回执）并做显存准入评估；
* ``on``     —— 声明过需求的 Agent 算一次 SupplyDecision，执行时读它：按角色的 task_type、按决定的
  provider/model 调用，``unmet`` 非空拒绝开跑。**三格全空的 Agent 什么都不算**（不调选脑、不写
  路由回执、不探硬件），喂给 router 的入参与 ``off`` 逐字段相同 —— 不声明就什么都不变。所以默认开着
  是安全的。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.AgentSupply")

REPO_ROOT = Path(__file__).resolve().parent.parent

SUPPLY_MODES: Tuple[str, ...] = ("off", "shadow", "on")
DEFAULT_SUPPLY_MODE = "on"
MODEL_PREFERENCES: Tuple[str, ...] = ("", "dispatch", "produce", "gatekeep")
LOCUS_CONSTRAINTS: Tuple[str, ...] = ("", "local_only", "cloud_ok")
MODALITIES: Tuple[str, ...] = ("vision_in", "audio_in", "audio_out", "video_in")

#: Agent 角色 → 路由的角色提示（``multi_llm_router.ROLE_BRAIN_HINTS`` 的键）。
ROLE_TO_BRAIN_ROLE: Dict[str, str] = {
    "coordinator": "coordinator",
    "planner": "planner",
    "analyst": "analyst",
    "executor": "executor",
    "monitor": "worker",
    "communicator": "writer",
    "specialist": "coder",
}

#: 显式声明的偏好压过角色映射：偏好说的是「这一格要哪一类脑」。
PREFERENCE_TO_BRAIN_ROLE: Dict[str, str] = {"dispatch": "executor", "produce": "writer", "gatekeep": "reviewer"}

DIVERGENCE_LOG = REPO_ROOT / "runtime" / "agent_supply" / "divergences.jsonl"


def agent_supply_mode() -> str:
    raw = (os.environ.get("GALAXY_AGENT_SUPPLY", DEFAULT_SUPPLY_MODE) or DEFAULT_SUPPLY_MODE).strip().lower()
    return raw if raw in SUPPLY_MODES else "off"  # 认不得的取值按 off —— 宁可不算，不可误算


# ---------------------------------------------------------------------------
# 需求声明（G13）
# ---------------------------------------------------------------------------


def declaration_violations(model_preference: Any, modality_required: Any, locus_constraint: Any) -> List[str]:
    """三格取值是否都在枚举里。点名供应商或模型 tag 的一律越出枚举，因此一并被拦下。"""
    problems: List[str] = []
    if model_preference not in MODEL_PREFERENCES:
        problems.append(f"model_preference={model_preference!r} 不在 {MODEL_PREFERENCES} 内 —— 声明需求，不点名供应商")
    if locus_constraint not in LOCUS_CONSTRAINTS:
        problems.append(f"locus_constraint={locus_constraint!r} 不在 {LOCUS_CONSTRAINTS} 内")
    if not isinstance(modality_required, (tuple, list)) or any(m not in MODALITIES for m in modality_required):
        problems.append(f"modality_required={modality_required!r} 必须是 {MODALITIES} 的子集")
    return problems


def sanitize_declaration(raw: Dict[str, Any]) -> Dict[str, Any]:
    """LLM 生成的 Agent 配置里的三格：合法的原样保留，不合法的清空并告警（不猜）。"""
    pref = raw.get("model_preference", "") or ""
    mods = raw.get("modality_required", ()) or ()
    locus = raw.get("locus_constraint", "") or ""
    out = {
        "model_preference": pref if pref in MODEL_PREFERENCES else "",
        "modality_required": tuple(m for m in mods if m in MODALITIES) if isinstance(mods, (list, tuple)) else (),
        "locus_constraint": locus if locus in LOCUS_CONSTRAINTS else "",
    }
    problems = declaration_violations(pref, list(mods) if isinstance(mods, (list, tuple)) else mods, locus)
    if problems:
        logger.warning("Agent 供给声明不合法，已清空越界的格: %s", "；".join(problems))
    return out


# ---------------------------------------------------------------------------
# SupplyDecision
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SupplyDecision:
    agent_id: str
    brain_role: str
    provider: str
    model: str
    locus: str  # 细粒度：provider 名；回执降成 local/cloud 时只许由细到粗
    is_local: bool
    route_type: str  # dispatch | produce | gatekeep
    task_type: str  # 喂给路由的 task_type（按角色，不再是同一个字面量）
    modality_plan: Dict[str, Any] = field(default_factory=dict)
    unmet: Tuple[str, ...] = ()
    admission_provisional: bool = False
    reason: str = ""
    mode: str = "off"
    decided_at: float = 0.0
    declared: bool = False  # 三格里至少声明了一格；全空＝今天的行为（验收 ④）

    @property
    def runnable(self) -> bool:
        return not self.unmet

    @property
    def steers(self) -> bool:
        """这份决定是否真的改变执行：只有 ``on`` 档、且 Agent 声明过需求时。"""
        return self.mode == "on" and self.declared

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "brain_role": self.brain_role,
            "provider": self.provider,
            "model": self.model,
            "locus": self.locus,
            "is_local": self.is_local,
            "route_type": self.route_type,
            "task_type": self.task_type,
            "modality_plan": dict(self.modality_plan),
            "unmet": list(self.unmet),
            "admission_provisional": self.admission_provisional,
            "reason": self.reason,
            "mode": self.mode,
            "decided_at": self.decided_at,
            "declared": self.declared,
        }


def _brain_selector(router: Any) -> Any:
    if router is None:
        return None
    if hasattr(router, "select_brain_for_role"):
        return router
    backend = getattr(router, "get_execution_backend", None)
    return backend() if callable(backend) else None


def _route_type(hint: Dict[str, Any]) -> str:
    # 与 MultiLLMRouter._record_thinking_locus 同一条划分：偏本地＝派活，偏远端＝把关，其余＝产出。
    if hint.get("prefer_local"):
        return "dispatch"
    if hint.get("prefer_remote"):
        return "gatekeep"
    return "produce"


def _admission_provisional(model: str, is_local: bool) -> Tuple[bool, str]:
    """照搬 ``fit_detail()`` 的 provisional，不在这里重算。云端没有显存准入这回事。"""
    if not is_local:
        return False, ""
    try:
        from core.hardware_compute_profiler import get_hardware_profiler
        from core.model_catalog import get_model
        from core.routes.models import fit_detail

        spec = get_model(model)
        if spec is None:
            return True, f"本地模型 {model!r} 不在模型目录里，显存准入无从判定"
        prof = get_hardware_profiler().profile_sync()
        detail = fit_detail(spec, bool(prof.gpus), int(prof.max_model_size_mb))
        return bool(detail.get("provisional")), str(detail.get("fit", ""))
    except Exception as exc:  # noqa: BLE001 — 判不了就如实说判不了
        return True, f"显存准入未能评估：{exc}"


def decide_supply(
    agent_id: str,
    *,
    role: str,
    model_preference: str = "",
    modality_required: Tuple[str, ...] = (),
    locus_constraint: str = "",
    router: Any = None,
    mode: Optional[str] = None,
) -> SupplyDecision:
    """为一个 Agent 一次算定供给。确定性：同样的事实、同样的声明，同样的结论。"""
    from core.multi_llm_router import ROLE_BRAIN_HINTS, is_local_provider

    mode = mode or agent_supply_mode()
    brain_role = PREFERENCE_TO_BRAIN_ROLE.get(model_preference) or ROLE_TO_BRAIN_ROLE.get(role, "worker")
    hint = ROLE_BRAIN_HINTS.get(brain_role, {})
    task_type = getattr(hint.get("task_type"), "value", str(hint.get("task_type") or "general"))
    route_type = _route_type(hint)
    unmet: List[str] = []
    reasons: List[str] = []

    selector = _brain_selector(router)
    provider = model = ""
    is_local = False
    if selector is None:
        unmet.append("brain:no_router")
        reasons.append("工厂没有 router：没有脑可供")
    else:
        decision = selector.select_brain_for_role(brain_role, complexity_score=float(hint.get("min_complexity", 0.5)))
        provider, model = str(decision.provider or ""), str(decision.model or "")
        cfg = getattr(selector, "providers", {}).get(provider)
        is_local = bool(is_local_provider(provider, cfg)) if provider else False
        reasons.append(str(getattr(decision, "reason", "") or ""))
        if not provider or provider == "none":
            unmet.append("brain:unavailable")

    if locus_constraint == "local_only" and provider and not is_local:
        unmet.append("locus:local_only")

    plan_dict: Dict[str, Any] = {}
    if modality_required:
        from core.modality_capability import negotiate

        plan = negotiate(locus=None if is_local or not provider else provider)
        plan_dict = plan.to_dict()
        unmet += [m for m in modality_required if plan.get(m).mode == "unavailable"]

    provisional, fit_note = _admission_provisional(model, is_local) if provider else (False, "")
    if fit_note:
        reasons.append(f"准入：{fit_note}")
    return SupplyDecision(
        agent_id=agent_id,
        brain_role=brain_role,
        provider=provider,
        model=model,
        locus=provider or "unknown",
        is_local=is_local,
        route_type=route_type,
        task_type=task_type,
        modality_plan=plan_dict,
        unmet=tuple(unmet),
        admission_provisional=provisional,
        reason="；".join(r for r in reasons if r),
        mode=mode,
        decided_at=time.time(),
        declared=bool(model_preference or modality_required or locus_constraint),
    )


def supply_for_config(agent_id: str, config: Any, router: Any) -> Optional[SupplyDecision]:
    """工厂在造出 Agent 时调。``off`` 档、以及 ``on`` 档下三格全空的 Agent，返回 ``None``（什么都不算）。"""
    mode = agent_supply_mode()
    if mode == "off":
        return None
    declared = bool(
        getattr(config, "model_preference", "")
        or getattr(config, "modality_required", ())
        or getattr(config, "locus_constraint", "")
    )
    if mode == "on" and not declared:
        return None
    try:
        return decide_supply(
            agent_id,
            role=getattr(getattr(config, "role", None), "value", str(getattr(config, "role", ""))),
            model_preference=getattr(config, "model_preference", ""),
            modality_required=tuple(getattr(config, "modality_required", ()) or ()),
            locus_constraint=getattr(config, "locus_constraint", ""),
            router=router,
            mode=mode,
        )
    except Exception as exc:  # noqa: BLE001 — 供给计算失败时如实记成供不上，不假装算过
        logger.warning("Agent %s 的供给计算失败: %s", agent_id, exc)
        return SupplyDecision(
            agent_id=agent_id,
            brain_role="",
            provider="",
            model="",
            locus="unknown",
            is_local=False,
            route_type="unknown",
            task_type="general",
            unmet=("supply:decision_failed",),
            reason=str(exc),
            mode=mode,
            decided_at=time.time(),
        )


def call_kwargs(supply: Optional[SupplyDecision]) -> Dict[str, Any]:
    """执行时喂给 router 的入参。不 ``steers`` 时（off / shadow / 三格全空）与今天逐字段相同。"""
    if supply is None or not supply.steers:
        return {"task_type": "agent_control"}
    kwargs: Dict[str, Any] = {"task_type": supply.task_type}
    if supply.provider:
        kwargs["provider"] = supply.provider
    if supply.model:
        kwargs["model"] = supply.model
    return kwargs


_divergence_lock = threading.Lock()


def record_divergence(supply: Optional[SupplyDecision], actual_provider: str, actual_model: str = "") -> bool:
    """shadow 档：算出来的与路由实际选中的逐字段比；不一致落一条。返回是否不一致。"""
    if supply is None or supply.mode != "shadow" or not actual_provider:
        return False
    if (supply.provider, supply.model or actual_model) == (actual_provider, actual_model or supply.model):
        return False
    entry = {
        "at": time.time(),
        "agent_id": supply.agent_id,
        "decided": {"provider": supply.provider, "model": supply.model, "task_type": supply.task_type},
        "actual": {"provider": actual_provider, "model": actual_model, "task_type": "agent_control"},
    }
    try:
        with _divergence_lock:
            DIVERGENCE_LOG.parent.mkdir(parents=True, exist_ok=True)
            with DIVERGENCE_LOG.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning("供给 divergence 落盘失败（记在日志里）: %s | %s", exc, entry)
    return True


def unmet_refusal(supply: SupplyDecision, task: Any) -> Dict[str, Any]:
    """G14：供不上就报。结构与工厂的任务结果同形，``status`` 明说是供给问题。"""
    return {
        "task": task,
        "success": False,
        "status": "supply_unmet",
        "error": f"Agent {supply.agent_id} 声明的需求供不上：{', '.join(supply.unmet)}",
        "supply": supply.to_dict(),
    }


__all__ = [
    "LOCUS_CONSTRAINTS",
    "MODALITIES",
    "MODEL_PREFERENCES",
    "PREFERENCE_TO_BRAIN_ROLE",
    "ROLE_TO_BRAIN_ROLE",
    "SUPPLY_MODES",
    "SupplyDecision",
    "agent_supply_mode",
    "call_kwargs",
    "decide_supply",
    "declaration_violations",
    "record_divergence",
    "sanitize_declaration",
    "supply_for_config",
    "unmet_refusal",
]
