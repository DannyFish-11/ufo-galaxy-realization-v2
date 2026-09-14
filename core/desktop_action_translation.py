"""core/desktop_action_translation.py — 把命中的控件翻译成仲裁器听得懂的动作
=============================================================================

断在哪里
--------
``core/routes/ui_act.py`` 把结构化的活全干完了:读控件图 → grounding 命中某个控件 →
派发。但它派发的目标是 ``Node_36_UIAWindows`` 的 HTTP ``/click {x, y}``。

而 ``core.windows_execution_arbiter`` 早就是一条四级降级链::

    Level 1  System API      启动/聚焦/热键
    Level 2  UIA             按控件身份操作(find_and_click / find_and_type)
    Level 3  GUI             坐标模拟
    Level 4  VLM             截图 + 视觉模型

Node_36 是 **Level 3**。也就是说:整条链里最强的两级就在隔壁、已经写好、而且有活
的调用方(``windows_aip_client`` 收到 ``task_assign`` 就走仲裁器),而服务端这条路
把结构化命中的结果直接交给了最弱的一级。

Level 2 一路到底是通的,逐段都在:

    仲裁器 ``_try_uia`` → ``_uia_exec`` → ``WindowsAutonomyManager.execute_action``
    → ``_action_find_and_click`` → ``UIAutomationWrapper.find_element_by_name``
    → ``click_element()`` → ``InvokePattern.Invoke()``

缺的只有一句翻译:把"命中了这个控件"说成仲裁器的动作词汇。

为什么 automation_id 要单独给
-----------------------------
``_action_find_and_click`` 的分支是 ``if name: ... elif automation_id: ...`` ——
**两个都给时 name 赢**。而 name 是可见文本:会随界面语言变、随控件状态变(「播放」→
「暂停」)、还可能和别的控件重名;automation_id 是开发者显式写死的。

所以有 automation_id 时**只给 automation_id**,不把 name 一起塞进去 —— 否则那条
更稳的路永远走不到。这不是调用方该知道的细节,所以钉在这里。

为什么"能点成"也要标 degraded
-----------------------------
没有控件身份时退坐标是对的(不能让任务直接失败),但**不能悄悄退**。这和
``core.execution_isolation`` 是同一个立场:容器起不来时回落内置可以,可调用方若不知
道这次是在裸机上跑的,就会以为自己有边界。这里同理:调用方若不知道这次是盲点坐标,
就会以为自己点的是那个控件。

``degraded`` 不是"失败",是"这次比你以为的弱"。两者必须能分开。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

__all__ = [
    "ARBITER_FIND_AND_CLICK",
    "ARBITER_FIND_AND_TYPE",
    "ARBITER_CLICK",
    "ARBITER_TYPE",
    "DesktopDispatch",
    "identity_of",
    "translate",
]

#: 仲裁器 Level 2(UIA)的动作词 —— 按控件身份操作。
ARBITER_FIND_AND_CLICK = "find_and_click"
ARBITER_FIND_AND_TYPE = "find_and_type"

#: 仲裁器 Level 3(GUI)的动作词 —— 按坐标操作。
ARBITER_CLICK = "click"
ARBITER_TYPE = "type"


@dataclass(frozen=True)
class DesktopDispatch:
    """一次桌面派发:发什么动作、带什么参数、以及**这次有多弱**。

    冻结:判定不该在派发途中被改写。
    """

    action: str
    params: Dict[str, Any] = field(default_factory=dict)
    degraded: bool = False
    reason: str = ""
    identity_used: bool = False
    dispatchable: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "params": dict(self.params),
            "degraded": self.degraded,
            "reason": self.reason,
            "identity_used": self.identity_used,
            "dispatchable": self.dispatchable,
        }


def identity_of(node: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """从一个 UIElementNode(dict)里择出可用来复定位的身份。

    只认 ``automation_id`` 与 ``label``。**不认 ``node_id``** —— 它是树路径
    (``"0.3.1"``,见 ``ui_tree.control_to_node``),窗口多一个子控件路径就变,
    拿它当身份是把位置当成了标识。

    有 automation_id 时**只返回它**:见模块 docstring 里 ``if name: elif
    automation_id:`` 那一段。
    """
    if not node:
        return {}
    aid = str(node.get("automation_id") or "").strip()
    if aid:
        return {"automation_id": aid}
    label = str(node.get("label") or "").strip()
    if label:
        return {"name": label}
    return {}


def translate(
    *,
    kind: str,
    node: Optional[Dict[str, Any]] = None,
    coordinates: Optional[Tuple[int, int]] = None,
    text: str = "",
) -> DesktopDispatch:
    """把一次 grounding 命中翻译成仲裁器的动作。

    ``kind`` 取 ``"tap"``/``"click"`` 或 ``"set_text"``/``"type"``。
    ``node`` 是命中的 UIElementNode(dict);``coordinates`` 是它的中心点(兜底用)。
    """
    typing = kind.lower() in ("set_text", "type", "type_text", "input")
    identity = identity_of(node)

    if identity:
        return DesktopDispatch(
            action=ARBITER_FIND_AND_TYPE if typing else ARBITER_FIND_AND_CLICK,
            params={**identity, **({"text": text} if typing else {})},
            degraded=False,
            reason=(
                "按控件身份操作(仲裁器 Level 2 / UIA):不经过鼠标,"
                "窗口移动、控件被遮挡、列表滚出视口、DPI 缩放都影响不到它"
            ),
            identity_used=True,
        )

    if coordinates is not None:
        x, y = coordinates
        return DesktopDispatch(
            action=ARBITER_TYPE if typing else ARBITER_CLICK,
            params={"x": int(x), "y": int(y), **({"text": text} if typing else {})},
            degraded=True,
            reason=(
                "命中的控件没有 automation_id 也没有可见名,只能按坐标操作"
                "(仲裁器 Level 3 / GUI)—— 窗口若在采集之后动过,这一下会落空,"
                "而且落在哪儿不可知"
            ),
            identity_used=False,
        )

    return DesktopDispatch(
        action="",
        params={},
        degraded=True,
        reason="既没有控件身份也没有坐标 —— 不猜一个中心点,这里必须是显式失败",
        identity_used=False,
        dispatchable=False,
    )
