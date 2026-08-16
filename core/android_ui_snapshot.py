#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/android_ui_snapshot.py — Android 无障碍快照 → 统一控件契约
================================================================

**Stage C：填上 ``UISource.ANDROID_A11Y`` 的生产者，让服务端"看得见"手机屏幕。**

之前是什么状态
--------------
两端各自都做完了，中间那根线不存在：

* **Android 端**：``AccessibilityUiSnapshotProvider`` 读 ``rootInActiveWindow``、
  剪枝（只收可见且有语义价值的节点、上限 120、深度 40）、拍平成
  ``UiStructuredSnapshot``，还修过一个节点未回收的真 bug。
* **V2 端**：``UIGraph`` 契约里 ``UISource.ANDROID_A11Y`` 这个来源
  **声明了却零生产者**；``ui_grounding`` 在 Android 上因此永远走 ``DEFER_TO_MODEL``。
* 设备一直在上报 ``accessibility_ready: true``，而网关**只拿它做设备选择评分**，
  从没有任何链路把那棵树取回来。

本模块就是那根线的 V2 端。

看得见 ≠ 可以决定
-----------------
这是本模块最要紧的一条纪律，写在 :data:`SNAPSHOT_IS_FOR_SEEING_POLICY`：
拿到的图**只用于服务端"看得见"**——跨设备编排、面板呈现、多步规划的可行性判断
——**绝不用于覆盖设备端 ``GroundingArbiter`` 已经做出的裁决**
（见 :mod:`core.perception_grounding` 的 POLICY_1 / POLICY_3）。

两端在延迟不同的两个瞬间看到的是不同的屏幕。让后到的一方推翻先到的一方，
得到的不是更准，是不可复现——而且现场分不出这一下是谁点的。

搭车而不是新开一条管道
----------------------
快照搭 ``DEVICE_PERCEPTION_EMISSION`` 这条既有上行（Android 端已在持续发送
screenshot / vision / grounding），只多一个**默认为空的可选字段**。
没有新消息类型、没有协议变更；设备不带这个字段时，整条链路与改造前逐字节相同。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from core.schemas.ui_element import UIActionKind, UIBounds, UIElementNode, UIGraph, UISource

logger = logging.getLogger("Galaxy.AndroidUISnapshot")

__all__ = [
    "SNAPSHOT_IS_FOR_SEEING_POLICY",
    "SNAPSHOT_RIDES_AN_EXISTING_UPLINK_POLICY",
    "ANDROID_CLASS_ROLE_MAP",
    "SNAPSHOT_PAYLOAD_KEY",
    "project_android_snapshot",
    "absorb_snapshot_payload",
    "latest_graph_for",
    "snapshot_store_stats",
]


# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

SNAPSHOT_IS_FOR_SEEING_POLICY: str = (
    "ANDROID_UI_SNAPSHOT::POLICY_1: "
    "A received snapshot is for the server to SEE with, never to decide with. "
    "Android grounding is owned by the device (perception_grounding POLICY_1); "
    "the two sides observed the screen at different instants, so a server-side "
    "override produces irreproducibility rather than accuracy — and afterwards "
    "nobody can tell which side issued the tap."
)

SNAPSHOT_RIDES_AN_EXISTING_UPLINK_POLICY: str = (
    "ANDROID_UI_SNAPSHOT::POLICY_2: "
    "The snapshot travels as one optional, default-absent field on the existing "
    "DEVICE_PERCEPTION_EMISSION uplink.  No new message type and no protocol "
    "change: a device that does not send the field leaves every byte of the "
    "existing path unchanged, which is what makes this safe to land before "
    "anyone has decided whether to switch it on."
)


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

SNAPSHOT_PAYLOAD_KEY: str = "ui_snapshot_payload"
"""Android 端在 emission payload 上挂快照用的字段名(两端唯一约定处)。"""

ANDROID_CLASS_ROLE_MAP: Dict[str, str] = {
    "button": "button",
    "imagebutton": "button",
    "imageview": "image",
    "edittext": "edit",
    "autocompletetextview": "edit",
    "textview": "text",
    "checkbox": "checkbox",
    "radiobutton": "radio",
    "switch": "switch",
    "switchcompat": "switch",
    "seekbar": "slider",
    "spinner": "combobox",
    "recyclerview": "list",
    "listview": "list",
    "scrollview": "list",
    "nestedscrollview": "list",
    "viewpager": "tab",
    "tablayout": "tab",
    "webview": "group",
    "framelayout": "group",
    "linearlayout": "group",
    "relativelayout": "group",
    "constraintlayout": "group",
    "view": "view",
}
"""Android 控件类名(去包名、小写)→ 契约里的规范化 role。

查不到的类名落到 ``view``——**不是** ``text``:说不上来是什么，就别声称它是一段
文字。谎报成不可交互的文字，模型就不会去点它。"""

_MAX_DEVICES = 64
"""最多为多少台设备各留一份最新快照。

有界是必须的:这是长驻进程里的缓存,不是日志。超出后按最久未更新淘汰。"""

_STALE_SECONDS = 120.0
"""超过这个时长的快照不再作为"当前界面"回答。

界面是会变的。把两分钟前的树当成现在的屏幕交出去,比说"我不知道"更危险——
调用方会照着它规划一串再也点不中的动作。"""

_lock = threading.Lock()
_latest: Dict[str, Tuple[float, UIGraph]] = {}
_stats: Dict[str, int] = {"absorbed": 0, "rejected": 0, "served": 0, "stale_declined": 0}


def _role_of(class_name: str) -> str:
    leaf = (class_name or "").strip().rsplit(".", 1)[-1].lower()
    return ANDROID_CLASS_ROLE_MAP.get(leaf, "view")


def _bounds_of(element: Dict[str, Any]) -> Optional[UIBounds]:
    """LTRB → 左上角+宽高。给不出**可用**锚点时返回 None 并说明原因。

    零面积框会被丢弃:它看起来像个有效坐标,却点不中任何东西,而下游拿到它就不会
    再退回让模型看画面。猜错的坐标比没有坐标危险。
    """
    try:
        left = int(element.get("left", 0) or 0)
        top = int(element.get("top", 0) or 0)
        right = int(element.get("right", 0) or 0)
        bottom = int(element.get("bottom", 0) or 0)
    except (TypeError, ValueError) as exc:
        logger.warning("a11y 元素坐标无法解析(%s),该节点没有坐标锚点", exc)
        return None
    bounds = UIBounds(x=left, y=top, width=max(0, right - left), height=max(0, bottom - top))
    if bounds.area() <= 0:
        return None
    return bounds


def _project_element(raw: Dict[str, Any]) -> Optional[UIElementNode]:
    text = str(raw.get("text", "") or "").strip()
    desc = str(raw.get("contentDescription", "") or raw.get("content_description", "") or "").strip()
    label = text or desc
    clickable = bool(raw.get("clickable", False))
    role = _role_of(str(raw.get("className", "") or raw.get("class_name", "")))
    editable = role == "edit"

    actions: List[UIActionKind] = []
    if clickable:
        actions.append(UIActionKind.TAP)
    if editable:
        actions.append(UIActionKind.SET_TEXT)

    bounds = _bounds_of(raw)
    if not label and bounds is None:
        # 既叫不出名字、又点不中的节点，对模型和执行器都不构成一个可用候选：
        # 它引用不了（to_prompt 里是一行空壳）、也落不了点。留着只会把图撑大，
        # 还会让"拿到了一张图"这件事变得不再意味着"看得见这一屏"。
        # 采集端本来就只收有语义价值的节点，走到这里说明这一条是坏的。
        return None

    index = raw.get("index")
    return UIElementNode(
        node_id=f"a11y-{index}" if index is not None else "",
        role=role,
        label=label,
        bounds=bounds,
        clickable=clickable,
        editable=editable,
        actions=actions,
        source=UISource.ANDROID_A11Y,
        # 结构节点是系统对自身的陈述,不是对像素的推断 —— 置信度就是 1.0。
        confidence=1.0,
        class_name=str(raw.get("className", "") or raw.get("class_name", "") or ""),
        package=str(raw.get("package", "") or ""),
    )


def project_android_snapshot(payload: Any, *, device_id: str = "") -> Tuple[UIGraph, str]:
    """``UiStructuredSnapshot`` 的 JSON → ``UIGraph``。返回 ``(图, 说明)``。

    说明恒非空:"这一屏没有可用控件"与"载荷坏了"都产生空图,但前者该退回纯视觉,
    后者是缺陷。空图配空说明会把这个区别抹掉。
    """
    empty = UIGraph(source=UISource.ANDROID_A11Y, device_id=device_id)
    if not isinstance(payload, dict):
        return empty, f"载荷不是对象({type(payload).__name__})"

    raw_elements = payload.get("elements")
    if not isinstance(raw_elements, list):
        return empty, "载荷缺少 elements 列表"

    children: List[UIElementNode] = []
    skipped = 0
    for raw in raw_elements:
        if not isinstance(raw, dict):
            skipped += 1
            continue
        node = _project_element(raw)
        if node is None:
            skipped += 1
            continue
        children.append(node)

    if not children:
        return empty, f"快照里没有可用控件(收到 {len(raw_elements)} 条,全部跳过)"

    package = str(payload.get("packageName", "") or payload.get("package_name", "") or "")
    root = UIElementNode(role="root", label=package, source=UISource.ANDROID_A11Y, confidence=1.0)
    root.children = children

    def _dim(*keys: str) -> int:
        for key in keys:
            try:
                value = int(payload.get(key, 0) or 0)
            except (TypeError, ValueError):
                continue
            if value:
                return value
        return 0

    graph = UIGraph(
        root=root,
        source=UISource.ANDROID_A11Y,
        device_id=device_id,
        app=package,
        screen_width=_dim("screenWidth", "screen_width"),
        screen_height=_dim("screenHeight", "screen_height"),
        captured_at_ms=int(time.time() * 1000),
    )
    note = f"a11y 快照:{len(children)} 个控件"
    if skipped:
        note += f"(跳过 {skipped} 条无效)"
    return graph, note


def _evict_locked() -> None:
    while len(_latest) > _MAX_DEVICES:
        oldest = min(_latest, key=lambda key: _latest[key][0])
        _latest.pop(oldest, None)


def absorb_snapshot_payload(payload: Any, *, device_id: str) -> Tuple[bool, str]:
    """把设备上报的快照收进来。返回 ``(是否收下, 说明)``。

    永不抛:它跑在 WebSocket 上行处理里,一个坏载荷不该影响连接。
    """
    if not device_id:
        with _lock:
            _stats["rejected"] += 1
        return False, "缺少 device_id,无法归属"
    try:
        graph, note = project_android_snapshot(payload, device_id=device_id)
    except Exception as exc:  # noqa: BLE001 — 上行处理绝不能因为一个坏载荷而中断
        logger.warning("a11y 快照投影异常(device=%s): %s", device_id, exc)
        with _lock:
            _stats["rejected"] += 1
        return False, f"投影异常({type(exc).__name__})"

    if graph.root is None:
        with _lock:
            _stats["rejected"] += 1
        return False, note

    with _lock:
        _latest[device_id] = (time.time(), graph)
        _stats["absorbed"] += 1
        _evict_locked()
    logger.info("已收下设备 %s 的 %s", device_id, note)
    return True, note


def latest_graph_for(device_id: str) -> Tuple[Optional[UIGraph], str]:
    """取某台设备最近一次的界面结构——**供服务端"看得见",不供覆盖设备裁决**。

    过期的快照一律不给（见 :data:`_STALE_SECONDS`）：界面会变，把两分钟前的树
    当成现在的屏幕交出去，调用方会照着它规划一串再也点不中的动作。
    """
    if not device_id:
        return None, "缺少 device_id"
    with _lock:
        hit = _latest.get(device_id)
        if hit is None:
            return None, "该设备尚未上报过界面结构"
        captured_at, graph = hit
        age = time.time() - captured_at
        if age > _STALE_SECONDS:
            _stats["stale_declined"] += 1
            return None, f"最近一次快照已过期({age:.0f}s > {_STALE_SECONDS:.0f}s)"
        _stats["served"] += 1
    return graph, f"{age:.1f}s 前的界面结构"


def snapshot_store_stats() -> Dict[str, Any]:
    """收了多少、拒了多少、给出去多少、因过期挡下多少。"""
    with _lock:
        return {**_stats, "devices": len(_latest), "stale_seconds": _STALE_SECONDS}
