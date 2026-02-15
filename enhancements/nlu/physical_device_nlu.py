"""
Physical Device NLU Module for UFO Galaxy Realization.

This module provides natural language understanding for physical device control,
mapping user commands like "让无人机起飞" to specific node operations.

Supported Devices:
- Drone (Node_43_MAVLink): 起飞、降落、移动、拍照
- 3D Printer (Node_49_OctoPrint): 开始打印、暂停、设置温度
- Quantum Computer (Node_51_QuantumDispatcher): 提交量子任务
"""

import re
import json
import logging
from typing import Dict, List, Optional, Any, Callable, Tuple
from dataclasses import dataclass, field
from enum import Enum, auto
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CommandType(Enum):
    """Types of device commands"""
    # Drone commands
    DRONE_TAKEOFF = "drone_takeoff"
    DRONE_LAND = "drone_land"
    DRONE_MOVE = "drone_move"
    DRONE_CAPTURE = "drone_capture"
    DRONE_GET_STATUS = "drone_get_status"
    
    # 3D Printer commands
    PRINTER_START_PRINT = "printer_start_print"
    PRINTER_PAUSE = "printer_pause"
    PRINTER_RESUME = "printer_resume"
    PRINTER_CANCEL = "printer_cancel"
    PRINTER_SET_TEMP = "printer_set_temp"
    PRINTER_GET_STATUS = "printer_get_status"
    
    # Quantum commands
    QUANTUM_SUBMIT_JOB = "quantum_submit_job"
    QUANTUM_GET_RESULT = "quantum_get_result"
    
    # Generic
    UNKNOWN = "unknown"


class DeviceType(Enum):
    """Types of physical devices"""
    DRONE = "drone"
    PRINTER_3D = "printer_3d"
    QUANTUM = "quantum"
    UNKNOWN = "unknown"


@dataclass
class DeviceCommand:
    """Parsed device command"""
    command_type: CommandType
    device_type: DeviceType
    node_id: str
    action: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    raw_text: str = ""


@dataclass
class NLUResult:
    """NLU processing result"""
    success: bool
    command: Optional[DeviceCommand] = None
    error_message: Optional[str] = None
    alternatives: List[DeviceCommand] = field(default_factory=list)


class PhysicalDeviceNLU:
    """
    Natural Language Understanding for Physical Device Control
    
    Maps natural language commands to specific device node operations.
    
    Example:
        >>> nlu = PhysicalDeviceNLU()
        >>> result = nlu.parse("让无人机起飞到20米")
        >>> print(result.command.node_id)  # "Node_43_MAVLink"
        >>> print(result.command.action)   # "takeoff"
    """
    
    # Node mappings
    NODE_MAPPINGS = {
        DeviceType.DRONE: "Node_43_MAVLink",
        DeviceType.PRINTER_3D: "Node_49_OctoPrint",
        DeviceType.QUANTUM: "Node_51_QuantumDispatcher"
    }
    
    # Command patterns for Chinese
    COMMAND_PATTERNS = {
        # Drone patterns
        CommandType.DRONE_TAKEOFF: {
            "patterns": [
                r"无人机.*起飞",
                r"起飞.*无人机",
                r"让.*无人机.*飞",
                r"drone.*takeoff",
                r"takeoff.*drone"
            ],
            "action": "takeoff",
            "device": DeviceType.DRONE,
            "param_extractors": {
                "altitude": r"(\d+)\s*米"
            }
        },
        CommandType.DRONE_LAND: {
            "patterns": [
                r"无人机.*降落",
                r"降落.*无人机",
                r"让.*无人机.*降落",
                r"drone.*land",
                r"land.*drone"
            ],
            "action": "land",
            "device": DeviceType.DRONE
        },
        CommandType.DRONE_MOVE: {
            "patterns": [
                r"无人机.*(前进|后退|向左|向右|上升|下降)",
                r"让.*无人机.*(前进|后退|向左|向右|上升|下降)"
            ],
            "action": "move",
            "device": DeviceType.DRONE,
            "param_extractors": {
                "direction": r"(前进|后退|向左|向右|上升|下降)",
                "distance": r"(\d+)\s*米"
            }
        },
        CommandType.DRONE_CAPTURE: {
            "patterns": [
                r"无人机.*拍照",
                r"拍照.*无人机",
                r"drone.*capture",
                r"capture.*photo"
            ],
            "action": "capture",
            "device": DeviceType.DRONE
        },
        CommandType.DRONE_GET_STATUS: {
            "patterns": [
                r"无人机.*状态",
                r"查看.*无人机",
                r"drone.*status"
            ],
            "action": "get_status",
            "device": DeviceType.DRONE
        },
        
        # 3D Printer patterns
        CommandType.PRINTER_START_PRINT: {
            "patterns": [
                r"开始.*打印",
                r"打印.*开始",
                r"start.*print"
            ],
            "action": "start_print",
            "device": DeviceType.PRINTER_3D,
            "param_extractors": {
                "file": r"文件\s*[:：]?\s*(\S+)"
            }
        },
        CommandType.PRINTER_PAUSE: {
            "patterns": [
                r"暂停.*打印",
                r"打印.*暂停",
                r"pause.*print"
            ],
            "action": "pause",
            "device": DeviceType.PRINTER_3D
        },
        CommandType.PRINTER_RESUME: {
            "patterns": [
                r"恢复.*打印",
                r"继续.*打印",
                r"resume.*print"
            ],
            "action": "resume",
            "device": DeviceType.PRINTER_3D
        },
        CommandType.PRINTER_CANCEL: {
            "patterns": [
                r"取消.*打印",
                r"停止.*打印",
                r"cancel.*print"
            ],
            "action": "cancel",
            "device": DeviceType.PRINTER_3D
        },
        CommandType.PRINTER_SET_TEMP: {
            "patterns": [
                r"设置.*温度",
                r"温度.*设置",
                r"set.*temperature"
            ],
            "action": "set_temperature",
            "device": DeviceType.PRINTER_3D,
            "param_extractors": {
                "temperature": r"(\d+)\s*度",
                "component": r"(喷头|热床|nozzle|bed)"
            }
        },
        CommandType.PRINTER_GET_STATUS: {
            "patterns": [
                r"打印.*状态",
                r"查看.*打印",
                r"printer.*status"
            ],
            "action": "get_status",
            "device": DeviceType.PRINTER_3D
        }
    }
    
    def __init__(self):
        """Initialize the Physical Device NLU"""
        self._command_handlers: Dict[CommandType, Callable] = {}
        self._confidence_threshold = 0.6
        logger.info("PhysicalDeviceNLU initialized")
    
    def parse(self, text: str) -> NLUResult:
        """
        Parse natural language command
        
        Args:
            text: Natural language command
            
        Returns:
            NLUResult with parsed command
        """
        text = text.lower().strip()
        
        # Try to match command patterns
        best_match = None
        best_confidence = 0.0
        
        for cmd_type, config in self.COMMAND_PATTERNS.items():
            for pattern in config["patterns"]:
                if re.search(pattern, text, re.IGNORECASE):
                    confidence = self._calculate_confidence(text, pattern)
                    if confidence > best_confidence:
                        best_confidence = confidence
                        best_match = (cmd_type, config)
        
        if best_match and best_confidence >= self._confidence_threshold:
            cmd_type, config = best_match
            
            # Extract parameters
            parameters = self._extract_parameters(text, config.get("param_extractors", {}))
            
            # Create command
            command = DeviceCommand(
                command_type=cmd_type,
                device_type=config["device"],
                node_id=self.NODE_MAPPINGS.get(config["device"], "unknown"),
                action=config["action"],
                parameters=parameters,
                confidence=best_confidence,
                raw_text=text
            )
            
            logger.info(f"Parsed command: {cmd_type.value} -> {command.node_id}.{command.action}")
            
            return NLUResult(success=True, command=command)
        
        return NLUResult(
            success=False,
            error_message=f"Could not understand command: '{text}'"
        )
    
    def _calculate_confidence(self, text: str, pattern: str) -> float:
        """Calculate match confidence"""
        # Simple confidence based on pattern match length
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            match_length = match.end() - match.start()
            return min(0.6 + (match_length / len(text)) * 0.4, 1.0)
        return 0.0
    
    def _extract_parameters(self, text: str, extractors: Dict[str, str]) -> Dict[str, Any]:
        """Extract parameters from text"""
        parameters = {}
        
        for param_name, pattern in extractors.items():
            match = re.search(pattern, text)
            if match:
                value = match.group(1)
                # Try to convert to number
                try:
                    value = float(value) if "." in value else int(value)
                except ValueError:
                    pass
                parameters[param_name] = value
        
        return parameters
    
    def register_handler(self, command_type: CommandType, handler: Callable) -> None:
        """Register a command handler"""
        self._command_handlers[command_type] = handler
        logger.debug(f"Registered handler for {command_type.value}")
    
    async def execute(self, text: str) -> Dict[str, Any]:
        """
        Parse and execute a natural language command
        
        Args:
            text: Natural language command
            
        Returns:
            Execution result
        """
        result = self.parse(text)
        
        if not result.success:
            return {
                "status": "error",
                "message": result.error_message
            }
        
        command = result.command
        handler = self._command_handlers.get(command.command_type)
        
        if handler:
            try:
                if asyncio.iscoroutinefunction(handler):
                    return await handler(command)
                else:
                    return handler(command)
            except Exception as e:
                logger.error(f"Command execution error: {e}")
                return {
                    "status": "error",
                    "message": str(e)
                }
        
        return {
            "status": "parsed",
            "command": {
                "node_id": command.node_id,
                "action": command.action,
                "parameters": command.parameters
            }
        }
    
    def get_supported_commands(self) -> List[Dict[str, str]]:
        """Get list of supported commands"""
        commands = []
        for cmd_type, config in self.COMMAND_PATTERNS.items():
            commands.append({
                "type": cmd_type.value,
                "device": config["device"].value,
                "action": config["action"],
                "examples": config["patterns"][:2]
            })
        return commands


# Import for async support
import asyncio


# Convenience function
def parse_device_command(text: str) -> NLUResult:
    """Quick function to parse a device command"""
    nlu = PhysicalDeviceNLU()
    return nlu.parse(text)


if __name__ == "__main__":
    # Test the NLU
    nlu = PhysicalDeviceNLU()
    
    test_commands = [
        "让无人机起飞到20米",
        "无人机降落",
        "开始打印文件test.gcode",
        "设置喷头温度200度"
    ]
    
    for cmd in test_commands:
        result = nlu.parse(cmd)
        if result.success:
            print(f"✓ '{cmd}' -> {result.command.node_id}.{result.command.action}")
        else:
            print(f"✗ '{cmd}' -> {result.error_message}")
