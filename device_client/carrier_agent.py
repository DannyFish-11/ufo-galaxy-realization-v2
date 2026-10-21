"""device_client/carrier_agent.py — 载体上接中心派来的 Agent(跨设备整体方案阶段 5)。

和手机上的桥接 Agent(安卓 ``BridgeAgentRuntime``)说同一套对外 A2A(``core/a2a_link.py``):

* ``agent_dispatch`` → 回 ``agent_installed``(附上这台机器有什么:系统、CPU、内存、GPU、沙箱;能做的动作);
* ``delegate_goal`` → 在本机把整段目标做完,每一步报 ``delegate_progress``,做完报 ``delegate_result``。
  两种做法:目标里给了 ``steps``(一串动作)就按顺序做;只给了一句话,就跑推理加行动的循环
  (``core.local_agent_runtime`` 的 ReAct),**模型经中心**:每一轮用 ``tool_call``(``llm.chat``)
  问中心,钥匙只在中心,载体上不放任何模型钥匙;
* ``recall`` / ``context_return`` → 停下手上的目标、卸下 Agent;
* ``tool_result`` → 交给在等它的那一轮模型调用。

一次只做一个目标(后来的排队);做目标在后台跑,不挡收发(确认、召回照常)。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional

from core import a2a_link as a2a

logger = logging.getLogger("galaxy-device-client.carrier")

BRIDGE_VERSION = "bridge/1"
#: 一轮模型调用最多等中心多久(秒)。
LLM_CALL_TIMEOUT_S = 120.0
MAX_SUMMARY_CHARS = 2000


class CarrierAgent:
    def __init__(
        self,
        executor: Any,
        device_id: Callable[[], str],
        send: Callable[[Dict[str, Any]], Awaitable[None]],
    ) -> None:
        self.executor = executor
        self._device_id = device_id
        self._send = send
        self.link: Optional[a2a.Link] = None
        self.installed = False
        self._goal_task: Optional["asyncio.Task[None]"] = None
        self._goal_queue: List[a2a.Envelope] = []
        self._calls: Dict[str, "asyncio.Future[Dict[str, Any]]"] = {}

    # ── 收 ────────────────────────────────────────────────────────────────────

    async def on_frame(self, frame: Dict[str, Any]) -> None:
        """中心发来一条 ``type="a2a"`` 帧:去重、排序、回确认,按序交给 :meth:`_handle`。"""
        env = a2a.Envelope.from_dict(frame.get("payload"))
        if env is None or env.from_agent != a2a.CENTER_AGENT:
            return
        if env.kind != a2a.Kind.ACK.value and (self.link is None or self.link.session_id != env.session_id):
            # 中心为这台设备开了(新的)会话:链路跟着它走
            self.link = a2a.Link(env.session_id, a2a.agent_id_for(self._device_id()), a2a.CENTER_AGENT)
            self.installed = False
        if self.link is None:
            return
        deliver, ack = self.link.accept(env)
        if ack is not None:
            await self._send(ack.to_aip_frame(self._device_id()))
        for item in deliver:
            try:
                await self._handle(item)
            except Exception as exc:  # noqa: BLE001 — 一条处理失败不该卡住后面的
                logger.warning("carrier: %s failed: %s", item.kind, exc, exc_info=True)

    async def resend_unacked(self) -> int:
        """(重新)登记之后补发中心还没确认的。"""
        if self.link is None:
            return 0
        pending = self.link.unacked()
        for env in pending:
            await self._send(env.to_aip_frame(self._device_id()))
        return len(pending)

    async def _emit(
        self, kind: a2a.Kind, body: Dict[str, Any], *, task_id: str = "", trace_id: str = "", ack_required: bool = True
    ) -> None:
        if self.link is None:
            return
        env = self.link.make(kind, body, task_id=task_id, trace_id=trace_id, ack_required=ack_required)
        await self._send(env.to_aip_frame(self._device_id()))

    async def _handle(self, env: a2a.Envelope) -> None:
        kind = env.kind
        if kind == a2a.Kind.AGENT_DISPATCH.value:
            resumed, self.installed = self.installed, True
            info = self.executor.describe()
            await self._emit(
                a2a.Kind.AGENT_INSTALLED,
                {
                    "runtime": "carrier",
                    "bridge_version": BRIDGE_VERSION,
                    "resumed": resumed,
                    "host": info.get("host", {}),
                    "actions": info.get("actions", []),
                },
                trace_id=env.trace_id,
            )
        elif kind == a2a.Kind.DELEGATE_GOAL.value:
            self._goal_queue.append(env)
            self._pump()
        elif kind == a2a.Kind.TOOL_RESULT.value:
            fut = self._calls.pop(str(env.body.get("call_id") or ""), None)
            if fut is not None and not fut.done():
                fut.set_result(dict(env.body))
        elif kind in (a2a.Kind.RECALL.value, a2a.Kind.CONTEXT_RETURN.value):
            self.installed = False
            self._goal_queue.clear()
            if self._goal_task is not None and not self._goal_task.done():
                self._goal_task.cancel()
        elif kind == a2a.Kind.TOOL_CALL.value:
            await self._emit(
                a2a.Kind.TOOL_RESULT,
                {"call_id": env.body.get("call_id", env.msg_id), "success": False, "error": "单个动作走 command 帧"},
                task_id=env.task_id,
                trace_id=env.trace_id,
            )

    # ── 做目标 ─────────────────────────────────────────────────────────────────

    def _pump(self) -> None:
        if (self._goal_task is not None and not self._goal_task.done()) or not self._goal_queue:
            return
        env = self._goal_queue.pop(0)
        self._goal_task = asyncio.get_running_loop().create_task(self._run_goal(env))
        self._goal_task.add_done_callback(lambda _t: self._pump())

    async def _run_goal(self, env: a2a.Envelope) -> None:
        try:
            result = await self._do_goal(env)
        except asyncio.CancelledError:
            await self._emit(
                a2a.Kind.DELEGATE_RESULT,
                {"success": False, "error": "中心收回了 Agent,这个目标没做完"},
                task_id=env.task_id,
                trace_id=env.trace_id,
            )
            raise
        except Exception as exc:  # noqa: BLE001 — 做目标出错作为结果报回去,不能让中心干等
            logger.warning("carrier goal %s failed: %s", env.task_id, exc, exc_info=True)
            result = {"success": False, "error": str(exc)}
        logger.info("carrier goal %s done: success=%s", env.task_id, result.get("success"))
        await self._emit(a2a.Kind.DELEGATE_RESULT, result, task_id=env.task_id, trace_id=env.trace_id)

    async def _tool(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return await asyncio.get_running_loop().run_in_executor(None, self.executor.execute, action, params)

    def _tools(self) -> List[Dict[str, Any]]:
        schemas = getattr(self.executor, "capability_schemas", None)
        specs = schemas() if callable(schemas) else [{"action": a} for a in self.executor.supported_actions()]
        return [
            {
                "name": s["action"],
                "description": s.get("description") or s["action"],
                "parameters": s.get("parameters") or {"type": "object", "properties": {}},
            }
            for s in specs
        ]

    async def _do_goal(self, env: a2a.Envelope) -> Dict[str, Any]:
        from core.local_agent_runtime import LocalAgentRuntime

        body = env.body
        goal = str(body.get("goal") or "").strip()
        steps = [s for s in body.get("steps") or [] if isinstance(s, dict)]
        if not goal and not steps:
            return {"success": False, "error": "需要 goal 或 steps"}

        async def report(_manifest_id: str, step: Dict[str, Any]) -> None:
            if step.get("action") and not step.get("observation"):
                return  # 动手前那一次不报,做完带着结果报
            await self._emit(
                a2a.Kind.DELEGATE_PROGRESS,
                {k: step.get(k) for k in ("step_id", "action", "success", "observation", "thought") if k in step},
                task_id=env.task_id,
                trace_id=env.trace_id,
                ack_required=False,
            )

        manifest: Dict[str, Any] = {"manifest_id": env.task_id or uuid.uuid4().hex, "tools": self._tools()}
        if steps:
            manifest["execution_mode"] = "sequential"
            manifest["tasks"] = [
                {"action": str(s.get("action") or ""), "params": dict(s.get("params") or {})} for s in steps
            ]
        else:
            constraints = [str(c) for c in body.get("constraints") or []]
            manifest["execution_mode"] = "react"
            manifest["system_prompt"] = (
                "你是中心智能体派到这台机器上的 Agent。用给你的工具在本机把目标做完;代码只经 run_code 在沙箱里跑。"
                "做完用一两句话说清做了什么、结果在哪。" + (" 要求:" + ";".join(constraints) if constraints else "")
            )
            manifest["tasks"] = [{"instruction": goal}]
        runtime = LocalAgentRuntime(tool_executor=self._tool, status_reporter=report, llm_chat=self._llm_chat)
        result = await runtime.execute(manifest)
        summary = result.final_output if result.success else (result.error or result.final_output or "没做成")
        out: Dict[str, Any] = {
            "success": bool(result.success),
            "summary": str(summary)[:MAX_SUMMARY_CHARS],
            "steps": result.steps[-10:],
        }
        if not result.success:
            out["error"] = result.error or str(summary)
        return out

    async def _llm_chat(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        """推理加行动的每一轮问中心的模型(钥匙只在中心):``tool_call``(``llm.chat``)→ 等 ``tool_result``。"""
        call_id = uuid.uuid4().hex
        fut: "asyncio.Future[Dict[str, Any]]" = asyncio.get_running_loop().create_future()
        self._calls[call_id] = fut
        await self._emit(
            a2a.Kind.TOOL_CALL, {"call_id": call_id, "tool": "llm.chat", "messages": messages, "tools": tools}
        )
        try:
            res = await asyncio.wait_for(fut, timeout=LLM_CALL_TIMEOUT_S)
        except asyncio.TimeoutError:
            raise RuntimeError(f"中心的模型 {LLM_CALL_TIMEOUT_S:.0f} 秒没答") from None
        finally:
            self._calls.pop(call_id, None)
        if not res.get("success"):
            raise RuntimeError(f"中心的模型没答上:{res.get('error') or '原因不明'}")
        return {"content": str(res.get("content") or ""), "tool_calls": res.get("tool_calls") or None}
