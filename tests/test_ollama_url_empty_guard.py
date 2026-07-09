"""tests/test_ollama_url_empty_guard.py
==========================================

克隆界面/onboarding 探测 Ollama 时的 "Request URL is missing an 'http://'..." 报错:
根因是 OLLAMA_URL="" 进了运行进程 os.environ(面板保存配置会同步),消费端拿到空
URL 发 httpx 就炸。两个最内层消费端(LocalBrainManager / OllamaBackend)对
【空值】和【无协议头】都必须兜底成合法 URL,绝不放空 URL 出门。
"""
from __future__ import annotations

import pytest

from core.local_brain_manager import LocalBrainManager
from core.local_model_backends import OllamaBackend

_DEFAULT = "http://localhost:11434"


class TestNormalizeOllamaUrl:
    def test_empty_returns_default(self):
        # 回归:此前返回 "" → 拿空 URL ping Ollama 报 missing protocol
        assert LocalBrainManager._normalize_ollama_url("") == _DEFAULT

    def test_whitespace_returns_default(self):
        assert LocalBrainManager._normalize_ollama_url("   ") == _DEFAULT

    def test_none_returns_default(self):
        assert LocalBrainManager._normalize_ollama_url(None) == _DEFAULT

    def test_bare_hostport_gets_protocol(self):
        assert LocalBrainManager._normalize_ollama_url("localhost:11434") == _DEFAULT

    def test_full_url_preserved_trailing_slash_stripped(self):
        assert LocalBrainManager._normalize_ollama_url("http://host:9/") == "http://host:9"

    def test_manager_with_empty_env_gets_default(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_URL", "")  # 模拟面板写入的空值
        mgr = LocalBrainManager(backend="ollama")
        assert mgr.ollama_url == _DEFAULT


class TestOllamaBackendUrl:
    def test_empty_returns_default(self):
        assert OllamaBackend(base_url="").base_url == _DEFAULT

    def test_bare_hostport_gets_protocol(self):
        assert OllamaBackend(base_url="localhost:11434").base_url == _DEFAULT

    def test_default_ctor_ok(self):
        assert OllamaBackend().base_url == _DEFAULT

    def test_full_url_trailing_slash_stripped(self):
        assert OllamaBackend(base_url="http://h:1/").base_url == "http://h:1"
