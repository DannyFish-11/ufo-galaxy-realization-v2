"""阶跃(StepFun)的全双工 realtime 接进双工会话,以及视频上行这条新加的路。

## 为什么阶跃这条是**继承** OpenAI 适配器而不是新写一份

阶跃的 WS 面与 OpenAI Realtime 同构(官方 Step-Realtime-Console 用的就是一份改过的
OpenAI SDK,端点形式也一样)。同构却各写一份,得到的是两份会各自漂移的实现 ——
本仓已经因为"同一件事两份实现"吃过几次亏。所以只改真正不同的三处:
鉴权头、voice 必填、不发 input_audio_transcription。

下面的用例就按这三处来钉:**同构的部分必须真的相同**(而不是碰巧写得像),
**不同的三处必须真的不同**。

## 没核实到的部分,测试不假装它被核实了

``platform.stepfun.com`` / ``.ai`` / arxiv 在开发环境被出网代理挡住,所以事件名没能
逐条对照官方文档。这里**不**去断言"阶跃的事件名就是 OpenAI 那套" —— 那会把一个推断
钉成事实。能断言的是结构关系(继承自谁、哪几处被改了),那是代码里的事实。
"""

import pytest

from core.voice_duplex_session import (
    _ADAPTERS,
    DuplexSessionConfig,
    GeminiLiveAdapter,
    OpenAIRealtimeAdapter,
    StepRealtimeAdapter,
    get_adapter,
)

STEP_MODEL = "stepaudio-3-realtime-preview"


def _cfg(**kw):
    base = dict(
        url=f"wss://api.stepfun.com/v1/realtime?model={STEP_MODEL}",
        api_key="sk-step-test",
        model=STEP_MODEL,
        voice="qingchunshaonv",
        provider="step_realtime",
    )
    base.update(kw)
    return DuplexSessionConfig(**base)


class TestItIsRegistered:
    def test_get_adapter_returns_the_step_adapter(self):
        assert isinstance(get_adapter("step_realtime"), StepRealtimeAdapter)

    def test_an_unknown_provider_still_raises_instead_of_silently_defaulting(self):
        """登记表的价值在于"没登记的会炸" —— 静默退回默认实现会让人以为在用 A、实发 B。"""
        with pytest.raises(ValueError):
            get_adapter("stepfun")  # 名字写错的常见形态


class TestOnlyThreeThingsDifferFromOpenAI:
    def test_it_inherits_rather_than_reimplements(self):
        assert issubclass(StepRealtimeAdapter, OpenAIRealtimeAdapter)

    def test_the_auth_header_drops_the_openai_beta_marker(self):
        h = StepRealtimeAdapter().headers(_cfg())
        assert h == {"Authorization": "Bearer sk-step-test"}
        assert "OpenAI-Beta" in OpenAIRealtimeAdapter().headers(_cfg()), "对照组:OpenAI 那边确实有这个头"

    def test_it_does_not_send_openais_whisper_transcription_model(self):
        """whisper-1 是 OpenAI 自己的模型名,往别家 session 里塞一个没核实过的名字,
        失败方向是坏的(整帧被拒 / 被静默忽略)。而上行转写本来就不是双工的必需品。"""
        step = StepRealtimeAdapter().session_update(_cfg())["session"]
        openai = OpenAIRealtimeAdapter().session_update(_cfg())["session"]
        assert "input_audio_transcription" not in step
        assert openai["input_audio_transcription"] == {"model": "whisper-1"}, "对照组"

    def test_everything_else_is_byte_for_byte_the_same_shape(self):
        """同构的部分必须**真的**相同 —— 这条正是"继承而非另写"的意义所在。"""
        step = StepRealtimeAdapter().session_update(_cfg())["session"]
        openai = OpenAIRealtimeAdapter().session_update(_cfg())["session"]
        openai.pop("input_audio_transcription")
        assert step == openai

    def test_the_audio_and_interrupt_frames_are_inherited_unchanged(self):
        pcm = b"\x01\x02\x03\x04"
        assert StepRealtimeAdapter().audio_frame(pcm) == OpenAIRealtimeAdapter().audio_frame(pcm)
        assert StepRealtimeAdapter().interrupt_frame() == OpenAIRealtimeAdapter().interrupt_frame()


class TestVoiceIsMandatory:
    def test_an_empty_voice_fails_loudly_instead_of_being_rejected_by_the_server(self):
        """阶跃把 voice 列为必需参数。与其发一个必然被拒的帧、再去读服务端的错,
        不如在这里就说清楚缺什么、去哪儿配。"""
        with pytest.raises(ValueError) as exc:
            StepRealtimeAdapter().session_update(_cfg(voice=""))
        assert "voice" in str(exc.value)
        assert "GALAXY_REALTIME_VOICE" in str(exc.value), "报错要说清去哪儿配,否则等于只说了'不行'"


class TestFromEnvWiresTheWholeThing:
    """判据盯着**真的走一遍 from_env**,而不是读代码里写没写那几个字符串。"""

    def test_it_builds_the_step_endpoint_and_picks_up_the_registry_defaults(self, monkeypatch):
        monkeypatch.setenv("GALAXY_REALTIME_PROVIDER", "step_realtime")
        monkeypatch.setenv("STEP_API_KEY", "sk-step-real")
        monkeypatch.delenv("GALAXY_REALTIME_URL", raising=False)
        monkeypatch.delenv("GALAXY_REALTIME_MODEL", raising=False)
        monkeypatch.delenv("GALAXY_REALTIME_VOICE", raising=False)

        cfg = DuplexSessionConfig.from_env()
        assert cfg is not None
        assert cfg.provider == "step_realtime"
        assert cfg.url.startswith("wss://api.stepfun.com/v1/realtime?model=")
        assert cfg.api_key == "sk-step-real"
        assert cfg.voice, "voice 必填,from_env 必须保证它不是空串"

    def test_the_model_comes_from_the_registry_not_a_literal_in_this_file(self, monkeypatch):
        """型号是 PROVIDER_REGISTRY 说了算 —— 那里才有漂移守卫
        (scripts/verify_provider_apis.py 只比对 registry)。"""
        from core.provider_registry import PROVIDER_REGISTRY

        spec = next(s for s in PROVIDER_REGISTRY if s["name"] == "step")
        monkeypatch.setenv("GALAXY_REALTIME_PROVIDER", "step_realtime")
        monkeypatch.setenv("STEP_API_KEY", "sk-step-real")
        monkeypatch.delenv("GALAXY_REALTIME_URL", raising=False)
        monkeypatch.delenv("GALAXY_REALTIME_MODEL", raising=False)

        cfg = DuplexSessionConfig.from_env()
        assert cfg.model == spec["default_realtime_model"]

    def test_no_key_means_no_session_rather_than_a_half_built_one(self, monkeypatch):
        monkeypatch.setenv("GALAXY_REALTIME_PROVIDER", "step_realtime")
        monkeypatch.delenv("STEP_API_KEY", raising=False)
        monkeypatch.delenv("GALAXY_REALTIME_API_KEY", raising=False)
        monkeypatch.delenv("GALAXY_REALTIME_URL", raising=False)
        monkeypatch.setenv("GALAXY_SECRET_BACKEND", "env")
        assert DuplexSessionConfig.from_env() is None


class TestTheRegistryEntryItself:
    def test_step_declares_its_realtime_models_separately_from_text_models(self):
        from core.provider_registry import PROVIDER_REGISTRY

        spec = next(s for s in PROVIDER_REGISTRY if s["name"] == "step")
        assert spec["realtime_models"], "双工型号要与文本型号分开维护(同 openai / google)"
        assert spec["default_realtime_model"] in spec["realtime_models"]
        assert not set(spec["realtime_models"]) & set(spec["models"]), "两类型号走的是完全不同的接口,不该混"

    def test_the_cross_verified_model_name_is_still_listed(self):
        """step-2.5-realtime 是目前**唯一交叉验证过**的双工型号名。默认那个若不对,
        改成它即可 —— 所以它必须一直在列表里,而不是被"只留最新"清掉。"""
        from core.provider_registry import PROVIDER_REGISTRY

        spec = next(s for s in PROVIDER_REGISTRY if s["name"] == "step")
        assert "step-2.5-realtime" in spec["realtime_models"]


class TestVideoUplink:
    """新加的一条路:把画面帧送进双工会话。"""

    def test_gemini_live_accepts_video_on_the_same_media_channel(self):
        frame = GeminiLiveAdapter().video_frame(b"\xff\xd8\xff")
        assert frame is not None
        chunk = frame["realtimeInput"]["mediaChunks"][0]
        assert chunk["mimeType"] == "image/jpeg"
        assert chunk["data"], "帧要 base64 进去,不是原样塞二进制"

    def test_video_and_audio_share_one_channel_on_gemini(self):
        """这正是 Gemini「每块自带 mimeType」换来的:视频不必另开通道、也不改 setup。"""
        a = GeminiLiveAdapter().audio_frame(b"\x00\x01")
        v = GeminiLiveAdapter().video_frame(b"\xff\xd8")
        assert set(a) == set(v) == {"realtimeInput"}
        assert a["realtimeInput"]["mediaChunks"][0]["mimeType"].startswith("audio/")
        assert v["realtimeInput"]["mediaChunks"][0]["mimeType"].startswith("image/")

    @pytest.mark.parametrize("name", ["openai_realtime", "step_realtime"])
    def test_providers_without_a_verified_video_format_say_so_instead_of_guessing(self, name):
        """**返回 None = 这家没有视频上行**,不是"出错了"。

        凭猜测拼一个视频帧发出去,结果要么 session 被拒、要么被静默丢弃 ——
        两种都比"明确说这家不支持"更难排查。
        """
        assert get_adapter(name).video_frame(b"\xff\xd8") is None

    def test_the_base_class_default_is_no_video_rather_than_a_crash(self):
        """新增 provider 时不写 video_frame,得到的是"不支持",而不是运行期炸。"""
        from core.voice_duplex_session import ProtocolAdapter

        assert ProtocolAdapter().video_frame(b"\xff\xd8") is None
