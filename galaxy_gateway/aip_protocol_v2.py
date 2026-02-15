"""
UFO³ Galaxy - AIP v2.0 协议（Agent Interaction Protocol）

功能：
1. 统一的消息格式标准
2. 支持多种消息类型（文本、二进制、流）
3. 消息确认和重传机制
4. 心跳和重连机制
5. 消息编解码
6. 设备管理、任务调度、GUI操作等扩展协议

作者：Manus AI
日期：2026-01-22
版本：2.1
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
# 枚举定义 - 基础消息类型（向后兼容）
# ============================================================================

class MessageType(Enum):
    """基础消息类型 - 保持向后兼容"""
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

# ============================================================================
# 枚举定义 - 扩展消息类型（新增 24 个消息类型）
# ============================================================================

class ExtendedMessageType(Enum):
    """扩展消息类型 - 用于更细粒度的消息分类"""
    
    # ========== 设备管理 (6个) ==========
    DEVICE_REGISTER = "device_register"           # 设备注册请求
    DEVICE_REGISTER_ACK = "device_register_ack"   # 设备注册确认
    DEVICE_UNREGISTER = "device_unregister"       # 设备注销
    DEVICE_HEARTBEAT = "device_heartbeat"         # 设备心跳
    DEVICE_STATUS = "device_status"               # 设备状态上报
    DEVICE_CAPABILITIES = "device_capabilities"   # 设备能力上报
    
    # ========== 任务调度 (6个) ==========
    TASK_SUBMIT = "task_submit"                   # 任务提交
    TASK_ASSIGN = "task_assign"                   # 任务分配
    TASK_STATUS = "task_status"                   # 任务状态
    TASK_RESULT = "task_result"                   # 任务结果
    TASK_CANCEL = "task_cancel"                   # 任务取消
    TASK_PROGRESS = "task_progress"               # 任务进度
    
    # ========== GUI操作 (5个) ==========
    GUI_CLICK = "gui_click"                       # GUI点击操作
    GUI_SWIPE = "gui_swipe"                       # GUI滑动操作
    GUI_INPUT = "gui_input"                       # GUI输入操作
    GUI_SCREENSHOT = "gui_screenshot"             # GUI截图
    GUI_ELEMENT_QUERY = "gui_element_query"       # GUI元素查询
    
    # ========== 命令 (3个) ==========
    COMMAND = "command"                           # 命令执行
    COMMAND_RESULT = "command_result"             # 命令结果
    COMMAND_BATCH = "command_batch"               # 批量命令
    
    # ========== 错误 (2个) ==========
    ERROR_RECOVERY = "error_recovery"             # 错误恢复
    ERROR_REPORT = "error_report"                 # 错误报告

# ============================================================================
# 枚举定义 - 消息类型映射（兼容层）
# ============================================================================

class MessageTypeRegistry:
    """消息类型注册表 - 统一管理所有消息类型"""
    
    # 基础类型到扩展类型的映射
    TYPE_MAPPING = {
        "control": ["command", "command_batch"],
        "ack": ["device_register_ack"],
        "heartbeat": ["device_heartbeat"],
        "error": ["error_recovery", "error_report"],
    }
    
    @classmethod
    def get_all_types(cls) -> List[str]:
        """获取所有消息类型"""
        base_types = [t.value for t in MessageType]
        extended_types = [t.value for t in ExtendedMessageType]
        return base_types + extended_types
    
    @classmethod
    def is_valid_type(cls, msg_type: str) -> bool:
        """检查消息类型是否有效"""
        return msg_type in cls.get_all_types()
    
    @classmethod
    def get_extended_types_by_category(cls, category: str) -> List[str]:
        """按类别获取扩展消息类型"""
        category_map = {
            "device": ["device_register", "device_register_ack", "device_unregister", 
                      "device_heartbeat", "device_status", "device_capabilities"],
            "task": ["task_submit", "task_assign", "task_status", 
                    "task_result", "task_cancel", "task_progress"],
            "gui": ["gui_click", "gui_swipe", "gui_input", 
                   "gui_screenshot", "gui_element_query"],
            "command": ["command", "command_result", "command_batch"],
            "error": ["error_recovery", "error_report"],
        }
        return category_map.get(category, [])

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

class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"                    # 待处理
    RUNNING = "running"                    # 运行中
    PAUSED = "paused"                      # 已暂停
    COMPLETED = "completed"                # 已完成
    FAILED = "failed"                      # 失败
    CANCELLED = "cancelled"                # 已取消

class DeviceStatus(Enum):
    """设备状态"""
    ONLINE = "online"                      # 在线
    OFFLINE = "offline"                    # 离线
    BUSY = "busy"                          # 忙碌
    IDLE = "idle"                          # 空闲
    ERROR = "error"                        # 错误状态

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
    status: Optional[str] = None           # 设备状态
    capabilities: Optional[List[str]] = None  # 设备能力列表

@dataclass
class TaskInfo:
    """任务信息"""
    task_id: str
    task_type: str
    status: str
    priority: str = "normal"
    progress: float = 0.0                  # 进度 0-100
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

@dataclass
class GUIElement:
    """GUI元素信息"""
    element_id: str
    element_type: str                      # button, input, text, etc.
    bounds: Optional[Dict[str, int]] = None  # {x, y, width, height}
    text: Optional[str] = None
    clickable: bool = False
    enabled: bool = True

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
    extended_type: Optional[str] = None    # 扩展消息类型
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
            "extended_type": self.extended_type,
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
            extended_type=data.get("extended_type"),
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
# 消息构建器 - 基础消息（向后兼容）
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
            chunk_size=1024*1024 if chunks else None,
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
            to_device=None,
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
# 消息构建器 - 扩展消息（新增 24 个消息类型）
# ============================================================================

class ExtendedMessageBuilder(MessageBuilder):
    """扩展消息构建器 - 支持 24 个新增消息类型"""
    
    # ========== 设备管理消息 ==========
    
    @staticmethod
    def create_device_register_message(
        device: DeviceInfo,
        gateway_device: DeviceInfo = None
    ) -> AIPMessage:
        """创建设备注册消息"""
        payload = MessagePayload(
            data_type="device_register",
            format="json",
            size=0,
            checksum="",
            transfer_method=TransferMethod.GATEWAY.value,
            metadata={
                "device_info": asdict(device),
                "register_time": datetime.now(timezone.utc).isoformat()
            }
        )
        
        return AIPMessage(
            from_device=device,
            to_device=gateway_device,
            message_type=MessageType.CONTROL,
            extended_type=ExtendedMessageType.DEVICE_REGISTER.value,
            content_type=ContentType.JSON,
            payload=payload,
            requires_ack=True,
            priority=Priority.HIGH
        )
    
    @staticmethod
    def create_device_register_ack_message(
        original_message: AIPMessage,
        success: bool,
        session_token: str = None,
        error: str = None
    ) -> AIPMessage:
        """创建设备注册确认消息"""
        metadata = {
            "original_message_id": original_message.message_id,
            "success": success,
            "error": error
        }
        if session_token:
            metadata["session_token"] = session_token
            
        payload = MessagePayload(
            data_type="device_register_ack",
            format="json",
            size=0,
            checksum="",
            transfer_method=TransferMethod.GATEWAY.value,
            metadata=metadata
        )
        
        return AIPMessage(
            from_device=original_message.to_device,
            to_device=original_message.from_device,
            message_type=MessageType.ACK,
            extended_type=ExtendedMessageType.DEVICE_REGISTER_ACK.value,
            content_type=ContentType.JSON,
            payload=payload,
            correlation_id=original_message.message_id
        )
    
    @staticmethod
    def create_device_unregister_message(
        device: DeviceInfo,
        reason: str = None
    ) -> AIPMessage:
        """创建设备注销消息"""
        payload = MessagePayload(
            data_type="device_unregister",
            format="json",
            size=0,
            checksum="",
            transfer_method=TransferMethod.GATEWAY.value,
            metadata={
                "device_id": device.device_id,
                "reason": reason,
                "unregister_time": datetime.now(timezone.utc).isoformat()
            }
        )
        
        return AIPMessage(
            from_device=device,
            to_device=None,
            message_type=MessageType.CONTROL,
            extended_type=ExtendedMessageType.DEVICE_UNREGISTER.value,
            content_type=ContentType.JSON,
            payload=payload,
            requires_ack=True
        )
    
    @staticmethod
    def create_device_heartbeat_message(
        device: DeviceInfo,
        status: str = None
    ) -> AIPMessage:
        """创建设备心跳消息"""
        payload = MessagePayload(
            data_type="device_heartbeat",
            format="json",
            size=0,
            checksum="",
            transfer_method=TransferMethod.GATEWAY.value,
            metadata={
                "device_id": device.device_id,
                "status": status or DeviceStatus.ONLINE.value,
                "timestamp": time.time()
            }
        )
        
        return AIPMessage(
            from_device=device,
            to_device=None,
            message_type=MessageType.HEARTBEAT,
            extended_type=ExtendedMessageType.DEVICE_HEARTBEAT.value,
            content_type=ContentType.JSON,
            payload=payload,
            priority=Priority.LOW
        )
    
    @staticmethod
    def create_device_status_message(
        device: DeviceInfo,
        status: str,
        extra_info: Dict[str, Any] = None
    ) -> AIPMessage:
        """创建设备状态上报消息"""
        metadata = {
            "device_id": device.device_id,
            "status": status,
            "report_time": datetime.now(timezone.utc).isoformat()
        }
        if extra_info:
            metadata.update(extra_info)
            
        payload = MessagePayload(
            data_type="device_status",
            format="json",
            size=0,
            checksum="",
            transfer_method=TransferMethod.GATEWAY.value,
            metadata=metadata
        )
        
        return AIPMessage(
            from_device=device,
            to_device=None,
            message_type=MessageType.CONTROL,
            extended_type=ExtendedMessageType.DEVICE_STATUS.value,
            content_type=ContentType.JSON,
            payload=payload
        )
    
    @staticmethod
    def create_device_capabilities_message(
        device: DeviceInfo,
        capabilities: List[str]
    ) -> AIPMessage:
        """创建设备能力上报消息"""
        payload = MessagePayload(
            data_type="device_capabilities",
            format="json",
            size=0,
            checksum="",
            transfer_method=TransferMethod.GATEWAY.value,
            metadata={
                "device_id": device.device_id,
                "capabilities": capabilities,
                "report_time": datetime.now(timezone.utc).isoformat()
            }
        )
        
        return AIPMessage(
            from_device=device,
            to_device=None,
            message_type=MessageType.CONTROL,
            extended_type=ExtendedMessageType.DEVICE_CAPABILITIES.value,
            content_type=ContentType.JSON,
            payload=payload
        )
    
    # ========== 任务调度消息 ==========
    
    @staticmethod
    def create_task_submit_message(
        from_device: DeviceInfo,
        to_device: DeviceInfo,
        task_type: str,
        task_params: Dict[str, Any],
        task_id: str = None
    ) -> AIPMessage:
        """创建任务提交消息"""
        task_id = task_id or f"task_{uuid.uuid4().hex[:12]}"
        params_json = json.dumps(task_params)
        
        payload = MessagePayload(
            data_type="task_submit",
            format="json",
            size=len(params_json),
            checksum=ExtendedMessageBuilder._calculate_checksum(params_json),
            transfer_method=TransferMethod.GATEWAY.value,
            metadata={
                "task_id": task_id,
                "task_type": task_type,
                "submit_time": datetime.now(timezone.utc).isoformat()
            },
            data=params_json
        )
        
        return AIPMessage(
            from_device=from_device,
            to_device=to_device,
            message_type=MessageType.CONTROL,
            extended_type=ExtendedMessageType.TASK_SUBMIT.value,
            content_type=ContentType.JSON,
            payload=payload,
            requires_ack=True,
            priority=Priority.NORMAL
        )
    
    @staticmethod
    def create_task_assign_message(
        from_device: DeviceInfo,
        to_device: DeviceInfo,
        task_id: str,
        task_info: Dict[str, Any]
    ) -> AIPMessage:
        """创建任务分配消息"""
        payload = MessagePayload(
            data_type="task_assign",
            format="json",
            size=0,
            checksum="",
            transfer_method=TransferMethod.GATEWAY.value,
            metadata={
                "task_id": task_id,
                "task_info": task_info,
                "assign_time": datetime.now(timezone.utc).isoformat()
            }
        )
        
        return AIPMessage(
            from_device=from_device,
            to_device=to_device,
            message_type=MessageType.CONTROL,
            extended_type=ExtendedMessageType.TASK_ASSIGN.value,
            content_type=ContentType.JSON,
            payload=payload,
            requires_ack=True
        )
    
    @staticmethod
    def create_task_status_message(
        from_device: DeviceInfo,
        to_device: DeviceInfo,
        task_id: str,
        status: str,
        extra_info: Dict[str, Any] = None
    ) -> AIPMessage:
        """创建任务状态消息"""
        metadata = {
            "task_id": task_id,
            "status": status,
            "update_time": datetime.now(timezone.utc).isoformat()
        }
        if extra_info:
            metadata.update(extra_info)
            
        payload = MessagePayload(
            data_type="task_status",
            format="json",
            size=0,
            checksum="",
            transfer_method=TransferMethod.GATEWAY.value,
            metadata=metadata
        )
        
        return AIPMessage(
            from_device=from_device,
            to_device=to_device,
            message_type=MessageType.CONTROL,
            extended_type=ExtendedMessageType.TASK_STATUS.value,
            content_type=ContentType.JSON,
            payload=payload
        )
    
    @staticmethod
    def create_task_result_message(
        from_device: DeviceInfo,
        to_device: DeviceInfo,
        task_id: str,
        result: Dict[str, Any],
        success: bool = True
    ) -> AIPMessage:
        """创建任务结果消息"""
        result_json = json.dumps(result)
        
        payload = MessagePayload(
            data_type="task_result",
            format="json",
            size=len(result_json),
            checksum=ExtendedMessageBuilder._calculate_checksum(result_json),
            transfer_method=TransferMethod.GATEWAY.value,
            metadata={
                "task_id": task_id,
                "success": success,
                "completion_time": datetime.now(timezone.utc).isoformat()
            },
            data=result_json
        )
        
        return AIPMessage(
            from_device=from_device,
            to_device=to_device,
            message_type=MessageType.CONTROL,
            extended_type=ExtendedMessageType.TASK_RESULT.value,
            content_type=ContentType.JSON,
            payload=payload,
            requires_ack=True
        )
    
    @staticmethod
    def create_task_cancel_message(
        from_device: DeviceInfo,
        to_device: DeviceInfo,
        task_id: str,
        reason: str = None
    ) -> AIPMessage:
        """创建任务取消消息"""
        payload = MessagePayload(
            data_type="task_cancel",
            format="json",
            size=0,
            checksum="",
            transfer_method=TransferMethod.GATEWAY.value,
            metadata={
                "task_id": task_id,
                "reason": reason,
                "cancel_time": datetime.now(timezone.utc).isoformat()
            }
        )
        
        return AIPMessage(
            from_device=from_device,
            to_device=to_device,
            message_type=MessageType.CONTROL,
            extended_type=ExtendedMessageType.TASK_CANCEL.value,
            content_type=ContentType.JSON,
            payload=payload,
            requires_ack=True,
            priority=Priority.URGENT
        )
    
    @staticmethod
    def create_task_progress_message(
        from_device: DeviceInfo,
        to_device: DeviceInfo,
        task_id: str,
        progress: float,
        message: str = None
    ) -> AIPMessage:
        """创建任务进度消息"""
        payload = MessagePayload(
            data_type="task_progress",
            format="json",
            size=0,
            checksum="",
            transfer_method=TransferMethod.GATEWAY.value,
            metadata={
                "task_id": task_id,
                "progress": progress,
                "message": message,
                "update_time": datetime.now(timezone.utc).isoformat()
            }
        )
        
        return AIPMessage(
            from_device=from_device,
            to_device=to_device,
            message_type=MessageType.CONTROL,
            extended_type=ExtendedMessageType.TASK_PROGRESS.value,
            content_type=ContentType.JSON,
            payload=payload,
            priority=Priority.LOW
        )
    
    # ========== GUI操作消息 ==========
    
    @staticmethod
    def create_gui_click_message(
        from_device: DeviceInfo,
        to_device: DeviceInfo,
        x: int,
        y: int,
        element_id: str = None
    ) -> AIPMessage:
        """创建GUI点击消息"""
        payload = MessagePayload(
            data_type="gui_click",
            format="json",
            size=0,
            checksum="",
            transfer_method=TransferMethod.GATEWAY.value,
            metadata={
                "x": x,
                "y": y,
                "element_id": element_id,
                "action_time": datetime.now(timezone.utc).isoformat()
            }
        )
        
        return AIPMessage(
            from_device=from_device,
            to_device=to_device,
            message_type=MessageType.CONTROL,
            extended_type=ExtendedMessageType.GUI_CLICK.value,
            content_type=ContentType.JSON,
            payload=payload,
            requires_ack=True
        )
    
    @staticmethod
    def create_gui_swipe_message(
        from_device: DeviceInfo,
        to_device: DeviceInfo,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration: int = 300
    ) -> AIPMessage:
        """创建GUI滑动消息"""
        payload = MessagePayload(
            data_type="gui_swipe",
            format="json",
            size=0,
            checksum="",
            transfer_method=TransferMethod.GATEWAY.value,
            metadata={
                "start_x": start_x,
                "start_y": start_y,
                "end_x": end_x,
                "end_y": end_y,
                "duration": duration,
                "action_time": datetime.now(timezone.utc).isoformat()
            }
        )
        
        return AIPMessage(
            from_device=from_device,
            to_device=to_device,
            message_type=MessageType.CONTROL,
            extended_type=ExtendedMessageType.GUI_SWIPE.value,
            content_type=ContentType.JSON,
            payload=payload,
            requires_ack=True
        )
    
    @staticmethod
    def create_gui_input_message(
        from_device: DeviceInfo,
        to_device: DeviceInfo,
        text: str,
        element_id: str = None
    ) -> AIPMessage:
        """创建GUI输入消息"""
        payload = MessagePayload(
            data_type="gui_input",
            format="json",
            size=len(text.encode('utf-8')),
            checksum=ExtendedMessageBuilder._calculate_checksum(text),
            transfer_method=TransferMethod.GATEWAY.value,
            metadata={
                "element_id": element_id,
                "action_time": datetime.now(timezone.utc).isoformat()
            },
            data=text
        )
        
        return AIPMessage(
            from_device=from_device,
            to_device=to_device,
            message_type=MessageType.CONTROL,
            extended_type=ExtendedMessageType.GUI_INPUT.value,
            content_type=ContentType.JSON,
            payload=payload,
            requires_ack=True
        )
    
    @staticmethod
    def create_gui_screenshot_message(
        from_device: DeviceInfo,
        to_device: DeviceInfo,
        screenshot_data: bytes = None,
        format: str = "jpeg"
    ) -> AIPMessage:
        """创建GUI截图消息"""
        if screenshot_data:
            size = len(screenshot_data)
            data = base64.b64encode(screenshot_data).decode('utf-8') if size < 1024*1024 else None
        else:
            size = 0
            data = None
            
        payload = MessagePayload(
            data_type="gui_screenshot",
            format=format,
            size=size,
            checksum=ExtendedMessageBuilder._calculate_checksum(screenshot_data) if screenshot_data else "",
            transfer_method=TransferMethod.GATEWAY.value,
            metadata={
                "capture_time": datetime.now(timezone.utc).isoformat()
            },
            data=data
        )
        
        return AIPMessage(
            from_device=from_device,
            to_device=to_device,
            message_type=MessageType.IMAGE,
            extended_type=ExtendedMessageType.GUI_SCREENSHOT.value,
            content_type=ContentType(f"image/{format}"),
            payload=payload,
            requires_ack=True
        )
    
    @staticmethod
    def create_gui_element_query_message(
        from_device: DeviceInfo,
        to_device: DeviceInfo,
        query: str,
        query_type: str = "id"  # id, text, class, xpath
    ) -> AIPMessage:
        """创建GUI元素查询消息"""
        payload = MessagePayload(
            data_type="gui_element_query",
            format="json",
            size=0,
            checksum="",
            transfer_method=TransferMethod.GATEWAY.value,
            metadata={
                "query": query,
                "query_type": query_type,
                "query_time": datetime.now(timezone.utc).isoformat()
            }
        )
        
        return AIPMessage(
            from_device=from_device,
            to_device=to_device,
            message_type=MessageType.CONTROL,
            extended_type=ExtendedMessageType.GUI_ELEMENT_QUERY.value,
            content_type=ContentType.JSON,
            payload=payload,
            requires_ack=True
        )
    
    # ========== 命令消息 ==========
    
    @staticmethod
    def create_command_message(
        from_device: DeviceInfo,
        to_device: DeviceInfo,
        command: str,
        params: Dict[str, Any] = None,
        timeout: int = 30
    ) -> AIPMessage:
        """创建命令执行消息"""
        params = params or {}
        params_json = json.dumps(params)
        
        payload = MessagePayload(
            data_type="command",
            format="json",
            size=len(params_json),
            checksum=ExtendedMessageBuilder._calculate_checksum(params_json),
            transfer_method=TransferMethod.GATEWAY.value,
            metadata={
                "command": command,
                "timeout": timeout,
                "command_time": datetime.now(timezone.utc).isoformat()
            },
            data=params_json
        )
        
        return AIPMessage(
            from_device=from_device,
            to_device=to_device,
            message_type=MessageType.CONTROL,
            extended_type=ExtendedMessageType.COMMAND.value,
            content_type=ContentType.JSON,
            payload=payload,
            requires_ack=True
        )
    
    @staticmethod
    def create_command_result_message(
        from_device: DeviceInfo,
        to_device: DeviceInfo,
        original_command_id: str,
        success: bool,
        result: Any = None,
        error: str = None
    ) -> AIPMessage:
        """创建命令结果消息"""
        result_data = json.dumps({
            "success": success,
            "result": result,
            "error": error
        })
        
        payload = MessagePayload(
            data_type="command_result",
            format="json",
            size=len(result_data),
            checksum=ExtendedMessageBuilder._calculate_checksum(result_data),
            transfer_method=TransferMethod.GATEWAY.value,
            metadata={
                "original_command_id": original_command_id,
                "success": success,
                "error": error,
                "result_time": datetime.now(timezone.utc).isoformat()
            },
            data=result_data
        )
        
        return AIPMessage(
            from_device=from_device,
            to_device=to_device,
            message_type=MessageType.CONTROL,
            extended_type=ExtendedMessageType.COMMAND_RESULT.value,
            content_type=ContentType.JSON,
            payload=payload,
            correlation_id=original_command_id
        )
    
    @staticmethod
    def create_command_batch_message(
        from_device: DeviceInfo,
        to_device: DeviceInfo,
        commands: List[Dict[str, Any]],
        sequential: bool = True
    ) -> AIPMessage:
        """创建批量命令消息"""
        commands_json = json.dumps(commands)
        
        payload = MessagePayload(
            data_type="command_batch",
            format="json",
            size=len(commands_json),
            checksum=ExtendedMessageBuilder._calculate_checksum(commands_json),
            transfer_method=TransferMethod.GATEWAY.value,
            metadata={
                "command_count": len(commands),
                "sequential": sequential,
                "batch_time": datetime.now(timezone.utc).isoformat()
            },
            data=commands_json
        )
        
        return AIPMessage(
            from_device=from_device,
            to_device=to_device,
            message_type=MessageType.CONTROL,
            extended_type=ExtendedMessageType.COMMAND_BATCH.value,
            content_type=ContentType.JSON,
            payload=payload,
            requires_ack=True
        )
    
    # ========== 错误消息 ==========
    
    @staticmethod
    def create_error_recovery_message(
        from_device: DeviceInfo,
        to_device: DeviceInfo,
        error_type: str,
        recovery_action: str,
        original_message_id: str = None
    ) -> AIPMessage:
        """创建错误恢复消息"""
        payload = MessagePayload(
            data_type="error_recovery",
            format="json",
            size=0,
            checksum="",
            transfer_method=TransferMethod.GATEWAY.value,
            metadata={
                "error_type": error_type,
                "recovery_action": recovery_action,
                "original_message_id": original_message_id,
                "recovery_time": datetime.now(timezone.utc).isoformat()
            }
        )
        
        return AIPMessage(
            from_device=from_device,
            to_device=to_device,
            message_type=MessageType.ERROR,
            extended_type=ExtendedMessageType.ERROR_RECOVERY.value,
            content_type=ContentType.JSON,
            payload=payload,
            correlation_id=original_message_id,
            priority=Priority.HIGH
        )
    
    @staticmethod
    def create_error_report_message(
        from_device: DeviceInfo,
        error_code: str,
        error_message: str,
        error_details: Dict[str, Any] = None
    ) -> AIPMessage:
        """创建错误报告消息"""
        metadata = {
            "error_code": error_code,
            "error_message": error_message,
            "report_time": datetime.now(timezone.utc).isoformat()
        }
        if error_details:
            metadata["error_details"] = error_details
            
        payload = MessagePayload(
            data_type="error_report",
            format="json",
            size=0,
            checksum="",
            transfer_method=TransferMethod.GATEWAY.value,
            metadata=metadata
        )
        
        return AIPMessage(
            from_device=from_device,
            to_device=None,
            message_type=MessageType.ERROR,
            extended_type=ExtendedMessageType.ERROR_REPORT.value,
            content_type=ContentType.JSON,
            payload=payload,
            priority=Priority.HIGH
        )

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
        
        # 检查扩展类型是否有效
        if message.extended_type:
            if not MessageTypeRegistry.is_valid_type(message.extended_type):
                return False, f"invalid extended_type: {message.extended_type}"
        
        # 检查 payload
        if message.payload:
            if message.payload.data:
                data = message.payload.data
                if isinstance(data, str) and message.payload.data_type in ["image", "gui_screenshot"]:
                    try:
                        data = base64.b64decode(data)
                    except Exception:
                        return False, "invalid base64 data"
                
                calculated_checksum = MessageBuilder._calculate_checksum(data)
                if calculated_checksum != message.payload.checksum:
                    return False, f"checksum mismatch"
        
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
    
    # 示例 1: 设备注册
    print("\n示例 1: 设备注册")
    print("-"*80)
    register_msg = ExtendedMessageBuilder.create_device_register_message(phone_a)
    print(json.dumps(register_msg.to_dict(), ensure_ascii=False, indent=2))
    
    # 示例 2: 设备注册确认
    print("\n示例 2: 设备注册确认")
    print("-"*80)
    register_ack = ExtendedMessageBuilder.create_device_register_ack_message(
        original_message=register_msg,
        success=True,
        session_token="sess_abc123"
    )
    print(json.dumps(register_ack.to_dict(), ensure_ascii=False, indent=2))
    
    # 示例 3: 任务提交
    print("\n示例 3: 任务提交")
    print("-"*80)
    task_submit = ExtendedMessageBuilder.create_task_submit_message(
        from_device=phone_a,
        to_device=pc,
        task_type="screenshot",
        task_params={"quality": 80, "format": "jpeg"}
    )
    print(json.dumps(task_submit.to_dict(), ensure_ascii=False, indent=2))
    
    # 示例 4: 任务进度
    print("\n示例 4: 任务进度")
    print("-"*80)
    task_progress = ExtendedMessageBuilder.create_task_progress_message(
        from_device=pc,
        to_device=phone_a,
        task_id="task_123",
        progress=50.0,
        message="Processing..."
    )
    print(json.dumps(task_progress.to_dict(), ensure_ascii=False, indent=2))
    
    # 示例 5: GUI点击
    print("\n示例 5: GUI点击")
    print("-"*80)
    gui_click = ExtendedMessageBuilder.create_gui_click_message(
        from_device=phone_a,
        to_device=pc,
        x=100,
        y=200,
        element_id="btn_submit"
    )
    print(json.dumps(gui_click.to_dict(), ensure_ascii=False, indent=2))
    
    # 示例 6: 命令执行
    print("\n示例 6: 命令执行")
    print("-"*80)
    command_msg = ExtendedMessageBuilder.create_command_message(
        from_device=phone_a,
        to_device=pc,
        command="open_browser",
        params={"url": "https://example.com"},
        timeout=30
    )
    print(json.dumps(command_msg.to_dict(), ensure_ascii=False, indent=2))
    
    # 示例 7: 错误报告
    print("\n示例 7: 错误报告")
    print("-"*80)
    error_report = ExtendedMessageBuilder.create_error_report_message(
        from_device=phone_a,
        error_code="E001",
        error_message="Connection timeout",
        error_details={"retry_count": 3}
    )
    print(json.dumps(error_report.to_dict(), ensure_ascii=False, indent=2))
    
    # 示例 8: 消息类型注册表
    print("\n示例 8: 消息类型注册表")
    print("-"*80)
    print(f"所有消息类型数量: {len(MessageTypeRegistry.get_all_types())}")
    print(f"设备管理类型: {MessageTypeRegistry.get_extended_types_by_category('device')}")
    print(f"任务调度类型: {MessageTypeRegistry.get_extended_types_by_category('task')}")
    print(f"GUI操作类型: {MessageTypeRegistry.get_extended_types_by_category('gui')}")
    print(f"命令类型: {MessageTypeRegistry.get_extended_types_by_category('command')}")
    print(f"错误类型: {MessageTypeRegistry.get_extended_types_by_category('error')}")
    
    # 示例 9: 验证消息
    print("\n示例 9: 消息验证")
    print("-"*80)
    valid, error = MessageCodec.validate(command_msg)
    print(f"验证结果: {'有效' if valid else '无效'}")
    if error:
        print(f"错误: {error}")

if __name__ == "__main__":
    example_usage()
