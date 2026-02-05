"""
Hardware Module for UFO Galaxy

Hardware-level monitoring and control for 24/7 operation:
- Temperature monitoring
- Power management
- Hardware watchdog
- UPS monitoring
- Hardware triggers and UI state machine integration
"""

from .hardware_monitor import (
    HardwareMonitor,
    TemperatureReading,
    PowerStatus,
    HardwareMetrics,
    HardwareState,
    start_hardware_monitor
)

from .hardwaretrigger import (
    HardwareTrigger,
    UIStateMachine,
    UIController,
    SystemState,
    TriggerType,
    create_hardware_trigger,
    start_hardware_trigger_system
)

__all__ = [
    "HardwareMonitor",
    "TemperatureReading",
    "PowerStatus",
    "HardwareMetrics",
    "HardwareState",
    "start_hardware_monitor",
    "HardwareTrigger",
    "UIStateMachine",
    "UIController",
    "SystemState",
    "TriggerType",
    "create_hardware_trigger",
    "start_hardware_trigger_system"
]
