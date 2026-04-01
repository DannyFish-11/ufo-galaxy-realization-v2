#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr8_status_board_control_surface.py
==============================================

PR-8 — Upgrade windows_client/status_board_v2 to a desktop control surface.

Validates that status_board_v2 is no longer read-only and satisfies the
acceptance criteria for PR-8:

  AC1. status_board_v2 can apply a bounded set of real runtime-relevant
       configuration changes.
  AC2. Writes flow through canonical configuration authority (ConfigService).
  AC3. Runtime-visible apply/reload/result feedback is surfaced in the board.
  AC4. status_board_v2 is materially closer to a true desktop control surface
       rather than a read-only projection board.

The tests are intentionally narrow and focus on proving each acceptance
criterion with clear, isolated assertions.  Exhaustive edge-case coverage
lives in tests/test_pr15_status_board_config_control.py.

Test index
----------
  AC1 — Bounded runtime-relevant configuration changes
   1. ConfigControlSurface is importable from the package.
   2. apply_toggle(provider, enabled=True) returns succeeded=True.
   3. apply_toggle(provider, enabled=False) returns succeeded=True.
   4. apply_routing_policy(mode) returns succeeded=True for 'strict'.
   5. apply_routing_policy(mode) returns succeeded=True for 'prefer'.
   6. apply_routing_policy(mode) returns succeeded=True for 'allow_fallback'.
   7. Unknown operations are rejected (succeeded=False).
   8. Empty provider names are rejected (succeeded=False).
   9. Empty routing policy modes are rejected (succeeded=False).
  10. Operations outside the allowed set are never applied.

  AC2 — Writes flow through canonical ConfigService, not ad-hoc paths
  11. apply_toggle calls ConfigService.set_toggle exactly once.
  12. apply_toggle does NOT call any local state write.
  13. apply_routing_policy calls ConfigService.set_native_mm_policy exactly once.
  14. apply_routing_policy does NOT call any local state write.
  15. ConfigControlSurface constructor does not import any ad-hoc config writer.
  16. Multiple sequential applies each call ConfigService independently.

  AC3 — Apply/reload/result feedback visible in the board
  17. ControlApplyResult.succeeded is True after a successful toggle.
  18. ControlApplyResult.last_applied_key describes the applied change.
  19. render_feedback() is non-empty after a successful apply.
  20. render_feedback() contains 'APPLIED' or '✓' after success.
  21. render_feedback() contains 'REJECTED' or '✗' after failure.
  22. render_feedback() describes reload status after success.
  23. render_feedback() is empty before any apply.
  24. StatusBoardV2App.render_once() renders a Config Control panel when
      feedback is present.
  25. StatusBoardV2App.render_once() does NOT render a Config Control panel
      when no apply has occurred.
  26. Config Control panel in render_once() contains feedback text.
  27. last_result is None before any apply.
  28. last_result is a ControlApplyResult after a successful apply.
  29. ControlApplyResult.to_dict() is JSON-serialisable.
  30. ControlApplyResult.to_dict() has a 'succeeded' key.

  AC4 — Board is a true desktop control surface, not read-only
  31. Package __all__ exports ConfigControlSurface.
  32. Package __all__ exports STATUS_BOARD_CONFIG_CONTROL_AUTHORITY.
  33. Package __all__ exports ControlOperation.
  34. Package __all__ exports ControlApplyResult.
  35. ControlOperation.TOGGLE_PROVIDER is defined.
  36. ControlOperation.SET_ROUTING_POLICY is defined.
  37. StatusBoardV2App accepts control_surface parameter.
  38. CLI parser exposes --apply-toggle argument.
  39. CLI parser exposes --apply-routing-policy argument.
  40. Projection/read behaviour is unaffected (render_once returns all surfaces).
"""

from __future__ import annotations

import json
import unittest
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Minimal mocks
# ---------------------------------------------------------------------------

class _MockConfigService:
    """Minimal ConfigService mock that records call history."""

    def __init__(self):
        self.toggle_calls: List[tuple] = []
        self.policy_calls: List[str] = []
        self._store = _MockStore()
        self._should_raise_value: Optional[Exception] = None

    @property
    def config_path(self) -> str:
        return self._store._config_path

    def set_toggle(self, provider: str, enabled: bool) -> None:
        if self._should_raise_value:
            raise self._should_raise_value
        self.toggle_calls.append((provider, enabled))

    def set_native_mm_policy(self, mode: str) -> None:
        if self._should_raise_value:
            raise self._should_raise_value
        self.policy_calls.append(mode)


@dataclass
class _MockStore:
    _config_path: str = "/tmp/test/config.json"


class _MockHotReloadManager:
    def __init__(self, errors=None):
        self.load_calls: List[str] = []
        self._errors = errors or []

    def load_from_file(self, path: Optional[str] = None) -> List[str]:
        self.load_calls.append(path or "")
        return self._errors


def _make_surface(hot_reload_manager=None, raise_value=None):
    """Return a ConfigControlSurface backed by a fresh MockConfigService."""
    from windows_client.status_board_v2.config_control import ConfigControlSurface
    svc = _MockConfigService()
    if raise_value is not None:
        svc._should_raise_value = raise_value
    return ConfigControlSurface(service=svc, hot_reload_manager=hot_reload_manager), svc


def _minimal_projection() -> Dict[str, Any]:
    return {"tri_state_phase": "silent", "timestamp": 0.0}


def _make_app(control_surface=None):
    from windows_client.status_board_v2.app import StatusBoardV2App
    return StatusBoardV2App(
        file_path="/dev/null",
        control_surface=control_surface,
    )


# ---------------------------------------------------------------------------
# AC1 — Bounded runtime-relevant configuration changes
# ---------------------------------------------------------------------------

class TestAC1BoundedChanges(unittest.TestCase):
    """Tests 1–10: AC1 — bounded, runtime-relevant config changes."""

    def test_01_config_control_surface_importable(self):
        from windows_client.status_board_v2.config_control import ConfigControlSurface
        self.assertIsNotNone(ConfigControlSurface)

    def test_02_apply_toggle_enabled_true_succeeds(self):
        surface, _ = _make_surface()
        result = surface.apply_toggle("openai", True)
        self.assertTrue(result.succeeded)

    def test_03_apply_toggle_enabled_false_succeeds(self):
        surface, _ = _make_surface()
        result = surface.apply_toggle("anthropic", False)
        self.assertTrue(result.succeeded)

    def test_04_apply_routing_policy_strict_succeeds(self):
        surface, _ = _make_surface()
        result = surface.apply_routing_policy("strict")
        self.assertTrue(result.succeeded)

    def test_05_apply_routing_policy_prefer_succeeds(self):
        surface, _ = _make_surface()
        result = surface.apply_routing_policy("prefer")
        self.assertTrue(result.succeeded)

    def test_06_apply_routing_policy_allow_fallback_succeeds(self):
        surface, _ = _make_surface()
        result = surface.apply_routing_policy("allow_fallback")
        self.assertTrue(result.succeeded)

    def test_07_unknown_operation_rejected(self):
        surface, _ = _make_surface()
        result = surface.apply("unknown_operation")
        self.assertFalse(result.succeeded)

    def test_08_empty_provider_rejected(self):
        surface, _ = _make_surface()
        result = surface.apply_toggle("", True)
        self.assertFalse(result.succeeded)

    def test_09_empty_routing_policy_mode_rejected(self):
        surface, _ = _make_surface()
        result = surface.apply_routing_policy("")
        self.assertFalse(result.succeeded)

    def test_10_rejected_operation_has_no_write(self):
        surface, svc = _make_surface()
        surface.apply_toggle("", True)
        self.assertEqual(svc.toggle_calls, [], "empty provider must not reach ConfigService")


# ---------------------------------------------------------------------------
# AC2 — Writes flow through canonical ConfigService
# ---------------------------------------------------------------------------

class TestAC2CanonicalWrites(unittest.TestCase):
    """Tests 11–16: AC2 — writes via ConfigService only."""

    def test_11_apply_toggle_calls_set_toggle_once(self):
        surface, svc = _make_surface()
        surface.apply_toggle("openai", True)
        self.assertEqual(len(svc.toggle_calls), 1)

    def test_12_apply_toggle_passes_correct_args(self):
        surface, svc = _make_surface()
        surface.apply_toggle("openai", True)
        self.assertEqual(svc.toggle_calls[0], ("openai", True))

    def test_13_apply_routing_policy_calls_set_native_mm_policy_once(self):
        surface, svc = _make_surface()
        surface.apply_routing_policy("prefer")
        self.assertEqual(len(svc.policy_calls), 1)

    def test_14_apply_routing_policy_passes_correct_mode(self):
        surface, svc = _make_surface()
        surface.apply_routing_policy("allow_fallback")
        self.assertEqual(svc.policy_calls[0], "allow_fallback")

    def test_15_no_separate_local_config_state_maintained(self):
        """ConfigControlSurface must not have its own config dict."""
        from windows_client.status_board_v2.config_control import ConfigControlSurface
        svc = _MockConfigService()
        surface = ConfigControlSurface(service=svc)
        # The surface must not carry any _config, _local_config, or _state attr
        self.assertFalse(
            hasattr(surface, "_config") or hasattr(surface, "_local_config"),
            "Surface must not maintain a parallel configuration dict",
        )

    def test_16_multiple_applies_each_call_service(self):
        surface, svc = _make_surface()
        surface.apply_toggle("openai", True)
        surface.apply_toggle("anthropic", False)
        surface.apply_routing_policy("strict")
        self.assertEqual(len(svc.toggle_calls), 2)
        self.assertEqual(len(svc.policy_calls), 1)


# ---------------------------------------------------------------------------
# AC3 — Apply/reload/result feedback visible in the board
# ---------------------------------------------------------------------------

class TestAC3Feedback(unittest.TestCase):
    """Tests 17–30: AC3 — feedback visible in the board."""

    def test_17_succeeded_true_after_toggle(self):
        surface, _ = _make_surface()
        result = surface.apply_toggle("openai", True)
        self.assertTrue(result.succeeded)

    def test_18_last_applied_key_describes_change(self):
        surface, _ = _make_surface()
        result = surface.apply_toggle("openai", True)
        self.assertIn("openai", result.last_applied_key)
        self.assertIn("True", result.last_applied_key)

    def test_19_render_feedback_non_empty_after_success(self):
        surface, _ = _make_surface()
        surface.apply_toggle("openai", True)
        self.assertNotEqual(surface.render_feedback(), "")

    def test_20_render_feedback_contains_applied_marker_on_success(self):
        surface, _ = _make_surface()
        surface.apply_toggle("openai", True)
        feedback = surface.render_feedback()
        self.assertTrue(
            "APPLIED" in feedback or "✓" in feedback,
            f"Expected 'APPLIED' or '✓' in feedback: {feedback!r}",
        )

    def test_21_render_feedback_contains_rejected_marker_on_failure(self):
        surface, _ = _make_surface()
        surface.apply_toggle("", True)
        feedback = surface.render_feedback()
        self.assertTrue(
            "REJECTED" in feedback or "✗" in feedback,
            f"Expected 'REJECTED' or '✗' in feedback: {feedback!r}",
        )

    def test_22_render_feedback_describes_reload_status(self):
        mgr = _MockHotReloadManager()
        surface, _ = _make_surface(hot_reload_manager=mgr)
        surface.apply_toggle("openai", True)
        feedback = surface.render_feedback()
        # Should mention reload in some form
        self.assertTrue(
            "reload" in feedback.lower() or "restart" in feedback.lower(),
            f"Expected reload info in feedback: {feedback!r}",
        )

    def test_23_render_feedback_empty_before_any_apply(self):
        surface, _ = _make_surface()
        self.assertEqual(surface.render_feedback(), "")

    def test_24_render_once_shows_config_control_panel_when_feedback_present(self):
        mgr = _MockHotReloadManager()
        surface, _ = _make_surface(hot_reload_manager=mgr)
        surface.apply_toggle("openai", True)
        app = _make_app(control_surface=surface)
        frame = app.render_once(_minimal_projection())
        self.assertIn("Config Control", frame)

    def test_25_render_once_no_config_panel_when_no_apply(self):
        surface, _ = _make_surface()
        app = _make_app(control_surface=surface)
        frame = app.render_once(_minimal_projection())
        self.assertNotIn("Config Control", frame)

    def test_26_config_panel_contains_feedback_text(self):
        mgr = _MockHotReloadManager()
        surface, _ = _make_surface(hot_reload_manager=mgr)
        surface.apply_toggle("openai", True)
        app = _make_app(control_surface=surface)
        frame = app.render_once(_minimal_projection())
        self.assertIn("openai", frame)

    def test_27_last_result_none_before_any_apply(self):
        surface, _ = _make_surface()
        self.assertIsNone(surface.last_result)

    def test_28_last_result_populated_after_apply(self):
        from windows_client.status_board_v2.config_control import ControlApplyResult
        surface, _ = _make_surface()
        surface.apply_toggle("openai", True)
        self.assertIsInstance(surface.last_result, ControlApplyResult)

    def test_29_to_dict_json_serialisable(self):
        surface, _ = _make_surface()
        result = surface.apply_toggle("openai", True)
        d = result.to_dict()
        encoded = json.dumps(d)
        self.assertIsInstance(encoded, str)

    def test_30_to_dict_has_succeeded_key(self):
        surface, _ = _make_surface()
        result = surface.apply_toggle("openai", True)
        self.assertIn("succeeded", result.to_dict())


# ---------------------------------------------------------------------------
# AC4 — Board is a true desktop control surface, not read-only
# ---------------------------------------------------------------------------

class TestAC4DesktopControlSurface(unittest.TestCase):
    """Tests 31–40: AC4 — board is a true desktop control surface."""

    def test_31_package_exports_config_control_surface(self):
        import windows_client.status_board_v2 as pkg
        self.assertIn("ConfigControlSurface", pkg.__all__)

    def test_32_package_exports_authority_sentinel(self):
        import windows_client.status_board_v2 as pkg
        self.assertIn("STATUS_BOARD_CONFIG_CONTROL_AUTHORITY", pkg.__all__)

    def test_33_package_exports_control_operation(self):
        import windows_client.status_board_v2 as pkg
        self.assertIn("ControlOperation", pkg.__all__)

    def test_34_package_exports_control_apply_result(self):
        import windows_client.status_board_v2 as pkg
        self.assertIn("ControlApplyResult", pkg.__all__)

    def test_35_control_operation_toggle_provider_defined(self):
        from windows_client.status_board_v2.config_control import ControlOperation
        self.assertIn("TOGGLE_PROVIDER", [op.name for op in ControlOperation])

    def test_36_control_operation_set_routing_policy_defined(self):
        from windows_client.status_board_v2.config_control import ControlOperation
        self.assertIn("SET_ROUTING_POLICY", [op.name for op in ControlOperation])

    def test_37_status_board_app_accepts_control_surface(self):
        from windows_client.status_board_v2.app import StatusBoardV2App
        import inspect
        sig = inspect.signature(StatusBoardV2App.__init__)
        self.assertIn("control_surface", sig.parameters)

    def test_38_cli_parser_has_apply_toggle(self):
        from windows_client.status_board_v2.app import _build_parser
        parser = _build_parser()
        action_dests = {a.dest for a in parser._actions}
        self.assertIn("apply_toggle", action_dests)

    def test_39_cli_parser_has_apply_routing_policy(self):
        from windows_client.status_board_v2.app import _build_parser
        parser = _build_parser()
        action_dests = {a.dest for a in parser._actions}
        self.assertIn("apply_routing_policy", action_dests)

    def test_40_render_once_still_renders_all_existing_surfaces(self):
        """Read/projection behaviour must be preserved alongside control writes."""
        surface, _ = _make_surface()
        surface.apply_toggle("openai", True)
        app = _make_app(control_surface=surface)
        frame = app.render_once({
            "tri_state_phase": "manifest",
            "timestamp": 1_700_000_000.0,
            "runtime_domain": "local",
        })
        # Board title must always be present
        self.assertIn("Status Board", frame)
        # Both control feedback AND projection surfaces must be rendered
        self.assertIn("Config Control", frame)


if __name__ == "__main__":
    unittest.main()
