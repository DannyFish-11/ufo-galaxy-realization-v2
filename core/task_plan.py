"""core/task_plan.py — 多步计划(跨设备整体方案阶段 4)。

模型写出步骤、依赖、每步用哪台设备 → 分层执行 → 汇总给模型。智能体的工具名是 ``devices__plan``
(和设备工具同一族;方案里叫 ``tasks__plan``)。

- 每一步要么是一个动作(走 ``devices__invoke``:规范派发 → 设备),要么是一整段目标(走
  ``devices__delegate``:交给装了桥接 Agent 的设备自己规划)。
- 执行用现成的 ConstellationRuntime 分层执行(就绪驱动:依赖都成功了才轮到,同一轮并行);拆解和挑设备
  不再由它自己做 —— 用模型写的计划。它的自动重排(DAGEvolver)不开:一步失败的原因回到模型,由模型决定
  重试、换设备还是问人(自动重做一个发消息、下单的动作会重复动手)。
- 同一台设备串行(每台设备一个队列,:mod:`core.device_queue`),不同设备同时下发不超过
  ``GALAXY_MULTI_DEVICE_DISPATCH_LIMIT``。
- 随时写盘(``$GALAXY_DATA_DIR/task_plans.json``)。重启后只接着做没做完、且依赖都成功了的步骤;
  崩溃时正在做的那一步结果不明,不自动重做(免得重复动手),依赖它的步骤也不做;做完把结果记进发起计划的
  会话,智能体下一轮就看得到。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.TaskPlan")

MAX_STEPS = 20
MAX_RESULT_CHARS = 600
RESUME_DEVICE_WAIT_S = 300.0
_STATE_FILE = "task_plans.json"
_KEEP_FINISHED = 10

PENDING, RUNNING, SUCCESS, FAILED, SKIPPED, UNKNOWN = "pending", "running", "success", "failed", "skipped", "unknown"
_DONE = {SUCCESS, FAILED, SKIPPED, UNKNOWN}

_lock = threading.Lock()
_tasks: set = set()


# ── 计划长什么样 ─────────────────────────────────────────────────────────────


def parse_plan(args: Dict[str, Any], session_id: str = "") -> Tuple[Optional[Dict[str, Any]], str]:
    """把模型给的参数整理成一份计划;不对就返回 ``(None, 哪里不对)``。"""
    raw = args.get("steps")
    if not isinstance(raw, list) or not raw:
        return None, "需要 steps:至少一步"
    if len(raw) > MAX_STEPS:
        return None, f"一份计划最多 {MAX_STEPS} 步;拆成几份,前一份的结果出来再写下一份"
    steps: List[Dict[str, Any]] = []
    seen: set = set()
    for i, s in enumerate(raw):
        if not isinstance(s, dict):
            return None, f"第 {i + 1} 步不是一个对象"
        sid = str(s.get("id") or f"s{i + 1}").strip()
        if sid in seen:
            return None, f"步骤 id 重复:{sid}"
        seen.add(sid)
        device_id = str(s.get("device_id") or "").strip()
        action = str(s.get("action") or "").strip()
        goal = str(s.get("goal") or "").strip()
        if not device_id:
            return None, f"步骤 {sid} 没写 device_id(用哪台设备)"
        if bool(action) == bool(goal):
            return None, f"步骤 {sid} 要么写 action(一个动作),要么写 goal(一整段目标),只能二选一"
        deps = [str(d) for d in (s.get("depends_on") or [])]
        try:
            timeout = float(s.get("timeout_s") or (180.0 if goal else 60.0))
        except (TypeError, ValueError):
            return None, f"步骤 {sid} 的 timeout_s 不是数"
        steps.append(
            {
                "id": sid,
                "device_id": device_id,
                "action": action,
                "params": dict(s.get("params") or {}) if action else {},
                "goal": goal,
                "constraints": [str(c) for c in (s.get("constraints") or [])] if goal else [],
                "depends_on": deps,
                "timeout_s": max(5.0, min(timeout, 600.0)),
                "status": PENDING,
                "result": None,
                "error": "",
            }
        )
    ids = {s["id"] for s in steps}
    for s in steps:
        unknown = [d for d in s["depends_on"] if d not in ids]
        if unknown:
            return None, f"步骤 {s['id']} 依赖的 {unknown} 不在这份计划里"
    plan = {
        "plan_id": f"plan_{uuid.uuid4().hex[:12]}",
        "goal": str(args.get("goal") or "").strip(),
        "session_id": session_id,
        "created_at": time.time(),
        "finished_at": 0.0,
        "resumed": False,
        "steps": steps,
    }
    try:
        _decomposition(plan)  # 有环在这里就报
    except ValueError as exc:
        return None, f"步骤之间的依赖有环:{exc}"
    return plan, ""


def _decomposition(plan: Dict[str, Any]):
    from core.orchestrator_engine import DAGScheduler
    from core.schemas.orchestration import SubTask, SubTaskStatus, TaskDecomposition

    status_map = {SUCCESS: SubTaskStatus.SUCCESS, FAILED: SubTaskStatus.FAILED, SKIPPED: SubTaskStatus.SKIPPED}
    subtasks = []
    for s in plan["steps"]:
        subtasks.append(
            SubTask(
                task_id=s["id"],
                name=s["id"],
                description=s["goal"] or s["action"],
                depends_on=list(s["depends_on"]),
                device_id=s["device_id"],
                action=s["action"] or "delegate_goal",
                params=dict(s["params"]),
                timeout_seconds=s["timeout_s"],
                # 结果不明的那一步当作失败:依赖它的不做
                status=status_map.get(
                    s["status"], SubTaskStatus.FAILED if s["status"] == UNKNOWN else SubTaskStatus.PENDING
                ),
            )
        )
    layers, task_map = DAGScheduler.build_and_validate(subtasks)
    return TaskDecomposition(goal=plan["goal"] or "multi-step plan", subtasks=subtasks), layers, task_map


# ── 写盘 ─────────────────────────────────────────────────────────────────────


def _path() -> str:
    from core.data_paths import data_path

    return data_path(_STATE_FILE)


def _load_all() -> Dict[str, Any]:
    try:
        with open(_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(plan: Dict[str, Any]) -> None:
    """把这份计划的此刻写盘(原子替换);做完的只留最近几份供诊断。"""
    with _lock:
        data = _load_all()
        active = data.setdefault("active", {})
        finished = data.setdefault("finished", [])
        if plan.get("finished_at"):
            active.pop(plan["plan_id"], None)
            finished = [p for p in finished if p.get("plan_id") != plan["plan_id"]] + [plan]
            data["finished"] = finished[-_KEEP_FINISHED:]
        else:
            active[plan["plan_id"]] = plan
        path = _path()
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False)
            os.replace(tmp, path)
        except OSError as exc:
            logger.warning("task plan: 写盘失败 %s: %s", path, exc)
            try:
                os.unlink(tmp)
            except OSError:
                pass


def plan_state(plan_id: str) -> Optional[Dict[str, Any]]:
    """一份计划此刻的样子(进行中的或最近做完的);诊断与测试看。"""
    data = _load_all()
    if plan_id in data.get("active", {}):
        return data["active"][plan_id]
    return next((p for p in data.get("finished", []) if p.get("plan_id") == plan_id), None)


# ── 执行 ─────────────────────────────────────────────────────────────────────


class _StepRunner:
    """ConstellationRuntime 分层执行里「做一个子任务」的那一环:每步交给设备工具。"""

    def __init__(self, plan: Dict[str, Any]) -> None:
        from core.device_queue import dispatch_limit

        self.plan = plan
        self.steps = {s["id"]: s for s in plan["steps"]}
        self._limit = asyncio.Semaphore(dispatch_limit())

    async def _execute_subtask(self, task: Any, orch_request: Any) -> Dict[str, Any]:
        from core.schemas.orchestration import SubTaskStatus

        step = self.steps[task.task_id]
        task.status = SubTaskStatus.RUNNING
        try:
            res = await self._run(step)
        except Exception as exc:  # noqa: BLE001 — 一步出错作为这一步的结果,不炸掉整份计划
            res = {"success": False, "error": str(exc)}
        ok = bool(res.get("success"))
        step["status"], step["finished_at"] = (SUCCESS if ok else FAILED), time.time()
        step["result"] = _brief(res)
        step["error"] = "" if ok else str(res.get("error") or "没有成功,也没说原因")
        task.status = SubTaskStatus.SUCCESS if ok else SubTaskStatus.FAILED
        task.result, task.error, task.completed_at = res, step["error"], step["finished_at"]
        _save(self.plan)
        return res

    async def _run(self, step: Dict[str, Any]) -> Dict[str, Any]:
        """排进这台设备的队列;**轮到它、真开始做时**才占一个同时下发的名额、记「正在做」。

        排着队的那一步还没动过设备,崩溃后要接着做;只有真开始做了的那一步才算结果不明。名额在轮到之后才占:
        排在一台忙设备后面的几步不占名额,不挡别的设备上能做的步骤。
        """
        from core.device_queue import run_on_device

        async def job() -> Dict[str, Any]:
            async with self._limit:
                step["status"], step["started_at"] = RUNNING, time.time()
                _save(self.plan)
                return await self._dispatch(step)

        return await run_on_device(step["device_id"], job, timeout=step["timeout_s"] + 10)

    async def _dispatch(self, step: Dict[str, Any]) -> Dict[str, Any]:
        # 直接调设备工具的内层(队列已经在上面排过了;再走 dispatch_devices_tool 会在同一个队列里等自己)
        from core import phone_bridge
        from core.device_onboarding import agent_tools

        session_id = self.plan.get("session_id", "")
        if step["goal"]:
            context = {d: self.steps[d].get("result") for d in step["depends_on"]}
            constraints = list(step["constraints"])
            if any(context.values()):
                constraints.append("前面几步的结果:" + json.dumps(context, ensure_ascii=False)[:MAX_RESULT_CHARS])
            return await phone_bridge.delegate(
                step["device_id"],
                step["goal"],
                constraints=constraints,
                timeout=step["timeout_s"],
                session_id=session_id,
            )
        return await agent_tools._invoke(
            {"device_id": step["device_id"], "action": step["action"], "params": step["params"]}, session_id
        )


def _brief(res: Dict[str, Any]) -> Any:
    """一步的结果进模型上下文前截短。"""
    keep = {k: v for k, v in res.items() if k not in ("success", "progress")}
    text = json.dumps(keep, ensure_ascii=False, default=str)
    return keep if len(text) <= MAX_RESULT_CHARS else text[:MAX_RESULT_CHARS] + "…"


async def _execute(plan: Dict[str, Any]) -> Dict[str, Any]:
    from core.constellation_runtime import ConstellationRuntime
    from core.schemas.orchestration import OrchestrationRequest

    decomposition, layers, task_map = _decomposition(plan)
    runtime = ConstellationRuntime(enable_dag_evolution=False)
    runner = _StepRunner(plan)
    await runtime._execute_layers(
        layers=layers,
        task_map=task_map,
        decomposition=decomposition,
        orch_request=OrchestrationRequest(
            task_description=plan["goal"] or "multi-step plan", session_id=plan.get("session_id", "")
        ),
        orchestrator=runner,
        trace_id=plan["plan_id"],
        request_id=plan["plan_id"],
        ledger=runtime._get_audit_ledger(),
    )
    by_id = {s["id"]: s for s in plan["steps"]}
    for s in plan["steps"]:
        if s["status"] in (PENDING, RUNNING):
            blockers = [d for d in s["depends_on"] if by_id[d]["status"] != SUCCESS]
            s["status"] = SKIPPED
            s["error"] = f"前置步骤 {', '.join(blockers)} 没成功,这一步没做" if blockers else "没有轮到"
    plan["finished_at"] = time.time()
    _save(plan)
    return _report(plan)


def _report(plan: Dict[str, Any]) -> Dict[str, Any]:
    steps = plan["steps"]
    done = sum(1 for s in steps if s["status"] == SUCCESS)
    out = {
        "success": done == len(steps),
        "plan_id": plan["plan_id"],
        "summary": f"{done}/{len(steps)} 步成功",
        "steps": [
            {
                "id": s["id"],
                "device_id": s["device_id"],
                "status": s["status"],
                **({"result": s["result"]} if s["status"] == SUCCESS else {"error": s["error"]}),
            }
            for s in steps
        ],
    }
    if done < len(steps):
        out["next"] = "看每一步的 error 再决定:只把没成功的步骤(和依赖它们的)重新交一份计划、换一台设备,或者问人"
    return out


def _graph_node(plan: Dict[str, Any]) -> str:
    """整份计划在任务流程图里记一个节点(步骤与依赖在元数据里);单步下发各自也有节点。"""
    from core.device_onboarding.device_card import record_dispatch

    return record_dispatch(
        "",
        "devices__plan",
        plan.get("session_id", ""),
        metadata={
            "kind": "plan",
            "plan_id": plan["plan_id"],
            "steps": [{k: s[k] for k in ("id", "device_id", "depends_on")} for s in plan["steps"]],
        },
    )


async def run_plan(args: Dict[str, Any], session_id: str = "") -> Dict[str, Any]:
    """``devices__plan`` 的执行端。"""
    from core.device_onboarding.device_card import record_result

    if args.get("plan_id") and not args.get("steps"):
        # 只给 plan_id:查一份进行中 / 重启后接着做 / 最近做完的计划此刻怎么样
        state = plan_state(str(args["plan_id"]))
        if state is None:
            return {"success": False, "error": f"没有这份计划:{args['plan_id']}(做完的只留最近 {_KEEP_FINISHED} 份)"}
        return {**_report(state), "finished": bool(state.get("finished_at")), "resumed": bool(state.get("resumed"))}
    plan, err = parse_plan(args, session_id)
    if plan is None:
        return {"success": False, "error": err}
    _save(plan)
    node = _graph_node(plan)
    report = await _execute(plan)
    record_result(
        node, report["success"], summary=report["summary"], error="" if report["success"] else report["summary"]
    )
    return report


# ── 重启后接着做 ───────────────────────────────────────────────────────────────


def _online(device_id: str) -> bool:
    try:
        from core.unified.connection_manager import get_unified_connection_manager

        presence = get_unified_connection_manager().channel_presence(device_id)
        return any(bool(rec.get("online")) for rec in presence.values())
    except Exception:  # noqa: BLE001
        return False


async def _resume_one(plan: Dict[str, Any]) -> Dict[str, Any]:
    needed = {s["device_id"] for s in plan["steps"] if s["status"] == PENDING}
    deadline = time.monotonic() + RESUME_DEVICE_WAIT_S
    while needed and time.monotonic() < deadline and not all(_online(d) for d in needed):
        await asyncio.sleep(2.0)
    report = await _execute(plan)
    await _tell_session(plan, report)
    return report


async def _tell_session(plan: Dict[str, Any], report: Dict[str, Any]) -> None:
    if not plan.get("session_id"):
        return
    try:
        from core.session_memory_facade import record_session_turn

        lines = [
            f"{s['id']}({s['device_id']}):{s['status']}" + (f" —— {s['error']}" if s.get("error") else "")
            for s in report["steps"]
        ]
        await record_session_turn(
            conversation_session_id=plan["session_id"],
            role="system",
            content=f"(重启后接着做完了计划「{plan['goal'] or plan['plan_id']}」)"
            + report["summary"]
            + ";"
            + ";".join(lines),
            metadata={"source": "task_plan_resume", "plan_id": plan["plan_id"]},
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("task plan: 续跑结果没能记进会话: %s", exc)


async def resume_unfinished_plans() -> Dict[str, Any]:
    """启动时调:把没做完的计划接着做(在后台,等用到的设备连回来)。"""
    unfinished = list(_load_all().get("active", {}).values())
    resumed: List[str] = []
    for plan in unfinished:
        for s in plan.get("steps", []):
            if s.get("status") == RUNNING:
                s["status"] = UNKNOWN
                s["error"] = "重启时这一步正在做,结果不明;没有自动重做,免得重复动手"
        plan["resumed"] = True
        _save(plan)
        try:
            task = asyncio.get_running_loop().create_task(_resume_one(plan))
        except RuntimeError:
            continue
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
        resumed.append(plan["plan_id"])
    if resumed:
        logger.info("task plan: 重启后接着做 %d 份没做完的计划: %s", len(resumed), resumed)
    return {"resumed_plans": resumed}
