"""
Galaxy - AIP v2.0 协议（Agent Interaction Protocol）

.. deprecated::
    **此模块已弃用，禁止直接导入。**
    所有代码必须改用 ``galaxy_gateway.protocol.aip_v3``（v3 单一事实源）。
    Legacy 输入请通过 ``galaxy_gateway.protocol.compat.parse_message_compat`` 进行转换。

    Importing this module will raise :class:`ImportError`.
"""

raise ImportError(
    "galaxy_gateway.aip_protocol_v2 is DEPRECATED and must not be imported directly. "
    "Use 'galaxy_gateway.protocol.aip_v3' for all protocol types, or "
    "'galaxy_gateway.protocol.compat.parse_message_compat' for legacy→v3 conversion."
)
