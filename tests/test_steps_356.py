"""
tests/test_steps_356.py
=======================

Tests for the Steps 3 / 5 / 6 completion:

  Step 3 — Legacy Windows paths are hard-disabled (RuntimeError on import).
  Step 5 — RuntimeDomain enum exists and ContinuumState exposes runtime_domain.
  Step 6 — status_board.py is retired (hard-disabled); status_board_v2 is the canonical surface.
"""

from __future__ import annotations

import importlib
import pathlib
import sys
import warnings

import pytest


# ===========================================================================
# Step 3 — Hard-fail stubs raise RuntimeError on import
# ===========================================================================

_LEGACY_MODULES = [
    "windows_client.windows_mcp_server",
    "windows_client.ui_sidebar",
    "windows_client.client",
    "windows_client.desktop_automation",
]


class TestLegacyHardFail:
    """Each legacy Windows module must raise RuntimeError when imported."""

    @pytest.mark.parametrize("module_name", _LEGACY_MODULES)
    def test_raises_runtime_error_on_import(self, module_name: str):
        # Ensure a clean import each time.
        if module_name in sys.modules:
            del sys.modules[module_name]

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            with pytest.raises(RuntimeError) as exc_info:
                importlib.import_module(module_name)

        # The error message must guide the user to the replacement.
        msg = str(exc_info.value).lower()
        assert "windows_aip_client" in msg or "arbiter" in msg or "execution" in msg, (
            f"{module_name}: RuntimeError message should mention the replacement path"
        )

    @pytest.mark.parametrize("module_name", _LEGACY_MODULES)
    def test_deprecation_warning_still_emitted(self, module_name: str):
        """DeprecationWarning must be emitted BEFORE the RuntimeError fires."""
        if module_name in sys.modules:
            del sys.modules[module_name]

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            with pytest.raises(RuntimeError):
                importlib.import_module(module_name)

        dep_warns = [x for x in w if issubclass(x.category, DeprecationWarning)]
        assert len(dep_warns) >= 1, (
            f"{module_name}: expected DeprecationWarning before RuntimeError"
        )

    def test_client_source_contains_deprecation_warning(self):
        """Sanity-check: client.py source still contains warnings.warn."""
        src = (
            pathlib.Path(__file__).parent.parent
            / "windows_client"
            / "client.py"
        ).read_text()
        assert "DeprecationWarning" in src
        assert "warnings.warn" in src


# ===========================================================================
# Step 5 — RuntimeDomain enum and ContinuumState.runtime_domain
# ===========================================================================

from core.continuum.types import (
    ContinuumPhase,
    ContinuumState,
    RuntimeDomain,
    TriStatePhase,
)
from core.continuum import RuntimeDomain as RuntimeDomainFromInit


class TestRuntimeDomainEnum:
    """RuntimeDomain must have exactly the three required values."""

    def test_local_value(self):
        assert RuntimeDomain.LOCAL.value == "local"

    def test_cross_device_value(self):
        assert RuntimeDomain.CROSS_DEVICE.value == "cross_device"

    def test_transition_value(self):
        assert RuntimeDomain.TRANSITION.value == "transition"

    def test_is_str_enum(self):
        assert isinstance(RuntimeDomain.LOCAL, str)

    def test_three_members(self):
        assert len(list(RuntimeDomain)) == 3

    def test_exported_from_init(self):
        assert RuntimeDomainFromInit is RuntimeDomain

    def test_in_all(self):
        import core.continuum as cc
        assert "RuntimeDomain" in cc.__all__


class TestContinuumStateRuntimeDomain:
    """ContinuumState must expose runtime_domain as an additive, optional field."""

    def test_default_is_none(self):
        state = ContinuumState(phase=ContinuumPhase.FORMLESS)
        assert state.runtime_domain is None

    def test_accepts_local(self):
        state = ContinuumState(
            phase=ContinuumPhase.MANIFEST,
            runtime_domain=RuntimeDomain.LOCAL,
        )
        assert state.runtime_domain is RuntimeDomain.LOCAL

    def test_accepts_cross_device(self):
        state = ContinuumState(
            phase=ContinuumPhase.MANIFEST,
            runtime_domain=RuntimeDomain.CROSS_DEVICE,
        )
        assert state.runtime_domain is RuntimeDomain.CROSS_DEVICE

    def test_accepts_transition(self):
        state = ContinuumState(
            phase=ContinuumPhase.LIMINAL,
            runtime_domain=RuntimeDomain.TRANSITION,
        )
        assert state.runtime_domain is RuntimeDomain.TRANSITION

    def test_serialises_to_dict(self):
        state = ContinuumState(
            phase=ContinuumPhase.MANIFEST,
            runtime_domain=RuntimeDomain.LOCAL,
        )
        d = state.model_dump()
        assert d["runtime_domain"] == "local"

    def test_none_serialises_to_null(self):
        state = ContinuumState(phase=ContinuumPhase.FORMLESS)
        d = state.model_dump()
        assert d["runtime_domain"] is None

    def test_formless_default_has_none_domain(self):
        state = ContinuumState.formless_default()
        assert state.runtime_domain is None

    def test_tri_state_phase_still_works_alongside_domain(self):
        """runtime_domain must not break the existing tri_state_phase property."""
        state = ContinuumState(
            phase=ContinuumPhase.MANIFEST,
            runtime_domain=RuntimeDomain.CROSS_DEVICE,
        )
        assert state.tri_state_phase is TriStatePhase.MANIFEST
        assert state.runtime_domain is RuntimeDomain.CROSS_DEVICE

    def test_existing_api_consumers_unbroken(self):
        """ContinuumState without runtime_domain must still work (additive)."""
        state = ContinuumState(
            phase=ContinuumPhase.LIMINAL,
            presence_intensity=0.5,
            coherence=0.4,
        )
        # No runtime_domain provided — must not raise.
        assert state.tri_state_phase is TriStatePhase.LIMINAL
        assert state.runtime_domain is None


# ===========================================================================
# Step 6 — Minimal read-only status board
# ===========================================================================


class TestStatusBoard:
    """windows_client/status_board.py 已整体退役拆除(收口到 status_board_v2 与
    规范面板端点,见 PR-PANEL-CANONICAL / tests/test_pr7_semantic_closure.py)。
    原 11 个用例钉的是已拆除模块的 CLI/渲染契约,全部失去对象;保留本类仅钉
    "退役模块不得复活"这一条终态约束。"""

    def test_status_board_module_fully_decommissioned(self):
        import pathlib
        repo = pathlib.Path(__file__).parent.parent
        assert not (repo / "windows_client" / "status_board.py").exists(), (
            "windows_client/status_board.py 已退役拆除,不应被重新引入"
        )

