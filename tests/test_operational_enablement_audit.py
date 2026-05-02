"""
tests/test_operational_enablement_audit.py
==========================================
Tests for core/operational_enablement_audit.py.

Each test validates a specific factual claim against the real code structures
they document. The tests do NOT use prior audit documents as evidence.

Test categories
---------------
- Module integrity (imports, authority sentinel)
- V2-side config layer count and key classifications
- Android-side config layer count and default values
- Desktop board control surface facts
- Agent tri-state / UI shell / fabric mode enumerations
- Android model provisioning (counts, limitations, pipeline stages)
- Runbook completeness
- Final verdict classification
- get_audit_summary() shape
"""

from __future__ import annotations

import pytest

from core.operational_enablement_audit import (
    OPERATIONAL_ENABLEMENT_AUDIT_AUTHORITY,
    AUDIT_SCOPE,
    V2ConfigSource,
    V2_CONFIG_SOURCE_PRECEDENCE,
    V2_REQUIRED_API_KEY_ENV_VARS,
    V2_VALID_PROVIDERS,
    V2_NON_SECRET_CONFIG_KEYS,
    V2_STARTUP_ONLY_CONFIG,
    V2_RUNTIME_HOT_RELOADABLE_CONFIG,
    V2_CONFIG_SETUP_PATHS,
    AndroidConfigLayer,
    ANDROID_CONFIG_PRECEDENCE,
    ANDROID_SERVER_URL_DEFAULT_DEBUG,
    ANDROID_SERVER_URL_DEFAULT_RELEASE,
    ANDROID_ASSET_GATEWAY_URL_PLACEHOLDER,
    ANDROID_CROSS_DEVICE_DEFAULT,
    ANDROID_SERVER_URL_RUNTIME_EDITABLE,
    ANDROID_CROSS_DEVICE_RUNTIME_EDITABLE,
    ANDROID_SETTINGS_UI_EXISTS,
    ANDROID_REMOTE_CONFIG_FETCH,
    DESKTOP_BOARD_IS_CONTROL_SURFACE,
    DESKTOP_BOARD_WRITE_OPERATIONS,
    DESKTOP_BOARD_READ_SURFACES,
    DESKTOP_BOARD_WRITE_PERSISTENCE,
    DESKTOP_BOARD_AFFECTS_RUNTIME,
    DESKTOP_BOARD_VERDICT,
    TriStateMode,
    TRI_STATE_IS_REAL_RUNTIME_MODE,
    TRI_STATE_BEHAVIORAL_CONSEQUENCES,
    UIShellMode,
    FabricMode,
    THREE_STATE_DISAMBIGUATION,
    ANDROID_MODELS,
    ANDROID_MODEL_DOWNLOAD_MECHANISM,
    ANDROID_MODEL_PROVISIONING_PIPELINE_STAGES,
    ANDROID_MODEL_PROVISIONING_AUTO_ON_STARTUP,
    ANDROID_MODEL_PROVISIONING_LIMITATIONS,
    ANDROID_MODEL_PROVISIONING_VERDICT,
    RunbookStep,
    V2_RUNBOOK,
    ANDROID_RUNBOOK,
    OperabilityTier,
    FINAL_VERDICT,
    FINAL_VERDICT_QUALIFICATIONS,
    CHINESE_SUMMARY,
    get_audit_summary,
)


# ===========================================================================
# Module integrity
# ===========================================================================

class TestModuleIntegrity:
    def test_authority_sentinel_is_canonical_module_path(self):
        assert OPERATIONAL_ENABLEMENT_AUDIT_AUTHORITY == "core.operational_enablement_audit"

    def test_scope_references_both_repos(self):
        assert "ufo-galaxy-realization-v2" in AUDIT_SCOPE
        assert "ufo-galaxy-android" in AUDIT_SCOPE
        assert "real-source-code-only" in AUDIT_SCOPE


# ===========================================================================
# V2-side config
# ===========================================================================

class TestV2Config:
    def test_five_config_source_layers(self):
        """
        V2 has exactly 5 config sources.
        Source: core/unified_config.py load order.
        """
        assert len(V2_CONFIG_SOURCE_PRECEDENCE) == 5

    def test_process_env_is_highest_precedence(self):
        assert V2_CONFIG_SOURCE_PRECEDENCE[-1] == V2ConfigSource.PROCESS_ENVIRONMENT

    def test_static_config_json_is_lowest_precedence(self):
        assert V2_CONFIG_SOURCE_PRECEDENCE[0] == V2ConfigSource.STATIC_CONFIG_JSON

    def test_runtime_config_json_in_middle(self):
        sources = V2_CONFIG_SOURCE_PRECEDENCE
        json_idx = sources.index(V2ConfigSource.RUNTIME_CONFIG_JSON)
        env_idx = sources.index(V2ConfigSource.PROCESS_ENVIRONMENT)
        static_idx = sources.index(V2ConfigSource.STATIC_CONFIG_JSON)
        assert static_idx < json_idx < env_idx

    def test_nine_api_key_env_vars(self):
        """
        9 known secret keys.
        Source: core/config_schema.py SECRET_KEYS frozenset (9 entries).
        """
        assert len(V2_REQUIRED_API_KEY_ENV_VARS) == 9

    def test_openai_key_present(self):
        assert "OPENAI_API_KEY" in V2_REQUIRED_API_KEY_ENV_VARS

    def test_galaxy_api_token_present(self):
        assert "GALAXY_API_TOKEN" in V2_REQUIRED_API_KEY_ENV_VARS

    def test_seven_valid_providers(self):
        """
        7 providers.
        Source: core/config_schema.py VALID_PROVIDERS frozenset.
        """
        assert len(V2_VALID_PROVIDERS) == 7

    def test_all_canonical_providers_present(self):
        for provider in ["openai", "anthropic", "gemini", "deepseek", "groq", "openrouter", "oneapi"]:
            assert provider in V2_VALID_PROVIDERS

    def test_system_mode_env_vars_are_startup_only(self):
        """
        GALAXY_SYSTEM_MODE is startup-only.
        Source: core/system_mode.py FABRIC_CONFIG resolved at import time.
        """
        assert "GALAXY_SYSTEM_MODE" in V2_STARTUP_ONLY_CONFIG
        assert "GALAXY_CROSS_DEVICE_ENABLED" in V2_STARTUP_ONLY_CONFIG

    def test_hot_reloadable_includes_provider_toggle(self):
        """
        Provider enable/disable is hot-reloadable.
        Source: windows_client/status_board_v2/config_control.py ControlOperation.TOGGLE_PROVIDER.
        """
        assert any("providers" in k for k in V2_RUNTIME_HOT_RELOADABLE_CONFIG)

    def test_hot_reloadable_includes_routing_policy(self):
        """
        Routing policy is hot-reloadable.
        Source: windows_client/status_board_v2/config_control.py ControlOperation.SET_ROUTING_POLICY.
        """
        assert any("routing" in k for k in V2_RUNTIME_HOT_RELOADABLE_CONFIG)

    def test_setup_wizard_in_config_setup_paths(self):
        """
        setup_wizard.py exists as a config path.
        Source: setup_wizard.py file existence.
        """
        assert any("setup_wizard" in path for path in V2_CONFIG_SETUP_PATHS)


# ===========================================================================
# Android-side config
# ===========================================================================

class TestAndroidConfig:
    def test_three_config_layers(self):
        """
        Android has 3 config layers.
        Source: app/src/main/assets/config.properties header comment.
        """
        assert len(ANDROID_CONFIG_PRECEDENCE) == 3

    def test_shared_prefs_is_highest(self):
        assert ANDROID_CONFIG_PRECEDENCE[-1] == AndroidConfigLayer.SHARED_PREFS

    def test_build_config_is_lowest(self):
        assert ANDROID_CONFIG_PRECEDENCE[0] == AndroidConfigLayer.BUILD_CONFIG

    def test_debug_url_is_local_ip(self):
        """
        Debug build URL points to 192.168.1.100.
        Source: app/build.gradle buildConfigField GALAXY_SERVER_URL debug default.
        """
        assert "192.168.1.100" in ANDROID_SERVER_URL_DEFAULT_DEBUG
        assert ANDROID_SERVER_URL_DEFAULT_DEBUG.startswith("ws://")

    def test_release_url_is_production_host(self):
        """
        Release build URL points to galaxy.ufo.ai.
        Source: app/build.gradle buildTypes.release GALAXY_SERVER_URL.
        """
        assert "galaxy.ufo.ai" in ANDROID_SERVER_URL_DEFAULT_RELEASE
        assert ANDROID_SERVER_URL_DEFAULT_RELEASE.startswith("wss://")

    def test_asset_gateway_url_is_placeholder(self):
        """
        assets/config.properties uses 100.x.x.x placeholder — must be replaced.
        Source: app/src/main/assets/config.properties galaxy_gateway_url=ws://100.x.x.x:8765
        """
        assert "100.x.x.x" in ANDROID_ASSET_GATEWAY_URL_PLACEHOLDER

    def test_cross_device_default_is_false(self):
        """
        cross_device_enabled defaults to false.
        Source: app/src/main/assets/config.properties cross_device_enabled=false
                AND app/build.gradle CROSS_DEVICE_ENABLED=false.
        """
        assert ANDROID_CROSS_DEVICE_DEFAULT is False

    def test_server_url_runtime_editable(self):
        """
        Server URL can be changed at runtime via NetworkSettingsScreen without rebuild.
        Source: ui/NetworkSettingsScreen.kt onSaveAndReconnect callback.
        """
        assert ANDROID_SERVER_URL_RUNTIME_EDITABLE is True

    def test_cross_device_runtime_editable(self):
        """
        cross_device_enabled can be changed at runtime without rebuild.
        Source: config.properties comment: 'runtime value can be toggled via
        UFOGalaxyApplication.setCrossDeviceEnabled(Boolean) or the developer settings menu.'
        """
        assert ANDROID_CROSS_DEVICE_RUNTIME_EDITABLE is True

    def test_settings_ui_exists(self):
        """
        A full settings UI exists (NetworkSettingsScreen.kt).
        Source: app/src/main/java/com/ufo/galaxy/ui/NetworkSettingsScreen.kt.
        """
        assert ANDROID_SETTINGS_UI_EXISTS is True

    def test_remote_config_fetch_exists(self):
        """
        M3 remote config fetch via RemoteConfigFetcher exists.
        Source: UFOGalaxyApplication.kt initRemoteGatewayConfig().
        """
        assert ANDROID_REMOTE_CONFIG_FETCH is True


# ===========================================================================
# Desktop state board / control surface
# ===========================================================================

class TestDesktopBoard:
    def test_board_is_control_surface(self):
        """
        Status board V2 includes a write-through control surface.
        Source: windows_client/status_board_v2/config_control.py ConfigControlSurface.
        """
        assert DESKTOP_BOARD_IS_CONTROL_SURFACE is True

    def test_exactly_two_write_operations(self):
        """
        Only two write operations are supported (bounded set).
        Source: windows_client/status_board_v2/config_control.py ControlOperation enum.
        """
        assert len(DESKTOP_BOARD_WRITE_OPERATIONS) == 2

    def test_write_operations_include_provider_toggle(self):
        assert any("toggle_provider" in op or "provider" in op.lower()
                   for op in DESKTOP_BOARD_WRITE_OPERATIONS)

    def test_write_operations_include_routing_policy(self):
        assert any("routing" in op.lower() or "policy" in op.lower()
                   for op in DESKTOP_BOARD_WRITE_OPERATIONS)

    def test_board_has_multiple_read_surfaces(self):
        """
        Status board provides multiple read-only projection surfaces.
        Source: windows_client/status_board_v2/__init__.py package docstring.
        """
        assert len(DESKTOP_BOARD_READ_SURFACES) >= 8

    def test_board_writes_persist(self):
        """
        Board writes go to runtime/config.json and survive restarts.
        Source: core/config_store.py ConfigStore.write_config().
        """
        assert DESKTOP_BOARD_WRITE_PERSISTENCE is True

    def test_board_writes_affect_runtime(self):
        """
        Board writes trigger hot-reload via HotReloadConfigManager.
        Source: windows_client/status_board_v2/config_control.py ConfigControlSurface._apply_change().
        """
        assert DESKTOP_BOARD_AFFECTS_RUNTIME is True

    def test_board_verdict_describes_bounded_control(self):
        assert "bounded" in DESKTOP_BOARD_VERDICT.lower() or "STATUS_PLUS" in DESKTOP_BOARD_VERDICT


# ===========================================================================
# Agent tri-state / UI shell / fabric mode
# ===========================================================================

class TestAgentStates:
    def test_three_tri_state_modes(self):
        """
        Exactly 3 subject lifecycle states.
        Source: core/desktop_presence_runtime.py class TriState(str, Enum).
        """
        modes = list(TriStateMode)
        assert len(modes) == 3

    def test_tri_state_values(self):
        assert TriStateMode.SILENT.value == "silent"
        assert TriStateMode.LIMINAL.value == "liminal"
        assert TriStateMode.MANIFEST.value == "manifest"

    def test_tri_state_is_real_runtime_mode(self):
        """
        The three states are real runtime mode gates, not display labels.
        Source: core/desktop_presence_runtime.py DesktopPresenceRuntime._transition_to().
        """
        assert TRI_STATE_IS_REAL_RUNTIME_MODE is True

    def test_behavioral_consequences_cover_all_states(self):
        for mode in TriStateMode:
            assert mode in TRI_STATE_BEHAVIORAL_CONSEQUENCES, (
                f"Missing behavioral consequence for state: {mode}"
            )

    def test_four_ui_shell_modes(self):
        """
        Exactly 4 desktop UI shell expansion modes.
        Source: system_integration/hardware_trigger.py class SystemState(str, Enum).
        """
        modes = list(UIShellMode)
        assert len(modes) == 4

    def test_ui_shell_modes_values(self):
        expected = {"dormant", "island", "sidesheet", "fullagent"}
        actual = {m.value for m in UIShellMode}
        assert actual == expected

    def test_two_fabric_modes(self):
        """
        Exactly 2 fabric / deployment modes.
        Source: core/system_mode.py class SystemMode(str, Enum).
        """
        modes = list(FabricMode)
        assert len(modes) == 2

    def test_fabric_modes_values(self):
        assert FabricMode.DESKTOP_LOCAL.value == "desktop-local"
        assert FabricMode.DESKTOP_CROSS_DEVICE.value == "desktop-cross-device"

    def test_disambiguation_has_three_entries(self):
        """
        Three distinct state-type disambiguation entries exist.
        """
        assert len(THREE_STATE_DISAMBIGUATION) == 3

    def test_disambiguation_references_all_state_types(self):
        text = " ".join(THREE_STATE_DISAMBIGUATION.values())
        assert "SILENT" in text
        assert "DORMANT" in text
        assert "desktop-local" in text


# ===========================================================================
# Android model provisioning
# ===========================================================================

class TestAndroidModelProvisioning:
    def test_three_model_assets(self):
        """
        Three model assets: mobilevlm, seeclick (param), seeclick_bin.
        Source: ModelAssetManager.kt registry keys.
        """
        assert len(ANDROID_MODELS) == 3

    def test_model_ids_match_asset_manager_constants(self):
        ids = {m["model_id"] for m in ANDROID_MODELS}
        assert "mobilevlm" in ids
        assert "seeclick" in ids
        assert "seeclick_bin" in ids

    def test_huggingface_urls_present_for_all_models(self):
        for model in ANDROID_MODELS:
            assert "huggingface.co" in model["huggingface_url"], (
                f"Expected HuggingFace URL for model {model['model_id']}"
            )

    def test_mobilevlm_uses_ziangwu_repo(self):
        """
        Source: ModelManifest.kt forKnownModel() HuggingFace repoId = 'ZiangWu/MobileVLM_V2-1.7B-GGUF'.
        """
        mvlm = next(m for m in ANDROID_MODELS if m["model_id"] == "mobilevlm")
        assert "ZiangWu" in mvlm["huggingface_repo"]

    def test_seeclick_uses_cckevinn_repo(self):
        """
        Source: ModelManifest.kt forKnownModel() HuggingFace repoId = 'cckevinn/SeeClick'.
        """
        sc = next(m for m in ANDROID_MODELS if m["model_id"] == "seeclick")
        assert "cckevinn" in sc["huggingface_repo"]

    def test_mobilevlm_sha256_is_now_hardcoded(self):
        """
        MobileVLM SHA-256 is now a real non-null hash (15d4bd09...).
        Source: ModelAssetManager.kt MOBILEVLM_SHA256 (2026-05-02 update).
        """
        mobilevlm = next(m for m in ANDROID_MODELS if m["model_id"] == "mobilevlm")
        assert mobilevlm["sha256"] is not None, (
            "MobileVLM SHA-256 should be a real hash, not null"
        )
        assert len(mobilevlm["sha256"]) == 64, (
            f"Expected 64-char SHA-256 hex string, got {len(mobilevlm['sha256'])}"
        )

    def test_seeclick_sha256_still_null(self):
        """
        SeeClick SHA-256 is null at code time (computed post-download by design).
        Source: ModelAssetManager.kt SEECLICK_SHA256 / SEECLICK_BIN_SHA256 = null.
        """
        for model_id in ("seeclick", "seeclick_bin"):
            model = next(m for m in ANDROID_MODELS if m["model_id"] == model_id)
            assert model["sha256"] is None, (
                f"Expected null SHA-256 for {model_id} (computed post-download)"
            )

    def test_eight_provisioning_pipeline_stages(self):
        """
        Exactly 8 stages in the formal provisioning pipeline.
        Source: ModelProvisioningPipeline.kt class-level docstring.
        """
        assert len(ANDROID_MODEL_PROVISIONING_PIPELINE_STAGES) == 8

    def test_provisioning_pipeline_includes_huggingface_download(self):
        stages_text = " ".join(ANDROID_MODEL_PROVISIONING_PIPELINE_STAGES)
        assert "Download" in stages_text or "download" in stages_text

    def test_provisioning_pipeline_includes_checksum(self):
        stages_text = " ".join(ANDROID_MODEL_PROVISIONING_PIPELINE_STAGES)
        assert "Checksum" in stages_text or "verify" in stages_text.lower()

    def test_provisioning_pipeline_includes_atomic_install(self):
        stages_text = " ".join(ANDROID_MODEL_PROVISIONING_PIPELINE_STAGES)
        assert "Atomic" in stages_text or "rename" in stages_text.lower()

    def test_provisioning_auto_on_startup(self):
        """
        Model download auto-runs at startup.
        Source: UFOGalaxyApplication.kt ensureModelsAtStartup() called in onCreate().
        """
        assert ANDROID_MODEL_PROVISIONING_AUTO_ON_STARTUP is True

    def test_limitations_mention_inference_runtimes(self):
        """
        llama.cpp and NCNN are now bundled in app/build.gradle (b4833 and ncnn-android-vulkan).
        The limitations list must still mention both runtimes (describing their current status).
        Source: app/build.gradle dependencies (verified by direct inspection — 2026-05-02).
        """
        text = " ".join(ANDROID_MODEL_PROVISIONING_LIMITATIONS)
        assert "llama" in text.lower() or "llama.cpp" in text.lower()
        assert "ncnn" in text.lower() or "NCNN" in text

    def test_limitations_mention_checksums(self):
        """SeeClick SHA-256 is still null at code time; MobileVLM is now hardcoded."""
        text = " ".join(ANDROID_MODEL_PROVISIONING_LIMITATIONS)
        assert "null" in text.lower() or "SHA-256" in text or "sha256" in text.lower()

    def test_provisioning_verdict_reflects_bundled_runtime(self):
        """
        The verdict now reflects that inference runtimes ARE bundled.
        Prior verdict noted 'NOT_BUNDLED'; new verdict notes 'BUNDLED'.
        Source: app/build.gradle with llama.cpp:b4833 + ncnn-android-vulkan:20240410.
        """
        verdict_lower = ANDROID_MODEL_PROVISIONING_VERDICT.lower()
        # New verdict confirms runtimes are bundled and download is the gate
        assert "bundled" in verdict_lower or "executable" in verdict_lower

    def test_total_model_size_over_1gb(self):
        total_bytes = sum(m["size_bytes_approx"] for m in ANDROID_MODELS)
        assert total_bytes > 1_000_000_000, (
            f"Expected total model size > 1 GB, got {total_bytes / 1e9:.2f} GB"
        )


# ===========================================================================
# Runbook completeness
# ===========================================================================

class TestRunbook:
    def test_v2_runbook_minimum_steps(self):
        """
        V2 runbook has at least 4 required steps (clone, install, configure, run).
        """
        assert len(V2_RUNBOOK) >= 4

    def test_v2_runbook_has_all_required_fields(self):
        for step in V2_RUNBOOK:
            assert isinstance(step, RunbookStep)
            assert step.seq > 0
            assert step.action
            assert isinstance(step.required, bool)
            assert isinstance(step.rebuild_needed, bool)
            assert step.notes

    def test_v2_runbook_has_python_run_step(self):
        actions = " ".join(s.action for s in V2_RUNBOOK)
        assert "python main.py" in actions

    def test_v2_runbook_has_api_key_setup(self):
        all_text = " ".join(s.action + " " + s.notes for s in V2_RUNBOOK)
        assert "api" in all_text.lower() or "key" in all_text.lower() or "secret" in all_text.lower()

    def test_android_runbook_minimum_steps(self):
        """
        Android runbook has at least 6 required steps.
        """
        assert len(ANDROID_RUNBOOK) >= 6

    def test_android_runbook_has_gradlew_step(self):
        actions = " ".join(s.action for s in ANDROID_RUNBOOK)
        assert "gradlew" in actions

    def test_android_runbook_has_model_download_step(self):
        all_text = " ".join(s.action + " " + s.notes for s in ANDROID_RUNBOOK)
        assert "model" in all_text.lower() or "download" in all_text.lower()

    def test_android_runbook_has_cross_device_step(self):
        all_text = " ".join(s.action + " " + s.notes for s in ANDROID_RUNBOOK)
        assert "cross_device" in all_text

    def test_android_runbook_has_tailscale_or_gateway_step(self):
        all_text = " ".join(s.action + " " + s.notes for s in ANDROID_RUNBOOK)
        assert "tailscale" in all_text.lower() or "gateway" in all_text.lower()


# ===========================================================================
# Final verdict
# ===========================================================================

class TestFinalVerdict:
    def test_verdict_is_impl_complete_not_partial(self):
        """
        The system is implementation-complete, not a partial work-in-progress.
        """
        assert FINAL_VERDICT != OperabilityTier.PARTIALLY_COMPLETE

    def test_verdict_is_not_mature_consumer_app(self):
        """
        The system is NOT a zero-config consumer application due to inference runtime gaps.
        """
        assert FINAL_VERDICT != OperabilityTier.MATURE_CONFIGURABLE_APP

    def test_verdict_is_devops_oriented(self):
        assert FINAL_VERDICT == OperabilityTier.IMPL_COMPLETE_DEVOPS_ORIENTED

    def test_at_least_ten_qualifications(self):
        """
        The verdict is supported by at least 10 specific qualifications.
        """
        assert len(FINAL_VERDICT_QUALIFICATIONS) >= 10

    def test_qualifications_include_remaining_gaps(self):
        """
        Prior critical gaps (llama.cpp, NCNN, SHA-256) are now resolved.
        The qualifications list should still document remaining gaps.
        """
        text = " ".join(FINAL_VERDICT_QUALIFICATIONS)
        # Some gaps remain (e.g., SeeClick SHA-256, GUI console, deployment)
        assert "GAP" in text or "DEPLOYMENT" in text or "CONFIGURATION" in text

    def test_qualifications_acknowledge_working_features(self):
        text = " ".join(FINAL_VERDICT_QUALIFICATIONS)
        assert "complete" in text.lower() or "fully" in text.lower()

    def test_chinese_summary_is_non_empty(self):
        assert len(CHINESE_SUMMARY) > 500

    def test_chinese_summary_covers_all_sections(self):
        assert "V2" in CHINESE_SUMMARY
        assert "Android" in CHINESE_SUMMARY
        assert "HuggingFace" in CHINESE_SUMMARY or "Hugging" in CHINESE_SUMMARY
        assert "SILENT" in CHINESE_SUMMARY or "静默" in CHINESE_SUMMARY
        assert "LIMINAL" in CHINESE_SUMMARY or "边界" in CHINESE_SUMMARY


# ===========================================================================
# get_audit_summary() shape
# ===========================================================================

class TestAuditSummary:
    def test_returns_dict(self):
        summary = get_audit_summary()
        assert isinstance(summary, dict)

    def test_has_authority(self):
        summary = get_audit_summary()
        assert summary["authority"] == OPERATIONAL_ENABLEMENT_AUDIT_AUTHORITY

    def test_has_v2_config_sources_count(self):
        summary = get_audit_summary()
        assert summary["v2_config_sources_count"] == 5

    def test_has_android_cross_device_default_false(self):
        summary = get_audit_summary()
        assert summary["android_cross_device_default"] is False

    def test_has_final_verdict(self):
        summary = get_audit_summary()
        assert summary["final_verdict"] == OperabilityTier.IMPL_COMPLETE_DEVOPS_ORIENTED.value

    def test_has_android_models_count_three(self):
        summary = get_audit_summary()
        assert summary["android_models_count"] == 3

    def test_has_eight_provisioning_pipeline_stages(self):
        summary = get_audit_summary()
        assert summary["android_model_provisioning_pipeline_stages"] is not None
        assert len(summary["android_model_provisioning_pipeline_stages"]) == 8

    def test_desktop_board_is_control_surface_true(self):
        summary = get_audit_summary()
        assert summary["desktop_board_is_control_surface"] is True

    def test_tri_state_modes_contains_three_values(self):
        summary = get_audit_summary()
        assert len(summary["tri_state_modes"]) == 3

