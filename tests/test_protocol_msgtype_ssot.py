"""tests/test_protocol_msgtype_ssot.py
========================================
协议单一真相源(SSOT)回归防护 —— 三仓消息类型契约收口到 v2 aip_v3.MessageType。

背景
----
三仓(v2 中枢 / ufo-galaxy-android / galaxy-wearos)的消息类型此前靠手工镜像维护,
必然漂移。tools/protocol/check_aip_msgtype_drift.py 把 v2 的 `MessageType` 当作唯一
真相源,发现两客户端历史上发着一批 v2 **不认**的 wire 值:

  - 6 个短别名(relay/forward/reply/lock/unlock/broadcast),语义等同 v2 的
    canonical 长名(relay_request/relay_forward/relay_reply/coord_lock/
    coord_unlock/coord_broadcast),但字符串不同 —— server `MessageType('relay')`
    会 ValueError → 返回 UNKNOWN_MESSAGE_TYPE,整条消息被拒。
  - 2 个 v2 此前无对应类型(operator_action_request / device_audit_report),同样被拒。

修复(沿用本文件既有 "previously absent → added" 补丁做法):把这 8 个客户端 wire 值
登记进 v2 `MessageType` 作为【入向兼容别名】。server 从此认得,经 catch-all 与其
canonical 对应类型一样优雅路由;canonical 输出仍只用长名。

本测试锁住:这 8 个值恒可解析(不再 UNKNOWN_MESSAGE_TYPE),且漂移检查器对
android/wearos 已知 wire 值集判定为"零未知"(strict 门禁应通过)。任何回退
(删掉别名、或客户端新增未登记类型)都会让本测试失败。
"""

from __future__ import annotations

import importlib.util
import os

import pytest

from galaxy_gateway.protocol.aip_v3 import MessageType

# 修复前会被 server 端 MessageType(...) 拒收的 8 个客户端 wire 值。
_PREVIOUSLY_REJECTED_CLIENT_WIRE_VALUES = [
    "relay", "forward", "reply", "lock", "unlock", "broadcast",
    "operator_action_request", "device_audit_report",
]

# 6 个短别名 → v2 canonical 长名。必须两者都在 enum 里(别名入向兼容、长名 canonical 输出)。
_ALIAS_TO_CANONICAL = {
    "relay": "relay_request",
    "forward": "relay_forward",
    "reply": "relay_reply",
    "lock": "coord_lock",
    "unlock": "coord_unlock",
    "broadcast": "coord_broadcast",
}


@pytest.mark.parametrize("wire", _PREVIOUSLY_REJECTED_CLIENT_WIRE_VALUES)
def test_client_wire_value_resolves_without_unknown_message_type(wire):
    """8 个客户端 wire 值都应能解析成 MessageType(不再 ValueError → UNKNOWN_MESSAGE_TYPE)。"""
    mt = MessageType(wire)  # 修复前这里对这些值会抛 ValueError
    assert mt.value == wire


@pytest.mark.parametrize("alias,canonical", sorted(_ALIAS_TO_CANONICAL.items()))
def test_alias_and_canonical_both_registered_and_distinct(alias, canonical):
    """短别名与 canonical 长名必须同时存在且是不同成员(别名入向、长名输出,互不吞并)。"""
    assert MessageType(alias).value == alias
    assert MessageType(canonical).value == canonical
    assert MessageType(alias) is not MessageType(canonical)


def _load_drift_checker():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(here, "tools", "protocol", "check_aip_msgtype_drift.py")
    spec = importlib.util.spec_from_file_location("_drift_checker", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_drift_checker_reports_zero_unknown_for_known_client_sets():
    """用已知的 android/wearos wire 值集喂进 classify:应零未知(server 不会拒任何一个)。

    不依赖 sibling 仓 checkout —— 直接把两客户端当前的 wire 值集内联进来,校验
    分类结果:6/2 个别名归 accepted_alias、其余 canonical 一致或客户端专有扩展,
    未知(server 会拒)必须为 0。这正是 CI strict 门禁通过的等价条件。
    """
    checker = _load_drift_checker()
    v2_values = checker.parse_v2_messagetype(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "galaxy_gateway", "protocol", "aip_v3.py")
    )

    # android 当前的"非 canonical"wire 值(别名 + 专有扩展),必须全部被接受。
    android_non_canonical = {
        "relay", "forward", "reply", "lock", "unlock", "broadcast",  # accepted_alias
        "auth", "event", "liquid_event", "phase_report", "voice_query",  # client_ext
    }
    r = checker.classify(android_non_canonical, v2_values)
    assert r["unknown"] == [], f"android 不应有 server 会拒的未知类型: {r['unknown']}"
    assert len(r["accepted_alias"]) == 6

    # wearos 当前的"非 canonical"wire 值。
    wearos_non_canonical = {
        "relay", "broadcast",  # accepted_alias
        "auth", "decision_request", "event", "liquid_event", "phase_report", "voice_query",
    }
    r2 = checker.classify(wearos_non_canonical, v2_values)
    assert r2["unknown"] == [], f"wearos 不应有 server 会拒的未知类型: {r2['unknown']}"
    assert len(r2["accepted_alias"]) == 2


def test_unregistered_client_type_is_flagged_as_unknown():
    """反向:一个既非 canonical、非别名、非白名单的编造类型,必须被判为 unknown(门禁应拦)。"""
    checker = _load_drift_checker()
    r = checker.classify({"totally_new_unregistered_type"}, {"heartbeat", "relay_request"})
    assert r["unknown"] == ["totally_new_unregistered_type"]
