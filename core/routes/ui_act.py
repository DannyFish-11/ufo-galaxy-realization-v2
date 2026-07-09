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
      "execute": true                        # 可选:false=只规划不执行(dry-run)
    }
    resp: { planned: {...}, dispatched: bool, result?: {...}, grounding_prompt?: str }

结构优先命中 → 直接动作;点不准 → needs_model=True + 返回【与截图一同发给模型】的
结构化辅助提示(由前端把它 + 截图交给多模态模型,再带 model_reply 回调本接口)。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel

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
    "Node_36_UIAWindows": {"tap": "click", "double_tap": "double_click",
                           "right_click": "right_click", "set_text": "type_text",
                           "scroll": "scroll", "focus": "focus"},
    "Node_45_DesktopAuto": {"tap": "click", "double_tap": "double_click",
                            "set_text": "type", "scroll": "scroll"},
    "Node_33_ADB": {"tap": "tap", "long_press": "tap", "set_text": "input",
                    "swipe": "swipe", "scroll": "swipe"},
    "Node_92_AutoControl": {"tap": "click", "set_text": "input", "scroll": "scroll"},
}


class UIActRequest(BaseModel):
    instruction: str = ""
    ui_graph: Optional[Dict[str, Any]] = None
    node_id: str = ""
    model_reply: Optional[str] = None
    execute: bool = True


def _node_action(node_id: str, action_value: str) -> str:
    return _ACTION_ALIAS.get(node_id, {}).get(action_value, action_value)


@router.post("/act")
async def ui_act(req: UIActRequest) -> Dict[str, Any]:
    """结构化操作:意图 + 界面图 → 规划 →(可选)派发执行。"""
    from core.schemas.ui_element import UIGraph
    from core.grounded_planner import plan as plan_step

    if not req.ui_graph:
        return {"success": False, "error": "ui_graph 必填(结构化界面图)"}
    try:
        graph = UIGraph.model_validate(req.ui_graph)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ui_act: UIGraph 解析失败: %s", exc)
        return {"success": False, "error": "ui_graph 解析失败"}

    planned = plan_step(graph, req.instruction, model_reply=req.model_reply)
    out: Dict[str, Any] = {
        "success": True,
        "planned": planned.model_dump(exclude={"grounding_prompt"}),
        "dispatched": False,
    }

    # 结构点不准 → 交多模态模型(视觉一直在看);把结构化辅助提示回给前端。
    if planned.needs_model or not planned.executable:
        out["needs_model"] = True
        out["grounding_prompt"] = planned.grounding_prompt
        return out

    if not req.execute:
        return out  # dry-run:只规划

    # 结构确定命中 → 经规范执行器派发到操作节点(带 ui_graph 结构化界面态)。
    # 安全:node_id 不可信,严格白名单校验后才交给 invoke_node(防路径穿越)。
    node_id = _safe_node_id(req.node_id) or "Node_36_UIAWindows"  # 非法/空 → 缺省桌面 UIA
    node_action = _node_action(node_id, planned.action.value)
    params: Dict[str, Any] = {"target_node_id": planned.node_id, "label": planned.label}
    if planned.coordinates:
        params["x"], params["y"] = planned.coordinates[0], planned.coordinates[1]
    if planned.text:
        params["text"] = planned.text

    try:
        from core.node_invocation import invoke_node, InvocationSource
        result = await invoke_node(
            node_id, node_action, params,
            invocation_source=InvocationSource.UNKNOWN,
            ui_graph=req.ui_graph,  # 结构化界面态随 TASK_ASSIGN 流转
        )
        out["dispatched"] = True
        out["result"] = result.to_legacy_dict() if hasattr(result, "to_legacy_dict") else {
            "success": getattr(result, "success", False),
            "error": getattr(result, "error", ""),
        }
        out["dispatched_action"] = f"{node_id}.{node_action}"
    except Exception as exc:  # noqa: BLE001
        logger.warning("ui_act 派发失败: %s", exc)
        out["dispatched"] = False
        out["error"] = "dispatch_failed"
    return out
