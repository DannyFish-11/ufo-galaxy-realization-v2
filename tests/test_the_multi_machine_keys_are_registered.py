"""多机模式底下那二十来个「代码在读、却没登记」的环境变量，现在都登记了；凭据不会明文进 ``.env``。

没登记 = ``POST /api/config`` 按未知键整批 400、``.env`` 的落盘与密钥分流够不着它、登记默认与代码默认是否一致的
守卫也看不见它。TURN 的凭据就是这样一直没被当成密钥：``classify_key`` 按后缀认，``_CREDENTIAL`` 不在后缀里。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.config_schema import classify_key
from core.routes import config as config_routes
from core.routes.config_schema_multimachine import MULTI_MACHINE_SCHEMA
from core.routes.config_schema_registry import CONFIG_SCHEMA

#: 清点时列出来的、代码在读却没登记的那一批。
THE_UNREGISTERED_BATCH = (
    "FEDERATION_INSTANCE_ID",
    "FEDERATION_MIN_HEARTBEAT_INTERVAL",
    "FEDERATION_OFFLINE_THRESHOLD",
    "GALAXY_TURN_USERNAME",
    "GALAXY_TURN_CREDENTIAL",
    "GALAXY_STUN_URLS",
    "GALAXY_TAILSCALE_ENABLED",
    "GALAXY_TAILSCALE_HOST",
    "GALAXY_TAILSCALE_TAG",
    "GALAXY_TRANSPORT_PRIORITY",
    "GALAXY_ENABLE_WEBRTC",
    "GALAXY_USE_GATEWAY_FOR_WEBRTC",
    "GALAXY_WEBRTC_TASK_READY_TIMEOUT_S",
    "GALAXY_HOLE_PUNCH_TIMEOUT_S",
    "GALAXY_MESH_NODE_ID",
    "GALAXY_MESH_PORT",
    "GALAXY_MULTI_DEVICE_DISPATCH_LIMIT",
    "GALAXY_ENABLE_LEGACY_MULTIDEVICE",
    "GALAXY_WORKER_ID",
    "GALAXY_WORKER_VERSION",
)


@pytest.mark.parametrize("key", THE_UNREGISTERED_BATCH)
def test_every_key_in_the_batch_is_registered(key):
    assert key in CONFIG_SCHEMA, f"{key} 代码在读，登记表里没有 —— POST /api/config 会 400"


def test_the_batch_comes_from_the_one_file_and_is_not_empty():
    assert set(MULTI_MACHINE_SCHEMA) >= set(THE_UNREGISTERED_BATCH)
    assert all(k in CONFIG_SCHEMA for k in MULTI_MACHINE_SCHEMA)


def test_every_entry_has_the_four_fields_the_panel_needs():
    for key, meta in MULTI_MACHINE_SCHEMA.items():
        assert {"default", "type", "category", "description"} <= set(meta), key
        assert meta["type"] in {"string", "number", "boolean", "url", "select", "password"}, key


def test_the_turn_credential_is_a_secret_and_never_lands_in_plaintext_env(tmp_path, monkeypatch):
    assert classify_key("GALAXY_TURN_CREDENTIAL") == "secret"
    assert CONFIG_SCHEMA["GALAXY_TURN_CREDENTIAL"]["type"] == "password"

    import core.config_store as config_store_module

    monkeypatch.setattr(config_routes, "ENV_FILE", tmp_path / ".env.test")
    monkeypatch.setattr(
        config_store_module,
        "_singleton",
        config_store_module.ConfigStore(
            config_path=tmp_path / "config.json.test", secrets_path=tmp_path / "secrets.env.test"
        ),
    )
    monkeypatch.setenv("GALAXY_TURN_CREDENTIAL", "")
    app = FastAPI()
    app.include_router(config_routes.router)
    resp = TestClient(app).post(
        "/api/config",
        json={"config": {"GALAXY_TURN_CREDENTIAL": "TURN-SECRET-VALUE-123", "GALAXY_TURN_USERNAME": "alice"}},
    )
    assert resp.status_code == 200, resp.text
    env_text = (tmp_path / ".env.test").read_text(encoding="utf-8")
    assert "TURN-SECRET-VALUE-123" not in env_text, "TURN 凭据被明文写进了 .env"
    assert "GALAXY_TURN_USERNAME=alice" in env_text  # 非密钥照常落盘
    secrets_text = (tmp_path / "secrets.env.test").read_text(encoding="utf-8")
    assert "TURN-SECRET-VALUE-123" in secrets_text


def test_internal_tuning_is_registered_but_not_listed_and_the_connectivity_keys_are():
    listed = config_routes.PANEL_HIDDEN_KEYS
    for hidden in (
        "FEDERATION_INSTANCE_ID",
        "GALAXY_MESH_PORT",
        "GALAXY_WORKER_ID",
        "GALAXY_MULTI_DEVICE_DISPATCH_LIMIT",
    ):
        assert hidden in listed
    for shown in ("GALAXY_TURN_USERNAME", "GALAXY_TURN_CREDENTIAL", "GALAXY_STUN_URLS", "GALAXY_TAILSCALE_HOST"):
        assert shown not in listed, f"{shown} 是用户为「连不上」要填的，不该藏起来"


def test_the_cross_device_button_does_not_claim_local_node_addresses():
    from core.routes.config_bundles import CONFIG_BUNDLES, owned_keys

    bundle = next(b for b in CONFIG_BUNDLES if b["key"] == "cross_device")
    owned = owned_keys(bundle, CONFIG_SCHEMA.keys())
    assert not [k for k in owned if k.startswith("NODE_") and k.endswith("_URL")]
