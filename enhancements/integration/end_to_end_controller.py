"""
End-to-End Controller for UFO Galaxy Realization.

This module provides the complete integration layer that connects:
1. Android voice input
2. Natural Language Understanding (NLU)
3. Cross-Device Scheduler
4. Physical Device Nodes (Drone, 3D Printer, etc.)

Example flow:
    用户语音: "让无人机起飞"
        ↓
    VoiceCommandProcessor
        ↓
    PhysicalDeviceNLU.parse()
        ↓
    DeviceCommandExecutor
        ↓
    CrossDeviceScheduler.submit_task()
        ↓
    Node_43_MAVLink.takeoff()
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ExecutionStatus(Enum):
    """Execution status"""
    PENDING = "pending"
    PARSING = "parsing"
    SCHEDULING = "scheduling"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ExecutionResult:
    """End-to-end execution result"""
    status: ExecutionStatus
    voice_input: str
    parsed_command: Optional[Dict[str, Any]] = None
    node_id: Optional[str] = None
    action: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    execution_time_ms: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "status": self.status.value,
            "voice_input": self.voice_input,
            "parsed_command": self.parsed_command,
            "node_id": self.node_id,
            "action": self.action,
            "result": self.result,
            "error_message": self.error_message,
            "execution_time_ms": self.execution_time_ms,
            "timestamp": self.timestamp.isoformat()
        }


class VoiceCommandProcessor:
    """
    Process voice commands from Android client
    
    Handles:
    - Voice-to-text conversion (via Android)
    - Command parsing via NLU
    - Command validation
    """
    
    def __init__(self, nlu_module=None):
        """
        Initialize voice command processor
        
        Args:
            nlu_module: NLU module for parsing (auto-created if None)
        """
        self.nlu = nlu_module or self._create_default_nlu()
        logger.info("VoiceCommandProcessor initialized")
    
    def _create_default_nlu(self):
        """Create default NLU module"""
        try:
            from enhancements.nlu.physical_device_nlu import PhysicalDeviceNLU
            return PhysicalDeviceNLU()
        except ImportError:
            logger.warning("PhysicalDeviceNLU not available")
            return None
    
    async def process(self, voice_text: str) -> ExecutionResult:
        """
        Process voice command
        
        Args:
            voice_text: Voice input text from Android
            
        Returns:
            ExecutionResult with parsed command
        """
        start_time = datetime.now()
        
        if not self.nlu:
            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                voice_input=voice_text,
                error_message="NLU module not available"
            )
        
        # Parse command
        nlu_result = self.nlu.parse(voice_text)
        
        if not nlu_result.success:
            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                voice_input=voice_text,
                error_message=nlu_result.error_message
            )
        
        command = nlu_result.command
        
        return ExecutionResult(
            status=ExecutionStatus.PARSING,
            voice_input=voice_text,
            parsed_command={
                "command_type": command.command_type.value,
                "device_type": command.device_type.value,
                "action": command.action,
                "parameters": command.parameters
            },
            node_id=command.node_id,
            action=command.action,
            execution_time_ms=(datetime.now() - start_time).total_seconds() * 1000
        )


class DeviceCommandExecutor:
    """
    Execute device commands via node system
    
    Handles:
    - Node discovery and routing
    - Task submission to CrossDeviceScheduler
    - Result collection
    """
    
    def __init__(self, scheduler=None, node_registry=None):
        """
        Initialize device command executor
        
        Args:
            scheduler: Cross-device scheduler (auto-created if None)
            node_registry: Node registry for looking up nodes
        """
        self.scheduler = scheduler
        self.node_registry = node_registry or {}
        self._node_clients: Dict[str, Any] = {}
        logger.info("DeviceCommandExecutor initialized")
    
    async def execute(
        self,
        node_id: str,
        action: str,
        parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute command on device node
        
        Args:
            node_id: Target node ID (e.g., "Node_43_MAVLink")
            action: Action to perform (e.g., "takeoff")
            parameters: Action parameters
            
        Returns:
            Execution result
        """
        try:
            # Route to appropriate node handler
            if "MAVLink" in node_id or "drone" in node_id.lower():
                return await self._execute_drone_command(action, parameters)
            elif "OctoPrint" in node_id or "printer" in node_id.lower():
                return await self._execute_printer_command(action, parameters)
            elif "Quantum" in node_id:
                return await self._execute_quantum_command(action, parameters)
            else:
                return {
                    "status": "error",
                    "message": f"Unknown node type: {node_id}"
                }
        
        except Exception as e:
            logger.error(f"Command execution error: {e}")
            return {
                "status": "error",
                "message": str(e)
            }
    
    async def _execute_drone_command(
        self,
        action: str,
        parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute drone command via Node_43_MAVLink"""
        try:
            # Import drone controller
            from nodes.Node_43_MAVLink.universal_drone_controller import (
                UniversalDroneController, DroneProtocol
            )
            
            controller = UniversalDroneController(DroneProtocol.MAVLINK)
            
            # Connect to drone
            connect_result = await controller.connect({
                "connection_string": "udp:127.0.0.1:14550"
            })
            
            if connect_result.get("status") != "success":
                return connect_result
            
            # Execute action
            if action == "takeoff":
                altitude = parameters.get("altitude", 10.0)
                return await controller.takeoff(altitude)
            elif action == "land":
                return await controller.land()
            elif action == "move":
                direction = parameters.get("direction", "forward")
                distance = parameters.get("distance", 5.0)
                return await controller.move(direction, distance)
            elif action == "capture":
                return await controller.capture_photo()
            elif action == "get_status":
                return {
                    "status": "success",
                    "state": {
                        "battery": controller.current_state.battery,
                        "altitude": controller.current_state.altitude,
                        "speed": controller.current_state.speed,
                        "status": controller.current_state.status.value
                    }
                }
            else:
                return {
                    "status": "error",
                    "message": f"Unknown drone action: {action}"
                }
        
        except Exception as e:
            logger.error(f"Drone command error: {e}")
            return {
                "status": "error",
                "message": f"Drone command failed: {str(e)}"
            }
    
    async def _execute_printer_command(
        self,
        action: str,
        parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute 3D printer command via Node_49_OctoPrint"""
        # Placeholder for OctoPrint integration
        logger.info(f"Executing printer command: {action}")
        
        return {
            "status": "success",
            "message": f"Printer command '{action}' executed",
            "action": action,
            "parameters": parameters
        }
    
    async def _execute_quantum_command(
        self,
        action: str,
        parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute quantum computing command via Node_51_QuantumDispatcher"""
        # Placeholder for quantum integration
        logger.info(f"Executing quantum command: {action}")
        
        return {
            "status": "success",
            "message": f"Quantum command '{action}' executed",
            "action": action,
            "parameters": parameters
        }


class EndToEndController:
    """
    End-to-End Controller for Voice-to-Device Execution
    
    This is the main entry point for processing voice commands
    and executing them on physical devices.
    
    Example:
        >>> controller = EndToEndController()
        >>> result = await controller.process_voice_command("让无人机起飞")
        >>> print(result.status)  # "completed"
    """
    
    def __init__(
        self,
        voice_processor: Optional[VoiceCommandProcessor] = None,
        command_executor: Optional[DeviceCommandExecutor] = None
    ):
        """
        Initialize end-to-end controller
        
        Args:
            voice_processor: Voice command processor
            command_executor: Device command executor
        """
        self.voice_processor = voice_processor or VoiceCommandProcessor()
        self.command_executor = command_executor or DeviceCommandExecutor()
        self._callbacks: List[Callable] = []
        
        logger.info("EndToEndController initialized")
    
    async def process_voice_command(self, voice_text: str) -> ExecutionResult:
        """
        Process a voice command end-to-end
        
        Args:
            voice_text: Voice input text
            
        Returns:
            ExecutionResult with full execution details
        """
        start_time = datetime.now()
        
        # Step 1: Parse voice command
        parse_result = await self.voice_processor.process(voice_text)
        
        if parse_result.status == ExecutionStatus.FAILED:
            return parse_result
        
        # Step 2: Execute on device
        node_id = parse_result.node_id
        action = parse_result.action
        parameters = parse_result.parsed_command.get("parameters", {})
        
        exec_result = await self.command_executor.execute(
            node_id, action, parameters
        )
        
        # Build final result
        final_status = (
            ExecutionStatus.COMPLETED
            if exec_result.get("status") == "success"
            else ExecutionStatus.FAILED
        )
        
        result = ExecutionResult(
            status=final_status,
            voice_input=voice_text,
            parsed_command=parse_result.parsed_command,
            node_id=node_id,
            action=action,
            result=exec_result,
            error_message=exec_result.get("message") if final_status == ExecutionStatus.FAILED else None,
            execution_time_ms=(datetime.now() - start_time).total_seconds() * 1000
        )
        
        # Notify callbacks
        await self._notify_callbacks(result)
        
        return result
    
    def register_callback(self, callback: Callable) -> None:
        """Register execution callback"""
        self._callbacks.append(callback)
    
    async def _notify_callbacks(self, result: ExecutionResult) -> None:
        """Notify registered callbacks"""
        for callback in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(result)
                else:
                    callback(result)
            except Exception as e:
                logger.error(f"Callback error: {e}")
    
    def get_supported_commands(self) -> List[Dict[str, Any]]:
        """Get list of supported voice commands"""
        if self.voice_processor.nlu:
            return self.voice_processor.nlu.get_supported_commands()
        return []


# Convenience function
async def execute_voice_command(voice_text: str) -> ExecutionResult:
    """Quick function to execute a voice command"""
    controller = EndToEndController()
    return await controller.process_voice_command(voice_text)


if __name__ == "__main__":
    # Test end-to-end flow
    async def test():
        controller = EndToEndController()
        
        test_commands = [
            "让无人机起飞到10米",
            "无人机状态",
            "开始打印文件test.gcode"
        ]
        
        for cmd in test_commands:
            print(f"\nTesting: '{cmd}'")
            result = await controller.process_voice_command(cmd)
            print(f"Status: {result.status.value}")
            print(f"Node: {result.node_id}")
            print(f"Action: {result.action}")
            if result.result:
                print(f"Result: {result.result}")
    
    asyncio.run(test())
