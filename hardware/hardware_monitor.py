"""
Hardware Monitor Module for UFO Galaxy

Provides hardware-level monitoring and control for 24/7 operation:
- Temperature monitoring
- Fan control
- Power management
- Hardware watchdog
- UPS/battery monitoring
"""

import os
import sys
import time
import logging
import subprocess
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
import threading

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class HardwareState(Enum):
    """Hardware operational states"""
    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"
    UNKNOWN = "unknown"


@dataclass
class TemperatureReading:
    """Temperature sensor reading"""
    sensor_name: str
    temperature_c: float
    threshold_warning: float = 70.0
    threshold_critical: float = 85.0
    timestamp: datetime = field(default_factory=datetime.now)
    
    def get_state(self) -> HardwareState:
        """Get temperature state"""
        if self.temperature_c >= self.threshold_critical:
            return HardwareState.CRITICAL
        elif self.temperature_c >= self.threshold_warning:
            return HardwareState.WARNING
        return HardwareState.NORMAL


@dataclass
class PowerStatus:
    """Power supply status"""
    is_on_battery: bool = False
    battery_percent: Optional[float] = None
    battery_time_remaining: Optional[int] = None  # minutes
    input_voltage: Optional[float] = None
    load_percent: Optional[float] = None
    timestamp: datetime = field(default_factory=datetime.now)
    
    def is_healthy(self) -> bool:
        """Check if power status is healthy"""
        if self.is_on_battery:
            if self.battery_percent is not None and self.battery_percent < 20:
                return False
            if self.battery_time_remaining is not None and self.battery_time_remaining < 10:
                return False
        return True


@dataclass
class HardwareMetrics:
    """Complete hardware metrics"""
    timestamp: datetime = field(default_factory=datetime.now)
    temperatures: List[TemperatureReading] = field(default_factory=list)
    power: Optional[PowerStatus] = None
    fan_speeds: Dict[str, int] = field(default_factory=dict)  # RPM
    voltages: Dict[str, float] = field(default_factory=dict)
    
    def get_overall_state(self) -> HardwareState:
        """Get overall hardware state"""
        worst_state = HardwareState.NORMAL
        
        for temp in self.temperatures:
            state = temp.get_state()
            if state.value == "critical":
                return HardwareState.CRITICAL
            elif state.value == "warning" and worst_state.value == "normal":
                worst_state = HardwareState.WARNING
        
        if self.power and not self.power.is_healthy():
            return HardwareState.WARNING
        
        return worst_state


class HardwareMonitor:
    """
    Hardware Monitor for 24/7 Operation
    
    Monitors system hardware and takes action when needed:
    - Temperature monitoring with automatic fan control
    - UPS/Battery monitoring
    - Hardware watchdog for automatic recovery
    
    Example:
        >>> monitor = HardwareMonitor()
        >>> monitor.start_monitoring()
        >>> # Runs continuously
        >>> monitor.stop_monitoring()
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize hardware monitor
        
        Args:
            config: Hardware monitoring configuration
        """
        self.config = config or {}
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._watchdog_thread: Optional[threading.Thread] = None
        
        # Metrics history
        self.metrics_history: List[HardwareMetrics] = []
        self.max_history = 1000
        
        # Callbacks
        self._temperature_callbacks: List[callable] = []
        self._power_callbacks: List[callable] = []
        
        # Hardware watchdog
        self._watchdog_enabled = self.config.get('watchdog_enabled', True)
        self._watchdog_timeout = self.config.get('watchdog_timeout', 60)
        self._last_pet = time.time()
        
        logger.info("HardwareMonitor initialized")
    
    def start_monitoring(self, interval: int = 30):
        """
        Start hardware monitoring
        
        Args:
            interval: Monitoring interval in seconds
        """
        if self._running:
            return
        
        self._running = True
        
        # Start monitoring thread
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            args=(interval,),
            daemon=True
        )
        self._monitor_thread.start()
        
        # Start watchdog thread
        if self._watchdog_enabled:
            self._watchdog_thread = threading.Thread(
                target=self._watchdog_loop,
                daemon=True
            )
            self._watchdog_thread.start()
        
        logger.info(f"Hardware monitoring started (interval: {interval}s)")
    
    def stop_monitoring(self):
        """Stop hardware monitoring"""
        self._running = False
        
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
        
        if self._watchdog_thread:
            self._watchdog_thread.join(timeout=5)
        
        logger.info("Hardware monitoring stopped")
    
    def _monitor_loop(self, interval: int):
        """Main monitoring loop"""
        while self._running:
            try:
                # Collect metrics
                metrics = self._collect_metrics()
                
                # Store metrics
                self.metrics_history.append(metrics)
                if len(self.metrics_history) > self.max_history:
                    self.metrics_history = self.metrics_history[-self.max_history:]
                
                # Check thresholds and take action
                self._check_thresholds(metrics)
                
                # Pet the watchdog
                self.pet_watchdog()
                
            except Exception as e:
                logger.error(f"Monitor loop error: {e}")
            
            # Wait for next interval
            for _ in range(interval):
                if not self._running:
                    break
                time.sleep(1)
    
    def _collect_metrics(self) -> HardwareMetrics:
        """Collect hardware metrics"""
        metrics = HardwareMetrics()
        
        # Collect temperatures
        metrics.temperatures = self._get_temperatures()
        
        # Collect power status
        metrics.power = self._get_power_status()
        
        # Collect fan speeds
        metrics.fan_speeds = self._get_fan_speeds()
        
        # Collect voltages
        metrics.voltages = self._get_voltages()
        
        return metrics
    
    def _get_temperatures(self) -> List[TemperatureReading]:
        """Get temperature readings from all sensors"""
        temperatures = []
        
        try:
            # Try to read from thermal zones (Linux)
            thermal_path = "/sys/class/thermal"
            if os.path.exists(thermal_path):
                for zone in os.listdir(thermal_path):
                    if zone.startswith("thermal_zone"):
                        try:
                            # Read temperature
                            temp_file = os.path.join(thermal_path, zone, "temp")
                            if os.path.exists(temp_file):
                                with open(temp_file, 'r') as f:
                                    temp_millidegrees = int(f.read().strip())
                                    temp_c = temp_millidegrees / 1000.0
                                
                                # Read type
                                type_file = os.path.join(thermal_path, zone, "type")
                                sensor_name = zone
                                if os.path.exists(type_file):
                                    with open(type_file, 'r') as f:
                                        sensor_name = f.read().strip()
                                
                                temperatures.append(TemperatureReading(
                                    sensor_name=sensor_name,
                                    temperature_c=temp_c
                                ))
                        except Exception as e:
                            logger.debug(f"Error reading {zone}: {e}")
            
            # Try sensors command (lm-sensors)
            try:
                output = subprocess.check_output(
                    ["sensors", "-u"],
                    stderr=subprocess.DEVNULL,
                    text=True
                )
                # Parse sensors output
                # This is a simplified parser
                for line in output.split('\n'):
                    if 'temp' in line.lower() and 'input' in line.lower():
                        parts = line.split(':')
                        if len(parts) == 2:
                            try:
                                temp_c = float(parts[1].strip())
                                sensor_name = line.split('.')[0].strip()
                                temperatures.append(TemperatureReading(
                                    sensor_name=sensor_name,
                                    temperature_c=temp_c
                                ))
                            except ValueError:
                                pass
            except (subprocess.CalledProcessError, FileNotFoundError):
                pass
        
        except Exception as e:
            logger.error(f"Error collecting temperatures: {e}")
        
        return temperatures
    
    def _get_power_status(self) -> Optional[PowerStatus]:
        """Get power supply status"""
        power = PowerStatus()
        
        try:
            # Check if on battery (Linux)
            power_supply_path = "/sys/class/power_supply"
            if os.path.exists(power_supply_path):
                for supply in os.listdir(power_supply_path):
                    supply_path = os.path.join(power_supply_path, supply)
                    
                    # Read type
                    type_file = os.path.join(supply_path, "type")
                    if os.path.exists(type_file):
                        with open(type_file, 'r') as f:
                            supply_type = f.read().strip()
                        
                        if supply_type == "Battery":
                            # Read battery status
                            status_file = os.path.join(supply_path, "status")
                            if os.path.exists(status_file):
                                with open(status_file, 'r') as f:
                                    status = f.read().strip()
                                    power.is_on_battery = (status == "Discharging")
                            
                            # Read battery capacity
                            capacity_file = os.path.join(supply_path, "capacity")
                            if os.path.exists(capacity_file):
                                with open(capacity_file, 'r') as f:
                                    power.battery_percent = float(f.read().strip())
                            
                            # Read time remaining
                            time_file = os.path.join(supply_path, "time_to_empty")
                            if os.path.exists(time_file):
                                with open(time_file, 'r') as f:
                                    power.battery_time_remaining = int(f.read().strip()) // 60
        
        except Exception as e:
            logger.debug(f"Error reading power status: {e}")
        
        return power
    
    def _get_fan_speeds(self) -> Dict[str, int]:
        """Get fan speeds in RPM"""
        fan_speeds = {}
        
        try:
            # Try hwmon (Linux)
            hwmon_path = "/sys/class/hwmon"
            if os.path.exists(hwmon_path):
                for hwmon in os.listdir(hwmon_path):
                    hwmon_dir = os.path.join(hwmon_path, hwmon)
                    
                    # Read name
                    name_file = os.path.join(hwmon_dir, "name")
                    if os.path.exists(name_file):
                        with open(name_file, 'r') as f:
                            hwmon_name = f.read().strip()
                    else:
                        hwmon_name = hwmon
                    
                    # Find fan inputs
                    for entry in os.listdir(hwmon_dir):
                        if entry.startswith("fan") and entry.endswith("_input"):
                            fan_name = f"{hwmon_name}_{entry[:-6]}"
                            fan_file = os.path.join(hwmon_dir, entry)
                            
                            try:
                                with open(fan_file, 'r') as f:
                                    rpm = int(f.read().strip())
                                    fan_speeds[fan_name] = rpm
                            except (ValueError, IOError):
                                pass
        
        except Exception as e:
            logger.debug(f"Error reading fan speeds: {e}")
        
        return fan_speeds
    
    def _get_voltages(self) -> Dict[str, float]:
        """Get voltage readings"""
        voltages = {}
        
        try:
            # Try hwmon (Linux)
            hwmon_path = "/sys/class/hwmon"
            if os.path.exists(hwmon_path):
                for hwmon in os.listdir(hwmon_path):
                    hwmon_dir = os.path.join(hwmon_path, hwmon)
                    
                    # Read name
                    name_file = os.path.join(hwmon_dir, "name")
                    if os.path.exists(name_file):
                        with open(name_file, 'r') as f:
                            hwmon_name = f.read().strip()
                    else:
                        hwmon_name = hwmon
                    
                    # Find voltage inputs
                    for entry in os.listdir(hwmon_dir):
                        if entry.startswith("in") and entry.endswith("_input"):
                            voltage_name = f"{hwmon_name}_{entry[:-6]}"
                            voltage_file = os.path.join(hwmon_dir, entry)
                            
                            try:
                                with open(voltage_file, 'r') as f:
                                    millivolts = int(f.read().strip())
                                    volts = millivolts / 1000.0
                                    voltages[voltage_name] = volts
                            except (ValueError, IOError):
                                pass
        
        except Exception as e:
            logger.debug(f"Error reading voltages: {e}")
        
        return voltages
    
    def _check_thresholds(self, metrics: HardwareMetrics):
        """Check metrics against thresholds and take action"""
        overall_state = metrics.get_overall_state()
        
        if overall_state == HardwareState.CRITICAL:
            logger.error("CRITICAL: Hardware in critical state!")
            self._handle_critical_state(metrics)
        elif overall_state == HardwareState.WARNING:
            logger.warning("WARNING: Hardware in warning state")
            self._handle_warning_state(metrics)
        
        # Notify callbacks
        for temp in metrics.temperatures:
            if temp.get_state() != HardwareState.NORMAL:
                for callback in self._temperature_callbacks:
                    try:
                        callback(temp)
                    except Exception as e:
                        logger.error(f"Temperature callback error: {e}")
        
        if metrics.power and not metrics.power.is_healthy():
            for callback in self._power_callbacks:
                try:
                    callback(metrics.power)
                except Exception as e:
                    logger.error(f"Power callback error: {e}")
    
    def _handle_critical_state(self, metrics: HardwareMetrics):
        """Handle critical hardware state"""
        # Increase fan speeds if possible
        self._increase_fan_speeds()
        
        # Could trigger emergency shutdown if needed
        # self._emergency_shutdown()
    
    def _handle_warning_state(self, metrics: HardwareMetrics):
        """Handle warning hardware state"""
        # Increase fan speeds
        self._increase_fan_speeds()
    
    def _increase_fan_speeds(self):
        """Attempt to increase fan speeds"""
        # This would require hardware-specific implementation
        # For now, just log the attempt
        logger.info("Attempting to increase fan speeds")
    
    def _emergency_shutdown(self):
        """Perform emergency shutdown"""
        logger.critical("EMERGENCY SHUTDOWN INITIATED")
        # Implement emergency shutdown procedure
        # This could save state, notify admins, etc.
    
    def _watchdog_loop(self):
        """Hardware watchdog loop"""
        while self._running:
            time.sleep(1)
            
            # Check if watchdog has been pet recently
            elapsed = time.time() - self._last_pet
            
            if elapsed > self._watchdog_timeout:
                logger.error(f"Watchdog timeout! No pet for {elapsed:.0f}s")
                self._handle_watchdog_timeout()
    
    def pet_watchdog(self):
        """Pet the hardware watchdog"""
        self._last_pet = time.time()
    
    def _handle_watchdog_timeout(self):
        """Handle watchdog timeout - system may be stuck"""
        logger.critical("Watchdog timeout detected - system may be unresponsive")
        
        # Could trigger automatic restart
        # This would need to be implemented based on specific requirements
    
    def register_temperature_callback(self, callback: callable):
        """Register callback for temperature alerts"""
        self._temperature_callbacks.append(callback)
    
    def register_power_callback(self, callback: callable):
        """Register callback for power alerts"""
        self._power_callbacks.append(callback)
    
    def get_current_metrics(self) -> Optional[HardwareMetrics]:
        """Get current hardware metrics"""
        if self.metrics_history:
            return self.metrics_history[-1]
        return None
    
    def get_metrics_history(self, count: int = 100) -> List[HardwareMetrics]:
        """Get metrics history"""
        return self.metrics_history[-count:]


# Convenience functions
def start_hardware_monitor(config: Optional[Dict[str, Any]] = None) -> HardwareMonitor:
    """Start hardware monitoring"""
    monitor = HardwareMonitor(config)
    monitor.start_monitoring()
    return monitor


if __name__ == "__main__":
    # Test hardware monitor
    monitor = HardwareMonitor()
    monitor.start_monitoring(interval=5)
    
    try:
        while True:
            time.sleep(10)
            metrics = monitor.get_current_metrics()
            if metrics:
                print(f"Hardware State: {metrics.get_overall_state().value}")
                for temp in metrics.temperatures:
                    print(f"  {temp.sensor_name}: {temp.temperature_c:.1f}°C")
    except KeyboardInterrupt:
        monitor.stop_monitoring()
