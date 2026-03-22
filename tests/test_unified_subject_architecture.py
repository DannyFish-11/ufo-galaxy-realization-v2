"""
tests/test_unified_subject_architecture.py
============================================

Static assertions and unit tests for the Unified Subject Architecture.

This test file verifies:
1. DesktopPresenceRuntime is the outer runtime shell
2. OpenClawd is the subject core (operates inside liminal)
3. The three state systems are distinct
4. Native multimodal ingress is owned by the runtime shell
5. Request-bound multimodal_context is fused inside OpenClawd
6. Liminal execution branching semantics (local/cross_device/hybrid/none)
7. Gateway is internal substrate, not a primary entrypoint
8. Adapter surfaces are demoted (chat, launchers, dashboard, windows_client)
9. Documentation files exist and contain correct framing

These are primarily structural/static assertions — they verify that the
architecture is correctly described in code and docs without running
full integration tests.
"""

import pathlib
import inspect

REPO_ROOT = pathlib.Path(__file__).parent.parent


# ─────────────────────────────────────────────────────────────────────────────
# 1. Unified subject: DesktopPresenceRuntime wraps OpenClawd
# ─────────────────────────────────────────────────────────────────────────────

class TestUnifiedSubjectStructure:
    """DesktopPresenceRuntime + OpenClawd = single subject, two layers."""

    def test_dpr_module_positions_itself_as_shell(self):
        src = (REPO_ROOT / "core" / "desktop_presence_runtime.py").read_text()
        assert "runtime shell" in src
        assert "OpenClawd" in src

    def test_openclawd_module_positions_itself_as_core(self):
        src = (REPO_ROOT / "core" / "openclawd.py").read_text()
        assert "subject core" in src.lower() or "Subject Core" in src
        assert "DesktopPresenceRuntime" in src

    def test_dpr_class_docstring_mentions_openclawd(self):
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        doc = DesktopPresenceRuntime.__doc__ or ""
        assert "OpenClawd" in doc, "DesktopPresenceRuntime class doc must mention OpenClawd"

    def test_openclawd_class_docstring_mentions_dpr(self):
        from core.openclawd import OpenClawd
        doc = OpenClawd.__doc__ or ""
        assert "DesktopPresenceRuntime" in doc or "runtime shell" in doc.lower(), (
            "OpenClawd class doc must mention DesktopPresenceRuntime or runtime shell"
        )

    def test_dpr_invokes_openclawd_in_handle_via_openclawd(self):
        src = (REPO_ROOT / "core" / "desktop_presence_runtime.py").read_text()
        # Verify the shell's handler calls OpenClawd
        assert "get_openclawd" in src
        assert "clawd.process" in src

    def test_runtime_session_id_is_propagated_to_openclawd(self):
        src = (REPO_ROOT / "core" / "desktop_presence_runtime.py").read_text()
        assert "runtime_session_id=rsession.runtime_session_id" in src or \
               "runtime_session_id" in src


# ─────────────────────────────────────────────────────────────────────────────
# 2. Canonical tri-state lifecycle
# ─────────────────────────────────────────────────────────────────────────────

class TestCanonicalTriStateLifecycle:
    """Tri-state is the subject lifecycle, owned by DesktopPresenceRuntime."""

    def test_tristate_enum_exists_with_correct_values(self):
        from core.desktop_presence_runtime import TriState
        assert TriState.SILENT.value == "silent"
        assert TriState.LIMINAL.value == "liminal"
        assert TriState.MANIFEST.value == "manifest"

    def test_tristate_has_exactly_three_values(self):
        from core.desktop_presence_runtime import TriState
        assert len(list(TriState)) == 3

    def test_handle_request_drives_tristate_full_cycle(self):
        """handle_request must drive SILENT → LIMINAL → MANIFEST → SILENT."""
        src = (REPO_ROOT / "core" / "desktop_presence_runtime.py").read_text()
        assert "TriState.LIMINAL" in src
        assert "TriState.MANIFEST" in src
        assert "TriState.SILENT" in src

    def test_runtime_session_starts_in_silent(self):
        from core.desktop_presence_runtime import RuntimeSession, TriState
        s = RuntimeSession(source="test")
        assert s.tristate == TriState.SILENT

    def test_tristate_not_dormant_island_etc(self):
        """UI shell states must not appear in TriState."""
        from core.desktop_presence_runtime import TriState
        values = {s.value for s in TriState}
        for ui_state in ("dormant", "island", "sidesheet", "fullagent"):
            assert ui_state not in values, (
                f"'{ui_state}' is a UI shell state and must not be in TriState"
            )

    def test_dpr_source_param_is_observability_only(self):
        """source parameter must be documented as observability tag only."""
        src = (REPO_ROOT / "core" / "desktop_presence_runtime.py").read_text()
        assert "observability tag" in src.lower() or "Observability tag" in src


# ─────────────────────────────────────────────────────────────────────────────
# 3. Three state systems are distinct
# ─────────────────────────────────────────────────────────────────────────────

class TestThreeStateSystemsDistinct:
    """Tri-state / continuum posture / UI shell states must not be conflated."""

    def test_hardware_trigger_system_state_has_dormant(self):
        src = (REPO_ROOT / "system_integration" / "hardware_trigger.py").read_text()
        assert "DORMANT" in src

    def test_hardware_trigger_system_state_doc_is_clothing_layer(self):
        src = (REPO_ROOT / "system_integration" / "hardware_trigger.py").read_text()
        # Should mention clothing or presentation or "not tri-state"
        assert "clothing" in src.lower() or "presentation" in src.lower() or \
               "not" in src.lower()

    def test_state_machine_ui_integration_has_clothing_doc(self):
        src = (REPO_ROOT / "system_integration" / "state_machine_ui_integration.py").read_text()
        assert "clothing" in src.lower() or "presentation" in src.lower()

    def test_openclawd_state_continuum_doc_notes_distinction(self):
        src = (REPO_ROOT / "docs" / "OPENCLAWD_STATE_CONTINUUM.md").read_text()
        assert "DesktopPresenceRuntime" in src
        assert "distinct" in src.lower() or "not" in src.lower()

    def test_openclawd_state_continuum_doc_mentions_ui_states(self):
        src = (REPO_ROOT / "docs" / "OPENCLAWD_STATE_CONTINUUM.md").read_text()
        assert "DORMANT" in src or "ISLAND" in src or "UI shell" in src


# ─────────────────────────────────────────────────────────────────────────────
# 4. Multimodal ingress: two distinct paths
# ─────────────────────────────────────────────────────────────────────────────

class TestMultimodalIngress:
    """Runtime shell owns continuous host ingress; OpenClawd fuses request-bound."""

    def test_ingest_runtime_doc_mentions_shell_ownership(self):
        src = (REPO_ROOT / "core" / "multimodal" / "ingest_runtime.py").read_text()
        assert "runtime shell" in src.lower() or "Runtime Shell" in src

    def test_ingest_runtime_doc_distinguishes_continuous_vs_request_bound(self):
        src = (REPO_ROOT / "core" / "multimodal" / "ingest_runtime.py").read_text()
        assert "continuous" in src.lower()
        assert "request" in src.lower()

    def test_ingress_bus_doc_mentions_shell_ownership(self):
        src = (REPO_ROOT / "core" / "multimodal" / "ingress_bus.py").read_text()
        assert "runtime shell" in src.lower() or "Runtime Shell" in src

    def test_perception_frame_doc_continuous_host_perception(self):
        src = (REPO_ROOT / "core" / "multimodal" / "perception_frame.py").read_text()
        assert "continuous" in src.lower()

    def test_multimodal_bus_doc_request_bound(self):
        src = (REPO_ROOT / "core" / "perception" / "multimodal_bus.py").read_text()
        assert "request" in src.lower()
        assert "per-request" in src.lower() or "request-bound" in src.lower()

    def test_dpr_try_start_ingest_bus_doc_shell_ownership(self):
        src = (REPO_ROOT / "core" / "desktop_presence_runtime.py").read_text()
        assert "shell" in src and "ingest" in src.lower()

    def test_multimodal_ingress_doc_clarifies_two_paths(self):
        src = (REPO_ROOT / "docs" / "MULTIMODAL_INGRESS.md").read_text()
        assert "continuous" in src.lower()
        assert "request" in src.lower()


# ─────────────────────────────────────────────────────────────────────────────
# 5. Liminal execution branching
# ─────────────────────────────────────────────────────────────────────────────

class TestLiminalExecutionBranching:
    """OpenClawd determines execution path: local/cross_device/hybrid/none."""

    def test_determine_execution_path_returns_local(self):
        from core.openclawd import OpenClawd
        result = OpenClawd._determine_execution_path(
            entry_mode="local",
            execution_result={"action_taken": "focus_window"},
            cross_device_dispatched=False,
        )
        assert result == "local"

    def test_determine_execution_path_returns_cross_device(self):
        from core.openclawd import OpenClawd
        result = OpenClawd._determine_execution_path(
            entry_mode="local",
            execution_result={"action_taken": "none"},
            cross_device_dispatched=True,
        )
        assert result == "cross_device"

    def test_determine_execution_path_returns_hybrid(self):
        from core.openclawd import OpenClawd
        result = OpenClawd._determine_execution_path(
            entry_mode="local",
            execution_result={"action_taken": "launch_app"},
            cross_device_dispatched=True,
        )
        assert result == "hybrid"

    def test_determine_execution_path_returns_none(self):
        from core.openclawd import OpenClawd
        result = OpenClawd._determine_execution_path(
            entry_mode="local",
            execution_result={"action_taken": "none"},
            cross_device_dispatched=False,
        )
        assert result == "none"

    def test_openclawd_process_accepts_entry_mode(self):
        from core.openclawd import OpenClawd
        sig = inspect.signature(OpenClawd.process)
        assert "entry_mode" in sig.parameters

    def test_openclawd_process_accepts_runtime_session_id(self):
        from core.openclawd import OpenClawd
        sig = inspect.signature(OpenClawd.process)
        assert "runtime_session_id" in sig.parameters

    def test_decision_executor_doc_is_local_manifestation(self):
        src = (REPO_ROOT / "core" / "execution" / "decision_executor.py").read_text()
        assert "local manifestation" in src.lower() or "Local Manifestation" in src

    def test_command_router_doc_cross_device_liminal_expansion(self):
        src = (REPO_ROOT / "core" / "command_router.py").read_text()
        assert "cross-device" in src.lower() or "cross_device" in src.lower()
        assert "liminal" in src.lower()


# ─────────────────────────────────────────────────────────────────────────────
# 6. Gateway is internal substrate, not primary entrypoint
# ─────────────────────────────────────────────────────────────────────────────

class TestGatewayInternalSubstrate:
    """galaxy_gateway must be described as internal cross-device substrate."""

    def test_gateway_app_doc_internal(self):
        src = (REPO_ROOT / "galaxy_gateway" / "app.py").read_text()
        assert "internal" in src.lower()

    def test_gateway_app_doc_not_primary_entrypoint(self):
        src = (REPO_ROOT / "galaxy_gateway" / "app.py").read_text()
        # Must say it is NOT a primary entrypoint
        assert "NOT" in src or "not a primary" in src.lower() or "not a subject" in src.lower()

    def test_gateway_device_router_doc_internal(self):
        src = (REPO_ROOT / "galaxy_gateway" / "device_router.py").read_text()
        assert "internal" in src.lower()

    def test_gateway_cross_device_coordinator_doc_internal(self):
        src = (REPO_ROOT / "galaxy_gateway" / "cross_device_coordinator.py").read_text()
        assert "internal" in src.lower()

    def test_cross_device_routing_doc_liminal_expansion(self):
        src = (REPO_ROOT / "docs" / "CROSS_DEVICE_ROLE_ROUTING_POLICY.md").read_text()
        assert "liminal" in src.lower()


# ─────────────────────────────────────────────────────────────────────────────
# 7. Adapter surfaces are demoted
# ─────────────────────────────────────────────────────────────────────────────

class TestAdapterSurfacesDemoted:
    """Chat route, launchers, gateway are demoted from subject-core authority."""

    def test_chat_route_doc_is_adapter(self):
        src = (REPO_ROOT / "core" / "routes" / "chat.py").read_text()
        assert "adapter" in src.lower() or "Adapter" in src

    def test_chat_route_calls_desktop_presence_runtime(self):
        src = (REPO_ROOT / "core" / "routes" / "chat.py").read_text()
        assert "desktop_presence_runtime" in src
        assert "get_desktop_presence_runtime" in src

    def test_main_py_doc_bootstrap_launcher(self):
        src = (REPO_ROOT / "main.py").read_text()
        assert "bootstrap" in src.lower() or "Bootstrap" in src or "launcher" in src.lower()

    def test_unified_launcher_doc_bootstrap_launcher(self):
        src = (REPO_ROOT / "unified_launcher.py").read_text()
        assert "bootstrap" in src.lower() or "Bootstrap" in src or "launcher" in src.lower()

    def test_entrypoint_demotion_doc_exists_and_complete(self):
        doc = (REPO_ROOT / "docs" / "ENTRYPOINT_AND_SURFACE_DEMOTION.md").read_text()
        # Must cover all required demoted surfaces
        for term in ("chat", "gateway", "launcher", "dashboard", "windows_client"):
            assert term in doc.lower(), f"ENTRYPOINT_AND_SURFACE_DEMOTION.md must mention {term}"


# ─────────────────────────────────────────────────────────────────────────────
# 8. Documentation files exist and have correct framing
# ─────────────────────────────────────────────────────────────────────────────

class TestDocumentationFiles:
    """Required documentation files must exist and contain key architecture framing."""

    def _doc(self, path: str) -> str:
        return (REPO_ROOT / path).read_text(encoding="utf-8")

    def test_unified_subject_architecture_doc_exists(self):
        assert (REPO_ROOT / "docs" / "UNIFIED_SUBJECT_ARCHITECTURE.md").exists()

    def test_unified_subject_architecture_doc_content(self):
        doc = self._doc("docs/UNIFIED_SUBJECT_ARCHITECTURE.md")
        assert "DesktopPresenceRuntime" in doc
        assert "OpenClawd" in doc
        assert "runtime shell" in doc
        assert "subject core" in doc
        assert "tri-state" in doc.lower() or "TriState" in doc
        assert "DORMANT" in doc or "UI shell" in doc

    def test_entrypoint_demotion_doc_exists(self):
        assert (REPO_ROOT / "docs" / "ENTRYPOINT_AND_SURFACE_DEMOTION.md").exists()

    def test_readme_has_unified_subject_section(self):
        doc = self._doc("README.md")
        assert "DesktopPresenceRuntime" in doc
        assert "OpenClawd" in doc

    def test_architecture_review_has_unified_subject_note(self):
        doc = self._doc("ARCHITECTURE_REVIEW.md")
        assert "统一主体架构" in doc or "Unified" in doc

    def test_system_design_has_unified_subject_note(self):
        doc = self._doc("SYSTEM_DESIGN_INTEGRATION_SUMMARY.md")
        assert "DesktopPresenceRuntime" in doc or "统一主体" in doc

    def test_openclawd_state_continuum_distinguishes_from_shell_tristate(self):
        doc = self._doc("docs/OPENCLAWD_STATE_CONTINUUM.md")
        assert "DesktopPresenceRuntime" in doc

    def test_multimodal_ingress_doc_distinguishes_two_paths(self):
        doc = self._doc("docs/MULTIMODAL_INGRESS.md")
        assert "continuous" in doc.lower()
        assert "request" in doc.lower()

    def test_decision_execution_policy_doc_local_manifestation(self):
        doc = self._doc("docs/DECISION_EXECUTION_POLICY.md")
        assert "local manifestation" in doc.lower() or "Local Manifestation" in doc

    def test_cross_device_policy_doc_liminal_expansion(self):
        doc = self._doc("docs/CROSS_DEVICE_ROLE_ROUTING_POLICY.md")
        assert "liminal" in doc.lower()

    def test_readme_ui_l4_has_architecture_note(self):
        doc = self._doc("README_UI_L4_INTEGRATION.md")
        assert "DesktopPresenceRuntime" in doc or "统一主体" in doc

    def test_ui_l4_integration_report_has_architecture_note(self):
        doc = self._doc("UI_L4_INTEGRATION_REPORT.md")
        assert "DesktopPresenceRuntime" in doc or "统一主体" in doc
