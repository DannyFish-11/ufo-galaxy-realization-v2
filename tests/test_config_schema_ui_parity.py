"""tests/test_config_schema_ui_parity.py
==========================================
真机复现:用户点"保存"填好的 API Key,面板显示"保存失败"。上一轮以为是限流
误伤(已修复),但用户在真机上再次复现——这次找到一个完全独立的根因:

ModelsTab.tsx 在上一轮修复里新增了三行 UI(OpenRouter/DeepSeek OCR/OpenAI 自定义
地址),这三个 key(OPENROUTER_API_KEY / DEEPSEEK_OCR2_API_KEY / OPENAI_API_BASE)
当时只核对过 core/routes/system.py 的 _SECRET_MODEL_KEYS/_NON_SECRET_MODEL_KEYS
(GET /api/config 精简版读接口用的白名单),却没有核对 core/routes/config.py 的
CONFIG_SCHEMA(POST /api/config 写接口用的另一份、完全独立、未同步的白名单)。

后果:core/routes/config.py::update_config() 对 req.config 里任何不在
CONFIG_SCHEMA 里的 key 直接 400——ModelsTab 保存请求只要 changed 里包含这三个
新字段中的任何一个,整个批量保存请求全部失败(哪怕同批里还夹着本来能存的
DEEPSEEK_API_KEY),前端只会显示笼统的"保存失败"。

修复:把这三个 key(以及同样只在 system.py 里出现、不在 CONFIG_SCHEMA 里的
SONAR_API_KEY/VLLM_URL)补进 CONFIG_SCHEMA。

本文件的测试有两层:
1. 结构性回归闸门:直接解析 ModelsTab.tsx/SettingsTab.tsx 源码里引用的每个
   config key,断言它们都在 CONFIG_SCHEMA 里——以后再有人往面板 UI 加一个新
   provider/设置项而忘了同步 CONFIG_SCHEMA,这个测试会先炸,而不是等用户在
   真机上点"保存"才发现。
2. 端到端复现:直接用 TestClient 打 POST /api/config,验证这三个 key 现在
   能保存成功(不再 400)。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parent.parent
MODELS_TAB = REPO_ROOT / "electron/renderer/panel/src/components/ModelsTab.tsx"
SETTINGS_TAB = REPO_ROOT / "electron/renderer/panel/src/components/SettingsTab.tsx"

_KEY_RE = re.compile(r"""\b(?:key|extraKey)\s*:\s*'([A-Z][A-Z0-9_]*)'""")
_SETTINGS_KEY_RE = re.compile(r"""'([A-Z][A-Z0-9_]*)'""")


def _extract_models_tab_keys() -> set[str]:
    src = MODELS_TAB.read_text(encoding="utf-8")
    return set(_KEY_RE.findall(src))


def _extract_settings_tab_keys() -> set[str]:
    """从 SettingsTab.tsx 的 CONFIG_KEYS 字典字面量里提取所有 key 字符串。"""
    src = SETTINGS_TAB.read_text(encoding="utf-8")
    start = src.index("const CONFIG_KEYS")
    end = src.index("\n};", start)
    block = src[start:end]
    return set(_SETTINGS_KEY_RE.findall(block))


class TestModelsTabKeysExistInConfigSchema:
    """ModelsTab.tsx 里出现的每一个 provider key,POST /api/config 都必须认得。"""

    def test_every_models_tab_key_is_in_config_schema(self):
        from core.routes.config import CONFIG_SCHEMA

        ui_keys = _extract_models_tab_keys()
        assert ui_keys, "未能从 ModelsTab.tsx 解析出任何 key —— 正则可能需要更新"
        missing = sorted(k for k in ui_keys if k not in CONFIG_SCHEMA)
        assert not missing, (
            f"ModelsTab.tsx 引用了以下 key,但 core/routes/config.py::CONFIG_SCHEMA "
            f'里没有——POST /api/config 会对这些 key 返回 400,导致面板显示"保存失败": '
            f"{missing}"
        )

    def test_regression_openrouter_deepseek_ocr_openai_base_present(self):
        """本次真机复现直接命中的三个 key——显式钉住,防止再次漏同步。"""
        from core.routes.config import CONFIG_SCHEMA

        for key in ("OPENROUTER_API_KEY", "DEEPSEEK_OCR2_API_KEY", "OPENAI_API_BASE"):
            assert key in CONFIG_SCHEMA, f"{key} 缺失于 CONFIG_SCHEMA"


class TestSettingsTabKeysExistInConfigSchema:
    def test_every_settings_tab_key_is_in_config_schema(self):
        from core.routes.config import CONFIG_SCHEMA

        ui_keys = _extract_settings_tab_keys()
        assert ui_keys, "未能从 SettingsTab.tsx 解析出任何 key —— 正则可能需要更新"
        missing = sorted(k for k in ui_keys if k not in CONFIG_SCHEMA)
        assert not missing, f"SettingsTab.tsx 的 CONFIG_KEYS 引用了以下 key,但 CONFIG_SCHEMA 里没有: {missing}"


class TestPostConfigEndToEnd:
    """直接打 POST /api/config,复现并验证修复。"""

    def _client(self, tmp_path, monkeypatch):
        import core.routes.config as config_module

        # 隔离真实 .env,避免测试写脏仓库根目录的 .env。
        monkeypatch.setattr(config_module, "ENV_FILE", tmp_path / ".env.test")

        app = FastAPI()
        app.include_router(config_module.router)
        return TestClient(app)

    def test_saving_openrouter_key_no_longer_400s(self, tmp_path, monkeypatch):
        client = self._client(tmp_path, monkeypatch)
        resp = client.post("/api/config", json={"config": {"OPENROUTER_API_KEY": "sk-or-test"}})
        assert resp.status_code == 200, resp.text
        assert resp.json()["success"] is True

    def test_saving_deepseek_ocr_key_no_longer_400s(self, tmp_path, monkeypatch):
        client = self._client(tmp_path, monkeypatch)
        resp = client.post("/api/config", json={"config": {"DEEPSEEK_OCR2_API_KEY": "sk-ocr-test"}})
        assert resp.status_code == 200, resp.text

    def test_saving_openai_api_base_no_longer_400s(self, tmp_path, monkeypatch):
        client = self._client(tmp_path, monkeypatch)
        resp = client.post("/api/config", json={"config": {"OPENAI_API_BASE": "https://proxy.example.com/v1"}})
        assert resp.status_code == 200, resp.text

    def test_batch_save_with_one_previously_unknown_key_no_longer_fails_whole_batch(self, tmp_path, monkeypatch):
        """真实故障模式:同一批里混着一个能存的 key 和一个当时不认识的 key,
        整批 400,连本来能存的那个也存不进去。"""
        client = self._client(tmp_path, monkeypatch)
        resp = client.post(
            "/api/config",
            json={"config": {"DEEPSEEK_API_KEY": "sk-ds-test", "OPENROUTER_API_KEY": "sk-or-test"}},
        )
        assert resp.status_code == 200, resp.text
        assert set(resp.json()["updated"]) == {"DEEPSEEK_API_KEY", "OPENROUTER_API_KEY"}

    def test_truly_unknown_key_still_rejected(self, tmp_path, monkeypatch):
        """确认修复没有把校验整个关掉——真正未知的 key 仍应 400。"""
        client = self._client(tmp_path, monkeypatch)
        resp = client.post("/api/config", json={"config": {"TOTALLY_MADE_UP_KEY_XYZ": "x"}})
        assert resp.status_code == 400
