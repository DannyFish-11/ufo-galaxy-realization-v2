"""tests/test_protocol_ssot_fusion.py
=========================================

域6 · 协议融合:galaxy_gateway/protocol/aip_v3.MessageType 是 message-type 字符串的
唯一权威(SSOT)。

- drift 守卫:core/schemas/aip_v3.MsgType 的每个 wire 值必须存在于 SSOT
  (此前二者都自称 canonical 且漂移了 4 个 NATS 值——已提升进 SSOT,本测试钉死)。
- 客户端短别名(relay/forward/reply/lock/unlock/broadcast)经 _LEGACY_TYPE_MAP
  归一化到 canonical 长名——此前短名被枚举收留但无人消费,relay/lock 静默丢弃。
- 死成员 FILE_DELETE/FILE_LIST(全仓零足迹)已删。
"""

from __future__ import annotations

from galaxy_gateway.protocol.aip_v3 import MessageType
from galaxy_gateway.protocol.compat import _LEGACY_TYPE_MAP


class TestSSOTDriftGuard:
    def test_core_schemas_values_subset_of_gateway_ssot(self):
        from core.schemas.aip_v3 import MsgType

        gateway_values = {m.value for m in MessageType}
        missing = {m.value for m in MsgType} - gateway_values
        assert missing == set(), (
            f"core/schemas/aip_v3.MsgType 漂移出 SSOT 的 wire 值: {missing}"
            "(新增消息类型必须先进 galaxy_gateway/protocol/aip_v3.MessageType)"
        )

    def test_promoted_nats_values_present(self):
        vals = {m.value for m in MessageType}
        assert {"capability_query", "webrtc_bind", "webrtc_unbind", "webrtc_transport_state"} <= vals

    def test_dead_members_removed(self):
        vals = {m.value for m in MessageType}
        assert "file_delete" not in vals and "file_list" not in vals


class TestClientAliasNormalization:
    def test_short_aliases_map_to_canonical(self):
        assert _LEGACY_TYPE_MAP["relay"] is MessageType.RELAY_REQUEST
        assert _LEGACY_TYPE_MAP["forward"] is MessageType.RELAY_FORWARD
        assert _LEGACY_TYPE_MAP["reply"] is MessageType.RELAY_REPLY
        assert _LEGACY_TYPE_MAP["lock"] is MessageType.COORD_LOCK
        assert _LEGACY_TYPE_MAP["unlock"] is MessageType.COORD_UNLOCK
        assert _LEGACY_TYPE_MAP["broadcast"] is MessageType.COORD_BROADCAST

    def test_alias_values_still_parse_as_enum(self):
        # 直接 v3 解析路径不回退错误:短名仍是合法枚举值(归一化层负责升级)。
        assert MessageType("relay") is MessageType.RELAY
