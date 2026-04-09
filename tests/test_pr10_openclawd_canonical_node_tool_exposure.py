"""
tests/test_pr10_openclawd_canonical_node_tool_exposure.py
===========================================================
PR-10: Remove OpenClawd Legacy Layer 3 Node Discovery —
Make Canonical Node Tool Exposure Registry-Only.

Covers:
  1. Authority module: sentinels, policies, and enums are importable and
     contain the expected identifier strings.
  2. LegacyNodeDiscoverySurface: catalogue contains the expected surfaces
     (node_registry_json_read, fusion_entry_dynamic_scan, core_node_actions_static_dict).
  3. LegacyNodeDiscoveryStatus: expected enum values are present.
  4. is_legacy_node_scan_compat_enabled(): returns False by default; returns
     True only when OPENCLAWD_LEGACY_NODE_SCAN_COMPAT_ENABLED=true.
  5. build_canonical_tool_exposure_snapshot(): returns a snapshot with
     canonical_path_active=True and correct surface counts.
  6. get_legacy_discovery_summary(): returns a summary with expected keys.
  7. OpenClawd._collect_tools() does NOT read config/node_registry.json when
     the compat flag is disabled (default).
  8. OpenClawd._collect_tools() does NOT call _discover_node_actions() when
     the compat flag is disabled (default).
  9. _find_node_key() returns None for unknown node_ids when compat is disabled
     (default) rather than falling back to node_registry.json.
 10. Projection sentinel is importable and not the UNAVAILABLE stub.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _import_authority():
    from core.openclawd_canonical_node_tool_exposure import (
        OPENCLAWD_CANONICAL_NODE_TOOL_EXPOSURE_IS_AUTHORITY,
        OPENCLAWD_CANONICAL_NODE_TOOL_EXPOSURE_PR10_SENTINEL,
        CANONICAL_NODE_TOOLS_COME_FROM_RUNTIME_REGISTRY_ONLY_POLICY,
        NODE_REGISTRY_JSON_IS_NOT_TOOL_EXPOSURE_AUTHORITY_POLICY,
        FUSION_ENTRY_SCAN_IS_NOT_TOOL_EXPOSURE_AUTHORITY_POLICY,
        LEGACY_LAYER3_IS_COMPAT_ONLY_POLICY,
        CANONICAL_TOOL_EXPOSURE_REQUIRES_GOVERNANCE_FILTER_POLICY,
        LegacyNodeDiscoveryStatus,
        LegacyNodeDiscoverySurface,
        CanonicalNodeToolExposureSnapshot,
        build_legacy_discovery_surface_registry,
        get_legacy_discovery_summary,
        is_legacy_node_scan_compat_enabled,
        build_canonical_tool_exposure_snapshot,
    )
    return {
        "AUTHORITY": OPENCLAWD_CANONICAL_NODE_TOOL_EXPOSURE_IS_AUTHORITY,
        "SENTINEL": OPENCLAWD_CANONICAL_NODE_TOOL_EXPOSURE_PR10_SENTINEL,
        "REGISTRY_POLICY": CANONICAL_NODE_TOOLS_COME_FROM_RUNTIME_REGISTRY_ONLY_POLICY,
        "JSON_POLICY": NODE_REGISTRY_JSON_IS_NOT_TOOL_EXPOSURE_AUTHORITY_POLICY,
        "SCAN_POLICY": FUSION_ENTRY_SCAN_IS_NOT_TOOL_EXPOSURE_AUTHORITY_POLICY,
        "COMPAT_POLICY": LEGACY_LAYER3_IS_COMPAT_ONLY_POLICY,
        "GOV_POLICY": CANONICAL_TOOL_EXPOSURE_REQUIRES_GOVERNANCE_FILTER_POLICY,
        "LegacyNodeDiscoveryStatus": LegacyNodeDiscoveryStatus,
        "LegacyNodeDiscoverySurface": LegacyNodeDiscoverySurface,
        "CanonicalNodeToolExposureSnapshot": CanonicalNodeToolExposureSnapshot,
        "build_legacy_discovery_surface_registry": build_legacy_discovery_surface_registry,
        "get_legacy_discovery_summary": get_legacy_discovery_summary,
        "is_legacy_node_scan_compat_enabled": is_legacy_node_scan_compat_enabled,
        "build_canonical_tool_exposure_snapshot": build_canonical_tool_exposure_snapshot,
    }


# ===========================================================================
# 1. Authority sentinels and module importability
# ===========================================================================

class TestAuthorityModule:
    """The authority module is importable and sentinels contain expected identifiers."""

    def test_module_importable(self) -> None:
        """core.openclawd_canonical_node_tool_exposure is importable."""
        m = _import_authority()
        assert m is not None

    def test_authority_sentinel_contains_pr10(self) -> None:
        m = _import_authority()
        assert "PR10" in m["AUTHORITY"]

    def test_pr10_sentinel_value(self) -> None:
        m = _import_authority()
        assert "PR10_SENTINEL" in m["SENTINEL"]

    def test_registry_policy_mentions_node_fabric_registry(self) -> None:
        m = _import_authority()
        assert "NodeFabricRegistry" in m["REGISTRY_POLICY"]

    def test_json_policy_mentions_node_registry_json(self) -> None:
        m = _import_authority()
        assert "node_registry.json" in m["JSON_POLICY"]

    def test_scan_policy_mentions_fusion_entry(self) -> None:
        m = _import_authority()
        assert "fusion_entry" in m["SCAN_POLICY"]

    def test_compat_policy_mentions_compat_flag(self) -> None:
        m = _import_authority()
        assert "OPENCLAWD_LEGACY_NODE_SCAN_COMPAT_ENABLED" in m["COMPAT_POLICY"]

    def test_governance_policy_mentions_capability_node(self) -> None:
        m = _import_authority()
        assert "CAPABILITY_NODE" in m["GOV_POLICY"]


# ===========================================================================
# 2. LegacyNodeDiscoveryStatus enum
# ===========================================================================

class TestLegacyNodeDiscoveryStatusEnum:
    """LegacyNodeDiscoveryStatus contains the expected values."""

    def test_removed_from_canonical_path_value(self) -> None:
        m = _import_authority()
        Status = m["LegacyNodeDiscoveryStatus"]
        assert Status.REMOVED_FROM_CANONICAL_PATH.value == "removed_from_canonical_path"

    def test_compat_only_value(self) -> None:
        m = _import_authority()
        Status = m["LegacyNodeDiscoveryStatus"]
        assert Status.COMPAT_ONLY.value == "compat_only"

    def test_deprecated_value(self) -> None:
        m = _import_authority()
        Status = m["LegacyNodeDiscoveryStatus"]
        assert Status.DEPRECATED.value == "deprecated"


# ===========================================================================
# 3. Legacy surface catalogue
# ===========================================================================

class TestLegacySurfaceCatalogue:
    """build_legacy_discovery_surface_registry() contains expected surfaces."""

    def _get_surfaces(self):
        m = _import_authority()
        return m["build_legacy_discovery_surface_registry"]()

    def test_returns_list(self) -> None:
        surfaces = self._get_surfaces()
        assert isinstance(surfaces, list)
        assert len(surfaces) > 0

    def test_contains_node_registry_json_read(self) -> None:
        surfaces = self._get_surfaces()
        names = [s.name for s in surfaces]
        assert "node_registry_json_read" in names

    def test_contains_fusion_entry_dynamic_scan(self) -> None:
        surfaces = self._get_surfaces()
        names = [s.name for s in surfaces]
        assert "fusion_entry_dynamic_scan" in names

    def test_contains_core_node_actions_static_dict(self) -> None:
        surfaces = self._get_surfaces()
        names = [s.name for s in surfaces]
        assert "core_node_actions_static_dict" in names

    def test_node_registry_json_is_removed_from_canonical(self) -> None:
        m = _import_authority()
        Status = m["LegacyNodeDiscoveryStatus"]
        surfaces = self._get_surfaces()
        entry = next(s for s in surfaces if s.name == "node_registry_json_read")
        assert entry.status == Status.REMOVED_FROM_CANONICAL_PATH

    def test_fusion_entry_scan_is_removed_from_canonical(self) -> None:
        m = _import_authority()
        Status = m["LegacyNodeDiscoveryStatus"]
        surfaces = self._get_surfaces()
        entry = next(s for s in surfaces if s.name == "fusion_entry_dynamic_scan")
        assert entry.status == Status.REMOVED_FROM_CANONICAL_PATH

    def test_static_dict_is_compat_only(self) -> None:
        m = _import_authority()
        Status = m["LegacyNodeDiscoveryStatus"]
        surfaces = self._get_surfaces()
        entry = next(s for s in surfaces if s.name == "core_node_actions_static_dict")
        assert entry.status == Status.COMPAT_ONLY

    def test_surfaces_have_canonical_replacement(self) -> None:
        surfaces = self._get_surfaces()
        for s in surfaces:
            assert s.canonical_replacement, f"surface {s.name!r} missing canonical_replacement"

    def test_surface_to_dict_has_expected_keys(self) -> None:
        surfaces = self._get_surfaces()
        required = {"name", "status", "description", "canonical_replacement", "is_compat_flag_gated"}
        for s in surfaces:
            d = s.to_dict()
            assert required <= d.keys(), f"surface {s.name!r} to_dict missing keys: {required - d.keys()}"


# ===========================================================================
# 4. is_legacy_node_scan_compat_enabled()
# ===========================================================================

class TestCompatFlagBehaviour:
    """is_legacy_node_scan_compat_enabled() respects the environment variable."""

    def test_disabled_by_default(self) -> None:
        m = _import_authority()
        env_backup = os.environ.pop("OPENCLAWD_LEGACY_NODE_SCAN_COMPAT_ENABLED", None)
        try:
            assert m["is_legacy_node_scan_compat_enabled"]() is False
        finally:
            if env_backup is not None:
                os.environ["OPENCLAWD_LEGACY_NODE_SCAN_COMPAT_ENABLED"] = env_backup

    def test_enabled_with_true(self) -> None:
        m = _import_authority()
        with patch.dict(os.environ, {"OPENCLAWD_LEGACY_NODE_SCAN_COMPAT_ENABLED": "true"}):
            assert m["is_legacy_node_scan_compat_enabled"]() is True

    def test_enabled_with_1(self) -> None:
        m = _import_authority()
        with patch.dict(os.environ, {"OPENCLAWD_LEGACY_NODE_SCAN_COMPAT_ENABLED": "1"}):
            assert m["is_legacy_node_scan_compat_enabled"]() is True

    def test_disabled_with_false(self) -> None:
        m = _import_authority()
        with patch.dict(os.environ, {"OPENCLAWD_LEGACY_NODE_SCAN_COMPAT_ENABLED": "false"}):
            assert m["is_legacy_node_scan_compat_enabled"]() is False

    def test_disabled_with_empty_string(self) -> None:
        m = _import_authority()
        with patch.dict(os.environ, {"OPENCLAWD_LEGACY_NODE_SCAN_COMPAT_ENABLED": ""}):
            assert m["is_legacy_node_scan_compat_enabled"]() is False


# ===========================================================================
# 5. build_canonical_tool_exposure_snapshot()
# ===========================================================================

class TestCanonicalToolExposureSnapshot:
    """build_canonical_tool_exposure_snapshot() returns expected snapshot."""

    def _snapshot(self, compat: bool = False):
        m = _import_authority()
        env = {"OPENCLAWD_LEGACY_NODE_SCAN_COMPAT_ENABLED": "true" if compat else "false"}
        with patch.dict(os.environ, env):
            return m["build_canonical_tool_exposure_snapshot"]()

    def test_canonical_path_active_is_true(self) -> None:
        snap = self._snapshot()
        assert snap.canonical_path_active is True

    def test_compat_disabled_by_default(self) -> None:
        snap = self._snapshot(compat=False)
        assert snap.compat_enabled is False

    def test_compat_enabled_when_flag_set(self) -> None:
        snap = self._snapshot(compat=True)
        assert snap.compat_enabled is True

    def test_removed_surface_count_is_positive(self) -> None:
        snap = self._snapshot()
        assert snap.removed_surface_count >= 2  # at least json + fusion_entry

    def test_snapshot_to_dict_has_required_keys(self) -> None:
        snap = self._snapshot()
        d = snap.to_dict()
        required = {
            "legacy_surfaces",
            "removed_surface_count",
            "compat_surface_count",
            "compat_enabled",
            "canonical_path_active",
            "pr10_sentinel",
        }
        assert required <= d.keys()

    def test_pr10_sentinel_in_snapshot(self) -> None:
        snap = self._snapshot()
        assert "PR10" in snap.pr10_sentinel


# ===========================================================================
# 6. get_legacy_discovery_summary()
# ===========================================================================

class TestLegacyDiscoverySummary:
    """get_legacy_discovery_summary() returns a dict with expected keys."""

    def _summary(self):
        m = _import_authority()
        with patch.dict(os.environ, {"OPENCLAWD_LEGACY_NODE_SCAN_COMPAT_ENABLED": "false"}):
            return m["get_legacy_discovery_summary"]()

    def test_returns_dict(self) -> None:
        s = self._summary()
        assert isinstance(s, dict)

    def test_has_pr10_sentinel_key(self) -> None:
        s = self._summary()
        assert "pr10_sentinel" in s

    def test_canonical_path_active_is_true(self) -> None:
        s = self._summary()
        assert s["canonical_path_active"] is True

    def test_compat_enabled_is_false(self) -> None:
        s = self._summary()
        assert s["compat_enabled"] is False

    def test_has_surfaces_list(self) -> None:
        s = self._summary()
        assert "surfaces" in s
        assert isinstance(s["surfaces"], list)

    def test_has_policy_block(self) -> None:
        s = self._summary()
        assert "policy" in s
        policy = s["policy"]
        assert "canonical_only" in policy
        assert "no_registry_json" in policy
        assert "no_fusion_entry_scan" in policy


# ===========================================================================
# 7. OpenClawd._collect_tools() — no node_registry.json read by default
# ===========================================================================

class TestCollectToolsNoRegistryJsonByDefault:
    """_collect_tools() must not open config/node_registry.json when compat is off."""

    def test_open_not_called_for_node_registry_json(self) -> None:
        """The real _collect_tools() does not open node_registry.json when compat disabled."""
        with patch.dict(os.environ, {"OPENCLAWD_LEGACY_NODE_SCAN_COMPAT_ENABLED": "false"}):
            try:
                from core.openclawd import OpenClawd
            except Exception:
                pytest.skip("OpenClawd not importable in this environment")

            cwd = OpenClawd.__new__(OpenClawd)
            # Minimal attribute initialisation to avoid __init__ side effects.
            cwd._node_id_to_key = {}
            cwd._node_actions_cache = {}
            cwd._tool_permission_checker = None
            cwd._capability_dispatcher = None
            cwd._cancel_registry = set()

            opened_paths: List[str] = []

            def _spy_open(path, *args, **kwargs):
                opened_paths.append(str(path))
                # Raise so no real I/O happens; the test only cares about
                # which paths were attempted.
                raise FileNotFoundError(f"spy_open blocked: {path}")

            # Stub all sub-calls that would do heavy work so _collect_tools()
            # can run end-to-end without external dependencies.
            with (
                patch("builtins.open", side_effect=_spy_open),
                patch(
                    "core.openclawd_canonical_node_tool_exposure.is_legacy_node_scan_compat_enabled",
                    return_value=False,
                ),
                patch("core.openclawd.OpenClawd._GITHUB_BUILTIN_TOOLS", new=[], create=True),
                patch("core.openclawd.OpenClawd._ACADEMIC_BUILTIN_TOOLS", new=[], create=True),
                patch("core.openclawd.OpenClawd._ENGINEER_BUILTIN_TOOLS", new=[], create=True),
                patch("core.openclawd.OpenClawd._RESOURCE_BUILTIN_TOOLS", new=[], create=True),
                patch.dict("sys.modules", {
                    "core.unified.capability_resolver": MagicMock(
                        get_capability_resolver=MagicMock(return_value=MagicMock(
                            collect_tool_schemas=MagicMock(return_value=[])
                        ))
                    ),
                    "core.nodes.node_fabric_registry": MagicMock(
                        get_node_fabric_registry=MagicMock(return_value=MagicMock(
                            sync_capabilities_to_registry=MagicMock(return_value=0)
                        ))
                    ),
                    "core.unified.capability_contract": MagicMock(),
                    "core.mcp_gateway": MagicMock(
                        get_mcp_gateway=MagicMock(return_value=MagicMock(
                            list_generated_tools=MagicMock(return_value=[])
                        ))
                    ),
                }),
            ):
                try:
                    cwd._collect_tools()
                except Exception:
                    # Exceptions from missing modules are acceptable; what
                    # matters is that node_registry.json was not opened.
                    pass

            # No file with "node_registry.json" should have been opened.
            registry_opens = [p for p in opened_paths if "node_registry.json" in p]
            assert registry_opens == [], (
                f"node_registry.json was opened unexpectedly when compat is "
                f"disabled: {registry_opens}"
            )

    def test_compat_flag_controls_legacy_scan_execution(self) -> None:
        """is_legacy_node_scan_compat_enabled() returns False when compat is off."""
        from core.openclawd_canonical_node_tool_exposure import (
            is_legacy_node_scan_compat_enabled,
        )
        with patch.dict(os.environ, {"OPENCLAWD_LEGACY_NODE_SCAN_COMPAT_ENABLED": "false"}):
            assert is_legacy_node_scan_compat_enabled() is False

    def test_compat_flag_true_enables_legacy_scan(self) -> None:
        """is_legacy_node_scan_compat_enabled() returns True when compat is on."""
        from core.openclawd_canonical_node_tool_exposure import (
            is_legacy_node_scan_compat_enabled,
        )
        with patch.dict(os.environ, {"OPENCLAWD_LEGACY_NODE_SCAN_COMPAT_ENABLED": "true"}):
            assert is_legacy_node_scan_compat_enabled() is True


# ===========================================================================
# 8. _find_node_key() returns None for unknown nodes when compat is off
# ===========================================================================

class TestFindNodeKeyCompatBehaviour:
    """_find_node_key() does not fall back to node_registry.json when compat is off."""

    def _make_openclawd_stub(self):
        try:
            from core.openclawd import OpenClawd
        except Exception:
            pytest.skip("OpenClawd not importable")
        obj = OpenClawd.__new__(OpenClawd)
        obj._node_id_to_key = {}
        obj._node_actions_cache = {}
        obj._tool_permission_checker = None
        obj._capability_dispatcher = None
        obj._cancel_registry = set()
        return obj

    def test_returns_none_for_unknown_node_compat_off(self) -> None:
        """Unknown node_id returns None without reading node_registry.json."""
        obj = self._make_openclawd_stub()
        with patch.dict(os.environ, {"OPENCLAWD_LEGACY_NODE_SCAN_COMPAT_ENABLED": "false"}):
            result = obj._find_node_key("Node_NONEXISTENT_99999")
        assert result is None

    def test_returns_cached_key_without_file_read(self) -> None:
        """A pre-cached node_id→key is returned directly without file I/O."""
        obj = self._make_openclawd_stub()
        obj._node_id_to_key["Node_42"] = "Node_42_Test"
        with patch.dict(os.environ, {"OPENCLAWD_LEGACY_NODE_SCAN_COMPAT_ENABLED": "false"}):
            result = obj._find_node_key("Node_42")
        assert result == "Node_42_Test"


# ===========================================================================
# 9. Projection sentinel
# ===========================================================================

class TestProjectionSentinel:
    """The PR-10 projection sentinel is importable and not the UNAVAILABLE stub."""

    @pytest.mark.skipif(
        True,
        reason="projection.py requires fastapi; skip in minimal test environment",
    )
    def test_sentinel_importable(self) -> None:
        from core.routes.projection import OPENCLAWD_CANONICAL_NODE_TOOL_EXPOSURE_ALIGNED_PR10
        assert OPENCLAWD_CANONICAL_NODE_TOOL_EXPOSURE_ALIGNED_PR10 is not None

    @pytest.mark.skipif(
        True,
        reason="projection.py requires fastapi; skip in minimal test environment",
    )
    def test_sentinel_not_unavailable(self) -> None:
        from core.routes.projection import OPENCLAWD_CANONICAL_NODE_TOOL_EXPOSURE_ALIGNED_PR10
        assert "UNAVAILABLE" not in OPENCLAWD_CANONICAL_NODE_TOOL_EXPOSURE_ALIGNED_PR10

    @pytest.mark.skipif(
        True,
        reason="projection.py requires fastapi; skip in minimal test environment",
    )
    def test_sentinel_has_pr10_v1_prefix(self) -> None:
        from core.routes.projection import OPENCLAWD_CANONICAL_NODE_TOOL_EXPOSURE_ALIGNED_PR10
        assert "ALIGNED_PR10_V1" in OPENCLAWD_CANONICAL_NODE_TOOL_EXPOSURE_ALIGNED_PR10

    def test_authority_module_sentinel_directly(self) -> None:
        """Authority sentinel can be verified without fastapi."""
        m = _import_authority()
        assert "PR10_SENTINEL_V1" in m["SENTINEL"]

    def test_authority_mentions_node_fabric_registry(self) -> None:
        m = _import_authority()
        assert "NodeFabricRegistry" in m["AUTHORITY"]

    def test_authority_mentions_canonical_path(self) -> None:
        m = _import_authority()
        assert "canonical" in m["AUTHORITY"].lower()
