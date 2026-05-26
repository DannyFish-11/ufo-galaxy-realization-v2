from __future__ import annotations

import sys
import time
from unittest.mock import MagicMock, patch


def _patch_numpy():
    return patch.dict(
        sys.modules,
        {
            "numpy": MagicMock(),
            "sounddevice": MagicMock(),
            "pyaudio": MagicMock(),
        },
    )


class TestFormalPresenceDefinitions:
    def test_three_modes_are_formally_defined(self):
        from core.desktop_presence_system import (
            PRESENCE_MODE_DEFINITIONS,
            list_presence_mode_names,
        )

        assert list_presence_mode_names() == ["static", "liminal", "manifest"]
        assert len(PRESENCE_MODE_DEFINITIONS) == 3
        liminal = next(d for d in PRESENCE_MODE_DEFINITIONS if d.mode.value == "liminal")
        assert "ambient board" in liminal.ambient_board_role.lower()
        assert "busy" in liminal.non_equivalence_guard.lower()

    def test_transition_policies_cover_all_target_modes(self):
        from core.desktop_presence_system import iter_presence_transition_targets

        targets = set(iter_presence_transition_targets())
        assert targets == {"static", "liminal", "manifest"}


class TestPresenceStateMachine:
    def test_transitions_static_liminal_manifest_and_cooldown_back_to_static(self):
        from core.desktop_presence_system import DesktopPresenceStateMachine

        sm = DesktopPresenceStateMachine()
        sm._mode_since -= 1.0
        sm.update(
            tri_state="liminal",
            task_active=True,
            sensing_active=False,
            execution_active=False,
            user_interaction=True,
        )
        assert sm.mode.value == "liminal"

        sm._mode_since -= 1.0
        sm.update(
            tri_state="manifest",
            task_active=True,
            sensing_active=False,
            execution_active=True,
            user_interaction=True,
        )
        assert sm.mode.value == "manifest"

        sm._mode_since -= 1.0
        sm.update(
            tri_state="silent",
            task_active=False,
            sensing_active=False,
            execution_active=False,
            user_interaction=False,
            result_committed=True,
        )
        assert sm.mode.value == "liminal"

        sm._mode_since -= 1.0
        sm._last_manifest_exit_at = time.monotonic() - 0.5
        sm.update(
            tri_state="silent",
            task_active=False,
            sensing_active=False,
            execution_active=False,
            user_interaction=False,
        )
        assert sm.mode.value == "static"


class TestRuntimePresenceSummaryProjection:
    def test_presence_summary_exposes_formal_desktop_presence_system(self):
        with _patch_numpy():
            from core.desktop_presence_runtime import DesktopPresenceRuntime

            rt = DesktopPresenceRuntime()
            summary = rt.presence_summary()

        assert "desktop_presence_system" in summary
        system_view = summary["desktop_presence_system"]
        assert "formal_presence_modes" in system_view
        assert "state_machine" in system_view
        assert "mapping_to_runtime" in system_view
        assert "liminal_ambient_board" in system_view
        assert "foreground_hierarchy" in system_view
        assert "future_extension_home" in system_view

        coupling = system_view["mapping_to_runtime"]["runtime_coupling"]
        assert coupling["runtime_shell"] == "DesktopPresenceRuntime"
        assert coupling["subject_core"] == "OpenClawd"
        assert coupling["command_routing"] == "CommandRouter"

        hierarchy = system_view["foreground_hierarchy"]
        assert hierarchy["primary_foreground"] == "desktop_presence_layer"


class TestExistenceSurfaceReadsPresenceSummary:
    def test_subject_lifecycle_reader_calls_presence_summary_method(self):
        from core.desktop_existence_surface import DesktopExistenceSurfaceBuilder

        builder = DesktopExistenceSurfaceBuilder()
        runtime_mock = MagicMock()
        runtime_mock.presence_summary.return_value = {
            "dominant_tristate": "manifest",
            "active_session_count": 2,
            "tristate_distribution": {"manifest": 2},
        }
        with patch(
            "core.desktop_presence_runtime.get_desktop_presence_runtime",
            return_value=runtime_mock,
        ):
            snap = builder._read_subject_lifecycle()

        runtime_mock.presence_summary.assert_called_once()
        assert snap.dominant_tristate == "manifest"
        assert snap.active_session_count == 2
