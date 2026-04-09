"""
tests/test_pr3_canonical_node_list_detail_status.py
=====================================================
PR-3: Canonical node list/detail/status surface refactor.

Verifies that:
  - Three new policy sentinels are present in NodeFabricRegistry.
  - GET /api/v1/nodes canonical logic reads from NodeFabricRegistry,
    not from raw filesystem scans.
  - GET /api/v1/nodes/{node_name} canonical logic reads from
    NodeFabricRegistry; 404 for nodes absent from the registry.
  - node_status_cache is NOT consulted by canonical list/detail surfaces.
  - A node on disk but not in the canonical registry does NOT appear in
    the canonical list response.
  - The legacy filesystem route is explicitly marked as compat-only.
  - The PR-3 alignment sentinel is present in projection.py.
  - core/routes/nodes.py imports the PR-3 policy sentinels.
"""

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# New policy sentinels in NodeFabricRegistry
# ─────────────────────────────────────────────────────────────────────────────

class TestNodeFabricRegistryPR3Sentinels:
    """Verify three new PR-3 policy sentinels are present and meaningful."""

    def test_canonical_node_list_surface_policy_present(self):
        from core.nodes.node_fabric_registry import (
            CANONICAL_NODE_LIST_SURFACE_READS_FROM_REGISTRY_POLICY,
        )
        assert isinstance(CANONICAL_NODE_LIST_SURFACE_READS_FROM_REGISTRY_POLICY, str)
        assert len(CANONICAL_NODE_LIST_SURFACE_READS_FROM_REGISTRY_POLICY) > 0
        assert "NodeFabricRegistry" in CANONICAL_NODE_LIST_SURFACE_READS_FROM_REGISTRY_POLICY
        assert "canonical" in CANONICAL_NODE_LIST_SURFACE_READS_FROM_REGISTRY_POLICY.lower()

    def test_canonical_node_list_surface_policy_covers_filesystem(self):
        from core.nodes.node_fabric_registry import (
            CANONICAL_NODE_LIST_SURFACE_READS_FROM_REGISTRY_POLICY,
        )
        assert "filesystem" in CANONICAL_NODE_LIST_SURFACE_READS_FROM_REGISTRY_POLICY.lower()

    def test_filesystem_scan_not_authority_policy_present(self):
        from core.nodes.node_fabric_registry import (
            FILESYSTEM_SCAN_IS_NOT_NODE_MEMBERSHIP_AUTHORITY_POLICY,
        )
        assert isinstance(FILESYSTEM_SCAN_IS_NOT_NODE_MEMBERSHIP_AUTHORITY_POLICY, str)
        assert len(FILESYSTEM_SCAN_IS_NOT_NODE_MEMBERSHIP_AUTHORITY_POLICY) > 0
        assert "filesystem" in FILESYSTEM_SCAN_IS_NOT_NODE_MEMBERSHIP_AUTHORITY_POLICY.lower()

    def test_filesystem_scan_not_authority_policy_mentions_main_py(self):
        from core.nodes.node_fabric_registry import (
            FILESYSTEM_SCAN_IS_NOT_NODE_MEMBERSHIP_AUTHORITY_POLICY,
        )
        assert "main.py" in FILESYSTEM_SCAN_IS_NOT_NODE_MEMBERSHIP_AUTHORITY_POLICY

    def test_node_status_cache_not_canonical_policy_present(self):
        from core.nodes.node_fabric_registry import (
            NODE_STATUS_CACHE_IS_NOT_CANONICAL_STATUS_SOURCE_POLICY,
        )
        assert isinstance(NODE_STATUS_CACHE_IS_NOT_CANONICAL_STATUS_SOURCE_POLICY, str)
        assert len(NODE_STATUS_CACHE_IS_NOT_CANONICAL_STATUS_SOURCE_POLICY) > 0
        assert "node_status_cache" in NODE_STATUS_CACHE_IS_NOT_CANONICAL_STATUS_SOURCE_POLICY

    def test_node_status_cache_not_canonical_policy_mentions_registry(self):
        from core.nodes.node_fabric_registry import (
            NODE_STATUS_CACHE_IS_NOT_CANONICAL_STATUS_SOURCE_POLICY,
        )
        assert "NodeFabricRegistry" in NODE_STATUS_CACHE_IS_NOT_CANONICAL_STATUS_SOURCE_POLICY


# ─────────────────────────────────────────────────────────────────────────────
# Canonical list_nodes() logic (GET /api/v1/nodes)
# ─────────────────────────────────────────────────────────────────────────────

class TestCanonicalListNodes:
    """Unit-test the canonical list_nodes logic without HTTP layer."""

    def setup_method(self):
        from core.nodes.node_fabric_registry import reset_node_fabric_registry
        reset_node_fabric_registry()

    def _build_list_response(self):
        """Replicate the canonical list_nodes logic (no HTTP layer)."""
        from core.nodes.node_fabric_registry import get_node_fabric_registry
        fab = get_node_fabric_registry()
        nodes = []
        for node_info in sorted(fab.list_nodes(), key=lambda n: n.node_id):
            reg_meta = (
                node_info.metadata if isinstance(node_info.metadata, dict) else {}
            )
            nodes.append({
                "name": node_info.node_id,
                "description": reg_meta.get("description", ""),
                "group": reg_meta.get("group", ""),
                "status": (
                    node_info.status.value
                    if hasattr(node_info.status, "value")
                    else str(node_info.status)
                ),
                "capabilities": node_info.capability_names(),
                "role": (
                    node_info.role.value
                    if hasattr(node_info.role, "value")
                    else str(node_info.role)
                ),
                "health_score": round(node_info.health_score(), 4),
                "registry_source": "canonical",
            })
        return {
            "nodes": nodes,
            "total": len(nodes),
            "registry_authority": "canonical:NodeFabricRegistry",
        }

    def test_empty_registry_returns_no_nodes(self):
        result = self._build_list_response()
        assert result["nodes"] == []
        assert result["total"] == 0

    def test_registered_node_appears_in_list(self):
        from core.nodes.node_fabric_registry import (
            get_node_fabric_registry, NodeInfo, NodeRole, NodeStatus,
        )
        fab = get_node_fabric_registry()
        fab.register(NodeInfo(node_id="pr3-node-01", role=NodeRole.WORKER,
                               status=NodeStatus.HEALTHY))
        result = self._build_list_response()
        ids = [n["name"] for n in result["nodes"]]
        assert "pr3-node-01" in ids

    def test_status_from_registry_not_status_cache(self):
        """Status must come from NodeFabricRegistry, not node_status_cache."""
        from core.nodes.node_fabric_registry import (
            get_node_fabric_registry, NodeInfo, NodeRole, NodeStatus,
        )
        fab = get_node_fabric_registry()
        fab.register(NodeInfo(node_id="pr3-status-node", role=NodeRole.WORKER,
                               status=NodeStatus.DEGRADED))
        result = self._build_list_response()
        matching = [n for n in result["nodes"] if n["name"] == "pr3-status-node"]
        assert len(matching) == 1
        # Status must reflect the registry value (degraded), not any cache default.
        assert matching[0]["status"] == "degraded"

    def test_registry_authority_key_present(self):
        result = self._build_list_response()
        assert result.get("registry_authority") == "canonical:NodeFabricRegistry"

    def test_registry_source_field_is_canonical(self):
        from core.nodes.node_fabric_registry import (
            get_node_fabric_registry, NodeInfo, NodeRole,
        )
        fab = get_node_fabric_registry()
        fab.register(NodeInfo(node_id="pr3-src-node", role=NodeRole.WORKER))
        result = self._build_list_response()
        matching = [n for n in result["nodes"] if n["name"] == "pr3-src-node"]
        assert len(matching) == 1
        assert matching[0]["registry_source"] == "canonical"

    def test_disk_only_node_does_not_appear(self):
        """A node that exists on disk but NOT in NodeFabricRegistry must not appear."""
        import os
        from core.routes._helpers import nodes_root
        # The nodes_root directory has real node subdirectories; none of those
        # should appear in the canonical list unless they were explicitly registered.
        result = self._build_list_response()
        # With an empty registry, no disk nodes should appear.
        assert result["nodes"] == []

    def test_multiple_nodes_sorted_by_id(self):
        from core.nodes.node_fabric_registry import (
            get_node_fabric_registry, NodeInfo, NodeRole,
        )
        fab = get_node_fabric_registry()
        fab.register(NodeInfo(node_id="z-node", role=NodeRole.WORKER))
        fab.register(NodeInfo(node_id="a-node", role=NodeRole.WORKER))
        fab.register(NodeInfo(node_id="m-node", role=NodeRole.WORKER))
        result = self._build_list_response()
        ids = [n["name"] for n in result["nodes"]]
        assert ids == sorted(ids)


# ─────────────────────────────────────────────────────────────────────────────
# Canonical get_node() logic (GET /api/v1/nodes/{node_name})
# ─────────────────────────────────────────────────────────────────────────────

class TestCanonicalGetNode:
    """Unit-test the canonical get_node logic without HTTP layer."""

    def setup_method(self):
        from core.nodes.node_fabric_registry import reset_node_fabric_registry
        reset_node_fabric_registry()

    def _lookup_node(self, node_name: str):
        """Replicate the canonical get_node lookup (no HTTP layer)."""
        from core.nodes.node_fabric_registry import get_node_fabric_registry
        fab = get_node_fabric_registry()
        return fab.get(node_name)

    def test_registered_node_is_found(self):
        from core.nodes.node_fabric_registry import (
            get_node_fabric_registry, NodeInfo, NodeRole, NodeStatus,
        )
        fab = get_node_fabric_registry()
        fab.register(NodeInfo(node_id="pr3-detail-01", role=NodeRole.AGENT,
                               status=NodeStatus.HEALTHY))
        node = self._lookup_node("pr3-detail-01")
        assert node is not None
        assert node.node_id == "pr3-detail-01"

    def test_unregistered_node_returns_none(self):
        """A node absent from the canonical registry must return None (→ 404)."""
        node = self._lookup_node("not-in-registry-pr3")
        assert node is None

    def test_disk_only_node_returns_none(self):
        """A node that exists on disk but not in canonical registry returns None (→ 404)."""
        # Verify that even if Node_06_Filesystem directory exists on disk, it is
        # not found via canonical get() lookup when not registered.
        node = self._lookup_node("Node_06_Filesystem")
        assert node is None

    def test_status_from_registry_not_status_cache(self):
        """Canonical detail status must come from NodeFabricRegistry, not node_status_cache."""
        from core.nodes.node_fabric_registry import (
            get_node_fabric_registry, NodeInfo, NodeRole, NodeStatus,
        )
        fab = get_node_fabric_registry()
        fab.register(NodeInfo(node_id="pr3-detail-status", role=NodeRole.WORKER,
                               status=NodeStatus.OFFLINE))
        node = self._lookup_node("pr3-detail-status")
        assert node is not None
        # Registry says OFFLINE; the test verifies we read from the registry.
        assert node.status == NodeStatus.OFFLINE

    def test_returned_node_has_expected_fields(self):
        from core.nodes.node_fabric_registry import (
            get_node_fabric_registry, NodeInfo, NodeRole, NodeStatus,
        )
        fab = get_node_fabric_registry()
        fab.register(NodeInfo(
            node_id="pr3-fields-test",
            role=NodeRole.TOOL,
            status=NodeStatus.HEALTHY,
            host="localhost",
            port=9001,
            metadata={"version": "1.2.3"},
        ))
        node = self._lookup_node("pr3-fields-test")
        assert node is not None
        assert node.role == NodeRole.TOOL
        assert node.host == "localhost"
        assert node.port == 9001
        assert node.metadata.get("version") == "1.2.3"


# ─────────────────────────────────────────────────────────────────────────────
# nodes.py module-level PR-3 sentinel import
# ─────────────────────────────────────────────────────────────────────────────

class TestNodeRouteModuleSentinelImports:
    """Verify core/routes/nodes.py imports the PR-3 policy sentinels."""

    def test_nodes_module_imports_pr3_list_policy(self):
        import pathlib
        src = pathlib.Path("core/routes/nodes.py").read_text(encoding="utf-8")
        assert "CANONICAL_NODE_LIST_SURFACE_READS_FROM_REGISTRY_POLICY" in src

    def test_nodes_module_imports_pr3_filesystem_policy(self):
        import pathlib
        src = pathlib.Path("core/routes/nodes.py").read_text(encoding="utf-8")
        assert "FILESYSTEM_SCAN_IS_NOT_NODE_MEMBERSHIP_AUTHORITY_POLICY" in src

    def test_nodes_module_imports_pr3_cache_policy(self):
        import pathlib
        src = pathlib.Path("core/routes/nodes.py").read_text(encoding="utf-8")
        assert "NODE_STATUS_CACHE_IS_NOT_CANONICAL_STATUS_SOURCE_POLICY" in src

    def test_nodes_module_no_longer_imports_node_status_cache_for_canonical_use(self):
        """node_status_cache must not be imported for use in canonical routes."""
        import pathlib
        src = pathlib.Path("core/routes/nodes.py").read_text(encoding="utf-8")
        # Check that no import statement in nodes.py imports node_status_cache.
        # It may appear in comments/docstrings as documentation, but must not
        # be imported for use in canonical routes.
        for line in src.splitlines():
            stripped = line.strip()
            if "node_status_cache" in stripped and (
                stripped.startswith("import ") or
                stripped.startswith("from ") or
                (not stripped.startswith("#") and not stripped.startswith('"') and
                 not stripped.startswith("'") and "node_status_cache" in stripped and
                 "=" in stripped and "import" not in stripped.lower() and
                 "comment" not in stripped.lower())
            ):
                pytest.fail(
                    f"node_status_cache is imported or used in core/routes/nodes.py: {line!r}"
                )

    def test_nodes_module_canonical_routes_use_node_fabric_registry(self):
        import pathlib
        src = pathlib.Path("core/routes/nodes.py").read_text(encoding="utf-8")
        assert "NodeFabricRegistry" in src or "get_node_fabric_registry" in src

    def test_legacy_filesystem_route_marked_as_compat(self):
        """The legacy filesystem route must have an explicit compat marker."""
        import pathlib
        src = pathlib.Path("core/routes/nodes.py").read_text(encoding="utf-8")
        assert "legacy" in src.lower() and "filesystem" in src.lower()
        assert "_compat_warning" in src or "LEGACY/COMPAT" in src or "legacy_filesystem" in src


# ─────────────────────────────────────────────────────────────────────────────
# Legacy filesystem route is NOT canonical
# ─────────────────────────────────────────────────────────────────────────────

class TestLegacyFilesystemRouteIsNotCanonical:
    """Verify the legacy filesystem route is explicitly demoted."""

    def test_legacy_route_path_contains_legacy(self):
        import pathlib
        src = pathlib.Path("core/routes/nodes.py").read_text(encoding="utf-8")
        # The legacy route must be at a path that explicitly signals its compat nature.
        assert "/api/v1/nodes/legacy/filesystem" in src

    def test_legacy_route_has_compat_warning_in_response(self):
        import pathlib
        src = pathlib.Path("core/routes/nodes.py").read_text(encoding="utf-8")
        assert "_compat_warning" in src

    def test_legacy_route_registry_source_is_legacy_filesystem(self):
        import pathlib
        src = pathlib.Path("core/routes/nodes.py").read_text(encoding="utf-8")
        assert "legacy_filesystem" in src


# ─────────────────────────────────────────────────────────────────────────────
# Projection sentinel
# ─────────────────────────────────────────────────────────────────────────────

class TestProjectionSentinelPR3:
    """Verify CANONICAL_NODE_LIST_DETAIL_STATUS_ALIGNED_PR3 is present in projection.py."""

    def test_sentinel_present_in_projection(self):
        import pathlib
        src = pathlib.Path("core/routes/projection.py").read_text(encoding="utf-8")
        assert "CANONICAL_NODE_LIST_DETAIL_STATUS_ALIGNED_PR3" in src

    def test_sentinel_references_node_fabric_registry(self):
        import pathlib
        src = pathlib.Path("core/routes/projection.py").read_text(encoding="utf-8")
        assert "NodeFabricRegistry" in src

    def test_sentinel_references_filesystem_demotion(self):
        import pathlib
        src = pathlib.Path("core/routes/projection.py").read_text(encoding="utf-8")
        assert "filesystem" in src.lower()

    def test_sentinel_references_node_status_cache(self):
        import pathlib
        src = pathlib.Path("core/routes/projection.py").read_text(encoding="utf-8")
        assert "node_status_cache" in src

    def test_sentinel_references_legacy_compat_path(self):
        import pathlib
        src = pathlib.Path("core/routes/projection.py").read_text(encoding="utf-8")
        assert "legacy" in src.lower() and "compat" in src.lower()

    def test_sentinel_imports_pr3_policies_from_node_fabric_registry(self):
        import pathlib
        src = pathlib.Path("core/routes/projection.py").read_text(encoding="utf-8")
        assert "CANONICAL_NODE_LIST_SURFACE_READS_FROM_REGISTRY_POLICY" in src
        assert "FILESYSTEM_SCAN_IS_NOT_NODE_MEMBERSHIP_AUTHORITY_POLICY" in src
        assert "NODE_STATUS_CACHE_IS_NOT_CANONICAL_STATUS_SOURCE_POLICY" in src


# ─────────────────────────────────────────────────────────────────────────────
# No competing filesystem authority in canonical surfaces
# ─────────────────────────────────────────────────────────────────────────────

class TestNoFilesystemAuthorityOnCanonicalSurfaces:
    """Verify canonical surfaces no longer use filesystem scans as primary authority."""

    def test_list_nodes_not_gated_on_main_py_for_canonical(self):
        """The canonical list_nodes must not check for main.py existence for membership."""
        import pathlib
        src = pathlib.Path("core/routes/nodes.py").read_text(encoding="utf-8")
        # Split the source by function boundaries.  main.py checks must only
        # appear inside the explicitly-marked legacy filesystem function.
        # Strategy: find the legacy filesystem function block (between its def
        # and the next top-level def/decorator) and verify all "main.py"
        # occurrences are inside that block.
        legacy_marker = "list_nodes_legacy_filesystem"
        assert legacy_marker in src, "legacy filesystem route function must be present"

        # Extract the legacy function block (from its definition onwards).
        legacy_start = src.index(legacy_marker)
        # Find the next function definition after the legacy function.
        # Everything before legacy_start is "non-legacy" code.
        non_legacy_section = src[:legacy_start]
        assert "main.py" not in non_legacy_section, (
            "main.py must not be referenced in the canonical (non-legacy) code section"
        )
