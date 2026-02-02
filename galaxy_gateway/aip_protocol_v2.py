"""
UFO³ Galaxy - AIP v2.0 协议（Agent Interaction Protocol）

功能：
1. 统一的消息格式标准
2. 支持多种消息类型（文本、二进制、流）
3. 消息确认和重传机制
4. 心跳和重连机制
5. 消息编解码

作者：Manus AI
日期：2026-01-22
版本：2.0
"""

import json
import hashlib
import time
import uuid
from typing import Dict, List, Any, Optional, Union
from dataclasses import dataclass, asdict, field
from enum import Enum
from datetime import datetime, timezone
import base64

# ============================================================================
# 枚举定义
# ============================================================================

class MessageType(Enum):
    """消息类型"""
    CONTROL = "control"                    # 控制消息（任务、命令）
    TEXT = "text"                          # 文本消息
    IMAGE = "image"                        # 图片
    VIDEO = "video"                        # 视频
    AUDIO = "audio"                        # 音频
    FILE = "file"                          # 文件
    STREAM = "stream"                      # 实时流
    ACK = "ack"                           # 确认消息
    HEARTBEAT = "heartbeat"               # 心跳
    ERROR = "error"                        # 错误消息

class TransferMethod(Enum):
    """传输方式"""
    GATEWAY = "gateway"                    # 通过 Gateway 中转
    P2P = "p2p"                           # P2P 直连
    WEBRTC = "webrtc"                     # WebRTC（实时流）

class Priority(Enum):
    """优先级"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"

class ContentType(Enum):
    """内容类型"""
    JSON = "application/json"
    TEXT = "text/plain"
    JPEG = "image/jpeg"
    PNG = "image/png"
    WEBP = "image/webp"
    MP4 = "video/mp4"
    WEBM = "video/webm"
    MP3 = "audio/mp3"
    WAV = "audio/wav"
    OPUS = "audio/opus"
    BINARY = "application/octet-stream"

# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class DeviceInfo:
    """设备信息"""
    device_id: str
    device_name: str
    device_type: str
    ip_address: Optional[str] = None

@dataclass
class MessagePayload:
    """消息负载"""
    data_type: str                         # 数据类型（image, video, audio, file, text）
    format: str                            # 格式（jpeg, mp4, mp3, etc.）
    size: int                              # 大小（字节）
    checksum: str                          # 校验和（sha256）
    transfer_method: str                   # 传输方式（gateway, p2p, webrtc）
    chunks: Optional[int] = None           # 分块数（如果分块传输）
    chunk_size: Optional[int] = None       # 每块大小
    metadata: Dict[str, Any] = field(default_factory=dict)  # 元数据
    data: Optional[Union[str, bytes]] = None  # 实际数据（小文件可以直接包含）
    data_url: Optional[str] = None         # 数据 URL（大文件通过 URL 传输）

@dataclass
class AIPMessage:
    """AIP v2.0 消息"""
    version: str = "2.0"                   # 协议版本
    message_id: str = field(default_factory=lambda: f"msg_{uuid.uuid4().hex[:16]}")
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    from_device: Optional[DeviceInfo] = None
    to_device: Optional[DeviceInfo] = None
    message_type: MessageType = MessageType.TEXT
    content_type: ContentType = ContentType.JSON
    payload: Optional[MessagePayload] = None
    priority: Priority = Priority.NORMAL
    ttl: int = 3600                        # 生存时间（秒）
    requires_ack: bool = False             # 是否需要确认
    correlation_id: Optional[str] = None   # 关联 ID（用于请求-响应）
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "version": self.version,
            "message_id": self.message_id,
            "timestamp": self.timestamp,
            "from": asdict(self.from_device) if self.from_device else None,
            "to": asdict(self.to_device) if self.to_device else None,
            "type": self.message_type.value,
            "content_type": self.content_type.value,
            "payload": asdict(self.payload) if self.payload else None,
            "priority": self.priority.value,
            "ttl": self.ttl,
            "requires_ack": self.requires_ack,
            "correlation_id": self.correlation_id
        }
    
    def to_json(self) -> str:
        """转换为 JSON"""
        return json.dumps(self.to_dict(), ensure_ascii=False)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AIPMessage':
        """从字典创建"""
        from_device = DeviceInfo(**data["from"]) if data.get("from") else None
        to_device = DeviceInfo(**data["to"]) if data.get("to") else None
        payload = MessagePayload(**data["payload"]) if data.get("payload") else None
        
        return cls(
            version=data.get("version", "2.0"),
            message_id=data["message_id"],
            timestamp=data["timestamp"],
            from_device=from_device,
            to_device=to_device,
            message_type=MessageType(data["type"]),
            content_type=ContentType(data["content_type"]),
            payload=payload,
            priority=Priority(data.get("priority", "normal")),
            ttl=data.get("ttl", 3600),
            requires_ack=data.get("requires_ack", False),
            correlation_id=data.get("correlation_id")
        )
    
    @classmethod
    def from_json(cls, json_str: str) -> 'AIPMessage':
        """从 JSON 创建"""
        data = json.loads(json_str)
        return cls.from_dict(data)

# ============================================================================
# 消息构建器
# ============================================================================

class MessageBuilder:
    """消息构建器 - 简化消息创建"""
    
    @staticmethod
    def create_control_message(
        from_device: DeviceInfo,
        to_device: DeviceInfo,
        command: str,
        parameters: Dict[str, Any]
    ) -> AIPMessage:
        """创建控制消息"""
        payload = MessagePayload(
            data_type="control",
            format="json",
            size=len(json.dumps(parameters)),
            checksum=MessageBuilder._calculate_checksum(json.dumps(parameters)),
            transfer_method=TransferMethod.GATEWAY.value,
            metadata={"command": command},
            data=json.dumps(parameters)
        )
        
        return AIPMessage(
            from_device=from_device,
            to_device=to_device,
            message_type=MessageType.CONTROL,
            content_type=ContentType.JSON,
            payload=payload,
            requires_ack=True
        )
    
    @staticmethod
    def create_text_message(
        from_device: DeviceInfo,
        to_device: DeviceInfo,
        text: str
    ) -> AIPMessage:
        """创建文本消息"""
        payload = MessagePayload(
            data_type="text",
            format="plain",
            size=len(text.encode('utf-8')),
            checksum=MessageBuilder._calculate_checksum(text),
            transfer_method=TransferMethod.GATEWAY.value,
            data=text
        )
        
        return AIPMessage(
            from_device=from_device,
            to_device=to_device,
            message_type=MessageType.TEXT,
            content_type=ContentType.TEXT,
            payload=payload
        )
    
    @staticmethod
    def create_image_message(
        from_device: DeviceInfo,
        to_device: DeviceInfo,
        image_data: bytes,
        format: str = "jpeg",
        metadata: Dict[str, Any] = None
    ) -> AIPMessage:
        """创建图片消息"""
        # 如果图片小于 1MB，直接包含在消息中（Base64 编码）
        # 否则，使用 P2P 传输
        size = len(image_data)
        transfer_method = TransferMethod.GATEWAY.value if size < 1024*1024 else TransferMethod.P2P.value
        
        payload = MessagePayload(
            data_type="image",
            format=format,
            size=size,
            checksum=MessageBuilder._calculate_checksum(image_data),
            transfer_method=transfer_method,
            metadata=metadata or {},
            data=base64.b64encode(image_data).decode('utf-8') if size < 1024*1024 else None
        )
        
        return AIPMessage(
            from_device=from_device,
            to_device=to_device,
            message_type=MessageType.IMAGE,
            content_type=ContentType(f"image/{format}"),
            payload=payload,
            requires_ack=True
        )
    
    @staticmethod
    def create_file_message(
        from_device: DeviceInfo,
        to_device: DeviceInfo,
        file_path: str,
        file_size: int,
        file_checksum: str,
        chunks: int = None,
        metadata: Dict[str, Any] = None
    ) -> AIPMessage:
        """创建文件消息"""
        payload = MessagePayload(
            data_type="file",
            format="binary",
            size=file_size,
            checksum=file_checksum,
            transfer_method=TransferMethod.P2P.value,
            chunks=chunks,
            chunk_size=1024*1024 if chunks else None,  # 1MB per chunk
            metadata=metadata or {"file_path": file_path}
        )
        
        return AIPMessage(
            from_device=from_device,
            to_device=to_device,
            message_type=MessageType.FILE,
            content_type=ContentType.BINARY,
            payload=payload,
            requires_ack=True,
            priority=Priority.NORMAL
        )
    
    @staticmethod
    def create_ack_message(
        original_message: AIPMessage,
        success: bool,
        error: str = None
    ) -> AIPMessage:
        """创建确认消息"""
        payload = MessagePayload(
            data_type="ack",
            format="json",
            size=0,
            checksum="",
            transfer_method=TransferMethod.GATEWAY.value,
            metadata={
                "original_message_id": original_message.message_id,
                "success": success,
                "error": error
            }
        )
        
        return AIPMessage(
            from_device=original_message.to_device,
            to_device=original_message.from_device,
            message_type=MessageType.ACK,
            content_type=ContentType.JSON,
            payload=payload,
            correlation_id=original_message.message_id
        )
    
    @staticmethod
    def create_heartbeat_message(device: DeviceInfo) -> AIPMessage:
        """创建心跳消息"""
        payload = MessagePayload(
            data_type="heartbeat",
            format="json",
            size=0,
            checksum="",
            transfer_method=TransferMethod.GATEWAY.value,
            metadata={"timestamp": time.time()}
        )
        
        return AIPMessage(
            from_device=device,
            to_device=None,  # 发送到 Gateway
            message_type=MessageType.HEARTBEAT,
            content_type=ContentType.JSON,
            payload=payload,
            priority=Priority.LOW
        )
    
    @staticmethod
    def _calculate_checksum(data: Union[str, bytes]) -> str:
        """计算校验和"""
        if isinstance(data, str):
            data = data.encode('utf-8')
        return f"sha256:{hashlib.sha256(data).hexdigest()}"

# ============================================================================
# 消息编解码器
# ============================================================================

class MessageCodec:
    """消息编解码器"""
    
    @staticmethod
    def encode(message: AIPMessage) -> bytes:
        """编码消息为字节"""
        json_str = message.to_json()
        return json_str.encode('utf-8')
    
    @staticmethod
    def decode(data: bytes) -> AIPMessage:
        """解码字节为消息"""
        json_str = data.decode('utf-8')
        return AIPMessage.from_json(json_str)
    
    @staticmethod
    def validate(message: AIPMessage) -> tuple[bool, Optional[str]]:
        """验证消息"""
        # 检查必填字段
        if not message.message_id:
            return False, "message_id is required"
        
        if not message.from_device:
            return False, "from_device is required"
        
        if not message.message_type:
            return False, "message_type is required"
        
        # 检查 payload
        if message.payload:
            # 验证校验和
            if message.payload.data:
                data = message.payload.data
                if isinstance(data, str) and message.payload.data_type == "image":
                    # Base64 编码的图片
                    data = base64.b64decode(data)
                
                calculated_checksum = MessageBuilder._calculate_checksum(data)
                if calculated_checksum != message.payload.checksum:
                    return False, f"checksum mismatch: expected {message.payload.checksum}, got {calculated_checksum}"
        
        return True, None

# ============================================================================
# 使用示例
# ============================================================================

def example_usage():
    """使用示例"""
    
    # 创建设备信息
    phone_a = DeviceInfo(
        device_id="phone_a",
        device_name="手机A",
        device_type="android",
        ip_address="192.168.1.100"
    )
    
    pc = DeviceInfo(
        device_id="pc",
        device_name="电脑",
        device_type="windows",
        ip_address="192.168.1.10"
    )
    
    print("="*80)
    print("AIP v2.0 协议使用示例")
    print("="*80)
    
    # 示例 1: 控制消息
    print("\n示例 1: 控制消息")
    print("-"*80)
    control_msg = MessageBuilder.create_control_message(
        from_device=phone_a,
        to_device=pc,
        command="open_app",
        parameters={"app": "chrome", "url": "https://google.com"}
    )
    print(json.dumps(control_msg.to_dict(), ensure_ascii=False, indent=2))
    
    # 示例 2: 文本消息
    print("\n示例 2: 文本消息")
    print("-"*80)
    text_msg = MessageBuilder.create_text_message(
        from_device=phone_a,
        to_device=pc,
        text="Hello from Phone A!"
    )
    print(json.dumps(text_msg.to_dict(), ensure_ascii=False, indent=2))
    
    # 示例 3: 图片消息（小图片）
    print("\n示例 3: 图片消息")
    print("-"*80)
    fake_image_data = b"fake_image_data_here" * 100  # 假装是图片数据
    image_msg = MessageBuilder.create_image_message(
        from_device=phone_a,
        to_device=pc,
        image_data=fake_image_data,
        format="jpeg",
        metadata={"width": 1920, "height": 1080, "filename": "photo.jpg"}
    )
    print(json.dumps(image_msg.to_dict(), ensure_ascii=False, indent=2))
    
    # 示例 4: 文件消息（大文件）
    print("\n示例 4: 文件消息")
    print("-"*80)
    file_msg = MessageBuilder.create_file_message(
        from_device=phone_a,
        to_device=pc,
        file_path="/sdcard/video.mp4",
        file_size=500*1024*1024,  # 500MB
        file_checksum="sha256:abc123...",
        chunks=500,
        metadata={"filename": "video.mp4", "duration": 300}
    )
    print(json.dumps(file_msg.to_dict(), ensure_ascii=False, indent=2))
    
    # 示例 5: 确认消息
    print("\n示例 5: 确认消息")
    print("-"*80)
    ack_msg = MessageBuilder.create_ack_message(
        original_message=control_msg,
        success=True
    )
    print(json.dumps(ack_msg.to_dict(), ensure_ascii=False, indent=2))
    
    # 示例 6: 心跳消息
    print("\n示例 6: 心跳消息")
    print("-"*80)
    heartbeat_msg = MessageBuilder.create_heartbeat_message(phone_a)
    print(json.dumps(heartbeat_msg.to_dict(), ensure_ascii=False, indent=2))
    
    # 示例 7: 编解码
    print("\n示例 7: 编解码")
    print("-"*80)
    encoded = MessageCodec.encode(text_msg)
    print(f"编码后大小: {len(encoded)} 字节")
    
    decoded = MessageCodec.decode(encoded)
    print(f"解码后消息 ID: {decoded.message_id}")
    
    # 示例 8: 验证
    print("\n示例 8: 验证")
    print("-"*80)
    valid, error = MessageCodec.validate(text_msg)
    print(f"验证结果: {'有效' if valid else '无效'}")
    if error:
        print(f"错误: {error}")

if __name__ == "__main__":
    example_usage()
