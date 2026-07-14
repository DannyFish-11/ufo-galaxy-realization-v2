"""
core.agentic.strategy — 策略 → Workflow 工厂（Phase B 接线）
==========================================================

把 ExecutionPlanner 选出的执行策略（single / specialized / swarm / parallel / fractal）
映射成一个统一的 :class:`~core.agentic.workflow.Workflow`，并用**真实**的一站式执行器接线：

- ``fractal``                       → ``FractalExecutor(llm_router, factory).run(task, ctx)``
- ``specialized``/``swarm``/``parallel`` → ``TeamManager(...).execute_team_task(task, strategy)``
- ``single``（及其它）              → 单成员团队（``member_count=1``，最接近单 agent 的一站式入口）

这是「策略 → Workflow」唯一知情点。``run_strategy_workflow`` 经 SessionManager 在 plan 的会话上
驱动该 Workflow（带证据链），并把结果压回 ExecutionPlanner 可消费的 dict 形状。

接入由开关 ``GALAXY_UNIFIED_WORKFLOW`` 控制（见 ExecutionPlanner._dispatch）；默认关闭、
旧路径为默认与兜底，因而零默认行为变化。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Callable, Dict, List

from core.agentic import workflow as wf

logger = logging.getLogger("Galaxy.Agentic.Strategy")


# ─────────────────────────── 策略注册表（Phase C：收口去特判） ───────────────────────────
# 「策略 → 如何构造 Workflow」收敛到一张注册表，而非 if/elif 特判链。新增一种 agent 策略
# 只需 register_strategy(name, builder)，无需改动 build_strategy_workflow 或 _dispatch。
# builder 签名：``(llm_router, factory) -> Workflow``。

StrategyBuilder = Callable[[Any, Any], wf.Workflow]
_STRATEGY_BUILDERS: Dict[str, StrategyBuilder] = {}
_DEFAULT_STRATEGY = "single"


def register_strategy(name: str, builder: StrategyBuilder) -> None:
    """注册一种策略的 Workflow 构造器（覆盖同名）。"""
    _STRATEGY_BUILDERS[name.lower()] = builder


def available_strategies() -> List[str]:
    return sorted(_STRATEGY_BUILDERS.keys())


def _agent_factory(llm_router: Any, factory: Any) -> Any:
    if factory is not None:
        return factory
    from core.agent_factory import get_agent_factory

    return get_agent_factory(llm_router)


def _build_fractal(llm_router: Any, factory: Any) -> wf.Workflow:
    from core.fractal_agent import FractalExecutor

    executor = FractalExecutor(llm_router=llm_router, agent_factory=_agent_factory(llm_router, factory))
    return wf.from_fractal_executor(executor, name="fractal")


def _build_team(strategy: str) -> StrategyBuilder:
    def _builder(llm_router: Any, factory: Any) -> wf.Workflow:
        from core.agent_team import TeamManager

        manager = TeamManager(agent_factory=_agent_factory(llm_router, factory))
        return wf.from_team_manager(manager, strategy, name=f"team:{strategy}")

    return _builder


def _build_single(llm_router: Any, factory: Any) -> wf.Workflow:
    # single：用单成员团队作最接近单 agent 的一站式入口。
    from core.agent_team import TeamManager

    manager = TeamManager(agent_factory=_agent_factory(llm_router, factory))
    return wf.from_team_manager(manager, "specialized", member_count=1, name="single")


# 内置策略注册（等价于此前的 if/elif 分支，但现在是数据驱动、可扩展）。
register_strategy("fractal", _build_fractal)
register_strategy("specialized", _build_team("specialized"))
register_strategy("swarm", _build_team("swarm"))
register_strategy("parallel", _build_team("parallel"))
register_strategy("single", _build_single)


def build_strategy_workflow(
    strategy: str,
    *,
    llm_router: Any = None,
    factory: Any = None,
) -> wf.Workflow:
    """按策略构造一个真实接线的 Workflow（查注册表，未知策略回退 single）。"""
    strat = (strategy or _DEFAULT_STRATEGY).lower()
    builder = _STRATEGY_BUILDERS.get(strat) or _STRATEGY_BUILDERS[_DEFAULT_STRATEGY]
    return builder(llm_router, factory)


def _result_to_planner_dict(session: Any, strategy: str) -> Dict[str, Any]:
    """把 Workflow 跑完后的 Session 压成 ExecutionPlanner 可消费的结果 dict。"""
    reply = ""
    try:
        for msg in reversed(getattr(session, "history", []) or []):
            if getattr(msg, "role", "") == "assistant":
                reply = getattr(msg, "content", "") or ""
                break
    except Exception:  # noqa: BLE001
        pass
    structured = {}
    try:
        structured = (getattr(session, "metadata", {}) or {}).get("last_result", {})
    except Exception:  # noqa: BLE001
        structured = {}
    success = True
    if isinstance(structured, dict) and structured.get("error"):
        success = False
    return {
        "success": success,
        "reply": reply,
        "task_result": structured if isinstance(structured, dict) else {"result": structured},
        "chosen_strategy": strategy,
    }


async def run_strategy_workflow(
    *,
    message: str,
    strategy: str,
    session_id: str = "",
    device_id: str = "",
    llm_router: Any = None,
    factory: Any = None,
) -> Dict[str, Any]:
    """经统一 Workflow 层运行一次策略执行，返回 ExecutionPlanner 可消费的结果 dict。

    在 plan 的会话（缺省则用临时会话）上驱动，全程落证据链。任何异常向上抛，
    由调用方（_dispatch）回退到 legacy 路径。
    """
    workflow = build_strategy_workflow(strategy, llm_router=llm_router, factory=factory)
    sid = session_id or f"session_wf_{uuid.uuid4().hex[:10]}"
    runner = wf.WorkflowRunner(workflow)
    session = await runner.run(sid, message, device_id=device_id)
    return _result_to_planner_dict(session, strategy)
