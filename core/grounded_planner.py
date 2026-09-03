"""core/grounded_planner.py — 视觉+结构 落成可执行动作(设备无关)
====================================================================

把前面几块拼成一个**可跑的一步规划器**——模型与"操作方法"之间的中间机制:

    界面图(UIGraph) + 意图 ──▶ GroundedPlanner.plan ──▶ PlannedAction
                                                          │
                                    ├─ 结构确定性命中 → 直接给动作(动词+目标+坐标+文本)
                                    └─ 结构点不准    → needs_model=True,产出【与截图一同
                                                        发给模型】的结构化辅助提示;模型回
                                                        [n]/描述后,再喂回 plan(model_reply=…)

一步规划出的动作可 :func:`to_task_assign` 落成 AIP v3 ``TASK_ASSIGN`` —— 带上动作参数
和当前 ``ui_graph``,交给设备执行器(桌面 UIAWindows / 手机 AccessibilityActionExecutor)
落地。视觉与结构恒并存:模型永远看着截图,结构只是给它精确锚点;结构缺了,模型照样能
靠视觉操作。

规划器**模型无关、设备无关**:桌面与手机复用同一份。
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel

from core.schemas.aip_v3 import TaskAssignMsg
from core.schemas.ui_element import UIActionKind, UIGraph
from core.ui_grounding import (
    GroundingStrategy,
    build_grounding_prompt,
    parse_model_action,
    resolve_target,
)


class PlannedAction(BaseModel):
    """一步可执行动作(或"需要模型判断"的待决状态)。"""

    action: UIActionKind = UIActionKind.TAP
    node_id: str = ""  # 目标控件端内标识(设备侧据此/坐标复定位)
    label: str = ""
    coordinates: Optional[List[int]] = None  # [x, y] 目标中心;结构点中才有
    text: str = ""  # SET_TEXT 要输入的文字
    confidence: float = 0.0
    strategy: GroundingStrategy = GroundingStrategy.NONE
    needs_model: bool = False  # True=结构点不准,得让模型(看着截图+结构)判断
    grounding_prompt: str = ""  # needs_model 时:与截图一同发给模型的辅助提示
    reason: str = ""
    fusion_source: str = ""
    """坐标裁决的来源标签(agreement / tree_override / tree_rescue / vlm_only)。

    非坐标路径为空串。留在动作上是为了让"这一点是谁定的"可审计 —— 阈值将来要按
    真机数据调,没有这一列就只能拍脑袋。
    """

    @property
    def executable(self) -> bool:
        """能否直接执行(结构已确定命中,不必再问模型)。"""
        return not self.needs_model and (self.coordinates is not None or bool(self.node_id) or bool(self.label))


def plan(
    graph: UIGraph, instruction: str, *, model_reply: Optional[str] = None, action: Optional[UIActionKind] = None
) -> PlannedAction:
    """规划一步。

    - 未给 model_reply:先走结构确定性快路径 :func:`resolve_target`。命中→直接动作;
      点不准→ needs_model,附上【与截图一同发给模型】的结构化辅助提示。
    - 给了 model_reply:模型(已看着截图+结构清单)回了 [n]/描述,:func:`parse_model_action`
      解析成确定动作。
    """
    if model_reply is not None:
        gr = parse_model_action(model_reply, graph, action=action)
    else:
        gr = resolve_target(graph, instruction, action=action)

    if gr.ok:
        # 落点统一走 target_center():裁决出的坐标优先于节点中心(理由见该方法)。
        center = gr.target_center()
        return PlannedAction(
            action=gr.action,
            node_id=gr.node.node_id if gr.node is not None else "",
            label=gr.node.label if gr.node is not None else "",
            coordinates=[center[0], center[1]] if center is not None else None,
            text=gr.text,
            confidence=gr.confidence,
            strategy=gr.strategy,
            needs_model=False,
            reason=gr.reason,
            fusion_source=gr.fusion_source,
        )

    # 结构点不准 → 交给多模态模型(它一直看着截图;结构清单作辅助一起给)
    return PlannedAction(
        action=gr.action,
        text=gr.text,
        confidence=0.0,
        strategy=gr.strategy,
        needs_model=True,
        grounding_prompt=build_grounding_prompt(graph, instruction),
        reason=gr.reason,
    )


def to_task_assign(action: PlannedAction, graph: UIGraph, *, goal: str = "") -> TaskAssignMsg:
    """把规划出的动作落成 AIP v3 TASK_ASSIGN，带上当前结构化界面态。

    设备执行器收到后:优先用 node_id/label 在自己那棵实时树里复定位(最稳),
    退而用 coordinates 直接点(结构给的精确坐标)。ui_graph 供闭环校验/审计。"""
    return TaskAssignMsg(
        action=action.action.value,
        params={
            "node_id": action.node_id,
            "label": action.label,
            "coordinates": action.coordinates,
            "text": action.text,
        },
        goal=goal or action.label,
        ui_graph=graph.model_dump(),
    )
