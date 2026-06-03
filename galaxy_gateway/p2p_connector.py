"""
Galaxy - P2P 连接器

功能：
1. P2P 直连建立（设备间直接通信）
2. NAT 穿透（STUN/TURN）
3. 连接管理和维护
4. 数据同步

作者：Manus AI
日期：2026-01-22
版本：1.0
"""

import asyncio
import logging
import os
import socket as sock_module
import struct
import json
import time
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import aiohttp

logger = logging.getLogger(__name__)

# ============================================================================
# 配置
# ============================================================================

class P2PConfig:
    """P2P 配置"""
    # STUN 服务器列表（用于 NAT 穿透）
    STUN_SERVERS = [
        ("stun.l.google.com", 19302),
        ("stun1.l.google.com", 19302),
        ("stun2.l.google.com", 19302),
        ("stun3.l.google.com", 19302),
        ("stun4.l.google.com", 19302),
    ]
    
    # TURN 服务器（如果 STUN 失败）
    TURN_SERVER = None  # 需要自己部署或使用第三方服务
    
    # 连接超时
    CONNECTION_TIMEOUT = 10  # 秒
    
    # 心跳间隔
    HEARTBEAT_INTERVAL = 30  # 秒
    
    # 重连间隔
    RECONNECT_INTERVAL = 5  # 秒

# ============================================================================
# 枚举
# ============================================================================

class ConnectionState(Enum):
    """连接状态"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    FAILED = "failed"

class NATType(Enum):
    """NAT 类型"""
    UNKNOWN = "unknown"
    OPEN = "open"                          # 无 NAT
    FULL_CONE = "full_cone"                # 完全锥形 NAT
    RESTRICTED_CONE = "restricted_cone"    # 限制锥形 NAT
    PORT_RESTRICTED_CONE = "port_restricted_cone"  # 端口限制锥形 NAT
    SYMMETRIC = "symmetric"                # 对称 NAT

# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class PeerInfo:
    """对等节点信息"""
    device_id: str
    device_name: str
    local_ip: str
    local_port: int
    public_ip: Optional[str] = None
    public_port: Optional[int] = None
    nat_type: NATType = NATType.UNKNOWN

@dataclass
class P2PConnection:
    """P2P 连接"""
    peer: PeerInfo
    state: ConnectionState = ConnectionState.DISCONNECTED
    sock: Optional[sock_module.socket] = None
    reader: Optional[asyncio.StreamReader] = None
    writer: Optional[asyncio.StreamWriter] = None
    last_heartbeat: float = field(default_factory=time.time)
    
# ============================================================================
# STUN 客户端（用于 NAT 穿透）
# ============================================================================

class STUNClient:
    """STUN 客户端 - 用于发现公网 IP 和端口"""
    
    # STUN 消息类型
    BINDING_REQUEST = 0x0001
    BINDING_RESPONSE = 0x0101
    
    # STUN 属性
    MAPPED_ADDRESS = 0x0001
    XOR_MAPPED_ADDRESS = 0x0020
    
    @staticmethod
    def _blocking_stun_request(
        local_port: int,
        stun_server: Tuple[str, int]
    ) -> Tuple[Optional[str], Optional[int]]:
        """阻塞式 STUN 请求（在线程池中运行以避免阻塞事件循环）。"""
        sock = None
        try:
            # 创建 UDP socket
            sock = sock_module.socket(sock_module.AF_INET, sock_module.SOCK_DGRAM)
            sock.bind(('0.0.0.0', local_port))
            sock.settimeout(5)

            # 构建 STUN Binding Request
            transaction_id = os.urandom(12)
            message = struct.pack('!HHI', STUNClient.BINDING_REQUEST, 0, 0x2112A442) + transaction_id

            # 发送请求
            sock.sendto(message, stun_server)

            # 接收响应
            data, addr = sock.recvfrom(1024)

            # 解析响应
            if len(data) < 20:
                return None, None

            msg_type, msg_len, magic_cookie = struct.unpack('!HHI', data[:8])

            if msg_type != STUNClient.BINDING_RESPONSE:
                return None, None

            # 解析属性
            offset = 20
            while offset < len(data):
                if offset + 4 > len(data):
                    break

                attr_type, attr_len = struct.unpack('!HH', data[offset:offset+4])
                offset += 4

                if attr_type == STUNClient.XOR_MAPPED_ADDRESS:
                    # XOR-MAPPED-ADDRESS
                    if attr_len >= 8:
                        family, port, ip_bytes = struct.unpack('!BBH4s', data[offset:offset+8])

                        # XOR 解码
                        port ^= (magic_cookie >> 16)
                        ip = '.'.join(str(b ^ ((magic_cookie >> (24 - i*8)) & 0xFF)) for i, b in enumerate(ip_bytes))

                        return ip, port

                offset += attr_len

            return None, None
        except Exception as e:
            logger.warning("STUN 错误: %s", e)
            return None, None
        finally:
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass

    @staticmethod
    async def get_public_address(
        local_port: int,
        stun_server: Tuple[str, int] = None
    ) -> Tuple[Optional[str], Optional[int]]:
        """
        获取公网地址（使用 asyncio.to_thread 包装阻塞操作）

        Args:
            local_port: 本地端口
            stun_server: STUN 服务器（可选）

        Returns:
            (public_ip, public_port) 或 (None, None)
        """
        if not stun_server:
            stun_server = P2PConfig.STUN_SERVERS[0]

        return await asyncio.to_thread(
            STUNClient._blocking_stun_request, local_port, stun_server
        )

# ============================================================================
# P2P 连接器
# ============================================================================

class P2PConnector:
    """P2P 连接器 - 管理设备间的 P2P 连接"""
    
    def __init__(self, local_device: PeerInfo):
        self.local_device = local_device
        self.connections: Dict[str, P2PConnection] = {}
        self.server_task: Optional[asyncio.Task] = None
        self.heartbeat_task: Optional[asyncio.Task] = None
    
    async def start(self):
        """启动 P2P 连接器"""
        # 发现公网地址
        public_ip, public_port = await STUNClient.get_public_address(
            self.local_device.local_port
        )
        
        if public_ip and public_port:
            self.local_device.public_ip = public_ip
            self.local_device.public_port = public_port
            print(f"公网地址: {public_ip}:{public_port}")
        else:
            print("无法获取公网地址，将只支持局域网连接")
        
        # 启动服务器（监听连接）
        self.server_task = asyncio.create_task(self._run_server())
        
        # 启动心跳任务
        self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())
    
    async def stop(self):
        """停止 P2P 连接器"""
        # 关闭所有连接
        for conn in self.connections.values():
            await self._close_connection(conn)
        
        # 停止任务
        if self.server_task:
            self.server_task.cancel()
        
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
    
    async def connect(self, peer: PeerInfo) -> bool:
        """
        连接到对等节点
        
        Args:
            peer: 对等节点信息
        
        Returns:
            bool: 是否成功连接
        """
        if peer.device_id in self.connections:
            conn = self.connections[peer.device_id]
            if conn.state == ConnectionState.CONNECTED:
                return True
        
        # 创建连接
        conn = P2PConnection(peer=peer, state=ConnectionState.CONNECTING)
        self.connections[peer.device_id] = conn
        
        try:
            # 尝试连接（先尝试局域网，再尝试公网）
            connected = False
            
            # 尝试 1: 局域网直连
            if peer.local_ip:
                try:
                    reader, writer = await asyncio.wait_for(
                        asyncio.open_connection(peer.local_ip, peer.local_port),
                        timeout=P2PConfig.CONNECTION_TIMEOUT
                    )
                    conn.reader = reader
                    conn.writer = writer
                    connected = True
                    print(f"通过局域网连接到 {peer.device_id}")
                except Exception as e:
                    print(f"局域网连接失败 ({peer.device_id}): {e}")
            
            # 尝试 2: 公网直连
            if not connected and peer.public_ip:
                try:
                    reader, writer = await asyncio.wait_for(
                        asyncio.open_connection(peer.public_ip, peer.public_port),
                        timeout=P2PConfig.CONNECTION_TIMEOUT
                    )
                    conn.reader = reader
                    conn.writer = writer
                    connected = True
                    print(f"通过公网连接到 {peer.device_id}")
                except Exception as e:
                    print(f"公网连接失败 ({peer.device_id}): {e}")
            
            if connected:
                conn.state = ConnectionState.CONNECTED
                conn.last_heartbeat = time.time()
                
                # 发送握手消息
                await self._send_handshake(conn)
                
                # 启动接收任务
                asyncio.create_task(self._receive_loop(conn))
                
                return True
            else:
                conn.state = ConnectionState.FAILED
                return False
        
        except Exception as e:
            print(f"连接失败: {e}")
            conn.state = ConnectionState.FAILED
            return False
    
    async def send(self, device_id: str, data: bytes) -> bool:
        """
        发送数据到对等节点
        
        Args:
            device_id: 设备 ID
            data: 数据
        
        Returns:
            bool: 是否成功发送
        """
        if device_id not in self.connections:
            return False
        
        conn = self.connections[device_id]
        
        if conn.state != ConnectionState.CONNECTED or not conn.writer:
            return False
        
        try:
            # 发送数据长度（4 字节）+ 数据
            conn.writer.write(struct.pack('!I', len(data)))
            conn.writer.write(data)
            await conn.writer.drain()
            return True
        except Exception as e:
            print(f"发送失败: {e}")
            await self._close_connection(conn)
            return False
    
    async def _run_server(self):
        """运行服务器（监听连接）"""
        try:
            server = await asyncio.start_server(
                self._handle_client,
                '0.0.0.0',
                self.local_device.local_port
            )
            
            print(f"P2P 服务器启动: {self.local_device.local_ip}:{self.local_device.local_port}")
            
            async with server:
                await server.serve_forever()
        except Exception as e:
            print(f"服务器错误: {e}")
    
    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """处理客户端连接"""
        try:
            # 接收握手消息
            peer_info = await self._receive_handshake(reader)
            
            if not peer_info:
                writer.close()
                await writer.wait_closed()
                return
            
            # 创建连接
            conn = P2PConnection(
                peer=peer_info,
                state=ConnectionState.CONNECTED,
                reader=reader,
                writer=writer,
                last_heartbeat=time.time()
            )
            
            self.connections[peer_info.device_id] = conn
            
            print(f"接受来自 {peer_info.device_id} 的连接")
            
            # 启动接收任务
            await self._receive_loop(conn)
        
        except Exception as e:
            print(f"处理客户端错误: {e}")
            writer.close()
            await writer.wait_closed()
    
    async def _send_handshake(self, conn: P2PConnection):
        """发送握手消息"""
        handshake = {
            "type": "handshake",
            "device_id": self.local_device.device_id,
            "device_name": self.local_device.device_name,
            "local_ip": self.local_device.local_ip,
            "local_port": self.local_device.local_port,
            "public_ip": self.local_device.public_ip,
            "public_port": self.local_device.public_port
        }
        
        data = json.dumps(handshake).encode('utf-8')
        conn.writer.write(struct.pack('!I', len(data)))
        conn.writer.write(data)
        await conn.writer.drain()
    
    async def _receive_handshake(self, reader: asyncio.StreamReader) -> Optional[PeerInfo]:
        """接收握手消息"""
        try:
            # 读取长度
            length_data = await asyncio.wait_for(reader.readexactly(4), timeout=5)
            length = struct.unpack('!I', length_data)[0]
            
            # 读取数据
            data = await asyncio.wait_for(reader.readexactly(length), timeout=5)
            handshake = json.loads(data.decode('utf-8'))
            
            if handshake.get("type") != "handshake":
                return None
            
            return PeerInfo(
                device_id=handshake["device_id"],
                device_name=handshake["device_name"],
                local_ip=handshake["local_ip"],
                local_port=handshake["local_port"],
                public_ip=handshake.get("public_ip"),
                public_port=handshake.get("public_port")
            )
        except Exception:
            return None

    async def _receive_loop(self, conn: P2PConnection):
        """接收循环"""
        try:
            while conn.state == ConnectionState.CONNECTED:
                # 读取数据长度
                length_data = await conn.reader.readexactly(4)
                length = struct.unpack('!I', length_data)[0]
                
                # 读取数据
                data = await conn.reader.readexactly(length)
                
                # 处理数据
                await self._handle_data(conn, data)
                
                # 更新心跳时间
                conn.last_heartbeat = time.time()
        
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"接收错误: {e}")
            await self._close_connection(conn)
    
    async def _handle_data(self, conn: P2PConnection, data: bytes):
        """处理接收到的数据"""
        try:
            message = json.loads(data.decode('utf-8'))
            msg_type = message.get("type")
            
            if msg_type == "heartbeat":
                # 心跳消息已在接收循环中更新时间，此处无需额外处理
                return
                
            logger.info(f"📩 Received P2P message from {conn.peer.device_id}: {msg_type}")
            # 触发业务逻辑回调（此处可扩展）
        except Exception as e:
            logger.error(f"❌ Error handling P2P data: {e}")
    
    async def _heartbeat_loop(self):
        """心跳循环"""
        while True:
            try:
                await asyncio.sleep(P2PConfig.HEARTBEAT_INTERVAL)
                
                current_time = time.time()
                
                for device_id, conn in list(self.connections.items()):
                    if conn.state != ConnectionState.CONNECTED:
                        continue
                    
                    # 检查心跳超时
                    if current_time - conn.last_heartbeat > P2PConfig.HEARTBEAT_INTERVAL * 2:
                        print(f"连接 {device_id} 心跳超时，关闭连接")
                        await self._close_connection(conn)
                        continue
                    
                    # 发送心跳
                    heartbeat = json.dumps({"type": "heartbeat", "timestamp": current_time}).encode('utf-8')
                    try:
                        conn.writer.write(struct.pack('!I', len(heartbeat)))
                        conn.writer.write(heartbeat)
                        await conn.writer.drain()
                    except Exception:
                        await self._close_connection(conn)
            
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"心跳错误: {e}")
    
    async def _close_connection(self, conn: P2PConnection):
        """关闭连接"""
        if conn.writer:
            conn.writer.close()
            await conn.writer.wait_closed()
        
        conn.state = ConnectionState.DISCONNECTED
        
        if conn.peer.device_id in self.connections:
            del self.connections[conn.peer.device_id]

# ============================================================================
# 使用示例
# ============================================================================

async def example_usage():
    """使用示例"""
    print("="*80)
    print("P2P 连接器示例")
    print("="*80)
    
    # 创建两个设备
    device_a = PeerInfo(
        device_id="phone_a",
        device_name="手机A",
        local_ip="127.0.0.1",
        local_port=9001
    )
    
    device_b = PeerInfo(
        device_id="phone_b",
        device_name="手机B",
        local_ip="127.0.0.1",
        local_port=9002
    )
    
    # 创建 P2P 连接器
    connector_a = P2PConnector(device_a)
    connector_b = P2PConnector(device_b)
    
    # 启动
    await connector_a.start()
    await connector_b.start()
    
    # 等待启动完成
    await asyncio.sleep(1)
    
    # 设备 A 连接到设备 B
    print("\n设备 A 连接到设备 B...")
    success = await connector_a.connect(device_b)
    print(f"连接结果: {'成功' if success else '失败'}")
    
    if success:
        # 发送数据
        print("\n设备 A 发送数据到设备 B...")
        data = b"Hello from Device A!"
        await connector_a.send(device_b.device_id, data)
        
        # 等待接收
        await asyncio.sleep(1)
    
    # 清理
    await connector_a.stop()
    await connector_b.stop()
    
    print("\n" + "="*80)
    print("P2P 连接器示例完成")
    print("="*80)

if __name__ == "__main__":
    asyncio.run(example_usage())
