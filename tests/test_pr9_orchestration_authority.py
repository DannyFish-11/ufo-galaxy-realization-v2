"""
tests/test_pr9_orchestration_authority.py
==========================================

PR-9: Orchestration Authority Consolidation — focused tests.

Coverage:
  1.  AuthorityRole — enum values, ROLE_CATALOG shape, helpers.
  2.  LegacyPathStatus / LegacyPathEntry / LEGACY_PATH_REGISTRY — registry
      contents, to_dict, LegacyPathStatus, LEGACY_ORCHESTRATOR_PATHS shim.
  3.  Legacy path guardrail helpers — is_legacy_path, get_legacy_entry,
      classify_path_status, emit_legacy_guardrail (log output).
  4.  classify_module — known modules, prefix matching, legacy registry
      fallback, empty/unknown strings.
  5.  authority_chain — structure and ordering.
  6.  authority_catalog — schema_version, required sections, legacy inclusion.
  7.  AuthoritySummary — factory, to_dict / from_dict round-trip, defaults.
  8.  authority_summary_for_projection — minimal keys present.
  9.  attach_authority_to_event — PR-7 integration helper.
  10. attach_authority_to_envelope_summary — PR-8 integration helper.
  11. resolve_trace_authority — trace dict annotation.
  12. Edge cases — unknown module, None values, empty strings.
"""

from __future__ import annotations

import logging
from typing import Any, Dict
from unittest.mock import patch

import pytest


# ===========================================================================
# 1. AuthorityRole
# ===========================================================================

class TestAuthorityRole:
    def test_core_values_are_strings(self):
        from core.orchestration_authority import AuthorityRole

        assert AuthorityRole.AUTHORITATIVE_ENTRYPOINT.value == "authoritative_entrypoint"
        assert AuthorityRole.EXECUTION_RUNTIME_DELEGATE.value == "execution_runtime_delegate"
        assert AuthorityRole.DAG_EXECUTION_ENGINE.value == "dag_execution_engine"
        assert AuthorityRole.ORCHESTRATION_COORDINATOR.value == "orchestration_coordinator"
        assert AuthorityRole.LEGACY_COMPATIBILITY.value == "legacy_compatibility"
        assert AuthorityRole.DEPRECATED.value == "deprecated"
        assert AuthorityRole.UNKNOWN.value == "unknown"

    def test_all_roles_in_catalog(self):
        from core.orchestration_authority import AuthorityRole, ROLE_CATALOG

        for role in AuthorityRole:
            assert role in ROLE_CATALOG, f"{role} missing from ROLE_CATALOG"

    def test_role_catalog_required_keys(self):
        from core.orchestration_authority import AuthorityRole, ROLE_CATALOG

        required_keys = {"role", "label", "description", "active"}
        for role in AuthorityRole:
            info = ROLE_CATALOG[role]
            for key in required_keys:
                assert key in info, f"ROLE_CATALOG[{role}] missing '{key}'"

    def test_role_label_returns_string(self):
        from core.orchestration_authority import AuthorityRole, role_label

        for role in AuthorityRole:
            label = role_label(role)
            assert isinstance(label, str) and label

    def test_is_authoritative_for_active_roles(self):
        from core.orchestration_authority import AuthorityRole, is_authoritative

        active_roles = {
            AuthorityRole.AUTHORITATIVE_ENTRYPOINT,
            AuthorityRole.EXECUTION_RUNTIME_DELEGATE,
            AuthorityRole.DAG_EXECUTION_ENGINE,
            AuthorityRole.ORCHESTRATION_COORDINATOR,
            AuthorityRole.LEGACY_COMPATIBILITY,
        }
        for role in active_roles:
            assert is_authoritative(role), f"Expected {role} to be active"

    def test_is_authoritative_false_for_deprecated(self):
        from core.orchestration_authority import AuthorityRole, is_authoritative

        assert not is_authoritative(AuthorityRole.DEPRECATED)

    def test_is_legacy_or_deprecated(self):
        from core.orchestration_authority import AuthorityRole, is_legacy_or_deprecated

        assert is_legacy_or_deprecated(AuthorityRole.LEGACY_COMPATIBILITY)
        assert is_legacy_or_deprecated(AuthorityRole.DEPRECATED)
        assert not is_legacy_or_deprecated(AuthorityRole.AUTHORITATIVE_ENTRYPOINT)

    def test_role_descriptions_non_empty(self):
        from core.orchestration_authority import AuthorityRole, ROLE_DESCRIPTIONS

        for role in AuthorityRole:
            desc = ROLE_DESCRIPTIONS.get(role.value, "")
            assert isinstance(desc, str) and desc, f"ROLE_DESCRIPTIONS missing entry for {role}"

    def test_authoritative_entrypoint_catalog_has_canonical_module(self):
        from core.orchestration_authority import AuthorityRole, ROLE_CATALOG

        info = ROLE_CATALOG[AuthorityRole.AUTHORITATIVE_ENTRYPOINT]
        assert info["canonical_module"] == "core.desktop_presence_runtime"
        assert info["canonical_class"] == "DesktopPresenceRuntime"


# ===========================================================================
# 2. LegacyPathRegistry
# ===========================================================================

class TestLegacyPathRegistry:
    def test_registry_not_empty(self):
        from core.orchestration_authority import LEGACY_PATH_REGISTRY

        assert len(LEGACY_PATH_REGISTRY) > 0

    def test_constellation_runtime_known_paths_present(self):
        """All paths from core/constellation_runtime.py must be in the registry."""
        from core.orchestration_authority import LEGACY_PATH_REGISTRY

        expected = {
            "nodes.Node_110_SmartOrchestrator.server",
            "nodes.Node_110_SmartOrchestrator.main",
            "nodes.Node_81_Orchestrator.main",
            "nodes.Node_50_Transformer.task_orchestrator",
            "galaxy_gateway.orchestrator.task_orchestrator",
        }
        for path in expected:
            assert path in LEGACY_PATH_REGISTRY, f"Missing legacy path: {path}"

    def test_legacy_path_entry_to_dict(self):
        from core.orchestration_authority import LEGACY_PATH_REGISTRY

        for path, entry in LEGACY_PATH_REGISTRY.items():
            d = entry.to_dict()
            assert d["module_path"] == path
            assert "status" in d
            assert "recommendation" in d

    def test_legacy_orchestrator_paths_shim(self):
        from core.orchestration_authority import (
            LEGACY_ORCHESTRATOR_PATHS,
            LEGACY_PATH_REGISTRY,
        )

        # Shim must contain all registry keys
        for path in LEGACY_PATH_REGISTRY:
            assert path in LEGACY_ORCHESTRATOR_PATHS

    def test_legacy_path_status_values(self):
        from core.orchestration_authority import LegacyPathStatus

        assert LegacyPathStatus.LEGACY_COMPATIBILITY.value == "legacy_compatibility"
        assert LegacyPathStatus.DEPRECATED.value == "deprecated"
        assert LegacyPathStatus.ACTIVE.value == "active"

    def test_node50_is_deprecated(self):
        from core.orchestration_authority import (
            LEGACY_PATH_REGISTRY,
            LegacyPathStatus,
        )

        entry = LEGACY_PATH_REGISTRY.get("nodes.Node_50_Transformer.task_orchestrator")
        assert entry is not None
        assert entry.status == LegacyPathStatus.DEPRECATED


# ===========================================================================
# 3. Legacy path guardrail helpers
# ===========================================================================

class TestLegacyGuardrail:
    def test_is_legacy_path_known(self):
        from core.orchestration_authority import is_legacy_path

        assert is_legacy_path("nodes.Node_110_SmartOrchestrator.server")
        assert is_legacy_path("galaxy_gateway.orchestrator.task_orchestrator")

    def test_is_legacy_path_unknown(self):
        from core.orchestration_authority import is_legacy_path

        assert not is_legacy_path("core.desktop_presence_runtime")
        assert not is_legacy_path("some.completely.random.module")

    def test_get_legacy_entry_returns_entry(self):
        from core.orchestration_authority import get_legacy_entry, LegacyPathEntry

        entry = get_legacy_entry("nodes.Node_81_Orchestrator.main")
        assert entry is not None
        assert isinstance(entry, LegacyPathEntry)
        assert entry.module_path == "nodes.Node_81_Orchestrator.main"

    def test_get_legacy_entry_returns_none_for_unknown(self):
        from core.orchestration_authority import get_legacy_entry

        assert get_legacy_entry("totally.unknown.path") is None

    def test_classify_path_status_legacy(self):
        from core.orchestration_authority import classify_path_status, LegacyPathStatus

        status = classify_path_status("nodes.Node_110_SmartOrchestrator.server")
        assert status == LegacyPathStatus.LEGACY_COMPATIBILITY

    def test_classify_path_status_deprecated(self):
        from core.orchestration_authority import classify_path_status, LegacyPathStatus

        status = classify_path_status("nodes.Node_50_Transformer.task_orchestrator")
        assert status == LegacyPathStatus.DEPRECATED

    def test_classify_path_status_active_for_unknown(self):
        from core.orchestration_authority import classify_path_status, LegacyPathStatus

        status = classify_path_status("some.unknown.module.that.does.not.exist")
        assert status == LegacyPathStatus.ACTIVE

    def test_emit_legacy_guardrail_logs_warning(self, caplog):
        from core.orchestration_authority import emit_legacy_guardrail

        with caplog.at_level(logging.WARNING, logger="Galaxy.OrchestrationAuthority"):
            emit_legacy_guardrail(
                "nodes.Node_110_SmartOrchestrator.server",
                trace_id="trace_test_001",
            )

        assert any("LEGACY PATH GUARDRAIL" in m for m in caplog.messages)
        assert any("trace_test_001" in m for m in caplog.messages)

    def test_emit_legacy_guardrail_unregistered_path(self, caplog):
        from core.orchestration_authority import emit_legacy_guardrail

        with caplog.at_level(logging.WARNING, logger="Galaxy.OrchestrationAuthority"):
            emit_legacy_guardrail("some.unregistered.path")

        assert any("LEGACY PATH GUARDRAIL" in m for m in caplog.messages)

    def test_emit_legacy_guardrail_override_recommendation(self, caplog):
        from core.orchestration_authority import emit_legacy_guardrail

        with caplog.at_level(logging.WARNING, logger="Galaxy.OrchestrationAuthority"):
            emit_legacy_guardrail(
                "nodes.Node_81_Orchestrator.main",
                override_recommendation="Custom migration guide here.",
            )

        assert any("Custom migration guide here." in m for m in caplog.messages)


# ===========================================================================
# 4. classify_module
# ===========================================================================

class TestClassifyModule:
    def test_desktop_presence_runtime(self):
        from core.orchestration_authority import classify_module, AuthorityRole

        assert classify_module("core.desktop_presence_runtime") == AuthorityRole.AUTHORITATIVE_ENTRYPOINT

    def test_constellation_runtime(self):
        from core.orchestration_authority import classify_module, AuthorityRole

        assert classify_module("core.constellation_runtime") == AuthorityRole.EXECUTION_RUNTIME_DELEGATE

    def test_task_graph(self):
        from core.orchestration_authority import classify_module, AuthorityRole

        assert classify_module("core.task_graph") == AuthorityRole.DAG_EXECUTION_ENGINE

    def test_e2e_orchestrator(self):
        from core.orchestration_authority import classify_module, AuthorityRole

        assert classify_module("core.e2e_orchestrator") == AuthorityRole.ORCHESTRATION_COORDINATOR

    def test_node_110_prefix(self):
        from core.orchestration_authority import classify_module, AuthorityRole

        assert classify_module("nodes.Node_110_SmartOrchestrator.server") == AuthorityRole.LEGACY_COMPATIBILITY
        assert classify_module("nodes.Node_110_SmartOrchestrator") == AuthorityRole.LEGACY_COMPATIBILITY

    def test_node_81(self):
        from core.orchestration_authority import classify_module, AuthorityRole

        assert classify_module("nodes.Node_81_Orchestrator.main") == AuthorityRole.LEGACY_COMPATIBILITY

    def test_node_50_deprecated(self):
        from core.orchestration_authority import classify_module, AuthorityRole

        assert classify_module("nodes.Node_50_Transformer.task_orchestrator") == AuthorityRole.DEPRECATED
        assert classify_module("nodes.Node_50_Transformer") == AuthorityRole.DEPRECATED

    def test_galaxy_gateway_orchestrator(self):
        from core.orchestration_authority import classify_module, AuthorityRole

        assert classify_module("galaxy_gateway.orchestrator.task_orchestrator") == AuthorityRole.LEGACY_COMPATIBILITY

    def test_fusion_unified_orchestrator(self):
        from core.orchestration_authority import classify_module, AuthorityRole

        assert classify_module("fusion.unified_orchestrator") == AuthorityRole.LEGACY_COMPATIBILITY

    def test_orchestrator_engine(self):
        from core.orchestration_authority import classify_module, AuthorityRole

        assert classify_module("core.orchestrator_engine") == AuthorityRole.LEGACY_COMPATIBILITY

    def test_unknown_module(self):
        from core.orchestration_authority import classify_module, AuthorityRole

        assert classify_module("completely.unknown.module") == AuthorityRole.UNKNOWN

    def test_empty_string(self):
        from core.orchestration_authority import classify_module, AuthorityRole

        assert classify_module("") == AuthorityRole.UNKNOWN

    def test_submodule_prefix_match(self):
        """Submodule paths should match their parent's role."""
        from core.orchestration_authority import classify_module, AuthorityRole

        assert (
            classify_module("core.desktop_presence_runtime.DesktopPresenceRuntime")
            == AuthorityRole.AUTHORITATIVE_ENTRYPOINT
        )
        assert (
            classify_module("core.constellation_runtime.ConstellationRuntime")
            == AuthorityRole.EXECUTION_RUNTIME_DELEGATE
        )


# ===========================================================================
# 5. authority_chain
# ===========================================================================

class TestAuthorityChain:
    def test_returns_list_of_tuples(self):
        from core.orchestration_authority import authority_chain, AuthorityRole

        chain = authority_chain()
        assert isinstance(chain, list)
        assert len(chain) >= 3
        for role, module in chain:
            assert isinstance(role, AuthorityRole)
            assert isinstance(module, str)

    def test_authoritative_entrypoint_is_first(self):
        from core.orchestration_authority import authority_chain, AuthorityRole

        chain = authority_chain()
        assert chain[0][0] == AuthorityRole.AUTHORITATIVE_ENTRYPOINT

    def test_dag_engine_is_last(self):
        from core.orchestration_authority import authority_chain, AuthorityRole

        chain = authority_chain()
        assert chain[-1][0] == AuthorityRole.DAG_EXECUTION_ENGINE

    def test_no_duplicate_roles(self):
        from core.orchestration_authority import authority_chain

        chain = authority_chain()
        roles = [r for r, _ in chain]
        assert len(roles) == len(set(roles))


# ===========================================================================
# 6. authority_catalog
# ===========================================================================

class TestAuthorityCatalog:
    def test_schema_version(self):
        from core.orchestration_authority import authority_catalog

        catalog = authority_catalog()
        assert catalog["schema_version"] == 1

    def test_pr_tag(self):
        from core.orchestration_authority import authority_catalog

        catalog = authority_catalog()
        assert catalog["pr"] == "PR-9"

    def test_authority_chain_present(self):
        from core.orchestration_authority import authority_catalog

        catalog = authority_catalog()
        chain = catalog["authority_chain"]
        assert isinstance(chain, list)
        assert len(chain) >= 3

    def test_authority_chain_rank_ordering(self):
        from core.orchestration_authority import authority_catalog

        catalog = authority_catalog()
        ranks = [item["rank"] for item in catalog["authority_chain"]]
        assert ranks == sorted(ranks)

    def test_role_catalog_section(self):
        from core.orchestration_authority import authority_catalog, AuthorityRole

        catalog = authority_catalog()
        role_cat = catalog["role_catalog"]
        for role in AuthorityRole:
            assert role.value in role_cat

    def test_legacy_paths_included_by_default(self):
        from core.orchestration_authority import authority_catalog, LEGACY_PATH_REGISTRY

        catalog = authority_catalog()
        assert "legacy_paths" in catalog
        assert len(catalog["legacy_paths"]) == len(LEGACY_PATH_REGISTRY)

    def test_legacy_paths_excluded(self):
        from core.orchestration_authority import authority_catalog

        catalog = authority_catalog(include_legacy=False)
        assert "legacy_paths" not in catalog

    def test_catalog_is_json_serialisable(self):
        import json
        from core.orchestration_authority import authority_catalog

        catalog = authority_catalog()
        # Should not raise
        serialised = json.dumps(catalog)
        assert isinstance(serialised, str)

    def test_legacy_path_entry_has_required_keys(self):
        from core.orchestration_authority import authority_catalog

        catalog = authority_catalog()
        for entry in catalog["legacy_paths"]:
            assert "module_path" in entry
            assert "status" in entry
            assert "recommendation" in entry


# ===========================================================================
# 7. AuthoritySummary
# ===========================================================================

class TestAuthoritySummary:
    def test_summarise_authority_known_module(self):
        from core.orchestration_authority import summarise_authority, AuthorityRole

        summary = summarise_authority(
            "core.desktop_presence_runtime",
            trace_id="trace_001",
            runtime_session_id="rsess_001",
        )
        assert summary.role == AuthorityRole.AUTHORITATIVE_ENTRYPOINT
        assert summary.active is True
        assert summary.trace_id == "trace_001"
        assert summary.runtime_session_id == "rsess_001"
        assert summary.canonical_module == "core.desktop_presence_runtime"

    def test_summarise_authority_unknown_module(self):
        from core.orchestration_authority import summarise_authority, AuthorityRole

        summary = summarise_authority("completely.unknown.module")
        assert summary.role == AuthorityRole.UNKNOWN

    def test_summarise_authority_none_module(self):
        from core.orchestration_authority import summarise_authority, AuthorityRole

        summary = summarise_authority(None)
        assert summary.role == AuthorityRole.UNKNOWN

    def test_to_dict_round_trip(self):
        from core.orchestration_authority import (
            summarise_authority,
            AuthoritySummary,
            AuthorityRole,
        )

        summary = summarise_authority(
            "core.constellation_runtime",
            trace_id="trace_abc",
            runtime_session_id="rsess_xyz",
        )
        d = summary.to_dict()
        assert d["role"] == AuthorityRole.EXECUTION_RUNTIME_DELEGATE.value
        assert d["trace_id"] == "trace_abc"
        assert d["runtime_session_id"] == "rsess_xyz"

        restored = AuthoritySummary.from_dict(d)
        assert restored.role == summary.role
        assert restored.trace_id == summary.trace_id
        assert restored.runtime_session_id == summary.runtime_session_id

    def test_from_dict_unknown_role_defaults_to_unknown(self):
        from core.orchestration_authority import AuthoritySummary, AuthorityRole

        d = {"role": "nonexistent_role", "active": False}
        summary = AuthoritySummary.from_dict(d)
        assert summary.role == AuthorityRole.UNKNOWN

    def test_from_dict_empty_dict(self):
        from core.orchestration_authority import AuthoritySummary, AuthorityRole

        summary = AuthoritySummary.from_dict({})
        assert summary.role == AuthorityRole.UNKNOWN

    def test_extra_field_preserved(self):
        from core.orchestration_authority import summarise_authority

        summary = summarise_authority(
            "core.task_graph",
            extra={"dag_size": 5, "custom_key": "custom_value"},
        )
        d = summary.to_dict()
        assert d["extra"]["dag_size"] == 5


# ===========================================================================
# 8. authority_summary_for_projection
# ===========================================================================

class TestAuthorityProjection:
    def test_minimal_keys(self):
        from core.orchestration_authority import (
            summarise_authority,
            authority_summary_for_projection,
        )

        summary = summarise_authority(
            "core.desktop_presence_runtime",
            trace_id="trace_proj_001",
            runtime_session_id="rsess_proj_001",
        )
        proj = authority_summary_for_projection(summary)

        for key in ("role", "label", "active", "trace_id", "runtime_session_id", "canonical_module"):
            assert key in proj, f"Missing key: {key}"

    def test_active_true_for_authoritative(self):
        from core.orchestration_authority import (
            summarise_authority,
            authority_summary_for_projection,
        )

        summary = summarise_authority("core.desktop_presence_runtime")
        proj = authority_summary_for_projection(summary)
        assert proj["active"] is True

    def test_active_false_for_deprecated(self):
        from core.orchestration_authority import (
            summarise_authority,
            authority_summary_for_projection,
        )

        summary = summarise_authority("nodes.Node_50_Transformer.task_orchestrator")
        proj = authority_summary_for_projection(summary)
        assert proj["active"] is False


# ===========================================================================
# 9. attach_authority_to_event (PR-7 integration)
# ===========================================================================

class TestAttachAuthorityToEvent:
    def test_adds_orchestration_authority_key(self):
        from core.orchestration_authority import attach_authority_to_event

        event = {
            "trace_id": "trace_event_001",
            "runtime_session_id": "rsess_event_001",
            "executor_level": "system_api",
        }
        result = attach_authority_to_event(
            event,
            source_module="core.constellation_runtime",
        )
        assert "orchestration_authority" in result
        assert result["orchestration_authority"]["role"] == "execution_runtime_delegate"

    def test_original_keys_preserved(self):
        from core.orchestration_authority import attach_authority_to_event

        event = {"trace_id": "t1", "executor_level": "uia"}
        result = attach_authority_to_event(event, source_module="core.task_graph")
        assert result["trace_id"] == "t1"
        assert result["executor_level"] == "uia"

    def test_reads_source_module_from_event_dict(self):
        from core.orchestration_authority import attach_authority_to_event

        event = {
            "trace_id": "t2",
            "source_module": "core.desktop_presence_runtime",
        }
        result = attach_authority_to_event(event)
        assert result["orchestration_authority"]["role"] == "authoritative_entrypoint"

    def test_unknown_module_fallback(self):
        from core.orchestration_authority import attach_authority_to_event

        event = {"trace_id": "t3"}
        result = attach_authority_to_event(event, source_module="some.random.module")
        assert result["orchestration_authority"]["role"] == "unknown"

    def test_no_source_module(self):
        from core.orchestration_authority import attach_authority_to_event

        event = {"trace_id": "t4"}
        result = attach_authority_to_event(event)
        assert "orchestration_authority" in result


# ===========================================================================
# 10. attach_authority_to_envelope_summary (PR-8 integration)
# ===========================================================================

class TestAttachAuthorityToEnvelopeSummary:
    def test_adds_orchestration_authority_key(self):
        from core.orchestration_authority import attach_authority_to_envelope_summary

        es = {
            "trace_id": "trace_env_001",
            "role": "task",
            "envelope_class": "TaskEnvelope",
        }
        result = attach_authority_to_envelope_summary(
            es,
            source_module="core.e2e_orchestrator",
        )
        assert "orchestration_authority" in result
        assert result["orchestration_authority"]["role"] == "orchestration_coordinator"

    def test_original_keys_preserved(self):
        from core.orchestration_authority import attach_authority_to_envelope_summary

        es = {"trace_id": "t5", "role": "command"}
        result = attach_authority_to_envelope_summary(es, source_module="core.task_graph")
        assert result["trace_id"] == "t5"
        assert result["role"] == "command"


# ===========================================================================
# 11. resolve_trace_authority
# ===========================================================================

class TestResolveTraceAuthority:
    def test_adds_authority_key(self):
        from core.orchestration_authority import resolve_trace_authority

        trace = {"trace_id": "trace_rt_001", "runtime_session_id": "rsess_rt"}
        result = resolve_trace_authority(
            trace,
            source_module="core.desktop_presence_runtime",
        )
        assert "authority" in result
        assert result["authority"]["role"] == "authoritative_entrypoint"
        assert result["authority"]["active"] is True

    def test_source_module_none(self):
        from core.orchestration_authority import resolve_trace_authority

        trace = {"trace_id": "trace_rt_002"}
        result = resolve_trace_authority(trace)
        assert "authority" in result
        assert result["authority"]["role"] == "unknown"

    def test_original_fields_preserved(self):
        from core.orchestration_authority import resolve_trace_authority

        trace = {"trace_id": "trace_rt_003", "extra_field": "value"}
        result = resolve_trace_authority(trace, source_module="core.task_graph")
        assert result["trace_id"] == "trace_rt_003"
        assert result["extra_field"] == "value"


# ===========================================================================
# 12. Edge cases
# ===========================================================================

class TestEdgeCases:
    def test_classify_module_partial_match_does_not_collide(self):
        """core.desktop_presence_runtime_extension should not match desktop_presence_runtime."""
        from core.orchestration_authority import classify_module, AuthorityRole

        # A module that starts with the same text but is a different top-level module
        role = classify_module("core.desktop_presence_runtime_extra_suffix")
        # Should NOT match the authoritative entrypoint prefix rule because
        # the prefix rule requires a dot or colon separator
        assert role == AuthorityRole.UNKNOWN

    def test_authority_catalog_is_idempotent(self):
        from core.orchestration_authority import authority_catalog

        c1 = authority_catalog()
        c2 = authority_catalog()
        assert c1["schema_version"] == c2["schema_version"]
        assert len(c1["authority_chain"]) == len(c2["authority_chain"])

    def test_summarise_authority_extra_none_not_in_dict(self):
        from core.orchestration_authority import summarise_authority

        summary = summarise_authority("core.task_graph")
        d = summary.to_dict()
        assert "extra" not in d  # extra=None → not included

    def test_legacy_path_entry_is_frozen(self):
        from core.orchestration_authority import LEGACY_PATH_REGISTRY

        entry = next(iter(LEGACY_PATH_REGISTRY.values()))
        with pytest.raises((AttributeError, TypeError)):
            entry.module_path = "modified"  # type: ignore[misc]

    def test_authority_chain_immutable_copy(self):
        """authority_chain() should return an independent list copy."""
        from core.orchestration_authority import authority_chain

        c1 = authority_chain()
        c2 = authority_chain()
        c1.clear()
        assert len(c2) > 0
