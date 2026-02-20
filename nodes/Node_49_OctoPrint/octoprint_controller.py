"""
OctoPrint 3D 打印机控制器
支持真实的 OctoPrint API 通信和模拟模式
"""

import asyncio
import logging
import time
import httpx
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class PrinterStatus(Enum):
    """打印机状态"""
    DISCONNECTED = "disconnected"
    OPERATIONAL = "operational"
    PRINTING = "printing"
    PAUSED = "paused"
    ERROR = "error"
    OFFLINE = "offline"


@dataclass
class PrinterState:
    """打印机状态"""
    connected: bool = False
    status: PrinterStatus = PrinterStatus.DISCONNECTED
    bed_temp_actual: float = 25.0
    bed_temp_target: float = 0.0
    nozzle_temp_actual: float = 25.0
    nozzle_temp_target: float = 0.0
    print_progress: float = 0.0  # 0-100
    print_time_elapsed: float = 0.0  # 秒
    print_time_remaining: float = 0.0  # 秒
    current_file: Optional[str] = None
    last_update: float = 0.0
    metadata: Dict = field(default_factory=dict)


class OctoPrintController:
    """OctoPrint 3D 打印机控制器"""
    
    def __init__(self, api_url: Optional[str] = None, api_key: Optional[str] = None, simulation_mode: bool = True):
        """
        初始化 OctoPrint 控制器
        
        Args:
            api_url: OctoPrint API URL（如 "http://192.168.1.100:5000"）
            api_key: OctoPrint API Key
            simulation_mode: 是否使用模拟模式（True 时不需要真实硬件）
        """
        self.api_url = (api_url or "http://localhost:5000").rstrip("/")
        self.api_key = api_key or ""
        self.simulation_mode = simulation_mode
        self.state = PrinterState()
        self.http_client = None
        
        if not simulation_mode and api_key:
            self.http_client = httpx.AsyncClient(
                timeout=30.0,
                headers={
                    "X-Api-Key": api_key,
                    "Content-Type": "application/json"
                }
            )
        
        logger.info(f"OctoPrintController 初始化 (模拟模式: {simulation_mode})")
    
    async def connect(self, connection_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        连接打印机
        
        Args:
            connection_params: 连接参数
        
        Returns:
            连接结果
        """
        logger.info(f"连接打印机: {self.api_url}")
        
        try:
            if self.simulation_mode:
                # 模拟模式
                await asyncio.sleep(0.5)
                self.state.connected = True
                self.state.status = PrinterStatus.OPERATIONAL
                self.state.last_update = time.time()
                
                return {
                    "success": True,
                    "status": "connected",
                    "message": "打印机已连接（模拟模式）",
                    "api_version": "1.8.0",
                    "simulation": True
                }
            else:
                # 真实模式 - 调用 OctoPrint API
                if not self.http_client:
                    return {
                        "success": False,
                        "status": "error",
                        "message": "HTTP 客户端未初始化"
                    }
                
                # 获取打印机状态
                response = await self.http_client.get(f"{self.api_url}/api/printer")
                
                if response.status_code == 200:
                    data = response.json()
                    self.state.connected = True
                    self.state.status = PrinterStatus.OPERATIONAL
                    self.state.last_update = time.time()
                    
                    # 更新温度
                    if "temperature" in data:
                        temp_data = data["temperature"]
                        if "bed" in temp_data:
                            self.state.bed_temp_actual = temp_data["bed"].get("actual", 25.0)
                            self.state.bed_temp_target = temp_data["bed"].get("target", 0.0)
                        if "tool0" in temp_data:
                            self.state.nozzle_temp_actual = temp_data["tool0"].get("actual", 25.0)
                            self.state.nozzle_temp_target = temp_data["tool0"].get("target", 0.0)
                    
                    return {
                        "success": True,
                        "status": "connected",
                        "message": "打印机已连接（真实模式）",
                        "api_version": data.get("version", "unknown"),
                        "simulation": False
                    }
                else:
                    return {
                        "success": False,
                        "status": "error",
                        "message": f"连接失败: HTTP {response.status_code}"
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
        logger.info("断开打印机连接")
        
        if self.http_client:
            await self.http_client.aclose()
            self.http_client = None
        
        self.state.connected = False
        self.state.status = PrinterStatus.DISCONNECTED
        
        return {
            "success": True,
            "status": "disconnected",
            "message": "打印机已断开连接"
        }
    
    async def start_print(self, file_path: str) -> Dict[str, Any]:
        """
        开始打印
        
        Args:
            file_path: 打印文件路径（在 OctoPrint 中的路径）
        
        Returns:
            执行结果
        """
        if not self.state.connected:
            return {"success": False, "message": "打印机未连接"}
        
        logger.info(f"开始打印: {file_path}")
        
        if self.simulation_mode:
            # 模拟打印
            self.state.status = PrinterStatus.PRINTING
            self.state.current_file = file_path
            self.state.print_progress = 0.0
            self.state.print_time_elapsed = 0.0
            self.state.print_time_remaining = 3600.0  # 假设 1 小时
            self.state.nozzle_temp_target = 200.0
            self.state.bed_temp_target = 60.0
            
            # 模拟加热
            await self._simulate_heating()
            
            return {
                "success": True,
                "status": "printing",
                "message": f"开始打印: {file_path}",
                "file": file_path,
                "estimated_time": 3600.0
            }
        else:
            # 真实模式 - 调用 OctoPrint API
            if not self.http_client:
                return {"success": False, "message": "HTTP 客户端未初始化"}
            
            try:
                # 选择文件
                response = await self.http_client.post(
                    f"{self.api_url}/api/files/local/{file_path}",
                    json={"command": "select", "print": True}
                )
                
                if response.status_code == 204:
                    self.state.status = PrinterStatus.PRINTING
                    self.state.current_file = file_path
                    
                    return {
                        "success": True,
                        "status": "printing",
                        "message": f"开始打印: {file_path}",
                        "file": file_path
                    }
                else:
                    return {
                        "success": False,
                        "status": "error",
                        "message": f"打印失败: HTTP {response.status_code}"
                    }
            
            except Exception as e:
                logger.error(f"打印失败: {e}")
                return {
                    "success": False,
                    "status": "error",
                    "message": f"打印失败: {str(e)}"
                }
    
    async def pause_print(self) -> Dict[str, Any]:
        """暂停打印"""
        if self.state.status != PrinterStatus.PRINTING:
            return {"success": False, "message": "打印机未在打印中"}
        
        logger.info("暂停打印")
        
        if self.simulation_mode:
            self.state.status = PrinterStatus.PAUSED
        else:
            if self.http_client:
                await self.http_client.post(
                    f"{self.api_url}/api/job",
                    json={"command": "pause", "action": "pause"}
                )
                self.state.status = PrinterStatus.PAUSED
        
        return {
            "success": True,
            "status": "paused",
            "message": "打印已暂停"
        }
    
    async def resume_print(self) -> Dict[str, Any]:
        """恢复打印"""
        if self.state.status != PrinterStatus.PAUSED:
            return {"success": False, "message": "打印机未在暂停状态"}
        
        logger.info("恢复打印")
        
        if self.simulation_mode:
            self.state.status = PrinterStatus.PRINTING
        else:
            if self.http_client:
                await self.http_client.post(
                    f"{self.api_url}/api/job",
                    json={"command": "pause", "action": "resume"}
                )
                self.state.status = PrinterStatus.PRINTING
        
        return {
            "success": True,
            "status": "printing",
            "message": "打印已恢复"
        }
    
    async def cancel_print(self) -> Dict[str, Any]:
        """取消打印"""
        if self.state.status not in [PrinterStatus.PRINTING, PrinterStatus.PAUSED]:
            return {"success": False, "message": "没有正在进行的打印任务"}
        
        logger.info("取消打印")
        
        if self.simulation_mode:
            self.state.status = PrinterStatus.OPERATIONAL
            self.state.current_file = None
            self.state.print_progress = 0.0
            self.state.nozzle_temp_target = 0.0
            self.state.bed_temp_target = 0.0
        else:
            if self.http_client:
                await self.http_client.post(
                    f"{self.api_url}/api/job",
                    json={"command": "cancel"}
                )
                self.state.status = PrinterStatus.OPERATIONAL
                self.state.current_file = None
        
        return {
            "success": True,
            "status": "cancelled",
            "message": "打印已取消"
        }
    
    async def set_temperature(self, bed_temp: Optional[float] = None, nozzle_temp: Optional[float] = None) -> Dict[str, Any]:
        """
        设置温度
        
        Args:
            bed_temp: 热床温度（摄氏度）
            nozzle_temp: 喷嘴温度（摄氏度）
        
        Returns:
            执行结果
        """
        if not self.state.connected:
            return {"success": False, "message": "打印机未连接"}
        
        logger.info(f"设置温度: 热床={bed_temp}, 喷嘴={nozzle_temp}")
        
        if self.simulation_mode:
            if bed_temp is not None:
                self.state.bed_temp_target = bed_temp
            if nozzle_temp is not None:
                self.state.nozzle_temp_target = nozzle_temp
            
            # 模拟加热
            await self._simulate_heating()
        else:
            if self.http_client:
                payload = {}
                if bed_temp is not None:
                    payload["bed"] = {"target": bed_temp}
                if nozzle_temp is not None:
                    payload["tool0"] = {"target": nozzle_temp}
                
                await self.http_client.post(
                    f"{self.api_url}/api/printer/bed",
                    json=payload
                )
        
        return {
            "success": True,
            "status": "temperature_set",
            "message": "温度已设置",
            "bed_target": self.state.bed_temp_target,
            "nozzle_target": self.state.nozzle_temp_target
        }
    
    async def _simulate_heating(self):
        """模拟加热过程"""
        # 模拟热床加热
        while self.state.bed_temp_actual < self.state.bed_temp_target:
            self.state.bed_temp_actual = min(
                self.state.bed_temp_target,
                self.state.bed_temp_actual + 5
            )
            await asyncio.sleep(0.1)
        
        # 模拟喷嘴加热
        while self.state.nozzle_temp_actual < self.state.nozzle_temp_target:
            self.state.nozzle_temp_actual = min(
                self.state.nozzle_temp_target,
                self.state.nozzle_temp_actual + 10
            )
            await asyncio.sleep(0.1)
    
    async def home_axes(self, axes: Optional[str] = None) -> Dict[str, Any]:
        """
        归零轴
        
        Args:
            axes: 要归零的轴（"x", "y", "z", "xy", "xyz" 等），None 表示全部
        
        Returns:
            执行结果
        """
        if not self.state.connected:
            return {"success": False, "message": "打印机未连接"}
        
        axes = axes or "xyz"
        logger.info(f"归零轴: {axes}")
        
        if self.simulation_mode:
            await asyncio.sleep(1)
        else:
            if self.http_client:
                await self.http_client.post(
                    f"{self.api_url}/api/printer/printhead",
                    json={"command": "home", "axes": list(axes)}
                )
        
        return {
            "success": True,
            "status": "homed",
            "message": f"轴已归零: {axes}"
        }
    
    def get_state(self) -> Dict[str, Any]:
        """获取当前状态"""
        return {
            "connected": self.state.connected,
            "status": self.state.status.value,
            "temperature": {
                "bed": {
                    "actual": self.state.bed_temp_actual,
                    "target": self.state.bed_temp_target
                },
                "nozzle": {
                    "actual": self.state.nozzle_temp_actual,
                    "target": self.state.nozzle_temp_target
                }
            },
            "print": {
                "progress": self.state.print_progress,
                "time_elapsed": self.state.print_time_elapsed,
                "time_remaining": self.state.print_time_remaining,
                "current_file": self.state.current_file
            },
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
        elif command == "start_print":
            file_path = parameters.get("file_path", "test.gcode")
            return await self.start_print(file_path)
        elif command == "pause_print":
            return await self.pause_print()
        elif command == "resume_print":
            return await self.resume_print()
        elif command == "cancel_print":
            return await self.cancel_print()
        elif command == "set_temperature":
            bed_temp = parameters.get("bed_temp")
            nozzle_temp = parameters.get("nozzle_temp")
            return await self.set_temperature(bed_temp, nozzle_temp)
        elif command == "home_axes":
            axes = parameters.get("axes")
            return await self.home_axes(axes)
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
        if "打印" in description or "print" in description_lower:
            file_path = parameters.get("file_path", "test_model.gcode")
            return await self.start_print(file_path)
        
        elif "暂停" in description or "pause" in description_lower:
            return await self.pause_print()
        
        elif "恢复" in description or "resume" in description_lower:
            return await self.resume_print()
        
        elif "取消" in description or "cancel" in description_lower:
            return await self.cancel_print()
        
        elif "温度" in description or "temperature" in description_lower:
            bed_temp = parameters.get("bed_temp", 60.0)
            nozzle_temp = parameters.get("nozzle_temp", 200.0)
            return await self.set_temperature(bed_temp, nozzle_temp)
        
        else:
            # 通用执行
            logger.info(f"执行打印任务: {description}")
            
            # 默认流程：连接 → 设置温度 → 开始打印
            if not self.state.connected:
                await self.connect()
            
            result_steps = []
            
            # 设置温度
            result = await self.set_temperature(bed_temp=60.0, nozzle_temp=200.0)
            result_steps.append({"step": "set_temperature", "result": result})
            
            # 开始打印
            file_path = parameters.get("file_path", "support_bracket.gcode")
            result = await self.start_print(file_path)
            result_steps.append({"step": "start_print", "result": result})
            
            return {
                "success": True,
                "status": "completed",
                "message": f"打印任务完成: {description}",
                "steps": result_steps
            }
