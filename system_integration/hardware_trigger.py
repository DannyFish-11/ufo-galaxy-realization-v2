"""
Hardware Trigger Manager for Galaxy
System Integration Layer - Hardware Wake & State Switching

This module provides real hardware trigger detection for:
- Android: Hardware keys (volume/power), gestures, voice
- Windows: Hotkeys, touch gestures, voice
- Cross-platform: External devices (Bluetooth/USB)

Dependencies:
    pip install pynput pywin32 vosk sounddevice numpy pyserial pyusb
    
Android-specific (via Pyjnius):
    pip install pyjnius
"""

import os
import sys
import time
import json
import logging
import asyncio
import threading
import platform
from typing import Dict, List, Optional, Callable, Any, Set
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum, auto
from collections import deque
import importlib.util

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =============================================================================
# Trigger Types & Enums
# =============================================================================

class TriggerType(Enum):
    """Types of hardware triggers"""
    HARDWARE_KEY = "hardware_key"      # Volume/Power buttons
    GESTURE = "gesture"                 # Screen gestures
    HOTKEY = "hotkey"                   # Keyboard shortcuts
    VOICE = "voice"                     # Voice wake word
    EXTERNAL_DEVICE = "external_device" # Bluetooth/USB devices
    TOUCH = "touch"                     # Touch screen events
    PROXIMITY = "proximity"             # Proximity sensor
    MOTION = "motion"                   # Motion/accelerometer

class TriggerPriority(Enum):
    """Trigger priority levels"""
    CRITICAL = 0    # Emergency triggers
    HIGH = 1        # User-initiated actions
    MEDIUM = 2      # Automatic responses
    LOW = 3         # Background triggers

class SystemState(Enum):
    """System states for Galaxy"""
    DORMANT = "dormant"         # System sleeping, minimal resources
    ISLAND = "island"           # Compact UI mode (dynamic island)
    SIDESHEET = "sidesheet"     # Side panel mode
    FULLAGENT = "fullagent"     # Full agent interface

class PlatformType(Enum):
    """Platform detection"""
    ANDROID = "android"
    WINDOWS = "windows"
    LINUX = "linux"
    MACOS = "macos"
    UNKNOWN = "unknown"

# =============================================================================
# Data Models
# =============================================================================

@dataclass
class TriggerEvent:
    """Hardware trigger event"""
    trigger_type: TriggerType
    source: str
    timestamp: datetime = field(default_factory=datetime.now)
    data: Dict[str, Any] = field(default_factory=dict)
    priority: TriggerPriority = TriggerPriority.MEDIUM
    platform: PlatformType = PlatformType.UNKNOWN
    
    def to_dict(self) -> Dict:
        return {
            "trigger_type": self.trigger_type.value,
            "source": self.source,
            "timestamp": self.timestamp.isoformat(),
            "data": self.data,
            "priority": self.priority.value,
            "platform": self.platform.value
        }

@dataclass
class StateTransition:
    """State transition record"""
    from_state: SystemState
    to_state: SystemState
    trigger: TriggerEvent
    timestamp: datetime = field(default_factory=datetime.now)
    success: bool = True
    error_message: Optional[str] = None

@dataclass
class HardwareTriggerConfig:
    """Configuration for hardware triggers"""
    # Voice wake word
    wake_word: str = "hey ufo"
    voice_model_path: str = "./models/vosk-model-small-en-us-0.15"
    
    # Hotkey configuration
    hotkey_combination: str = "ctrl+shift+space"
    emergency_hotkey: str = "ctrl+alt+u"
    
    # Gesture sensitivity
    gesture_edge_threshold: int = 50  # pixels from edge
    gesture_min_distance: int = 100   # minimum swipe distance
    
    # Hardware key timing
    long_press_duration: float = 1.0  # seconds
    double_tap_interval: float = 0.3  # seconds
    
    # External device monitoring
    monitor_bluetooth: bool = True
    monitor_usb: bool = True
    
    # Enable/disable triggers
    enable_voice: bool = True
    enable_hotkey: bool = True
    enable_gesture: bool = True
    enable_hardware_key: bool = True
    enable_external_device: bool = True

# =============================================================================
# Platform Detection
# =============================================================================

def detect_platform() -> PlatformType:
    """Detect the current platform"""
    system = platform.system().lower()
    
    # Check for Android (via environment or build properties)
    if "ANDROID_ROOT" in os.environ or os.path.exists("/system/build.prop"):
        return PlatformType.ANDROID
    
    if system == "windows":
        return PlatformType.WINDOWS
    elif system == "linux":
        return PlatformType.LINUX
    elif system == "darwin":
        return PlatformType.MACOS
    
    return PlatformType.UNKNOWN

def is_android() -> bool:
    """Check if running on Android"""
    return detect_platform() == PlatformType.ANDROID

def is_windows() -> bool:
    """Check if running on Windows"""
    return detect_platform() == PlatformType.WINDOWS

# =============================================================================
# Voice Recognition (Vosk-based)
# =============================================================================

class VoiceTriggerListener:
    """
    Voice wake word detection using Vosk
    
    Features:
    - Continuous microphone monitoring
    - Wake word detection
    - Command recognition
    """
    
    def __init__(self, config: HardwareTriggerConfig, callback: Callable[[TriggerEvent], None]):
        self.config = config
        self.callback = callback
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._model = None
        self._recognizer = None
        self._audio_queue = deque(maxlen=100)
        
        # Wake word variations
        self.wake_words = [
            config.wake_word.lower(),
            "hey youfo",
            "hay ufo",
            "a ufo",
            "hey you eff oh"
        ]
        
        self._check_dependencies()
    
    def _check_dependencies(self):
        """Check if required dependencies are available"""
        self.vosk_available = importlib.util.find_spec("vosk") is not None
        self.sounddevice_available = importlib.util.find_spec("sounddevice") is not None
        self.numpy_available = importlib.util.find_spec("numpy") is not None
        
        if not all([self.vosk_available, self.sounddevice_available, self.numpy_available]):
            missing = []
            if not self.vosk_available:
                missing.append("vosk")
            if not self.sounddevice_available:
                missing.append("sounddevice")
            if not self.numpy_available:
                missing.append("numpy")
            logger.warning(f"Voice trigger dependencies missing: {missing}. Install: pip install {' '.join(missing)}")
    
    def start(self):
        """Start voice listening"""
        if not all([self.vosk_available, self.sounddevice_available, self.numpy_available]):
            logger.error("Cannot start voice listener - dependencies missing")
            return False
        
        if self._running:
            return True
        
        try:
            import vosk
            import sounddevice as sd
            import numpy as np
            
            # Load model
            model_path = self.config.voice_model_path
            if not os.path.exists(model_path):
                logger.warning(f"Vosk model not found at {model_path}. Download from https://alphacephei.com/vosk/models")
                # Try to use smaller model
                model_path = "./models/vosk-model-tiny-en-us-0.15"
                if not os.path.exists(model_path):
                    logger.error("No Vosk model found. Voice trigger disabled.")
                    return False
            
            self._model = vosk.Model(model_path)
            self._recognizer = vosk.KaldiRecognizer(self._model, 16000)
            
            self._running = True
            self._thread = threading.Thread(target=self._listen_loop, daemon=True)
            self._thread.start()
            
            logger.info(f"Voice trigger started - listening for '{self.config.wake_word}'")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start voice listener: {e}")
            return False
    
    def stop(self):
        """Stop voice listening"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        logger.info("Voice trigger stopped")
    
    def _listen_loop(self):
        """Main voice listening loop"""
        import sounddevice as sd
        import numpy as np
        
        def audio_callback(indata, frames, time_info, status):
            """Callback for audio stream"""
            if status:
                logger.debug(f"Audio status: {status}")
            # Convert to int16 and add to queue
            audio_data = (indata * 32767).astype(np.int16)
            self._audio_queue.append(audio_data.tobytes())
        
        try:
            with sd.RawInputStream(
                samplerate=16000,
                blocksize=8000,
                dtype=np.int16,
                channels=1,
                callback=audio_callback
            ):
                while self._running:
                    # Process audio queue
                    while self._audio_queue and self._running:
                        audio_chunk = self._audio_queue.popleft()
                        if self._recognizer.AcceptWaveform(audio_chunk):
                            result = json.loads(self._recognizer.Result())
                            text = result.get("text", "").lower()
                            if text:
                                self._process_recognized_text(text)
                        else:
                            # Check partial results for faster response
                            partial = json.loads(self._recognizer.PartialResult())
                            partial_text = partial.get("partial", "").lower()
                            if partial_text:
                                self._check_wake_word(partial_text, partial=True)
                    
                    time.sleep(0.01)
                    
        except Exception as e:
            logger.error(f"Voice listen loop error: {e}")
    
    def _process_recognized_text(self, text: str):
        """Process recognized text"""
        logger.debug(f"Recognized: {text}")
        
        # Check for wake word
        if self._check_wake_word(text):
            return
        
        # Check for commands after wake word
        command = self._extract_command(text)
        if command:
            event = TriggerEvent(
                trigger_type=TriggerType.VOICE,
                source="vosk_recognizer",
                data={"text": text, "command": command},
                priority=TriggerPriority.HIGH,
                platform=detect_platform()
            )
            self.callback(event)
    
    def _check_wake_word(self, text: str, partial: bool = False) -> bool:
        """Check if text contains wake word"""
        text_lower = text.lower()
        
        for wake_word in self.wake_words:
            if wake_word in text_lower:
                if not partial or len(text_lower) >= len(wake_word):
                    logger.info(f"Wake word detected: '{wake_word}' in '{text}'")
                    event = TriggerEvent(
                        trigger_type=TriggerType.VOICE,
                        source="vosk_wake_word",
                        data={"text": text, "wake_word": wake_word},
                        priority=TriggerPriority.HIGH,
                        platform=detect_platform()
                    )
                    self.callback(event)
                    return True
        return False
    
    def _extract_command(self, text: str) -> Optional[str]:
        """Extract command from recognized text"""
        # Remove wake word
        for wake_word in self.wake_words:
            text = text.replace(wake_word, "").strip()
        
        # Common commands
        commands = {
            "open": ["open", "show", "display"],
            "close": ["close", "hide", "exit"],
            "minimize": ["minimize", "small"],
            "maximize": ["maximize", "full screen", "fullscreen"],
            "search": ["search", "find", "look for"],
            "help": ["help", "assist", "support"]
        }
        
        for command, keywords in commands.items():
            for keyword in keywords:
                if keyword in text:
                    return command
        
        return None if text == "" else "unknown"

# =============================================================================
# Windows Hotkey Listener (pynput)
# =============================================================================

class WindowsHotkeyListener:
    """
    Windows global hotkey listener using pynput
    
    Features:
    - Global hotkey registration (works even when app not focused)
    - Multiple hotkey combinations
    - Emergency hotkey support
    """
    
    def __init__(self, config: HardwareTriggerConfig, callback: Callable[[TriggerEvent], None]):
        self.config = config
        self.callback = callback
        self._running = False
        self._listener = None
        self._pressed_keys: Set[str] = set()
        self._last_trigger_time = 0
        self._trigger_cooldown = 0.5  # seconds
        
        self._check_dependencies()
    
    def _check_dependencies(self):
        """Check if pynput is available"""
        self.pynput_available = importlib.util.find_spec("pynput") is not None
        if not self.pynput_available:
            logger.warning("pynput not available. Install: pip install pynput")
    
    def start(self):
        """Start hotkey listening"""
        if not self.pynput_available:
            logger.error("Cannot start hotkey listener - pynput not available")
            return False
        
        if self._running:
            return True
        
        try:
            from pynput import keyboard
            
            self._listener = keyboard.Listener(
                on_press=self._on_press,
                on_release=self._on_release
            )
            self._listener.start()
            self._running = True
            
            logger.info(f"Hotkey listener started - {self.config.hotkey_combination} to activate")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start hotkey listener: {e}")
            return False
    
    def stop(self):
        """Stop hotkey listening"""
        self._running = False
        if self._listener:
            self._listener.stop()
        logger.info("Hotkey listener stopped")
    
    def _on_press(self, key):
        """Handle key press"""
        try:
            key_str = key.char if hasattr(key, 'char') and key.char else str(key)
            self._pressed_keys.add(key_str.lower())
            self._check_hotkeys()
        except Exception as e:
            logger.debug(f"Key press error: {e}")
    
    def _on_release(self, key):
        """Handle key release"""
        try:
            key_str = key.char if hasattr(key, 'char') and key.char else str(key)
            self._pressed_keys.discard(key_str.lower())
        except Exception as e:
            logger.debug(f"Key release error: {e}")
    
    def _check_hotkeys(self):
        """Check if any hotkey combination is pressed"""
        current_time = time.time()
        if current_time - self._last_trigger_time < self._trigger_cooldown:
            return
        
        # Parse configured hotkeys
        hotkeys = {
            self.config.hotkey_combination: (TriggerPriority.HIGH, "activate"),
            self.config.emergency_hotkey: (TriggerPriority.CRITICAL, "emergency")
        }
        
        for hotkey_str, (priority, action) in hotkeys.items():
            if self._is_hotkey_pressed(hotkey_str):
                self._last_trigger_time = current_time
                event = TriggerEvent(
                    trigger_type=TriggerType.HOTKEY,
                    source="pynput_hotkey",
                    data={"hotkey": hotkey_str, "action": action},
                    priority=priority,
                    platform=PlatformType.WINDOWS
                )
                self.callback(event)
                break
    
    def _is_hotkey_pressed(self, hotkey_str: str) -> bool:
        """Check if a hotkey combination is currently pressed"""
        required_keys = [k.strip().lower() for k in hotkey_str.split('+')]
        return all(key in self._pressed_keys for key in required_keys)

# =============================================================================
# Android Hardware Key Listener (Pyjnius)
# =============================================================================

class AndroidHardwareKeyListener:
    """
    Android hardware key listener using Pyjnius
    
    Features:
    - Volume key long-press detection
    - Power button detection
    - Key combination detection
    """
    
    def __init__(self, config: HardwareTriggerConfig, callback: Callable[[TriggerEvent], None]):
        self.config = config
        self.callback = callback
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._pyjnius_available = False
        self._PythonActivity = None
        self._View = None
        self._KeyEvent = None
        
        self._key_states: Dict[int, Dict] = {}
        
        self._check_dependencies()
    
    def _check_dependencies(self):
        """Check if Pyjnius is available"""
        try:
            from jnius import autoclass, cast
            self._autoclass = autoclass
            self._cast = cast
            self._pyjnius_available = True
            logger.info("Pyjnius available for Android hardware key detection")
        except ImportError:
            logger.warning("Pyjnius not available. Install: pip install pyjnius")
    
    def start(self):
        """Start hardware key listening"""
        if not self._pyjnius_available:
            logger.error("Cannot start Android key listener - pyjnius not available")
            return False
        
        if self._running:
            return True
        
        try:
            # Get Android classes
            self._PythonActivity = self._autoclass('org.kivy.android.PythonActivity')
            self._View = self._autoclass('android.view.View')
            self._KeyEvent = self._autoclass('android.view.KeyEvent')
            
            # Get current activity
            activity = self._PythonActivity.mActivity
            
            # Set up key listener on the decor view
            self._setup_key_listener(activity)
            
            self._running = True
            self._thread = threading.Thread(target=self._key_loop, daemon=True)
            self._thread.start()
            
            logger.info("Android hardware key listener started")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start Android key listener: {e}")
            return False
    
    def stop(self):
        """Stop hardware key listening"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        logger.info("Android hardware key listener stopped")
    
    def _setup_key_listener(self, activity):
        """Set up key listener on activity"""
        try:
            from jnius import PythonJavaClass, java_method
            
            class KeyListener(PythonJavaClass):
                __javainterfaces__ = ['android.view.View$OnKeyListener']
                
                def __init__(self, callback):
                    super().__init__()
                    self.callback = callback
                
                @java_method('(Landroid/view/View;ILandroid/view/KeyEvent;)Z')
                def onKey(self, view, key_code, event):
                    return self.callback(key_code, event)
            
            self._key_listener = KeyListener(self._on_android_key)
            
            # Set on decor view
            decor_view = activity.getWindow().getDecorView()
            decor_view.setOnKeyListener(self._key_listener)
            
        except Exception as e:
            logger.error(f"Failed to setup key listener: {e}")
    
    def _on_android_key(self, key_code, event) -> bool:
        """Handle Android key event"""
        try:
            action = event.getAction()
            event_time = event.getEventTime()
            
            # Key pressed
            if action == self._KeyEvent.ACTION_DOWN:
                if key_code not in self._key_states:
                    self._key_states[key_code] = {
                        "press_time": eventTime,
                        "long_press_triggered": False
                    }
                
                # Check for long press
                press_duration = (eventTime - self._key_states[key_code]["press_time"]) / 1000.0
                
                if press_duration >= self.config.long_press_duration:
                    if not self._key_states[key_code]["long_press_triggered"]:
                        self._key_states[key_code]["long_press_triggered"] = True
                        self._handle_long_press(key_code)
            
            # Key released
            elif action == self._KeyEvent.ACTION_UP:
                if key_code in self._key_states:
                    press_duration = (eventTime - self._key_states[key_code]["press_time"]) / 1000.0
                    
                    if press_duration < self.config.long_press_duration:
                        self._handle_short_press(key_code)
                    
                    del self._key_states[key_code]
            
            return True  # Consume event
            
        except Exception as e:
            logger.error(f"Android key handling error: {e}")
            return False
    
    def _handle_short_press(self, key_code: int):
        """Handle short key press"""
        key_name = self._get_key_name(key_code)
        logger.debug(f"Short press: {key_name}")
        
        # Volume up + down combo
        if key_code in [self._KeyEvent.KEYCODE_VOLUME_UP, self._KeyEvent.KEYCODE_VOLUME_DOWN]:
            event = TriggerEvent(
                trigger_type=TriggerType.HARDWARE_KEY,
                source="android_volume_key",
                data={"key": key_name, "press_type": "short"},
                priority=TriggerPriority.MEDIUM,
                platform=PlatformType.ANDROID
            )
            self.callback(event)
    
    def _handle_long_press(self, key_code: int):
        """Handle long key press"""
        key_name = self._get_key_name(key_code)
        logger.info(f"Long press detected: {key_name}")
        
        # Long press on volume keys = wake
        if key_code in [self._KeyEvent.KEYCODE_VOLUME_UP, self._KeyEvent.KEYCODE_VOLUME_DOWN]:
            event = TriggerEvent(
                trigger_type=TriggerType.HARDWARE_KEY,
                source="android_volume_long_press",
                data={"key": key_name, "press_type": "long"},
                priority=TriggerPriority.HIGH,
                platform=PlatformType.ANDROID
            )
            self.callback(event)
        
        # Long press on power = emergency
        elif key_code == self._KeyEvent.KEYCODE_POWER:
            event = TriggerEvent(
                trigger_type=TriggerType.HARDWARE_KEY,
                source="android_power_long_press",
                data={"key": key_name, "press_type": "long"},
                priority=TriggerPriority.CRITICAL,
                platform=PlatformType.ANDROID
            )
            self.callback(event)
    
    def _get_key_name(self, key_code: int) -> str:
        """Get human-readable key name"""
        key_names = {
            24: "VOLUME_UP",
            25: "VOLUME_DOWN",
            26: "POWER",
            4: "BACK",
            3: "HOME",
            82: "MENU"
        }
        return key_names.get(key_code, f"KEY_{key_code}")
    
    def _key_loop(self):
        """Background key monitoring loop"""
        while self._running:
            # Check for key combinations
            self._check_key_combinations()
            time.sleep(0.05)
    
    def _check_key_combinations(self):
        """Check for key combinations"""
        # Volume up + down together
        up_pressed = 24 in self._key_states  # KEYCODE_VOLUME_UP
        down_pressed = 25 in self._key_states  # KEYCODE_VOLUME_DOWN
        
        if up_pressed and down_pressed:
            up_time = self._key_states[24]["press_time"]
            down_time = self._key_states[25]["press_time"]
            
            # If pressed within 100ms of each other
            if abs(up_time - down_time) < 100:
                logger.info("Volume up+down combo detected")
                event = TriggerEvent(
                    trigger_type=TriggerType.HARDWARE_KEY,
                    source="android_volume_combo",
                    data={"combo": "volume_up_down"},
                    priority=TriggerPriority.HIGH,
                    platform=PlatformType.ANDROID
                )
                self.callback(event)

# =============================================================================
# Android Gesture Listener
# =============================================================================

class AndroidGestureListener:
    """
    Android gesture listener using Pyjnius
    
    Features:
    - Edge swipe detection
    - Multi-touch gestures
    - Screen edge activation
    """
    
    def __init__(self, config: HardwareTriggerConfig, callback: Callable[[TriggerEvent], None]):
        self.config = config
        self.callback = callback
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._pyjnius_available = False
        
        self._touch_start: Optional[Dict] = None
        self._gesture_in_progress = False
        
        self._check_dependencies()
    
    def _check_dependencies(self):
        """Check if Pyjnius is available"""
        try:
            from jnius import autoclass
            self._autoclass = autoclass
            self._pyjnius_available = True
        except ImportError:
            logger.warning("Pyjnius not available for Android gesture detection")
    
    def start(self):
        """Start gesture listening"""
        if not self._pyjnius_available:
            logger.error("Cannot start Android gesture listener - pyjnius not available")
            return False
        
        if self._running:
            return True
        
        try:
            self._running = True
            self._thread = threading.Thread(target=self._gesture_loop, daemon=True)
            self._thread.start()
            
            logger.info("Android gesture listener started")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start Android gesture listener: {e}")
            return False
    
    def stop(self):
        """Stop gesture listening"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        logger.info("Android gesture listener stopped")
    
    def _gesture_loop(self):
        """Main gesture detection loop"""
        try:
            from jnius import autoclass
            
            DisplayMetrics = autoclass('android.util.DisplayMetrics')
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            
            activity = PythonActivity.mActivity
            metrics = DisplayMetrics()
            activity.getWindowManager().getDefaultDisplay().getMetrics(metrics)
            
            screen_width = metrics.widthPixels
            screen_height = metrics.heightPixels
            
            edge_threshold = self.config.gesture_edge_threshold
            
            while self._running:
                # Get touch coordinates from accessibility service or overlay
                # This is simplified - real implementation would use AccessibilityService
                # or a transparent overlay view
                
                # Simulate checking for edge swipes
                # In real implementation, this would come from onTouchEvent
                
                time.sleep(0.05)
                
        except Exception as e:
            logger.error(f"Gesture loop error: {e}")
    
    def on_touch_event(self, event):
        """Process touch event (called from Android)"""
        try:
            action = event.getAction()
            x = event.getRawX()
            y = event.getRawY()
            
            if action == 0:  # ACTION_DOWN
                self._touch_start = {"x": x, "y": y, "time": time.time()}
                self._gesture_in_progress = True
                
            elif action == 1:  # ACTION_UP
                if self._touch_start and self._gesture_in_progress:
                    self._process_gesture_end(x, y)
                self._touch_start = None
                self._gesture_in_progress = False
                
            elif action == 2:  # ACTION_MOVE
                if self._touch_start:
                    self._process_gesture_move(x, y)
                    
        except Exception as e:
            logger.error(f"Touch event error: {e}")
    
    def _process_gesture_move(self, x: float, y: float):
        """Process gesture movement"""
        if not self._touch_start:
            return
        
        dx = x - self._touch_start["x"]
        dy = y - self._touch_start["y"]
        distance = (dx ** 2 + dy ** 2) ** 0.5
        
        # Check for edge swipe
        if distance > self.config.gesture_min_distance:
            self._detect_edge_swipe(x, y, dx, dy)
    
    def _process_gesture_end(self, x: float, y: float):
        """Process gesture end"""
        if not self._touch_start:
            return
        
        dx = x - self._touch_start["x"]
        dy = y - self._touch_start["y"]
        duration = time.time() - self._touch_start["time"]
        
        # Detect swipe direction
        if abs(dx) > abs(dy):
            direction = "right" if dx > 0 else "left"
        else:
            direction = "down" if dy > 0 else "up"
        
        distance = (dx ** 2 + dy ** 2) ** 0.5
        
        if distance >= self.config.gesture_min_distance:
            logger.info(f"Swipe detected: {direction}, distance={distance:.0f}")
            
            event = TriggerEvent(
                trigger_type=TriggerType.GESTURE,
                source="android_gesture",
                data={
                    "gesture": "swipe",
                    "direction": direction,
                    "distance": distance,
                    "duration": duration
                },
                priority=TriggerPriority.HIGH,
                platform=PlatformType.ANDROID
            )
            self.callback(event)
    
    def _detect_edge_swipe(self, x: float, y: float, dx: float, dy: float):
        """Detect edge swipe gesture"""
        try:
            from jnius import autoclass
            
            DisplayMetrics = autoclass('android.util.DisplayMetrics')
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            
            activity = PythonActivity.mActivity
            metrics = DisplayMetrics()
            activity.getWindowManager().getDefaultDisplay().getMetrics(metrics)
            
            screen_width = metrics.widthPixels
            screen_height = metrics.heightPixels
            edge_threshold = self.config.gesture_edge_threshold
            
            # Check if started from edge
            from_left = self._touch_start["x"] < edge_threshold
            from_right = self._touch_start["x"] > (screen_width - edge_threshold)
            from_top = self._touch_start["y"] < edge_threshold
            from_bottom = self._touch_start["y"] > (screen_height - edge_threshold)
            
            if from_left and dx > 0:
                self._trigger_edge_gesture("left_edge_in")
            elif from_right and dx < 0:
                self._trigger_edge_gesture("right_edge_in")
            elif from_top and dy > 0:
                self._trigger_edge_gesture("top_edge_in")
            elif from_bottom and dy < 0:
                self._trigger_edge_gesture("bottom_edge_in")
                
        except Exception as e:
            logger.error(f"Edge swipe detection error: {e}")
    
    def _trigger_edge_gesture(self, edge_type: str):
        """Trigger edge gesture event"""
        logger.info(f"Edge gesture: {edge_type}")
        
        event = TriggerEvent(
            trigger_type=TriggerType.GESTURE,
            source="android_edge_gesture",
            data={"gesture": "edge_swipe", "edge": edge_type},
            priority=TriggerPriority.HIGH,
            platform=PlatformType.ANDROID
        )
        self.callback(event)

# =============================================================================
# Windows Touch Gesture Listener
# =============================================================================

class WindowsTouchGestureListener:
    """
    Windows touch gesture listener
    
    Features:
    - Touchpad gesture detection
    - Screen edge swipe
    - Multi-touch support
    """
    
    def __init__(self, config: HardwareTriggerConfig, callback: Callable[[TriggerEvent], None]):
        self.config = config
        self.callback = callback
        self._running = False
        self._thread: Optional[threading.Thread] = None
        
        # Touch tracking
        self._touches: Dict[int, Dict] = {}
        self._last_gesture_time = 0
        self._gesture_cooldown = 0.3
    
    def start(self):
        """Start touch gesture listening"""
        if not is_windows():
            logger.warning("Windows touch listener only works on Windows")
            return False
        
        if self._running:
            return True
        
        try:
            self._running = True
            self._thread = threading.Thread(target=self._touch_loop, daemon=True)
            self._thread.start()
            
            logger.info("Windows touch gesture listener started")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start Windows touch listener: {e}")
            return False
    
    def stop(self):
        """Stop touch gesture listening"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        logger.info("Windows touch gesture listener stopped")
    
    def _touch_loop(self):
        """Main touch detection loop"""
        try:
            import ctypes
            from ctypes import wintypes
            
            # Windows touch API constants
            WM_TOUCH = 0x0240
            TOUCHEVENTF_DOWN = 0x0001
            TOUCHEVENTF_UP = 0x0002
            TOUCHEVENTF_MOVE = 0x0004
            
            user32 = ctypes.windll.user32
            
            # Register for touch input
            # This is simplified - real implementation would use window message handling
            
            while self._running:
                # Poll for touch events
                # Real implementation would use GetMessage/DispatchMessage
                time.sleep(0.016)  # ~60fps
                
        except Exception as e:
            logger.error(f"Touch loop error: {e}")
    
    def process_touch_event(self, touch_info: Dict):
        """Process touch event from Windows"""
        try:
            touch_id = touch_info.get("id")
            x = touch_info.get("x", 0)
            y = touch_info.get("y", 0)
            event_type = touch_info.get("type", "")
            
            if event_type == "down":
                self._touches[touch_id] = {
                    "start_x": x,
                    "start_y": y,
                    "start_time": time.time(),
                    "x": x,
                    "y": y
                }
                
            elif event_type == "move":
                if touch_id in self._touches:
                    self._touches[touch_id]["x"] = x
                    self._touches[touch_id]["y"] = y
                    self._check_gestures()
                    
            elif event_type == "up":
                if touch_id in self._touches:
                    self._process_touch_end(touch_id)
                    del self._touches[touch_id]
                    
        except Exception as e:
            logger.error(f"Touch event processing error: {e}")
    
    def _check_gestures(self):
        """Check for gesture patterns"""
        current_time = time.time()
        if current_time - self._last_gesture_time < self._gesture_cooldown:
            return
        
        # Three-finger swipe up
        if len(self._touches) == 3:
            self._detect_three_finger_gesture()
        
        # Four-finger tap
        elif len(self._touches) == 4:
            self._detect_four_finger_gesture()
    
    def _detect_three_finger_gesture(self):
        """Detect three-finger gestures"""
        touches = list(self._touches.values())
        
        # Calculate average movement
        dy = sum(t["y"] - t["start_y"] for t in touches) / 3
        
        if dy < -100:  # Swipe up
            self._last_gesture_time = time.time()
            event = TriggerEvent(
                trigger_type=TriggerType.GESTURE,
                source="windows_three_finger_swipe_up",
                data={"gesture": "three_finger_swipe", "direction": "up"},
                priority=TriggerPriority.HIGH,
                platform=PlatformType.WINDOWS
            )
            self.callback(event)
    
    def _detect_four_finger_gesture(self):
        """Detect four-finger gestures"""
        self._last_gesture_time = time.time()
        event = TriggerEvent(
            trigger_type=TriggerType.GESTURE,
            source="windows_four_finger_tap",
            data={"gesture": "four_finger_tap"},
            priority=TriggerPriority.HIGH,
            platform=PlatformType.WINDOWS
        )
        self.callback(event)
    
    def _process_touch_end(self, touch_id: int):
        """Process touch end"""
        touch = self._touches.get(touch_id)
        if not touch:
            return
        
        dx = touch["x"] - touch["start_x"]
        dy = touch["y"] - touch["start_y"]
        duration = time.time() - touch["start_time"]
        
        # Detect edge swipe
        screen_width = 1920  # Should get from actual screen
        edge_threshold = self.config.gesture_edge_threshold
        
        if touch["start_x"] < edge_threshold and dx > self.config.gesture_min_distance:
            event = TriggerEvent(
                trigger_type=TriggerType.GESTURE,
                source="windows_edge_swipe",
                data={"gesture": "edge_swipe", "edge": "left", "direction": "right"},
                priority=TriggerPriority.HIGH,
                platform=PlatformType.WINDOWS
            )
            self.callback(event)

# =============================================================================
# External Device Listener (Bluetooth/USB)
# =============================================================================

class ExternalDeviceListener:
    """
    External device connection listener
    
    Features:
    - Bluetooth device detection
    - USB device detection
    - Device-specific triggers
    """
    
    def __init__(self, config: HardwareTriggerConfig, callback: Callable[[TriggerEvent], None]):
        self.config = config
        self.callback = callback
        self._running = False
        self._thread: Optional[threading.Thread] = None
        
        # Device tracking
        self._known_bluetooth_devices: Set[str] = set()
        self._known_usb_devices: Set[str] = set()
        
        # Trigger devices (specific device IDs that trigger actions)
        self.trigger_devices = {
            "bluetooth": ["Galaxy-Headset", "Galaxy-Watch", "Galaxy-Controller"],
            "usb": ["Galaxy-Dongle", "Galaxy-Device"]
        }
    
    def start(self):
        """Start external device monitoring"""
        if self._running:
            return True
        
        try:
            self._running = True
            self._thread = threading.Thread(target=self._device_loop, daemon=True)
            self._thread.start()
            
            logger.info("External device listener started")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start device listener: {e}")
            return False
    
    def stop(self):
        """Stop external device monitoring"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        logger.info("External device listener stopped")
    
    def _device_loop(self):
        """Main device monitoring loop"""
        while self._running:
            try:
                if self.config.monitor_bluetooth:
                    self._check_bluetooth_devices()
                
                if self.config.monitor_usb:
                    self._check_usb_devices()
                
                time.sleep(2)  # Check every 2 seconds
                
            except Exception as e:
                logger.error(f"Device loop error: {e}")
                time.sleep(5)
    
    def _check_bluetooth_devices(self):
        """Check for Bluetooth device changes"""
        try:
            current_devices = self._get_bluetooth_devices()
            
            # Check for new devices
            new_devices = current_devices - self._known_bluetooth_devices
            for device in new_devices:
                logger.info(f"Bluetooth device connected: {device}")
                self._handle_device_event("bluetooth", device, "connected")
            
            # Check for disconnected devices
            disconnected = self._known_bluetooth_devices - current_devices
            for device in disconnected:
                logger.info(f"Bluetooth device disconnected: {device}")
                self._handle_device_event("bluetooth", device, "disconnected")
            
            self._known_bluetooth_devices = current_devices
            
        except Exception as e:
            logger.debug(f"Bluetooth check error: {e}")
    
    def _get_bluetooth_devices(self) -> Set[str]:
        """Get currently connected Bluetooth devices"""
        devices = set()
        
        try:
            if is_windows():
                # Windows: Use PowerShell or WinRT
                import subprocess
                result = subprocess.run(
                    ["powershell", "-Command", "Get-PnpDevice -Class Bluetooth | Where-Object {$_.Status -eq 'OK'} | Select-Object -ExpandProperty FriendlyName"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                for line in result.stdout.strip().split('\n'):
                    if line.strip():
                        devices.add(line.strip())
                        
            elif is_android():
                # Android: Use Pyjnius
                try:
                    from jnius import autoclass
                    BluetoothAdapter = autoclass('android.bluetooth.BluetoothAdapter')
                    adapter = BluetoothAdapter.getDefaultAdapter()
                    if adapter and adapter.isEnabled():
                        bonded = adapter.getBondedDevices()
                        for device in bonded.toArray():
                            devices.add(device.getName())
                except Exception as e:
                    logger.debug(f"Android Bluetooth error: {e}")
                    
            else:  # Linux
                import subprocess
                result = subprocess.run(
                    ["bluetoothctl", "paired-devices"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                for line in result.stdout.strip().split('\n'):
                    if "Device" in line:
                        parts = line.split()
                        if len(parts) >= 3:
                            devices.add(parts[2])
                            
        except Exception as e:
            logger.debug(f"Get Bluetooth devices error: {e}")
        
        return devices
    
    def _check_usb_devices(self):
        """Check for USB device changes"""
        try:
            current_devices = self._get_usb_devices()
            
            # Check for new devices
            new_devices = current_devices - self._known_usb_devices
            for device in new_devices:
                logger.info(f"USB device connected: {device}")
                self._handle_device_event("usb", device, "connected")
            
            # Check for disconnected devices
            disconnected = self._known_usb_devices - current_devices
            for device in disconnected:
                logger.info(f"USB device disconnected: {device}")
                self._handle_device_event("usb", device, "disconnected")
            
            self._known_usb_devices = current_devices
            
        except Exception as e:
            logger.debug(f"USB check error: {e}")
    
    def _get_usb_devices(self) -> Set[str]:
        """Get currently connected USB devices"""
        devices = set()
        
        try:
            if is_windows():
                import subprocess
                result = subprocess.run(
                    ["powershell", "-Command", "Get-PnpDevice -Class USB | Where-Object {$_.Status -eq 'OK'} | Select-Object -ExpandProperty FriendlyName"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                for line in result.stdout.strip().split('\n'):
                    if line.strip():
                        devices.add(line.strip())
                        
            elif is_android():
                # Android USB host mode
                try:
                    from jnius import autoclass
                    UsbManager = autoclass('android.hardware.usb.UsbManager')
                    # Would need context to get UsbManager
                except Exception as e:
                    logger.debug(f"Android USB error: {e}")
                    
            else:  # Linux
                import os
                usb_path = "/sys/bus/usb/devices"
                if os.path.exists(usb_path):
                    for device_dir in os.listdir(usb_path):
                        product_file = os.path.join(usb_path, device_dir, "product")
                        if os.path.exists(product_file):
                            with open(product_file, 'r') as f:
                                product = f.read().strip()
                                if product:
                                    devices.add(product)
                                    
        except Exception as e:
            logger.debug(f"Get USB devices error: {e}")
        
        return devices
    
    def _handle_device_event(self, device_type: str, device_name: str, event: str):
        """Handle device connection/disconnection event"""
        # Check if this is a trigger device
        is_trigger = any(trigger in device_name for trigger in self.trigger_devices.get(device_type, []))
        
        priority = TriggerPriority.HIGH if is_trigger else TriggerPriority.LOW
        
        trigger_event = TriggerEvent(
            trigger_type=TriggerType.EXTERNAL_DEVICE,
            source=f"{device_type}_monitor",
            data={
                "device_type": device_type,
                "device_name": device_name,
                "event": event,
                "is_trigger_device": is_trigger
            },
            priority=priority,
            platform=detect_platform()
        )
        self.callback(trigger_event)

# =============================================================================
# Hardware Trigger Manager
# =============================================================================

class HardwareTriggerManager:
    """
    Central manager for all hardware triggers
    
    Coordinates multiple trigger listeners and routes events to handlers.
    Supports platform-specific trigger detection.
    
    Example:
        >>> config = HardwareTriggerConfig(wake_word="hey ufo")
        >>> manager = HardwareTriggerManager(config)
        >>> manager.on_trigger = lambda event: print(f"Triggered: {event}")
        >>> manager.start_all()
        >>> # ... run for a while ...
        >>> manager.stop_all()
    """
    
    def __init__(self, config: Optional[HardwareTriggerConfig] = None):
        self.config = config or HardwareTriggerConfig()
        self.platform = detect_platform()
        
        # Trigger listeners
        self._listeners: Dict[TriggerType, Any] = {}
        
        # Event handling
        self.on_trigger: Optional[Callable[[TriggerEvent], None]] = None
        self._event_queue: deque = deque(maxlen=1000)
        self._trigger_history: List[TriggerEvent] = []
        self._max_history = 1000
        
        # Statistics
        self._stats = {
            "triggers_received": 0,
            "triggers_by_type": {t.value: 0 for t in TriggerType},
            "start_time": None
        }
        
        # Initialize listeners based on platform
        self._initialize_listeners()
        
        logger.info(f"HardwareTriggerManager initialized for {self.platform.value}")
    
    def _initialize_listeners(self):
        """Initialize platform-appropriate listeners"""
        # Voice trigger (cross-platform)
        if self.config.enable_voice:
            self._listeners[TriggerType.VOICE] = VoiceTriggerListener(
                self.config, self._on_trigger_event
            )
        
        # Platform-specific listeners
        if self.platform == PlatformType.WINDOWS:
            if self.config.enable_hotkey:
                self._listeners[TriggerType.HOTKEY] = WindowsHotkeyListener(
                    self.config, self._on_trigger_event
                )
            if self.config.enable_gesture:
                self._listeners[TriggerType.GESTURE] = WindowsTouchGestureListener(
                    self.config, self._on_trigger_event
                )
                
        elif self.platform == PlatformType.ANDROID:
            if self.config.enable_hardware_key:
                self._listeners[TriggerType.HARDWARE_KEY] = AndroidHardwareKeyListener(
                    self.config, self._on_trigger_event
                )
            if self.config.enable_gesture:
                self._listeners[TriggerType.GESTURE] = AndroidGestureListener(
                    self.config, self._on_trigger_event
                )
        
        # External device monitoring (cross-platform)
        if self.config.enable_external_device:
            self._listeners[TriggerType.EXTERNAL_DEVICE] = ExternalDeviceListener(
                self.config, self._on_trigger_event
            )
    
    def _on_trigger_event(self, event: TriggerEvent):
        """Handle trigger event from any listener"""
        # Add to queue and history
        self._event_queue.append(event)
        self._trigger_history.append(event)
        
        # Update statistics
        self._stats["triggers_received"] += 1
        self._stats["triggers_by_type"][event.trigger_type.value] += 1
        
        # Trim history
        if len(self._trigger_history) > self._max_history:
            self._trigger_history = self._trigger_history[-self._max_history:]
        
        # Log event
        logger.info(f"Trigger: {event.trigger_type.value} from {event.source} (priority: {event.priority.name})")
        
        # Call user callback
        if self.on_trigger:
            try:
                self.on_trigger(event)
            except Exception as e:
                logger.error(f"Trigger callback error: {e}")
    
    def start_all(self) -> Dict[str, bool]:
        """Start all trigger listeners"""
        results = {}
        self._stats["start_time"] = datetime.now()
        
        for trigger_type, listener in self._listeners.items():
            try:
                success = listener.start()
                results[trigger_type.value] = success
                if success:
                    logger.info(f"Started {trigger_type.value} listener")
                else:
                    logger.warning(f"Failed to start {trigger_type.value} listener")
            except Exception as e:
                logger.error(f"Error starting {trigger_type.value} listener: {e}")
                results[trigger_type.value] = False
        
        return results
    
    def stop_all(self):
        """Stop all trigger listeners"""
        for trigger_type, listener in self._listeners.items():
            try:
                listener.stop()
                logger.info(f"Stopped {trigger_type.value} listener")
            except Exception as e:
                logger.error(f"Error stopping {trigger_type.value} listener: {e}")
    
    def start_listener(self, trigger_type: TriggerType) -> bool:
        """Start a specific trigger listener"""
        if trigger_type in self._listeners:
            return self._listeners[trigger_type].start()
        logger.warning(f"No listener registered for {trigger_type.value}")
        return False
    
    def stop_listener(self, trigger_type: TriggerType):
        """Stop a specific trigger listener"""
        if trigger_type in self._listeners:
            self._listeners[trigger_type].stop()
    
    def get_pending_events(self) -> List[TriggerEvent]:
        """Get all pending trigger events"""
        events = list(self._event_queue)
        self._event_queue.clear()
        return events
    
    def get_trigger_history(self, limit: int = 100) -> List[Dict]:
        """Get trigger history"""
        history = self._trigger_history[-limit:]
        return [e.to_dict() for e in history]
    
    def get_statistics(self) -> Dict:
        """Get trigger statistics"""
        stats = dict(self._stats)
        if stats["start_time"]:
            stats["uptime_seconds"] = (datetime.now() - stats["start_time"]).total_seconds()
        return stats
    
    def clear_history(self):
        """Clear trigger history"""
        self._trigger_history.clear()
        self._event_queue.clear()

# =============================================================================
# System State Machine
# =============================================================================

class SystemStateMachine:
    """
    Galaxy System State Machine
    
    Manages transitions between system states:
    - DORMANT: System sleeping, minimal resources
    - ISLAND: Compact UI mode (dynamic island)
    - SIDESHEET: Side panel mode
    - FULLAGENT: Full agent interface
    
    Features:
    - State transition validation
    - Callback hooks for state changes
    - Transition history tracking
    """
    
    # Valid state transitions
    VALID_TRANSITIONS = {
        SystemState.DORMANT: [SystemState.ISLAND, SystemState.SIDESHEET, SystemState.FULLAGENT],
        SystemState.ISLAND: [SystemState.DORMANT, SystemState.SIDESHEET, SystemState.FULLAGENT],
        SystemState.SIDESHEET: [SystemState.DORMANT, SystemState.ISLAND, SystemState.FULLAGENT],
        SystemState.FULLAGENT: [SystemState.DORMANT, SystemState.ISLAND, SystemState.SIDESHEET]
    }
    
    # Default trigger to state mapping
    TRIGGER_STATE_MAP = {
        # Voice triggers
        (TriggerType.VOICE, "vosk_wake_word"): SystemState.ISLAND,
        (TriggerType.VOICE, "vosk_recognizer"): SystemState.FULLAGENT,
        
        # Hotkey triggers
        (TriggerType.HOTKEY, "pynput_hotkey"): SystemState.SIDESHEET,
        
        # Hardware key triggers
        (TriggerType.HARDWARE_KEY, "android_volume_long_press"): SystemState.ISLAND,
        (TriggerType.HARDWARE_KEY, "android_volume_combo"): SystemState.FULLAGENT,
        (TriggerType.HARDWARE_KEY, "android_power_long_press"): SystemState.DORMANT,
        
        # Gesture triggers
        (TriggerType.GESTURE, "android_edge_gesture"): SystemState.SIDESHEET,
        (TriggerType.GESTURE, "android_gesture"): SystemState.ISLAND,
        (TriggerType.GESTURE, "windows_three_finger_swipe_up"): SystemState.FULLAGENT,
        (TriggerType.GESTURE, "windows_four_finger_tap"): SystemState.ISLAND,
        
        # External device triggers
        (TriggerType.EXTERNAL_DEVICE, "bluetooth_monitor"): SystemState.ISLAND,
        (TriggerType.EXTERNAL_DEVICE, "usb_monitor"): SystemState.FULLAGENT
    }
    
    def __init__(self, initial_state: SystemState = SystemState.DORMANT):
        self._state = initial_state
        self._state_lock = threading.RLock()
        
        # Transition history
        self._transition_history: deque = deque(maxlen=100)
        
        # Callbacks
        self._on_enter_callbacks: Dict[SystemState, List[Callable]] = {s: [] for s in SystemState}
        self._on_exit_callbacks: Dict[SystemState, List[Callable]] = {s: [] for s in SystemState}
        self._on_transition_callbacks: List[Callable[[StateTransition], None]] = []
        
        # State data
        self._state_data: Dict[SystemState, Dict] = {s: {} for s in SystemState}
        
        # Statistics
        self._state_entry_count: Dict[SystemState, int] = {s: 0 for s in SystemState}
        self._state_time: Dict[SystemState, float] = {s: 0.0 for s in SystemState}
        self._last_state_change = datetime.now()
        
        logger.info(f"SystemStateMachine initialized in {initial_state.value} state")
    
    @property
    def current_state(self) -> SystemState:
        """Get current system state"""
        with self._state_lock:
            return self._state
    
    @property
    def current_state_data(self) -> Dict:
        """Get data associated with current state"""
        with self._state_lock:
            return dict(self._state_data[self._state])
    
    def can_transition_to(self, new_state: SystemState) -> bool:
        """Check if transition to new state is valid"""
        with self._state_lock:
            return new_state in self.VALID_TRANSITIONS.get(self._state, [])
    
    def transition_to(self, new_state: SystemState, trigger: Optional[TriggerEvent] = None) -> StateTransition:
        """
        Transition to a new state
        
        Args:
            new_state: Target state
            trigger: Optional trigger event that caused the transition
            
        Returns:
            StateTransition record
        """
        with self._state_lock:
            old_state = self._state
            
            # Validate transition
            if not self.can_transition_to(new_state):
                error_msg = f"Invalid transition: {old_state.value} -> {new_state.value}"
                logger.error(error_msg)
                return StateTransition(
                    from_state=old_state,
                    to_state=new_state,
                    trigger=trigger or TriggerEvent(
                        trigger_type=TriggerType.HOTKEY,
                        source="manual_transition",
                        data={}
                    ),
                    success=False,
                    error_message=error_msg
                )
            
            # Update state time tracking
            time_in_state = (datetime.now() - self._last_state_change).total_seconds()
            self._state_time[old_state] += time_in_state
            
            # Execute exit callbacks for old state
            self._execute_callbacks(self._on_exit_callbacks[old_state], old_state)
            
            # Perform transition
            self._state = new_state
            self._last_state_change = datetime.now()
            self._state_entry_count[new_state] += 1
            
            # Execute enter callbacks for new state
            self._execute_callbacks(self._on_enter_callbacks[new_state], new_state)
            
            # Create transition record
            transition = StateTransition(
                from_state=old_state,
                to_state=new_state,
                trigger=trigger or TriggerEvent(
                    trigger_type=TriggerType.HOTKEY,
                    source="manual_transition",
                    data={}
                ),
                success=True
            )
            
            # Store transition
            self._transition_history.append(transition)
            
            # Execute transition callbacks
            for callback in self._on_transition_callbacks:
                try:
                    callback(transition)
                except Exception as e:
                    logger.error(f"Transition callback error: {e}")
            
            logger.info(f"State transition: {old_state.value} -> {new_state.value}")
            
            return transition
    
    def _execute_callbacks(self, callbacks: List[Callable], state: SystemState):
        """Execute callbacks for a state"""
        for callback in callbacks:
            try:
                callback(state)
            except Exception as e:
                logger.error(f"State callback error: {e}")
    
    def on_enter(self, state: SystemState, callback: Callable):
        """Register callback for entering a state"""
        self._on_enter_callbacks[state].append(callback)
    
    def on_exit(self, state: SystemState, callback: Callable):
        """Register callback for exiting a state"""
        self._on_exit_callbacks[state].append(callback)
    
    def on_transition(self, callback: Callable[[StateTransition], None]):
        """Register callback for any state transition"""
        self._on_transition_callbacks.append(callback)
    
    def set_state_data(self, state: SystemState, key: str, value: Any):
        """Set data for a state"""
        with self._state_lock:
            self._state_data[state][key] = value
    
    def get_state_data(self, state: SystemState, key: str, default: Any = None) -> Any:
        """Get data for a state"""
        with self._state_lock:
            return self._state_data[state].get(key, default)
    
    def get_state_from_trigger(self, event: TriggerEvent) -> Optional[SystemState]:
        """Get target state from trigger event"""
        key = (event.trigger_type, event.source)
        
        # Direct mapping
        if key in self.TRIGGER_STATE_MAP:
            return self.TRIGGER_STATE_MAP[key]
        
        # Partial matching
        for (t_type, t_source), state in self.TRIGGER_STATE_MAP.items():
            if event.trigger_type == t_type and t_source in event.source:
                return state
        
        # Default based on trigger type
        type_defaults = {
            TriggerType.VOICE: SystemState.ISLAND,
            TriggerType.HOTKEY: SystemState.SIDESHEET,
            TriggerType.HARDWARE_KEY: SystemState.ISLAND,
            TriggerType.GESTURE: SystemState.ISLAND,
            TriggerType.EXTERNAL_DEVICE: SystemState.FULLAGENT
        }
        
        return type_defaults.get(event.trigger_type)
    
    def get_transition_history(self, limit: int = 50) -> List[Dict]:
        """Get transition history"""
        history = list(self._transition_history)[-limit:]
        return [
            {
                "from": t.from_state.value,
                "to": t.to_state.value,
                "timestamp": t.timestamp.isoformat(),
                "trigger_type": t.trigger.trigger_type.value if t.trigger else None,
                "trigger_source": t.trigger.source if t.trigger else None,
                "success": t.success,
                "error": t.error_message
            }
            for t in history
        ]
    
    def get_statistics(self) -> Dict:
        """Get state machine statistics"""
        with self._state_lock:
            current_time = datetime.now()
            time_in_current = (current_time - self._last_state_change).total_seconds()
            
            return {
                "current_state": self._state.value,
                "state_entry_counts": {s.value: c for s, c in self._state_entry_count.items()},
                "total_time_in_states": {s.value: t for s, t in self._state_time.items()},
                "time_in_current_state": time_in_current,
                "total_transitions": len(self._transition_history)
            }
    
    def reset(self):
        """Reset state machine to initial state"""
        with self._state_lock:
            self._state = SystemState.DORMANT
            self._transition_history.clear()
            self._state_entry_count = {s: 0 for s in SystemState}
            self._state_time = {s: 0.0 for s in SystemState}
            self._last_state_change = datetime.now()
            logger.info("State machine reset to DORMANT")

# =============================================================================
# Integrated System Controller
# =============================================================================

class IntegratedSystemController:
    """
    Integrated System Controller for Galaxy
    
    Coordinates hardware triggers with system state transitions.
    Provides unified interface for trigger-to-state mapping.
    
    Features:
    - Automatic state transitions from triggers
    - Trigger priority handling
    - Multiple trigger coordination
    - State persistence
    
    Example:
        >>> controller = IntegratedSystemController()
        >>> controller.start()
        >>> # System now responds to hardware triggers
        >>> controller.stop()
    """
    
    def __init__(self, config: Optional[HardwareTriggerConfig] = None):
        self.config = config or HardwareTriggerConfig()
        
        # Core components
        self.trigger_manager = HardwareTriggerManager(self.config)
        self.state_machine = SystemStateMachine(SystemState.DORMANT)
        
        # Trigger handling
        self._trigger_queue: deque = deque()
        self._processing_thread: Optional[threading.Thread] = None
        self._running = False
        
        # Priority handling
        self._priority_lock = threading.Lock()
        self._active_high_priority = False
        self._priority_cooldown = 1.0  # seconds
        self._last_high_priority_time = 0
        
        # Custom trigger handlers
        self._custom_handlers: Dict[str, Callable[[TriggerEvent], Optional[SystemState]]] = {}
        
        # Statistics
        self._stats = {
            "triggers_processed": 0,
            "state_transitions": 0,
            "ignored_triggers": 0
        }
        
        # Set up trigger callback
        self.trigger_manager.on_trigger = self._on_trigger_received
        
        # Set up state callbacks
        self._setup_state_callbacks()
        
        logger.info("IntegratedSystemController initialized")
    
    def _setup_state_callbacks(self):
        """Set up state machine callbacks"""
        # Enter DORMANT
        self.state_machine.on_enter(SystemState.DORMANT, self._on_enter_dormant)
        
        # Enter ISLAND
        self.state_machine.on_enter(SystemState.ISLAND, self._on_enter_island)
        
        # Enter SIDESHEET
        self.state_machine.on_enter(SystemState.SIDESHEET, self._on_enter_sidesheet)
        
        # Enter FULLAGENT
        self.state_machine.on_enter(SystemState.FULLAGENT, self._on_enter_fullagent)
        
        # Transition callback
        self.state_machine.on_transition(self._on_state_transition)
    
    def _on_enter_dormant(self, state: SystemState):
        """Called when entering DORMANT state"""
        logger.info("Entering DORMANT state - minimizing resources")
        # Stop non-essential listeners
        if not self.config.enable_voice:
            self.trigger_manager.stop_listener(TriggerType.VOICE)
    
    def _on_enter_island(self, state: SystemState):
        """Called when entering ISLAND state"""
        logger.info("Entering ISLAND state - compact UI mode")
        # Ensure voice listener is active
        if self.config.enable_voice:
            self.trigger_manager.start_listener(TriggerType.VOICE)
    
    def _on_enter_sidesheet(self, state: SystemState):
        """Called when entering SIDESHEET state"""
        logger.info("Entering SIDESHEET state - side panel mode")
    
    def _on_enter_fullagent(self, state: SystemState):
        """Called when entering FULLAGENT state"""
        logger.info("Entering FULLAGENT state - full agent interface")
    
    def _on_state_transition(self, transition: StateTransition):
        """Called on any state transition"""
        self._stats["state_transitions"] += 1
        
        # Notify external systems
        self._notify_transition(transition)
    
    def _notify_transition(self, transition: StateTransition):
        """Notify external systems of state transition"""
        # This could be extended to send notifications to other components
        pass
    
    def _on_trigger_received(self, event: TriggerEvent):
        """Handle trigger event from manager"""
        # Add to processing queue
        self._trigger_queue.append(event)
    
    def _process_triggers(self):
        """Main trigger processing loop"""
        while self._running:
            try:
                # Process pending triggers
                while self._trigger_queue and self._running:
                    event = self._trigger_queue.popleft()
                    self._handle_trigger(event)
                
                time.sleep(0.01)  # 10ms polling interval
                
            except Exception as e:
                logger.error(f"Trigger processing error: {e}")
                time.sleep(0.1)
    
    def _handle_trigger(self, event: TriggerEvent):
        """Handle a single trigger event"""
        self._stats["triggers_processed"] += 1
        
        # Check priority handling
        if not self._should_process_trigger(event):
            self._stats["ignored_triggers"] += 1
            logger.debug(f"Trigger ignored due to priority: {event.trigger_type.value}")
            return
        
        # Check for custom handler
        handler_key = f"{event.trigger_type.value}:{event.source}"
        if handler_key in self._custom_handlers:
            custom_state = self._custom_handlers[handler_key](event)
            if custom_state:
                self._do_transition(custom_state, event)
                return
        
        # Get target state from trigger
        target_state = self.state_machine.get_state_from_trigger(event)
        
        if target_state:
            self._do_transition(target_state, event)
        else:
            logger.debug(f"No state mapping for trigger: {event.trigger_type.value}")
    
    def _should_process_trigger(self, event: TriggerEvent) -> bool:
        """Check if trigger should be processed based on priority"""
        current_time = time.time()
        
        with self._priority_lock:
            # Critical priority always processed
            if event.priority == TriggerPriority.CRITICAL:
                self._active_high_priority = True
                self._last_high_priority_time = current_time
                return True
            
            # High priority during cooldown blocks lower priorities
            if self._active_high_priority:
                if current_time - self._last_high_priority_time > self._priority_cooldown:
                    self._active_high_priority = False
                else:
                    # Block medium and low during high priority cooldown
                    if event.priority in [TriggerPriority.MEDIUM, TriggerPriority.LOW]:
                        return False
            
            # High priority triggers set the cooldown
            if event.priority == TriggerPriority.HIGH:
                self._active_high_priority = True
                self._last_high_priority_time = current_time
            
            return True
    
    def _do_transition(self, target_state: SystemState, trigger: TriggerEvent):
        """Execute state transition"""
        if self.state_machine.can_transition_to(target_state):
            transition = self.state_machine.transition_to(target_state, trigger)
            if transition.success:
                logger.info(f"Transitioned to {target_state.value} via {trigger.trigger_type.value}")
            else:
                logger.warning(f"Transition failed: {transition.error_message}")
        else:
            logger.debug(f"Cannot transition from {self.state_machine.current_state.value} to {target_state.value}")
    
    def register_custom_handler(self, trigger_type: TriggerType, source: str, 
                                 handler: Callable[[TriggerEvent], Optional[SystemState]]):
        """
        Register a custom handler for a specific trigger
        
        Args:
            trigger_type: Type of trigger
            source: Trigger source identifier
            handler: Function that returns target state or None
        """
        key = f"{trigger_type.value}:{source}"
        self._custom_handlers[key] = handler
        logger.info(f"Registered custom handler for {key}")
    
    def start(self) -> Dict[str, Any]:
        """
        Start the integrated controller
        
        Returns:
            Dictionary with start results
        """
        logger.info("Starting IntegratedSystemController")
        
        # Start trigger listeners
        listener_results = self.trigger_manager.start_all()
        
        # Start processing thread
        self._running = True
        self._processing_thread = threading.Thread(target=self._process_triggers, daemon=True)
        self._processing_thread.start()
        
        logger.info("IntegratedSystemController started")
        
        return {
            "success": True,
            "listeners_started": listener_results,
            "initial_state": self.state_machine.current_state.value
        }
    
    def stop(self):
        """Stop the integrated controller"""
        logger.info("Stopping IntegratedSystemController")
        
        self._running = False
        
        if self._processing_thread:
            self._processing_thread.join(timeout=2)
        
        self.trigger_manager.stop_all()
        
        logger.info("IntegratedSystemController stopped")
    
    def force_transition(self, state: SystemState) -> StateTransition:
        """Force a state transition (bypasses validation)"""
        # Temporarily allow all transitions
        old_transitions = SystemStateMachine.VALID_TRANSITIONS.copy()
        SystemStateMachine.VALID_TRANSITIONS = {s: list(SystemState) for s in SystemState}
        
        try:
            transition = self.state_machine.transition_to(state)
            return transition
        finally:
            SystemStateMachine.VALID_TRANSITIONS = old_transitions
    
    def get_status(self) -> Dict[str, Any]:
        """Get current controller status"""
        return {
            "running": self._running,
            "current_state": self.state_machine.current_state.value,
            "trigger_stats": dict(self._stats),
            "trigger_manager_stats": self.trigger_manager.get_statistics(),
            "state_machine_stats": self.state_machine.get_statistics(),
            "pending_triggers": len(self._trigger_queue)
        }
    
    def get_trigger_history(self, limit: int = 50) -> List[Dict]:
        """Get trigger history"""
        return self.trigger_manager.get_trigger_history(limit)
    
    def get_transition_history(self, limit: int = 50) -> List[Dict]:
        """Get state transition history"""
        return self.state_machine.get_transition_history(limit)

# =============================================================================
# Convenience Functions
# =============================================================================

def create_default_controller() -> IntegratedSystemController:
    """Create a controller with default configuration"""
    config = HardwareTriggerConfig()
    return IntegratedSystemController(config)

def quick_start() -> IntegratedSystemController:
    """Quick start the integrated system"""
    controller = create_default_controller()
    controller.start()
    return controller

# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    # Demo mode
    print("=" * 60)
    print("Galaxy Hardware Trigger System")
    print("=" * 60)
    
    # Create and start controller
    controller = quick_start()
    
    print(f"\nPlatform: {detect_platform().value}")
    print(f"Current state: {controller.state_machine.current_state.value}")
    print("\nTrigger types available:")
    
    for trigger_type, listener in controller.trigger_manager._listeners.items():
        status = "✓" if listener else "✗"
        print(f"  {status} {trigger_type.value}")
    
    print("\nListening for triggers... Press Ctrl+C to stop")
    
    try:
        while True:
            time.sleep(1)
            status = controller.get_status()
            print(f"\rState: {status['current_state']} | "
                  f"Triggers: {status['trigger_stats']['triggers_processed']} | "
                  f"Transitions: {status['trigger_stats']['state_transitions']}", 
                  end="", flush=True)
    except KeyboardInterrupt:
        print("\n\nStopping...")
    finally:
        controller.stop()
        print("Stopped.")
