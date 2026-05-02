"""
tests/test_url_config_and_android_vlm.py
=========================================
Tests for:
1. URL configuration in config_schema, config_service, config_control
2. Android inference mode configuration
3. AndroidVLMService (center-side VLM inference)
4. URLConfigSurface rendering
5. ManagementConsole rendering
6. StatusBoardV2App --management / --set-url / --set-api-key / --set-android-inference-mode
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture()
def tmp_runtime(tmp_path):
    """Create a temporary runtime directory with empty config and secrets."""
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "config.json").write_text("{}")
    (runtime / "secrets.env").write_text("")
    return runtime


@pytest.fixture()
def config_store(tmp_runtime):
    """Return a ConfigStore backed by the temp runtime directory."""
    from core.config_store import ConfigStore
    return ConfigStore(
        config_path=str(tmp_runtime / "config.json"),
        secrets_path=str(tmp_runtime / "secrets.env"),
    )


@pytest.fixture()
def config_service(config_store):
    """Return a ConfigService backed by the temp config store."""
    from core.config_service import ConfigService
    return ConfigService(store=config_store)


@pytest.fixture()
def control_surface(config_service):
    """Return a ConfigControlSurface with a mock hot-reload manager (disabled)."""
    from windows_client.status_board_v2.config_control import ConfigControlSurface
    return ConfigControlSurface(service=config_service, hot_reload_manager=None)


# ===========================================================================
# 1. Config schema: URL keys are in CONFIG_KEYS
# ===========================================================================

class TestConfigSchemaURLKeys:
    def test_gateway_url_is_config_key(self):
        from core.config_schema import CONFIG_KEYS
        assert "network.gateway_url" in CONFIG_KEYS

    def test_android_gateway_url_is_config_key(self):
        from core.config_schema import CONFIG_KEYS
        assert "network.android_gateway_url" in CONFIG_KEYS

    def test_nats_url_is_config_key(self):
        from core.config_schema import CONFIG_KEYS
        assert "network.nats_url" in CONFIG_KEYS

    def test_ats_url_is_config_key(self):
        from core.config_schema import CONFIG_KEYS
        assert "network.ats_url" in CONFIG_KEYS

    def test_webrtc_stun_url_is_config_key(self):
        from core.config_schema import CONFIG_KEYS
        assert "network.webrtc_stun_url" in CONFIG_KEYS

    def test_android_inference_mode_is_config_key(self):
        from core.config_schema import CONFIG_KEYS
        assert "android.inference_mode" in CONFIG_KEYS

    def test_valid_android_inference_modes(self):
        from core.config_schema import VALID_ANDROID_INFERENCE_MODES
        assert "center" in VALID_ANDROID_INFERENCE_MODES
        assert "local" in VALID_ANDROID_INFERENCE_MODES
        assert "hybrid" in VALID_ANDROID_INFERENCE_MODES

    def test_config_defaults_include_network(self):
        from core.config_schema import ConfigDefaults
        d = ConfigDefaults.as_dict()
        assert "network" in d
        assert "android" in d

    def test_config_defaults_android_inference_mode_is_center(self):
        from core.config_schema import ConfigDefaults
        d = ConfigDefaults.as_dict()
        assert d["android"]["inference_mode"] == "center"


# ===========================================================================
# 2. ConfigService: URL read/write
# ===========================================================================

class TestConfigServiceNetworkURLs:
    def test_set_and_get_gateway_url(self, config_service):
        config_service.set_network_url("gateway_url", "ws://10.0.0.1:8765")
        assert config_service.get_network_url("gateway_url") == "ws://10.0.0.1:8765"

    def test_set_and_get_android_gateway_url(self, config_service):
        config_service.set_network_url("android_gateway_url", "ws://10.0.0.1:8765")
        assert config_service.get_network_url("android_gateway_url") == "ws://10.0.0.1:8765"

    def test_set_and_get_nats_url(self, config_service):
        config_service.set_network_url("nats_url", "nats://10.0.0.1:4222")
        assert config_service.get_network_url("nats_url") == "nats://10.0.0.1:4222"

    def test_set_and_get_ats_url(self, config_service):
        config_service.set_network_url("ats_url", "https://10.0.0.1:8443")
        assert config_service.get_network_url("ats_url") == "https://10.0.0.1:8443"

    def test_set_and_get_webrtc_stun_url(self, config_service):
        config_service.set_network_url("webrtc_stun_url", "stun:stun.l.google.com:19302")
        assert config_service.get_network_url("webrtc_stun_url") == "stun:stun.l.google.com:19302"

    def test_empty_url_raises_value_error(self, config_service):
        with pytest.raises(ValueError, match="non-empty"):
            config_service.set_network_url("gateway_url", "")

    def test_unknown_url_key_raises_value_error(self, config_service):
        with pytest.raises(ValueError, match="Unknown network URL key"):
            config_service.set_network_url("bogus_url", "http://example.com")

    def test_get_unknown_url_key_raises_value_error(self, config_service):
        with pytest.raises(ValueError, match="Unknown network URL key"):
            config_service.get_network_url("bogus_url")

    def test_unset_url_returns_empty_string(self, config_service):
        assert config_service.get_network_url("nats_url") == ""

    def test_urls_are_persisted_in_config_json(self, config_service, config_store):
        config_service.set_network_url("gateway_url", "ws://1.2.3.4:8765")
        cfg = config_store.read_config()
        assert cfg["network"]["gateway_url"] == "ws://1.2.3.4:8765"


class TestConfigServiceAndroidInferenceMode:
    def test_set_center_mode(self, config_service):
        config_service.set_android_inference_mode("center")
        cfg = config_service._store.read_config()
        assert cfg["android"]["inference_mode"] == "center"

    def test_set_local_mode(self, config_service):
        config_service.set_android_inference_mode("local")
        cfg = config_service._store.read_config()
        assert cfg["android"]["inference_mode"] == "local"

    def test_set_hybrid_mode(self, config_service):
        config_service.set_android_inference_mode("hybrid")
        cfg = config_service._store.read_config()
        assert cfg["android"]["inference_mode"] == "hybrid"

    def test_invalid_mode_raises_value_error(self, config_service):
        with pytest.raises(ValueError, match="Invalid android inference mode"):
            config_service.set_android_inference_mode("cloud")


class TestConfigServiceValidationWarnings:
    def test_missing_gateway_url_produces_warning(self, config_service):
        result = config_service.validate()
        warning_text = " ".join(result.warnings)
        assert "gateway_url" in warning_text.lower() or "network" in warning_text.lower()

    def test_set_gateway_url_removes_warning(self, config_service):
        config_service.set_network_url("gateway_url", "ws://1.2.3.4:8765")
        result = config_service.validate()
        gateway_warnings = [w for w in result.warnings if "gateway_url" in w]
        assert len(gateway_warnings) == 0


# ===========================================================================
# 3. ConfigControlSurface: new operations
# ===========================================================================

class TestConfigControlSurfaceNetworkURL:
    def test_apply_network_url_succeeds(self, control_surface):
        result = control_surface.apply_network_url("gateway_url", "ws://10.0.0.1:8765")
        assert result.succeeded is True
        assert "network.gateway_url" in result.last_applied_key

    def test_apply_network_url_empty_key_fails(self, control_surface):
        result = control_surface.apply_network_url("", "ws://10.0.0.1:8765")
        assert result.succeeded is False
        assert "non-empty" in result.error.lower()

    def test_apply_network_url_empty_value_fails(self, control_surface):
        result = control_surface.apply_network_url("gateway_url", "")
        assert result.succeeded is False

    def test_apply_network_url_invalid_key_fails(self, control_surface):
        result = control_surface.apply_network_url("bogus_url", "ws://x")
        assert result.succeeded is False
        assert "Unknown network URL key" in result.error


class TestConfigControlSurfaceAPIKey:
    def test_apply_provider_api_key_succeeds(self, control_surface):
        result = control_surface.apply_provider_api_key("openai", "sk-test-key")
        assert result.succeeded is True
        # Key value must not appear in feedback
        assert "sk-test-key" not in result.last_applied_key
        assert "[set]" in result.last_applied_key

    def test_apply_provider_api_key_empty_provider_fails(self, control_surface):
        result = control_surface.apply_provider_api_key("", "sk-key")
        assert result.succeeded is False

    def test_apply_provider_api_key_empty_key_fails(self, control_surface):
        result = control_surface.apply_provider_api_key("openai", "")
        assert result.succeeded is False

    def test_apply_provider_api_key_invalid_provider_fails(self, control_surface):
        result = control_surface.apply_provider_api_key("nonexistent", "sk-key")
        assert result.succeeded is False


class TestConfigControlSurfaceAndroidMode:
    def test_apply_android_inference_mode_center(self, control_surface):
        result = control_surface.apply_android_inference_mode("center")
        assert result.succeeded is True
        assert "center" in result.last_applied_key

    def test_apply_android_inference_mode_local(self, control_surface):
        result = control_surface.apply_android_inference_mode("local")
        assert result.succeeded is True

    def test_apply_android_inference_mode_invalid(self, control_surface):
        result = control_surface.apply_android_inference_mode("cloud")
        assert result.succeeded is False

    def test_apply_dispatcher_routes_to_set_android_inference_mode(self, control_surface):
        from windows_client.status_board_v2.config_control import ControlOperation
        result = control_surface.apply(
            ControlOperation.SET_ANDROID_INFERENCE_MODE,
            mode="center",
        )
        assert result.succeeded is True


class TestConfigControlSurfaceDispatcher:
    def test_apply_set_network_url_via_dispatcher(self, control_surface):
        from windows_client.status_board_v2.config_control import ControlOperation
        result = control_surface.apply(
            ControlOperation.SET_NETWORK_URL,
            url_key="nats_url",
            url_value="nats://10.0.0.1:4222",
        )
        assert result.succeeded is True

    def test_apply_set_provider_api_key_via_dispatcher(self, control_surface):
        from windows_client.status_board_v2.config_control import ControlOperation
        result = control_surface.apply(
            ControlOperation.SET_PROVIDER_API_KEY,
            provider="openai",
            api_key="sk-test",
        )
        assert result.succeeded is True

    def test_unknown_operation_fails(self, control_surface):
        from windows_client.status_board_v2.config_control import ControlOperation
        result = control_surface.apply("bogus_op")  # type: ignore
        assert result.succeeded is False


# ===========================================================================
# 4. AndroidVLMService
# ===========================================================================

class TestAndroidVLMServiceInit:
    def test_singleton(self):
        from galaxy_gateway.android_vlm_service import (
            get_android_vlm_service,
            reset_android_vlm_service,
        )
        reset_android_vlm_service()
        s1 = get_android_vlm_service()
        s2 = get_android_vlm_service()
        assert s1 is s2
        reset_android_vlm_service()

    def test_reset_creates_new_instance(self):
        from galaxy_gateway.android_vlm_service import (
            get_android_vlm_service,
            reset_android_vlm_service,
        )
        reset_android_vlm_service()
        s1 = get_android_vlm_service()
        reset_android_vlm_service()
        s2 = get_android_vlm_service()
        assert s1 is not s2
        reset_android_vlm_service()


class TestAndroidVLMServiceModelChecksums:
    def test_checksum_registry_has_three_models(self):
        from galaxy_gateway.android_vlm_service import ANDROID_MODEL_CHECKSUMS
        assert len(ANDROID_MODEL_CHECKSUMS) == 3

    def test_checksum_registry_has_mobilevlm(self):
        from galaxy_gateway.android_vlm_service import ANDROID_MODEL_CHECKSUMS
        assert "mobilevlm_v2_1_7b_gguf" in ANDROID_MODEL_CHECKSUMS

    def test_checksum_registry_has_seeclick_params(self):
        from galaxy_gateway.android_vlm_service import ANDROID_MODEL_CHECKSUMS
        assert "seeclick_params" in ANDROID_MODEL_CHECKSUMS

    def test_checksum_registry_has_seeclick_bin(self):
        from galaxy_gateway.android_vlm_service import ANDROID_MODEL_CHECKSUMS
        assert "seeclick_bin" in ANDROID_MODEL_CHECKSUMS

    def test_each_model_has_sha256_field(self):
        from galaxy_gateway.android_vlm_service import ANDROID_MODEL_CHECKSUMS
        for model_id, meta in ANDROID_MODEL_CHECKSUMS.items():
            assert "sha256" in meta, f"Model {model_id} missing sha256 field"

    def test_each_model_has_file_field(self):
        from galaxy_gateway.android_vlm_service import ANDROID_MODEL_CHECKSUMS
        for model_id, meta in ANDROID_MODEL_CHECKSUMS.items():
            assert "file" in meta, f"Model {model_id} missing file field"

    def test_each_model_has_runtime_field(self):
        from galaxy_gateway.android_vlm_service import ANDROID_MODEL_CHECKSUMS
        for model_id, meta in ANDROID_MODEL_CHECKSUMS.items():
            assert "runtime" in meta, f"Model {model_id} missing runtime field"

    def test_mobilevlm_runtime_is_llamacpp(self):
        from galaxy_gateway.android_vlm_service import ANDROID_MODEL_CHECKSUMS
        assert "llama" in ANDROID_MODEL_CHECKSUMS["mobilevlm_v2_1_7b_gguf"]["runtime"].lower()

    def test_seeclick_runtime_is_ncnn(self):
        from galaxy_gateway.android_vlm_service import ANDROID_MODEL_CHECKSUMS
        assert "NCNN" in ANDROID_MODEL_CHECKSUMS["seeclick_params"]["runtime"].upper()


class TestAndroidVLMServicePlanValidation:
    @pytest.mark.asyncio
    async def test_plan_with_empty_image_returns_failure(self):
        from galaxy_gateway.android_vlm_service import AndroidVLMService
        svc = AndroidVLMService(router=None)
        result = await svc.plan(image_base64="", task="tap the button")
        assert result["success"] is False
        assert "image_base64" in result["error"]

    @pytest.mark.asyncio
    async def test_ground_with_empty_image_returns_failure(self):
        from galaxy_gateway.android_vlm_service import AndroidVLMService
        svc = AndroidVLMService(router=None)
        result = await svc.ground(image_base64="", query="find the submit button")
        assert result["success"] is False
        assert "image_base64" in result["error"]

    @pytest.mark.asyncio
    async def test_plan_no_router_returns_failure(self):
        from galaxy_gateway.android_vlm_service import AndroidVLMService
        svc = AndroidVLMService(router=None)
        with patch.object(svc, "_get_router", return_value=None):
            result = await svc.plan(image_base64="aW1hZ2U=", task="open camera")
        assert result["success"] is False
        assert "router" in result["error"].lower() or "unavailable" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_ground_no_router_returns_failure(self):
        from galaxy_gateway.android_vlm_service import AndroidVLMService
        svc = AndroidVLMService(router=None)
        with patch.object(svc, "_get_router", return_value=None):
            result = await svc.ground(image_base64="aW1hZ2U=", query="find button")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_ground_null_confidence_returns_zero_not_raises(self):
        """LLM JSON often omits or nulls confidence; must not crash the handler."""
        from galaxy_gateway.android_vlm_service import AndroidVLMService

        svc = AndroidVLMService(router=None)
        mock_router = MagicMock()
        mock_router.route_multimodal_first.return_value = MagicMock(provider_id="test")

        async def _fake_vision(*_a, **_kw):
            return '{"bbox": [1, 2, 3, 4], "label": "btn", "confidence": null}'

        with patch.object(svc, "_get_router", return_value=mock_router):
            with patch(
                "galaxy_gateway.android_vlm_service._chat_with_vision",
                new_callable=AsyncMock,
                side_effect=_fake_vision,
            ):
                result = await svc.ground(image_base64="aW1hZ2U=", query="submit")
        assert result["success"] is True
        assert result["confidence"] == 0.0


class TestAndroidVLMCanonicalApiRoutes:
    def test_create_api_routes_registers_android_vlm_status_path(self):
        from core.api_routes import create_api_routes

        api = create_api_routes()
        paths = [getattr(r, "path", "") for r in api.routes]
        assert "/api/v1/android/vlm/status" in paths


class TestSafeParseJson:
    def test_parse_plain_json(self):
        from galaxy_gateway.android_vlm_service import _safe_parse_json
        result = _safe_parse_json('{"action": "tap", "coordinates": [100, 200]}')
        assert result["action"] == "tap"
        assert result["coordinates"] == [100, 200]

    def test_parse_fenced_json(self):
        from galaxy_gateway.android_vlm_service import _safe_parse_json
        result = _safe_parse_json('```json\n{"action": "swipe"}\n```')
        assert result["action"] == "swipe"

    def test_parse_empty_string_returns_empty(self):
        from galaxy_gateway.android_vlm_service import _safe_parse_json
        assert _safe_parse_json("") == {}

    def test_parse_invalid_json_returns_empty(self):
        from galaxy_gateway.android_vlm_service import _safe_parse_json
        assert _safe_parse_json("not json at all") == {}

    def test_parse_json_embedded_in_prose(self):
        from galaxy_gateway.android_vlm_service import _safe_parse_json
        text = 'I will tap the button. {"action": "tap", "coordinates": [50, 60]}'
        result = _safe_parse_json(text)
        assert result.get("action") == "tap"


# ===========================================================================
# 5. URLConfigSurface rendering
# ===========================================================================

class TestURLConfigSurfaceRendering:
    def test_renders_without_crash(self, config_service):
        from windows_client.status_board_v2.url_config_surface import URLConfigSurface
        surface = URLConfigSurface()
        with patch("core.config_service.get_config_service", return_value=config_service):
            output = surface.render()
        assert isinstance(output, str)
        assert len(output) > 0

    def test_shows_not_set_when_urls_absent(self, config_service):
        from windows_client.status_board_v2.url_config_surface import URLConfigSurface
        surface = URLConfigSurface()
        with patch("core.config_service.get_config_service", return_value=config_service):
            output = surface.render()
        assert "NOT SET" in output

    def test_shows_set_url_after_configuration(self, config_service):
        from windows_client.status_board_v2.url_config_surface import URLConfigSurface
        config_service.set_network_url("gateway_url", "ws://10.0.0.1:8765")
        surface = URLConfigSurface()
        with patch("core.config_service.get_config_service", return_value=config_service):
            output = surface.render()
        assert "ws://10.0.0.1:8765" in output

    def test_lists_all_url_keys(self, config_service):
        from windows_client.status_board_v2.url_config_surface import URLConfigSurface
        surface = URLConfigSurface()
        with patch("core.config_service.get_config_service", return_value=config_service):
            output = surface.render()
        assert "gateway_url" in output.lower() or "Gateway URL" in output
        assert "nats_url" in output.lower() or "NATS" in output
        assert "ats_url" in output.lower() or "ATS" in output


# ===========================================================================
# 6. ManagementConsole rendering
# ===========================================================================

class TestManagementConsoleRendering:
    def test_renders_without_crash(self):
        from windows_client.status_board_v2.management_console import ManagementConsole
        console = ManagementConsole()
        output = console.render({})
        assert isinstance(output, str)
        assert len(output) > 0

    def test_contains_device_section(self):
        from windows_client.status_board_v2.management_console import ManagementConsole
        console = ManagementConsole()
        output = console.render({})
        assert "Device" in output or "device" in output.lower()

    def test_contains_task_chain_section(self):
        from windows_client.status_board_v2.management_console import ManagementConsole
        console = ManagementConsole()
        output = console.render({})
        assert "Task" in output

    def test_contains_model_section(self):
        from windows_client.status_board_v2.management_console import ManagementConsole
        console = ManagementConsole()
        output = console.render({})
        assert "Provider" in output or "LLM" in output

    def test_contains_readiness_section(self):
        from windows_client.status_board_v2.management_console import ManagementConsole
        console = ManagementConsole()
        output = console.render({})
        assert "Readiness" in output or "readiness" in output.lower()

    def test_shows_devices_from_projection(self):
        from windows_client.status_board_v2.management_console import ManagementConsole
        console = ManagementConsole()
        projection = {
            "devices": [
                {
                    "device_id": "android-001",
                    "device_type": "android",
                    "execution_stage": "idle",
                    "online": True,
                }
            ]
        }
        output = console.render(projection)
        assert "android-001" in output

    def test_shows_task_chains_from_projection(self):
        from windows_client.status_board_v2.management_console import ManagementConsole
        console = ManagementConsole()
        projection = {
            "task_chains": [
                {
                    "task_id": "task-abc-123",
                    "status": "completed",
                    "steps": [],
                }
            ]
        }
        output = console.render(projection)
        assert "task-abc-123" in output


# ===========================================================================
# 7. StatusBoardV2App — management console integration
# ===========================================================================

class TestStatusBoardV2AppManagementFlag:
    def test_management_false_does_not_create_console(self):
        from windows_client.status_board_v2.app import StatusBoardV2App
        app = StatusBoardV2App(show_management=False)
        assert app._management is None
        assert app._url_config is None

    def test_management_true_creates_console(self):
        from windows_client.status_board_v2.app import StatusBoardV2App
        app = StatusBoardV2App(show_management=True)
        assert app._management is not None
        assert app._url_config is not None

    def test_render_once_with_management_includes_url_section(self):
        from windows_client.status_board_v2.app import StatusBoardV2App
        app = StatusBoardV2App(show_management=True)
        output = app.render_once({})
        # Should contain URL config section header
        assert "Network URLs" in output or "gateway_url" in output.lower()

    def test_render_once_without_management_no_url_section(self):
        from windows_client.status_board_v2.app import StatusBoardV2App
        app = StatusBoardV2App(show_management=False)
        output = app.render_once({})
        # URL config section should not appear when management is off
        assert "Network URLs" not in output


class TestStatusBoardV2AppCLIParsing:
    def test_management_flag_is_false_by_default(self):
        from windows_client.status_board_v2.app import _build_parser
        args = _build_parser().parse_args([])
        assert args.management is False

    def test_management_flag_parses(self):
        from windows_client.status_board_v2.app import _build_parser
        args = _build_parser().parse_args(["--management"])
        assert args.management is True

    def test_set_url_arg_parses(self):
        from windows_client.status_board_v2.app import _build_parser
        args = _build_parser().parse_args(["--set-url", "gateway_url=ws://10.0.0.1:8765"])
        assert args.set_url == "gateway_url=ws://10.0.0.1:8765"

    def test_set_api_key_arg_parses(self):
        from windows_client.status_board_v2.app import _build_parser
        args = _build_parser().parse_args(["--set-api-key", "openai=sk-test"])
        assert args.set_api_key == "openai=sk-test"

    def test_set_android_inference_mode_arg_parses(self):
        from windows_client.status_board_v2.app import _build_parser
        args = _build_parser().parse_args(["--set-android-inference-mode", "center"])
        assert args.set_android_inference_mode == "center"


class TestApplyURLArg:
    def test_apply_url_arg_valid(self, control_surface):
        from windows_client.status_board_v2.app import _apply_url_arg
        result = _apply_url_arg(control_surface, "gateway_url=ws://10.0.0.1:8765")
        assert result.succeeded is True

    def test_apply_url_arg_no_equals(self, control_surface):
        from windows_client.status_board_v2.app import _apply_url_arg
        result = _apply_url_arg(control_surface, "no_equals_sign")
        assert result.succeeded is False
        assert "KEY=URL" in result.error

    def test_apply_api_key_arg_valid(self, control_surface):
        from windows_client.status_board_v2.app import _apply_api_key_arg
        result = _apply_api_key_arg(control_surface, "openai=sk-test-key")
        assert result.succeeded is True

    def test_apply_api_key_arg_no_equals(self, control_surface):
        from windows_client.status_board_v2.app import _apply_api_key_arg
        result = _apply_api_key_arg(control_surface, "openai")
        assert result.succeeded is False
        assert "PROVIDER=KEY" in result.error


# ===========================================================================
# 8. Vision handler now routes through OpenClawd multimodal pipeline
# ===========================================================================

class TestVisionHandlerMultimodalRouting:
    def test_handler_module_imports_cleanly(self):
        """Vision handler must import without error."""
        from galaxy_gateway.android.handlers.vision import handle_vision_request
        assert callable(handle_vision_request)

    def test_handler_uses_multimodal_context(self):
        """The private helper must use MultiModalContext schema."""
        import inspect
        from galaxy_gateway.android.handlers import vision as v_mod
        src = inspect.getsource(v_mod)
        assert "MultiModalContext" in src

    def test_handler_has_openclawd_primary_path(self):
        """Vision handler must attempt OpenClawd first."""
        import inspect
        from galaxy_gateway.android.handlers import vision as v_mod
        src = inspect.getsource(v_mod)
        assert "OpenClawd" in src or "openclawd" in src.lower()

    def test_handler_has_vision_pipeline_fallback(self):
        """Vision handler must fall back to VisionPipeline."""
        import inspect
        from galaxy_gateway.android.handlers import vision as v_mod
        src = inspect.getsource(v_mod)
        assert "VisionPipeline" in src

    @pytest.mark.asyncio
    async def test_empty_image_returns_error_message(self):
        """Empty image_base64 must return a VISION_NO_IMAGE error."""
        from galaxy_gateway.android.handlers.vision import handle_vision_request

        mock_bridge = MagicMock()
        message = {
            "device_id": "dev-test",
            "image_base64": "",
            "task_context": "open settings",
        }
        response = await handle_vision_request(mock_bridge, None, message)
        assert response is not None
        assert response.get("type") == "error" or "error" in str(response).lower() or \
               response.get("payload", {}).get("code") == "VISION_NO_IMAGE"
