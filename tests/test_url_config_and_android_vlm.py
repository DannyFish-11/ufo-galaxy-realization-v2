"""
tests/test_url_config_and_android_vlm.py
=========================================
Tests for:
1. URL configuration in config_schema / config_service
2. Android inference mode configuration
3. Vision handler 经 OpenClawd 多模态管线路由

原 3/4/5 三项（URLConfigSurface / ManagementConsole / StatusBoardV2App CLI）针对的是
终端状态板 windows_client/status_board_v2/，该表层随面板收敛删除，测试一并移除；
详见文件中段的说明。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

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
# 这里曾有五组测试，全部针对终端状态板 windows_client/status_board_v2/：
#   ConfigControlSurface（可写控制面：provider 开关 / 路由策略）
#   URLConfigSurface、ManagementConsole（渲染）
#   StatusBoardV2App 的 --management 开关与 CLI 参数解析
# 该表层已随面板收敛整包删除，这些测试一并移除。
#
# 注意这里删掉的**不只是渲染**：ConfigControlSurface 是一个可写控制面
# （见 core/operational_enablement_audit.py 里"status_board_v2 不是只读状态板"
# 那一节）。它写配置走的是 core.config_service，而上面 2/3/4 三组测试正是
# 直接对 ConfigService 断言 URL / API key / android_inference_mode 的写入与
# 校验——也就是说**配置写入这条链路的测试覆盖没有随表层消失**，只是不再经过
# 一个终端 UI 去间接验证。配置的唯一入口现在是 React 面板的「设置」页。
# ===========================================================================

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
        assert (
            response.get("type") == "error"
            or "error" in str(response).lower()
            or response.get("payload", {}).get("code") == "VISION_NO_IMAGE"
        )
