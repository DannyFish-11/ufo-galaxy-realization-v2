"""
Node 109 - ProactiveSensing (主动感知节点)
提供环境感知、事件检测和主动信息收集能力
"""
import os
import json
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable, Set
from dataclasses import dataclass, field, asdict
from enum import Enum
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import threading

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Node 109 - ProactiveSensing", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


class SensorType(str, Enum):
    """传感器类型"""
    SYSTEM = "system"           # 系统状态
    NETWORK = "network"         # 网络状态
    USER = "user"               # 用户行为
    ENVIRONMENT = "environment" # 环境变化
    DEVICE = "device"           # 设备状态
    APPLICATION = "application" # 应用状态
    CUSTOM = "custom"           # 自定义


class EventPriority(str, Enum):
    """事件优先级"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class SensingMode(str, Enum):
    """感知模式"""
    PASSIVE = "passive"     # 被动监听
    ACTIVE = "active"       # 主动探测
    REACTIVE = "reactive"   # 响应式
    PREDICTIVE = "predictive"  # 预测式


@dataclass
class Sensor:
    """传感器定义"""
    sensor_id: str
    sensor_type: SensorType
    name: str
    description: str
    polling_interval: float  # 秒
    enabled: bool = True
    last_reading: Optional[Dict] = None
    last_read_time: Optional[datetime] = None
    error_count: int = 0


@dataclass
class SensorReading:
    """传感器读数"""
    sensor_id: str
    value: Any
    unit: Optional[str]
    quality: float  # 0-1 数据质量
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DetectedEvent:
    """检测到的事件"""
    event_id: str
    event_type: str
    source: str
    priority: EventPriority
    description: str
    data: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.now)
    acknowledged: bool = False
    handled: bool = False


@dataclass
class SensingRule:
    """感知规则"""
    rule_id: str
    name: str
    condition: str  # 条件表达式
    action: str     # 触发动作
    sensors: List[str]  # 关联的传感器
    enabled: bool = True
    trigger_count: int = 0
    last_triggered: Optional[datetime] = None


class ProactiveSensingEngine:
    """主动感知引擎"""
    
    def __init__(self):
        self.sensors: Dict[str, Sensor] = {}
        self.readings: List[SensorReading] = []
        self.events: List[DetectedEvent] = []
        self.rules: Dict[str, SensingRule] = {}
        self.mode = SensingMode.PASSIVE
        self.is_running = False
        self._lock = threading.Lock()
        self._event_handlers: Dict[str, List[Callable]] = {}
        self._initialize_default_sensors()
    
    def _initialize_default_sensors(self):
        """初始化默认传感器"""
        default_sensors = [
            Sensor("sys_cpu", SensorType.SYSTEM, "CPU Monitor", "监控CPU使用率", 5.0),
            Sensor("sys_memory", SensorType.SYSTEM, "Memory Monitor", "监控内存使用", 5.0),
            Sensor("sys_disk", SensorType.SYSTEM, "Disk Monitor", "监控磁盘使用", 30.0),
            Sensor("net_connectivity", SensorType.NETWORK, "Network Connectivity", "网络连接状态", 10.0),
            Sensor("net_latency", SensorType.NETWORK, "Network Latency", "网络延迟", 15.0),
            Sensor("user_activity", SensorType.USER, "User Activity", "用户活动检测", 1.0),
            Sensor("env_time", SensorType.ENVIRONMENT, "Time Sensor", "时间感知", 60.0),
            Sensor("device_status", SensorType.DEVICE, "Device Status", "设备状态", 30.0),
        ]
        for sensor in default_sensors:
            self.sensors[sensor.sensor_id] = sensor
    
    def register_sensor(self, sensor: Sensor) -> bool:
        """注册新传感器"""
        with self._lock:
            if sensor.sensor_id in self.sensors:
                return False
            self.sensors[sensor.sensor_id] = sensor
            logger.info(f"Registered sensor: {sensor.sensor_id}")
            return True
    
    def unregister_sensor(self, sensor_id: str) -> bool:
        """注销传感器"""
        with self._lock:
            if sensor_id not in self.sensors:
                return False
            del self.sensors[sensor_id]
            logger.info(f"Unregistered sensor: {sensor_id}")
            return True
    
    async def read_sensor(self, sensor_id: str) -> Optional[SensorReading]:
        """读取传感器数据"""
        if sensor_id not in self.sensors:
            return None
        
        sensor = self.sensors[sensor_id]
        if not sensor.enabled:
            return None
        
        try:
            # 根据传感器类型获取数据
            value, unit, quality = await self._get_sensor_value(sensor)
            
            reading = SensorReading(
                sensor_id=sensor_id,
                value=value,
                unit=unit,
                quality=quality,
                metadata={"sensor_type": sensor.sensor_type.value}
            )
            
            # 更新传感器状态
            sensor.last_reading = {"value": value, "unit": unit}
            sensor.last_read_time = datetime.now()
            
            # 保存读数
            self.readings.append(reading)
            if len(self.readings) > 10000:
                self.readings = self.readings[-5000:]
            
            # 检查规则
            await self._check_rules(reading)
            
            return reading
            
        except Exception as e:
            sensor.error_count += 1
            logger.error(f"Error reading sensor {sensor_id}: {e}")
            return None
    
    async def _get_sensor_value(self, sensor: Sensor) -> tuple:
        """获取传感器值"""
        if sensor.sensor_type == SensorType.SYSTEM:
            return await self._read_system_sensor(sensor)
        elif sensor.sensor_type == SensorType.NETWORK:
            return await self._read_network_sensor(sensor)
        elif sensor.sensor_type == SensorType.USER:
            return await self._read_user_sensor(sensor)
        elif sensor.sensor_type == SensorType.ENVIRONMENT:
            return await self._read_environment_sensor(sensor)
        elif sensor.sensor_type == SensorType.DEVICE:
            return await self._read_device_sensor(sensor)
        else:
            return (None, None, 0.0)
    
    async def _read_system_sensor(self, sensor: Sensor) -> tuple:
        """读取系统传感器"""
        try:
            import psutil
            if sensor.sensor_id == "sys_cpu":
                value = psutil.cpu_percent(interval=0.1)
                return (value, "%", 1.0)
            elif sensor.sensor_id == "sys_memory":
                mem = psutil.virtual_memory()
                return (mem.percent, "%", 1.0)
            elif sensor.sensor_id == "sys_disk":
                disk = psutil.disk_usage('/')
                return (disk.percent, "%", 1.0)
        except ImportError:
            pass
        
        # 模拟数据
        import random
        if sensor.sensor_id == "sys_cpu":
            return (random.uniform(10, 80), "%", 0.8)
        elif sensor.sensor_id == "sys_memory":
            return (random.uniform(30, 70), "%", 0.8)
        elif sensor.sensor_id == "sys_disk":
            return (random.uniform(20, 60), "%", 0.8)
        return (0, None, 0.5)
    
    async def _read_network_sensor(self, sensor: Sensor) -> tuple:
        """读取网络传感器"""
        import random
        if sensor.sensor_id == "net_connectivity":
            return (True, "bool", 1.0)
        elif sensor.sensor_id == "net_latency":
            return (random.uniform(10, 100), "ms", 0.9)
        return (None, None, 0.5)
    
    async def _read_user_sensor(self, sensor: Sensor) -> tuple:
        """读取用户传感器"""
        # 模拟用户活动
        import random
        activity_level = random.choice(["idle", "active", "busy"])
        return (activity_level, "status", 0.7)
    
    async def _read_environment_sensor(self, sensor: Sensor) -> tuple:
        """读取环境传感器"""
        if sensor.sensor_id == "env_time":
            now = datetime.now()
            return ({
                "hour": now.hour,
                "minute": now.minute,
                "day_of_week": now.weekday(),
                "is_business_hours": 9 <= now.hour <= 18
            }, "time_info", 1.0)
        return (None, None, 0.5)
    
    async def _read_device_sensor(self, sensor: Sensor) -> tuple:
        """读取设备传感器"""
        return ({"status": "online", "health": "good"}, "device_info", 0.8)
    
    def add_rule(self, rule: SensingRule) -> bool:
        """添加感知规则"""
        with self._lock:
            if rule.rule_id in self.rules:
                return False
            self.rules[rule.rule_id] = rule
            logger.info(f"Added sensing rule: {rule.rule_id}")
            return True
    
    def remove_rule(self, rule_id: str) -> bool:
        """移除感知规则"""
        with self._lock:
            if rule_id not in self.rules:
                return False
            del self.rules[rule_id]
            return True
    
    async def _check_rules(self, reading: SensorReading):
        """检查规则是否触发"""
        for rule in self.rules.values():
            if not rule.enabled:
                continue
            if reading.sensor_id not in rule.sensors:
                continue
            
            try:
                # 简化的条件评估
                triggered = self._evaluate_condition(rule.condition, reading)
                if triggered:
                    await self._trigger_rule(rule, reading)
            except Exception as e:
                logger.error(f"Error checking rule {rule.rule_id}: {e}")
    
    def _evaluate_condition(self, condition: str, reading: SensorReading) -> bool:
        """评估条件"""
        # 简化的条件评估
        value = reading.value
        if isinstance(value, (int, float)):
            if ">" in condition:
                threshold = float(condition.split(">")[1].strip())
                return value > threshold
            elif "<" in condition:
                threshold = float(condition.split("<")[1].strip())
                return value < threshold
        return False
    
    async def _trigger_rule(self, rule: SensingRule, reading: SensorReading):
        """触发规则"""
        rule.trigger_count += 1
        rule.last_triggered = datetime.now()
        
        event = DetectedEvent(
            event_id=f"evt_{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
            event_type=f"rule_triggered:{rule.rule_id}",
            source=reading.sensor_id,
            priority=EventPriority.MEDIUM,
            description=f"Rule '{rule.name}' triggered by sensor {reading.sensor_id}",
            data={
                "rule_id": rule.rule_id,
                "sensor_value": reading.value,
                "condition": rule.condition
            }
        )
        
        await self.emit_event(event)
    
    async def emit_event(self, event: DetectedEvent):
        """发出事件"""
        self.events.append(event)
        if len(self.events) > 1000:
            self.events = self.events[-500:]
        
        logger.info(f"Event detected: {event.event_type} from {event.source}")
        
        # 调用事件处理器
        handlers = self._event_handlers.get(event.event_type, [])
        handlers.extend(self._event_handlers.get("*", []))
        for handler in handlers:
            try:
                await handler(event)
            except Exception as e:
                logger.error(f"Error in event handler: {e}")
    
    def register_event_handler(self, event_type: str, handler: Callable):
        """注册事件处理器"""
        if event_type not in self._event_handlers:
            self._event_handlers[event_type] = []
        self._event_handlers[event_type].append(handler)
    
    async def start_sensing(self):
        """启动感知循环"""
        self.is_running = True
        self.mode = SensingMode.ACTIVE
        logger.info("Proactive sensing started")
        
        while self.is_running:
            for sensor_id, sensor in list(self.sensors.items()):
                if sensor.enabled:
                    # 检查是否到了轮询时间
                    if sensor.last_read_time is None or \
                       (datetime.now() - sensor.last_read_time).total_seconds() >= sensor.polling_interval:
                        await self.read_sensor(sensor_id)
            
            await asyncio.sleep(1)
    
    def stop_sensing(self):
        """停止感知循环"""
        self.is_running = False
        self.mode = SensingMode.PASSIVE
        logger.info("Proactive sensing stopped")
    
    def get_status(self) -> Dict[str, Any]:
        """获取感知引擎状态"""
        return {
            "mode": self.mode.value,
            "is_running": self.is_running,
            "sensor_count": len(self.sensors),
            "active_sensors": sum(1 for s in self.sensors.values() if s.enabled),
            "rule_count": len(self.rules),
            "event_count": len(self.events),
            "reading_count": len(self.readings)
        }
    
    def get_recent_events(self, limit: int = 50, priority: Optional[EventPriority] = None) -> List[DetectedEvent]:
        """获取最近的事件"""
        events = self.events
        if priority:
            events = [e for e in events if e.priority == priority]
        return events[-limit:]
    
    def acknowledge_event(self, event_id: str) -> bool:
        """确认事件"""
        for event in self.events:
            if event.event_id == event_id:
                event.acknowledged = True
                return True
        return False


# 全局实例
sensing_engine = ProactiveSensingEngine()


# API 模型
class RegisterSensorRequest(BaseModel):
    sensor_id: str
    sensor_type: str
    name: str
    description: str
    polling_interval: float = 10.0

class AddRuleRequest(BaseModel):
    rule_id: str
    name: str
    condition: str
    action: str
    sensors: List[str]

class EmitEventRequest(BaseModel):
    event_type: str
    source: str
    priority: str = "medium"
    description: str
    data: Dict[str, Any] = {}


# API 端点
@app.get("/health")
async def health_check():
    return {"status": "healthy", "node": "Node_109_ProactiveSensing"}

@app.get("/status")
async def get_status():
    return sensing_engine.get_status()

@app.get("/sensors")
async def list_sensors():
    return {sid: asdict(s) for sid, s in sensing_engine.sensors.items()}

@app.post("/sensors")
async def register_sensor(request: RegisterSensorRequest):
    sensor = Sensor(
        sensor_id=request.sensor_id,
        sensor_type=SensorType(request.sensor_type),
        name=request.name,
        description=request.description,
        polling_interval=request.polling_interval
    )
    success = sensing_engine.register_sensor(sensor)
    return {"success": success}

@app.get("/sensors/{sensor_id}/read")
async def read_sensor(sensor_id: str):
    reading = await sensing_engine.read_sensor(sensor_id)
    if reading:
        return asdict(reading)
    raise HTTPException(status_code=404, detail="Sensor not found or disabled")

@app.post("/rules")
async def add_rule(request: AddRuleRequest):
    rule = SensingRule(
        rule_id=request.rule_id,
        name=request.name,
        condition=request.condition,
        action=request.action,
        sensors=request.sensors
    )
    success = sensing_engine.add_rule(rule)
    return {"success": success}

@app.get("/rules")
async def list_rules():
    return {rid: asdict(r) for rid, r in sensing_engine.rules.items()}

@app.get("/events")
async def get_events(limit: int = 50, priority: Optional[str] = None):
    p = EventPriority(priority) if priority else None
    events = sensing_engine.get_recent_events(limit, p)
    return [asdict(e) for e in events]

@app.post("/events")
async def emit_event(request: EmitEventRequest):
    event = DetectedEvent(
        event_id=f"evt_{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
        event_type=request.event_type,
        source=request.source,
        priority=EventPriority(request.priority),
        description=request.description,
        data=request.data
    )
    await sensing_engine.emit_event(event)
    return {"event_id": event.event_id}

@app.post("/events/{event_id}/acknowledge")
async def acknowledge_event(event_id: str):
    success = sensing_engine.acknowledge_event(event_id)
    return {"success": success}

@app.post("/start")
async def start_sensing(background_tasks: BackgroundTasks):
    if not sensing_engine.is_running:
        background_tasks.add_task(sensing_engine.start_sensing)
        return {"status": "started"}
    return {"status": "already_running"}

@app.post("/stop")
async def stop_sensing():
    sensing_engine.stop_sensing()
    return {"status": "stopped"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8109)
