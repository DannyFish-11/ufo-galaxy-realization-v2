#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/perception_grounding.py — 界面定位的权威归属
==================================================

**Stage A：先写下「哪一端决定点哪个控件」，再谈把树接过来。**

为什么这个模块必须先于接线存在
------------------------------
「这一步点哪个控件」这件事，仓库里目前有**三份各自独立的实现**：

===========================================  ====================  ==================
实现                                          位置                  现状
===========================================  ====================  ==================
``ui_grounding`` + ``grounded_planner``       V2 服务端             只有 Windows UIA 一个生产者
``vision_pipeline``                           V2 服务端             自成一套形状，只通向 HTTP 端点
``GroundingArbiter``(Kotlin)                  Android 设备本地      完整、有裁决矩阵与 JVM 单测
===========================================  ====================  ==================

三者互不相识，而契约里给另外两条预留的位置（``UISource.ANDROID_A11Y`` /
``VISION`` / ``OCR``）至今零生产者。

在这种状态下**先把 a11y 树传上来是错的**：没有归属约定，结果只会是第四份实现，
而且是延迟最高的那一份。所以本模块只做一件事——**写下判断规则**，不读、不算、
不决定，形状对齐 :mod:`core.semantic_anchoring`。

归属结论
--------
* **Android 设备 → 设备本地是权威。** 三条理由，都不是偏好问题：
  往返延迟直接体现在点击响应上；a11y 树剪枝后仍有上百个节点，每一拍上传是把
  带宽换成没人读的数据流；而设备端 ``GroundingArbiter`` 已经有明确的裁决矩阵
  （agreement / tree_override / tree_rescue / vlm_only）、两档阈值与单测。
* **桌面（Windows UIA / AT-SPI / AX） → V2 服务端是权威。** 设备端没有对应实现。

服务端拿到界面结构做什么
------------------------
**看得见，不等于替它决定。** V2 拿到 Android 的结构化快照是为了让服务端「看得见」
——跨设备编排、面板呈现、多步规划的可行性判断——**绝不用于覆盖设备端已经做出的
裁决**。两端在延迟不同的两个瞬间看到的是不同的屏幕，让后到的一方推翻先到的一方，
得到的不是更准，是不可复现。
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Dict, Tuple

logger = logging.getLogger("Galaxy.PerceptionGrounding")

__all__ = [
    "PERCEPTION_GROUNDING_IS_AUTHORITY",
    "GROUNDING_HAS_ONE_OWNER_PER_PLATFORM_POLICY",
    "MODEL_SELECTS_NEVER_SUPPLIES_POLICY",
    "SERVER_VIEW_NEVER_OVERRIDES_DEVICE_POLICY",
    "GroundingOwner",
    "PLATFORM_GROUNDING_OWNER",
    "DEFAULT_OWNER",
    "normalize_platform",
    "grounding_owner_for",
    "server_may_decide",
    "describe_grounding_authority",
]


# ---------------------------------------------------------------------------
# Authority / policy sentinels
# ---------------------------------------------------------------------------

PERCEPTION_GROUNDING_IS_AUTHORITY: str = (
    "PERCEPTION_GROUNDING::AUTHORITY: "
    "This module states which side decides which control gets acted on.  It "
    "reads no screen, resolves no element and dispatches no action — it only "
    "answers 'whose call is this', so that the answer exists in exactly one place."
)

GROUNDING_HAS_ONE_OWNER_PER_PLATFORM_POLICY: str = (
    "PERCEPTION_GROUNDING::POLICY_1: "
    "Deciding which control to act on has exactly ONE owner per platform. "
    "Android is owned by the device (round-trip latency is felt in every tap, the "
    "pruned a11y tree is still ~120 nodes, and GroundingArbiter already arbitrates "
    "with a documented matrix and unit tests).  Desktop is owned by the server "
    "(no device-side equivalent exists).  Neither side may build a second "
    "arbitration for a platform the other already owns."
)

MODEL_SELECTS_NEVER_SUPPLIES_POLICY: str = (
    "PERCEPTION_GROUNDING::POLICY_2: "
    "A model reply may only be parsed for WHICH element was chosen — never for "
    "what that element IS.  core.ui_grounding.parse_model_action extracts the "
    "index [n] and takes label/bounds/coordinates from the typed graph.  Parsing "
    "coordinates out of model prose would reintroduce the defect the object layer "
    "exists to remove: a fact carrying the model's sampling error rather than the "
    "authority of the underlying tree."
)

SERVER_VIEW_NEVER_OVERRIDES_DEVICE_POLICY: str = (
    "PERCEPTION_GROUNDING::POLICY_3: "
    "A structured snapshot the server receives from a device-owned platform is "
    "for SEEING, never for deciding.  The server must not use it to override a "
    "grounding decision the device already made: the two sides observed the "
    "screen at different instants, so letting the later one win produces "
    "irreproducibility, not accuracy."
)


# ---------------------------------------------------------------------------
# Ownership
# ---------------------------------------------------------------------------


class GroundingOwner(str, Enum):
    """Who resolves 'which control' for a given platform."""

    DEVICE = "device"
    """The device decides locally; the server observes but does not arbitrate."""

    SERVER = "server"
    """V2 resolves against the structured graph and dispatches an action."""


PLATFORM_GROUNDING_OWNER: Dict[str, GroundingOwner] = {
    "android": GroundingOwner.DEVICE,
    "wearos": GroundingOwner.DEVICE,
    "windows": GroundingOwner.SERVER,
    "linux": GroundingOwner.SERVER,
    "macos": GroundingOwner.SERVER,
    "web": GroundingOwner.SERVER,
}
"""Platform → owner.  Every entry is a claim someone defends at review time."""

DEFAULT_OWNER: GroundingOwner = GroundingOwner.SERVER
"""Unknown platforms fall to the server.

Deliberately not ``DEVICE``: an unrecognised platform has, by definition, no
device-side arbitration we know of, and answering 'the device owns it' would
silently leave nobody deciding.  Falling to the server preserves the behaviour
that existed before this module — ``ui_act`` already defaults to the desktop
node when the caller says nothing."""

_PLATFORM_ALIASES: Dict[str, str] = {
    "android_phone": "android",
    "androidtv": "android",
    "wear_os": "wearos",
    "wear": "wearos",
    "win": "windows",
    "win32": "windows",
    "darwin": "macos",
    "mac": "macos",
    "osx": "macos",
    "browser": "web",
}


def normalize_platform(platform: str) -> str:
    """Fold the spellings that actually appear in device reports onto one key."""
    key = (platform or "").strip().lower().replace("-", "_")
    return _PLATFORM_ALIASES.get(key, key)


def grounding_owner_for(platform: str) -> GroundingOwner:
    """Who decides 'which control' on *platform*.

    Never raises and never returns ``None``: a missing answer here would leave
    the caller to invent one, which is how the third implementation appeared.
    """
    key = normalize_platform(platform)
    owner = PLATFORM_GROUNDING_OWNER.get(key)
    if owner is None:
        if key:
            logger.info(
                "未登记平台 %r 的 grounding 归属,按默认 %s 处理(见 PLATFORM_GROUNDING_OWNER)",
                platform,
                DEFAULT_OWNER.value,
            )
        return DEFAULT_OWNER
    return owner


def server_may_decide(platform: str) -> Tuple[bool, str]:
    """May V2 resolve and dispatch an action for *platform* itself?

    Returns ``(allowed, reason)``.  The reason is always populated — a bare
    ``False`` would tell the caller nothing about whether this is a policy
    decision or a missing capability, and those need different fixes.
    """
    owner = grounding_owner_for(platform)
    if owner is GroundingOwner.SERVER:
        return True, f"{normalize_platform(platform) or '未知平台'} 由服务端归属"
    return False, (
        f"{normalize_platform(platform)} 由设备本地归属(POLICY_1):"
        "设备端 GroundingArbiter 已在做这件事,服务端再判一次就是第二份实现"
    )


def describe_grounding_authority(platform: str = "") -> Dict[str, Any]:
    """A JSON-safe statement of who owns what — for responses and diagnostics.

    Exposed on the wire so a caller can tell "the server declined to plan" apart
    from "the server failed to plan".  Silently returning nothing for a
    device-owned platform would make those two look identical.
    """
    payload: Dict[str, Any] = {
        "policies": [
            GROUNDING_HAS_ONE_OWNER_PER_PLATFORM_POLICY,
            MODEL_SELECTS_NEVER_SUPPLIES_POLICY,
            SERVER_VIEW_NEVER_OVERRIDES_DEVICE_POLICY,
        ],
        "owners": {name: owner.value for name, owner in sorted(PLATFORM_GROUNDING_OWNER.items())},
        "default_owner": DEFAULT_OWNER.value,
    }
    if platform:
        allowed, reason = server_may_decide(platform)
        payload["platform"] = normalize_platform(platform)
        payload["owner"] = grounding_owner_for(platform).value
        payload["server_may_decide"] = allowed
        payload["reason"] = reason
    return payload
