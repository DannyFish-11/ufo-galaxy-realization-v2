"""
Node 71 - Device Models
设备数据模型定义，包含设备能力声明、资源限制和状态管理
"""
import time
import uuid
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from datetime import datetime


class DeviceType(str, Enum):
    """设备类型枚举"""
    DRONE = "drone"
    PRINTER_3D = "printer_3d"
    ROBOT = "robot"
    CAMERA = "camera"
    SENSOR = "sensor"
    ACTUATOR = "actuator"
    DISPLAY = "display"
    SPEAKER = "speaker"
    ANDROID = "android"
    IOS = "ios"
    WINDOWS = "windows"
    LINUX = "linux"
    EMBEDDED = "embedded"
    CLOUD = "cloud"
    UNKNOWN = "unknown"


class DeviceState(str, Enum):
    """设备状态枚举"""
    ONLINE = "online"
    OFFLINE = "offline"
    BUSY = "busy"
    IDLE = "idle"
    ERROR = "error"
    MAINTENANCE = "maintenance"
    DISCOVERING = "discovering"  # 正在发现中
    REGISTERING = "registering"  # 正在注册中


class DiscoveryProtocol(str, Enum):
    """设备发现协议类型"""
    MDNS = "mdns"
    UPNP = "upnp"
    BROADCAST = "broadcast"
    MANUAL = "manual"


@dataclass
class ResourceConstraints:
    """资源约束定义"""
    max_cpu_percent: float = 100.0  # 最大CPU使用率
    max_memory_mb: int = 4096  # 最大内存(MB)
    max_concurrent_tasks: int = 10  # 最大并发任务数
    max_network_bandwidth_mbps: float = 100.0  # 最大网络带宽(Mbps)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ResourceConstraints":
        return cls(
            max_cpu_percent=data.get("max_cpu_percent", 100.0),
            max_memory_mb=data.get("max_memory_mb", 4096),
            max_concurrent_tasks=data.get("max_concurrent_tasks", 10),
            max_network_bandwidth_mbps=data.get("max_network_bandwidth_mbps", 100.0)
        )


@dataclass
class Capability:
    """设备能力定义"""
    name: str  # 能力名称
    version: str = "1.0"  # 能力版本
    parameters: Dict[str, Any] = field(default_factory=dict)  # 能力参数
    priority: int = 5  # 能力优先级 (1-10, 越低越优先)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "parameters": self.parameters,
            "priority": self.priority
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Capability":
        return cls(
            name=data["name"],
            version=data.get("version", "1.0"),
            parameters=data.get("parameters", {}),
            priority=data.get("priority", 5)
        )


@dataclass
class VectorClock:
    """向量时钟实现，用于分布式状态同步"""
    clock: Dict[str, int] = field(default_factory=dict)
    node_id: str = ""
    
    def __post_init__(self):
        if self.node_id and self.node_id not in self.clock:
            self.clock[self.node_id] = 0
    
    def increment(self) -> "VectorClock":
        """递增本节点的时钟"""
        if self.node_id:
            self.clock[self.node_id] = self.clock.get(self.node_id, 0) + 1
        return self
    
    def update(self, other: "VectorClock") -> "VectorClock":
        """合并另一个向量时钟"""
        for node, time_val in other.clock.items():
            self.clock[node] = max(self.clock.get(node, 0), time_val)
        return self
    
    def compare(self, other: "VectorClock") -> int:
        """
        比较两个向量时钟
        返回: -1 (self < other), 0 (并发), 1 (self > other)
        """
        self_greater = False
        other_greater = False
        
        all_nodes = set(self.clock.keys()) | set(other.clock.keys())
        
        for node in all_nodes:
            self_time = self.clock.get(node, 0)
            other_time = other.clock.get(node, 0)
            
            if self_time > other_time:
                self_greater = True
            elif other_time > self_time:
                other_greater = True
        
        if self_greater and not other_greater:
            return 1
        elif other_greater and not self_greater:
            return -1
        return 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "clock": dict(self.clock),
            "node_id": self.node_id
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VectorClock":
        return cls(
            clock=data.get("clock", {}),
            node_id=data.get("node_id", "")
        )
    
    def copy(self) -> "VectorClock":
        return VectorClock(clock=dict(self.clock), node_id=self.node_id)


@dataclass
class Device:
    """设备完整数据模型"""
    device_id: str
    name: str
    device_type: DeviceType
    state: DeviceState = DeviceState.OFFLINE
    
    # 能力声明
    capabilities: List[Capability] = field(default_factory=list)
    
    # 资源约束
    resource_constraints: ResourceConstraints = field(default_factory=ResourceConstraints)
    
    # 网络信息
    host: str = "localhost"
    port: int = 0
    endpoint: Optional[str] = None
    
    # 位置信息
    location: Optional[str] = None
    
    # 心跳与状态
    last_heartbeat: float = field(default_factory=time.time)
    last_state_change: float = field(default_factory=time.time)
    
    # 任务相关
    current_task: Optional[str] = None
    assigned_tasks: List[str] = field(default_factory=list)
    completed_tasks: int = 0
    failed_tasks: int = 0
    
    # 向量时钟 (用于状态同步)
    vector_clock: VectorClock = field(default_factory=lambda: VectorClock())
    
    # 发现协议
    discovery_protocol: DiscoveryProtocol = DiscoveryProtocol.MANUAL
    
    # 优先级与权重
    priority: int = 5  # 设备优先级 (1-10)
    weight: float = 1.0  # 负载均衡权重
    
    # 负载状态
    current_load: float = 0.0  # 当前负载 (0-1)
    
    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # 标签
    tags: Set[str] = field(default_factory=set)
    
    # 注册时间
    registered_at: float = field(default_factory=time.time)
    
    def __post_init__(self):
        if not self.device_id:
            self.device_id = str(uuid.uuid4())
        if isinstance(self.device_type, str):
            self.device_type = DeviceType(self.device_type)
        if isinstance(self.state, str):
            self.state = DeviceState(self.state)
        if isinstance(self.discovery_protocol, str):
            self.discovery_protocol = DiscoveryProtocol(self.discovery_protocol)
    
    def update_heartbeat(self) -> None:
        """更新心跳时间"""
        self.last_heartbeat = time.time()
        if self.state == DeviceState.OFFLINE:
            self.state = DeviceState.IDLE
    
    def is_healthy(self, timeout: float = 60.0) -> bool:
        """检查设备是否健康"""
        if self.state == DeviceState.OFFLINE:
            return False
        return time.time() - self.last_heartbeat < timeout
    
    def can_accept_task(self) -> bool:
        """检查设备是否可以接受新任务"""
        if self.state not in (DeviceState.IDLE, DeviceState.ONLINE):
            return False
        if len(self.assigned_tasks) >= self.resource_constraints.max_concurrent_tasks:
            return False
        return True
    
    def get_capability(self, name: str) -> Optional[Capability]:
        """获取指定能力"""
        for cap in self.capabilities:
            if cap.name == name:
                return cap
        return None
    
    def has_capability(self, name: str) -> bool:
        """检查是否具有指定能力"""
        return self.get_capability(name) is not None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "device_id": self.device_id,
            "name": self.name,
            "device_type": self.device_type.value,
            "state": self.state.value,
            "capabilities": [cap.to_dict() for cap in self.capabilities],
            "resource_constraints": self.resource_constraints.to_dict(),
            "host": self.host,
            "port": self.port,
            "endpoint": self.endpoint,
            "location": self.location,
            "last_heartbeat": self.last_heartbeat,
            "last_state_change": self.last_state_change,
            "current_task": self.current_task,
            "assigned_tasks": self.assigned_tasks,
            "completed_tasks": self.completed_tasks,
            "failed_tasks": self.failed_tasks,
            "vector_clock": self.vector_clock.to_dict(),
            "discovery_protocol": self.discovery_protocol.value,
            "priority": self.priority,
            "weight": self.weight,
            "current_load": self.current_load,
            "metadata": self.metadata,
            "tags": list(self.tags),
            "registered_at": self.registered_at
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Device":
        """从字典创建设备"""
        capabilities = [
            Capability.from_dict(cap) if isinstance(cap, dict) else cap
            for cap in data.get("capabilities", [])
        ]
        
        resource_constraints = data.get("resource_constraints", {})
        if isinstance(resource_constraints, dict):
            resource_constraints = ResourceConstraints.from_dict(resource_constraints)
        
        vector_clock = data.get("vector_clock", {})
        if isinstance(vector_clock, dict):
            vector_clock = VectorClock.from_dict(vector_clock)
        
        return cls(
            device_id=data["device_id"],
            name=data["name"],
            device_type=DeviceType(data.get("device_type", "unknown")),
            state=DeviceState(data.get("state", "offline")),
            capabilities=capabilities,
            resource_constraints=resource_constraints,
            host=data.get("host", "localhost"),
            port=data.get("port", 0),
            endpoint=data.get("endpoint"),
            location=data.get("location"),
            last_heartbeat=data.get("last_heartbeat", time.time()),
            last_state_change=data.get("last_state_change", time.time()),
            current_task=data.get("current_task"),
            assigned_tasks=data.get("assigned_tasks", []),
            completed_tasks=data.get("completed_tasks", 0),
            failed_tasks=data.get("failed_tasks", 0),
            vector_clock=vector_clock,
            discovery_protocol=DiscoveryProtocol(data.get("discovery_protocol", "manual")),
            priority=data.get("priority", 5),
            weight=data.get("weight", 1.0),
            current_load=data.get("current_load", 0.0),
            metadata=data.get("metadata", {}),
            tags=set(data.get("tags", [])),
            registered_at=data.get("registered_at", time.time())
        )


@dataclass
class DeviceRegistry:
    """设备注册表"""
    devices: Dict[str, Device] = field(default_factory=dict)
    _by_type: Dict[DeviceType, Set[str]] = field(default_factory=dict)
    _by_capability: Dict[str, Set[str]] = field(default_factory=dict)
    _by_location: Dict[str, Set[str]] = field(default_factory=dict)
    _by_tag: Dict[str, Set[str]] = field(default_factory=dict)
    
    def register(self, device: Device) -> bool:
        """注册设备"""
        if device.device_id in self.devices:
            return False
        
        self.devices[device.device_id] = device
        
        # 更新索引
        if device.device_type not in self._by_type:
            self._by_type[device.device_type] = set()
        self._by_type[device.device_type].add(device.device_id)
        
        for cap in device.capabilities:
            if cap.name not in self._by_capability:
                self._by_capability[cap.name] = set()
            self._by_capability[cap.name].add(device.device_id)
        
        if device.location:
            if device.location not in self._by_location:
                self._by_location[device.location] = set()
            self._by_location[device.location].add(device.device_id)
        
        for tag in device.tags:
            if tag not in self._by_tag:
                self._by_tag[tag] = set()
            self._by_tag[tag].add(device.device_id)
        
        return True
    
    def unregister(self, device_id: str) -> bool:
        """注销设备"""
        if device_id not in self.devices:
            return False
        
        device = self.devices[device_id]
        
        # 更新索引
        if device.device_type in self._by_type:
            self._by_type[device.device_type].discard(device_id)
        
        for cap in device.capabilities:
            if cap.name in self._by_capability:
                self._by_capability[cap.name].discard(device_id)
        
        if device.location and device.location in self._by_location:
            self._by_location[device.location].discard(device_id)
        
        for tag in device.tags:
            if tag in self._by_tag:
                self._by_tag[tag].discard(device_id)
        
        del self.devices[device_id]
        return True
    
    def get(self, device_id: str) -> Optional[Device]:
        """获取设备"""
        return self.devices.get(device_id)
    
    def get_by_type(self, device_type: DeviceType) -> List[Device]:
        """按类型获取设备"""
        device_ids = self._by_type.get(device_type, set())
        return [self.devices[did] for did in device_ids if did in self.devices]
    
    def get_by_capability(self, capability: str) -> List[Device]:
        """按能力获取设备"""
        device_ids = self._by_capability.get(capability, set())
        return [self.devices[did] for did in device_ids if did in self.devices]
    
    def get_by_location(self, location: str) -> List[Device]:
        """按位置获取设备"""
        device_ids = self._by_location.get(location, set())
        return [self.devices[did] for did in device_ids if did in self.devices]
    
    def get_by_tag(self, tag: str) -> List[Device]:
        """按标签获取设备"""
        device_ids = self._by_tag.get(tag, set())
        return [self.devices[did] for did in device_ids if did in self.devices]
    
    def get_online_devices(self) -> List[Device]:
        """获取所有在线设备"""
        return [
            d for d in self.devices.values()
            if d.state not in (DeviceState.OFFLINE, DeviceState.ERROR)
        ]
    
    def get_available_devices(self) -> List[Device]:
        """获取所有可用设备"""
        return [
            d for d in self.devices.values()
            if d.can_accept_task()
        ]
    
    def list_all(self) -> List[Device]:
        """列出所有设备"""
        return list(self.devices.values())
    
    def count(self) -> int:
        """设备总数"""
        return len(self.devices)
    
    def count_by_state(self, state: DeviceState) -> int:
        """按状态统计设备数"""
        return sum(1 for d in self.devices.values() if d.state == state)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "devices": {did: d.to_dict() for did, d in self.devices.items()},
            "count": self.count()
        }
