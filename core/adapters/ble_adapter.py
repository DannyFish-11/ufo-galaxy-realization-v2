"""
core/adapters/ble_adapter.py — BLE 传输适配器

Migrated from nodes/Node_38_BLE/main.py
使用 bleak 库提供 Bluetooth LE GATT 传输。

设计:
- 通过 GATT characteristic 写入发送 AIP v3 消息
- 支持消息分片（BLE MTU 限制）
- 自动扫描 + 连接管理

UUID 定义 (Galaxy BLE Service):
- Service:          0000aip3-0000-1000-8000-00805f9b34fb
- TX (write):       0000aip3-0001-1000-8000-00805f9b34fb
- RX (notify):      0000aip3-0002-1000-8000-00805f9b34fb
- CCCD:             00002902-0000-1000-8000-00805f9b34fb
"""

import asyncio
import json
import logging
from typing import Any, Dict, Optional

from core.aip_transport import TransportAdapter

logger = logging.getLogger("Galaxy.Adapter.BLE")

# bleak 可选依赖
try:
    from bleak import BleakClient, BleakScanner
    from bleak.backends.characteristic import BleakGATTCharacteristic
    BLE_AVAILABLE = True
except ImportError:
    BLE_AVAILABLE = False
    logger.warning("bleak not installed, BLE adapter disabled. pip install bleak")

# Galaxy AIP v3 BLE UUIDs
AIP_SERVICE_UUID = "0000aip3-0000-1000-8000-00805f9b34fb"
TX_CHAR_UUID = "0000aip3-0001-1000-8000-00805f9b34fb"  # 写入
RX_CHAR_UUID = "0000aip3-0002-1000-8000-00805f9b34fb"  # 通知
CCCD_UUID = "00002902-0000-1000-8000-00805f9b34fb"

# BLE 约束
BLE_MTU = 512  # 最大传输单元


class BLEAdapter(TransportAdapter):
    """BLE GATT 传输适配器。

    通过 Bluetooth Low Energy GATT characteristic 收发 AIP v3 消息。
    适用于: 手表配对、近场设备通信、离线场景。
    """

    @property
    def transport_type(self) -> str:
        return "ble"

    def __init__(self) -> None:
        self._scanner: Optional[Any] = None
        self._clients: Dict[str, Any] = {}          # device_id → BleakClient
        self._discovered: Dict[str, str] = {}       # address → name
        self._mtu: int = BLE_MTU
        if BLE_AVAILABLE:
            self._scanner = BleakScanner()

    # -- TransportAdapter 接口 ---------------------------------------------

    async def send(self, message: Dict[str, Any], target: str) -> Dict[str, Any]:
        """通过 BLE GATT 写入发送消息。支持自动分片。"""
        if not BLE_AVAILABLE:
            return {"success": False, "error": "bleak not installed"}

        client = self._clients.get(target)
        if not client or not client.is_connected:
            return {"success": False, "error": f"BLE device '{target}' not connected"}

        try:
            payload = json.dumps(message, ensure_ascii=False).encode("utf-8")

            if len(payload) <= self._mtu:
                # 单包发送
                await client.write_gatt_char(TX_CHAR_UUID, payload, response=False)
            else:
                # 分片发送 [seq(1B) + is_last(1B) + data]
                chunks = self._fragment(payload)
                for chunk in chunks:
                    await client.write_gatt_char(TX_CHAR_UUID, chunk, response=False)

            return {"success": True, "via": "ble", "bytes": len(payload)}
        except Exception as e:
            logger.warning("BLE send to '%s' failed: %s", target, e)
            return {"success": False, "error": str(e)}

    async def is_available(self, target: str) -> bool:
        client = self._clients.get(target)
        return client is not None and client.is_connected

    async def broadcast(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """BLE 广播: 发送到所有已连接的设备。"""
        results = {}
        for device_id in list(self._clients.keys()):
            results[device_id] = await self.send(message, device_id)
        return {"success": True, "via": "ble", "results": results}

    async def close(self) -> None:
        for client in list(self._clients.values()):
            try:
                await client.disconnect()
            except Exception:
                pass
        self._clients.clear()

    # -- 设备管理 ----------------------------------------------------------

    async def scan(self, timeout: float = 10.0) -> Dict[str, str]:
        """扫描 Galaxy BLE 设备。返回 {address: name}。"""
        if not BLE_AVAILABLE:
            logger.warning("bleak not installed, scan skipped")
            return {}

        self._discovered.clear()

        def _filter(device, adv_data):
            return AIP_SERVICE_UUID in [str(u) for u in (adv_data.service_uuids or [])]

        try:
            devices = await BleakScanner.discover(timeout=timeout)
            for d in devices:
                # 检查是否广播 Galaxy Service
                if d.metadata and "uuids" in d.metadata:
                    if AIP_SERVICE_UUID in d.metadata["uuids"]:
                        self._discovered[d.address] = d.name or "Unknown"
                        logger.debug("BLE found: %s (%s)", d.name or "Unknown", d.address)

            logger.info("BLE scan complete: %d devices found", len(self._discovered))
        except Exception as e:
            logger.warning("BLE scan failed: %s", e)

        return dict(self._discovered)

    async def connect(self, address: str) -> Dict[str, Any]:
        """连接到 BLE 设备。"""
        if not BLE_AVAILABLE:
            return {"success": False, "error": "bleak not installed"}

        try:
            client = BleakClient(address)
            connected = await client.connect()
            if not connected:
                return {"success": False, "error": f"Failed to connect to {address}"}

            # 启用 RX 通知
            await client.start_notify(RX_CHAR_UUID, self._on_rx_notify)

            self._clients[address] = client
            logger.info("BLE connected: %s", address)
            return {"success": True, "address": address}

        except Exception as e:
            logger.warning("BLE connect to '%s' failed: %s", address, e)
            return {"success": False, "error": str(e)}

    async def disconnect(self, address: str) -> None:
        client = self._clients.pop(address, None)
        if client:
            try:
                await client.disconnect()
            except Exception:
                pass
            logger.info("BLE disconnected: %s", address)

    def list_connected(self) -> List[str]:
        """返回已连接的设备地址列表。"""
        return [
            addr for addr, client in self._clients.items()
            if client.is_connected
        ]

    # -- 内部 --------------------------------------------------------------

    def _fragment(self, payload: bytes) -> list:
        """将消息分片为 BLE MTU 大小的块。"""
        chunk_size = self._mtu - 2  # 预留 seq + is_last
        chunks = []
        total = len(payload)
        offset = 0
        seq = 0

        while offset < total:
            end = min(offset + chunk_size, total)
            is_last = 1 if end >= total else 0
            header = bytes([seq & 0xFF, is_last])
            chunks.append(header + payload[offset:end])
            offset = end
            seq += 1

        return chunks

    def _on_rx_notify(self, sender: Any, data: bytearray) -> None:
        """处理 BLE RX 通知（接收到的消息）。"""
        try:
            payload = bytes(data).decode("utf-8")
            message = json.loads(payload)
            logger.debug("BLE RX: %s", message.get("type", "unknown"))
            # TODO: 分发到消息处理器
        except Exception as e:
            logger.debug("BLE RX parse error: %s", e)
