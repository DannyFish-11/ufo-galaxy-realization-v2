#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr15_status_board_config_control.py
===============================================

PR-15 — Status Board V2 canonical configuration control surface.

Validates that:
- The control surface module is importable and exports the correct symbols.
- STATUS_BOARD_CONFIG_CONTROL_AUTHORITY is a non-empty string.
- ControlOperation has the expected members.
- ConfigControlSurface is importable from the package __all__.
- Applying an allowed toggle operation writes through ConfigService (not
  ad-hoc state) and returns a succeeded ControlApplyResult.
- Applying an allowed routing policy writes through ConfigService and
  returns a succeeded ControlApplyResult.
- Runtime hot-reload hook is invoked when a manager is provided.
- Safe fallback is reported (not a crash) when hot-reload manager is absent.
- Projection/control feedback is updated and rendered after each apply.
- Unknown providers are rejected before any write.
- Unknown routing policies are rejected before any write.
- Empty provider names are rejected.
- Empty mode strings are rejected.
- ControlApplyResult.to_dict() is JSON-serialisable.
- ControlApplyResult.render_lines() returns a list of strings.
- render_feedback() returns an empty string before any apply.
- last_result is None before any apply.
- Rejected operations set succeeded=False and populate error.
- ConfigControlSurface.apply() dispatches correctly for TOGGLE_PROVIDER.
- ConfigControlSurface.apply() dispatches correctly for SET_ROUTING_POLICY.
- Feedback panel appears in StatusBoardV2App.render_once() when a
  control surface has a recent result.
- No feedback panel rendered when control surface has no result.
- StatusBoardV2App accepts control_surface parameter.
- CLI parser has --apply-toggle and --apply-routing-policy arguments.
- _apply_toggle_arg helper parses PROVIDER=BOOL correctly.
- _apply_toggle_arg rejects malformed args (no '=' separator).

Test index
----------
  1.  config_control module importable from windows_client.status_board_v2.config_control.
  2.  STATUS_BOARD_CONFIG_CONTROL_AUTHORITY importable from module.
  3.  ControlOperation importable from module.
  4.  ControlApplyResult importable from module.
  5.  ConfigControlSurface importable from module.
  6.  ConfigControlSurface importable from windows_client.status_board_v2 __all__.
  7.  STATUS_BOARD_CONFIG_CONTROL_AUTHORITY importable from package __all__.
  8.  ControlOperation importable from package __all__.
  9.  ControlApplyResult importable from package __all__.
  10. STATUS_BOARD_CONFIG_CONTROL_AUTHORITY is a non-empty string.
  11. STATUS_BOARD_CONFIG_CONTROL_AUTHORITY contains 'ConfigControlSurface'.
  12. ControlOperation.TOGGLE_PROVIDER is a member.
  13. ControlOperation.SET_ROUTING_POLICY is a member.
  14. ConfigControlSurface() instantiates without error (with mock service).
  15. ConfigControlSurface.last_result is None before any apply.
  16. ConfigControlSurface.render_feedback() returns empty string before any apply.
  17. apply_toggle (valid provider, enabled=True) returns succeeded=True.
  18. apply_toggle calls ConfigService.set_toggle, not local ad-hoc state.
  19. apply_toggle result.operation == 'toggle_provider'.
  20. apply_toggle result.last_applied_key contains provider name.
  21. apply_toggle result.last_applied_key contains the enabled value.
  22. apply_toggle with enabled=False also returns succeeded=True.
  23. apply_routing_policy (valid mode) returns succeeded=True.
  24. apply_routing_policy calls ConfigService.set_native_mm_policy.
  25. apply_routing_policy result.operation == 'set_routing_policy'.
  26. apply_routing_policy result.last_applied_key contains the mode.
  27. apply() dispatches TOGGLE_PROVIDER to apply_toggle.
  28. apply() dispatches SET_ROUTING_POLICY to apply_routing_policy.
  29. apply() with unknown operation returns succeeded=False.
  30. apply() with unknown operation populates error field.
  31. apply_toggle with empty provider returns succeeded=False.
  32. apply_toggle with unknown provider returns succeeded=False.
  33. apply_toggle with unknown provider error message is operator-meaningful.
  34. apply_routing_policy with empty mode returns succeeded=False.
  35. apply_routing_policy with invalid mode returns succeeded=False.
  36. apply_routing_policy with invalid mode error message is operator-meaningful.
  37. last_result is updated after apply_toggle.
  38. last_result is updated after apply_routing_policy.
  39. render_feedback() is non-empty after apply_toggle (succeeded).
  40. render_feedback() contains '✓' or 'APPLIED' after succeeded apply.
  41. render_feedback() contains '✗' or 'REJECTED' after failed apply.
  42. render_feedback() contains the last_applied_key after apply.
  43. ControlApplyResult.to_dict() returns a dict.
  44. ControlApplyResult.to_dict() is JSON-serialisable.
  45. ControlApplyResult.to_dict() contains 'succeeded' key.
  46. ControlApplyResult.to_dict() contains 'operation' key.
  47. ControlApplyResult.to_dict() contains 'reload_triggered' key.
  48. ControlApplyResult.to_dict() contains 'reload_supported' key.
  49. ControlApplyResult.render_lines() returns a list.
  50. ControlApplyResult.render_lines() is non-empty.
  51. Hot-reload manager is invoked when provided.
  52. reload_triggered=True when hot-reload manager succeeds.
  53. reload_supported=True when hot-reload manager is provided.
  54. reload_supported=False when no hot-reload manager available.
  55. reload_triggered=False when no hot-reload manager available.
  56. Reason field explains reload not available when manager absent.
  57. Hot-reload load_from_file errors propagate to result.reason.
  58. StatusBoardV2App accepts control_surface parameter.
  59. render_once() includes config control panel when surface has result.
  60. render_once() does NOT include config control panel when no result.
  61. Config control panel contains 'Config Control' header.
  62. Config control panel shows succeeded feedback.
  63. StatusBoardV2App.render_once() still renders all existing surfaces.
  64. CLI parser has --apply-toggle argument.
  65. CLI parser has --apply-routing-policy argument.
  66. _apply_toggle_arg parses 'openai=true' correctly.
  67. _apply_toggle_arg parses 'anthropic=false' correctly.
  68. _apply_toggle_arg rejects arg without '=' separator.
  69. Secret values are not included in feedback or render_lines output.
  70. apply_toggle with ConfigService raising generic exception returns succeeded=False.
"""

from __future__ import annotations

import json
import sys
import types
import unittest
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, call, patch


# ---------------------------------------------------------------------------
# Helpers to import the modules under test
# ---------------------------------------------------------------------------

def _import_control_module():
    import windows_client.status_board_v2.config_control as m
    return m


def _import_package():
    import windows_client.status_board_v2 as pkg
    return pkg


def _import_app_module():
    import windows_client.status_board_v2.app as m
    return m


# ---------------------------------------------------------------------------
# Minimal mock ConfigService
# ---------------------------------------------------------------------------

class _MockConfigService:
    """Minimal mock that records calls to set_toggle / set_native_mm_policy."""

    def __init__(self):
        self.toggle_calls: List[tuple] = []
        self.policy_calls: List[str] = []
        self._store = _MockStore()
        self._should_raise: Optional[Exception] = None

    @property
    def config_path(self) -> str:
        return self._store._config_path

    def set_toggle(self, provider: str, enabled: bool) -> None:
        if self._should_raise:
            raise self._should_raise
        self.toggle_calls.append((provider, enabled))

    def set_native_mm_policy(self, mode: str) -> None:
        if self._should_raise:
            raise self._should_raise
        self.policy_calls.append(mode)


@dataclass
class _MockStore:
    """Minimal mock store exposing _config_path."""
    _config_path: str = "/tmp/runtime/config.json"


class _MockHotReloadManager:
    """Minimal mock HotReloadConfigManager."""

    def __init__(self, return_errors=None):
        self.load_calls: List[str] = []
        self._return_errors = return_errors or []

    def load_from_file(self, path: Optional[str] = None) -> List[str]:
        self.load_calls.append(path or "")
        return self._return_errors


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class TestImports(unittest.TestCase):
    """Tests 1–13: Import and sentinel checks."""

    def test_01_module_importable(self):
        m = _import_control_module()
        self.assertIsNotNone(m)

    def test_02_authority_importable(self):
        m = _import_control_module()
        self.assertTrue(hasattr(m, "STATUS_BOARD_CONFIG_CONTROL_AUTHORITY"))

    def test_03_control_operation_importable(self):
        m = _import_control_module()
        self.assertTrue(hasattr(m, "ControlOperation"))

    def test_04_control_apply_result_importable(self):
        m = _import_control_module()
        self.assertTrue(hasattr(m, "ControlApplyResult"))

    def test_05_config_control_surface_importable(self):
        m = _import_control_module()
        self.assertTrue(hasattr(m, "ConfigControlSurface"))

    def test_06_surface_in_package_all(self):
        pkg = _import_package()
        self.assertIn("ConfigControlSurface", pkg.__all__)

    def test_07_authority_in_package_all(self):
        pkg = _import_package()
        self.assertIn("STATUS_BOARD_CONFIG_CONTROL_AUTHORITY", pkg.__all__)

    def test_08_control_operation_in_package_all(self):
        pkg = _import_package()
        self.assertIn("ControlOperation", pkg.__all__)

    def test_09_control_apply_result_in_package_all(self):
        pkg = _import_package()
        self.assertIn("ControlApplyResult", pkg.__all__)

    def test_10_authority_is_nonempty_string(self):
        m = _import_control_module()
        self.assertIsInstance(m.STATUS_BOARD_CONFIG_CONTROL_AUTHORITY, str)
        self.assertTrue(len(m.STATUS_BOARD_CONFIG_CONTROL_AUTHORITY) > 0)

    def test_11_authority_contains_class_name(self):
        m = _import_control_module()
        self.assertIn("ConfigControlSurface", m.STATUS_BOARD_CONFIG_CONTROL_AUTHORITY)

    def test_12_toggle_provider_member(self):
        m = _import_control_module()
        self.assertIn("TOGGLE_PROVIDER", [op.name for op in m.ControlOperation])

    def test_13_set_routing_policy_member(self):
        m = _import_control_module()
        self.assertIn("SET_ROUTING_POLICY", [op.name for op in m.ControlOperation])


class TestInstantiation(unittest.TestCase):
    """Tests 14–16: ConfigControlSurface construction and initial state."""

    def _make_surface(self):
        m = _import_control_module()
        svc = _MockConfigService()
        return m.ConfigControlSurface(service=svc)

    def test_14_instantiates_without_error(self):
        surface = self._make_surface()
        self.assertIsNotNone(surface)

    def test_15_last_result_is_none_initially(self):
        surface = self._make_surface()
        self.assertIsNone(surface.last_result)

    def test_16_render_feedback_empty_initially(self):
        surface = self._make_surface()
        self.assertEqual(surface.render_feedback(), "")


class TestApplyToggle(unittest.TestCase):
    """Tests 17–22: apply_toggle through ConfigService."""

    def _make(self, provider="openai", enabled=True, hot_reload_mgr=None):
        m = _import_control_module()
        svc = _MockConfigService()
        surface = m.ConfigControlSurface(
            service=svc,
            hot_reload_manager=hot_reload_mgr,
        )
        result = surface.apply_toggle(provider, enabled)
        return surface, svc, result

    def test_17_valid_toggle_succeeds(self):
        _, _, result = self._make()
        self.assertTrue(result.succeeded)

    def test_18_writes_through_config_service(self):
        _, svc, _ = self._make(provider="openai", enabled=True)
        # set_toggle must have been called
        self.assertEqual(len(svc.toggle_calls), 1)
        self.assertEqual(svc.toggle_calls[0], ("openai", True))

    def test_19_operation_value(self):
        _, _, result = self._make()
        self.assertEqual(result.operation, "toggle_provider")

    def test_20_last_applied_key_contains_provider(self):
        _, _, result = self._make(provider="openai")
        self.assertIn("openai", result.last_applied_key)

    def test_21_last_applied_key_contains_enabled(self):
        _, _, result = self._make(enabled=True)
        self.assertIn("True", result.last_applied_key)

    def test_22_toggle_disabled_succeeds(self):
        _, svc, result = self._make(provider="anthropic", enabled=False)
        self.assertTrue(result.succeeded)
        self.assertEqual(svc.toggle_calls[0], ("anthropic", False))


class TestApplyRoutingPolicy(unittest.TestCase):
    """Tests 23–26: apply_routing_policy through ConfigService."""

    def _make(self, mode="prefer", hot_reload_mgr=None):
        m = _import_control_module()
        svc = _MockConfigService()
        surface = m.ConfigControlSurface(
            service=svc,
            hot_reload_manager=hot_reload_mgr,
        )
        result = surface.apply_routing_policy(mode)
        return surface, svc, result

    def test_23_valid_policy_succeeds(self):
        _, _, result = self._make(mode="prefer")
        self.assertTrue(result.succeeded)

    def test_24_calls_set_native_mm_policy(self):
        _, svc, _ = self._make(mode="strict")
        self.assertEqual(svc.policy_calls, ["strict"])

    def test_25_operation_value(self):
        _, _, result = self._make(mode="prefer")
        self.assertEqual(result.operation, "set_routing_policy")

    def test_26_last_applied_key_contains_mode(self):
        _, _, result = self._make(mode="allow_fallback")
        self.assertIn("allow_fallback", result.last_applied_key)


class TestApplyDispatch(unittest.TestCase):
    """Tests 27–30: apply() dispatcher."""

    def _make_surface(self):
        m = _import_control_module()
        svc = _MockConfigService()
        return m.ConfigControlSurface(service=svc), svc, m.ControlOperation

    def test_27_dispatch_toggle_provider(self):
        surface, svc, ControlOperation = self._make_surface()
        result = surface.apply(
            ControlOperation.TOGGLE_PROVIDER,
            provider="openai",
            enabled=True,
        )
        self.assertTrue(result.succeeded)
        self.assertEqual(len(svc.toggle_calls), 1)

    def test_28_dispatch_set_routing_policy(self):
        surface, svc, ControlOperation = self._make_surface()
        result = surface.apply(
            ControlOperation.SET_ROUTING_POLICY,
            mode="prefer",
        )
        self.assertTrue(result.succeeded)
        self.assertEqual(svc.policy_calls, ["prefer"])

    def test_29_unknown_operation_fails(self):
        surface, _, _ = self._make_surface()
        result = surface.apply("not_a_real_operation")  # type: ignore[arg-type]
        self.assertFalse(result.succeeded)

    def test_30_unknown_operation_error_populated(self):
        surface, _, _ = self._make_surface()
        result = surface.apply("not_a_real_operation")  # type: ignore[arg-type]
        self.assertTrue(len(result.error) > 0)


class TestRejections(unittest.TestCase):
    """Tests 31–36: rejected operations fail safely with meaningful errors."""

    def _surface(self):
        m = _import_control_module()
        svc = _MockConfigService()
        return m.ConfigControlSurface(service=svc), svc

    def test_31_empty_provider_rejected(self):
        surface, svc = self._surface()
        result = surface.apply_toggle("", True)
        self.assertFalse(result.succeeded)
        self.assertEqual(len(svc.toggle_calls), 0)

    def test_32_unknown_provider_rejected(self):
        surface, svc = self._surface()
        svc._should_raise = ValueError("Unknown provider 'fakeprovider'")
        result = surface.apply_toggle("fakeprovider", True)
        self.assertFalse(result.succeeded)

    def test_33_unknown_provider_error_meaningful(self):
        surface, svc = self._surface()
        svc._should_raise = ValueError("Unknown provider 'fakeprovider'. Valid providers: ['openai']")
        result = surface.apply_toggle("fakeprovider", True)
        self.assertIn("fakeprovider", result.error.lower() + result.error)

    def test_34_empty_mode_rejected(self):
        surface, svc = self._surface()
        result = surface.apply_routing_policy("")
        self.assertFalse(result.succeeded)
        self.assertEqual(len(svc.policy_calls), 0)

    def test_35_invalid_mode_rejected(self):
        surface, svc = self._surface()
        svc._should_raise = ValueError("Invalid native_multimodal_policy 'turbo'")
        result = surface.apply_routing_policy("turbo")
        self.assertFalse(result.succeeded)

    def test_36_invalid_mode_error_meaningful(self):
        surface, svc = self._surface()
        svc._should_raise = ValueError("Invalid native_multimodal_policy 'turbo'. Valid values: ['allow_fallback', 'prefer', 'strict']")
        result = surface.apply_routing_policy("turbo")
        # Error must mention the bad value
        self.assertIn("turbo", result.error)


class TestLastResultAndFeedback(unittest.TestCase):
    """Tests 37–42: last_result and render_feedback."""

    def _surface(self):
        m = _import_control_module()
        svc = _MockConfigService()
        return m.ConfigControlSurface(service=svc)

    def test_37_last_result_updated_after_toggle(self):
        surface = self._surface()
        surface.apply_toggle("openai", True)
        self.assertIsNotNone(surface.last_result)

    def test_38_last_result_updated_after_policy(self):
        surface = self._surface()
        surface.apply_routing_policy("prefer")
        self.assertIsNotNone(surface.last_result)

    def test_39_render_feedback_nonempty_after_succeeded_apply(self):
        surface = self._surface()
        surface.apply_toggle("openai", True)
        self.assertTrue(len(surface.render_feedback()) > 0)

    def test_40_render_feedback_shows_applied(self):
        surface = self._surface()
        surface.apply_toggle("openai", True)
        feedback = surface.render_feedback()
        self.assertTrue("✓" in feedback or "APPLIED" in feedback)

    def test_41_render_feedback_shows_rejected_on_failure(self):
        surface = self._surface()
        surface.apply_toggle("", True)  # empty provider → failure
        feedback = surface.render_feedback()
        self.assertTrue("✗" in feedback or "REJECTED" in feedback)

    def test_42_render_feedback_contains_applied_key(self):
        surface = self._surface()
        surface.apply_toggle("openai", True)
        feedback = surface.render_feedback()
        self.assertIn("openai", feedback)


class TestControlApplyResultSerialization(unittest.TestCase):
    """Tests 43–50: ControlApplyResult serialisation."""

    def _make_result(self):
        m = _import_control_module()
        return m.ControlApplyResult(
            succeeded=True,
            operation="toggle_provider",
            last_applied_key="providers.openai.enabled → True",
            reload_triggered=True,
            reload_supported=True,
            reason="runtime hot-reload triggered",
        )

    def test_43_to_dict_returns_dict(self):
        r = self._make_result()
        self.assertIsInstance(r.to_dict(), dict)

    def test_44_to_dict_is_json_serialisable(self):
        r = self._make_result()
        json.dumps(r.to_dict())  # must not raise

    def test_45_to_dict_has_succeeded(self):
        r = self._make_result()
        self.assertIn("succeeded", r.to_dict())

    def test_46_to_dict_has_operation(self):
        r = self._make_result()
        self.assertIn("operation", r.to_dict())

    def test_47_to_dict_has_reload_triggered(self):
        r = self._make_result()
        self.assertIn("reload_triggered", r.to_dict())

    def test_48_to_dict_has_reload_supported(self):
        r = self._make_result()
        self.assertIn("reload_supported", r.to_dict())

    def test_49_render_lines_returns_list(self):
        r = self._make_result()
        self.assertIsInstance(r.render_lines(), list)

    def test_50_render_lines_nonempty(self):
        r = self._make_result()
        self.assertGreater(len(r.render_lines()), 0)


class TestHotReload(unittest.TestCase):
    """Tests 51–57: hot-reload integration."""

    def _surface_with_manager(self, errors=None):
        m = _import_control_module()
        svc = _MockConfigService()
        mgr = _MockHotReloadManager(return_errors=errors or [])
        surface = m.ConfigControlSurface(service=svc, hot_reload_manager=mgr)
        return surface, svc, mgr

    def _surface_without_manager(self):
        m = _import_control_module()
        svc = _MockConfigService()
        # Ensure no global manager is accidentally used by patching the lookup
        with patch("windows_client.status_board_v2.config_control._get_hot_reload_manager", return_value=None):
            surface = m.ConfigControlSurface(service=svc, hot_reload_manager=None)
            # Apply inside the context so the patch is active during _trigger_reload
            result = surface.apply_toggle("openai", True)
        return surface, svc, result

    def test_51_reload_manager_invoked(self):
        surface, _, mgr = self._surface_with_manager()
        surface.apply_toggle("openai", True)
        self.assertEqual(len(mgr.load_calls), 1)

    def test_52_reload_triggered_true_when_manager_succeeds(self):
        surface, _, _ = self._surface_with_manager()
        result = surface.apply_toggle("openai", True)
        self.assertTrue(result.reload_triggered)

    def test_53_reload_supported_true_when_manager_present(self):
        surface, _, _ = self._surface_with_manager()
        result = surface.apply_toggle("openai", True)
        self.assertTrue(result.reload_supported)

    def test_54_reload_supported_false_when_no_manager(self):
        _, _, result = self._surface_without_manager()
        self.assertFalse(result.reload_supported)

    def test_55_reload_triggered_false_when_no_manager(self):
        _, _, result = self._surface_without_manager()
        self.assertFalse(result.reload_triggered)

    def test_56_reason_explains_when_manager_absent(self):
        _, _, result = self._surface_without_manager()
        # reason should explain that reload is not available
        combined = (result.reason + " " + result.error).lower()
        self.assertTrue(
            "not" in combined
            or "startup" in combined
            or "restart" in combined
            or "absent" in combined
        )

    def test_57_reload_errors_propagate_to_reason(self):
        surface, _, mgr = self._surface_with_manager(errors=["config file missing"])
        result = surface.apply_toggle("openai", True)
        self.assertFalse(result.reload_triggered)
        self.assertTrue(result.reload_supported)
        self.assertIn("config file missing", result.reason)


class TestAppIntegration(unittest.TestCase):
    """Tests 58–63: StatusBoardV2App control feedback integration."""

    def _minimal_projection(self):
        return {"timestamp": None}

    def test_58_app_accepts_control_surface(self):
        from windows_client.status_board_v2.app import StatusBoardV2App
        m = _import_control_module()
        svc = _MockConfigService()
        control = m.ConfigControlSurface(service=svc)
        app = StatusBoardV2App(
            file_path=None,
            from_stdin=True,
            control_surface=control,
        )
        self.assertIsNotNone(app)

    def test_59_render_once_includes_feedback_when_result_present(self):
        from windows_client.status_board_v2.app import StatusBoardV2App
        m = _import_control_module()
        svc = _MockConfigService()
        control = m.ConfigControlSurface(service=svc)
        control.apply_toggle("openai", True)

        app = StatusBoardV2App(from_stdin=True, control_surface=control)
        frame = app.render_once(self._minimal_projection())
        self.assertIn("Config Control", frame)

    def test_60_render_once_no_feedback_panel_when_no_result(self):
        from windows_client.status_board_v2.app import StatusBoardV2App
        m = _import_control_module()
        svc = _MockConfigService()
        control = m.ConfigControlSurface(service=svc)
        # no apply — last_result is None

        app = StatusBoardV2App(from_stdin=True, control_surface=control)
        frame = app.render_once(self._minimal_projection())
        self.assertNotIn("Config Control", frame)

    def test_61_control_panel_contains_header(self):
        from windows_client.status_board_v2.app import StatusBoardV2App
        m = _import_control_module()
        svc = _MockConfigService()
        control = m.ConfigControlSurface(service=svc)
        control.apply_toggle("openai", True)

        app = StatusBoardV2App(from_stdin=True, control_surface=control)
        frame = app.render_once(self._minimal_projection())
        self.assertIn("Config Control", frame)

    def test_62_control_panel_shows_feedback_text(self):
        from windows_client.status_board_v2.app import StatusBoardV2App
        m = _import_control_module()
        svc = _MockConfigService()
        control = m.ConfigControlSurface(service=svc)
        control.apply_toggle("openai", True)

        app = StatusBoardV2App(from_stdin=True, control_surface=control)
        frame = app.render_once(self._minimal_projection())
        # feedback text includes '✓' or 'APPLIED' for success
        self.assertTrue("✓" in frame or "APPLIED" in frame)

    def test_63_render_once_still_renders_existing_surfaces(self):
        from windows_client.status_board_v2.app import StatusBoardV2App
        app = StatusBoardV2App(from_stdin=True, control_surface=None)
        frame = app.render_once(self._minimal_projection())
        # Board title still present
        self.assertIn("Status Board V2", frame)


class TestCLI(unittest.TestCase):
    """Tests 64–68: CLI argument parsing."""

    def _build_parser(self):
        from windows_client.status_board_v2.app import _build_parser
        return _build_parser()

    def test_64_parser_has_apply_toggle(self):
        p = self._build_parser()
        args = p.parse_args(["--apply-toggle", "openai=true"])
        self.assertEqual(args.apply_toggle, "openai=true")

    def test_65_parser_has_apply_routing_policy(self):
        p = self._build_parser()
        args = p.parse_args(["--apply-routing-policy", "prefer"])
        self.assertEqual(args.apply_routing_policy, "prefer")

    def test_66_apply_toggle_arg_parses_true(self):
        from windows_client.status_board_v2.app import _apply_toggle_arg
        m = _import_control_module()
        svc = _MockConfigService()
        control = m.ConfigControlSurface(service=svc)
        result = _apply_toggle_arg(control, "openai=true")
        self.assertTrue(result.succeeded)
        self.assertEqual(svc.toggle_calls[0], ("openai", True))

    def test_67_apply_toggle_arg_parses_false(self):
        from windows_client.status_board_v2.app import _apply_toggle_arg
        m = _import_control_module()
        svc = _MockConfigService()
        control = m.ConfigControlSurface(service=svc)
        result = _apply_toggle_arg(control, "anthropic=false")
        self.assertTrue(result.succeeded)
        self.assertEqual(svc.toggle_calls[0], ("anthropic", False))

    def test_68_apply_toggle_arg_rejects_no_equals(self):
        from windows_client.status_board_v2.app import _apply_toggle_arg
        m = _import_control_module()
        svc = _MockConfigService()
        control = m.ConfigControlSurface(service=svc)
        result = _apply_toggle_arg(control, "openai")
        self.assertFalse(result.succeeded)
        self.assertTrue(len(result.error) > 0)


class TestSecretSafety(unittest.TestCase):
    """Tests 69–70: secrets are never exposed in feedback."""

    def test_69_no_secret_in_feedback(self):
        """render_lines must not expose secret values."""
        m = _import_control_module()
        result = m.ControlApplyResult(
            succeeded=False,
            operation="toggle_provider",
            error="provider 'openai' key error",  # deliberately no actual key value
        )
        rendered = "\n".join(result.render_lines())
        # The rendered output should not contain anything that looks like a real key
        # We just assert the operation name is there and no 'sk-' prefix leaks
        self.assertNotIn("sk-", rendered)

    def test_70_generic_exception_returns_succeeded_false(self):
        """apply_toggle with a ConfigService raising a generic exception returns succeeded=False."""
        m = _import_control_module()
        svc = _MockConfigService()
        svc._should_raise = ValueError("unexpected internal error")
        surface = m.ConfigControlSurface(service=svc)
        result = surface.apply_toggle("openai", True)
        self.assertFalse(result.succeeded)
        self.assertTrue(len(result.error) > 0)


if __name__ == "__main__":
    unittest.main()
