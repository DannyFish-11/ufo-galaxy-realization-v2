"""
Node 71 - Device Discovery Module
设备发现模块，支持 mDNS、UPnP 和自定义广播三种发现协议
"""
import asyncio
import socket
import json
import logging
import time
import uuid
from typing import Dict, List, Optional, Any, Callable, Set
from dataclasses import dataclass, field
from enum import Enum, auto
from datetime import datetime
import struct

from models.device import (
    Device, DeviceType, DeviceState, DiscoveryProtocol,
    Capability, ResourceConstraints, VectorClock
)

logger = logging.getLogger(__name__)


class DiscoveryEventType(str, Enum):
    """发现事件类型"""
    DEVICE_FOUND = "device_found"
    DEVICE_LOST = "device_lost"
    DEVICE_UPDATED = "device_updated"
    DISCOVERY_STARTED = "discovery_started"
    DISCOVERY_STOPPED = "discovery_stopped"
    ERROR = "error"


@dataclass
class DiscoveryEvent:
    """发现事件"""
    event_type: DiscoveryEventType
    device: Optional[Device] = None
    message: str = ""
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type.value,
            "device": self.device.to_dict() if self.device else None,
            "message": self.message,
            "timestamp": self.timestamp
        }


@dataclass
class DiscoveryConfig:
    """发现配置"""
    # mDNS 配置
    mdns_enabled: bool = True
    mdns_service_type: str = "_ufo-galaxy._tcp.local."
    mdns_scan_interval: float = 30.0
    
    # UPnP 配置
    upnp_enabled: bool = True
    upnp_search_target: str = "urn:schemas-ufo-galaxy:device:Coordinator:1"
    upnp_scan_interval: float = 60.0
    
    # 广播配置
    broadcast_enabled: bool = True
    broadcast_port: int = 37021
    broadcast_address: str = "239.255.255.250"
    broadcast_interval: float = 10.0
    
    # 通用配置
    heartbeat_timeout: float = 60.0
    discovery_timeout: float = 5.0
    max_devices: int = 1000
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "mdns_enabled": self.mdns_enabled,
            "mdns_service_type": self.mdns_service_type,
            "mdns_scan_interval": self.mdns_scan_interval,
            "upnp_enabled": self.upnp_enabled,
            "upnp_search_target": self.upnp_search_target,
            "upnp_scan_interval": self.upnp_scan_interval,
            "broadcast_enabled": self.broadcast_enabled,
            "broadcast_port": self.broadcast_port,
            "broadcast_address": self.broadcast_address,
            "broadcast_interval": self.broadcast_interval,
            "heartbeat_timeout": self.heartbeat_timeout,
            "discovery_timeout": self.discovery_timeout,
            "max_devices": self.max_devices
        }


class BroadcastDiscovery:
    """
    自定义广播发现协议
    使用 UDP 多播进行设备发现
    """
    
    DISCOVERY_MESSAGE = "UFO_GALAXY_DISCOVER"
    RESPONSE_MESSAGE = "UFO_GALAXY_RESPONSE"
    
    def __init__(self, config: DiscoveryConfig, node_id: str):
        self.config = config
        self.node_id = node_id
        self._socket: Optional[socket.socket] = None
        self._running = False
        self._discovered: Dict[str, Device] = {}
        self._event_handlers: List[Callable[[DiscoveryEvent], None]] = []
        self._listen_task: Optional[asyncio.Task] = None
        self._broadcast_task: Optional[asyncio.Task] = None
        
    def add_event_handler(self, handler: Callable[[DiscoveryEvent], None]) -> None:
        """添加事件处理器"""
        self._event_handlers.append(handler)
    
    def _emit_event(self, event: DiscoveryEvent) -> None:
        """发送事件"""
        for handler in self._event_handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error(f"Event handler error: {e}")
    
    async def start(self) -> bool:
        """启动广播发现"""
        try:
            # 创建 UDP socket
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            # 绑定端口
            self._socket.bind(("", self.config.broadcast_port))
            
            # 加入多播组
            mreq = struct.pack(
                "4sl",
                socket.inet_aton(self.config.broadcast_address),
                socket.INADDR_ANY
            )
            self._socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            
            # 设置非阻塞
            self._socket.setblocking(False)
            
            self._running = True
            
            # 启动监听任务
            self._listen_task = asyncio.create_task(self._listen_loop())
            
            # 启动广播任务
            self._broadcast_task = asyncio.create_task(self._broadcast_loop())
            
            logger.info(f"Broadcast discovery started on port {self.config.broadcast_port}")
            self._emit_event(DiscoveryEvent(
                event_type=DiscoveryEventType.DISCOVERY_STARTED,
                message="Broadcast discovery started"
            ))
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to start broadcast discovery: {e}")
            self._emit_event(DiscoveryEvent(
                event_type=DiscoveryEventType.ERROR,
                message=f"Failed to start: {e}"
            ))
            return False
    
    async def stop(self) -> None:
        """停止广播发现"""
        self._running = False
        
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
        
        if self._broadcast_task:
            self._broadcast_task.cancel()
            try:
                await self._broadcast_task
            except asyncio.CancelledError:
                pass
        
        if self._socket:
            self._socket.close()
            self._socket = None
        
        logger.info("Broadcast discovery stopped")
        self._emit_event(DiscoveryEvent(
            event_type=DiscoveryEventType.DISCOVERY_STOPPED,
            message="Broadcast discovery stopped"
        ))
    
    async def _listen_loop(self) -> None:
        """监听循环"""
        loop = asyncio.get_event_loop()
        
        while self._running:
            try:
                data, addr = await loop.sock_recvfrom(self._socket, 4096)
                await self._handle_message(data, addr)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Listen error: {e}")
                await asyncio.sleep(0.1)
    
    async def _handle_message(self, data: bytes, addr: tuple) -> None:
        """处理接收到的消息"""
        try:
            message = data.decode("utf-8")
            
            if message.startswith(self.DISCOVERY_MESSAGE):
                # 收到发现请求，发送响应
                await self._send_response(addr)
                
            elif message.startswith(self.RESPONSE_MESSAGE):
                # 收到响应，解析设备信息
                await self._parse_response(message, addr)
                
        except Exception as e:
            logger.error(f"Error handling message: {e}")
    
    async def _send_response(self, addr: tuple) -> None:
        """发送响应消息"""
        try:
            response_data = {
                "type": self.RESPONSE_MESSAGE,
                "node_id": self.node_id,
                "timestamp": time.time()
            }
            message = json.dumps(response_data)
            
            self._socket.sendto(
                message.encode("utf-8"),
                (addr[0], self.config.broadcast_port)
            )
        except Exception as e:
            logger.error(f"Error sending response: {e}")
    
    async def _parse_response(self, message: str, addr: tuple) -> None:
        """解析响应消息"""
        try:
            # 移除前缀
            json_str = message[len(self.RESPONSE_MESSAGE):].strip()
            if not json_str:
                return
            
            data = json.loads(json_str)
            
            device_id = data.get("node_id")
            if not device_id:
                return
            
            # 检查是否已发现
            if device_id in self._discovered:
                # 更新心跳
                self._discovered[device_id].update_heartbeat()
                return
            
            # 创建新设备
            device = Device(
                device_id=device_id,
                name=data.get("name", f"Device-{device_id[:8]}"),
                device_type=DeviceType(data.get("device_type", "unknown")),
                host=addr[0],
                port=data.get("port", 0),
                state=DeviceState.IDLE,
                discovery_protocol=DiscoveryProtocol.BROADCAST,
                capabilities=[
                    Capability.from_dict(cap) for cap in data.get("capabilities", [])
                ],
                metadata=data.get("metadata", {})
            )
            
            self._discovered[device_id] = device
            
            # 发送发现事件
            self._emit_event(DiscoveryEvent(
                event_type=DiscoveryEventType.DEVICE_FOUND,
                device=device,
                message=f"Device discovered via broadcast: {device_id}"
            ))
            
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON in response: {message}")
        except Exception as e:
            logger.error(f"Error parsing response: {e}")
    
    async def _broadcast_loop(self) -> None:
        """广播循环"""
        while self._running:
            try:
                # 发送发现消息
                message = json.dumps({
                    "type": self.DISCOVERY_MESSAGE,
                    "node_id": self.node_id,
                    "timestamp": time.time()
                })
                
                self._socket.sendto(
                    message.encode("utf-8"),
                    (self.config.broadcast_address, self.config.broadcast_port)
                )
                
                logger.debug("Broadcast discovery message sent")
                
            except Exception as e:
                logger.error(f"Broadcast error: {e}")
            
            await asyncio.sleep(self.config.broadcast_interval)
    
    def get_discovered_devices(self) -> List[Device]:
        """获取已发现的设备"""
        return list(self._discovered.values())
    
    def remove_device(self, device_id: str) -> bool:
        """移除设备"""
        if device_id in self._discovered:
            device = self._discovered.pop(device_id)
            self._emit_event(DiscoveryEvent(
                event_type=DiscoveryEventType.DEVICE_LOST,
                device=device,
                message=f"Device removed: {device_id}"
            ))
            return True
        return False


class MDNSDiscovery:
    """
    mDNS 发现协议
    使用 zeroconf 库实现
    """
    
    def __init__(self, config: DiscoveryConfig, node_id: str):
        self.config = config
        self.node_id = node_id
        self._zeroconf = None
        self._browser = None
        self._service_info = None
        self._running = False
        self._discovered: Dict[str, Device] = {}
        self._event_handlers: List[Callable[[DiscoveryEvent], None]] = []
        
    def add_event_handler(self, handler: Callable[[DiscoveryEvent], None]) -> None:
        """添加事件处理器"""
        self._event_handlers.append(handler)
    
    def _emit_event(self, event: DiscoveryEvent) -> None:
        """发送事件"""
        for handler in self._event_handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error(f"Event handler error: {e}")
    
    async def start(self) -> bool:
        """启动 mDNS 发现"""
        try:
            from zeroconf import Zeroconf, ServiceBrowser, ServiceInfo
            
            self._zeroconf = Zeroconf()
            
            # 注册服务
            self._service_info = ServiceInfo(
                self.config.mdns_service_type,
                f"{self.node_id}.{self.config.mdns_service_type}",
                addresses=[socket.inet_aton("0.0.0.0")],
                port=8071,
                properties={
                    "node_id": self.node_id,
                    "type": "coordinator"
                }
            )
            
            await self._zeroconf.async_register_service(self._service_info)
            
            # 启动服务浏览器
            self._browser = ServiceBrowser(
                self._zeroconf,
                self.config.mdns_service_type,
                handlers=[self._on_service_state_change]
            )
            
            self._running = True
            
            logger.info(f"mDNS discovery started for {self.config.mdns_service_type}")
            self._emit_event(DiscoveryEvent(
                event_type=DiscoveryEventType.DISCOVERY_STARTED,
                message="mDNS discovery started"
            ))
            
            return True
            
        except ImportError:
            logger.warning("zeroconf not installed, mDNS discovery disabled")
            return False
        except Exception as e:
            logger.error(f"Failed to start mDNS discovery: {e}")
            return False
    
    def _on_service_state_change(self, zeroconf, service_type, name, state_change) -> None:
        """服务状态变化回调"""
        try:
            from zeroconf import ServiceStateChange
            
            if state_change == ServiceStateChange.Added:
                info = zeroconf.get_service_info(service_type, name)
                if info:
                    self._handle_service_added(info)
            elif state_change == ServiceStateChange.Removed:
                self._handle_service_removed(name)
                
        except Exception as e:
            logger.error(f"Error handling service state change: {e}")
    
    def _handle_service_added(self, info) -> None:
        """处理服务添加"""
        try:
            device_id = info.name.split(".")[0]
            
            if device_id == self.node_id:
                return  # 忽略自己
            
            if device_id in self._discovered:
                self._discovered[device_id].update_heartbeat()
                return
            
            # 获取地址
            addresses = info.addresses
            host = socket.inet_ntoa(addresses[0]) if addresses else "unknown"
            
            device = Device(
                device_id=device_id,
                name=info.name,
                device_type=DeviceType.UNKNOWN,
                host=host,
                port=info.port,
                state=DeviceState.IDLE,
                discovery_protocol=DiscoveryProtocol.MDNS,
                metadata=dict(info.properties) if info.properties else {}
            )
            
            self._discovered[device_id] = device
            
            self._emit_event(DiscoveryEvent(
                event_type=DiscoveryEventType.DEVICE_FOUND,
                device=device,
                message=f"Device discovered via mDNS: {device_id}"
            ))
            
        except Exception as e:
            logger.error(f"Error handling service added: {e}")
    
    def _handle_service_removed(self, name: str) -> None:
        """处理服务移除"""
        device_id = name.split(".")[0]
        
        if device_id in self._discovered:
            device = self._discovered.pop(device_id)
            self._emit_event(DiscoveryEvent(
                event_type=DiscoveryEventType.DEVICE_LOST,
                device=device,
                message=f"Device lost via mDNS: {device_id}"
            ))
    
    async def stop(self) -> None:
        """停止 mDNS 发现"""
        self._running = False
        
        if self._browser:
            self._browser.cancel()
            self._browser = None
        
        if self._zeroconf:
            if self._service_info:
                await self._zeroconf.async_unregister_service(self._service_info)
            self._zeroconf.close()
            self._zeroconf = None
        
        logger.info("mDNS discovery stopped")
        self._emit_event(DiscoveryEvent(
            event_type=DiscoveryEventType.DISCOVERY_STOPPED,
            message="mDNS discovery stopped"
        ))
    
    def get_discovered_devices(self) -> List[Device]:
        """获取已发现的设备"""
        return list(self._discovered.values())


class UPNPDiscovery:
    """
    UPnP 发现协议
    使用 SSDP 进行设备发现
    """
    
    SSDP_ADDR = "239.255.255.250"
    SSDP_PORT = 1900
    SSDP_MX = 3
    
    def __init__(self, config: DiscoveryConfig, node_id: str):
        self.config = config
        self.node_id = node_id
        self._socket: Optional[socket.socket] = None
        self._running = False
        self._discovered: Dict[str, Device] = {}
        self._event_handlers: List[Callable[[DiscoveryEvent], None]] = []
        self._listen_task: Optional[asyncio.Task] = None
        self._search_task: Optional[asyncio.Task] = None
        
    def add_event_handler(self, handler: Callable[[DiscoveryEvent], None]) -> None:
        """添加事件处理器"""
        self._event_handlers.append(handler)
    
    def _emit_event(self, event: DiscoveryEvent) -> None:
        """发送事件"""
        for handler in self._event_handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error(f"Event handler error: {e}")
    
    async def start(self) -> bool:
        """启动 UPnP 发现"""
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._socket.bind(("", self.SSDP_PORT))
            
            # 加入多播组
            mreq = struct.pack(
                "4sl",
                socket.inet_aton(self.SSDP_ADDR),
                socket.INADDR_ANY
            )
            self._socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            self._socket.setblocking(False)
            
            self._running = True
            
            self._listen_task = asyncio.create_task(self._listen_loop())
            self._search_task = asyncio.create_task(self._search_loop())
            
            logger.info("UPnP discovery started")
            self._emit_event(DiscoveryEvent(
                event_type=DiscoveryEventType.DISCOVERY_STARTED,
                message="UPnP discovery started"
            ))
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to start UPnP discovery: {e}")
            return False
    
    async def stop(self) -> None:
        """停止 UPnP 发现"""
        self._running = False
        
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
        
        if self._search_task:
            self._search_task.cancel()
            try:
                await self._search_task
            except asyncio.CancelledError:
                pass
        
        if self._socket:
            self._socket.close()
            self._socket = None
        
        logger.info("UPnP discovery stopped")
        self._emit_event(DiscoveryEvent(
            event_type=DiscoveryEventType.DISCOVERY_STOPPED,
            message="UPnP discovery stopped"
        ))
    
    async def _listen_loop(self) -> None:
        """监听循环"""
        loop = asyncio.get_event_loop()
        
        while self._running:
            try:
                data, addr = await loop.sock_recvfrom(self._socket, 4096)
                await self._handle_message(data, addr)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"UPnP listen error: {e}")
                await asyncio.sleep(0.1)
    
    async def _handle_message(self, data: bytes, addr: tuple) -> None:
        """处理 SSDP 消息"""
        try:
            message = data.decode("utf-8")
            
            if "NOTIFY" in message or "HTTP/1.1 200 OK" in message:
                await self._parse_ssdp_response(message, addr)
                
        except Exception as e:
            logger.error(f"Error handling SSDP message: {e}")
    
    async def _parse_ssdp_response(self, message: str, addr: tuple) -> None:
        """解析 SSDP 响应"""
        try:
            lines = message.split("\r\n")
            headers = {}
            
            for line in lines[1:]:
                if ":" in line:
                    key, value = line.split(":", 1)
                    headers[key.strip().lower()] = value.strip()
            
            usn = headers.get("usn", "")
            device_id = usn.split(":")[-1] if usn else str(uuid.uuid4())
            
            if device_id in self._discovered:
                self._discovered[device_id].update_heartbeat()
                return
            
            location = headers.get("location", "")
            server = headers.get("server", "")
            
            device = Device(
                device_id=device_id,
                name=headers.get("friendlyname", f"UPnP-{device_id[:8]}"),
                device_type=DeviceType.UNKNOWN,
                host=addr[0],
                port=0,
                state=DeviceState.IDLE,
                discovery_protocol=DiscoveryProtocol.UPNP,
                metadata={
                    "location": location,
                    "server": server,
                    "st": headers.get("st", ""),
                    "usn": usn
                }
            )
            
            self._discovered[device_id] = device
            
            self._emit_event(DiscoveryEvent(
                event_type=DiscoveryEventType.DEVICE_FOUND,
                device=device,
                message=f"Device discovered via UPnP: {device_id}"
            ))
            
        except Exception as e:
            logger.error(f"Error parsing SSDP response: {e}")
    
    async def _search_loop(self) -> None:
        """搜索循环"""
        while self._running:
            try:
                await self._send_search()
            except Exception as e:
                logger.error(f"UPnP search error: {e}")
            
            await asyncio.sleep(self.config.upnp_scan_interval)
    
    async def _send_search(self) -> None:
        """发送 SSDP 搜索请求"""
        search_message = (
            f"M-SEARCH * HTTP/1.1\r\n"
            f"HOST: {self.SSDP_ADDR}:{self.SSDP_PORT}\r\n"
            f"MAN: \"ssdp:discover\"\r\n"
            f"MX: {self.SSDP_MX}\r\n"
            f"ST: {self.config.upnp_search_target}\r\n"
            f"\r\n"
        )
        
        self._socket.sendto(
            search_message.encode("utf-8"),
            (self.SSDP_ADDR, self.SSDP_PORT)
        )
        
        logger.debug("UPnP search message sent")
    
    def get_discovered_devices(self) -> List[Device]:
        """获取已发现的设备"""
        return list(self._discovered.values())


class DeviceDiscovery:
    """
    设备发现服务
    统一管理多种发现协议
    """
    
    def __init__(self, config: DiscoveryConfig, node_id: str):
        self.config = config
        self.node_id = node_id
        
        # 发现协议实例
        self._broadcast: Optional[BroadcastDiscovery] = None
        self._mdns: Optional[MDNSDiscovery] = None
        self._upnp: Optional[UPNPDiscovery] = None
        
        # 已发现设备
        self._devices: Dict[str, Device] = {}
        
        # 事件处理器
        self._event_handlers: List[Callable[[DiscoveryEvent], None]] = []
        
        # 运行状态
        self._running = False
        self._cleanup_task: Optional[asyncio.Task] = None
        
    def add_event_handler(self, handler: Callable[[DiscoveryEvent], None]) -> None:
        """添加事件处理器"""
        self._event_handlers.append(handler)
    
    def _emit_event(self, event: DiscoveryEvent) -> None:
        """发送事件"""
        for handler in self._event_handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error(f"Event handler error: {e}")
    
    async def start(self) -> bool:
        """启动设备发现服务"""
        if self._running:
            return True
        
        self._running = True
        
        # 启动广播发现
        if self.config.broadcast_enabled:
            self._broadcast = BroadcastDiscovery(self.config, self.node_id)
            self._broadcast.add_event_handler(self._handle_discovery_event)
            await self._broadcast.start()
        
        # 启动 mDNS 发现
        if self.config.mdns_enabled:
            self._mdns = MDNSDiscovery(self.config, self.node_id)
            self._mdns.add_event_handler(self._handle_discovery_event)
            await self._mdns.start()
        
        # 启动 UPnP 发现
        if self.config.upnp_enabled:
            self._upnp = UPNPDiscovery(self.config, self.node_id)
            self._upnp.add_event_handler(self._handle_discovery_event)
            await self._upnp.start()
        
        # 启动清理任务
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        
        logger.info("Device discovery service started")
        return True
    
    async def stop(self) -> None:
        """停止设备发现服务"""
        self._running = False
        
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        if self._broadcast:
            await self._broadcast.stop()
        
        if self._mdns:
            await self._mdns.stop()
        
        if self._upnp:
            await self._upnp.stop()
        
        logger.info("Device discovery service stopped")
    
    def _handle_discovery_event(self, event: DiscoveryEvent) -> None:
        """处理发现事件"""
        if event.event_type == DiscoveryEventType.DEVICE_FOUND:
            if event.device:
                device_id = event.device.device_id
                if device_id not in self._devices:
                    self._devices[device_id] = event.device
                    self._emit_event(event)
                else:
                    # 更新心跳
                    self._devices[device_id].update_heartbeat()
        
        elif event.event_type == DiscoveryEventType.DEVICE_LOST:
            if event.device:
                device_id = event.device.device_id
                if device_id in self._devices:
                    del self._devices[device_id]
                    self._emit_event(event)
        
        else:
            self._emit_event(event)
    
    async def _cleanup_loop(self) -> None:
        """清理过期设备"""
        while self._running:
            try:
                current_time = time.time()
                expired = []
                
                for device_id, device in self._devices.items():
                    if current_time - device.last_heartbeat > self.config.heartbeat_timeout:
                        expired.append(device_id)
                
                for device_id in expired:
                    device = self._devices.pop(device_id)
                    self._emit_event(DiscoveryEvent(
                        event_type=DiscoveryEventType.DEVICE_LOST,
                        device=device,
                        message=f"Device expired: {device_id}"
                    ))
                
            except Exception as e:
                logger.error(f"Cleanup error: {e}")
            
            await asyncio.sleep(30)
    
    def get_device(self, device_id: str) -> Optional[Device]:
        """获取设备"""
        return self._devices.get(device_id)
    
    def get_all_devices(self) -> List[Device]:
        """获取所有设备"""
        return list(self._devices.values())
    
    def get_devices_by_type(self, device_type: DeviceType) -> List[Device]:
        """按类型获取设备"""
        return [d for d in self._devices.values() if d.device_type == device_type]
    
    def get_devices_by_capability(self, capability: str) -> List[Device]:
        """按能力获取设备"""
        return [d for d in self._devices.values() if d.has_capability(capability)]
    
    def count(self) -> int:
        """设备数量"""
        return len(self._devices)
    
    async def discover_now(self) -> List[Device]:
        """立即执行发现"""
        # 触发广播发现
        if self._broadcast:
            # 广播发现会自动发送发现消息
            pass
        
        # 触发 UPnP 搜索
        if self._upnp:
            await self._upnp._send_search()
        
        # 等待响应
        await asyncio.sleep(self.config.discovery_timeout)
        
        return self.get_all_devices()
