from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch


def test_routing_context_usage_records_misuse_event() -> None:
    from core.capability_registry import (
        get_capability_registry_misuse_events,
        get_device_capability_summary,
        reset_capability_registry_misuse_events,
    )

    reset_capability_registry_misuse_events()
    fake_stack = [
        SimpleNamespace(filename="/repo/core/capability_registry.py", function="_guard_routing_context_usage"),
        SimpleNamespace(filename="/repo/core/capability_registry.py", function="get_device_capability_summary"),
        SimpleNamespace(filename="/repo/core/device_router.py", function="route_task"),
    ]
    with patch("core.capability_registry.inspect.stack", return_value=fake_stack):
        get_device_capability_summary("android_001")

    events = get_capability_registry_misuse_events()
    assert len(events) == 1
    assert events[0].caller_module.endswith("device_router.py")
    assert events[0].operation == "get_device_capability_summary"


def test_non_routing_context_does_not_record_misuse_event() -> None:
    from core.capability_registry import (
        get_capability_registry_misuse_events,
        get_device_capability_summary,
        reset_capability_registry_misuse_events,
    )

    reset_capability_registry_misuse_events()
    fake_stack = [
        SimpleNamespace(filename="/repo/core/capability_registry.py", function="_guard_routing_context_usage"),
        SimpleNamespace(filename="/repo/core/capability_registry.py", function="get_device_capability_summary"),
        SimpleNamespace(filename="/repo/tests/test_capability_registry_routing_guard.py", function="test_fn"),
    ]
    with patch("core.capability_registry.inspect.stack", return_value=fake_stack):
        get_device_capability_summary("android_001")

    assert get_capability_registry_misuse_events() == []
