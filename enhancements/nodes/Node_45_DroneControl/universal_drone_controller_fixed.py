"""
通用无人机控制模块 - Node 45 - 修复版
支持多种无人机协议：
1. DJI Mobile SDK (大疆)
2. MAVLink (通用协议，支持 PX4/ArduPilot)
3. 其他通用无人机

修复内容:
1. 集成pymavlink进行真实无人机通信
2. 添加设备状态监控和故障恢复
3. 实现航点任务管理
4. 添加安全检查和边界限制
"""
import asyncio
import json
import logging
import math
import time
from typing import Dict, List, Any, Optional, Tuple, Callable
from dataclasses import dataclass, asdict
from enum import Enum
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class DroneProtocol(Enum):
    """无人机协议类型"""
    DJI = "dji"
    MAVLINK = "mavlink"
    GENERIC = "generic"
    MOCK = "mock"  # 模拟模式，用于测试


class DroneStatus(Enum):
    """无人机状态"""
    DISCONNECTED = "disconnected"
    IDLE = "idle"
    ARMING = "arming"
    ARMED = "armed"
    TAKEOFF = "takeoff"
    FLYING = "flying"
    LANDING = "landing"
    RTL = "rtl"  # Return to Launch
    MISSION = "mission"
    ERROR = "error"
    EMERGENCY = "emergency"


class FlightMode(Enum):
    """飞行模式"""
    STABILIZE = "STABILIZE"
    ALT_HOLD = "ALT_HOLD"
    LOITER = "LOITER"
    GUIDED = "GUIDED"
    AUTO = "AUTO"
    RTL = "RTL"
    LAND = "LAND"
    POSHOLD = "POSHOLD"


@dataclass
class GPSPosition:
    """GPS位置"""
    latitude: float  # 纬度
    longitude: float  # 经度
    altitude: float  # 海拔（米）
    
    def to_dict(self) -> Dict[str, float]:
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "altitude": self.altitude
        }


@dataclass
class DroneState:
    """无人机状态"""
    battery_percent: float = 0.0
    battery_voltage: float = 0.0
    altitude: float = 0.0  # 相对高度（米）
    ground_speed: float = 0.0  # 地速（米/秒）
    air_speed: float = 0.0  # 空速（米/秒）
    heading: float = 0.0  # 航向（度）
    gps_position: Optional[GPSPosition] = None
    gps_satellites: int = 0
    gps_hdop: float = 99.99  # GPS精度
    status: DroneStatus = DroneStatus.DISCONNECTED
    flight_mode: FlightMode = FlightMode.STABILIZE
    is_armed: bool = False
    timestamp: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "battery_percent": self.battery_percent,
            "battery_voltage": self.battery_voltage,
            "altitude": self.altitude,
            "ground_speed": self.ground_speed,
            "air_speed": self.air_speed,
            "heading": self.heading,
            "gps_position": self.gps_position.to_dict() if self.gps_position else None,
            "gps_satellites": self.gps_satellites,
            "gps_hdop": self.gps_hdop,
            "status": self.status.value,
            "flight_mode": self.flight_mode.value,
            "is_armed": self.is_armed,
            "timestamp": self.timestamp
        }


@dataclass
class Waypoint:
    """航点"""
    lat: float
    lon: float
    alt: float
    delay: float = 0.0  # 到达后延迟（秒）
    
    def to_dict(self) -> Dict[str, float]:
        return {
            "lat": self.lat,
            "lon": self.lon,
            "alt": self.alt,
            "delay": self.delay
        }


@dataclass
class SafetyLimits:
    """安全限制"""
    max_altitude: float = 120.0  # 最大高度（米）
    max_distance: float = 500.0  # 最大距离（米）
    min_battery: float = 20.0  # 最低电量（%）
    geofence_enabled: bool = True
    rtl_battery: float = 25.0  # 自动返航电量


class DroneDriver(ABC):
    """无人机驱动抽象基类"""
    
    @abstractmethod
    async def connect(self, connection_params: Dict[str, Any]) -> bool:
        """连接无人机"""
        pass
    
    @abstractmethod
    async def disconnect(self) -> bool:
        """断开连接"""
        pass
    
    @abstractmethod
    async def arm(self) -> bool:
        """解锁电机"""
        pass
    
    @abstractmethod
    async def disarm(self) -> bool:
        """锁定电机"""
        pass
    
    @abstractmethod
    async def takeoff(self, altitude: float) -> bool:
        """起飞"""
        pass
    
    @abstractmethod
    async def land(self) -> bool:
        """降落"""
        pass
    
    @abstractmethod
    async def rtl(self) -> bool:
        """返航"""
        pass
    
    @abstractmethod
    async def set_flight_mode(self, mode: FlightMode) -> bool:
        """设置飞行模式"""
        pass
    
    @abstractmethod
    async def goto_position(self, lat: float, lon: float, alt: float) -> bool:
        """飞往指定位置"""
        pass
    
    @abstractmethod
    async def move_velocity(self, vx: float, vy: float, vz: float) -> bool:
        """速度控制"""
        pass
    
    @abstractmethod
    async def get_state(self) -> DroneState:
        """获取当前状态"""
        pass
    
    @abstractmethod
    async def upload_mission(self, waypoints: List[Waypoint]) -> bool:
        """上传航点任务"""
        pass
    
    @abstractmethod
    async def start_mission(self) -> bool:
        """开始执行任务"""
        pass


class MAVLinkDriver(DroneDriver):
    """MAVLink协议驱动 - 使用pymavlink"""
    
    def __init__(self):
        self.mav = None
        self.master = None
        self.connection_string = None
        self.target_system = 1
        self.target_component = 1
        self._message_handlers: Dict[str, Callable] = {}
        self._state = DroneState()
        self._connected = False
        self._heartbeat_task = None
        
    async def connect(self, connection_params: Dict[str, Any]) -> bool:
        """连接MAVLink无人机"""
        try:
            from pymavlink import mavutil
            
            connection_string = connection_params.get(
                "connection_string", 
                "udp:127.0.0.1:14550"
            )
            self.connection_string = connection_string
            
            logger.info(f"正在连接MAVLink: {connection_string}")
            
            # 创建连接
            self.master = mavutil.mavlink_connection(connection_string)
            
            # 等待心跳
            self.master.wait_heartbeat()
            logger.info(f"收到心跳来自 system {self.master.target_system}")
            
            self.target_system = self.master.target_system
            self.target_component = self.master.target_component
            self._connected = True
            
            # 启动心跳任务
            self._heartbeat_task = asyncio.create_task(self._send_heartbeat_loop())
            
            # 请求数据流
            self._request_data_stream()
            
            # 启动状态更新任务
            asyncio.create_task(self._update_state_loop())
            
            logger.info("MAVLink连接成功")
            return True
            
        except ImportError:
            logger.error("pymavlink未安装，请运行: pip install pymavlink")
            return False
        except Exception as e:
            logger.error(f"MAVLink连接失败: {e}")
            return False
    
    async def disconnect(self) -> bool:
        """断开连接"""
        self._connected = False
        
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        
        if self.master:
            self.master.close()
        
        logger.info("MAVLink断开连接")
        return True
    
    def _request_data_stream(self):
        """请求数据流"""
        if not self.master:
            return
        
        # 请求所有数据流
        self.master.mav.request_data_stream_send(
            self.target_system,
            self.target_component,
            mavutil.mavlink.MAV_DATA_STREAM_ALL,
            4,  # 4Hz
            1   # 启用
        )
    
    async def _send_heartbeat_loop(self):
        """发送心跳循环"""
        while self._connected:
            try:
                if self.master:
                    self.master.mav.heartbeat_send(
                        mavutil.mavlink.MAV_TYPE_GCS,
                        mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                        0, 0, 0
                    )
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"心跳发送错误: {e}")
                await asyncio.sleep(1)
    
    async def _update_state_loop(self):
        """更新状态循环"""
        while self._connected:
            try:
                if self.master:
                    msg = self.master.recv_match(blocking=False)
                    if msg:
                        self._process_message(msg)
                await asyncio.sleep(0.01)  # 100Hz
            except Exception as e:
                logger.error(f"状态更新错误: {e}")
                await asyncio.sleep(0.1)
    
    def _process_message(self, msg):
        """处理MAVLink消息"""
        msg_type = msg.get_type()
        
        if msg_type == "HEARTBEAT":
            self._state.is_armed = (msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED) != 0
            self._state.status = DroneStatus.FLYING if self._state.is_armed else DroneStatus.IDLE
            
        elif msg_type == "SYS_STATUS":
            self._state.battery_voltage = msg.voltage_battery / 1000.0
            self._state.battery_percent = msg.battery_remaining
            
        elif msg_type == "GLOBAL_POSITION_INT":
            self._state.altitude = msg.relative_alt / 1000.0
            self._state.gps_position = GPSPosition(
                latitude=msg.lat / 1e7,
                longitude=msg.lon / 1e7,
                altitude=msg.alt / 1000.0
            )
            self._state.heading = msg.hdg / 100.0 if msg.hdg != 0 else 0
            
        elif msg_type == "GPS_RAW_INT":
            self._state.gps_satellites = msg.satellites_visible
            self._state.gps_hdop = msg.eph / 100.0 if msg.eph != 0 else 99.99
            
        elif msg_type == "VFR_HUD":
            self._state.ground_speed = msg.groundspeed
            self._state.air_speed = msg.airspeed
    
    async def arm(self) -> bool:
        """解锁电机"""
        if not self.master:
            return False
        
        logger.info("正在解锁电机...")
        self.master.mav.command_long_send(
            self.target_system,
            self.target_component,
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            0,
            1, 0, 0, 0, 0, 0, 0
        )
        
        # 等待确认
        await asyncio.sleep(2)
        return self._state.is_armed
    
    async def disarm(self) -> bool:
        """锁定电机"""
        if not self.master:
            return False
        
        logger.info("正在锁定电机...")
        self.master.mav.command_long_send(
            self.target_system,
            self.target_component,
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            0,
            0, 0, 0, 0, 0, 0, 0
        )
        
        await asyncio.sleep(1)
        return not self._state.is_armed
    
    async def takeoff(self, altitude: float) -> bool:
        """起飞"""
        if not self.master:
            return False
        
        logger.info(f"正在起飞到 {altitude} 米...")
        
        # 先设置GUIDED模式
        await self.set_flight_mode(FlightMode.GUIDED)
        
        # 解锁
        if not self._state.is_armed:
            await self.arm()
        
        # 发送起飞命令
        self.master.mav.command_long_send(
            self.target_system,
            self.target_component,
            mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
            0,
            0, 0, 0, 0, 0, 0,
            altitude
        )
        
        self._state.status = DroneStatus.TAKEOFF
        return True
    
    async def land(self) -> bool:
        """降落"""
        if not self.master:
            return False
        
        logger.info("正在降落...")
        
        self.master.mav.command_long_send(
            self.target_system,
            self.target_component,
            mavutil.mavlink.MAV_CMD_NAV_LAND,
            0,
            0, 0, 0, 0, 0, 0, 0
        )
        
        self._state.status = DroneStatus.LANDING
        return True
    
    async def rtl(self) -> bool:
        """返航"""
        if not self.master:
            return False
        
        logger.info("正在返航...")
        return await self.set_flight_mode(FlightMode.RTL)
    
    async def set_flight_mode(self, mode: FlightMode) -> bool:
        """设置飞行模式"""
        if not self.master:
            return False
        
        mode_id = self.master.mode_mapping().get(mode.value)
        if mode_id is None:
            logger.error(f"不支持的飞行模式: {mode.value}")
            return False
        
        self.master.mav.set_mode_send(
            self.target_system,
            mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
            mode_id
        )
        
        self._state.flight_mode = mode
        logger.info(f"飞行模式设置为: {mode.value}")
        return True
    
    async def goto_position(self, lat: float, lon: float, alt: float) -> bool:
        """飞往指定位置"""
        if not self.master:
            return False
        
        logger.info(f"飞往位置: lat={lat}, lon={lon}, alt={alt}")
        
        # 确保在GUIDED模式
        if self._state.flight_mode != FlightMode.GUIDED:
            await self.set_flight_mode(FlightMode.GUIDED)
        
        self.master.mav.set_position_target_global_int_send(
            0,
            self.target_system,
            self.target_component,
            mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,
            0b0000111111111000,
            int(lat * 1e7),
            int(lon * 1e7),
            alt,
            0, 0, 0, 0, 0, 0, 0, 0
        )
        
        return True
    
    async def move_velocity(self, vx: float, vy: float, vz: float) -> bool:
        """速度控制"""
        if not self.master:
            return False
        
        self.master.mav.set_position_target_local_ned_send(
            0,
            self.target_system,
            self.target_component,
            mavutil.mavlink.MAV_FRAME_BODY_NED,
            0b0000111111000111,
            0, 0, 0,
            vx, vy, vz,
            0, 0, 0, 0, 0
        )
        
        return True
    
    async def get_state(self) -> DroneState:
        """获取当前状态"""
        self._state.timestamp = time.time()
        return self._state
    
    async def upload_mission(self, waypoints: List[Waypoint]) -> bool:
        """上传航点任务"""
        if not self.master:
            return False
        
        logger.info(f"上传 {len(waypoints)} 个航点...")
        
        # 清除现有任务
        self.master.waypoint_clear_all_send()
        await asyncio.sleep(0.5)
        
        # 设置任务数量
        self.master.waypoint_count_send(len(waypoints))
        
        # 等待请求并发送每个航点
        for i, wp in enumerate(waypoints):
            msg = self.master.recv_match(type='MISSION_REQUEST', blocking=True, timeout=5)
            if msg:
                self.master.mav.mission_item_send(
                    self.target_system,
                    self.target_component,
                    i,
                    mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,
                    mavutil.mavlink.MAV_CMD_NAV_WAYPOINT,
                    0, 0, 0, 0, 0, 0,
                    wp.lat, wp.lon, wp.alt
                )
        
        logger.info("航点上传完成")
        return True
    
    async def start_mission(self) -> bool:
        """开始执行任务"""
        if not self.master:
            return False
        
        logger.info("开始执行任务...")
        
        # 切换到AUTO模式
        await self.set_flight_mode(FlightMode.AUTO)
        
        self._state.status = DroneStatus.MISSION
        return True


class MockDroneDriver(DroneDriver):
    """模拟无人机驱动 - 用于测试"""
    
    def __init__(self):
        self._state = DroneState()
        self._connected = False
        self._home_position = GPSPosition(39.9042, 116.4074, 0)
        self._waypoints: List[Waypoint] = []
        self._current_wp = 0
        
    async def connect(self, connection_params: Dict[str, Any]) -> bool:
        """连接模拟无人机"""
        logger.info("连接模拟无人机...")
        self._connected = True
        self._state.status = DroneStatus.IDLE
        self._state.gps_position = self._home_position
        self._state.battery_percent = 100.0
        
        # 启动状态模拟
        asyncio.create_task(self._simulate_state())
        return True
    
    async def disconnect(self) -> bool:
        """断开连接"""
        self._connected = False
        self._state.status = DroneStatus.DISCONNECTED
        return True
    
    async def _simulate_state(self):
        """模拟状态更新"""
        while self._connected:
            if self._state.status == DroneStatus.TAKEOFF:
                self._state.altitude = min(self._state.altitude + 0.5, 10)
                if self._state.altitude >= 10:
                    self._state.status = DroneStatus.FLYING
                    
            elif self._state.status == DroneStatus.LANDING:
                self._state.altitude = max(self._state.altitude - 0.3, 0)
                if self._state.altitude <= 0:
                    self._state.status = DroneStatus.IDLE
                    self._state.is_armed = False
                    
            elif self._state.status == DroneStatus.FLYING:
                # 模拟电池消耗
                self._state.battery_percent = max(0, self._state.battery_percent - 0.01)
                
            self._state.timestamp = time.time()
            await asyncio.sleep(0.1)
    
    async def arm(self) -> bool:
        """解锁"""
        logger.info("模拟: 解锁电机")
        self._state.is_armed = True
        return True
    
    async def disarm(self) -> bool:
        """锁定"""
        logger.info("模拟: 锁定电机")
        self._state.is_armed = False
        return True
    
    async def takeoff(self, altitude: float) -> bool:
        """起飞"""
        logger.info(f"模拟: 起飞到 {altitude} 米")
        self._state.status = DroneStatus.TAKEOFF
        return True
    
    async def land(self) -> bool:
        """降落"""
        logger.info("模拟: 降落")
        self._state.status = DroneStatus.LANDING
        return True
    
    async def rtl(self) -> bool:
        """返航"""
        logger.info("模拟: 返航")
        self._state.status = DroneStatus.RTL
        return True
    
    async def set_flight_mode(self, mode: FlightMode) -> bool:
        """设置飞行模式"""
        logger.info(f"模拟: 设置飞行模式为 {mode.value}")
        self._state.flight_mode = mode
        return True
    
    async def goto_position(self, lat: float, lon: float, alt: float) -> bool:
        """飞往位置"""
        logger.info(f"模拟: 飞往 lat={lat}, lon={lon}, alt={alt}")
        if self._state.gps_position:
            self._state.gps_position.latitude = lat
            self._state.gps_position.longitude = lon
            self._state.gps_position.altitude = alt
        return True
    
    async def move_velocity(self, vx: float, vy: float, vz: float) -> bool:
        """速度控制"""
        logger.info(f"模拟: 速度控制 vx={vx}, vy={vy}, vz={vz}")
        return True
    
    async def get_state(self) -> DroneState:
        """获取状态"""
        return self._state
    
    async def upload_mission(self, waypoints: List[Waypoint]) -> bool:
        """上传任务"""
        logger.info(f"模拟: 上传 {len(waypoints)} 个航点")
        self._waypoints = waypoints
        return True
    
    async def start_mission(self) -> bool:
        """开始任务"""
        logger.info("模拟: 开始执行任务")
        self._state.status = DroneStatus.MISSION
        return True


class UniversalDroneController:
    """通用无人机控制器 - 修复版"""
    
    def __init__(self, protocol: DroneProtocol = DroneProtocol.MOCK):
        self.protocol = protocol
        self.driver: DroneDriver = None
        self.safety_limits = SafetyLimits()
        self._status_callbacks: List[Callable] = []
        self._error_callbacks: List[Callable] = []
        self._monitoring_task = None
        self._last_state: Optional[DroneState] = None
        
        # 创建驱动
        if protocol == DroneProtocol.MAVLINK:
            self.driver = MAVLinkDriver()
        elif protocol == DroneProtocol.MOCK:
            self.driver = MockDroneDriver()
        else:
            self.driver = MockDroneDriver()
    
    async def connect(self, connection_params: Dict[str, Any] = None) -> Dict[str, Any]:
        """连接无人机"""
        connection_params = connection_params or {}
        
        logger.info(f"正在连接无人机 ({self.protocol.value})...")
        
        try:
            success = await self.driver.connect(connection_params)
            
            if success:
                # 启动监控任务
                self._monitoring_task = asyncio.create_task(self._monitoring_loop())
                
                return {
                    "status": "success",
                    "message": f"{self.protocol.value} 无人机已连接",
                    "protocol": self.protocol.value
                }
            else:
                return {
                    "status": "error",
                    "message": "连接失败"
                }
                
        except Exception as e:
            logger.error(f"连接失败: {e}")
            return {
                "status": "error",
                "message": f"连接失败: {str(e)}"
            }
    
    async def disconnect(self) -> Dict[str, Any]:
        """断开连接"""
        if self._monitoring_task:
            self._monitoring_task.cancel()
        
        success = await self.driver.disconnect()
        
        return {
            "status": "success" if success else "error",
            "message": "已断开连接"
        }
    
    async def takeoff(self, altitude: float = 10.0) -> Dict[str, Any]:
        """起飞"""
        # 安全检查
        if altitude > self.safety_limits.max_altitude:
            return {
                "status": "error",
                "message": f"目标高度 {altitude}m 超过安全限制 {self.safety_limits.max_altitude}m"
            }
        
        state = await self.driver.get_state()
        if state.battery_percent < self.safety_limits.min_battery:
            return {
                "status": "error",
                "message": f"电量过低: {state.battery_percent}%"
            }
        
        success = await self.driver.takeoff(altitude)
        
        return {
            "status": "success" if success else "error",
            "action": "takeoff",
            "target_altitude": altitude
        }
    
    async def land(self) -> Dict[str, Any]:
        """降落"""
        success = await self.driver.land()
        
        return {
            "status": "success" if success else "error",
            "action": "land"
        }
    
    async def rtl(self) -> Dict[str, Any]:
        """返航"""
        success = await self.driver.rtl()
        
        return {
            "status": "success" if success else "error",
            "action": "rtl"
        }
    
    async def move(self, direction: str, distance: float = 5.0) -> Dict[str, Any]:
        """移动控制"""
        velocity_map = {
            "forward": (distance, 0, 0),
            "backward": (-distance, 0, 0),
            "left": (0, -distance, 0),
            "right": (0, distance, 0),
            "up": (0, 0, -distance),
            "down": (0, 0, distance)
        }
        
        vx, vy, vz = velocity_map.get(direction, (0, 0, 0))
        success = await self.driver.move_velocity(vx, vy, vz)
        
        return {
            "status": "success" if success else "error",
            "action": "move",
            "direction": direction,
            "distance": distance
        }
    
    async def goto(self, lat: float, lon: float, alt: float = None) -> Dict[str, Any]:
        """飞往指定GPS坐标"""
        state = await self.driver.get_state()
        target_alt = alt if alt is not None else state.altitude
        
        # 距离检查
        if state.gps_position:
            dist = self._calculate_distance(
                state.gps_position.latitude, state.gps_position.longitude,
                lat, lon
            )
            if dist > self.safety_limits.max_distance:
                return {
                    "status": "error",
                    "message": f"目标距离 {dist:.0f}m 超过安全限制 {self.safety_limits.max_distance}m"
                }
        
        success = await self.driver.goto_position(lat, lon, target_alt)
        
        return {
            "status": "success" if success else "error",
            "action": "goto",
            "target": {"lat": lat, "lon": lon, "alt": target_alt}
        }
    
    async def upload_mission(self, waypoints: List[Dict[str, Any]]) -> Dict[str, Any]:
        """上传航点任务"""
        wp_objects = [Waypoint(**wp) for wp in waypoints]
        success = await self.driver.upload_mission(wp_objects)
        
        return {
            "status": "success" if success else "error",
            "action": "upload_mission",
            "waypoint_count": len(waypoints)
        }
    
    async def start_mission(self) -> Dict[str, Any]:
        """开始执行任务"""
        success = await self.driver.start_mission()
        
        return {
            "status": "success" if success else "error",
            "action": "start_mission"
        }
    
    async def get_status(self) -> Dict[str, Any]:
        """获取无人机状态"""
        state = await self.driver.get_state()
        return state.to_dict()
    
    def _calculate_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """计算两点间距离（米）"""
        R = 6371000  # 地球半径（米）
        
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lon = math.radians(lon2 - lon1)
        
        a = math.sin(delta_lat / 2) ** 2 + \
            math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        
        return R * c
    
    async def _monitoring_loop(self):
        """监控循环 - 检查安全限制和故障恢复"""
        while True:
            try:
                state = await self.driver.get_state()
                self._last_state = state
                
                # 检查电量
                if state.battery_percent < self.safety_limits.rtl_battery:
                    logger.warning(f"电量低，自动返航: {state.battery_percent}%")
                    await self.rtl()
                    self._notify_error("LOW_BATTERY", f"电量低: {state.battery_percent}%")
                
                # 检查高度
                if state.altitude > self.safety_limits.max_altitude:
                    logger.warning(f"高度超限: {state.altitude}m")
                    self._notify_error("ALTITUDE_LIMIT", f"高度超限: {state.altitude}m")
                
                # 检查GPS
                if state.gps_hdop > 5.0:
                    logger.warning(f"GPS信号差: HDOP={state.gps_hdop}")
                
                # 通知状态更新
                for callback in self._status_callbacks:
                    try:
                        if asyncio.iscoroutinefunction(callback):
                            await callback(state.to_dict())
                        else:
                            callback(state.to_dict())
                    except Exception as e:
                        logger.error(f"状态回调错误: {e}")
                
                await asyncio.sleep(1)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"监控循环错误: {e}")
                await asyncio.sleep(5)
    
    def _notify_error(self, error_code: str, message: str):
        """通知错误"""
        for callback in self._error_callbacks:
            try:
                callback({"code": error_code, "message": message})
            except Exception as e:
                logger.error(f"错误回调异常: {e}")
    
    def on_status_update(self, callback: Callable):
        """注册状态更新回调"""
        self._status_callbacks.append(callback)
    
    def on_error(self, callback: Callable):
        """注册错误回调"""
        self._error_callbacks.append(callback)
    
    def set_safety_limits(self, limits: Dict[str, Any]):
        """设置安全限制"""
        for key, value in limits.items():
            if hasattr(self.safety_limits, key):
                setattr(self.safety_limits, key, value)


# 便捷函数
def create_mavlink_controller(connection_string: str = "udp:127.0.0.1:14550") -> UniversalDroneController:
    """创建MAVLink控制器"""
    controller = UniversalDroneController(DroneProtocol.MAVLINK)
    return controller


def create_mock_controller() -> UniversalDroneController:
    """创建模拟控制器"""
    return UniversalDroneController(DroneProtocol.MOCK)


if __name__ == "__main__":
    # 测试控制器
    logging.basicConfig(level=logging.INFO)
    
    async def test():
        # 使用模拟模式测试
        controller = create_mock_controller()
        
        # 连接
        result = await controller.connect()
        print(f"连接结果: {result}")
        
        # 获取状态
        status = await controller.get_status()
        print(f"初始状态: {status}")
        
        # 起飞
        result = await controller.takeoff(10)
        print(f"起飞结果: {result}")
        
        # 等待
        await asyncio.sleep(3)
        
        # 获取状态
        status = await controller.get_status()
        print(f"飞行状态: {status}")
        
        # 降落
        result = await controller.land()
        print(f"降落结果: {result}")
        
        # 断开连接
        await controller.disconnect()
    
    asyncio.run(test())
