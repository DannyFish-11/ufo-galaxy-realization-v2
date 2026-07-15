"""tests/test_config_secret_routing.py
==========================================

域2 · 配置融合(密钥收敛):面板 update_config 把 API key / token 等敏感项路由到
唯一密钥库 ConfigService(runtime/secrets.env),不再明文落进 .env——消除
".env 旧值重启时盖住 secrets.env" 的历史丢 key 根因。ConfigService 不可用时回落
.env,不丢持久化。
"""

from __future__ import annotations

import asyncio
import os

import pytest

import core.routes.config as cfg


def _run(config_dict):
    return asyncio.run(cfg.update_config(cfg.ConfigUpdateRequest(config=config_dict)))


class _FakeCS:
    store: dict = {}

    def set_secret(self, k, v):
        _FakeCS.store[k] = v


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "ENV_FILE", tmp_path / ".env")
    _FakeCS.store = {}
    monkeypatch.setattr("core.config_service.ConfigService", _FakeCS)
    for k in ("DEEPSEEK_API_KEY", "GALAXY_SPEAK"):
        monkeypatch.delenv(k, raising=False)
    yield
    # update_config 用裸 os.environ[k]=v 写入,monkeypatch 无法自动撤销 → 显式清理,
    # 否则会污染同一 run 里其它测试(如 config_preflight 的 critical-missing 判定)。
    for k in ("DEEPSEEK_API_KEY", "GALAXY_SPEAK"):
        os.environ.pop(k, None)


def test_persist_failure_leaves_os_environ_untouched(monkeypatch):
    """落盘失败 → os.environ 一个字不动,消除"显示已配置却又保存失败"的自相矛盾。

    前端 GET /api/config 用 os.getenv 判"已配置";过去先写 os.environ 再落盘,落盘
    失败就成了"已配置↔保存失败"并存、无法判断到底存没存。现在先落盘、成功才应用,
    落盘失败则 os.environ 原封不动,"已配置"保持原状、错误如实报出。
    """
    from fastapi import HTTPException

    def _boom(*a, **k):
        raise OSError(".env locked by antivirus")

    monkeypatch.setattr(cfg, "_write_env_file_with", _boom)
    assert "GALAXY_SPEAK" not in os.environ
    with pytest.raises(HTTPException) as ei:
        _run({"GALAXY_SPEAK": "1"})
    assert ei.value.status_code == 500
    assert "未改动任何配置" in str(ei.value.detail)
    # 关键:未改动 os.environ → "已配置"如实保持 false,不与"保存失败"矛盾
    assert "GALAXY_SPEAK" not in os.environ


def test_secret_goes_to_canonical_store_not_plaintext_dotenv():
    _run({"DEEPSEEK_API_KEY": "sk-secret-xyz", "GALAXY_SPEAK": "1"})
    # 密钥进 canonical 密钥库
    assert _FakeCS.store.get("DEEPSEEK_API_KEY") == "sk-secret-xyz"
    env_text = cfg.ENV_FILE.read_text(encoding="utf-8")
    # 不明文落 .env(消除重启时 .env 盖住 secrets.env 的丢 key 根因)
    assert "sk-secret-xyz" not in env_text
    assert "DEEPSEEK_API_KEY" not in env_text
    # 非密钥的运行时开关仍走 .env
    assert "GALAXY_SPEAK=1" in env_text
    # os.environ 当次即时生效
    assert os.environ["DEEPSEEK_API_KEY"] == "sk-secret-xyz"


def test_secret_falls_back_to_dotenv_when_store_unavailable(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("config service unavailable")

    monkeypatch.setattr("core.config_service.ConfigService", _boom)
    _run({"DEEPSEEK_API_KEY": "sk-fallback"})
    env_text = cfg.ENV_FILE.read_text(encoding="utf-8")
    # 写 secrets.env 失败 → 回落 .env,绝不丢持久化
    assert "DEEPSEEK_API_KEY=sk-fallback" in env_text


def test_write_env_file_excludes_given_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-in-env")
    monkeypatch.setenv("GALAXY_SPEAK", "1")
    cfg._write_env_file(exclude={"DEEPSEEK_API_KEY"})
    text = cfg.ENV_FILE.read_text(encoding="utf-8")
    assert "DEEPSEEK_API_KEY" not in text  # 被排除
    assert "GALAXY_SPEAK=1" in text
