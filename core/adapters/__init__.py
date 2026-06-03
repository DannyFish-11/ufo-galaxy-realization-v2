"""
core/adapters/ — AIP v3 传输适配器集合
"""

from core.adapters.websocket_adapter import WebSocketAdapter
from core.adapters.nats_adapter import NATSAdapter

__all__ = ["WebSocketAdapter", "NATSAdapter"]
