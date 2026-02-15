"""
Bambu Lab 3D打印机控制器 - Node 43 - 修复版
支持Bambu Lab打印机控制

修复内容:
1. 集成bambulab-api进行真实打印机通信
2. 添加OctoPrint API支持
3. 实现打印任务管理
4. 添加设备状态监控和故障检测
"""
import asyncio
import json
import logging
import time
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, asdict
from enum import Enum
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class PrinterStatus(Enum):
    """打印机状态"""
    DISCONNECTED = "disconnected"
    IDLE = "idle"
    PRINTING = "printing"
    PAUSED = "paused"
    FINISHED = "finished"
    ERROR = "error"
    PREHEATING = "preheating"
    FILAMENT_CHANGE = "filament_change"


class PrinterCommand(Enum):
    """打印机命令"""
    START_PRINT = "start_print"
    PAUSE_PRINT = "pause_print"
    RESUME_PRINT = "resume_print"
    STOP_PRINT = "stop_print"
    SET_TEMPERATURE = "set_temperature"
    MOVE_AXIS = "move_axis"
    HOME_AXIS = "home_axis"


@dataclass
class TemperatureStatus:
    """温度状态"""
    nozzle_current: float = 0.0
    nozzle_target: float = 0.0
    bed_current: float = 0.0
    bed_target: float = 0.0
    chamber_current: float = 0.0
    chamber_target: float = 0.0
    
    def to_dict(self) -> Dict[str, float]:
        return {
            "nozzle_current": self.nozzle_current,
            "nozzle_target": self.nozzle_target,
            "bed_current": self.bed_current,
            "bed_target": self.bed_target,
            "chamber_current": self.chamber_current,
            "chamber_target": self.chamber_target
        }


@dataclass
class PrintProgress:
    """打印进度"""
    percent: float = 0.0
    current_layer: int = 0
    total_layers: int = 0
    print_time: int = 0  # 秒
    print_time_left: int = 0  # 秒
    file_name: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "percent": self.percent,
            "current_layer": self.current_layer,
            "total_layers": self.total_layers,
            "print_time": self.print_time,
            "print_time_left": self.print_time_left,
            "file_name": self.file_name
        }


@dataclass
class PrinterState:
    """打印机完整状态"""
    status: PrinterStatus = PrinterStatus.DISCONNECTED
    temperatures: TemperatureStatus = None
    progress: PrintProgress = None
    fan_speed: int = 0  # 0-100
    print_speed: int = 100  # 0-100
    lights_on: bool = False
    door_open: bool = False
    timestamp: float = 0.0
    
    def __post_init__(self):
        if self.temperatures is None:
            self.temperatures = TemperatureStatus()
        if self.progress is None:
            self.progress = PrintProgress()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "temperatures": self.temperatures.to_dict(),
            "progress": self.progress.to_dict(),
            "fan_speed": self.fan_speed,
            "print_speed": self.print_speed,
            "lights_on": self.lights_on,
            "door_open": self.door_open,
            "timestamp": self.timestamp
        }


class PrinterDriver(ABC):
    """打印机驱动抽象基类"""
    
    @abstractmethod
    async def connect(self, connection_params: Dict[str, Any]) -> bool:
        """连接打印机"""
        pass
    
    @abstractmethod
    async def disconnect(self) -> bool:
        """断开连接"""
        pass
    
    @abstractmethod
    async def get_state(self) -> PrinterState:
        """获取打印机状态"""
        pass
    
    @abstractmethod
    async def start_print(self, file_path: str, **kwargs) -> bool:
        """开始打印"""
        pass
    
    @abstractmethod
    async def pause_print(self) -> bool:
        """暂停打印"""
        pass
    
    @abstractmethod
    async def resume_print(self) -> bool:
        """恢复打印"""
        pass
    
    @abstractmethod
    async def stop_print(self) -> bool:
        """停止打印"""
        pass
    
    @abstractmethod
    async def set_temperature(self, nozzle: float = None, bed: float = None) -> bool:
        """设置温度"""
        pass
    
    @abstractmethod
    async def move_axis(self, axis: str, distance: float, speed: int = None) -> bool:
        """移动轴"""
        pass
    
    @abstractmethod
    async def home_axis(self, axis: str = "all") -> bool:
        """归零轴"""
        pass
    
    @abstractmethod
    async def send_gcode(self, gcode: str) -> bool:
        """发送G-code命令"""
        pass
    
    @abstractmethod
    async def get_files(self) -> List[Dict[str, Any]]:
        """获取文件列表"""
        pass
    
    @abstractmethod
    async def upload_file(self, file_path: str, content: bytes) -> bool:
        """上传文件"""
        pass


class BambuLabDriver(PrinterDriver):
    """Bambu Lab打印机驱动"""
    
    def __init__(self):
        self._client = None
        self._connected = False
        self._state = PrinterState()
        self._host = None
        self._access_code = None
        self._serial = None
        
    async def connect(self, connection_params: Dict[str, Any]) -> bool:
        """连接Bambu Lab打印机"""
        try:
            # 尝试使用bambulab-api
            try:
                from bambulabs import Printer
                
                self._host = connection_params.get("host")
                self._access_code = connection_params.get("access_code")
                self._serial = connection_params.get("serial")
                
                if not all([self._host, self._access_code, self._serial]):
                    logger.error("连接参数不完整，需要host, access_code, serial")
                    return False
                
                logger.info(f"正在连接Bambu Lab打印机: {self._host}")
                
                self._client = Printer(
                    host=self._host,
                    access_code=self._access_code,
                    serial=self._serial
                )
                
                # 连接并获取初始状态
                self._client.connect()
                self._connected = True
                
                # 启动状态更新循环
                asyncio.create_task(self._update_state_loop())
                
                logger.info("Bambu Lab打印机连接成功")
                return True
                
            except ImportError:
                logger.warning("bambulabs库未安装，尝试使用MQTT直接连接")
                return await self._connect_mqtt(connection_params)
                
        except Exception as e:
            logger.error(f"Bambu Lab连接失败: {e}")
            return False
    
    async def _connect_mqtt(self, connection_params: Dict[str, Any]) -> bool:
        """使用MQTT直接连接"""
        try:
            import paho.mqtt.client as mqtt
            import ssl
            
            self._host = connection_params.get("host")
            self._access_code = connection_params.get("access_code")
            self._serial = connection_params.get("serial")
            
            if not all([self._host, self._access_code, self._serial]):
                return False
            
            self._mqtt_client = mqtt.Client()
            self._mqtt_client.username_pw_set("bblp", self._access_code)
            self._mqtt_client.tls_set(tls_version=ssl.TLSVersion.TLSv1_2)
            self._mqtt_client.tls_insecure_set(True)
            
            self._mqtt_client.on_message = self._on_mqtt_message
            
            self._mqtt_client.connect(self._host, 8883, 60)
            self._mqtt_client.subscribe(f"device/{self._serial}/report")
            self._mqtt_client.loop_start()
            
            self._connected = True
            asyncio.create_task(self._update_state_loop())
            
            logger.info("Bambu Lab MQTT连接成功")
            return True
            
        except ImportError:
            logger.error("paho-mqtt未安装，请运行: pip install paho-mqtt")
            return False
        except Exception as e:
            logger.error(f"MQTT连接失败: {e}")
            return False
    
    def _on_mqtt_message(self, client, userdata, msg):
        """处理MQTT消息"""
        try:
            data = json.loads(msg.payload)
            self._process_printer_data(data)
        except Exception as e:
            logger.error(f"处理MQTT消息错误: {e}")
    
    def _process_printer_data(self, data: Dict[str, Any]):
        """处理打印机数据"""
        if "print" in data:
            print_data = data["print"]
            
            # 状态
            if "stg_cur" in print_data:
                status_map = {
                    0: PrinterStatus.IDLE,
                    1: PrinterStatus.PREHEATING,
                    2: PrinterStatus.PRINTING,
                    3: PrinterStatus.PAUSED,
                    4: PrinterStatus.PRINTING,
                }
                self._state.status = status_map.get(print_data["stg_cur"], PrinterStatus.IDLE)
            
            # 温度
            if "nozzle_temper" in print_data:
                self._state.temperatures.nozzle_current = print_data["nozzle_temper"]
            if "nozzle_target_temper" in print_data:
                self._state.temperatures.nozzle_target = print_data["nozzle_target_temper"]
            if "bed_temper" in print_data:
                self._state.temperatures.bed_current = print_data["bed_temper"]
            if "bed_target_temper" in print_data:
                self._state.temperatures.bed_target = print_data["bed_target_temper"]
            
            # 进度
            if "mc_percent" in print_data:
                self._state.progress.percent = print_data["mc_percent"]
            if "layer_num" in print_data:
                self._state.progress.current_layer = print_data["layer_num"]
            if "total_layer_num" in print_data:
                self._state.progress.total_layers = print_data["total_layer_num"]
            
            # 风扇速度
            if "fan_speed" in print_data:
                self._state.fan_speed = print_data["fan_speed"]
            
            # 灯光
            if "lights_report" in print_data:
                for light in print_data["lights_report"]:
                    if light.get("node") == "chamber_light":
                        self._state.lights_on = light.get("mode") == "on"
            
            self._state.timestamp = time.time()
    
    async def disconnect(self) -> bool:
        """断开连接"""
        self._connected = False
        
        if self._client:
            try:
                self._client.disconnect()
            except Exception:
                pass
        
        if hasattr(self, '_mqtt_client'):
            self._mqtt_client.loop_stop()
            self._mqtt_client.disconnect()
        
        logger.info("Bambu Lab打印机断开连接")
        return True
    
    async def _update_state_loop(self):
        """状态更新循环"""
        while self._connected:
            try:
                if self._client and hasattr(self._client, 'get_state'):
                    # 使用bambulabs-api获取状态
                    state_data = self._client.get_state()
                    if state_data:
                        self._process_printer_data({"print": state_data})
                
                await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"状态更新错误: {e}")
                await asyncio.sleep(5)
    
    async def get_state(self) -> PrinterState:
        """获取打印机状态"""
        return self._state
    
    async def start_print(self, file_path: str, **kwargs) -> bool:
        """开始打印"""
        try:
            if self._client and hasattr(self._client, 'start_print'):
                self._client.start_print(file_path)
                return True
            
            # 使用MQTT发送命令
            if hasattr(self, '_mqtt_client'):
                command = {
                    "print": {
                        "command": "project_file",
                        "param": file_path
                    }
                }
                self._mqtt_client.publish(
                    f"device/{self._serial}/request",
                    json.dumps(command)
                )
                return True
            
            return False
        except Exception as e:
            logger.error(f"开始打印失败: {e}")
            return False
    
    async def pause_print(self) -> bool:
        """暂停打印"""
        try:
            if self._client and hasattr(self._client, 'pause_print'):
                self._client.pause_print()
                return True
            
            if hasattr(self, '_mqtt_client'):
                command = {"print": {"command": "pause"}}
                self._mqtt_client.publish(
                    f"device/{self._serial}/request",
                    json.dumps(command)
                )
                return True
            
            return False
        except Exception as e:
            logger.error(f"暂停打印失败: {e}")
            return False
    
    async def resume_print(self) -> bool:
        """恢复打印"""
        try:
            if self._client and hasattr(self._client, 'resume_print'):
                self._client.resume_print()
                return True
            
            if hasattr(self, '_mqtt_client'):
                command = {"print": {"command": "resume"}}
                self._mqtt_client.publish(
                    f"device/{self._serial}/request",
                    json.dumps(command)
                )
                return True
            
            return False
        except Exception as e:
            logger.error(f"恢复打印失败: {e}")
            return False
    
    async def stop_print(self) -> bool:
        """停止打印"""
        try:
            if self._client and hasattr(self._client, 'stop_print'):
                self._client.stop_print()
                return True
            
            if hasattr(self, '_mqtt_client'):
                command = {"print": {"command": "stop"}}
                self._mqtt_client.publish(
                    f"device/{self._serial}/request",
                    json.dumps(command)
                )
                return True
            
            return False
        except Exception as e:
            logger.error(f"停止打印失败: {e}")
            return False
    
    async def set_temperature(self, nozzle: float = None, bed: float = None) -> bool:
        """设置温度"""
        try:
            if hasattr(self, '_mqtt_client'):
                if nozzle is not None:
                    command = {
                        "print": {
                            "command": "gcode_line",
                            "param": f"M104 S{nozzle}"
                        }
                    }
                    self._mqtt_client.publish(
                        f"device/{self._serial}/request",
                        json.dumps(command)
                    )
                
                if bed is not None:
                    command = {
                        "print": {
                            "command": "gcode_line",
                            "param": f"M140 S{bed}"
                        }
                    }
                    self._mqtt_client.publish(
                        f"device/{self._serial}/request",
                        json.dumps(command)
                    )
                return True
            
            return False
        except Exception as e:
            logger.error(f"设置温度失败: {e}")
            return False
    
    async def move_axis(self, axis: str, distance: float, speed: int = None) -> bool:
        """移动轴"""
        try:
            gcode = f"G1 {axis}{distance}"
            if speed:
                gcode += f" F{speed}"
            return await self.send_gcode(gcode)
        except Exception as e:
            logger.error(f"移动轴失败: {e}")
            return False
    
    async def home_axis(self, axis: str = "all") -> bool:
        """归零轴"""
        try:
            if axis == "all":
                return await self.send_gcode("G28")
            else:
                return await self.send_gcode(f"G28 {axis}")
        except Exception as e:
            logger.error(f"归零轴失败: {e}")
            return False
    
    async def send_gcode(self, gcode: str) -> bool:
        """发送G-code"""
        try:
            if hasattr(self, '_mqtt_client'):
                command = {
                    "print": {
                        "command": "gcode_line",
                        "param": gcode
                    }
                }
                self._mqtt_client.publish(
                    f"device/{self._serial}/request",
                    json.dumps(command)
                )
                return True
            return False
        except Exception as e:
            logger.error(f"发送G-code失败: {e}")
            return False
    
    async def get_files(self) -> List[Dict[str, Any]]:
        """获取文件列表"""
        # Bambu Lab打印机文件列表需要通过FTP获取
        logger.warning("Bambu Lab文件列表需要通过FTP获取，暂未实现")
        return []
    
    async def upload_file(self, file_path: str, content: bytes) -> bool:
        """上传文件"""
        # Bambu Lab打印机文件上传需要通过FTP
        logger.warning("Bambu Lab文件上传需要通过FTP，暂未实现")
        return False


class OctoPrintDriver(PrinterDriver):
    """OctoPrint驱动 - 支持多种打印机"""
    
    def __init__(self):
        self._api_key = None
        self._base_url = None
        self._session = None
        self._connected = False
        self._state = PrinterState()
        
    async def connect(self, connection_params: Dict[str, Any]) -> bool:
        """连接OctoPrint"""
        try:
            import aiohttp
            
            self._base_url = connection_params.get("url", "http://localhost:5000")
            self._api_key = connection_params.get("api_key")
            
            if not self._api_key:
                logger.error("需要提供OctoPrint API Key")
                return False
            
            logger.info(f"正在连接OctoPrint: {self._base_url}")
            
            self._session = aiohttp.ClientSession(
                headers={"X-Api-Key": self._api_key}
            )
            
            # 测试连接
            async with self._session.get(f"{self._base_url}/api/version") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    logger.info(f"OctoPrint版本: {data.get('version')}")
                    self._connected = True
                    
                    # 启动状态更新
                    asyncio.create_task(self._update_state_loop())
                    
                    return True
                else:
                    logger.error(f"OctoPrint连接失败: {resp.status}")
                    return False
                    
        except ImportError:
            logger.error("aiohttp未安装，请运行: pip install aiohttp")
            return False
        except Exception as e:
            logger.error(f"OctoPrint连接失败: {e}")
            return False
    
    async def disconnect(self) -> bool:
        """断开连接"""
        self._connected = False
        if self._session:
            await self._session.close()
        return True
    
    async def _update_state_loop(self):
        """状态更新循环"""
        while self._connected:
            try:
                async with self._session.get(f"{self._base_url}/api/printer") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self._process_printer_data(data)
                    
                async with self._session.get(f"{self._base_url}/api/job") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self._process_job_data(data)
                        
            except Exception as e:
                logger.error(f"状态更新错误: {e}")
            
            await asyncio.sleep(2)
    
    def _process_printer_data(self, data: Dict[str, Any]):
        """处理打印机数据"""
        if "temperature" in data:
            temp = data["temperature"]
            if "tool0" in temp:
                self._state.temperatures.nozzle_current = temp["tool0"].get("actual", 0)
                self._state.temperatures.nozzle_target = temp["tool0"].get("target", 0)
            if "bed" in temp:
                self._state.temperatures.bed_current = temp["bed"].get("actual", 0)
                self._state.temperatures.bed_target = temp["bed"].get("target", 0)
        
        if "state" in data:
            state_text = data["state"].get("text", "Unknown")
            status_map = {
                "Operational": PrinterStatus.IDLE,
                "Printing": PrinterStatus.PRINTING,
                "Paused": PrinterStatus.PAUSED,
                "Finishing": PrinterStatus.PRINTING,
                "Error": PrinterStatus.ERROR,
            }
            self._state.status = status_map.get(state_text, PrinterStatus.IDLE)
        
        self._state.timestamp = time.time()
    
    def _process_job_data(self, data: Dict[str, Any]):
        """处理任务数据"""
        if "progress" in data:
            progress = data["progress"]
            self._state.progress.percent = progress.get("completion", 0)
            self._state.progress.print_time = progress.get("printTime", 0)
            self._state.progress.print_time_left = progress.get("printTimeLeft", 0)
        
        if "job" in data and "file" in data["job"]:
            self._state.progress.file_name = data["job"]["file"].get("name", "")
    
    async def get_state(self) -> PrinterState:
        """获取打印机状态"""
        return self._state
    
    async def start_print(self, file_path: str, **kwargs) -> bool:
        """开始打印"""
        try:
            async with self._session.post(
                f"{self._base_url}/api/job",
                json={"command": "start"}
            ) as resp:
                return resp.status == 204
        except Exception as e:
            logger.error(f"开始打印失败: {e}")
            return False
    
    async def pause_print(self) -> bool:
        """暂停打印"""
        try:
            async with self._session.post(
                f"{self._base_url}/api/job",
                json={"command": "pause", "action": "pause"}
            ) as resp:
                return resp.status == 204
        except Exception as e:
            logger.error(f"暂停打印失败: {e}")
            return False
    
    async def resume_print(self) -> bool:
        """恢复打印"""
        try:
            async with self._session.post(
                f"{self._base_url}/api/job",
                json={"command": "pause", "action": "resume"}
            ) as resp:
                return resp.status == 204
        except Exception as e:
            logger.error(f"恢复打印失败: {e}")
            return False
    
    async def stop_print(self) -> bool:
        """停止打印"""
        try:
            async with self._session.post(
                f"{self._base_url}/api/job",
                json={"command": "cancel"}
            ) as resp:
                return resp.status == 204
        except Exception as e:
            logger.error(f"停止打印失败: {e}")
            return False
    
    async def set_temperature(self, nozzle: float = None, bed: float = None) -> bool:
        """设置温度"""
        try:
            commands = []
            if nozzle is not None:
                commands.append({"command": "target", "targets": {"tool0": nozzle}})
            if bed is not None:
                commands.append({"command": "target", "targets": {"bed": bed}})
            
            for cmd in commands:
                async with self._session.post(
                    f"{self._base_url}/api/printer",
                    json=cmd
                ) as resp:
                    if resp.status != 204:
                        return False
            return True
        except Exception as e:
            logger.error(f"设置温度失败: {e}")
            return False
    
    async def move_axis(self, axis: str, distance: float, speed: int = None) -> bool:
        """移动轴"""
        try:
            gcode = f"G1 {axis}{distance}"
            if speed:
                gcode += f" F{speed}"
            return await self.send_gcode(gcode)
        except Exception as e:
            logger.error(f"移动轴失败: {e}")
            return False
    
    async def home_axis(self, axis: str = "all") -> bool:
        """归零轴"""
        try:
            if axis == "all":
                return await self.send_gcode("G28")
            else:
                return await self.send_gcode(f"G28 {axis}")
        except Exception as e:
            logger.error(f"归零轴失败: {e}")
            return False
    
    async def send_gcode(self, gcode: str) -> bool:
        """发送G-code"""
        try:
            async with self._session.post(
                f"{self._base_url}/api/printer/command",
                json={"command": gcode}
            ) as resp:
                return resp.status == 204
        except Exception as e:
            logger.error(f"发送G-code失败: {e}")
            return False
    
    async def get_files(self) -> List[Dict[str, Any]]:
        """获取文件列表"""
        try:
            async with self._session.get(f"{self._base_url}/api/files") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("files", [])
                return []
        except Exception as e:
            logger.error(f"获取文件列表失败: {e}")
            return []
    
    async def upload_file(self, file_path: str, content: bytes) -> bool:
        """上传文件"""
        try:
            import aiohttp
            data = aiohttp.FormData()
            data.add_field('file', content, filename=file_path)
            
            async with self._session.post(
                f"{self._base_url}/api/files/local",
                data=data
            ) as resp:
                return resp.status == 201
        except Exception as e:
            logger.error(f"上传文件失败: {e}")
            return False


class UniversalPrinterController:
    """通用3D打印机控制器"""
    
    def __init__(self, driver_type: str = "bambu"):
        self.driver_type = driver_type
        self.driver: PrinterDriver = None
        self._status_callbacks: List[Callable] = []
        self._error_callbacks: List[Callable] = []
        
        if driver_type == "bambu":
            self.driver = BambuLabDriver()
        elif driver_type == "octoprint":
            self.driver = OctoPrintDriver()
        else:
            raise ValueError(f"不支持的驱动类型: {driver_type}")
    
    async def connect(self, connection_params: Dict[str, Any]) -> Dict[str, Any]:
        """连接打印机"""
        success = await self.driver.connect(connection_params)
        
        if success:
            # 启动状态监控
            asyncio.create_task(self._monitoring_loop())
        
        return {
            "status": "success" if success else "error",
            "driver": self.driver_type
        }
    
    async def disconnect(self) -> Dict[str, Any]:
        """断开连接"""
        success = await self.driver.disconnect()
        return {
            "status": "success" if success else "error"
        }
    
    async def get_status(self) -> Dict[str, Any]:
        """获取打印机状态"""
        state = await self.driver.get_state()
        return state.to_dict()
    
    async def start_print(self, file_path: str, **kwargs) -> Dict[str, Any]:
        """开始打印"""
        success = await self.driver.start_print(file_path, **kwargs)
        return {
            "status": "success" if success else "error",
            "action": "start_print"
        }
    
    async def pause_print(self) -> Dict[str, Any]:
        """暂停打印"""
        success = await self.driver.pause_print()
        return {
            "status": "success" if success else "error",
            "action": "pause_print"
        }
    
    async def resume_print(self) -> Dict[str, Any]:
        """恢复打印"""
        success = await self.driver.resume_print()
        return {
            "status": "success" if success else "error",
            "action": "resume_print"
        }
    
    async def stop_print(self) -> Dict[str, Any]:
        """停止打印"""
        success = await self.driver.stop_print()
        return {
            "status": "success" if success else "error",
            "action": "stop_print"
        }
    
    async def set_temperature(self, nozzle: float = None, bed: float = None) -> Dict[str, Any]:
        """设置温度"""
        success = await self.driver.set_temperature(nozzle, bed)
        return {
            "status": "success" if success else "error",
            "action": "set_temperature",
            "nozzle": nozzle,
            "bed": bed
        }
    
    async def send_gcode(self, gcode: str) -> Dict[str, Any]:
        """发送G-code"""
        success = await self.driver.send_gcode(gcode)
        return {
            "status": "success" if success else "error",
            "action": "send_gcode",
            "gcode": gcode
        }
    
    async def _monitoring_loop(self):
        """监控循环"""
        while True:
            try:
                state = await self.driver.get_state()
                
                # 检查错误状态
                if state.status == PrinterStatus.ERROR:
                    for callback in self._error_callbacks:
                        callback({"error": "Printer error state"})
                
                # 通知状态更新
                for callback in self._status_callbacks:
                    try:
                        if asyncio.iscoroutinefunction(callback):
                            await callback(state.to_dict())
                        else:
                            callback(state.to_dict())
                    except Exception as e:
                        logger.error(f"状态回调错误: {e}")
                
                await asyncio.sleep(2)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"监控循环错误: {e}")
                await asyncio.sleep(5)
    
    def on_status_update(self, callback: Callable):
        """注册状态更新回调"""
        self._status_callbacks.append(callback)
    
    def on_error(self, callback: Callable):
        """注册错误回调"""
        self._error_callbacks.append(callback)


# 便捷函数
def create_bambu_controller() -> UniversalPrinterController:
    """创建Bambu Lab控制器"""
    return UniversalPrinterController("bambu")


def create_octoprint_controller() -> UniversalPrinterController:
    """创建OctoPrint控制器"""
    return UniversalPrinterController("octoprint")


if __name__ == "__main__":
    # 测试控制器
    logging.basicConfig(level=logging.INFO)
    
    async def test():
        # 这里需要真实的连接参数才能测试
        logger.info("3D打印机控制器已加载")
        logger.info("使用示例:")
        logger.info("  controller = create_bambu_controller()")
        logger.info("  await controller.connect({")
        logger.info("      'host': '192.168.1.100',")
        logger.info("      'access_code': 'your_access_code',")
        logger.info("      'serial': 'your_printer_serial'")
        logger.info("  })")
    
    asyncio.run(test())
