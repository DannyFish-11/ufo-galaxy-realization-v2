"""
tests/test_aip_v3_actions.py
=============================

Tests for PR-6: AIP v3 canonical action vocabulary, payload validation,
legacy alias normalization, and the validate_message tuple contract.

Coverage:
1. ActionType enum completeness and values
2. LEGACY_ACTION_MAP — every alias resolves to a canonical ActionType
3. normalize_action_name() — canonical pass-through, alias resolution, unknown
4. validate_action_payload() — valid payloads, invalid payloads, legacy aliases
5. Per-action payload schema validation
6. validate_message() — now returns (bool, Optional[str]) tuple
7. create_gui_scroll_message() factory helper
8. normalize_action_in_payload() shim — top-level "command" and "commands" list
9. __init__.py exports include all new symbols
"""

from __future__ import annotations

import pytest

from galaxy_gateway.protocol.actions import (
    ActionType,
    AppLaunchPayload,
    ClickPayload,
    ClipboardPayload,
    KeyPressPayload,
    LEGACY_ACTION_MAP,
    ScrollPayload,
    ScreenshotPayload,
    ShellPayload,
    SwipePayload,
    TypePayload,
    get_payload_schema,
    normalize_action_name,
    validate_action_payload,
)
from galaxy_gateway.protocol.aip_v3 import (
    AIPMessage,
    MessageType,
    create_gui_scroll_message,
    validate_message,
)
from galaxy_gateway.protocol.compat import normalize_action_in_payload


# ============================================================================
# 1. ActionType enum
# ============================================================================

class TestActionTypeEnum:
    """ActionType enum must cover the full canonical vocabulary."""

    def test_canonical_values_present(self):
        expected = {
            "click", "long_press", "swipe", "scroll", "type", "key_press",
            "screenshot", "app_launch", "app_stop", "shell",
            "set_clipboard", "get_clipboard",
            "back", "home", "recent_apps", "wake_screen", "lock_screen",
            "volume_up", "volume_down",
            "ui_query", "install_apk", "list_packages",
        }
        actual = {a.value for a in ActionType}
        missing = expected - actual
        assert not missing, f"ActionType is missing: {missing}"

    def test_action_type_is_str_enum(self):
        assert ActionType.CLICK == "click"
        assert ActionType.TYPE == "type"
        assert ActionType.SCROLL == "scroll"


# ============================================================================
# 2. LEGACY_ACTION_MAP completeness
# ============================================================================

class TestLegacyActionMap:
    """Every entry in LEGACY_ACTION_MAP must map to a valid ActionType."""

    def test_all_values_are_action_types(self):
        for alias, canonical in LEGACY_ACTION_MAP.items():
            assert isinstance(canonical, ActionType), (
                f"LEGACY_ACTION_MAP[{alias!r}] is {canonical!r}, not ActionType"
            )

    @pytest.mark.parametrize("alias,expected", [
        ("tap", ActionType.CLICK),
        ("input_text", ActionType.TYPE),
        ("input", ActionType.TYPE),
        ("screen_capture", ActionType.SCREENSHOT),
        ("open_app", ActionType.APP_LAUNCH),
        ("launch_app", ActionType.APP_LAUNCH),
        ("keyevent", ActionType.KEY_PRESS),
        ("key_event", ActionType.KEY_PRESS),
        ("device_info", ActionType.SHELL),
        ("list_pkg", ActionType.LIST_PACKAGES),
    ])
    def test_known_alias(self, alias, expected):
        assert LEGACY_ACTION_MAP[alias] == expected


# ============================================================================
# 3. normalize_action_name()
# ============================================================================

class TestNormalizeActionName:
    """normalize_action_name must resolve aliases and pass through unknowns."""

    @pytest.mark.parametrize("alias,canonical", [
        ("tap", "click"),
        ("input_text", "type"),
        ("input", "type"),
        ("screen_capture", "screenshot"),
        ("open_app", "app_launch"),
        ("keyevent", "key_press"),
        ("key_event", "key_press"),
    ])
    def test_alias_resolved(self, alias, canonical):
        assert normalize_action_name(alias) == canonical

    @pytest.mark.parametrize("canonical", [
        "click", "type", "scroll", "swipe", "screenshot", "app_launch",
        "shell", "long_press", "key_press",
    ])
    def test_canonical_pass_through(self, canonical):
        assert normalize_action_name(canonical) == canonical

    def test_unknown_action_pass_through(self):
        assert normalize_action_name("completely_unknown_action") == "completely_unknown_action"

    def test_empty_string_pass_through(self):
        assert normalize_action_name("") == ""


# ============================================================================
# 4. validate_action_payload() — overall contract
# ============================================================================

class TestValidateActionPayload:
    """validate_action_payload must return (bool, Optional[str])."""

    def test_returns_tuple(self):
        result = validate_action_payload("click", {"x": 1, "y": 2})
        assert isinstance(result, tuple) and len(result) == 2

    def test_valid_click_returns_true(self):
        ok, err = validate_action_payload("click", {"x": 100, "y": 200})
        assert ok is True
        assert err is None

    def test_invalid_click_returns_false_with_message(self):
        # Missing all three targets (x/y, element_id, selector)
        ok, err = validate_action_payload("click", {})
        assert ok is False
        assert err is not None
        assert "click" in err

    def test_alias_resolved_before_validation(self):
        # "tap" is a legacy alias for "click"
        ok, err = validate_action_payload("tap", {"x": 5, "y": 10})
        assert ok is True
        assert err is None

    def test_unknown_action_passes(self):
        ok, err = validate_action_payload("totally_unknown", {"any": "field"})
        assert ok is True
        assert err is None

    def test_action_without_schema_passes(self):
        # ActionType.BACK has no registered schema
        ok, err = validate_action_payload("back", {})
        assert ok is True
        assert err is None

    def test_valid_type_payload(self):
        ok, err = validate_action_payload("type", {"text": "hello world"})
        assert ok is True

    def test_invalid_type_payload_missing_text(self):
        ok, err = validate_action_payload("type", {})
        assert ok is False
        assert err is not None

    def test_valid_scroll_payload(self):
        ok, err = validate_action_payload(
            "scroll", {"x": 500, "y": 900, "direction": "up"}
        )
        assert ok is True

    def test_valid_swipe_payload(self):
        ok, err = validate_action_payload(
            "swipe", {"x1": 0, "y1": 100, "x2": 0, "y2": 500}
        )
        assert ok is True

    def test_invalid_swipe_missing_coords(self):
        ok, err = validate_action_payload("swipe", {"x1": 0})
        assert ok is False

    def test_valid_app_launch_by_package(self):
        ok, err = validate_action_payload(
            "app_launch", {"package": "com.example.app"}
        )
        assert ok is True

    def test_valid_app_launch_by_name(self):
        ok, err = validate_action_payload(
            "app_launch", {"app_name": "Chrome"}
        )
        assert ok is True

    def test_invalid_app_launch_no_target(self):
        ok, err = validate_action_payload("app_launch", {})
        assert ok is False

    def test_valid_shell_payload(self):
        ok, err = validate_action_payload("shell", {"command": "ls -la"})
        assert ok is True

    def test_invalid_shell_missing_command(self):
        ok, err = validate_action_payload("shell", {})
        assert ok is False

    def test_valid_key_press_integer(self):
        ok, err = validate_action_payload("key_press", {"keycode": 4})
        assert ok is True

    def test_valid_key_press_string(self):
        ok, err = validate_action_payload("key_press", {"keycode": "ENTER"})
        assert ok is True

    def test_valid_screenshot_defaults(self):
        ok, err = validate_action_payload("screenshot", {})
        assert ok is True

    def test_valid_set_clipboard(self):
        ok, err = validate_action_payload("set_clipboard", {"text": "hello"})
        assert ok is True

    def test_invalid_set_clipboard_missing_text(self):
        ok, err = validate_action_payload("set_clipboard", {})
        assert ok is False


# ============================================================================
# 5. Per-action payload schemas — direct construction
# ============================================================================

class TestPayloadSchemas:
    """Pydantic payload schemas validate required fields correctly."""

    def test_click_requires_target(self):
        with pytest.raises(Exception):
            ClickPayload()  # no target at all

    def test_click_accepts_xy(self):
        p = ClickPayload(x=10, y=20)
        assert p.x == 10 and p.y == 20

    def test_click_accepts_element_id(self):
        p = ClickPayload(element_id="btn_ok")
        assert p.element_id == "btn_ok"

    def test_click_accepts_selector(self):
        p = ClickPayload(selector="//button[@id='ok']")
        assert p.selector is not None

    def test_swipe_all_required(self):
        p = SwipePayload(x1=0, y1=0, x2=100, y2=200)
        assert p.duration_ms == 300  # default

    def test_scroll_defaults(self):
        p = ScrollPayload(x=500, y=900)
        assert p.direction == "down"
        assert p.delta == 300

    def test_type_requires_text(self):
        with pytest.raises(Exception):
            TypePayload()

    def test_type_text(self):
        p = TypePayload(text="hello")
        assert p.text == "hello"
        assert p.clear_first is False

    def test_screenshot_quality_bounds(self):
        with pytest.raises(Exception):
            ScreenshotPayload(quality=0)
        with pytest.raises(Exception):
            ScreenshotPayload(quality=101)

    def test_app_launch_requires_package_or_name(self):
        with pytest.raises(Exception):
            AppLaunchPayload()

    def test_app_launch_package_ok(self):
        p = AppLaunchPayload(package="com.test")
        assert p.package == "com.test"

    def test_shell_requires_command(self):
        with pytest.raises(Exception):
            ShellPayload()

    def test_clipboard_requires_text(self):
        with pytest.raises(Exception):
            ClipboardPayload()

    def test_key_press_int(self):
        p = KeyPressPayload(keycode=4)
        assert p.keycode == 4

    def test_key_press_str(self):
        p = KeyPressPayload(keycode="BACK")
        assert p.keycode == "BACK"


# ============================================================================
# 6. validate_message() — tuple return contract
# ============================================================================

class TestValidateMessage:
    """validate_message must return (bool, Optional[str]) tuple."""

    def test_valid_message_returns_true_none(self):
        msg = AIPMessage(
            type=MessageType.DEVICE_REGISTER,
            device_id="dev-001",
        )
        result = validate_message(msg)
        assert isinstance(result, tuple) and len(result) == 2
        ok, err = result
        assert ok is True
        assert err is None

    def test_empty_device_id_fails(self):
        msg = AIPMessage.__new__(AIPMessage)
        # Build without pydantic validation to inject bad device_id
        object.__setattr__(msg, "device_id", "")
        object.__setattr__(msg, "type", MessageType.DEVICE_REGISTER)
        object.__setattr__(msg, "version", "3.0")
        ok, err = validate_message(msg)
        assert ok is False
        assert err is not None

    def test_unpacking_works(self):
        """Ensure tuple unpacking pattern (used in test_gateway_v3) works."""
        msg = AIPMessage(
            type=MessageType.DEVICE_HEARTBEAT,
            device_id="dev-002",
        )
        ok, error = validate_message(msg)
        assert ok
        assert error is None


# ============================================================================
# 7. create_gui_scroll_message()
# ============================================================================

class TestCreateGuiScrollMessage:
    """create_gui_scroll_message factory must produce a valid v3 AIPMessage."""

    def test_basic_scroll(self):
        msg = create_gui_scroll_message("dev-001", x=100, y=800)
        assert msg.type == MessageType.GUI_SCROLL
        assert msg.device_id == "dev-001"
        assert msg.payload["x"] == 100
        assert msg.payload["y"] == 800
        assert msg.payload["direction"] == "down"
        assert msg.payload["delta"] == 300

    def test_custom_direction_and_delta(self):
        msg = create_gui_scroll_message("dev-002", x=0, y=0, direction="up", delta=500)
        assert msg.payload["direction"] == "up"
        assert msg.payload["delta"] == 500

    def test_task_id_carried(self):
        msg = create_gui_scroll_message("dev-003", x=0, y=0, task_id="task-xyz")
        assert msg.task_id == "task-xyz"

    def test_validate_message_passes(self):
        msg = create_gui_scroll_message("dev-004", x=50, y=50)
        ok, err = validate_message(msg)
        assert ok is True
        assert err is None


# ============================================================================
# 8. normalize_action_in_payload() shim
# ============================================================================

class TestNormalizeActionInPayload:
    """normalize_action_in_payload must resolve legacy names in payload dicts."""

    def test_top_level_command_resolved(self):
        payload = {"command": "tap", "params": {"x": 10, "y": 20}}
        out = normalize_action_in_payload(payload)
        assert out["command"] == "click"
        assert out["params"] == {"x": 10, "y": 20}

    def test_canonical_command_unchanged(self):
        payload = {"command": "click", "params": {}}
        out = normalize_action_in_payload(payload)
        assert out["command"] == "click"

    def test_commands_list_tool_names_resolved(self):
        payload = {
            "commands": [
                {"tool_name": "tap", "parameters": {}},
                {"tool_name": "input_text", "parameters": {"text": "hi"}},
                {"tool_name": "screenshot", "parameters": {}},
            ]
        }
        out = normalize_action_in_payload(payload)
        tool_names = [c["tool_name"] for c in out["commands"]]
        assert tool_names == ["click", "type", "screenshot"]

    def test_commands_list_non_dict_items_preserved(self):
        payload = {"commands": ["not_a_dict", 42, None]}
        out = normalize_action_in_payload(payload)
        assert out["commands"] == ["not_a_dict", 42, None]

    def test_payload_not_mutated(self):
        original = {"command": "tap"}
        _ = normalize_action_in_payload(original)
        assert original["command"] == "tap"  # original must be unchanged

    def test_payload_without_command_key(self):
        payload = {"some_key": "some_value"}
        out = normalize_action_in_payload(payload)
        assert out == {"some_key": "some_value"}

    def test_empty_payload(self):
        out = normalize_action_in_payload({})
        assert out == {}


# ============================================================================
# 9. __init__.py exports
# ============================================================================

class TestProtocolPackageExports:
    """The galaxy_gateway.protocol package must export all new symbols."""

    def test_action_type_exported(self):
        from galaxy_gateway.protocol import ActionType  # noqa: F401

    def test_normalize_action_name_exported(self):
        from galaxy_gateway.protocol import normalize_action_name  # noqa: F401

    def test_validate_action_payload_exported(self):
        from galaxy_gateway.protocol import validate_action_payload  # noqa: F401

    def test_normalize_action_in_payload_exported(self):
        from galaxy_gateway.protocol import normalize_action_in_payload  # noqa: F401

    def test_create_gui_scroll_message_exported(self):
        from galaxy_gateway.protocol import create_gui_scroll_message  # noqa: F401

    def test_get_payload_schema_exported(self):
        from galaxy_gateway.protocol import get_payload_schema  # noqa: F401

    def test_payload_schema_classes_exported(self):
        from galaxy_gateway.protocol import (  # noqa: F401
            ClickPayload, SwipePayload, ScrollPayload, TypePayload,
            KeyPressPayload, ScreenshotPayload, AppLaunchPayload,
            ShellPayload, ClipboardPayload,
        )

    def test_legacy_action_map_exported(self):
        from galaxy_gateway.protocol import LEGACY_ACTION_MAP  # noqa: F401

    def test_validate_message_still_exported(self):
        from galaxy_gateway.protocol import validate_message  # noqa: F401
