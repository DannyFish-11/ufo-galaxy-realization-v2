"""
AIP v3.0 Canonical Action Vocabulary
======================================

Defines the normalized :class:`ActionType` enum, per-action Pydantic payload
schemas, payload validation, and the *legacy action name map* used exclusively
by the shim layer.

Design rules
------------
* **Only this module** is allowed to define canonical action names.
* **Only** :mod:`galaxy_gateway.protocol.compat` is allowed to reference
  :data:`LEGACY_ACTION_MAP` for alias resolution.  The canonical path
  (:mod:`galaxy_gateway.protocol.aip_v3` and all downstream handlers) must
  never branch on legacy names.
* Per-action payload schemas enforce field consistency (coordinates, text,
  selectors) across all action types.

Usage
-----
Validating an incoming action payload::

    from galaxy_gateway.protocol.actions import validate_action_payload

    ok, err = validate_action_payload("click", {"x": 100, "y": 200})
    # ok=True, err=None

    ok, err = validate_action_payload("tap", {"x": 100, "y": 200})
    # "tap" is resolved via LEGACY_ACTION_MAP → "click"; same result

    ok, err = validate_action_payload("click", {})
    # ok=False, err="Invalid payload for action 'click': ..."

Normalising a legacy action name::

    from galaxy_gateway.protocol.actions import normalize_action_name

    normalize_action_name("tap")        # "click"
    normalize_action_name("input_text") # "type"
    normalize_action_name("click")      # "click"  (already canonical)
    normalize_action_name("unknown")    # "unknown" (pass-through)
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional, Tuple, Type, Union

from pydantic import BaseModel, Field, model_validator


# ============================================================================
# Canonical action vocabulary
# ============================================================================

class ActionType(str, Enum):
    """Canonical AIP v3 action vocabulary.

    New code **must** use these names when populating
    :attr:`~galaxy_gateway.protocol.aip_v3.Command.tool_name` for GUI and
    system-level actions.

    The legacy alias map (:data:`LEGACY_ACTION_MAP`) in this module is the
    single permitted source of legacy → canonical mapping and is only accessed
    by the shim layer.
    """

    # --- Input actions ---
    CLICK = "click"               # point-and-click at (x, y) or element
    LONG_PRESS = "long_press"     # long-press at (x, y) or element
    SWIPE = "swipe"               # swipe from (x1, y1) to (x2, y2)
    SCROLL = "scroll"             # scroll at (x, y) in a direction / by delta
    TYPE = "type"                 # type text via keyboard input
    KEY_PRESS = "key_press"       # press a key by keycode or name

    # --- Screen actions ---
    SCREENSHOT = "screenshot"     # capture the current screen

    # --- App / system actions ---
    APP_LAUNCH = "app_launch"     # open an app by package or friendly name
    APP_STOP = "app_stop"         # force-stop an app
    SHELL = "shell"               # run an arbitrary shell command

    # --- Clipboard ---
    SET_CLIPBOARD = "set_clipboard"
    GET_CLIPBOARD = "get_clipboard"

    # --- Navigation ---
    BACK = "back"
    HOME = "home"
    RECENT_APPS = "recent_apps"
    WAKE_SCREEN = "wake_screen"
    LOCK_SCREEN = "lock_screen"

    # --- Volume ---
    VOLUME_UP = "volume_up"
    VOLUME_DOWN = "volume_down"

    # --- UI element query ---
    UI_QUERY = "ui_query"         # query the UI element tree

    # --- Install / packages ---
    INSTALL_APK = "install_apk"
    LIST_PACKAGES = "list_packages"


# ============================================================================
# Legacy alias → canonical ActionType  (SHIM-ONLY)
# ============================================================================

#: Mapping from legacy / alternative action name strings to their canonical
#: :class:`ActionType`.  This dict is the **single** permitted home for
#: legacy action aliases.  It is consumed only by
#: :func:`normalize_action_name` and the shim helpers in
#: :mod:`galaxy_gateway.protocol.compat`.
LEGACY_ACTION_MAP: Dict[str, ActionType] = {
    # click aliases
    "tap": ActionType.CLICK,
    # type / text input aliases
    "input_text": ActionType.TYPE,
    "input": ActionType.TYPE,
    "type_text": ActionType.TYPE,
    # screenshot aliases
    "screen_capture": ActionType.SCREENSHOT,
    "capture_screen": ActionType.SCREENSHOT,
    # app launch aliases
    "open_app": ActionType.APP_LAUNCH,
    "launch_app": ActionType.APP_LAUNCH,
    "start_app": ActionType.APP_LAUNCH,
    # key press aliases  (ADB-style names)
    "keyevent": ActionType.KEY_PRESS,
    "key_event": ActionType.KEY_PRESS,
    "press_key": ActionType.KEY_PRESS,
    # shell alias
    "device_info": ActionType.SHELL,
    # package list alias
    "list_pkg": ActionType.LIST_PACKAGES,
    "get_packages": ActionType.LIST_PACKAGES,
}


# ============================================================================
# Per-action payload schemas
# ============================================================================

class ClickPayload(BaseModel):
    """Payload schema for :attr:`ActionType.CLICK` and
    :attr:`ActionType.LONG_PRESS`.

    At least one of (``x`` + ``y``), ``element_id``, or ``selector`` must be
    provided.
    """

    x: Optional[int] = None
    y: Optional[int] = None
    element_id: Optional[str] = None
    selector: Optional[str] = None    # e.g. resource-id or XPath

    @model_validator(mode="after")
    def _require_target(self) -> "ClickPayload":
        if self.x is None and self.element_id is None and self.selector is None:
            raise ValueError(
                "click/long_press requires 'x'/'y' coordinates, "
                "'element_id', or 'selector'"
            )
        return self


class SwipePayload(BaseModel):
    """Payload schema for :attr:`ActionType.SWIPE`."""

    x1: int
    y1: int
    x2: int
    y2: int
    duration_ms: int = Field(default=300, ge=0)


class ScrollPayload(BaseModel):
    """Payload schema for :attr:`ActionType.SCROLL`."""

    x: int
    y: int
    direction: str = Field(default="down")  # up / down / left / right
    delta: int = Field(default=300, ge=0)   # pixel delta or step count


class TypePayload(BaseModel):
    """Payload schema for :attr:`ActionType.TYPE`."""

    text: str
    element_id: Optional[str] = None
    selector: Optional[str] = None
    clear_first: bool = False


class KeyPressPayload(BaseModel):
    """Payload schema for :attr:`ActionType.KEY_PRESS`."""

    keycode: Union[int, str]   # integer keycode OR named key ("ENTER", "BACK", …)


class ScreenshotPayload(BaseModel):
    """Payload schema for :attr:`ActionType.SCREENSHOT`."""

    format: str = "jpeg"
    quality: int = Field(default=80, ge=1, le=100)


class AppLaunchPayload(BaseModel):
    """Payload schema for :attr:`ActionType.APP_LAUNCH`."""

    package: Optional[str] = None
    app_name: Optional[str] = None
    activity: Optional[str] = None

    @model_validator(mode="after")
    def _require_package_or_name(self) -> "AppLaunchPayload":
        if not self.package and not self.app_name:
            raise ValueError("app_launch requires 'package' or 'app_name'")
        return self


class ShellPayload(BaseModel):
    """Payload schema for :attr:`ActionType.SHELL`."""

    command: str
    timeout_ms: int = Field(default=5000, ge=0)


class ClipboardPayload(BaseModel):
    """Payload schema for :attr:`ActionType.SET_CLIPBOARD`."""

    text: str


# Map from ActionType → Pydantic payload schema class.
# Actions without a registered schema are accepted with any payload (no-op
# validation).
_ACTION_PAYLOAD_SCHEMAS: Dict[ActionType, Type[BaseModel]] = {
    ActionType.CLICK: ClickPayload,
    ActionType.LONG_PRESS: ClickPayload,
    ActionType.SWIPE: SwipePayload,
    ActionType.SCROLL: ScrollPayload,
    ActionType.TYPE: TypePayload,
    ActionType.KEY_PRESS: KeyPressPayload,
    ActionType.SCREENSHOT: ScreenshotPayload,
    ActionType.APP_LAUNCH: AppLaunchPayload,
    ActionType.SHELL: ShellPayload,
    ActionType.SET_CLIPBOARD: ClipboardPayload,
}


# ============================================================================
# Public helpers
# ============================================================================

def normalize_action_name(action: str) -> str:
    """Return the canonical :class:`ActionType` string for *action*.

    Legacy aliases are resolved via :data:`LEGACY_ACTION_MAP`.  If *action*
    is already canonical (or unknown), it is returned unchanged.

    :param action: Action name string (canonical or legacy alias).
    :returns: Canonical action name string.

    Examples::

        normalize_action_name("tap")        # → "click"
        normalize_action_name("input_text") # → "type"
        normalize_action_name("click")      # → "click"
        normalize_action_name("unknown")    # → "unknown"
    """
    canonical = LEGACY_ACTION_MAP.get(action)
    if canonical is not None:
        return canonical.value
    return action


def validate_action_payload(
    action: str,
    payload: Dict[str, Any],
) -> Tuple[bool, Optional[str]]:
    """Validate *payload* against the canonical schema for *action*.

    Legacy aliases in *action* are resolved automatically via
    :func:`normalize_action_name` before schema lookup.

    :param action: Action name string (canonical or legacy alias).
    :param payload: Dict of payload fields to validate.
    :returns: ``(True, None)`` on success.
              ``(False, error_message)`` when validation fails.

    Examples::

        ok, err = validate_action_payload("click", {"x": 10, "y": 20})
        # ok=True, err=None

        ok, err = validate_action_payload("click", {})
        # ok=False, err="Invalid payload for action 'click': ..."

        ok, err = validate_action_payload("tap", {"x": 10, "y": 20})
        # "tap" resolved to "click"; ok=True, err=None
    """
    canonical_str = normalize_action_name(action)
    try:
        action_type = ActionType(canonical_str)
    except ValueError:
        # Unknown action — no schema registered, pass-through
        return True, None

    schema_cls = _ACTION_PAYLOAD_SCHEMAS.get(action_type)
    if schema_cls is None:
        # No schema for this action — no-op validation
        return True, None

    try:
        schema_cls.model_validate(payload)
        return True, None
    except Exception as exc:
        return False, f"Invalid payload for action '{canonical_str}': {exc}"


def get_payload_schema(action: str) -> Optional[Type[BaseModel]]:
    """Return the Pydantic payload schema class for *action*, or ``None``.

    Legacy aliases are resolved.  Returns ``None`` for unknown or
    schema-less actions.
    """
    canonical_str = normalize_action_name(action)
    try:
        action_type = ActionType(canonical_str)
    except ValueError:
        return None
    return _ACTION_PAYLOAD_SCHEMAS.get(action_type)
