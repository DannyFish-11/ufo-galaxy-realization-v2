"""
UFO Galaxy — 结构化 UI 节点契约（AG-UI，Pydantic V2）
=====================================================

跨端统一的「界面结构化表示」——把 Windows UIA 树 / Linux AT-SPI / macOS AX /
Android 无障碍(AccessibilityNodeInfo)树 / 视觉(VLM/OCR)推断出的控件，全部序列化
成**同一种** :class:`UIElementNode` 图，作为任务 DAG 的一等输入。

为什么要它
----------
此前 Agent 操作设备靠**纯视觉 grounding**:截图 → VLM → 猜像素坐标。分辨率/主题/
动画一变坐标就飘,准确性与稳定性最脆。系统 API（桌面 UIA、手机 accessibility）本来
就能白送一棵**语义控件树**(每个控件的 role/label/bounds/可交互性),此前只用它做
**输出**(点击/输入),没用它做**输入**(理解界面)。本契约把这棵树结构化,作为视觉的
**叠加辅助**——模型一边看画面,一边拿着「名为『发送』的按钮在这个坐标」的精确锚点,
而不必对着像素猜。

视觉主看 · 结构化恒辅助(不是二选一,更不是谁 fallback 谁)
--------------------------------------------------------
- **视觉一直是主视觉通道**:模型每一拍都看着截图,看到全部(含结构漏掉的
  Flutter·Canvas·游戏·自绘控件、第三方封锁无障碍的界面)。
- **结构化控件图一直作为叠加辅助**:系统 API(UIA/a11y)白送的语义控件树给视觉配上
  "每个控件叫什么、在哪、什么状态"的精确锚点——把过去"文字描述界面"的提示词换成
  结构化节点。结构缺了某控件,不影响视觉照样能操作它。
- :meth:`UIGraph.merge` 把两个来源的控件并进一张**混合图**(source 各自标注):结构给
  视觉控件补精确边界/状态,视觉补结构没识别到的控件——两条腿同时在。

:meth:`UIElementNode.to_prompt` 把这棵树渲染成紧凑的结构化文本,**取代**过去喂给模型
的自由提示词——同样一屏,信息更准、状态更明确、token 更省。
"""
from __future__ import annotations

import time
from enum import Enum
from typing import Any, Callable, Dict, Iterator, List, Optional

from pydantic import BaseModel, Field


class UISource(str, Enum):
    """一个控件的来源(证据链)。混合图里不同节点可有不同来源。"""
    UIA = "uia"                 # Windows UI Automation
    ATSPI = "atspi"             # Linux AT-SPI
    AX = "ax"                   # macOS Accessibility
    ANDROID_A11Y = "android_a11y"  # Android AccessibilityNodeInfo
    VISION = "vision"           # VLM 视觉推断(SeeClick / MobileVLM)
    OCR = "ocr"                 # OCR 文本框
    HYBRID = "hybrid"           # 结构 + 视觉融合后的节点


class UIActionKind(str, Enum):
    """规范化操作动词——桌面 system-API 与手机 accessibility 的并集。

    上层 Agent 只用这些语义动词;各端执行器(UIAWindows / AccessibilityActionExecutor /
    DesktopAuto)再把动词落到各自的物理 API。"""
    TAP = "tap"                 # 单击/轻触
    DOUBLE_TAP = "double_tap"
    LONG_PRESS = "long_press"
    RIGHT_CLICK = "right_click"
    SET_TEXT = "set_text"       # 写入文本(优先控件级 SET_TEXT,而非逐键)
    CLEAR = "clear"
    SCROLL = "scroll"
    SWIPE = "swipe"
    FOCUS = "focus"
    OPEN_APP = "open_app"
    BACK = "back"
    HOME = "home"
    KEY = "key"                 # 物理/虚拟按键


class UIBounds(BaseModel):
    """控件在屏幕上的矩形(左上角 + 宽高,像素)。"""
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0

    def center(self) -> "tuple[int, int]":
        return (self.x + self.width // 2, self.y + self.height // 2)

    def area(self) -> int:
        return max(0, self.width) * max(0, self.height)

    def iou(self, other: "UIBounds") -> float:
        """两矩形交并比——融合去重时判"是否同一个控件"。"""
        ax2, ay2 = self.x + self.width, self.y + self.height
        bx2, by2 = other.x + other.width, other.y + other.height
        ix1, iy1 = max(self.x, other.x), max(self.y, other.y)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
        inter = iw * ih
        if inter == 0:
            return 0.0
        union = self.area() + other.area() - inter
        return inter / union if union else 0.0


class UIElementNode(BaseModel):
    """一个结构化控件节点(含子树)。

    role/label/bounds 是模型 grounding 的三要素;states 让"能不能点、是否选中、
    是否可编辑"显式可读(取代过去要模型从截图里猜)。"""
    node_id: str = ""                       # 端内稳定标识(路径/自动化ID派生)
    role: str = ""                          # 规范化控件角色: button/edit/text/list/checkbox...
    label: str = ""                         # 可见名/文本/contentDescription
    value: str = ""                         # 当前值(输入框内容、开关态文本等)

    bounds: Optional[UIBounds] = None

    # ── 状态(显式,不用模型猜)──
    clickable: bool = False
    editable: bool = False
    focused: bool = False
    enabled: bool = True
    visible: bool = True
    selected: bool = False
    scrollable: bool = False
    checked: Optional[bool] = None          # 三态: True/False/None(不适用)

    actions: List[UIActionKind] = Field(default_factory=list)

    source: UISource = UISource.UIA
    confidence: float = 1.0                 # 视觉节点 <1;结构节点通常 =1

    # ── 端特有原始属性(保留证据,不丢信息)──
    automation_id: str = ""                 # UIA AutomationId
    class_name: str = ""                    # 控件类名
    package: str = ""                       # Android 包名 / 桌面进程名

    children: List["UIElementNode"] = Field(default_factory=list)

    # ── 遍历 / 查询 ──────────────────────────────────────────────────────────
    def walk(self) -> Iterator["UIElementNode"]:
        """深度优先遍历自身 + 全部后代。"""
        yield self
        for c in self.children:
            yield from c.walk()

    def flatten(self) -> List["UIElementNode"]:
        return list(self.walk())

    def find(self, pred: Callable[["UIElementNode"], bool]) -> Optional["UIElementNode"]:
        for n in self.walk():
            if pred(n):
                return n
        return None

    def find_all(self, pred: Callable[["UIElementNode"], bool]) -> List["UIElementNode"]:
        return [n for n in self.walk() if pred(n)]

    def is_interactive(self) -> bool:
        return bool(
            self.enabled and self.visible
            and (self.clickable or self.editable or self.scrollable or self.actions)
        )

    def interactive(self) -> List["UIElementNode"]:
        """可交互控件(过滤掉纯装饰/容器)——喂给模型的候选动作集。"""
        return [n for n in self.walk() if n.is_interactive()]

    def find_by_label(self, text: str, *, exact: bool = False) -> Optional["UIElementNode"]:
        t = (text or "").strip().lower()

        def _m(n: "UIElementNode") -> bool:
            hay = f"{n.label} {n.value}".strip().lower()
            return hay == t if exact else (bool(t) and t in hay)

        # 可交互优先(同名时更可能是用户要点的那个)
        cands = self.find_all(_m)
        cands.sort(key=lambda n: (0 if n.is_interactive() else 1))
        return cands[0] if cands else None

    def to_prompt(self, *, max_depth: int = 40, _depth: int = 0, _seq: Optional[List[int]] = None) -> str:
        """把子树渲染成紧凑结构化文本,取代自由提示词。

        形如::
            [3] button "发送" @(1180,2020·120x80) {clickable,enabled}
              [4] edit "输入消息" ="你好" @(60,2010·1000x80) {editable,focused}

        序号 [n] 是稳定的引用锚——模型回 "点 [3]" 即可精确定位,无需坐标。"""
        if _seq is None:
            _seq = [0]
        lines: List[str] = []
        idx = _seq[0]
        _seq[0] += 1

        parts: List[str] = [f"{'  ' * _depth}[{idx}]"]
        if self.role:
            parts.append(self.role)
        if self.label:
            parts.append(f'"{self.label}"')
        if self.value:
            parts.append(f'="{self.value}"')
        if self.bounds is not None:
            b = self.bounds
            parts.append(f"@({b.x},{b.y}·{b.width}x{b.height})")
        flags = [f for f, on in (
            ("clickable", self.clickable), ("editable", self.editable),
            ("focused", self.focused), ("selected", self.selected),
            ("scrollable", self.scrollable), ("disabled", not self.enabled),
            ("hidden", not self.visible),
        ) if on]
        if self.checked is not None:
            flags.append("checked" if self.checked else "unchecked")
        if self.source is UISource.VISION:
            flags.append(f"vision:{self.confidence:.2f}")
        if flags:
            parts.append("{" + ",".join(flags) + "}")
        lines.append(" ".join(parts))

        if _depth < max_depth:
            for c in self.children:
                sub = c.to_prompt(max_depth=max_depth, _depth=_depth + 1, _seq=_seq)
                if sub:
                    lines.append(sub)
        return "\n".join(lines)


UIElementNode.model_rebuild()  # 解析自引用 children 前向声明


class UIGraph(BaseModel):
    """一屏界面的结构化快照——DAG 任务节点携带的界面态。"""
    root: Optional[UIElementNode] = None
    source: UISource = UISource.UIA
    device_id: str = ""
    app: str = ""                           # 前台窗口标题 / Android 前台包名
    screen_width: int = 0
    screen_height: int = 0
    captured_at_ms: int = 0
    merged_from: List[UISource] = Field(default_factory=list)  # 混合图: 参与融合的来源
    vision_added: int = 0                   # 融合时视觉兜底新增的控件数(可观测)

    def flatten(self) -> List[UIElementNode]:
        return self.root.flatten() if self.root else []

    def interactive(self) -> List[UIElementNode]:
        return self.root.interactive() if self.root else []

    def find_by_label(self, text: str, *, exact: bool = False) -> Optional[UIElementNode]:
        return self.root.find_by_label(text, exact=exact) if self.root else None

    def to_prompt(self, *, header: bool = True) -> str:
        """整屏结构化文本——直接作为模型输入,替代"请看这张截图"式提示词。"""
        body = self.root.to_prompt() if self.root else "(空界面树)"
        if not header:
            return body
        loc = self.app or self.device_id or "当前设备"
        return f"当前界面【{loc}】结构（[n]=可引用控件序号）:\n{body}"

    def merge(self, vision: "UIGraph", *, iou_threshold: float = 0.6) -> "UIGraph":
        """把视觉图融进本(结构)图 → 混合图:两条腿一起走。

        - 视觉控件若与某结构控件框高度重叠(IoU≥阈值)→ 认为同一控件,视觉只为它补上
          缺失的 label(结构常缺文案),不新增节点。
        - 视觉控件若在结构树里找不到对应(结构缺失,如 Canvas 里的按钮)→ 作为新的
          VISION 源节点挂到根下,让模型仍能操作。
        本方法不改动 self,返回新图。"""
        struct_nodes = self.flatten()
        # 复制根(浅拷贝子树引用即可,合并只在根层加挂新节点)
        new_root = self.root.model_copy(deep=True) if self.root else UIElementNode(role="root")
        struct_flat = new_root.flatten()

        appended = 0
        for vnode in vision.flatten():
            if vnode.bounds is None:
                continue
            match = None
            best = 0.0
            for snode in struct_flat:
                if snode.bounds is None:
                    continue
                score = snode.bounds.iou(vnode.bounds)
                if score > best:
                    best, match = score, snode
            if match is not None and best >= iou_threshold:
                # 同一控件:视觉补语义(结构没文案时用视觉的 label)
                if not match.label and vnode.label:
                    match.label = vnode.label
                if match.confidence >= 1.0 and vnode.source is UISource.VISION:
                    match.source = UISource.HYBRID
            else:
                # 结构缺失的控件:视觉兜底,新增挂载
                new_root.children.append(vnode)
                appended += 1

        _ = len(struct_nodes)  # (结构控件数,便于将来记账/可观测)
        return UIGraph(
            root=new_root, source=UISource.HYBRID,
            device_id=self.device_id or vision.device_id,
            app=self.app or vision.app,
            screen_width=self.screen_width or vision.screen_width,
            screen_height=self.screen_height or vision.screen_height,
            captured_at_ms=self.captured_at_ms or vision.captured_at_ms,
            merged_from=[self.source, vision.source],
            vision_added=appended,
        )


def now_ms() -> int:
    return int(time.time() * 1000)
