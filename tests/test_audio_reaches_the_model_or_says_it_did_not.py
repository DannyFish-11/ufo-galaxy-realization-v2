"""录音要么原样到模型，要么**说出来它没到** —— 不许静默丢掉。

## 这一套要挡的是什么

音频比图像更容易被静默丢掉,因为它经过的关卡更多:

1. **要不要发**    —— 默认走 ASR 转文字(便宜、通用);原生音频是按需升级的;
2. **型号收不收**  —— 只有少数型号收音频;
3. **传输装不装**  —— 同一个型号在不同传输上不一样(本仓的 Responses 适配器
   没实现音频部件;Ollama 的音频要走 /v1,而适配器发的是 /api/chat)。

三关任何一关没过,如果处理成"悄悄不发",现象是**完全正常的一轮对话** ——
模型照常作答,只是它根本没听见那段录音,而没有任何人会发现。

所以这里钉的是:每一关拦下来都要**摘掉 + 在正文里写明 + 打 warning**,三样都要有。

## 依据从哪来

哪些型号收音频,不是从型号名字猜的,是**这个仓库自己已经在跑的代码**:
``core/audio_pipeline.py`` 对 ``gpt-4o-audio-preview`` 发 ``input_audio``、
对 ``gemini-2.0-flash`` 发 ``inline_data``。那两条路是活的。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket
import threading
from typing import Any, Dict, List

import pytest
import uvicorn
from fastapi import FastAPI, Request

WAV_B64 = "UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA="

AUDIO_MSG = [
    {"role": "system", "content": "你是助手"},
    {
        "role": "user",
        "content": [
            {"type": "text", "text": "这段录音里他是不是不高兴"},
            {"type": "input_audio", "input_audio": {"data": WAV_B64, "format": "wav"}},
        ],
    },
]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class _Upstream:
    def __init__(self) -> None:
        self.port = _free_port()
        self.seen: List[Dict[str, Any]] = []
        app = FastAPI()

        @app.post("/v1/chat/completions")
        async def chat(req: Request):  # noqa: ANN202
            self.seen.append(await req.json())
            return {
                "choices": [{"message": {"role": "assistant", "content": "好"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }

        cfg = uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="error")
        self.server = uvicorn.Server(cfg)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def __enter__(self) -> "_Upstream":
        import time

        self.thread.start()
        for _ in range(100):
            if self.server.started:
                return self
            time.sleep(0.05)
        raise RuntimeError("测试上游没起来")

    def __exit__(self, *exc) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)


@contextlib.contextmanager
def _warnings():
    records: List[logging.LogRecord] = []

    class _H(logging.Handler):
        def emit(self, record):  # noqa: D102
            records.append(record)

    lg = logging.getLogger("Galaxy.Modality")
    h = _H(level=logging.WARNING)
    lg.addHandler(h)
    old = lg.level
    lg.setLevel(logging.WARNING)
    try:
        yield records
    finally:
        lg.removeHandler(h)
        lg.setLevel(old)


class TestTheRecordingReallyArrivesWhenEverythingSupportsIt:
    def test_an_audio_model_gets_the_clip_over_chat_completions(self):
        """端到端:对着真服务器发,断言 input_audio 躺在请求体里。"""
        from core.llm_adapters import OpenAIAdapter
        from core.llm_types import ProviderConfig

        with _Upstream() as up:
            cfg = ProviderConfig(
                name="openai",
                api_key="sk-test",
                base_url=up.base_url,
                models=["gpt-4o-audio-preview"],
                default_model="gpt-4o-audio-preview",
            )
            asyncio.new_event_loop().run_until_complete(OpenAIAdapter(cfg).chat(AUDIO_MSG, "gpt-4o-audio-preview"))
            body = up.seen[-1]

        part = next(p for p in body["messages"][1]["content"] if p["type"] == "input_audio")
        assert part["input_audio"]["data"] == WAV_B64
        assert part["input_audio"]["format"] == "wav"


class TestEveryGateThatBlocksItSaysSo:
    """三关各一条。判据都是同一组三样:摘掉 + 正文写明 + 打 warning。"""

    @staticmethod
    def _assert_dropped_and_announced(out, records, expect_in_message: str):
        content = out[1]["content"]
        assert isinstance(content, str), "音频没被摘掉 —— 会发给一个收不了它的地方"
        assert "未发送" in content, "摘掉了却没在正文里说明,模型不知道自己少了什么"
        assert any(expect_in_message in r.getMessage() for r in records), "没有留痕"

    def test_a_model_that_does_not_take_audio(self):
        from core.modality import prepare

        with _warnings() as records:
            out = prepare("openai", AUDIO_MSG, model="gpt-5.6", provider="openai")
        self._assert_dropped_and_announced(out, records, "不接收")

    def test_a_transport_that_cannot_carry_audio(self):
        """型号收得了、这条传输装不下 —— 两件事,报出来要能分清是哪一件。

        Ollama 的音频要走它的 /v1 兼容面,而这个适配器发的是 /api/chat
        (原生那条的 audios 字段会被静默忽略)。
        """
        from core.modality import prepare

        with _warnings() as records:
            out = prepare("ollama", AUDIO_MSG, model="gpt-4o-audio-preview", provider="openai")
        self._assert_dropped_and_announced(out, records, "装不下")

    def test_anthropic_has_no_audio_input_at_all(self):
        from core.modality import prepare

        with _warnings() as records:
            out = prepare("anthropic", AUDIO_MSG, model="claude-sonnet-5", provider="anthropic")
        self._assert_dropped_and_announced(out, records, "audio")

    def test_only_the_blocked_modality_is_dropped(self):
        """图能发、音发不了的时候,不许把图也一起丢掉 —— 那是白白少做一件事。"""
        from core.modality import prepare

        mixed = [
            {"role": "system", "content": "x"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "看图听音"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}},
                    {"type": "input_audio", "input_audio": {"data": WAV_B64, "format": "wav"}},
                ],
            },
        ]
        out = prepare("openai", mixed, model="gpt-5.6", provider="openai")
        kinds = [p["type"] for p in out[1]["content"]]
        assert "image_url" in kinds, "图被音频连累一起丢了"
        assert "input_audio" not in kinds


class TestTheDefaultIsStillSpeechToText:
    """默认不发原生音频 —— ASR 已经把"他说了什么"转成文字了,原生多出来的只有
    语气/环境声那部分,不是每轮都值那个 token 钱。"""

    @staticmethod
    def _ctx(meta=None):
        from core.schemas.multimodal import MultiModalAudio, MultiModalContext

        return MultiModalContext(
            audio=[MultiModalAudio(mime="audio/wav", data=WAV_B64)],
            metadata=meta or {},
        )

    def test_audio_is_not_attached_by_default(self, monkeypatch):
        monkeypatch.delenv("GALAXY_NATIVE_AUDIO_CHAT", raising=False)
        from core.agent.multimodal_messages import build_user_message_content

        assert build_user_message_content("在说什么", self._ctx()) == "在说什么"

    def test_the_caller_can_ask_for_it_on_this_one_turn(self, monkeypatch):
        monkeypatch.delenv("GALAXY_NATIVE_AUDIO_CHAT", raising=False)
        from core.agent.multimodal_messages import build_user_message_content

        content = build_user_message_content("听听他语气", self._ctx({"want_native_audio": True}))
        assert isinstance(content, list)
        assert any(p["type"] == "input_audio" for p in content)

    def test_the_setting_can_turn_it_on_for_every_turn(self, monkeypatch):
        monkeypatch.setenv("GALAXY_NATIVE_AUDIO_CHAT", "1")
        from core.agent.multimodal_messages import build_user_message_content

        content = build_user_message_content("在说什么", self._ctx())
        assert isinstance(content, list)
        assert any(p["type"] == "input_audio" for p in content)

    def test_the_format_comes_from_the_same_conversion_as_the_audio_lane(self):
        """格式换算不许写第二遍 —— 两边认的格式不一样时,症状是"某种录音在对话里
        发不出去、在那条旁路里却好好的"。"""
        import inspect

        from core.agent import multimodal_messages as mm

        assert "_openai_audio_format" in inspect.getsource(mm._audio_format)

    def test_the_switch_is_settable_from_the_panel(self):
        from core.routes.config_schema_registry import CONFIG_SCHEMA

        meta = CONFIG_SCHEMA["GALAXY_NATIVE_AUDIO_CHAT"]
        assert meta["default"] == "false", "默认必须是关 —— 开着会让每轮带录音的对话都烧音频 token"


class TestWhatWeClaimToSupportIsWhatWeImplemented:
    def test_no_protocol_claims_a_modality_its_translator_cannot_produce(self):
        """``PROTOCOL_MODALITIES`` 声称能装的,``to_native`` 必须真的翻得出来。

        声称了却翻不出来,等于把一个没实现的能力伪装成实现了:上游收到一个它不认的
        部件,多半安静地忽略掉。
        """
        from core.modality import AUDIO, IMAGE, PROTOCOL_MODALITIES, to_native

        probes = {
            IMAGE: {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}},
            AUDIO: {"type": "input_audio", "input_audio": {"data": WAV_B64, "format": "wav"}},
        }
        for proto, mods in PROTOCOL_MODALITIES.items():
            for modality, part in probes.items():
                if modality not in mods:
                    continue
                msgs = [{"role": "user", "content": [{"type": "text", "text": "x"}, part]}]
                out = to_native(proto, msgs)
                content = out[0]["content"]
                survived = (isinstance(content, list) and len(content) > 1) or bool(out[0].get("images"))
                assert survived, f"{proto} 声称能装 {modality},但 to_native 把它翻没了"
