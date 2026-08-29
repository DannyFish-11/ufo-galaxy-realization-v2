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
        import core.config_store as config_store_module
        import core.routes.config as config_module

        # 隔离真实 .env,避免测试写脏仓库根目录的 .env。
        monkeypatch.setattr(config_module, "ENV_FILE", tmp_path / ".env.test")
        # 隔离真实 runtime/secrets.env:此前这里漏了这一步 —— POST /api/config
        # 里凡是分类为 secret 的 key(DEEPSEEK_API_KEY/OPENROUTER_API_KEY/...)会经
        # ConfigService().set_secret() 落到进程级单例 ConfigStore(core/config_store.py
        # 的 get_config_store()),而该单例默认路径就是仓库真实的
        # runtime/secrets.env——测试假密钥(sk-ds-test 等)会真的写进本地这份文件,
        # 污染真实的密钥库状态。改为进程级单例注入一个指向 tmp_path 的 ConfigStore。
        monkeypatch.setattr(
            config_store_module,
            "_singleton",
            config_store_module.ConfigStore(
                config_path=tmp_path / "config.json.test",
                secrets_path=tmp_path / "secrets.env.test",
            ),
        )

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


# ═══════════════════════════════════════════════════════════════════════════
# 反方向:CONFIG_SCHEMA → 面板
# ═══════════════════════════════════════════════════════════════════════════


class TestEverySchemaKeyIsReachableOrDeclaredAnAlias:
    """上面那一层查的是 **面板 → CONFIG_SCHEMA**(面板引用的键必须登记过)。
    这一层查**反方向**,而缺的一直是这个方向。

    没有它会发生什么(实际发生过)
    ----------------------------
    2026-08-29 盘点时,331 个配置项里有 8 个既不在面板上、也没被说明为什么不在。
    逐条查完是三种完全不同的东西:

    * **3 个是真别名**(``GEMINI_API_KEY`` / ``DASHSCOPE_API_KEY`` /
      ``SONAR_API_KEY``)—— 它们在 ``PROVIDER_REGISTRY`` 的 ``alt_env`` 里声明过,
      规范键已经在面板上。给别名再开一个输入框,等于同一个设置有两个框,
      填哪个都对但看起来像两件事。**不在面板上是对的。**
    * **4 个是真缺口**(``GALAXY_REASONING_OPENAI_*``)—— 推理位/独显那条泳道,
      ``multi_llm_router._LOCAL_OPENAI_LANES`` 早就按 env_prefix 认它们了,
      只是面板上没有地方填。感知位那台能在界面里配、推理位那台只能改 .env,
      而双模型档本来就是两台一起用。**已补。**
    * **1 个是死键**(``VLLM_URL``)—— 登记着、在明文回显白名单里、描述说是
      ``LOCAL_VLLM_URL`` 的别名,但**代码里零读取**。设了等于没设,而界面上
      看起来是可配的。这比"配不了"更糟:它谎称自己有用。**已删。**

    这三种混在一起时,盘点结果只是"8 个配不了",看不出哪个该补、哪个该删、
    哪个本来就该缺。这条判据把它们分开。

    别名从哪儿来
    ------------
    ``PROVIDER_REGISTRY[*].alt_env`` —— **不在这里另攒一份别名表**。另攒一份的
    表现是:registry 里加一个别名,这道门当场红,然后有人把它加进本地清单里
    "修好",于是两份清单开始各自漂移。
    """

    @staticmethod
    def _alias_keys() -> set[str]:
        from core.multi_llm_router import PROVIDER_REGISTRY

        return {alias for spec in PROVIDER_REGISTRY for alias in (spec.get("alt_env") or [])}

    @staticmethod
    def _panel_keys() -> set[str]:
        from core.routes.config_schema_registry import CONFIG_SCHEMA

        panel_src = "\n".join(
            p.read_text(encoding="utf-8") for p in (REPO_ROOT / "electron/renderer/panel/src").rglob("*.ts*")
        )
        return {k for k in CONFIG_SCHEMA if re.search(r"['\"]" + re.escape(k) + r"['\"]", panel_src)}

    def test_no_schema_key_is_silently_unreachable(self):
        from core.routes.config_schema_registry import CONFIG_SCHEMA

        unaccounted = sorted(set(CONFIG_SCHEMA) - self._panel_keys() - self._alias_keys())
        assert not unaccounted, (
            "这些配置项既不在面板上、也不是 PROVIDER_REGISTRY 声明的别名 —— "
            "用户改不了它们,而 CONFIG_SCHEMA 让它们看起来是可配的。"
            "该补面板就补,该删就删(零读取的死键),是别名就在 alt_env 里声明:"
            f"{unaccounted}"
        )

    def test_the_declared_aliases_are_actually_read(self):
        """别名之所以可以不上面板,前提是**它真的被读**。

        一个既不上面板、又没人读的键,挂着 alt_env 的名义就成了合法的死键 ——
        那正好绕过了上面那条判据。
        """
        import subprocess

        for alias in sorted(self._alias_keys()):
            hits = subprocess.run(
                ["grep", "-rl", alias, "--include=*.py", "core/", "galaxy_gateway/"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            ).stdout.strip()
            assert hits, f"{alias} 声明为别名但代码里没有任何一处提到它"

    def test_the_reasoning_lane_is_configurable_from_the_panel(self):
        """回归:推理位那条泳道曾经只能改 .env。

        钉住四个键而不是"至少一个" —— 少一个 SERVES,槽位解析就说不出这台服务
        伺候的是目录里哪个型号。
        """
        panel = self._panel_keys()
        for key in (
            "GALAXY_REASONING_OPENAI_URL",
            "GALAXY_REASONING_OPENAI_MODEL",
            "GALAXY_REASONING_OPENAI_SERVES",
            "GALAXY_REASONING_OPENAI_KEY",
        ):
            assert key in panel, f"{key} 不在面板上 —— 推理位那台服务又只能改 .env 了"

    def test_the_dead_key_stays_dead(self):
        """回归:``VLLM_URL`` 零读取,已从 CONFIG_SCHEMA 删除。

        ``LOCAL_VLLM_URL`` 是真的那个,留着。这条挡的是"看着像少了个别名,顺手补回去"。
        """
        from core.routes.config import _NON_SECRET_MODEL_KEYS
        from core.routes.config_schema_registry import CONFIG_SCHEMA

        assert "VLLM_URL" not in CONFIG_SCHEMA
        assert "VLLM_URL" not in _NON_SECRET_MODEL_KEYS
        assert "LOCAL_VLLM_URL" in CONFIG_SCHEMA
