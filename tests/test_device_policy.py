"""
tests/test_device_policy.py
============================
Unit tests for :mod:`core.device_policy`.

Verifies:
  1.  All physical/electronic device types are correctly classified.
  2.  Non-physical targets return False.
  3.  Case-insensitivity of the helpers.
  4.  Edge cases (None, empty string).
  5.  requires_agent_deploy mirrors is_physical_device.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.device_policy import (  # noqa: E402
    PHYSICAL_DEVICE_TYPES,
    is_physical_device,
    requires_agent_deploy,
)


# ---------------------------------------------------------------------------
# is_physical_device
# ---------------------------------------------------------------------------

class TestIsPhysicalDevice:
    @pytest.mark.parametrize("device_type", [
        "android", "ANDROID", "Android",
        "ios", "IOS",
        "windows", "WINDOWS",
        "macos", "MACOS",
        "linux", "LINUX",
        "iot", "IOT",
        "robot", "ROBOT",
        "drone", "DRONE",
    ])
    def test_physical_types_return_true(self, device_type: str):
        assert is_physical_device(device_type) is True

    @pytest.mark.parametrize("device_type", [
        "cloud",
        "browser",
        "unknown",
        "custom",
        "virtual",
        "server",
        "quantum",
    ])
    def test_non_physical_types_return_false(self, device_type: str):
        assert is_physical_device(device_type) is False

    @pytest.mark.parametrize("device_type", ["", None])
    def test_empty_or_none_returns_false(self, device_type):
        assert is_physical_device(device_type) is False

    def test_whitespace_stripped(self):
        assert is_physical_device("  android  ") is True

    def test_physical_device_types_set_is_frozen(self):
        assert isinstance(PHYSICAL_DEVICE_TYPES, frozenset)

    def test_physical_device_types_contains_all_required(self):
        required = {"ANDROID", "IOS", "WINDOWS", "MACOS", "LINUX", "IOT", "ROBOT", "DRONE"}
        assert required.issubset(PHYSICAL_DEVICE_TYPES)


# ---------------------------------------------------------------------------
# requires_agent_deploy — must mirror is_physical_device
# ---------------------------------------------------------------------------

class TestRequiresAgentDeploy:
    @pytest.mark.parametrize("device_type", [
        "android", "ios", "windows", "macos", "linux", "iot", "robot", "drone",
    ])
    def test_physical_types_require_deploy(self, device_type: str):
        assert requires_agent_deploy(device_type) is True

    @pytest.mark.parametrize("device_type", [
        "cloud", "browser", "unknown", "",
    ])
    def test_non_physical_types_do_not_require_deploy(self, device_type: str):
        assert requires_agent_deploy(device_type) is False

    def test_requires_matches_is_physical(self):
        """requires_agent_deploy must be consistent with is_physical_device."""
        test_values = list(PHYSICAL_DEVICE_TYPES) + [
            "cloud", "browser", "unknown", "custom", "", "  ",
        ]
        for val in test_values:
            assert requires_agent_deploy(val) == is_physical_device(val), (
                f"Mismatch for device_type={val!r}"
            )
