"""
UFO Galaxy v5.0 - Android Bridge Module
Android Device Integration System

This module provides Android device integration through ADB commands,
screen capture, device control, and app management.

Features:
- ADB command wrapper
- Screen capture and streaming
- Touch/Key input control
- App installation and management
- Device information retrieval
- Logcat monitoring
- File transfer

Author: UFO Galaxy Team
Version: 5.0.0
"""

import asyncio
import subprocess
import os
import re
import json
import logging
import tempfile
import base64
from typing import Dict, List, Optional, Tuple, Any, Union, Callable
from dataclasses import dataclass, field
from pathlib import Path
from enum import Enum
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ADBError(Exception):
    """ADB command error"""
    pass


class DeviceNotFoundError(ADBError):
    """Device not found error"""
    pass


class InstallError(ADBError):
    """App installation error"""
    pass


class ScreenCaptureError(ADBError):
    """Screen capture error"""
    pass


@dataclass
class AndroidDeviceInfo:
    """Android device information"""
    device_id: str
    model: str = "unknown"
    manufacturer: str = "unknown"
    android_version: str = "unknown"
    sdk_version: int = 0
    abi: str = "unknown"
    screen_resolution: Tuple[int, int] = (0, 0)
    screen_density: int = 0
    battery_level: int = 0
    is_charging: bool = False
    total_ram: int = 0
    available_ram: int = 0
    total_storage: int = 0
    available_storage: int = 0
    is_rooted: bool = False
    properties: Dict[str, str] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'device_id': self.device_id,
            'model': self.model,
            'manufacturer': self.manufacturer,
            'android_version': self.android_version,
            'sdk_version': self.sdk_version,
            'abi': self.abi,
            'screen_resolution': self.screen_resolution,
            'screen_density': self.screen_density,
            'battery_level': self.battery_level,
            'is_charging': self.is_charging,
            'total_ram': self.total_ram,
            'available_ram': self.available_ram,
            'total_storage': self.total_storage,
            'available_storage': self.available_storage,
            'is_rooted': self.is_rooted,
            'properties': self.properties
        }


@dataclass
class AppInfo:
    """Android app information"""
    package_name: str
    version_name: str = "unknown"
    version_code: int = 0
    is_system_app: bool = False
    is_enabled: bool = True
    first_install_time: Optional[float] = None
    last_update_time: Optional[float] = None
    permissions: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'package_name': self.package_name,
            'version_name': self.version_name,
            'version_code': self.version_code,
            'is_system_app': self.is_system_app,
            'is_enabled': self.is_enabled,
            'first_install_time': self.first_install_time,
            'last_update_time': self.last_update_time,
            'permissions': self.permissions
        }


@dataclass
class TouchEvent:
    """Touch event for input injection"""
    x: int
    y: int
    action: str = "down"  # down, up, move
    pointer_id: int = 0
    pressure: float = 1.0
    
    def to_adb_command(self) -> str:
        """Convert to ADB input command"""
        action_map = {
            'down': 0,
            'up': 1,
            'move': 2
        }
        action_code = action_map.get(self.action, 0)
        return f"input touchscreen tap {self.x} {self.y}"


@dataclass
class SwipeEvent:
    """Swipe event for input injection"""
    start_x: int
    start_y: int
    end_x: int
    end_y: int
    duration_ms: int = 300
    
    def to_adb_command(self) -> str:
        """Convert to ADB input command"""
        return f"input touchscreen swipe {self.start_x} {self.start_y} {self.end_x} {self.end_y} {self.duration_ms}"


@dataclass
class KeyEvent:
    """Key event for input injection"""
    keycode: int
    action: str = "down"  # down, up
    
    # Common keycodes
    KEYCODE_HOME = 3
    KEYCODE_BACK = 4
    KEYCODE_CALL = 5
    KEYCODE_ENDCALL = 6
    KEYCODE_VOLUME_UP = 24
    KEYCODE_VOLUME_DOWN = 25
    KEYCODE_POWER = 26
    KEYCODE_CAMERA = 27
    KEYCODE_MENU = 82
    KEYCODE_NOTIFICATION = 83
    KEYCODE_SEARCH = 84
    KEYCODE_APP_SWITCH = 187
    
    def to_adb_command(self) -> str:
        """Convert to ADB input command"""
        if self.action == 'longpress':
            return f"input keyevent --longpress {self.keycode}"
        return f"input keyevent {self.keycode}"


class ADBCommandExecutor:
    """Execute ADB commands"""
    
    def __init__(self, adb_path: str = "adb", default_timeout: float = 30.0):
        self.adb_path = adb_path
        self.default_timeout = default_timeout
        self._lock = asyncio.Lock()
    
    async def execute(
        self,
        command: List[str],
        device_id: Optional[str] = None,
        timeout: Optional[float] = None,
        check_error: bool = True
    ) -> Tuple[int, str, str]:
        """
        Execute ADB command
        
        Args:
            command: Command arguments
            device_id: Target device ID
            timeout: Command timeout
            check_error: Raise exception on error
            
        Returns:
            Tuple of (returncode, stdout, stderr)
        """
        cmd = [self.adb_path]
        
        if device_id:
            cmd.extend(["-s", device_id])
        
        cmd.extend(command)
        
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout or self.default_timeout
            )
            
            stdout_str = stdout.decode('utf-8', errors='ignore')
            stderr_str = stderr.decode('utf-8', errors='ignore')
            
            if check_error and proc.returncode != 0:
                error_msg = stderr_str or stdout_str
                if "device offline" in error_msg.lower():
                    raise DeviceNotFoundError(f"Device is offline: {device_id}")
                elif "device not found" in error_msg.lower():
                    raise DeviceNotFoundError(f"Device not found: {device_id}")
                raise ADBError(f"ADB command failed: {error_msg}")
            
            return proc.returncode, stdout_str, stderr_str
        
        except asyncio.TimeoutError:
            raise ADBError(f"ADB command timed out after {timeout or self.default_timeout}s")
        except Exception as e:
            if isinstance(e, ADBError):
                raise
            raise ADBError(f"ADB command error: {e}")
    
    async def shell(
        self,
        command: str,
        device_id: Optional[str] = None,
        timeout: Optional[float] = None
    ) -> str:
        """Execute shell command"""
        _, stdout, _ = await self.execute(
            ["shell", command],
            device_id,
            timeout
        )
        return stdout.strip()
    
    async def push(
        self,
        local_path: str,
        remote_path: str,
        device_id: Optional[str] = None
    ) -> None:
        """Push file to device"""
        await self.execute(
            ["push", local_path, remote_path],
            device_id
        )
    
    async def pull(
        self,
        remote_path: str,
        local_path: str,
        device_id: Optional[str] = None
    ) -> None:
        """Pull file from device"""
        await self.execute(
            ["pull", remote_path, local_path],
            device_id
        )


class AndroidBridge:
    """
    Android Bridge for UFO Galaxy
    
    Provides Android device integration through ADB commands,
    screen capture, device control, and app management.
    """
    
    def __init__(self, adb_path: str = "adb"):
        self.adb = ADBCommandExecutor(adb_path)
        self._devices: Dict[str, AndroidDeviceInfo] = {}
        self._logcat_callbacks: Dict[str, List[Callable]] = defaultdict(list)
        self._logcat_tasks: Dict[str, asyncio.Task] = {}
        self._screen_stream_tasks: Dict[str, asyncio.Task] = {}
        
        logger.info("AndroidBridge initialized")
    
    async def start_server(self) -> None:
        """Start ADB server"""
        await self.adb.execute(["start-server"], check_error=False)
        logger.info("ADB server started")
    
    async def kill_server(self) -> None:
        """Kill ADB server"""
        await self.adb.execute(["kill-server"], check_error=False)
        logger.info("ADB server killed")
    
    async def list_devices(self) -> List[str]:
        """List connected devices"""
        _, stdout, _ = await self.adb.execute(["devices"])
        
        devices = []
        for line in stdout.split('\n')[1:]:  # Skip header
            line = line.strip()
            if line and '\t' in line:
                device_id, status = line.split('\t')
                if status == 'device':
                    devices.append(device_id)
        
        return devices
    
    async def get_device_info(self, device_id: str) -> AndroidDeviceInfo:
        """Get detailed device information"""
        info = AndroidDeviceInfo(device_id=device_id)
        
        try:
            # Get basic properties
            info.model = await self.adb.shell("getprop ro.product.model", device_id) or "unknown"
            info.manufacturer = await self.adb.shell("getprop ro.product.manufacturer", device_id) or "unknown"
            info.android_version = await self.adb.shell("getprop ro.build.version.release", device_id) or "unknown"
            
            sdk_str = await self.adb.shell("getprop ro.build.version.sdk", device_id)
            info.sdk_version = int(sdk_str) if sdk_str.isdigit() else 0
            
            info.abi = await self.adb.shell("getprop ro.product.cpu.abi", device_id) or "unknown"
            
            # Get screen info
            wm_size = await self.adb.shell("wm size", device_id)
            match = re.search(r'(\d+)x(\d+)', wm_size)
            if match:
                info.screen_resolution = (int(match.group(1)), int(match.group(2)))
            
            wm_density = await self.adb.shell("wm density", device_id)
            match = re.search(r'(\d+)', wm_density)
            if match:
                info.screen_density = int(match.group(1))
            
            # Get battery info
            dumpsys_battery = await self.adb.shell("dumpsys battery", device_id)
            level_match = re.search(r'level: (\d+)', dumpsys_battery)
            if level_match:
                info.battery_level = int(level_match.group(1))
            status_match = re.search(r'status: (\d+)', dumpsys_battery)
            if status_match:
                info.is_charging = status_match.group(1) in ['2', '5']
            
            # Get memory info
            meminfo = await self.adb.shell("cat /proc/meminfo", device_id)
            total_match = re.search(r'MemTotal:\s+(\d+)', meminfo)
            if total_match:
                info.total_ram = int(total_match.group(1)) * 1024
            
            # Get storage info
            df_output = await self.adb.shell("df /data", device_id)
            lines = df_output.split('\n')
            if len(lines) >= 2:
                parts = lines[1].split()
                if len(parts) >= 4:
                    info.total_storage = int(parts[1]) * 1024
                    info.available_storage = int(parts[3]) * 1024
            
            # Check root access
            su_check = await self.adb.shell("which su", device_id)
            info.is_rooted = su_check.strip() != ''
            
            # Store all properties
            props_output = await self.adb.shell("getprop", device_id)
            for line in props_output.split('\n'):
                match = re.search(r'\[([^\]]+)\]: \[([^\]]*)\]', line)
                if match:
                    info.properties[match.group(1)] = match.group(2)
            
            # Cache device info
            self._devices[device_id] = info
            
        except Exception as e:
            logger.error(f"Error getting device info for {device_id}: {e}")
        
        return info
    
    async def connect_device(self, host: str, port: int = 5555) -> bool:
        """Connect to device over network"""
        try:
            returncode, stdout, _ = await self.adb.execute(
                ["connect", f"{host}:{port}"],
                check_error=False
            )
            return "connected" in stdout.lower() or returncode == 0
        except Exception as e:
            logger.error(f"Failed to connect to {host}:{port}: {e}")
            return False
    
    async def disconnect_device(self, host: str, port: int = 5555) -> bool:
        """Disconnect from network device"""
        try:
            await self.adb.execute(["disconnect", f"{host}:{port}"])
            return True
        except Exception as e:
            logger.error(f"Failed to disconnect {host}:{port}: {e}")
            return False
    
    # ===================================================================
    # Screen Capture and Control
    # ===================================================================
    
    async def capture_screen(
        self,
        device_id: str,
        output_path: Optional[str] = None,
        format: str = "png"
    ) -> bytes:
        """
        Capture device screen
        
        Args:
            device_id: Device ID
            output_path: Local output path (optional)
            format: Image format (png or jpg)
            
        Returns:
            Screenshot as bytes
        """
        try:
            # Capture to device
            remote_path = f"/sdcard/screen_capture.{format}"
            await self.adb.shell(f"screencap -p {remote_path}", device_id)
            
            # Pull to local
            if output_path:
                await self.adb.pull(remote_path, output_path, device_id)
                with open(output_path, 'rb') as f:
                    return f.read()
            else:
                # Pull to temp file
                with tempfile.NamedTemporaryFile(suffix=f".{format}", delete=False) as tmp:
                    await self.adb.pull(remote_path, tmp.name, device_id)
                    with open(tmp.name, 'rb') as f:
                        data = f.read()
                    os.unlink(tmp.name)
                    return data
        
        except Exception as e:
            raise ScreenCaptureError(f"Screen capture failed: {e}")
    
    async def capture_screen_base64(self, device_id: str, format: str = "png") -> str:
        """Capture screen and return as base64 string"""
        data = await self.capture_screen(device_id, format=format)
        return base64.b64encode(data).decode('utf-8')
    
    async def start_screen_stream(
        self,
        device_id: str,
        callback: Callable[[bytes], None],
        fps: int = 10
    ) -> None:
        """
        Start screen streaming
        
        Args:
            device_id: Device ID
            callback: Callback function for frame data
            fps: Frames per second
        """
        interval = 1.0 / fps
        
        async def stream_loop():
            while device_id in self._screen_stream_tasks:
                try:
                    frame = await self.capture_screen(device_id)
                    callback(frame)
                    await asyncio.sleep(interval)
                except Exception as e:
                    logger.error(f"Screen stream error: {e}")
                    await asyncio.sleep(1)
        
        task = asyncio.create_task(stream_loop())
        self._screen_stream_tasks[device_id] = task
        logger.info(f"Started screen stream for {device_id}")
    
    async def stop_screen_stream(self, device_id: str) -> None:
        """Stop screen streaming"""
        task = self._screen_stream_tasks.pop(device_id, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            logger.info(f"Stopped screen stream for {device_id}")
    
    # ===================================================================
    # Input Control
    # ===================================================================
    
    async def send_touch(self, device_id: str, event: TouchEvent) -> None:
        """Send touch event"""
        await self.adb.shell(event.to_adb_command(), device_id)
    
    async def send_swipe(self, device_id: str, event: SwipeEvent) -> None:
        """Send swipe event"""
        await self.adb.shell(event.to_adb_command(), device_id)
    
    async def send_key(self, device_id: str, event: KeyEvent) -> None:
        """Send key event"""
        await self.adb.shell(event.to_adb_command(), device_id)
    
    async def send_text(self, device_id: str, text: str) -> None:
        """Send text input"""
        # Escape special characters
        escaped = text.replace(' ', '%s').replace("'", "'\"'\"'")
        await self.adb.shell(f"input text '{escaped}'", device_id)
    
    async def tap(self, device_id: str, x: int, y: int) -> None:
        """Tap at coordinates"""
        await self.send_touch(device_id, TouchEvent(x, y, action="down"))
    
    async def swipe(
        self,
        device_id: str,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration_ms: int = 300
    ) -> None:
        """Swipe from start to end coordinates"""
        await self.send_swipe(
            device_id,
            SwipeEvent(start_x, start_y, end_x, end_y, duration_ms)
        )
    
    async def press_key(self, device_id: str, keycode: int) -> None:
        """Press a key"""
        await self.send_key(device_id, KeyEvent(keycode))
    
    async def press_home(self, device_id: str) -> None:
        """Press home button"""
        await self.press_key(device_id, KeyEvent.KEYCODE_HOME)
    
    async def press_back(self, device_id: str) -> None:
        """Press back button"""
        await self.press_key(device_id, KeyEvent.KEYCODE_BACK)
    
    async def press_power(self, device_id: str) -> None:
        """Press power button"""
        await self.press_key(device_id, KeyEvent.KEYCODE_POWER)
    
    async def press_volume_up(self, device_id: str) -> None:
        """Press volume up"""
        await self.press_key(device_id, KeyEvent.KEYCODE_VOLUME_UP)
    
    async def press_volume_down(self, device_id: str) -> None:
        """Press volume down"""
        await self.press_key(device_id, KeyEvent.KEYCODE_VOLUME_DOWN)
    
    # ===================================================================
    # App Management
    # ===================================================================
    
    async def install_app(
        self,
        device_id: str,
        apk_path: str,
        grant_permissions: bool = True,
        reinstall: bool = False
    ) -> bool:
        """
        Install APK on device
        
        Args:
            device_id: Device ID
            apk_path: Path to APK file
            grant_permissions: Grant all permissions
            reinstall: Reinstall if already exists
            
        Returns:
            True if successful
        """
        try:
            cmd = ["install"]
            
            if grant_permissions:
                cmd.append("-g")
            if reinstall:
                cmd.append("-r")
            
            cmd.append(apk_path)
            
            returncode, stdout, stderr = await self.adb.execute(
                cmd, device_id, timeout=120.0, check_error=False
            )
            
            if "success" in stdout.lower():
                logger.info(f"Installed {apk_path} on {device_id}")
                return True
            else:
                error_msg = stderr or stdout
                raise InstallError(f"Installation failed: {error_msg}")
        
        except Exception as e:
            logger.error(f"Failed to install {apk_path}: {e}")
            raise
    
    async def uninstall_app(
        self,
        device_id: str,
        package_name: str,
        keep_data: bool = False
    ) -> bool:
        """Uninstall app from device"""
        try:
            cmd = ["uninstall"]
            if keep_data:
                cmd.append("-k")
            cmd.append(package_name)
            
            returncode, stdout, _ = await self.adb.execute(
                cmd, device_id, check_error=False
            )
            
            success = "success" in stdout.lower() or returncode == 0
            if success:
                logger.info(f"Uninstalled {package_name} from {device_id}")
            return success
        
        except Exception as e:
            logger.error(f"Failed to uninstall {package_name}: {e}")
            return False
    
    async def list_packages(
        self,
        device_id: str,
        include_system: bool = False
    ) -> List[str]:
        """List installed packages"""
        cmd = ["shell", "pm", "list", "packages"]
        if not include_system:
            cmd.append("-3")  # Third-party only
        
        _, stdout, _ = await self.adb.execute(cmd, device_id)
        
        packages = []
        for line in stdout.split('\n'):
            line = line.strip()
            if line.startswith("package:"):
                packages.append(line[8:])  # Remove "package:" prefix
        
        return packages
    
    async def get_app_info(self, device_id: str, package_name: str) -> Optional[AppInfo]:
        """Get app information"""
        try:
            dumpsys = await self.adb.shell(
                f"dumpsys package {package_name}",
                device_id
            )
            
            info = AppInfo(package_name=package_name)
            
            # Parse version info
            version_match = re.search(r'versionName=([^\s]+)', dumpsys)
            if version_match:
                info.version_name = version_match.group(1)
            
            code_match = re.search(r'versionCode=(\d+)', dumpsys)
            if code_match:
                info.version_code = int(code_match.group(1))
            
            # Check if system app
            info.is_system_app = "system" in dumpsys.lower()
            
            # Check if enabled
            info.is_enabled = "enabled" in dumpsys.lower() or "disabled" not in dumpsys.lower()
            
            return info
        
        except Exception as e:
            logger.error(f"Failed to get app info for {package_name}: {e}")
            return None
    
    async def launch_app(self, device_id: str, package_name: str, activity: Optional[str] = None) -> bool:
        """Launch an app"""
        try:
            if activity:
                component = f"{package_name}/{activity}"
            else:
                component = package_name
            
            await self.adb.shell(
                f"monkey -p {package_name} -c android.intent.category.LAUNCHER 1",
                device_id
            )
            return True
        except Exception as e:
            logger.error(f"Failed to launch {package_name}: {e}")
            return False
    
    async def force_stop_app(self, device_id: str, package_name: str) -> None:
        """Force stop an app"""
        await self.adb.shell(f"am force-stop {package_name}", device_id)
    
    async def clear_app_data(self, device_id: str, package_name: str) -> None:
        """Clear app data"""
        await self.adb.shell(f"pm clear {package_name}", device_id)
    
    # ===================================================================
    # Logcat
    # ===================================================================
    
    async def start_logcat(
        self,
        device_id: str,
        callback: Callable[[str], None],
        filter_tag: Optional[str] = None,
        filter_level: str = "V"
    ) -> None:
        """
        Start logcat monitoring
        
        Args:
            device_id: Device ID
            callback: Callback for log lines
            filter_tag: Filter by tag
            filter_level: Log level (V, D, I, W, E, F)
        """
        cmd = ["logcat"]
        
        if filter_tag:
            cmd.extend(["-s", f"{filter_tag}:{filter_level}"])
        else:
            cmd.extend(["-v", "threadtime", f"*:{filter_level}"])
        
        async def logcat_loop():
            proc = await asyncio.create_subprocess_exec(
                self.adb.adb_path, "-s", device_id, *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            while device_id in self._logcat_tasks:
                try:
                    line = await asyncio.wait_for(
                        proc.stdout.readline(),
                        timeout=1.0
                    )
                    if line:
                        callback(line.decode('utf-8', errors='ignore').strip())
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.error(f"Logcat error: {e}")
                    break
            
            proc.terminate()
            await proc.wait()
        
        task = asyncio.create_task(logcat_loop())
        self._logcat_tasks[device_id] = task
        logger.info(f"Started logcat for {device_id}")
    
    async def stop_logcat(self, device_id: str) -> None:
        """Stop logcat monitoring"""
        task = self._logcat_tasks.pop(device_id, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            logger.info(f"Stopped logcat for {device_id}")
    
    async def clear_logcat(self, device_id: str) -> None:
        """Clear logcat buffer"""
        await self.adb.execute(["logcat", "-c"], device_id)
    
    # ===================================================================
    # File Operations
    # ===================================================================
    
    async def push_file(
        self,
        device_id: str,
        local_path: str,
        remote_path: str
    ) -> None:
        """Push file to device"""
        await self.adb.push(local_path, remote_path, device_id)
    
    async def pull_file(
        self,
        device_id: str,
        remote_path: str,
        local_path: str
    ) -> None:
        """Pull file from device"""
        await self.adb.pull(remote_path, local_path, device_id)
    
    async def list_directory(
        self,
        device_id: str,
        path: str
    ) -> List[Dict[str, Any]]:
        """List directory contents"""
        output = await self.adb.shell(f"ls -la '{path}'", device_id)
        
        entries = []
        for line in output.split('\n')[1:]:  # Skip total line
            parts = line.split()
            if len(parts) >= 8:
                entries.append({
                    'permissions': parts[0],
                    'owner': parts[2],
                    'group': parts[3],
                    'size': int(parts[4]) if parts[4].isdigit() else 0,
                    'date': ' '.join(parts[5:7]),
                    'name': parts[7]
                })
        
        return entries
    
    async def create_directory(self, device_id: str, path: str) -> None:
        """Create directory on device"""
        await self.adb.shell(f"mkdir -p '{path}'", device_id)
    
    async def remove_file(self, device_id: str, path: str) -> None:
        """Remove file or directory from device"""
        await self.adb.shell(f"rm -rf '{path}'", device_id)
    
    # ===================================================================
    # System Operations
    # ===================================================================
    
    async def reboot(self, device_id: str, mode: str = "normal") -> None:
        """
        Reboot device
        
        Args:
            device_id: Device ID
            mode: Reboot mode (normal, recovery, bootloader)
        """
        if mode == "recovery":
            await self.adb.execute(["reboot", "recovery"], device_id)
        elif mode == "bootloader":
            await self.adb.execute(["reboot", "bootloader"], device_id)
        else:
            await self.adb.execute(["reboot"], device_id)
    
    async def get_screenshot_size(self, device_id: str) -> Tuple[int, int]:
        """Get screen size"""
        info = await self.get_device_info(device_id)
        return info.screen_resolution


# ============================================================================
# Export
# ============================================================================

__all__ = [
    'ADBError',
    'DeviceNotFoundError',
    'InstallError',
    'ScreenCaptureError',
    'AndroidDeviceInfo',
    'AppInfo',
    'TouchEvent',
    'SwipeEvent',
    'KeyEvent',
    'ADBCommandExecutor',
    'AndroidBridge'
]
