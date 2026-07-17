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


async def _default_act(action: str, params: Dict[str, Any], node_id: str) -> Dict[str, Any]:
    """经规范执行器派发一步动作到桌面操作节点。"""
    from core.node_invocation import InvocationSource, invoke_node

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
    """

    def __init__(
        self,
        router: Any = None,
        perceive_fn: Optional[Callable[[], Awaitable[Optional[str]]]] = None,
        act_fn: Optional[Callable[[str, Dict[str, Any], str], Awaitable[Dict[str, Any]]]] = None,
        node_id: str = _DEFAULT_NODE,
    ) -> None:
        self._router = router
        self._perceive = perceive_fn or _default_perceive
        self._act = act_fn or _default_act
        self._node_id = node_id

    def _get_router(self):
        if self._router is None:
            from core.multi_llm_router import get_llm_router

            self._router = get_llm_router()
        return self._router

    async def _plan_step(self, instruction: str, history: List[StepRecord], screen_b64: str) -> Optional[Dict]:
        """一步规划:任务 + 步骤史 + 截图 → 动作 JSON。"""
        hist_lines = [
            f"步骤{r.index}: {r.action}({json.dumps(r.params, ensure_ascii=False)})"
            f" → {'成功' if r.success else '失败:' + r.error} | {r.reason}"
            for r in history[-8:]  # 只带最近 8 步,防上下文膨胀
        ]
        hist_text = "\n".join(hist_lines) if hist_lines else "(尚未执行任何步骤)"
        user_content = [
            {
                "type": "text",
                "text": f"任务:{instruction}\n\n已执行步骤:\n{hist_text}\n\n当前屏幕见截图。请给出下一步动作 JSON。",
            },
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{screen_b64}"}},
        ]
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
        """跑完整个任务闭环,返回 {success, stop_reason, message, steps}。"""
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
            planned = await self._plan_step(instruction, steps, screen)
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
