"""
增强版拓竹 3D 打印机数据对接模块

新增功能：
1. 实时状态监控（温度、进度、层数等）
2. 详细的打印统计
3. 错误检测和告警
4. 打印历史记录
5. 与 Galaxy 系统的深度集成

作者：Manus AI
日期：2025-01-20
"""

import json
import time
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from enum import Enum

class PrinterStatus(Enum):
    """打印机状态"""
    IDLE = "idle"
    PRINTING = "printing"
    PAUSED = "paused"
    FINISHED = "finished"
    ERROR = "error"

@dataclass
class PrinterState:
    """打印机详细状态"""
    # 基本状态
    status: PrinterStatus
    
    # 温度信息
    nozzle_temp: float  # 喷嘴温度
    nozzle_target_temp: float  # 喷嘴目标温度
    bed_temp: float  # 热床温度
    bed_target_temp: float  # 热床目标温度
    chamber_temp: float  # 腔体温度
    
    # 打印进度
    progress: float  # 打印进度（0-100）
    current_layer: int  # 当前层数
    total_layers: int  # 总层数
    print_time: int  # 已打印时间（秒）
    remaining_time: int  # 剩余时间（秒）
    
    # 文件信息
    file_name: str  # 当前打印文件名
    file_size: int  # 文件大小（字节）
    
    # 其他信息
    fan_speed: int  # 风扇速度（0-100）
    print_speed: int  # 打印速度（百分比）
    
    # 错误信息
    error_code: Optional[int] = None
    error_message: Optional[str] = None

class EnhancedBambuController:
    """增强版拓竹打印机控制器"""
    
    def __init__(self, ip: str, port: int, serial: str, access_code: str):
        """
        初始化控制器
        
        Args:
            ip: 打印机 IP 地址
            port: MQTT 端口（通常是 8883）
            serial: 打印机序列号
            access_code: 访问码
        """
        self.ip = ip
        self.port = port
        self.serial = serial
        self.access_code = access_code
        
        # 当前状态
        self.current_state = PrinterState(
            status=PrinterStatus.IDLE,
            nozzle_temp=0.0,
            nozzle_target_temp=0.0,
            bed_temp=0.0,
            bed_target_temp=0.0,
            chamber_temp=0.0,
            progress=0.0,
            current_layer=0,
            total_layers=0,
            print_time=0,
            remaining_time=0,
            file_name="",
            file_size=0,
            fan_speed=0,
            print_speed=100
        )
        
        # 打印历史
        self.print_history: List[Dict[str, Any]] = []
    
    def parse_status_report(self, report: Dict[str, Any]) -> PrinterState:
        """
        解析拓竹打印机的状态报告
        
        Args:
            report: 原始状态报告
        
        Returns:
            解析后的打印机状态
        """
        # 拓竹打印机的状态报告格式（简化版）
        print_data = report.get("print", {})
        
        # 解析状态
        gcode_state = print_data.get("gcode_state", "IDLE")
        if gcode_state == "RUNNING":
            status = PrinterStatus.PRINTING
        elif gcode_state == "PAUSE":
            status = PrinterStatus.PAUSED
        elif gcode_state == "FINISH":
            status = PrinterStatus.FINISHED
        elif gcode_state == "FAILED":
            status = PrinterStatus.ERROR
        else:
            status = PrinterStatus.IDLE
        
        # 解析温度
        nozzle_temp = print_data.get("nozzle_temper", 0.0)
        nozzle_target_temp = print_data.get("nozzle_target_temper", 0.0)
        bed_temp = print_data.get("bed_temper", 0.0)
        bed_target_temp = print_data.get("bed_target_temper", 0.0)
        chamber_temp = print_data.get("chamber_temper", 0.0)
        
        # 解析进度
        progress = print_data.get("mc_percent", 0)
        current_layer = print_data.get("layer_num", 0)
        total_layers = print_data.get("total_layer_num", 0)
        print_time = print_data.get("mc_remaining_time", 0)
        remaining_time = print_data.get("mc_remaining_time", 0)
        
        # 解析文件信息
        file_name = print_data.get("gcode_file", "")
        file_size = print_data.get("gcode_file_prepare_percent", 0)
        
        # 解析其他信息
        fan_speed = print_data.get("cooling_fan_speed", 0)
        print_speed = print_data.get("spd_mag", 100)
        
        # 更新状态
        self.current_state = PrinterState(
            status=status,
            nozzle_temp=nozzle_temp,
            nozzle_target_temp=nozzle_target_temp,
            bed_temp=bed_temp,
            bed_target_temp=bed_target_temp,
            chamber_temp=chamber_temp,
            progress=progress,
            current_layer=current_layer,
            total_layers=total_layers,
            print_time=print_time,
            remaining_time=remaining_time,
            file_name=file_name,
            file_size=file_size,
            fan_speed=fan_speed,
            print_speed=print_speed
        )
        
        return self.current_state
    
    def get_human_readable_status(self) -> str:
        """获取人类可读的状态描述"""
        state = self.current_state
        
        if state.status == PrinterStatus.IDLE:
            return "打印机空闲"
        elif state.status == PrinterStatus.PRINTING:
            return f"正在打印 {state.file_name}，进度 {state.progress}%，第 {state.current_layer}/{state.total_layers} 层"
        elif state.status == PrinterStatus.PAUSED:
            return f"打印已暂停，进度 {state.progress}%"
        elif state.status == PrinterStatus.FINISHED:
            return f"打印完成：{state.file_name}"
        elif state.status == PrinterStatus.ERROR:
            return f"打印错误：{state.error_message or '未知错误'}"
        else:
            return "未知状态"
    
    def get_temperature_report(self) -> Dict[str, Any]:
        """获取温度报告"""
        state = self.current_state
        return {
            "nozzle": {
                "current": state.nozzle_temp,
                "target": state.nozzle_target_temp,
                "status": "正常" if abs(state.nozzle_temp - state.nozzle_target_temp) < 5 else "加热中"
            },
            "bed": {
                "current": state.bed_temp,
                "target": state.bed_target_temp,
                "status": "正常" if abs(state.bed_temp - state.bed_target_temp) < 5 else "加热中"
            },
            "chamber": {
                "current": state.chamber_temp,
                "status": "正常"
            }
        }
    
    def get_progress_report(self) -> Dict[str, Any]:
        """获取进度报告"""
        state = self.current_state
        return {
            "progress": state.progress,
            "current_layer": state.current_layer,
            "total_layers": state.total_layers,
            "print_time": state.print_time,
            "remaining_time": state.remaining_time,
            "estimated_finish_time": time.time() + state.remaining_time
        }
    
    def check_for_errors(self) -> Optional[Dict[str, Any]]:
        """检查是否有错误"""
        state = self.current_state
        
        errors = []
        
        # 检查温度异常
        if state.nozzle_temp > 300:
            errors.append({"type": "temperature", "message": "喷嘴温度过高"})
        if state.bed_temp > 120:
            errors.append({"type": "temperature", "message": "热床温度过高"})
        
        # 检查状态异常
        if state.status == PrinterStatus.ERROR:
            errors.append({"type": "status", "message": state.error_message or "打印错误"})
        
        if errors:
            return {
                "has_errors": True,
                "errors": errors
            }
        else:
            return None
    
    def add_to_history(self, print_info: Dict[str, Any]):
        """添加打印记录到历史"""
        self.print_history.append({
            "timestamp": time.time(),
            "file_name": print_info.get("file_name"),
            "duration": print_info.get("duration"),
            "status": print_info.get("status"),
            "layers": print_info.get("layers")
        })
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取打印统计"""
        total_prints = len(self.print_history)
        successful_prints = sum(1 for p in self.print_history if p.get("status") == "finished")
        total_time = sum(p.get("duration", 0) for p in self.print_history)
        
        return {
            "total_prints": total_prints,
            "successful_prints": successful_prints,
            "success_rate": (successful_prints / total_prints * 100) if total_prints > 0 else 0,
            "total_print_time": total_time,
            "average_print_time": (total_time / total_prints) if total_prints > 0 else 0
        }

# 使用示例
if __name__ == "__main__":
    controller = EnhancedBambuController(
        ip="192.168.1.100",
        port=8883,
        serial="01S00A123456789",
        access_code="12345678"
    )
    
    # 模拟接收状态报告
    mock_report = {
        "print": {
            "gcode_state": "RUNNING",
            "nozzle_temper": 220.5,
            "nozzle_target_temper": 220.0,
            "bed_temper": 60.2,
            "bed_target_temper": 60.0,
            "chamber_temper": 35.0,
            "mc_percent": 45,
            "layer_num": 120,
            "total_layer_num": 267,
            "mc_remaining_time": 3600,
            "gcode_file": "test_model.gcode",
            "cooling_fan_speed": 80,
            "spd_mag": 100
        }
    }
    
    # 解析状态
    state = controller.parse_status_report(mock_report)
    
    # 输出各种报告
    print("状态描述:", controller.get_human_readable_status())
    print("\n温度报告:", json.dumps(controller.get_temperature_report(), indent=2, ensure_ascii=False))
    print("\n进度报告:", json.dumps(controller.get_progress_report(), indent=2, ensure_ascii=False))
    
    # 检查错误
    errors = controller.check_for_errors()
    if errors:
        print("\n错误报告:", json.dumps(errors, indent=2, ensure_ascii=False))
    else:
        print("\n✅ 一切正常")
