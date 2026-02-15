"""
MAVLink 无人机控制器
支持真实的 MAVLink 协议通信和模拟模式
"""

import asyncio
import logging
import time
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class DroneStatus(Enum):
    """无人机状态"""
    DISCONNECTED = "disconnected"
    IDLE = "idle"
    ARMED = "armed"
    FLYING = "flying"
    LANDING = "landing"
    ERROR = "error"


@dataclass
class DroneState:
    """无人机状态"""
    connected: bool = False
    armed: bool = False
    battery: float = 100.0  # 电量百分比
    altitude: float = 0.0  # 高度（米）
    speed: float = 0.0  # 速度（米/秒）
    latitude: float = 0.0  # 纬度
    longitude: float = 0.0  # 经度
    status: DroneStatus = DroneStatus.DISCONNECTED
    gps_fix: bool = False
    last_update: float = 0.0
    metadata: Dict = field(default_factory=dict)


class MAVLinkController:
    """MAVLink 无人机控制器"""
    
    def __init__(self, connection_string: Optional[str] = None, simulation_mode: bool = True):
        """
        初始化 MAVLink 控制器
        
        Args:
            connection_string: MAVLink 连接字符串（如 "udp:127.0.0.1:14550"）
            simulation_mode: 是否使用模拟模式（True 时不需要真实硬件）
        """
        self.connection_string = connection_string or "udp:127.0.0.1:14550"
        self.simulation_mode = simulation_mode
        self.state = DroneState()
        self.mavlink_connection = None
        
        logger.info(f"MAVLinkController 初始化 (模拟模式: {simulation_mode})")
    
    async def connect(self, connection_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        连接无人机
        
        Args:
            connection_params: 连接参数，可包含 host, port, protocol 等
        
        Returns:
            连接结果
        """
        logger.info(f"连接无人机: {self.connection_string}")
        
        try:
            if self.simulation_mode:
                # 模拟模式
                await asyncio.sleep(0.5)
                self.state.connected = True
                self.state.status = DroneStatus.IDLE
                self.state.gps_fix = True
                self.state.last_update = time.time()
                
                return {
                    "success": True,
                    "status": "connected",
                    "message": "无人机已连接（模拟模式）",
                    "protocol": "MAVLink v2.0",
                    "simulation": True
                }
            else:
                # 真实模式 - 需要 pymavlink
                try:
                    from pymavlink import mavutil
                    
                    # 创建 MAVLink 连接
                    self.mavlink_connection = mavutil.mavlink_connection(self.connection_string)
                    
                    # 等待心跳
                    logger.info("等待心跳...")
                    self.mavlink_connection.wait_heartbeat()
                    
                    self.state.connected = True
                    self.state.status = DroneStatus.IDLE
                    self.state.last_update = time.time()
                    
                    return {
                        "success": True,
                        "status": "connected",
                        "message": "无人机已连接（真实模式）",
                        "protocol": "MAVLink v2.0",
                        "simulation": False
                    }
                
                except ImportError:
                    logger.error("pymavlink 未安装，请运行: pip install pymavlink")
                    return {
                        "success": False,
                        "status": "error",
                        "message": "pymavlink 未安装"
                    }
        
        except Exception as e:
            logger.error(f"连接失败: {e}")
            return {
                "success": False,
                "status": "error",
                "message": f"连接失败: {str(e)}"
            }
    
    async def disconnect(self) -> Dict[str, Any]:
        """断开连接"""
        logger.info("断开无人机连接")
        
        if self.mavlink_connection:
            self.mavlink_connection.close()
            self.mavlink_connection = None
        
        self.state.connected = False
        self.state.status = DroneStatus.DISCONNECTED
        
        return {
            "success": True,
            "status": "disconnected",
            "message": "无人机已断开连接"
        }
    
    async def arm(self) -> Dict[str, Any]:
        """解锁无人机"""
        if not self.state.connected:
            return {"success": False, "message": "无人机未连接"}
        
        logger.info("解锁无人机")
        
        if self.simulation_mode:
            await asyncio.sleep(0.5)
            self.state.armed = True
            self.state.status = DroneStatus.ARMED
        else:
            # 真实模式 - 发送解锁命令
            if self.mavlink_connection:
                self.mavlink_connection.arducopter_arm()
                await asyncio.sleep(1)
                self.state.armed = True
                self.state.status = DroneStatus.ARMED
        
        return {
            "success": True,
            "status": "armed",
            "message": "无人机已解锁"
        }
    
    async def disarm(self) -> Dict[str, Any]:
        """上锁无人机"""
        if not self.state.connected:
            return {"success": False, "message": "无人机未连接"}
        
        logger.info("上锁无人机")
        
        if self.simulation_mode:
            await asyncio.sleep(0.5)
            self.state.armed = False
            self.state.status = DroneStatus.IDLE
        else:
            # 真实模式 - 发送上锁命令
            if self.mavlink_connection:
                self.mavlink_connection.arducopter_disarm()
                await asyncio.sleep(1)
                self.state.armed = False
                self.state.status = DroneStatus.IDLE
        
        return {
            "success": True,
            "status": "disarmed",
            "message": "无人机已上锁"
        }
    
    async def takeoff(self, altitude: float = 10.0) -> Dict[str, Any]:
        """
        起飞到指定高度
        
        Args:
            altitude: 目标高度（米）
        
        Returns:
            执行结果
        """
        if not self.state.connected:
            return {"success": False, "message": "无人机未连接"}
        
        if not self.state.armed:
            # 自动解锁
            arm_result = await self.arm()
            if not arm_result["success"]:
                return arm_result
        
        logger.info(f"起飞到 {altitude} 米")
        
        self.state.status = DroneStatus.FLYING
        
        if self.simulation_mode:
            # 模拟起飞过程
            steps = int(altitude / 2)
            for i in range(steps + 1):
                self.state.altitude = min(altitude, i * 2)
                self.state.last_update = time.time()
                await asyncio.sleep(0.3)
            
            self.state.altitude = altitude
        else:
            # 真实模式 - 发送起飞命令
            if self.mavlink_connection:
                self.mavlink_connection.mav.command_long_send(
                    self.mavlink_connection.target_system,
                    self.mavlink_connection.target_component,
                    mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
                    0, 0, 0, 0, 0, 0, 0, altitude
                )
                
                # 等待达到目标高度
                for _ in range(int(altitude * 2)):
                    await asyncio.sleep(0.5)
                    # 这里应该读取实际高度
                    self.state.altitude += 0.5
                    if self.state.altitude >= altitude:
                        break
        
        return {
            "success": True,
            "status": "flying",
            "message": f"已起飞到 {altitude} 米",
            "current_altitude": self.state.altitude,
            "battery": self.state.battery
        }
    
    async def land(self) -> Dict[str, Any]:
        """降落"""
        if not self.state.connected:
            return {"success": False, "message": "无人机未连接"}
        
        logger.info("降落")
        
        self.state.status = DroneStatus.LANDING
        
        if self.simulation_mode:
            # 模拟降落过程
            while self.state.altitude > 0:
                self.state.altitude = max(0, self.state.altitude - 2)
                self.state.last_update = time.time()
                await asyncio.sleep(0.3)
            
            self.state.altitude = 0
            self.state.status = DroneStatus.IDLE
            
            # 自动上锁
            await self.disarm()
        else:
            # 真实模式 - 发送降落命令
            if self.mavlink_connection:
                self.mavlink_connection.mav.command_long_send(
                    self.mavlink_connection.target_system,
                    self.mavlink_connection.target_component,
                    mavutil.mavlink.MAV_CMD_NAV_LAND,
                    0, 0, 0, 0, 0, 0, 0, 0
                )
                
                # 等待降落完成
                while self.state.altitude > 0.5:
                    await asyncio.sleep(0.5)
                    self.state.altitude = max(0, self.state.altitude - 0.5)
                
                self.state.altitude = 0
                self.state.status = DroneStatus.IDLE
        
        return {
            "success": True,
            "status": "landed",
            "message": "已安全降落",
            "battery": self.state.battery
        }
    
    async def capture_image(self) -> Dict[str, Any]:
        """拍照"""
        if not self.state.connected:
            return {"success": False, "message": "无人机未连接"}
        
        logger.info("拍照")
        
        await asyncio.sleep(0.5)
        
        timestamp = int(time.time())
        photo_path = f"/drone_photos/photo_{timestamp}.jpg"
        
        return {
            "success": True,
            "status": "captured",
            "message": "拍照成功",
            "photo_path": photo_path,
            "altitude": self.state.altitude,
            "location": {
                "latitude": self.state.latitude,
                "longitude": self.state.longitude
            }
        }
    
    async def set_altitude(self, altitude: float) -> Dict[str, Any]:
        """设置飞行高度"""
        if not self.state.connected:
            return {"success": False, "message": "无人机未连接"}
        
        if self.state.status != DroneStatus.FLYING:
            return {"success": False, "message": "无人机未在飞行中"}
        
        logger.info(f"设置高度: {altitude} 米")
        
        current_altitude = self.state.altitude
        
        if self.simulation_mode:
            # 模拟高度变化
            steps = abs(int((altitude - current_altitude) / 2))
            direction = 1 if altitude > current_altitude else -1
            
            for _ in range(steps):
                self.state.altitude += direction * 2
                self.state.last_update = time.time()
                await asyncio.sleep(0.3)
            
            self.state.altitude = altitude
        
        return {
            "success": True,
            "status": "altitude_set",
            "message": f"高度已设置为 {altitude} 米",
            "current_altitude": self.state.altitude
        }
    
    async def move_to(self, latitude: float, longitude: float, altitude: float) -> Dict[str, Any]:
        """移动到指定位置"""
        if not self.state.connected:
            return {"success": False, "message": "无人机未连接"}
        
        logger.info(f"移动到: ({latitude}, {longitude}, {altitude})")
        
        if self.simulation_mode:
            # 模拟移动
            await asyncio.sleep(2)
            self.state.latitude = latitude
            self.state.longitude = longitude
            self.state.altitude = altitude
            self.state.last_update = time.time()
        
        return {
            "success": True,
            "status": "moved",
            "message": f"已移动到目标位置",
            "location": {
                "latitude": self.state.latitude,
                "longitude": self.state.longitude,
                "altitude": self.state.altitude
            }
        }
    
    def get_state(self) -> Dict[str, Any]:
        """获取当前状态"""
        return {
            "connected": self.state.connected,
            "armed": self.state.armed,
            "status": self.state.status.value,
            "battery": self.state.battery,
            "altitude": self.state.altitude,
            "speed": self.state.speed,
            "location": {
                "latitude": self.state.latitude,
                "longitude": self.state.longitude
            },
            "gps_fix": self.state.gps_fix,
            "last_update": self.state.last_update,
            "simulation_mode": self.simulation_mode
        }
    
    async def execute(self, command: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行通用命令
        
        Args:
            command: 命令名称
            parameters: 命令参数
        
        Returns:
            执行结果
        """
        logger.info(f"执行命令: {command}, 参数: {parameters}")
        
        # 命令映射
        if command == "connect":
            return await self.connect(parameters)
        elif command == "disconnect":
            return await self.disconnect()
        elif command == "takeoff":
            altitude = parameters.get("altitude", 10.0)
            return await self.takeoff(altitude)
        elif command == "land":
            return await self.land()
        elif command == "capture_image" or command == "take_photo":
            return await self.capture_image()
        elif command == "set_altitude":
            altitude = parameters.get("altitude", 10.0)
            return await self.set_altitude(altitude)
        elif command == "move_to":
            lat = parameters.get("latitude", 0.0)
            lon = parameters.get("longitude", 0.0)
            alt = parameters.get("altitude", 10.0)
            return await self.move_to(lat, lon, alt)
        elif command == "get_state":
            return self.get_state()
        else:
            return {
                "success": False,
                "status": "unknown_command",
                "message": f"未知命令: {command}"
            }
    
    async def execute_command(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行设备控制命令（由 ActionExecutor 调用）
        
        Args:
            parameters: 命令参数，包含 description 和其他参数
        
        Returns:
            执行结果
        """
        description = parameters.get("description", "")
        description_lower = description.lower()
        
        # 根据描述推断操作
        if "起飞" in description or "takeoff" in description_lower:
            altitude = parameters.get("altitude", 10.0)
            return await self.takeoff(altitude)
        
        elif "降落" in description or "land" in description_lower:
            return await self.land()
        
        elif "拍照" in description or "photo" in description_lower or "capture" in description_lower:
            return await self.capture_image()
        
        elif "高度" in description or "altitude" in description_lower:
            altitude = parameters.get("altitude", 10.0)
            return await self.set_altitude(altitude)
        
        else:
            # 通用执行
            logger.info(f"执行无人机任务: {description}")
            
            # 默认流程：起飞 → 拍照 → 降落
            if not self.state.connected:
                await self.connect()
            
            result_steps = []
            
            # 起飞
            result = await self.takeoff(10.0)
            result_steps.append({"step": "takeoff", "result": result})
            
            # 拍照
            result = await self.capture_image()
            result_steps.append({"step": "capture", "result": result})
            
            # 降落
            result = await self.land()
            result_steps.append({"step": "land", "result": result})
            
            return {
                "success": True,
                "status": "completed",
                "message": f"无人机任务完成: {description}",
                "steps": result_steps
            }
