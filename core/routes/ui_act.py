"""core/routes/ui_act.py — 结构化操作入口（AG-UI 活派发,un-orphan 规划器）
=============================================================================

把此前"建好却没人调用"的结构化机制接进**活路径**:一句自然语言意图 + 一张
结构化界面图(UIGraph)→ grounding 规划 → 落成动作 → 经**规范执行器**
(core.node_invocation.invoke_node,带 ui_graph)派发到设备操作节点执行。

  POST /api/v1/ui/act
    body: {
      "instruction": "点发送",              # 必填:自然语言意图
      "ui_graph": {...UIGraph...},          # 必填:结构化界面图(桌面 UIA / 手机 a11y)
      "node_id": "Node_36_UIAWindows",      # 可选:目标操作节点(缺省按平台推断)
      "model_reply": "[2]",                 # 可选:模型看了 to_prompt() 后的回复
      "execute": true,                       # 可选:false=只规划不执行(dry-run)
      "screenshot_b64": "...",               # 可选:没有结构树时走视觉投影;与 ui_graph 同给则融合
      "device_id": "d1",                     # 可选:设备最近上报过界面结构就直接用
      "platform": "android"                  # 可选:决定服务端能不能派发(见下)
    }
    resp: { planned: {...}, dispatched: bool, result?: {...}, grounding_prompt?: str,
            grounding_authority: {...}, vision_note?: str, dispatch_declined?: str }

  GET /api/v1/ui/perception
    界面感知自述:谁说了算、设备有没有在上报屏幕结构、有多少次因过期被挡下。

界面图有三个来源，同一份契约
----------------------------
桌面 UIA(``Node_36_UIAWindows``)、视觉投影(``core.vision_ui_projection``,
截图 → OCR/GUI 元素 → ``UISource.VISION``/``OCR``)、Android 无障碍快照
(``core.android_ui_snapshot``, ``UISource.ANDROID_A11Y``)。结构与视觉同给时
两条腿一起走(``UIGraph.merge``),不是谁 fallback 谁。

谁能派发
--------
``platform`` 归属设备本地时(Android/WearOS)本接口**只规划不派发**,并在
``dispatch_declined`` 里说明——设备端 ``GroundingArbiter`` 已在同一屏上裁决过,
服务端再派一次,两个不同瞬间的判断会打架而现场看不出是谁点的。
判据见 :mod:`core.perception_grounding`。

结构优先命中 → 直接动作;点不准 → needs_model=True + 返回【与截图一同发给模型】的
结构化辅助提示(由前端把它 + 截图交给多模态模型,再带 model_reply 回调本接口)。
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from core.desktop_action_translation import DesktopDispatch
from core.perception_grounding import normalize_platform
from core.schemas.ui_element import UISource

logger = logging.getLogger("Galaxy.Routes.UIAct")

router = APIRouter(prefix="/api/v1/ui", tags=["ui-act"])

# 安全:node_id 来自不可信请求体,会被 invoke_node 用于 os.path.join(nodes_root, id)
# + 目录 fuzzy 匹配。严格白名单形状,杜绝路径穿越(../、绝对路径、分隔符)。
_NODE_ID_RE = re.compile(r"^Node_[A-Za-z0-9_]{1,64}$")


def _safe_node_id(raw: str) -> Optional[str]:
    s = (raw or "").strip()
    return s if _NODE_ID_RE.match(s) else None


# 规范化动作 → 各操作节点的动作名(节点动作名与 UIActionKind 略有出入)。
_ACTION_ALIAS = {
    "Node_36_UIAWindows": {
        "tap": "click",
        "double_tap": "double_click",
        "right_click": "right_click",
        "set_text": "type_text",
        "scroll": "scroll",
        "focus": "focus",
    },
    "Node_45_DesktopAuto": {"tap": "click", "double_tap": "double_click", "set_text": "type", "scroll": "scroll"},
    "Node_33_ADB": {"tap": "tap", "long_press": "tap", "set_text": "input", "swipe": "swipe", "scroll": "swipe"},
    "Node_92_AutoControl": {"tap": "click", "set_text": "input", "scroll": "scroll"},
}


class UIActRequest(BaseModel):
    instruction: str = ""
    ui_graph: Optional[Dict[str, Any]] = None
    node_id: str = ""
    model_reply: Optional[str] = None
    execute: bool = True
    # 没有结构树的平台(Canvas/自绘/第三方封锁无障碍)可以只给截图:走视觉管线
    # 解出控件再投影成同一份契约。见 core/vision_ui_projection.py。
    screenshot_b64: Optional[str] = None
    platform: str = ""
    device_id: str = ""


async def _graph_from_screenshot(req: UIActRequest) -> "tuple[Optional[Dict[str, Any]], str]":
    """截图 → 视觉管线 → UIGraph(dict)。返回 ``(图, 说明)``,失败时图为 None。

    说明恒非空:调用方要能区分"这一屏没识别出控件"与"视觉链路坏了",
    两者都给不出图,但需要的处置完全不同。
    """
    try:
        from core.vision_pipeline import VisionPipeline
        from core.vision_ui_projection import project_vision_result
    except Exception as exc:  # noqa: BLE001 — 视觉链路是可选能力,缺了不该炸掉本路由
        logger.info("ui_act: 视觉链路不可用: %s", exc)
        return None, f"视觉链路不可用({type(exc).__name__})"

    try:
        result = await VisionPipeline().understand(image_base64=req.screenshot_b64, mode="full")
    except Exception as exc:  # noqa: BLE001
        logger.warning("ui_act: 视觉识别失败: %s", exc)
        return None, f"视觉识别失败({type(exc).__name__})"

    graph, note = project_vision_result(result, device_id=req.device_id)
    if graph.root is None:
        return None, note
    return graph.model_dump(mode="json"), note


async def _merge_screenshot_into(req: UIActRequest, structural: Dict[str, Any]) -> "tuple[Dict[str, Any], str]":
    """结构图 + 截图 → 混合图。融合失败一律退回结构图，绝不因此丢掉本来就好的那份。"""
    try:
        from core.schemas.ui_element import UIGraph
        from core.vision_pipeline import VisionPipeline
        from core.vision_ui_projection import project_and_merge

        base = UIGraph.model_validate(structural)
        result = await VisionPipeline().understand(image_base64=req.screenshot_b64, mode="full")
        merged, note = project_and_merge(result, base, device_id=req.device_id)
        return merged.model_dump(mode="json"), note
    except Exception as exc:  # noqa: BLE001 — 融合是增益,不是前提
        logger.info("ui_act: 结构图与截图融合跳过: %s", exc)
        return structural, f"融合跳过({type(exc).__name__}),按纯结构图规划"


@router.get("/perception")
async def ui_perception_state() -> Dict[str, Any]:
    """界面感知的当前状态：谁说了算、设备有没有在上报屏幕结构。

    没有这一处，Stage C 整条链路是不可见的：设备到底传没传、传上来的被不被当成
    "当前界面"、有多少次因为过期被挡下——全都只能靠翻日志猜。
    """
    from core.perception_grounding import describe_grounding_authority

    out: Dict[str, Any] = {"authority": describe_grounding_authority()}
    try:
        from core.android_ui_snapshot import snapshot_store_stats

        out["android_ui_snapshot"] = snapshot_store_stats()
    except Exception as exc:  # noqa: BLE001
        logger.warning("界面快照统计不可读", exc_info=True)
        out["android_ui_snapshot_error"] = type(exc).__name__
    return out


def _node_action(node_id: str, action_value: str) -> str:
    return _ACTION_ALIAS.get(node_id, {}).get(action_value, action_value)


def _resolve_node(graph: Any, node_id: str) -> Optional[Dict[str, Any]]:
    """按 PlannedAction.node_id(树路径)在图里找回那个控件节点。

    找回来是为了拿 ``automation_id`` —— 规划器只带 node_id 和 label,而 node_id 是
    树路径(``"0.3.1"``),不能当身份用。automation_id 在图里,不在规划结果里。
    """
    if graph is None or graph.root is None or not node_id:
        return None
    hits = graph.root.find_all(lambda n: n.node_id == node_id)
    return hits[0].model_dump() if hits else None


def _translate_for_desktop(graph: Any, planned: Any) -> "DesktopDispatch":
    """命中的控件 → 仲裁器动作词。翻译规则在 core.desktop_action_translation。"""
    from core.desktop_action_translation import translate

    node = _resolve_node(graph, planned.node_id)
    coords = tuple(planned.coordinates) if planned.coordinates else None
    return translate(kind=planned.action.value, node=node, coordinates=coords, text=planned.text)


async def _dispatch_via_arbiter(dispatch: Any, req: "UIActRequest", planned: Any) -> Optional[Dict[str, Any]]:
    """经 Windows 执行仲裁器派发。仲裁器不可用时返回 None,由调用方决定回落。

    返回 None 与返回 ``{"dispatched": False}`` 是两件事:前者是"这台机器上没有仲裁器"
    (该回落),后者是"仲裁器跑了但没成"(不该再用别的路径重试一次)。
    """
    try:
        from core.windows_execution_arbiter import get_windows_arbiter
    except Exception as exc:  # noqa: BLE001 — 非 Windows 宿主 import 不进来是预期的
        logger.info("ui_act: 执行仲裁器不可用: %s", exc)
        return None

    try:
        arbiter = get_windows_arbiter()
    except Exception as exc:  # noqa: BLE001
        logger.info("ui_act: 执行仲裁器取不到实例: %s", exc)
        return None

    # 关键一问:这个仲裁器**到底有没有 UIA**。
    #
    # 仲裁器类长在 core/ 里,在 Linux 上一样 import 得进来 —— 只是它的 Level 1/2
    # 适配器都需要 Windows,拿不到时静默为 None,于是 _try_uia 一律 SKIPPED、直接
    # 降到坐标级。服务端与目标 Windows 不同机时就是这个状态。
    #
    # 不问这一句就派过去,结果会是:看起来"走了仲裁器",实际一路降到坐标,而调用方
    # 以为自己按控件身份操作了。宁可回落到既有节点派发并**说出来**,也不要一个
    # 看起来更高级、实际一样盲点的路径。
    #
    # 跨设备该怎么走(把意图交给 CommandRouter 派到对端、由对端 Agent 用它自己的
    # 仲裁器执行)是另一件事,尚未定案 —— 这里只保证不谎报。
    if dispatch.identity_used and not getattr(arbiter, "uia_available", False):
        logger.info("ui_act: 仲裁器没有 UIA 这一级(服务端多半不是目标 Windows),不经它派发")
        return None

    try:
        result = await arbiter.execute(
            action=dispatch.action,
            params=dict(dispatch.params),
            device_id=req.device_id or "local",
            instruction=req.instruction,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("ui_act: 仲裁器派发失败: %s", exc)
        return {"dispatched": False, "error": "dispatch_failed"}

    payload: Dict[str, Any] = {
        "dispatched": True,
        "dispatched_action": f"arbiter.{dispatch.action}",
        "result": result.to_dict() if hasattr(result, "to_dict") else {"success": bool(result)},
    }
    # 仲裁器自己记了"最后落在哪一级",把它抬到响应里 —— 否则调用方看到 success 就
    # 以为走了 UIA,而实际上可能一路降到了坐标甚至 VLM。
    level = getattr(result, "final_level", None) or getattr(result, "level", None)
    if level is not None:
        payload["executor_level"] = getattr(level, "value", str(level))
    return payload


@router.post("/act")
async def ui_act(req: UIActRequest) -> Dict[str, Any]:
    """结构化操作:意图 + 界面图 → 规划 →(可选)派发执行。"""
    from core.grounded_planner import plan as plan_step
    from core.perception_grounding import describe_grounding_authority, server_may_decide
    from core.schemas.ui_element import UIGraph

    ui_graph = req.ui_graph
    graph_note = ""
    if not ui_graph and req.device_id:
        # 设备最近上报过界面结构就直接用(Stage C)。这一步只让服务端**看得见**——
        # Android 仍不派发,下面 POLICY_1 那一段照样拦。
        from core.android_ui_snapshot import latest_graph_for

        stored, stored_note = latest_graph_for(req.device_id)
        if stored is not None:
            ui_graph, graph_note = stored.model_dump(mode="json"), stored_note
        elif stored_note:
            graph_note = stored_note
    if not ui_graph and req.screenshot_b64:
        ui_graph, graph_note = await _graph_from_screenshot(req)
    elif ui_graph and req.screenshot_b64:
        # 两样都给了就两条腿一起走:结构给视觉配精确边界与状态,视觉补结构漏掉的控件
        # (Canvas / 自绘 / 第三方封锁无障碍的界面)。这是 ui_element 契约本身的立场
        # ——不是谁 fallback 谁。
        ui_graph, graph_note = await _merge_screenshot_into(req, ui_graph)
    if not ui_graph:
        return {
            "success": False,
            "error": "ui_graph 必填(结构化界面图);或给 screenshot_b64 走视觉投影",
            **({"vision_note": graph_note} if graph_note else {}),
        }
    try:
        graph = UIGraph.model_validate(ui_graph)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ui_act: UIGraph 解析失败: %s", exc)
        return {"success": False, "error": "ui_graph 解析失败"}

    planned = plan_step(graph, req.instruction, model_reply=req.model_reply)
    out: Dict[str, Any] = {
        "success": True,
        "planned": planned.model_dump(exclude={"grounding_prompt"}),
        "dispatched": False,
        "grounding_authority": describe_grounding_authority(req.platform),
    }
    if graph_note:
        out["vision_note"] = graph_note

    # POLICY_1:归属设备本地的平台,服务端**只规划不派发**。
    # 说出来而不是静默照做:设备端 GroundingArbiter 已经在同一屏上做过裁决,
    # 服务端再派一次动作,两个不同瞬间的判断会打架,而现场看不出是谁点的。
    may_decide, why = server_may_decide(req.platform) if req.platform else (True, "")
    if not may_decide:
        out["dispatch_declined"] = why
        out["needs_model"] = bool(planned.needs_model)
        logger.info("ui_act: %s — 只规划不派发", why)
        return out

    # 结构点不准 → 交多模态模型(视觉一直在看);把结构化辅助提示回给前端。
    if planned.needs_model or not planned.executable:
        out["needs_model"] = True
        out["grounding_prompt"] = planned.grounding_prompt
        return out

    if not req.execute:
        return out  # dry-run:只规划

    # ── 桌面:派给执行仲裁器,而不是直接派给坐标节点 ──────────────────────────
    #
    # 此前这里无条件派到 ``Node_36_UIAWindows`` 的 /click {x,y}。但 Node_36 是
    # ``core.windows_execution_arbiter`` 四级降级链里的 **Level 3(坐标)**;
    # Level 2(UIA,按控件身份 find_and_click)就在隔壁、一路到底都通,而且
    # ``windows_aip_client`` 收到 task_assign 时走的正是仲裁器。
    #
    # 也就是说:结构化的活全干完了,结果却交给了整条链里最弱的一级。这里把它接上。
    #
    # 判据不只看 req.platform:调用方常常不填它,而漏填会让这条改进直接失效。
    # 图自己带着来源(UIA 图必然来自 Windows 桌面),这个信号比让人记得填一个字段可靠。
    desktop = (normalize_platform(req.platform) == "windows") or (graph.source == UISource.UIA)

    if desktop:
        dispatch = _translate_for_desktop(graph, planned)
        out["desktop_dispatch"] = dispatch.to_dict()
        if not dispatch.dispatchable:
            out["dispatched"] = False
            out["error"] = "no_actionable_target"
            return out
        arb_out = await _dispatch_via_arbiter(dispatch, req, planned)
        if arb_out is not None:
            out.update(arb_out)
            return out
        # 仲裁器拿不到(非 Windows 宿主 / 未装依赖)→ 落回节点派发,但**说出来**:
        # 调用方若不知道这次没走仲裁器,就会以为自己用上了 UIA。
        out["arbiter_unavailable"] = "执行仲裁器不可用,本次回落到坐标节点派发"

    # 安全:node_id 不可信,严格白名单校验后才交给 invoke_node(防路径穿越)。
    node_id = _safe_node_id(req.node_id) or "Node_36_UIAWindows"  # 非法/空 → 缺省桌面 UIA
    node_action = _node_action(node_id, planned.action.value)
    params: Dict[str, Any] = {"target_node_id": planned.node_id, "label": planned.label}
    if planned.coordinates:
        params["x"], params["y"] = planned.coordinates[0], planned.coordinates[1]
    if planned.text:
        params["text"] = planned.text

    try:
        from core.node_invocation import InvocationSource, invoke_node

        result = await invoke_node(
            node_id,
            node_action,
            params,
            invocation_source=InvocationSource.UNKNOWN,
            ui_graph=req.ui_graph,  # 结构化界面态随 TASK_ASSIGN 流转
        )
        out["dispatched"] = True
        out["result"] = (
            result.to_legacy_dict()
            if hasattr(result, "to_legacy_dict")
            else {
                "success": getattr(result, "success", False),
                "error": getattr(result, "error", ""),
            }
        )
        out["dispatched_action"] = f"{node_id}.{node_action}"
    except Exception as exc:  # noqa: BLE001
        logger.warning("ui_act 派发失败: %s", exc)
        out["dispatched"] = False
        out["error"] = "dispatch_failed"
    return out
