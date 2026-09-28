"""从模板生成的 .env 起来,鉴权是开着的,而且桌面照样能用。

以前 ``.env.example`` 写着 ``GALAXY_AUTH_ENABLED=false``(代码默认是开),复制模板
的每一份安装鉴权都是关的。只删那一行还不够:模板里还有
``GALAXY_API_TOKEN=your_galaxy_api_token_here``,鉴权一开它就会被当成**真令牌** ——
模板是公开的,谁都能拿它过鉴权;它还让"已配共享令牌"成立,本机令牌不签,桌面被 401。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi import HTTPException

from core import auth

ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDER = "your_galaxy_api_token_here"


@pytest.fixture
def fresh_clone(tmp_path, monkeypatch):
    for k in (
        "GALAXY_API_TOKEN",
        "GALAXY_API_TOKENS",
        "GALAXY_AUTH_ENABLED",
        "GALAXY_MODE",
        "GALAXY_DATA_DIR",
        "GALAXY_REQUIRE_API_TOKEN",
    ):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(auth, "_auth_config_validated", False)
    return tmp_path


def test_the_template_does_not_turn_auth_off():
    active = [
        ln.split("#", 1)[0].strip()
        for ln in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]
    assert not any(ln.replace(" ", "").lower().startswith("galaxy_auth_enabled=") for ln in active)
    token_lines = [ln for ln in active if ln.startswith("GALAXY_API_TOKEN=")]
    assert token_lines == ["GALAXY_API_TOKEN="], token_lines


def test_an_install_made_from_the_template_has_auth_on_and_a_local_token(fresh_clone):
    import main

    (fresh_clone / ".env.example").write_text((ROOT / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
    assert main.bootstrap_env_file(str(fresh_clone))
    before = dict(os.environ)
    try:
        main.load_env_files_into_environ(str(fresh_clone))
        assert auth.is_auth_enabled() is True
        auth.ensure_auth_config_validated()
        assert auth.auth_posture()["token"] == "local"
        assert (fresh_clone / "data" / "api_token.json").is_file()
    finally:
        for k in set(os.environ) - set(before):
            del os.environ[k]


def test_the_template_placeholder_is_never_a_valid_token(fresh_clone, monkeypatch):
    """装过旧模板的机器 .env 里还留着这一行 —— 也必须当"没配"。"""
    monkeypatch.setenv("GALAXY_API_TOKEN", PLACEHOLDER)
    monkeypatch.setenv("GALAXY_API_TOKENS", f"{PLACEHOLDER},real-rotation-token-abc")

    assert PLACEHOLDER not in auth.get_active_tokens()
    assert "real-rotation-token-abc" in auth.get_active_tokens()
    assert auth.verify_api_token(PLACEHOLDER) is False


def test_a_placeholder_does_not_stop_the_local_token_from_being_signed(fresh_clone, monkeypatch):
    monkeypatch.setenv("GALAXY_API_TOKEN", PLACEHOLDER)

    auth.ensure_auth_config_validated()

    assert auth.auth_posture()["token"] == "local", "占位值被当成已配令牌,本机令牌没签 —— 桌面会被 401"
    assert auth.read_local_token() in auth.get_active_tokens()


def test_a_request_bearing_the_placeholder_is_rejected(fresh_clone, monkeypatch):
    import asyncio

    monkeypatch.setenv("GALAXY_API_TOKEN", PLACEHOLDER)
    auth.ensure_auth_config_validated()
    with pytest.raises(HTTPException) as exc:
        asyncio.run(auth.require_auth(authorization=f"Bearer {PLACEHOLDER}", x_device_id=None))
    assert exc.value.status_code == 401


def test_production_does_not_accept_the_placeholder_as_its_token(fresh_clone, monkeypatch):
    monkeypatch.setenv("GALAXY_MODE", "production")
    monkeypatch.setenv("GALAXY_API_TOKEN", "your_" + "x" * 40)
    with pytest.raises(RuntimeError):
        auth.validate_auth_config()


def test_the_settings_panel_shows_the_real_default():
    from core.routes.config_schema_registry import CONFIG_SCHEMA

    assert CONFIG_SCHEMA["GALAXY_AUTH_ENABLED"]["default"] == "true"


@pytest.mark.parametrize("real", ["x" * 40, "xxxQ3v_real-random-token-abc", "todo9Fz_real", "exampleZ_real_token"])
def test_real_tokens_that_happen_to_start_like_a_placeholder_still_work(fresh_clone, monkeypatch, real):
    """真随机令牌碰巧以 xxx / todo / example 开头时不许被误判成占位值 —— 那是一次莫名的锁死。"""
    monkeypatch.setenv("GALAXY_API_TOKEN", real)
    assert real in auth.get_active_tokens()
