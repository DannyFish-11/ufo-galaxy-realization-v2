"""设置明细接口**不下发密钥的值**,只说配没配。

后端监听 ``0.0.0.0``,设置这组原先挂载时又没带鉴权。原先 ``GET /api/config/all`` 把 30 个密钥类键的
**原值**整份返回 —— 各家 API Key,连同鉴权令牌 ``GALAXY_API_TOKEN`` 本身。同一局域网里
任何一台机器 GET 一下就全拿走。

面板从来不回填密钥(``ui/settings.ts``:密码框留空、占位写「已配置(留空=不改)」),
要的只是「配没配」。所以接口给掩码或空串;面板(或别的客户端)把掩码原样写回来,当没改。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """隔离 ``.env``、``secrets.env`` 与 ``os.environ``(写法同 test_saving_a_setting_really_takes_effect)。"""
    import os

    from core.routes import config as route

    written: dict = {}
    monkeypatch.setattr(route, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(
        route,
        "_write_env_file_with",
        lambda overrides=None, exclude=None: written.update(overrides or {}),
    )

    class _Secrets:
        def set_secret(self, key, value):  # noqa: D102
            written[key] = value

        def delete_secret(self, key):  # noqa: D102
            written[key] = ""

    import core.config_service as cs

    monkeypatch.setattr(cs, "ConfigService", lambda *a, **k: _Secrets())

    before = dict(os.environ)
    app = FastAPI()
    app.include_router(route.router)
    try:
        with TestClient(app) as c:
            c.written = written  # type: ignore[attr-defined]
            yield c
    finally:
        os.environ.clear()
        os.environ.update(before)


def test_configured_secrets_come_back_masked(client, monkeypatch):
    from core.routes.config import SECRET_MASK

    monkeypatch.setenv("OPENAI_API_KEY", "sk-live-should-not-leave")
    monkeypatch.setenv("GALAXY_API_TOKEN", "token-should-not-leave")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    resp = client.get("/api/config/all")
    assert resp.status_code == 200
    body = resp.json()
    raw = json.dumps(body)
    assert "sk-live-should-not-leave" not in raw
    assert "token-should-not-leave" not in raw
    assert body["OPENAI_API_KEY"]["value"] == SECRET_MASK
    assert body["GALAXY_API_TOKEN"]["value"] == SECRET_MASK
    assert body["ANTHROPIC_API_KEY"]["value"] == "", "没配的给空串,面板据此写「未配置」"


def test_no_secret_value_leaves_whatever_its_name(client, monkeypatch):
    """不只是那张显式密钥表:名字像密钥的(``*_OPENAI_KEY``、``GALAXY_API_TOKENS``)同样不下发。"""
    from core.routes.config import CONFIG_SCHEMA, _masked

    planted = {}
    for key, meta in CONFIG_SCHEMA.items():
        if _masked(key) and meta["type"] not in ("boolean", "number"):
            planted[key] = f"planted-{key.lower()}-value"
            monkeypatch.setenv(key, planted[key])
    monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "true")  # 跨设备专属键也列出来,一起查
    raw = json.dumps(client.get("/api/config/all").json())
    leaked = [k for k, v in planted.items() if v in raw]
    assert not leaked, f"这些键的值仍原样下发: {leaked}"


def test_switches_with_secret_looking_names_still_say_true_or_false(client):
    """名字以 ``_TOKEN`` / ``_KEY`` 结尾的布尔开关(首字就出声、停止键……)照旧给 true/false。"""
    from core.routes.config import CONFIG_SCHEMA, _masked

    body = client.get("/api/config/all").json()
    for key, item in body.items():
        if _masked(key) and CONFIG_SCHEMA[key]["type"] == "boolean":
            assert item["value"] in ("true", "false"), key


def test_an_echoed_mask_is_not_saved_as_the_key(client, monkeypatch):
    from core.routes.config import SECRET_MASK

    monkeypatch.setenv("OPENAI_API_KEY", "sk-keep-me")
    resp = client.post("/api/config", json={"config": {"OPENAI_API_KEY": SECRET_MASK}})
    assert resp.status_code == 200, resp.text
    import os

    assert os.environ["OPENAI_API_KEY"] == "sk-keep-me"
    assert "OPENAI_API_KEY" not in client.written


def test_backend_and_panel_agree_on_what_a_secret_name_is():
    """面板当密钥画的(不回填),后端就不下发真值 —— 两边是同一条规则。"""
    from core.routes.config import _SECRET_NAME

    ts = (REPO / "electron/renderer/panel/src/ui/settings.ts").read_text(encoding="utf-8")
    m = re.search(r"const SECRET_RE = /(.+)/;", ts)
    assert m, "ui/settings.ts 里找不到 SECRET_RE"
    assert m.group(1) == _SECRET_NAME.pattern
