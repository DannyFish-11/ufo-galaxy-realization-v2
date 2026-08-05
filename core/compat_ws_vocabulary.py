"""core.compat_ws_vocabulary — 兼容设备入口的类型名与 AIP 词汇之间的那层翻译

要解决什么
==========
本仓的规范信封是 AIP v3（``galaxy_gateway/protocol/aip_v3.py``，
``core/dual_repo_system_map.py`` 把它标注为 *canonical cross-repo envelope*），
v1↔v3 的别名归一表在 ``galaxy_gateway/protocol/compat.py``。

而 ``core/api_routes.py`` 的兼容设备入口 ``/ws/device/{device_id}`` 是**设备入口**，
它的 ``elif msg_type == ...`` 分支名却是手抄的一套词汇，从不问那张归一表。实测后果
（探针直连该端点）：

    device_heartbeat  ->  {"type": "error", "message": "未知消息类型: device_heartbeat"}
    device_status     ->  同上

心跳被回 error 意味着 UDM 收不到心跳 —— 设备明明连着，却会被判离线；而故障现场只有
一行 "未知消息类型" 的 warning，指不到"两套词汇没对齐"这个真因。

判据
====
翻译**只有一处来源**：AIP 自己的归一表。这里不建第二张别名表 —— 建一张就是第二份
定义，AIP 以后加别名时它不会跟着变，而症状恰恰是"某些客户端的消息静默走不通"。

两个方向都要走
==============
第一次做的时候只做了一个方向，漏掉一半。AIP 的规范名并不总是那个看起来更"正式"的
长名：

* ``MessageType.DEVICE_HEARTBEAT.value == "heartbeat"`` —— 规范名是**短名**，
  ``device_heartbeat`` 才是别名。所以要**正向**归一：入帧别名 → 规范名 → 本面分支。
* ``MessageType.DEVICE_STATUS.value == "device_status"`` —— 这里反过来，本面分支名
  ``status_update`` 才是别名。所以要**反向**登记：分支的规范形态 → 分支名。

只做一个方向时，另一半照旧落进「未知消息类型」，而且测试如果只覆盖做通的那一半，
看上去还是全绿的。
"""

from __future__ import annotations

import logging
from typing import Callable, Dict, Optional, Tuple

logger = logging.getLogger("Galaxy.CompatWSVocabulary")

__all__ = [
    "COMPAT_WS_BRANCH_TYPES",
    "build_compat_ws_alias_map",
    "resolve_compat_ws_branch",
]

#: 兼容设备入口 ``/ws/device/{device_id}`` 的 ``elif msg_type == ...`` 分支名全集。
#:
#: 与真实 elif 链的一致性由 ``tests/test_compat_ws_speaks_aip_vocabulary.py`` 按 AST
#: 钉住：这份清单会漂，漂了的症状又恰恰是"新分支不参与别名解析、只有旧客户端发得通"，
#: 必须有断言盯着。
COMPAT_WS_BRANCH_TYPES: Tuple[str, ...] = (
    "heartbeat",
    "status_update",
    "command_result",
    "task_result",
    "goal_result",
    "goal_execution_result",
    "ocr_request",
    "chat",
    "command_dispatch",
    "relay_request",
    "relay_reply",
    "peer_announce",
    "peer_exchange_request",
    "agent_deploy_ack",
    "agent_status",
    "agent_result",
    "ai_intent",
)


def _aip_canonical_or_none() -> Optional[Callable[[str], str]]:
    """取 AIP 归一函数；网关协议层不可用时返回 ``None`` 并留 warning。

    降级要**响**：静默降级的症状是"某些客户端的消息偶尔走不通"，指不回这里。
    """
    try:
        from galaxy_gateway.protocol.compat import canonical_message_type

        return canonical_message_type
    except Exception as exc:  # noqa: BLE001 — 协议层缺席不该拖垮设备入口
        logger.warning(
            "兼容设备入口取不到 AIP 归一表，本次只认本面分支名；AIP 别名"
            "（device_heartbeat / device_status 等）会落进未知类型分支 | err=%s",
            exc,
        )
        return None


def build_compat_ws_alias_map() -> Dict[str, str]:
    """AIP 规范名 → 本兼容面分支名（**反向**那一半，由 AIP 归一表推导）。

    正向那一半不落表，在 :func:`resolve_compat_ws_branch` 里直接问归一表。

    **规范名本身已有直接分支的，一律不收。** 那不是别名冲突，是两件不同的事：
    ``command_result`` 的规范形态是 ``task_result``（对网关而言二者确实同一件事），
    但本兼容面把它们当两件事处理 —— ``command_result`` 要 resolve 一个挂起的命令
    future（按 ``command_id``），``task_result`` 走统一结果归口（按 ``task_id``）。
    收进来会让入帧改道、future 永不落地，而症状是"命令发出去就没下文"。
    ``goal_result`` / ``goal_execution_result`` 同理，两者各有分支。
    """
    canonical_of = _aip_canonical_or_none()
    if canonical_of is None:
        return {}
    direct = set(COMPAT_WS_BRANCH_TYPES)
    alias_map: Dict[str, str] = {}
    for branch in COMPAT_WS_BRANCH_TYPES:
        canonical = canonical_of(branch)
        if canonical and canonical != branch and canonical not in direct:
            alias_map[canonical] = branch
    return alias_map


_ALIAS_MAP_CACHE: Optional[Dict[str, str]] = None


def _cached_alias_map() -> Dict[str, str]:
    """别名表只由常量推导，运行期不会变，算一次即可。"""
    global _ALIAS_MAP_CACHE
    if _ALIAS_MAP_CACHE is None:
        _ALIAS_MAP_CACHE = build_compat_ws_alias_map()
    return _ALIAS_MAP_CACHE


def resolve_compat_ws_branch(msg_type: str, alias_map: Optional[Dict[str, str]] = None) -> str:
    """把入帧类型名解析成本兼容面的分支名；解析不出就原样返回。

    顺序刻意是「先直接分支、再归一」：直接分支存在就绝不改道，所以既有客户端的行为
    一字不变，本函数只可能让原本落进「未知消息类型」的帧被接住。

    解析不出**不编分支**：``relay_forward`` / ``task_submit`` 在本面确实没有实现，
    那是功能缺口不是命名不一致，照旧交给「未知消息类型」分支显式回 error。
    """
    if msg_type in COMPAT_WS_BRANCH_TYPES:
        return msg_type
    alias_map = _cached_alias_map() if alias_map is None else alias_map
    canonical_of = _aip_canonical_or_none()
    if canonical_of is not None:
        canonical = canonical_of(msg_type)
        if canonical in COMPAT_WS_BRANCH_TYPES:
            logger.debug("compat_ws 词汇改道: %s → %s (AIP 归一)", msg_type, canonical)
            return canonical
        # 两跳才够：``status`` 归一到 ``device_status``（不是本面分支），而
        # ``device_status`` 才是分支 ``status_update`` 的规范形态。只查一次的话
        # v2 的短名会停在半路，症状与修之前一模一样。
        if canonical in alias_map:
            logger.debug("compat_ws 词汇改道: %s → %s (经 AIP 规范名 %s)", msg_type, alias_map[canonical], canonical)
            return alias_map[canonical]
    return alias_map.get(msg_type, msg_type)
