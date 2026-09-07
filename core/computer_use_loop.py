"""core/computer_use_loop.py — 桌面 computer use 自主闭环
===========================================================

补上此前缺失的最后一环。排查结论(真实现状):
  - 感知(看屏幕):DesktopPerceptionStore 的屏幕帧已注入每次请求 ✅
  - 执行(动手):Node_36/45 的 pyautogui/UIA 动作节点真实可用 ✅
  - 【循环】(截屏 → 决策 → 动作 → 再截屏 → 直到完成):不存在——
    grounded_planner 只规划一步,microsoft_ufo_integration.execute_task 是桩,
    多步执行全靠前端反复调 /api/v1/ui/act。本模块补上这个内部自主循环。

循环形状(每步):
  1. 感知:取 DesktopPerceptionStore 里【新鲜】的屏幕帧(桌面覆盖层持续采集);
  2. 规划:把「任务 + 已执行步骤史 + 当前屏幕截图」交给视觉模型(经
     multi_llm_router,本地 Ollama VLM / 云端多模态均可),要求返回单步动作 JSON;
  3. 安全门:动作必须在白名单内;连续 3 次重复同一动作视为死循环,中止;
  4. 执行:经规范执行器 invoke_node 派发到桌面操作节点(缺省 Node_36_UIAWindows,
     动作别名复用 core.routes.ui_act 的 _ACTION_ALIAS,不另起一套);
  5. 静置:等 GALAXY_CU_SETTLE_S(默认 1s)让界面反应,回到 1。
终止:模型宣布 done/fail、步数达 GALAXY_CU_MAX_STEPS(默认 15)、循环检测命中、
或感知不可用(如实报错,绝不闭眼乱点)。

安全边界:
  - GALAXY_COMPUTER_USE=0 可整体关闭(默认开;本循环只能被显式调用——REST 端点
    或模型工具调用,不会自发启动);
  - 动作白名单之外一律拒绝(模型幻觉出的动作不会落到真实键鼠);
  - dry_run=True 只规划第一步不执行,供预览/确认。

依赖注入设计:perceive/plan/act 三个环节都可注入替身,单测不触网、不动真键鼠。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from core.computer_use_memory import ComputerUseEpisodicMemory

logger = logging.getLogger("Galaxy.ComputerUse")

# 动作白名单:模型可用的全部动作(与 Node_36/45 真实能力对齐)。
# done/fail/wait 是循环控制动作,不派发到节点。
ALLOWED_ACTIONS = {
    "click",
    "double_click",
    "right_click",
    "type",
    "press_key",
    "hotkey",
    "scroll",
    "move",
    "drag",
    "wait",
    "done",
    "fail",
}

# 规范动作 → Node_36_UIAWindows 的动作名(执行节点缺省;其它节点的别名映射
# 复用 core.routes.ui_act._ACTION_ALIAS,不另起一套)。
_N36_ACTION = {
    "click": "click",
    "double_click": "double_click",
    "right_click": "right_click",
    "type": "type_text",
    "press_key": "press_key",
    "hotkey": "hotkey",
    "scroll": "scroll",
    "move": "move_mouse",
    "drag": "drag",
}

_DEFAULT_NODE = "Node_36_UIAWindows"

_PLANNER_SYSTEM = """你是桌面操作代理。根据任务、已执行步骤和当前屏幕截图,决定【下一步】动作。

只返回一个 JSON 对象,不要任何其它文字:
{"action": "<动作>", "reason": "<一句话理由>", ...动作参数}

可用动作与参数:
  click / double_click / right_click: {"x": <int>, "y": <int>}
  type: {"text": "<要输入的文字>"}          (先 click 目标输入框再 type)
  press_key: {"key": "<enter|tab|esc|...>"}
  hotkey: {"keys": ["ctrl","s"]}
  scroll: {"clicks": <int,负数向下>, "x": <int>, "y": <int>}
  move: {"x": <int>, "y": <int>}
  drag: {"start_x":..,"start_y":..,"end_x":..,"end_y":..}
  wait: {"seconds": <float≤5>}               (界面还在加载时)
  done: {"result": "<任务完成的结果说明>"}    (任务已完成)
  fail: {"result": "<无法完成的原因>"}        (确认无法完成,如实说明)

规则:每次只做一步;坐标以截图像素为准;看不清/没把握就先 wait 或宣布 fail,
绝不猜坐标乱点;任务完成立即 done,不做多余动作。"""


def computer_use_enabled() -> bool:
    """computer use 闭环是否启用(默认开;GALAXY_COMPUTER_USE=0 关)。"""
    raw = os.environ.get("GALAXY_COMPUTER_USE")
    if raw is None or raw.strip() == "":
        return True
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _max_steps() -> int:
    try:
        return max(1, min(50, int(os.environ.get("GALAXY_CU_MAX_STEPS", "15"))))
    except (TypeError, ValueError):
        return 15


def _settle_s() -> float:
    try:
        return max(0.0, min(10.0, float(os.environ.get("GALAXY_CU_SETTLE_S", "1.0"))))
    except (TypeError, ValueError):
        return 1.0


@dataclass
class StepRecord:
    """一步的完整记录(可观测:面板/日志/测试都用它)。"""

    index: int
    action: str
    params: Dict[str, Any]
    reason: str = ""
    dispatched: bool = False
    success: bool = False
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "action": self.action,
            "params": self.params,
            "reason": self.reason,
            "dispatched": self.dispatched,
            "success": self.success,
            "error": self.error,
        }


def _parse_action_json(text: str) -> Optional[Dict[str, Any]]:
    """模型回复 → 动作 dict。容忍 markdown 代码块/前后杂讯;解析不出返回 None。"""
    if not text:
        return None
    t = text.strip()
    if "```" in t:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", t)
        if m:
            t = m.group(1).strip()
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(t[start : end + 1])
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


async def _default_perceive() -> Optional[str]:
    """取新鲜屏幕帧(base64,不带 data: 前缀)。没有新鲜帧返回 None——绝不闭眼操作。"""
    try:
        from core.perception.desktop_perception_store import get_desktop_perception_store

        snap = get_desktop_perception_store().snapshot_media()
        return snap.get("screen_b64") or None
    except Exception as exc:  # noqa: BLE001
        logger.debug("computer_use 感知读取失败: %s", exc)
        return None


async def _try_arbiter_first(action: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """先走 Windows 执行仲裁器的结构化降级链（System API → UIA → GUI）。

    此前每一步动作都直奔 ``invoke_node(Node_36)`` 的坐标级 GUI 派发,把仲裁器整条
    降级链跳过了 —— 「打开记事本」本来一个 Win32 调用就够,却被规划成点坐标,又慢又脆。

    成功则返回结果；结构级都不行时返回 ``None``,由调用方回落既有节点派发路径 ——
    今天能跑的东西不得因此跑不了。

    第 4 级(VLM)靠**递归保护**排除,不靠这里传空 instruction:仲裁器会把空 instruction
    替换成动作摘要(``instruction or action_summary``),所以传空拦不住它。真正的不变式是
    ``ComputerUseLoop.run()`` 全程置位的那个标记。
    """
    try:
        from core.windows_execution_arbiter import get_windows_arbiter
    except Exception as exc:  # noqa: BLE001
        logger.debug("computer_use 取仲裁器失败,回落节点派发: %s", exc)
        return None
    try:
        result = await get_windows_arbiter().execute(
            action=action,
            params=params,
            device_id="local",
            instruction="",  # 空 instruction：VLM 级即便没被排除也不会再起一个闭环
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("computer_use 仲裁器执行异常,回落节点派发: %s", exc)
        return None
    if getattr(result, "success", False):
        return {"success": True, "error": "", "via": f"arbiter:{getattr(result.final_level, 'value', '')}"}
    return None


async def _default_act(action: str, params: Dict[str, Any], node_id: str) -> Dict[str, Any]:
    """经规范执行器派发一步动作到桌面操作节点。"""
    from core.node_invocation import InvocationSource, invoke_node

    if node_id == _DEFAULT_NODE:
        # 只对本机 Windows 桌面节点走仲裁器：仲裁器的降级链是 Windows 专用的，
        # 派到别的节点（如安卓）上没有意义。
        arbitrated = await _try_arbiter_first(action, params)
        if arbitrated is not None:
            return arbitrated

    node_action = _N36_ACTION.get(action, action)
    if node_id != _DEFAULT_NODE:
        try:
            from core.routes.ui_act import _ACTION_ALIAS

            node_action = _ACTION_ALIAS.get(node_id, {}).get(action, node_action)
        except Exception:  # noqa: BLE001 — 别名表不可用则用规范名
            pass
    result = await invoke_node(
        node_id,
        node_action,
        params,
        invocation_source=InvocationSource.UNKNOWN,
    )
    return {
        "success": bool(getattr(result, "success", False)),
        "error": getattr(result, "error", "") or "",
    }


class ComputerUseLoop:
    """感知 → 规划 → 执行 → 再感知 的自主闭环。

    Args:
        router: 规划用 LLM 路由器(须支持多模态 message);None 则用统一路由器。
        perceive_fn: 替身感知(测试用);返回屏幕帧 base64 或 None。
        act_fn: 替身执行(测试用);签名 (action, params, node_id) -> {success, error}。
        node_id: 桌面操作节点,缺省 Node_36_UIAWindows。
        memory: 情景记忆替身(测试用);None 则用 ComputerUseEpisodicMemory()。
    """

    def __init__(
        self,
        router: Any = None,
        perceive_fn: Optional[Callable[[], Awaitable[Optional[str]]]] = None,
        act_fn: Optional[Callable[[str, Dict[str, Any], str], Awaitable[Dict[str, Any]]]] = None,
        node_id: str = _DEFAULT_NODE,
        memory: Any = None,
    ) -> None:
        self._router = router
        self._perceive = perceive_fn or _default_perceive
        self._act = act_fn or _default_act
        self._node_id = node_id
        # 情景记忆:失败的步骤(带截图)与任务结局写进跨模态记忆,开跑前召回一次。
        # 没配记忆后端时整体是 no-op —— 见 core/computer_use_memory 的说明。
        self._memory = memory if memory is not None else ComputerUseEpisodicMemory()

    def _get_router(self):
        if self._router is None:
            from core.multi_llm_router import get_llm_router

            self._router = get_llm_router()
        return self._router

    async def _plan_step(
        self,
        instruction: str,
        history: List[StepRecord],
        screen_b64: str,
        experience: str = "",
        experience_media: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Dict]:
        """一步规划:任务 + 步骤史 + 截图 (+ 过往经验) → 动作 JSON。

        *experience* 是本次运行开跑前召回的跨模态记忆(见
        :mod:`core.computer_use_memory`)。空串表示「没有可用记忆或没命中」——
        此时**整段都不出现在提示词里**,而不是塞一句「过往经验:(无)」。后者会让
        模型以为系统查过且确实没有,而实际可能是记忆层根本没配。
        """
        hist_lines = [
            f"步骤{r.index}: {r.action}({json.dumps(r.params, ensure_ascii=False)})"
            f" → {'成功' if r.success else '失败:' + r.error} | {r.reason}"
            for r in history[-8:]  # 只带最近 8 步,防上下文膨胀
        ]
        hist_text = "\n".join(hist_lines) if hist_lines else "(尚未执行任何步骤)"
        exp_text = f"\n\n过往经验(来自记忆,可能来自别的运行):\n{experience}" if experience else ""
        user_content = [
            {
                "type": "text",
                "text": (
                    f"任务:{instruction}{exp_text}\n\n已执行步骤:\n{hist_text}"
                    "\n\n当前屏幕见截图。请给出下一步动作 JSON。"
                ),
            },
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{screen_b64}"}},
        ]
        # 过往画面排在**当前屏幕之后**:当前这一张是「现在什么样」,是判断的主体;
        # 召回来的是「上次什么样」,是参照。顺序反了模型容易把旧图当成现状。
        #
        # 这一轮的型号收不收图、这条传输装不装得下,由 core.modality 那个唯一的头
        # 在发出前判(收不了会摘掉并留痕),这里不重复判一遍。
        if experience_media:
            user_content.append({"type": "text", "text": "下面是记忆里与此相关的过往画面/声音(供参照,不是现状):"})
            user_content.extend(experience_media)
        messages = [
            {"role": "system", "content": _PLANNER_SYSTEM},
            {"role": "user", "content": user_content},
        ]
        try:
            resp = await asyncio.wait_for(
                self._get_router().chat(messages=messages, task_type="agent_control", max_tokens=512),
                timeout=60.0,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("computer_use 规划调用失败: %s", exc)
            return None
        return _parse_action_json(getattr(resp, "content", "") or "")

    async def run(self, instruction: str, *, max_steps: Optional[int] = None, dry_run: bool = False) -> Dict[str, Any]:
        """跑完整个任务闭环,返回 {success, stop_reason, message, steps}。

        全程置位仲裁器的递归保护标记：本闭环运行期间，任何回到仲裁器的动作都不得
        再降级到第 4 级(VLM)——那一级又会委托回本闭环，就是无限递归。标记由闭环
        自己持有而不是只在「被仲裁器叫起来」时置位：从 REST 路由/工具直接进来的
        那条路同样会发出动作，同样要防。
        """
        try:
            from core.windows_execution_arbiter import _in_computer_use_loop

            _guard_token = _in_computer_use_loop.set(True)
        except Exception:  # noqa: BLE001 — 仲裁器不可用时闭环照常跑
            _guard_token = None
        try:
            result = await self._run_guarded(instruction, max_steps=max_steps, dry_run=dry_run)
        finally:
            if _guard_token is not None:
                from core.windows_execution_arbiter import _in_computer_use_loop as _cv

                _cv.reset(_guard_token)

        # 结局写在这一层,而不是 _run_guarded 里:那个函数有六个 return 点
        # (disabled / bad_request / no_perception / plan_failed / action_rejected /
        # loop_detected / done|fail / max_steps),逐个补写必然漏掉一个,而漏掉的
        # 多半是最少见、也最值得记的那条退出路径。这里收成一处。
        #
        # dry_run 不写:它没有真的操作任何东西,记进去只会污染召回。
        if not dry_run:
            await self._write_outcome(instruction, result)
        return result

    async def _write_outcome(self, instruction: str, result: Dict[str, Any]) -> None:
        """把一次运行的结局写进情景记忆。

        结局不带截图 —— 它是对整段情景的总结,不对应某一个具体画面;而失败的那些
        步骤已经各自带着自己的截图了。:mod:`core.computer_use_memory` 在没有截图时
        会退回纯文本写入。
        """
        try:
            await self._memory.remember_outcome(
                instruction,
                success=bool(result.get("success")),
                stop_reason=str(result.get("stop_reason", "")),
                message=str(result.get("message", "")),
                step_count=len(result.get("steps") or []),
            )
        except Exception as exc:  # noqa: BLE001 — 记不上结局不该改变任务的返回值
            logger.debug("情景记忆结局写入失败(不影响返回): %s", exc)

    async def _run_guarded(
        self, instruction: str, *, max_steps: Optional[int] = None, dry_run: bool = False
    ) -> Dict[str, Any]:
        """闭环本体。调用方必须是 :meth:`run`（它负责递归保护标记的置位与复位）。"""
        if not computer_use_enabled():
            return {
                "success": False,
                "stop_reason": "disabled",
                "message": "computer use 已被 GALAXY_COMPUTER_USE=0 关闭",
                "steps": [],
            }
        if not (instruction or "").strip():
            return {"success": False, "stop_reason": "bad_request", "message": "instruction 不能为空", "steps": []}

        limit = max_steps if max_steps else _max_steps()
        steps: List[StepRecord] = []
        recent_sig: List[str] = []  # 循环检测:最近动作签名
        t0 = time.monotonic()

        # 开跑前召回一次,整轮复用。不每步召回:那会把提示词撑大,也会把一次运行的
        # 延迟乘上步数,而「过往经验」在一个任务里基本是恒定的。
        # 裸调是不行的:契约是「记忆坏掉不该中断一个正在操作真实键鼠的闭环」,
        # 而这个契约必须在**调用点**成立。默认实现自己吞异常,但注入进来的替身
        # (或将来换的另一个实现)不一定守规矩 —— 这条 try 是最初漏掉的,被
        # tests/test_computer_use_memory.py::test_记忆层抛异常时任务照常完成 抓到。
        experience_media: List[Dict[str, Any]] = []
        try:
            # 一次召回,两样东西:文字进提示词,画面(如果开了回放)作为内容部件带走。
            # 走 ``recall_experience_parts`` 而不是两次召回 —— 召回本身要打向量库,
            # 打两遍既慢又可能因为并发写入拿到两份不一样的结果。
            parts = await self._memory.recall_experience_parts(instruction)
            experience = "\n".join(p.get("text", "") for p in parts if p.get("type") == "text").strip()
            experience_media = [p for p in parts if p.get("type") != "text"]
        except Exception as exc:  # noqa: BLE001
            logger.debug("情景记忆召回失败(不影响任务): %s", exc)
            experience = ""
        if experience:
            logger.info("computer_use 召回到过往经验 %d 条", experience.count("\n") + 1)
        if experience_media:
            logger.info("computer_use 这一轮带回了 %d 项过往画面/声音", len(experience_media))

        for i in range(1, limit + 1):
            # ── 1. 感知 ────────────────────────────────────────────────
            screen = await self._perceive()
            if not screen:
                return {
                    "success": False,
                    "stop_reason": "no_perception",
                    "message": (
                        "拿不到新鲜的屏幕画面——桌面覆盖层的屏幕感知未开启或未授权。"
                        "请在 Electron 弹窗允许屏幕采集(或设 GALAXY_DESKTOP_PERCEPTION=1)后重试。"
                    ),
                    "steps": [s.to_dict() for s in steps],
                }

            # ── 2. 规划 ────────────────────────────────────────────────
            planned = await self._plan_step(instruction, steps, screen, experience, experience_media)
            if not planned:
                return {
                    "success": False,
                    "stop_reason": "plan_failed",
                    "message": "规划模型未返回可解析的动作 JSON",
                    "steps": [s.to_dict() for s in steps],
                }
            action = str(planned.get("action", "")).strip().lower()
            reason = str(planned.get("reason", ""))
            params = {k: v for k, v in planned.items() if k not in ("action", "reason")}

            # ── 3. 安全门 ──────────────────────────────────────────────
            if action not in ALLOWED_ACTIONS:
                rec = StepRecord(i, action, params, reason, error=f"动作不在白名单: {action}")
                steps.append(rec)
                return {
                    "success": False,
                    "stop_reason": "action_rejected",
                    "message": f"模型给出的动作 '{action}' 不在白名单内,已拒绝执行",
                    "steps": [s.to_dict() for s in steps],
                }

            # 终止动作
            if action in ("done", "fail"):
                steps.append(StepRecord(i, action, params, reason, success=(action == "done")))
                return {
                    "success": action == "done",
                    "stop_reason": action,
                    "message": str(params.get("result", "")) or reason,
                    "steps": [s.to_dict() for s in steps],
                    "duration_s": round(time.monotonic() - t0, 1),
                }

            # 循环检测:连续 3 次同一动作+参数 → 判定原地打转
            sig = f"{action}:{json.dumps(params, sort_keys=True, ensure_ascii=False)}"
            recent_sig.append(sig)
            if len(recent_sig) >= 3 and recent_sig[-1] == recent_sig[-2] == recent_sig[-3]:
                steps.append(StepRecord(i, action, params, reason, error="重复动作循环"))
                return {
                    "success": False,
                    "stop_reason": "loop_detected",
                    "message": "连续 3 次重复同一动作,判定为死循环,已中止",
                    "steps": [s.to_dict() for s in steps],
                }

            rec = StepRecord(i, action, params, reason)

            # ── 4. 执行 ────────────────────────────────────────────────
            if dry_run:
                rec.error = "dry_run:未执行"
                steps.append(rec)
                return {
                    "success": True,
                    "stop_reason": "dry_run",
                    "message": f"dry-run:第一步将执行 {action}({params}) — {reason}",
                    "steps": [s.to_dict() for s in steps],
                }

            if action == "wait":
                try:
                    secs = min(5.0, max(0.1, float(params.get("seconds", 1.0))))
                except (TypeError, ValueError):
                    secs = 1.0
                await asyncio.sleep(secs)
                rec.dispatched = True
                rec.success = True
            else:
                out = await self._act(action, params, self._node_id)
                rec.dispatched = True
                rec.success = bool(out.get("success"))
                rec.error = str(out.get("error", ""))
            steps.append(rec)
            logger.info(
                "computer_use 步骤%d: %s %s → %s",
                i,
                action,
                params,
                "ok" if rec.success else f"失败:{rec.error}",
            )

            # 只记失败:顺利走过去的步骤下次也会顺利走过去,而失败那一步才是下次
            # 需要知道的。带上**当时那张截图** —— 让下次能凭「这个界面」召回,
            # 而不只是凭任务描述的字面相似。
            if not rec.success:
                try:
                    await self._memory.remember_failure(
                        instruction,
                        index=i,
                        action=action,
                        params=params,
                        error=rec.error,
                        screen_b64=screen,
                    )
                except Exception as exc:  # noqa: BLE001 — 同上:写不进记忆不该中断操作
                    logger.debug("情景记忆失败步骤写入失败(不影响任务): %s", exc)

            # ── 5. 静置后进入下一轮感知 ────────────────────────────────
            if action != "wait":
                await asyncio.sleep(_settle_s())

        return {
            "success": False,
            "stop_reason": "max_steps",
            "message": f"达到步数上限({limit})任务仍未完成",
            "steps": [s.to_dict() for s in steps],
            "duration_s": round(time.monotonic() - t0, 1),
        }


async def run_computer_use_task(
    instruction: str,
    *,
    max_steps: Optional[int] = None,
    dry_run: bool = False,
    node_id: str = _DEFAULT_NODE,
) -> Dict[str, Any]:
    """模块级便捷入口(REST 路由与 openclawd 工具都调这里)。"""
    loop = ComputerUseLoop(node_id=node_id)
    return await loop.run(instruction, max_steps=max_steps, dry_run=dry_run)


COMPUTER_USE_LOOP_AUTHORITY: str = (
    "COMPUTER_USE_LOOP_V1: core/computer_use_loop.py | "
    "感知(DesktopPerceptionStore 屏幕帧)→规划(视觉模型经统一路由器)→安全门(动作白名单+"
    "循环检测)→执行(invoke_node→Node_36/45)→静置再感知 的自主闭环. "
    "入口: run_computer_use_task() / POST /api/v1/computer-use/task / computer_use__run 工具."
)
