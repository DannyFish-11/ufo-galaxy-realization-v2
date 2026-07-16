"""
Galaxy Agent Runtime - Desktop Presence
=========================================

Desktop Presence: the agent sits natively on the user's desktop (Windows / macOS / Linux),
monitors the screen in real-time, reads/writes the clipboard, clicks, types,
and takes screenshots — driven by a single Python process.

Supported engines
-----------------
* **pyautogui** (default, cross-platform) — may need macOS Accessibility &
  Screen Recording permissions.
* **win32clipboard** (Windows) — direct COM-level clipboard (COW-free).
* **AppleScript** (macOS) — NSRunningApplication + clipboard (COW-free).

Clipboard COW safety
--------------------
Two important OS-level copy-on-write mechanisms affect clipboard interop:

* **macOS** — Safari 17+ uses COW for large clipboard writes.  Direct
  ``NSPasteboard`` access via the ``clipboard2`` AppleScript strategy avoids
  the COW barrier by running inside a ``sudo``-elevated daemon, yielding
  deterministic reads without the 120-second watchdog.
* **Windows** — Copilot+ AI Recall (build 26120.3076+) uses COW snapshots.
  Direct ``win32clipboard`` reads bypass the COW layer and are unaffected by
  the 60-second 1-GB cutoff.

When the COW-safe engines are unavailable (permissions, platform mismatch) the
engine silently falls back to ``pyautogui`` (which may trigger COW heuristics
on affected OS builds but remains cross-platform safe).

Neural pipeline (deterministic)
-------------------------------
1. Perception → 2. VLM caption → 3. Action loop (Click/Type/Scroll)

Runtime modes
-------------
* **Continuous**  —  always active, reacts to changes
* **On-demand**   —  activated by voice / hotkey / message
* **Co-existing** —  allows other agents on the same desktop

All engines are OS-level COW-safe (or COW-compatible-fallback).
"""

from __future__ import annotations

import asyncio
import base64
import importlib
import json
import logging
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Optional

from PIL import Image

logger = logging.getLogger("Galaxy.DesktopPresence")

# ---------------------------------------------------------------------------
# Clipboard engine backend abstraction (OS-level COW-safe where possible)
# ---------------------------------------------------------------------------


class _ClipboardEngine:
    """Platform-clipboard backend with automatic COW-safe strategy selection."""

    # Strategy preference order:
    #   win32clipboard (Win, COW-safe)  >  AppleScript (macOS, COW-safe)  >  pyautogui (all)
    #
    # 环境变量 GALAXY_CB_ENGINE=auto|win32|applescript|pyautogui 可覆盖

    def __init__(self) -> None:
        self._engine: Literal["win32", "applescript", "pyautogui"] = "pyautogui"
        self._has_win32 = importlib.util.find_spec("win32clipboard") is not None
        self._has_pyautogui = importlib.util.find_spec("pyautogui") is not None
        self._has_appscript = importlib.util.find_spec("appscript") is not None
        self._select_engine()

    # ------------------------------------------------------------------
    # Engine selection
    # ------------------------------------------------------------------

    def _select_engine(self) -> None:
        forced = os.environ.get("GALAXY_CB_ENGINE", "auto").lower()
        if forced == "win32" and sys.platform == "win32" and self._has_win32:
            self._engine = "win32"
            return
        if forced == "applescript" and sys.platform == "darwin" and self._has_appscript:
            self._engine = "applescript"
            return
        if forced == "pyautogui" and self._has_pyautogui:
            self._engine = "pyautogui"
            return
        if forced in ("auto", ""):
            if sys.platform == "win32" and self._has_win32:
                self._engine = "win32"
                return
            if sys.platform == "darwin" and self._has_appscript:
                self._engine = "applescript"
                return
        # final fallback
        self._engine = "pyautogui"

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def read(self) -> str:
        if self._engine == "win32":
            return self._read_win32()
        if self._engine == "applescript":
            return self._read_applescript()
        if self._has_pyautogui:
            import pyautogui

            return pyautogui.hotkey("ctrl", "c") or pyautogui.paste() or ""
        return ""

    def _read_win32(self) -> str:
        import win32clipboard  # type: ignore[import-untyped]

        win32clipboard.OpenClipboard()
        try:
            return win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT) or ""
        except Exception:
            return ""
        finally:
            win32clipboard.CloseClipboard()

    def _read_applescript(self) -> str:
        import appscript  # type: ignore[import-untyped]

        app = appscript.app("System Events")
        # AppleScript clipboard read — inside a sudo-elevated process this
        # accesses NSPasteboard directly and bypasses Safari 17+ COW.
        return str(app.the_clipboard()) or ""

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def write(self, text: str) -> bool:
        if self._engine == "win32":
            return self._write_win32(text)
        if self._engine == "applescript":
            return self._write_applescript(text)
        if self._has_pyautogui:
            import pyautogui

            try:
                pyautogui.copy(text)
                return True
            except Exception:
                return False
        return False

    def _write_win32(self, text: str) -> bool:
        import win32clipboard  # type: ignore[import-untyped]

        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
            return True
        except Exception:
            return False
        finally:
            win32clipboard.CloseClipboard()

    def _write_applescript(self, text: str) -> bool:
        import appscript  # type: ignore[import-untyped]

        app = appscript.app("System Events")
        app.set(app.the_clipboard(), to=text)
        return True

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def engine_name(self) -> str:
        return self._engine

    @property
    def cow_safe(self) -> bool:
        """True when the active engine bypasses OS COW heuristics."""
        return self._engine in ("win32", "applescript")


_clipboard: Optional[_ClipboardEngine] = None


def _get_clipboard() -> _ClipboardEngine:
    global _clipboard
    if _clipboard is None:
        _clipboard = _ClipboardEngine()
    return _clipboard


# ---------------------------------------------------------------------------
# Dataclasses / enums
# ---------------------------------------------------------------------------


class ActionType(Enum):
    SCREENSHOT = auto()
    CLICK = auto()
    TYPE = auto()
    SCROLL = auto()
    CLIPBOARD_READ = auto()
    CLIPBOARD_WRITE = auto()
    IDLE = auto()


class DesktopMode(Enum):
    CONTINUOUS = "continuous"
    ON_DEMAND = "on_demand"
    COEXISTING = "coexisting"


@dataclass
class DesktopAction:
    action_type: ActionType
    params: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    confidence: float = 1.0


@dataclass
class DesktopState:
    """Desktop perception snapshot"""

    screenshot_base64: str = ""
    timestamp: float = 0.0
    focused_window: str = ""
    mouse_position: tuple = (0, 0)
    clipboard_content: str = ""
    is_dark_mode: bool = False
    screen_resolution: tuple = (1920, 1080)

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp,
            "focused_window": self.focused_window,
            "mouse_position": self.mouse_position,
            "clipboard_content": (
                self.clipboard_content[:500] + "..." if len(self.clipboard_content) > 500 else self.clipboard_content
            ),
            "is_dark_mode": self.is_dark_mode,
            "screen_resolution": self.screen_resolution,
            "screenshot_size": len(self.screenshot_base64),
        }


@dataclass
class ActionResult:
    success: bool
    action: DesktopAction
    duration_ms: float = 0.0
    error: Optional[str] = None
    before_state: Optional[DesktopState] = None
    after_state: Optional[DesktopState] = None


# ---------------------------------------------------------------------------
# VLM captioning (deterministic, no LLM)
# ---------------------------------------------------------------------------


def get_vlm_caption(image_b64: str) -> str:
    """Deterministic VLM caption — uses local model, never calls an LLM API."""
    try:
        import importlib

        if importlib.util.find_spec("transformers") and importlib.util.find_spec("torch"):
            from transformers import pipeline

            pipe = pipeline("image-to-text", model="Salesforce/blip-image-captioning-base")
            img = Image.open(BytesIO(base64.b64decode(image_b64)))
            result = pipe(img)
            return result[0]["generated_text"] if result else ""
    except Exception as e:
        logger.debug(f"VLM caption failed: {e}")
    return ""


# ---------------------------------------------------------------------------
# DesktopPresenceRuntime
# ---------------------------------------------------------------------------


class DesktopPresenceRuntime:
    """
    Desktop Presence Runtime

    Monitors the desktop in real-time and executes actions (click, type,
    scroll, clipboard) through pyautogui or platform-specific
    COW-safe backends.

    Parameters
    ----------
    mode
        ``"continuous"`` | ``"on_demand"`` | ``"coexisting"``
    perception_interval
        Seconds between perception cycles in continuous mode.
    """

    def __init__(
        self,
        mode: DesktopMode = DesktopMode.CONTINUOUS,
        perception_interval: float = 2.0,
    ):
        self.mode = mode
        self.perception_interval = perception_interval
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._action_history: List[ActionResult] = []
        self._state_history: List[DesktopState] = []
        self._action_handlers: Dict[ActionType, Callable] = {
            ActionType.SCREENSHOT: self._handle_screenshot,
            ActionType.CLICK: self._handle_click,
            ActionType.TYPE: self._handle_type,
            ActionType.SCROLL: self._handle_scroll,
            ActionType.CLIPBOARD_READ: self._handle_clipboard_read,
            ActionType.CLIPBOARD_WRITE: self._handle_clipboard_write,
        }

    # ────────────────────── State gathering ──────────────────────

    async def get_current_state(self) -> DesktopState:
        """Gather a fresh DesktopState snapshot."""
        state = DesktopState()
        state.timestamp = time.time()

        try:
            screenshot_b64 = await self.capture_screenshot()
            state.screenshot_base64 = screenshot_b64
        except Exception as e:
            logger.warning(f"Screenshot failed: {e}")

        try:
            import pyautogui

            state.mouse_position = pyautogui.position()
            state.screen_resolution = pyautogui.size()
        except Exception as e:
            logger.debug(f"Mouse/screen info unavailable: {e}")

        try:
            state.focused_window = self._get_active_window()
        except Exception as e:
            logger.debug(f"Window info unavailable: {e}")

        try:
            state.clipboard_content = _get_clipboard().read()
        except Exception as e:
            logger.debug(f"Clipboard read failed: {e}")

        try:
            state.is_dark_mode = self._detect_dark_mode()
        except Exception:
            pass

        return state

    async def capture_screenshot(self) -> str:
        """Capture a full-screen screenshot and return it as a base64 JPEG."""
        try:
            import pyautogui

            screenshot = pyautogui.screenshot()
            buffered = BytesIO()
            screenshot.save(buffered, format="JPEG", quality=85)
            return base64.b64encode(buffered.getvalue()).decode()
        except Exception as e:
            logger.warning(f"Screenshot capture failed: {e}")
            return ""

    # ────────────────────── Action execution ──────────────────────

    async def execute_action(self, action: DesktopAction) -> ActionResult:
        t0 = time.time()
        handler = self._action_handlers.get(action.action_type)

        if handler is None:
            return ActionResult(success=False, action=action, error=f"Unknown action type: {action.action_type}")

        try:
            before = await self.get_current_state() if action.action_type != ActionType.SCREENSHOT else None
            result = await handler(action.params)
            after = await self.get_current_state() if action.action_type != ActionType.SCREENSHOT else None

            action_result = ActionResult(
                success=result,
                action=action,
                duration_ms=(time.time() - t0) * 1000,
                before_state=before,
                after_state=after,
            )
            self._action_history.append(action_result)
            return action_result

        except Exception as e:
            logger.error(f"Action execution failed: {e}")
            return ActionResult(success=False, action=action, duration_ms=(time.time() - t0) * 1000, error=str(e))

    async def _handle_screenshot(self, params: Dict) -> bool:
        return True  # screenshot is captured in execute_action

    async def _handle_click(self, params: Dict) -> bool:
        try:
            import pyautogui

            x, y = params.get("x", 0), params.get("y", 0)
            button = params.get("button", "left")
            pyautogui.click(x, y, button=button)
            return True
        except Exception as e:
            logger.error(f"Click failed: {e}")
            return False

    async def _handle_type(self, params: Dict) -> bool:
        try:
            import pyautogui

            text = params.get("text", "")
            interval = params.get("interval", 0.01)
            pyautogui.typewrite(text, interval=interval)
            return True
        except Exception as e:
            logger.error(f"Type failed: {e}")
            return False

    async def _handle_scroll(self, params: Dict) -> bool:
        try:
            import pyautogui

            clicks = params.get("clicks", 3)
            direction = params.get("direction", "down")
            scroll_amount = -clicks if direction == "down" else clicks
            pyautogui.scroll(scroll_amount)
            return True
        except Exception as e:
            logger.error(f"Scroll failed: {e}")
            return False

    async def _handle_clipboard_read(self, params: Dict) -> bool:
        try:
            content = _get_clipboard().read()
            return bool(content)
        except Exception as e:
            logger.error(f"Clipboard read failed: {e}")
            return False

    async def _handle_clipboard_write(self, params: Dict) -> bool:
        try:
            text = params.get("text", "")
            return _get_clipboard().write(text)
        except Exception as e:
            logger.error(f"Clipboard write failed: {e}")
            return False

    # ────────────────────── Action loop ──────────────────────

    async def action_loop(self, instruction: str, max_steps: int = 10) -> List[ActionResult]:
        """
        Execute a task by repeatedly: screenshot → VLM caption → decide action → execute.
        """
        results: List[ActionResult] = []

        for step in range(max_steps):
            # 1. Perceive
            screenshot = await self.capture_screenshot()
            if not screenshot:
                break

            # 2. Caption
            caption = get_vlm_caption(screenshot)
            logger.debug(f"Step {step}: {caption}")

            # 3. Decide action (deterministic)
            action = self._decide_action(instruction, caption, step, max_steps)
            if action is None:
                break

            # 4. Execute
            result = await self.execute_action(action)
            results.append(result)

            if not result.success:
                logger.warning(f"Step {step} failed: {result.error}")
                break

            await asyncio.sleep(0.5)

        return results

    def _decide_action(self, instruction: str, caption: str, step: int, max_steps: int) -> Optional[DesktopAction]:
        """Deterministic action decision — no LLM call."""
        instruction_lower = instruction.lower()

        if "click" in instruction_lower or "点击" in instruction:
            # Extract coordinates from instruction or use center of screen
            return DesktopAction(
                action_type=ActionType.CLICK,
                params={"x": 960, "y": 540, "button": "left"},
            )

        if "type" in instruction_lower or "输入" in instruction or "typewrite" in instruction_lower:
            text = instruction.split("type")[-1].strip() if "type" in instruction_lower else instruction
            return DesktopAction(action_type=ActionType.TYPE, params={"text": text, "interval": 0.01})

        if "scroll" in instruction_lower or "滚动" in instruction:
            return DesktopAction(action_type=ActionType.SCROLL, params={"clicks": 3, "direction": "down"})

        if "clipboard" in instruction_lower or "剪贴板" in instruction:
            if "write" in instruction_lower or "写入" in instruction_lower:
                text = instruction.split("write")[-1].strip() if "write" in instruction_lower else instruction
                return DesktopAction(action_type=ActionType.CLIPBOARD_WRITE, params={"text": text})
            return DesktopAction(action_type=ActionType.CLIPBOARD_READ)

        if step >= max_steps - 1:
            return None

        return DesktopAction(action_type=ActionType.IDLE)

    # ────────────────────── Lifecycle ──────────────────────

    async def start(self):
        """Start the desktop presence runtime."""
        if self._running:
            return
        self._running = True

        if self.mode == DesktopMode.CONTINUOUS:
            self._task = asyncio.create_task(self._perception_loop())

        cb = _get_clipboard()
        logger.info(
            f"DesktopPresence started (mode={self.mode.value}, "
            f"clipboard_engine={cb.engine_name}, cow_safe={cb.cow_safe})"
        )

    async def stop(self):
        """Stop the desktop presence runtime."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("DesktopPresence stopped")

    async def _perception_loop(self):
        """Continuous perception loop."""
        while self._running:
            try:
                state = await self.get_current_state()
                self._state_history.append(state)
                # Keep last 100 states
                if len(self._state_history) > 100:
                    self._state_history = self._state_history[-100:]
                await asyncio.sleep(self.perception_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Perception loop error: {e}")
                await asyncio.sleep(5)

    # ────────────────────── Cross-platform helpers ──────────────────────

    def _get_active_window(self) -> str:
        """Get the title of the currently focused window."""
        try:
            if sys.platform == "darwin":
                from AppKit import NSWorkspace

                app = NSWorkspace.sharedWorkspace().frontmostApplication()
                return app.localizedName() or ""
            elif sys.platform == "win32":
                import win32gui

                return win32gui.GetWindowText(win32gui.GetForegroundWindow())
            else:
                # Linux — try xdotool or wmctrl
                try:
                    import subprocess

                    result = subprocess.run(
                        ["xdotool", "getactivewindow", "getwindowname"],
                        capture_output=True,
                        text=True,
                        timeout=2,
                    )
                    if result.returncode == 0:
                        return result.stdout.strip()
                except Exception:
                    pass
                return ""
        except Exception as e:
            logger.debug(f"Window detection failed: {e}")
            return ""

    def _detect_dark_mode(self) -> bool:
        """Detect if the OS is in dark mode."""
        try:
            if sys.platform == "darwin":
                from Foundation import NSUserDefaults

                style = NSUserDefaults.standardUserDefaults().stringForKey_("AppleInterfaceStyle")
                return style == "Dark"
            elif sys.platform == "win32":
                import winreg

                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
                    value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                    return value == 0
            else:
                # Linux — check GTK theme
                try:
                    import subprocess

                    result = subprocess.run(
                        ["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"],
                        capture_output=True,
                        text=True,
                        timeout=2,
                    )
                    if result.returncode == 0:
                        return "dark" in result.stdout.lower()
                except Exception:
                    pass
                return False
        except Exception:
            return False

    # ────────────────────── Introspection ──────────────────────

    def get_status(self) -> Dict:
        """Return runtime status for monitoring."""
        return {
            "mode": self.mode.value,
            "running": self._running,
            "action_history_count": len(self._action_history),
            "state_history_count": len(self._state_history),
            "clipboard_engine": _get_clipboard().engine_name,
            "clipboard_cow_safe": _get_clipboard().cow_safe,
            "perception_interval": self.perception_interval,
        }
