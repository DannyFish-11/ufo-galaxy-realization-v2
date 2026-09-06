"""看图和听声那两条路,必须与主链**用同一把钥匙、同一条取法**。

## 背景:它们是两条旁路

``core/vision_pipeline.py`` 和 ``core/audio_pipeline.py`` 不走 ``MultiLLMRouter``。
它们各自拿 key、各自发 httpx、各自四级降级。这在架构上是一个有意的选择(那是
"委派式感知":把看图/听声外包给专门的模型),但它带来一个**不该有的副作用** ——
密钥的取法与主链不是同一条:

* 面板把密钥存进 Vault / ``runtime/secrets.env``,只读 ``os.getenv`` 的那一侧
  在某些路径上根本看不见;
* 占位符(``your_..._here``)在路由器那侧会被过滤,在裸 getenv 那侧会被当成真密钥,
  于是那一路"看起来配好了",一发请求才认证失败;
* 名字回落各写各的:音频那条 ``GEMINI_API_KEY`` 取不到会退回 ``GOOGLE_API_KEY``,
  视觉那条不会。**同一台机器、同一把 Google 密钥,语音能用、看图不能用** ——
  而没有任何一处会说出这件事。

这些用例钉的就是最后那条真坑,以及它的根:两条路现在都问
``core.credential_vault.resolve_key``。
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "DEEPSEEK_OCR2_API_KEY",
        "NOVITA_API_KEY",
        "OPENROUTER_API_KEY",
    ):
        monkeypatch.delenv(k, raising=False)


class TestOneGoogleKeyWorksForBothLanes:
    """这是那个真坑:只填面板主推的 GOOGLE_API_KEY,两条路都要能用。"""

    def test_vision_falls_back_to_the_general_google_key(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "sk-google")
        from core.vision_pipeline import VisionPipeline

        assert VisionPipeline().gemini_api_key == "sk-google", (
            "只填了 GOOGLE_API_KEY,看图那条就取不到 —— 而语音那条取得到。"
            "同一把钥匙、同一台机器,一半能用一半不能用,且没有任何提示"
        )

    def test_audio_falls_back_the_same_way(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "sk-google")
        from core.audio_pipeline import AudioPipeline

        assert AudioPipeline().gemini_api_key == "sk-google"

    def test_the_dedicated_name_still_wins_when_both_are_set(self, monkeypatch):
        """回落是回落,不能反过来把专用名盖掉。"""
        monkeypatch.setenv("GEMINI_API_KEY", "sk-dedicated")
        monkeypatch.setenv("GOOGLE_API_KEY", "sk-general")
        from core.audio_pipeline import AudioPipeline
        from core.vision_pipeline import VisionPipeline

        assert VisionPipeline().gemini_api_key == "sk-dedicated"
        assert AudioPipeline().gemini_api_key == "sk-dedicated"


class TestAPlaceholderIsNotAKey:
    """``.env.example`` 里没改的模板值不能被当成真密钥。

    被当成真密钥的后果:那一级降级会被认为"已配置",于是排在真正可用的那一级
    前面,每次都先撞一次 401 再往下走 —— 而日志里只有一句认证失败。
    """

    def test_vision_treats_a_template_value_as_unconfigured(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "your_gemini_api_key_here")
        from core.vision_pipeline import VisionPipeline

        assert VisionPipeline().gemini_api_key == ""

    def test_audio_treats_a_template_value_as_unconfigured(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "your_openai_api_key_here")
        from core.audio_pipeline import AudioPipeline

        assert AudioPipeline().openai_api_key == ""


class TestTheVaultIsVisibleToBothLanes:
    """面板存进 Vault 的密钥,这两条路要能读到 —— 裸 getenv 读不到。"""

    def test_a_key_only_in_the_vault_is_found(self, monkeypatch):
        import core.credential_vault as cv

        class _FakeVault:
            def get_credential(self, name, actor="system"):  # noqa: D102
                return "sk-from-vault" if name == "OPENROUTER_API_KEY" else None

        monkeypatch.setattr(cv, "get_vault", lambda: _FakeVault())
        from core.vision_pipeline import VisionPipeline

        assert VisionPipeline().openrouter_api_key == "sk-from-vault"


class TestNeitherLaneReadsTheEnvironmentBehindTheChainsBack:
    def test_both_pipelines_ask_the_shared_resolver(self):
        """白盒:两处都必须调 resolve_key。

        黑盒用例只能证明**现在**的行为对;这一条钉的是"别再自己 getenv" ——
        那正是上面所有分歧的来源,而它复发时不会有任何报错。
        """
        import inspect

        from core.audio_pipeline import AudioPipeline
        from core.vision_pipeline import VisionPipeline

        for cls in (VisionPipeline, AudioPipeline):
            src = inspect.getsource(cls.__init__)
            assert "resolve_key" in src, f"{cls.__name__} 又自己 getenv 取密钥了"


class TestThePanelCanConfigureEverythingTheseLanesRead:
    """这两条路真的在读的键,面板上必须都配得了。

    配不了的后果不是"少个高级选项":换一家 OCR 中转、换一个音频型号,只能去改
    .env 或者改代码 —— 而面板恰恰是这个系统让人配 API 的地方。
    """

    @pytest.mark.parametrize(
        "key",
        [
            "DEEPSEEK_OCR2_API_KEY",
            "NOVITA_API_KEY",
            "DEEPSEEK_OCR2_API_BASE",
            "DEEPSEEK_OCR2_MODEL",
            "GEMINI_API_KEY",
            "OPENROUTER_API_KEY",
            "LOCAL_VLLM_URL",
            "GEMINI_AUDIO_MODEL",
            "OPENAI_AUDIO_MODEL",
            "OPENAI_API_BASE",
        ],
    )
    def test_it_is_in_the_config_schema(self, key):
        from core.routes.config_schema_registry import CONFIG_SCHEMA

        assert key in CONFIG_SCHEMA, f"{key} 是这两条路真的在读的键,面板上却配不了"

    def test_they_are_all_filed_under_the_supplier_section(self):
        """都是"填 API 地址/密钥/型号"这一类事,该和厂商密钥在同一档里。"""
        from core.routes.config_schema_registry import CONFIG_SCHEMA

        for key in ("NOVITA_API_KEY", "DEEPSEEK_OCR2_API_BASE", "GEMINI_AUDIO_MODEL", "OPENAI_AUDIO_MODEL"):
            assert CONFIG_SCHEMA[key]["category"] == "llm", f"{key} 不在「供应商与密钥」那一档"
