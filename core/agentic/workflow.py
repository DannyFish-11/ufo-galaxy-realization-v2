"""
core.agentic.workflow — 统一 Agent/Workflow 编排层
===================================================

把现有三种形状各异的 agent（单 agent ``execute_agent_task(id, dict)->dict``、团队
``execute_team_task(task)->dict``、分形 ``execute(FractalTask)->FractalResult``）统一到
**一个最薄的契约**之上：

    async def forward(session) -> session

借鉴 PyTorch / OpenRath 的「层是变换、数据在 Session 里流动」：
- **Workflow** = 一层变换（≈ nn.Module）。Agent 是其中一种 Workflow。
- **状态不在 agent 里**，而在 Session 里（复用 core.session_manager 的会话 + 证据链 + 血缘）。
- Workflow 可任意嵌套/组合：Sequential（串）、Parallel（并，走 fork/merge）、Selector（动态路由）。

**设计取向（最优做法）**：不重写任何现有 agent，只用「适配器」把它们包成 Workflow；
适配器接受一个 ``invoke`` 协程（``async (task:str) -> 结果``），与具体 agent 的构造解耦，
因而本层可在**无 LLM、无重依赖**下完整单测。真实 agent 的接线在 from_* 构造器里完成。

Session I/O 契约（必须固定，否则各 agent 各读各写会乱）
-------------------------------------------------------
- **读输入**：``session.metadata["pending_task"]``，缺省取 history 里最后一条 user 消息。
- **写输出**：追加一条 assistant 消息（自动落 message 证据 chunk）；结构化结果放
  ``session.metadata["last_result"]``，并落一条 workflow 证据 chunk（actor=工作流名）。
- forward 进出都是**同一个 Session 对象**（来自 SessionManager 的活引用），全程可回放。
"""

from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, List, Optional, Sequence, Union

logger = logging.getLogger("Galaxy.Agentic.Workflow")

# 仅做类型提示，避免与 session_manager 形成导入环（session_manager 不依赖本模块）。
SessionT = Any


# ─────────────────────────── Session I/O 契约 ───────────────────────────

def read_task(session: SessionT) -> str:
    """从 Session 取本次要处理的任务文本（pending_task 优先，否则最后一条 user 消息）。"""
    try:
        meta = getattr(session, "metadata", None) or {}
        pending = meta.get("pending_task")
        if pending:
            return str(pending)
        for msg in reversed(getattr(session, "history", []) or []):
            if getattr(msg, "role", "") == "user":
                return getattr(msg, "content", "") or ""
    except Exception as exc:  # noqa: BLE001
        logger.debug("read_task 失败: %s", exc)
    return ""


def set_task(session: SessionT, task: str) -> None:
    """设置 pending_task（供 Selector 链式改写下一步输入、或外部驱动用）。"""
    try:
        if getattr(session, "metadata", None) is None:
            session.metadata = {}
        session.metadata["pending_task"] = task
    except Exception as exc:  # noqa: BLE001
        logger.debug("set_task 失败: %s", exc)


def _jsonable(obj: Any, _depth: int = 0) -> Any:
    """把任意结果转成可 JSON 序列化、且体量受控的对象（用于证据 payload）。"""
    if _depth > 4:
        return str(obj)[:500]
    if obj is None or isinstance(obj, (bool, int, float)):
        return obj
    if isinstance(obj, str):
        return obj[:2000]
    if hasattr(obj, "to_dict"):
        try:
            return _jsonable(obj.to_dict(), _depth + 1)
        except Exception:  # noqa: BLE001
            return str(obj)[:500]
    if isinstance(obj, dict):
        return {str(k): _jsonable(v, _depth + 1) for k, v in list(obj.items())[:50]}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v, _depth + 1) for v in list(obj)[:50]]
    return str(obj)[:500]


def coerce_text(result: Any) -> str:
    """把各种结果形状（str / dict / TeamResult / FractalResult ...）压成一段展示文本。"""
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    # 带 to_dict 的 dataclass（TeamResult/FractalResult/...）
    src: Any = result
    if hasattr(result, "to_dict"):
        try:
            src = result.to_dict()
        except Exception:  # noqa: BLE001
            src = result
    if isinstance(src, dict):
        for k in ("synthesized", "result", "output", "text", "response",
                  "content", "answer", "analysis", "summary"):
            v = src.get(k)
            if isinstance(v, str) and v.strip():
                return v
        try:
            return json.dumps(_jsonable(src), ensure_ascii=False)[:4000]
        except Exception:  # noqa: BLE001
            return str(src)[:4000]
    # 非 dict 对象：找常见输出属性
    for attr in ("output", "result", "synthesized", "text", "response"):
        v = getattr(src, attr, None)
        if isinstance(v, str) and v.strip():
            return v
    return str(src)[:4000]


async def write_result(
    session: SessionT,
    *,
    text: str = "",
    actor: str = "workflow",
    structured: Any = None,
    emit_message: bool = True,
) -> SessionT:
    """把一层变换的输出写回 Session（assistant 消息 + last_result + 证据 chunk）。

    经 SessionManager 写入，保证持久化/广播/证据链一致；失败不影响 forward 主流程。
    返回同一个 Session 对象（便于链式）。
    """
    try:
        from core.session_manager import get_session_manager, EvidenceKind
        sm = get_session_manager()
        if structured is not None:
            try:
                if getattr(session, "metadata", None) is None:
                    session.metadata = {}
                session.metadata["last_result"] = _jsonable(structured)
            except Exception:  # noqa: BLE001
                pass
        if emit_message and text:
            await sm.add_message(
                getattr(session, "id", ""), "assistant", text,
                metadata={"actor": actor},
            )
        # 工作流步骤证据（与 message chunk 互补：记录哪层变换、结构化结果）
        sm.record_evidence(
            getattr(session, "id", ""), EvidenceKind.NOTE, actor=f"workflow:{actor}",
            payload={"event": "forward", "text": (text or "")[:500],
                     "structured": _jsonable(structured)},
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("write_result 失败(已忽略): %s", exc)
    return session


# ─────────────────────────── Workflow 契约 ───────────────────────────

class Workflow(ABC):
    """一层 Session→Session 变换。子类只需实现 ``forward``。

    ``name`` / ``description`` 用于人读与 Selector 的自我描述路由。
    """

    name: str = "workflow"
    description: str = ""

    @abstractmethod
    async def forward(self, session: SessionT) -> SessionT:  # pragma: no cover - abstract
        ...

    async def __call__(self, session: SessionT) -> SessionT:
        return await self.forward(session)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"<{type(self).__name__} name={self.name!r}>"


class EmptyWorkflow(Workflow):
    """空操作（Selector 的终止态：表示「无需再走任何 Workflow」）。"""

    name = "empty"
    description = "no-op; signals completion"

    async def forward(self, session: SessionT) -> SessionT:
        return session


# ─────────────────────────── Agent 适配器（通用） ───────────────────────────

InvokeFn = Callable[[str], Awaitable[Any]]


class Agent(Workflow):
    """把一个 ``invoke`` 协程包成 Workflow 的通用 Agent 适配器。

    ``invoke(task:str) -> 结果``。结果用 :func:`coerce_text` 压成展示文本写回 Session，
    原始结果作为结构化证据保留。与具体 agent 的构造完全解耦 → 本层可无 LLM 单测。
    """

    def __init__(self, invoke: InvokeFn, *, name: str, description: str = "") -> None:
        self._invoke = invoke
        self.name = name
        self.description = description

    async def forward(self, session: SessionT) -> SessionT:
        task = read_task(session)
        try:
            result = await self._invoke(task)
        except Exception as exc:  # noqa: BLE001 —— 单层失败也要落证据、不崩整条链
            logger.warning("Agent[%s] 执行失败: %s", self.name, exc)
            await write_result(session, text=f"[{self.name} 失败] {exc}",
                               actor=self.name, structured={"error": str(exc)})
            return session
        await write_result(session, text=coerce_text(result),
                           actor=self.name, structured=result)
        return session


# ── 三个真实形状的构造器（在 invoke 闭包里接线，Phase B/C 用） ──

def from_task_agent(factory: Any, agent_id: str, *,
                    name: str = "", description: str = "") -> Agent:
    """单 agent：``factory.execute_agent_task(agent_id, {"task": task})``。"""
    async def _invoke(task: str) -> Any:
        return await factory.execute_agent_task(
            agent_id, {"task": task, "description": task})
    return Agent(_invoke, name=name or f"agent:{agent_id}", description=description)


def from_team(team_manager: Any, strategy: Any = "specialized", *,
              member_count: int = 3, providers: Optional[List[str]] = None,
              name: str = "team", description: str = "") -> Agent:
    """团队（一站式）：``team_manager.execute_team_task(task, strategy, ...)``。"""
    async def _invoke(task: str) -> Any:
        return await team_manager.execute_team_task(
            task, strategy, member_count=member_count, providers=providers)
    return Agent(_invoke, name=name, description=description)


def from_fractal(fractal: Any, *, name: str = "fractal",
                 description: str = "") -> Agent:
    """分形：``fractal.execute(FractalTask(...))``。"""
    async def _invoke(task: str) -> Any:
        from core.fractal_agent import FractalTask
        import uuid as _uuid
        return await fractal.execute(
            FractalTask(id=f"ft_{_uuid.uuid4().hex[:8]}", description=task))
    return Agent(_invoke, name=name, description=description)


# ─────────────────────────── 组合子（本身也是 Workflow） ───────────────────────────

class Sequential(Workflow):
    """串联：前一层的 session 喂下一层（≈ nn.Sequential）。"""

    def __init__(self, steps: Sequence[Workflow], *, name: str = "sequential") -> None:
        self.steps = list(steps)
        self.name = name
        self.description = "run steps in order: " + " → ".join(s.name for s in self.steps)

    async def forward(self, session: SessionT) -> SessionT:
        for step in self.steps:
            session = await step.forward(session)
        return session


MergeStrategy = Union[str, Callable[[SessionT, List[Any]], Any]]


class Parallel(Workflow):
    """并联：每条分支 fork 一个子会话并行跑，再 merge 回父会话（复用 Session 血缘）。

    merge 策略：
    - ``"collect"``（默认）：把各分支 last_result 收进父会话 ``metadata["parallel_results"]``；
    - ``"first_success"``：取第一条 ``error`` 为空的分支结果作为父会话 last_result；
    - 也可传一个 ``fn(parent_session, [branch_results]) -> Any``。
    无 SessionManager（如纯对象测试）时退化为「不 fork、各分支直接跑」。
    """

    def __init__(self, branches: Sequence[Workflow], *,
                 merge: MergeStrategy = "collect", name: str = "parallel") -> None:
        self.branches = list(branches)
        self.merge = merge
        self.name = name
        self.description = "run branches in parallel: " + ", ".join(
            b.name for b in self.branches)

    async def forward(self, session: SessionT) -> SessionT:
        sm = None
        try:
            from core.session_manager import get_session_manager
            sm = get_session_manager()
        except Exception:  # noqa: BLE001
            sm = None

        # 1) 为每条分支准备一个（fork 出来的）子会话
        children: List[Any] = []
        if sm is not None and getattr(session, "id", ""):
            for b in self.branches:
                child = None
                try:
                    child = await sm.fork_session(
                        session.id, branch_label=f"parallel:{b.name}")
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Parallel fork 失败，回退共享会话: %s", exc)
                children.append(child if child is not None else session)
        else:
            children = [session for _ in self.branches]

        # 2) 并行执行
        results = await asyncio.gather(
            *[b.forward(child) for b, child in zip(self.branches, children)],
            return_exceptions=True,
        )

        # 3) 收集各分支结构化结果
        branch_results: List[Any] = []
        for b, child, res in zip(self.branches, children, results):
            if isinstance(res, BaseException):
                branch_results.append({"branch": b.name, "error": str(res)})
                continue
            last = {}
            try:
                last = (getattr(child, "metadata", {}) or {}).get("last_result", {})
            except Exception:  # noqa: BLE001
                last = {}
            branch_results.append({"branch": b.name, "result": last})

        # 4) merge → 写回父会话
        merged: Any
        if callable(self.merge):
            merged = self.merge(session, branch_results)
        elif self.merge == "first_success":
            merged = next(
                (br for br in branch_results
                 if not (isinstance(br.get("result"), dict)
                         and br["result"].get("error")) and "error" not in br),
                branch_results[0] if branch_results else {},
            )
        else:  # "collect"
            merged = {"parallel_results": branch_results}
        await write_result(session, text=coerce_text(merged),
                           actor=self.name, structured=merged)
        return session


SelectFn = Callable[[str, List[Workflow]], Awaitable[int]]


class Selector(Workflow):
    """动态路由：由 ``select_fn`` 在若干自我描述的 Workflow 间选下一个，循环到终止。

    ``select_fn(task, choices) -> int``：返回要跑的下标；返回 <0 表示结束（EmptyWorkflow）。
    带 ``max_steps`` 防止 LLM 路由抖动导致死循环。

    注意：这是**单机内 agent/工作流**之间的编排路由，**不替代**设备级派发权威
    （core.canonical_dispatch_slot_authority / openclawd 执行路径决策）。
    """

    def __init__(self, select_fn: SelectFn, choices: Sequence[Workflow], *,
                 max_steps: int = 8, name: str = "selector") -> None:
        self.select_fn = select_fn
        self.choices = list(choices)
        self.max_steps = max_steps
        self.name = name
        self.description = "dynamically route among: " + ", ".join(
            f"{c.name}({c.description})" for c in self.choices)

    async def forward(self, session: SessionT) -> SessionT:
        for _ in range(self.max_steps):
            task = read_task(session)
            try:
                idx = await self.select_fn(task, self.choices)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Selector select_fn 失败，提前结束: %s", exc)
                break
            if idx is None or idx < 0 or idx >= len(self.choices):
                break
            session = await self.choices[idx].forward(session)
        return session


# ─────────────────────────── 运行入口（Phase B/C 用） ───────────────────────────

class WorkflowRunner:
    """便捷入口：确保会话存在、设置任务、forward、返回会话。

    供调用方一行驱动一条 Workflow，而无需关心 Session I/O 契约细节。
    """

    def __init__(self, workflow: Workflow) -> None:
        self.workflow = workflow

    async def run(self, session_id: str, task: str, *,
                  user_id: str = "", device_id: str = "") -> SessionT:
        from core.session_manager import get_session_manager
        sm = get_session_manager()
        session = await sm.ensure_session(
            session_id, user_id=user_id or f"device::{device_id or 'default'}",
            device_id=device_id)
        set_task(session, task)
        return await self.workflow.forward(session)
