"""nodes/Node_36_UIAWindows/ui_tree.py
=======================================

Windows System API(UIA)→ 结构化 UI 图。把 pywinauto 的 UIA 控件树序列化成
仓库统一的 :class:`core.schemas.ui_element.UIElementNode` / :class:`UIGraph`,
让桌面与手机(Android a11y)对着**同一种结构化控件图**推理——这是"结构优先、
视觉兜底"里桌面 system-API 的那条腿。

设计要点
--------
序列化是**纯函数**且对控件对象**鸭子类型**访问(``_txt`` / ``_rect`` 等用 getattr
+ 可调用判断),因此:
  - 生产环境吃真实 pywinauto 控件(Windows 上 ``Desktop(backend="uia")``);
  - 单测用最小假控件即可覆盖,无需 Windows、无需 pywinauto。

pywinauto 不在本函数里 import —— 真正连接桌面的 :func:`capture_desktop_graph`
才延迟 import,并对非 Windows / 缺依赖优雅降级。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from core.schemas.ui_element import (
    UIActionKind,
    UIBounds,
    UIElementNode,
    UIGraph,
    UISource,
    now_ms,
)


# ── 鸭子类型访问器(既吃真 pywinauto 控件,也吃假控件)──────────────────────────
def _call(obj: Any, name: str, default: Any = None) -> Any:
    """取 obj.name;可调用就调用它,否则取属性值。异常/缺失回落 default。"""
    try:
        attr = getattr(obj, name, None)
        if attr is None:
            return default
        return attr() if callable(attr) else attr
    except Exception:  # noqa: BLE001 — 控件访问随时可能抛(窗口关闭等)
        return default


def _text(ctl: Any) -> str:
    for name in ("window_text", "name"):
        v = _call(ctl, name, "")
        if v:
            return str(v)
    return ""


def _rect(ctl: Any) -> Optional[UIBounds]:
    r = _call(ctl, "rectangle")
    if r is None:
        return None
    left = _call(r, "left", getattr(r, "left", 0))
    top = _call(r, "top", getattr(r, "top", 0))
    width = _call(r, "width", None)
    height = _call(r, "height", None)
    if width is None:
        width = int(getattr(r, "right", left)) - int(left)
    if height is None:
        height = int(getattr(r, "bottom", top)) - int(top)
    try:
        return UIBounds(x=int(left), y=int(top), width=int(width), height=int(height))
    except Exception:  # noqa: BLE001
        return None


def _control_type(ctl: Any) -> str:
    # pywinauto: element_info.control_type;或 friendly_class_name()
    ei = getattr(ctl, "element_info", None)
    if ei is not None:
        ct = getattr(ei, "control_type", None)
        if ct:
            return str(ct)
    return str(_call(ctl, "friendly_class_name", "") or _call(ctl, "class_name", ""))


def _automation_id(ctl: Any) -> str:
    ei = getattr(ctl, "element_info", None)
    if ei is not None:
        aid = getattr(ei, "automation_id", None)
        if aid:
            return str(aid)
    return str(_call(ctl, "automation_id", "") or "")


# UIA control_type → 规范化 role + 默认可交互性
_CLICKABLE_TYPES = {
    "Button", "Hyperlink", "MenuItem", "ListItem", "TabItem", "TreeItem",
    "CheckBox", "RadioButton", "SplitButton", "Custom",
}
_EDITABLE_TYPES = {"Edit", "Document", "ComboBox"}
_SCROLLABLE_TYPES = {"List", "Tree", "DataGrid", "Pane", "Document"}
_ROLE_ALIAS = {
    "Edit": "edit", "Button": "button", "Text": "text", "CheckBox": "checkbox",
    "RadioButton": "radio", "Hyperlink": "link", "MenuItem": "menuitem",
    "ListItem": "listitem", "List": "list", "ComboBox": "combobox",
    "TabItem": "tab", "Window": "window", "Pane": "pane", "Image": "image",
}


def _role(control_type: str) -> str:
    return _ROLE_ALIAS.get(control_type, (control_type or "element").lower())


def control_to_node(
    ctl: Any,
    *,
    source: UISource = UISource.UIA,
    max_depth: int = 40,
    _depth: int = 0,
    _path: str = "0",
) -> UIElementNode:
    """单个 pywinauto UIA 控件(含子树)→ UIElementNode。纯函数、鸭子类型。"""
    ct = _control_type(ctl)
    enabled = bool(_call(ctl, "is_enabled", True))
    visible = bool(_call(ctl, "is_visible", True))
    editable = ct in _EDITABLE_TYPES
    clickable = ct in _CLICKABLE_TYPES

    actions: List[UIActionKind] = []
    if clickable:
        actions.append(UIActionKind.TAP)
    if editable:
        actions.append(UIActionKind.SET_TEXT)
    if ct in _SCROLLABLE_TYPES:
        actions.append(UIActionKind.SCROLL)

    # checkbox/radio 三态
    checked: Optional[bool] = None
    if ct in ("CheckBox", "RadioButton"):
        tog = _call(ctl, "get_toggle_state", None)
        if tog is not None:
            checked = bool(tog)

    node = UIElementNode(
        node_id=_path,
        role=_role(ct),
        label=_text(ctl),
        bounds=_rect(ctl),
        clickable=clickable,
        editable=editable,
        focused=bool(_call(ctl, "has_keyboard_focus", False) or _call(ctl, "is_focused", False)),
        enabled=enabled,
        visible=visible,
        scrollable=ct in _SCROLLABLE_TYPES,
        checked=checked,
        actions=actions,
        source=source,
        automation_id=_automation_id(ctl),
        class_name=str(_call(ctl, "class_name", "") or ct),
    )

    if _depth < max_depth:
        kids = _call(ctl, "children", []) or []
        for i, child in enumerate(kids):
            try:
                node.children.append(control_to_node(
                    child, source=source, max_depth=max_depth,
                    _depth=_depth + 1, _path=f"{_path}.{i}",
                ))
            except Exception:  # noqa: BLE001 — 单个坏控件不拖垮整棵树
                continue
    return node


def build_ui_graph(
    root_ctl: Any,
    *,
    app: str = "",
    device_id: str = "",
    screen: "tuple[int, int]" = (0, 0),
    max_depth: int = 40,
) -> UIGraph:
    """根控件 → 整屏 UIGraph。"""
    root = control_to_node(root_ctl, max_depth=max_depth)
    return UIGraph(
        root=root, source=UISource.UIA, device_id=device_id,
        app=app or root.label, screen_width=screen[0], screen_height=screen[1],
        captured_at_ms=now_ms(),
    )


# ── 选择器匹配(把 find_element 从桩做实)────────────────────────────────────────
def _selector_pred(selector: Dict[str, Any]) -> Callable[[UIElementNode], bool]:
    name = (selector.get("name") or selector.get("label") or "").strip().lower()
    aid = (selector.get("automation_id") or "").strip()
    cls = (selector.get("class_name") or "").strip().lower()
    ctype = (selector.get("control_type") or selector.get("role") or "").strip().lower()

    def _pred(n: UIElementNode) -> bool:
        if name and name not in f"{n.label} {n.value}".strip().lower():
            return False
        if aid and aid != n.automation_id:
            return False
        if cls and cls not in n.class_name.lower():
            return False
        if ctype and ctype != n.role.lower():
            return False
        # 至少给一个条件才算命中(全空不匹配所有)
        return any((name, aid, cls, ctype))

    return _pred


def find_in_graph(graph: UIGraph, selector: Dict[str, Any]) -> List[UIElementNode]:
    if graph.root is None:
        return []
    pred = _selector_pred(selector)
    hits = graph.root.find_all(pred)
    hits.sort(key=lambda n: (0 if n.is_interactive() else 1))
    return hits
