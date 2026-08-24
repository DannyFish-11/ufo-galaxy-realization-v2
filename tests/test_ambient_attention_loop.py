"""tests/test_ambient_attention_loop.py
==========================================

全路径覆盖常驻注意力循环（自发在场）:
  门控放行/拦截 · 三选一解析 · 三路路由(SPEAK/SILENT/DELEGATE) ·
  记忆写回(工作记忆恒写、终身记忆仅 salient) · 事件发布 · 冷却 · 音频去重 ·
  帧差门控 · 决策脑多模态消息构造与降级。

所有协作者通过构造注入,不触网、不起真循环。
"""

from __future__ import annotations

import asyncio
import base64
import io
from typing import Any, Dict, List, Optional

import pytest

from core.ambient_attention_loop import (
    AmbientAction,
    AmbientAttentionLoop,
    AmbientDecision,
    AmbientObservation,
    FrameGate,
    LLMRouterDecider,
    parse_decision,
)


# ── 测试用真实 JPEG 帧 ──────────────────────────────────────────────────────
def _jpeg(color: int, size: int = 64) -> str:
    from PIL import Image

    img = Image.new("L", (size, size), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


_BLACK = _jpeg(0)
_WHITE = _jpeg(255)


# ── Fakes ───────────────────────────────────────────────────────────────────
class FakeStore:
    def __init__(self, media: Dict[str, Any]):
        self._media = media

    def snapshot_media(self) -> Dict[str, Any]:
        return dict(self._media)

    def set(self, **kw):
        self._media.update(kw)


class FakeWM:
    def __init__(self):
        self.adds: List[Dict[str, Any]] = []

    def add(self, *, session_id, role, content, trace_id="", metadata=None):
        self.adds.append({"session_id": session_id, "role": role, "content": content, "metadata": metadata})


class FakeUM:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.remembered: List[Dict[str, Any]] = []
        self.media: List[Dict[str, Any]] = []

    def remember(self, content, *, modality="text", tags=None, metadata=None, origin=None):
        # origin 是 UnifiedMemory.remember 的参数(见 core/memory_provenance.py)。
        # 替身漏掉它的话,调用方传 origin 会 TypeError,而这里的调用点外面包着
        # 一层 `except Exception: logger.debug(...)` —— 于是记忆一条都写不进去,
        # **而且悄无声息**。这个替身必须跟着真接口走。
        self.remembered.append(
            {"content": content, "modality": modality, "tags": tags, "origin": origin}
        )

    def remember_media(self, data_b64, *, modality, mime="", tags=None, metadata=None, caption=""):
        self.media.append({"modality": modality, "caption": caption})


class FakeBus:
    def __init__(self):
        self.events: List[Dict[str, Any]] = []

    def publish(self, event_type, *, source, payload=None, **kw):
        self.events.append({"type": event_type, "source": source, "payload": payload})


class FakeDecider:
    def __init__(self, decision: AmbientDecision):
        self.decision = decision
        self.calls = 0
        self.last_obs: Optional[AmbientObservation] = None

    async def decide(self, obs: AmbientObservation) -> AmbientDecision:
        self.calls += 1
        self.last_obs = obs
        return self.decision


def _loop(store, decider, **kw):
    return AmbientAttentionLoop(
        decider=decider,
        perception_store=store,
        working_memory=kw.pop("wm", FakeWM()),
        unified_memory=kw.pop("um", FakeUM()),
        event_bus=kw.pop("bus", FakeBus()),
        cooldown_s=kw.pop("cooldown_s", 0.0),
        **kw,
    )


# ── parse_decision ────────────────────────────────────────────────────────────
class TestParseDecision:
    def test_speak(self):
        d = parse_decision("SPEAK\n用户卡在报错上\n说：需要我帮你查这个报错吗？")
        assert d.action == AmbientAction.SPEAK
        assert d.utterance == "需要我帮你查这个报错吗？"
        assert d.rationale == "用户卡在报错上"
        assert d.salient is True

    def test_silent(self):
        d = parse_decision("SILENT\n用户在正常打字，无需打扰")
        assert d.action == AmbientAction.SILENT
        assert d.salient is False

    def test_delegate(self):
        d = parse_decision("DELEGATE\n屏幕反复报同一个错\n派：查看最近的错误日志并定位原因")
        assert d.action == AmbientAction.DELEGATE
        assert d.task == "查看最近的错误日志并定位原因"
        assert d.salient is True

    def test_malformed_defaults_silent(self):
        assert parse_decision("我觉得这个画面挺好看的").action == AmbientAction.SILENT
        assert parse_decision("").action == AmbientAction.SILENT

    def test_speak_without_content_degrades_to_silent(self):
        # SPEAK 但既无"说："也无理由 → 不空口说白话，降级 SILENT
        assert parse_decision("SPEAK").action == AmbientAction.SILENT

    def test_speak_uses_rationale_when_no_utterance(self):
        d = parse_decision("SPEAK\n你回来了")
        assert d.action == AmbientAction.SPEAK
        assert d.utterance == "你回来了"

    def test_delegate_without_task_degrades_to_silent(self):
        assert parse_decision("DELEGATE").action == AmbientAction.SILENT

    def test_first_token_wins_over_body_keyword(self):
        # 首行 SILENT 即便正文出现 speak 字样也应沉默
        assert parse_decision("SILENT\n没必要 speak").action == AmbientAction.SILENT


# ── FrameGate ────────────────────────────────────────────────────────────────
class TestFrameGate:
    def test_first_frame_is_change(self):
        assert FrameGate().changed(_BLACK) is True

    def test_identical_frame_not_change(self):
        g = FrameGate()
        assert g.changed(_BLACK) is True
        assert g.changed(_BLACK) is False

    def test_big_visual_change_detected(self):
        g = FrameGate()
        g.changed(_BLACK)
        assert g.changed(_WHITE) is True

    def test_none_frame_not_change(self):
        assert FrameGate().changed(None) is False


# ── tick: 门控 ────────────────────────────────────────────────────────────────
class TestTickGating:
    def test_no_perception_gates_out_no_decider_call(self):
        store = FakeStore({})  # 无帧无音频
        dec = FakeDecider(AmbientDecision(AmbientAction.SILENT))
        loop = _loop(store, dec)
        result = asyncio.run(loop.tick())
        assert result is None
        assert dec.calls == 0  # 门控挡下，不惊动模型

    def test_static_frame_gates_out_after_first(self):
        store = FakeStore({"camera_b64": _BLACK, "camera_mime": "image/jpeg"})
        dec = FakeDecider(AmbientDecision(AmbientAction.SILENT, rationale="ok"))
        loop = _loop(store, dec)
        first = asyncio.run(loop.tick())  # 第一帧 → 放行
        assert first is not None and dec.calls == 1
        second = asyncio.run(loop.tick())  # 同一帧 → 挡下
        assert second is None and dec.calls == 1

    def test_frame_change_triggers_decider(self):
        store = FakeStore({"camera_b64": _BLACK, "camera_mime": "image/jpeg"})
        dec = FakeDecider(AmbientDecision(AmbientAction.SILENT, rationale="ok"))
        loop = _loop(store, dec)
        asyncio.run(loop.tick())
        store.set(camera_b64=_WHITE)  # 画面大变
        assert asyncio.run(loop.tick()) is not None
        assert dec.calls == 2

    def test_new_audio_triggers_even_without_frame_change(self):
        store = FakeStore({"camera_b64": _BLACK, "audio_b64": "AAAA", "audio_mime": "audio/webm"})
        dec = FakeDecider(AmbientDecision(AmbientAction.SILENT, rationale="ok"))
        loop = _loop(store, dec)
        asyncio.run(loop.tick())  # 首拍消费帧+音频
        # 帧不变，但来一段新音频 → 仍放行
        store.set(audio_b64="BBBB")
        assert asyncio.run(loop.tick()) is not None
        assert dec.calls == 2

    def test_same_audio_deduped(self):
        store = FakeStore({"camera_b64": _BLACK, "audio_b64": "AAAA"})
        dec = FakeDecider(AmbientDecision(AmbientAction.SILENT, rationale="ok"))
        loop = _loop(store, dec)
        asyncio.run(loop.tick())  # 首拍
        # 帧不变、音频也是同一段 → 挡下
        assert asyncio.run(loop.tick()) is None
        assert dec.calls == 1

    def test_cooldown_blocks_after_action(self):
        store = FakeStore({"camera_b64": _BLACK})
        dec = FakeDecider(AmbientDecision(AmbientAction.SPEAK, utterance="hi", salient=True))
        loop = _loop(store, dec, cooldown_s=999.0)
        # 首拍 SPEAK → 记录动作时间戳
        with _patch_speak() as spoken:
            asyncio.run(loop.tick())
            assert spoken
        # 冷却期内即便画面大变也挡下
        store.set(camera_b64=_WHITE)
        assert asyncio.run(loop.tick()) is None


class TestAmbientHearing:
    """听:ambient 决策脑是纯文本消费者,想"听"就必须转写。原生音频门控
    (GALAXY_NATIVE_AUDIO)管的是全模态服务通路,不该让常驻循环变聋。"""

    def _run_with_transcript(self, monkeypatch, native_gate: str) -> Optional[str]:
        monkeypatch.setenv("GALAXY_NATIVE_AUDIO", native_gate)
        # 桥接转写打桩:返回定值,证明"确实调了转写"。
        import core.modality_bridge as mb

        monkeypatch.setattr(mb, "transcribe_b64", lambda b64, mime="audio/webm", language="zh": "用户说了话")
        store = FakeStore({"camera_b64": _BLACK, "audio_b64": "AAAA", "audio_mime": "audio/webm"})
        dec = FakeDecider(AmbientDecision(AmbientAction.SILENT, rationale="ok"))
        loop = _loop(store, dec)
        asyncio.run(loop.tick())
        return dec.last_obs.audio_transcript if dec.last_obs else None

    def test_transcribes_when_native_gate_off(self, monkeypatch):
        assert self._run_with_transcript(monkeypatch, "0") == "用户说了话"

    def test_transcribes_even_when_native_gate_on(self, monkeypatch):
        # 回归:此前门控开=跳过转写→原生音频又无处送→决策脑收到空 transcript(聋)。
        assert self._run_with_transcript(monkeypatch, "1") == "用户说了话"


# ── tick: 三路路由 ────────────────────────────────────────────────────────────
import contextlib
from unittest.mock import patch


@contextlib.contextmanager
def _patch_speak():
    spoken: List[str] = []
    with patch("core.speech_output.speak_response", side_effect=lambda text, source="": spoken.append((text, source))):
        yield spoken


class TestTickRouting:
    def test_speak_routes_to_tts_and_records(self):
        store = FakeStore({"camera_b64": _BLACK})
        wm, um, bus = FakeWM(), FakeUM(), FakeBus()
        dec = FakeDecider(
            AmbientDecision(AmbientAction.SPEAK, rationale="卡住了", utterance="要帮忙吗？", salient=True)
        )
        loop = _loop(store, dec, wm=wm, um=um, bus=bus)
        with _patch_speak() as spoken:
            d = asyncio.run(loop.tick())
        assert d.action == AmbientAction.SPEAK
        assert spoken == [("要帮忙吗？", "ambient")]
        # 工作记忆恒写
        assert wm.adds and wm.adds[0]["role"] == "ambient"
        # salient → 终身记忆写
        assert um.remembered and "ambient" in (um.remembered[0]["tags"] or [])
        # 感知摘要是**屏幕/麦克风看到的世界**,不是用户对我们说的话。
        # 而且环境回路不在对话轮次里跑,不能靠 context_provenance 的全局回执 ——
        # 那样会捡到上一轮聊天的来源,把一条感知记忆标成用户说的。
        assert um.remembered[0]["origin"] == "external"
        # 事件发布 observed + decision
        types = [e["type"] for e in bus.events]
        assert "ambient.observed" in types and "ambient.decision" in types

    def test_silent_does_not_speak_but_records(self):
        store = FakeStore({"camera_b64": _BLACK})
        wm, um = FakeWM(), FakeUM()
        dec = FakeDecider(AmbientDecision(AmbientAction.SILENT, rationale="正常打字"))
        loop = _loop(store, dec, wm=wm, um=um)
        with _patch_speak() as spoken:
            d = asyncio.run(loop.tick())
        assert d.action == AmbientAction.SILENT
        assert spoken == []  # 沉默不出声
        assert wm.adds  # 但工作记忆仍记录
        assert um.remembered == []  # 非 salient → 不进终身记忆

    def test_delegate_routes_through_handle_request(self):
        store = FakeStore({"camera_b64": _BLACK})
        dec = FakeDecider(
            AmbientDecision(AmbientAction.DELEGATE, rationale="反复报错", task="查错误日志", salient=True)
        )
        loop = _loop(store, dec)

        calls = {}

        class FakeRuntime:
            async def handle_request(self, *, message, source, **kw):
                calls["message"] = message
                calls["source"] = source
                calls["mm"] = kw.get("multimodal_context")
                return {"success": True, "response": "在查了"}

        with patch("core.desktop_presence_runtime.get_desktop_presence_runtime", return_value=FakeRuntime()):
            d = asyncio.run(loop.tick())
        assert d.action == AmbientAction.DELEGATE
        assert calls["message"] == "查错误日志"
        assert calls["source"] == "ambient"  # 走正门,来源标记 ambient
        assert calls["mm"] is not None  # 携带当前帧

    def test_non_salient_skips_longterm_memory(self):
        store = FakeStore({"camera_b64": _BLACK})
        um = FakeUM()
        dec = FakeDecider(AmbientDecision(AmbientAction.SILENT, rationale="无事", salient=False))
        loop = _loop(store, dec, um=um)
        asyncio.run(loop.tick())
        assert um.remembered == []

    def test_disabled_longterm_memory_is_safe(self):
        store = FakeStore({"camera_b64": _BLACK})
        um = FakeUM(enabled=False)
        dec = FakeDecider(AmbientDecision(AmbientAction.SPEAK, utterance="hi", salient=True))
        loop = _loop(store, dec, um=um)
        with _patch_speak():
            asyncio.run(loop.tick())
        assert um.remembered == []  # enabled=False → 不写，也不报错

    def test_decider_exception_becomes_silent(self):
        store = FakeStore({"camera_b64": _BLACK})

        class BoomDecider:
            async def decide(self, obs):
                raise RuntimeError("boom")

        loop = _loop(store, BoomDecider())
        with _patch_speak() as spoken:
            d = asyncio.run(loop.tick())
        assert d.action == AmbientAction.SILENT  # 决策异常 → 保守沉默
        assert spoken == []


# ── 决策脑:多模态消息构造 ──────────────────────────────────────────────────────
class TestLLMRouterDecider:
    def test_builds_multimodal_message_with_image_part(self):
        d = LLMRouterDecider()
        obs = AmbientObservation(frame_b64=_BLACK, frame_mime="image/jpeg", recent_memory=["[silent] 之前"])
        msgs = d._build_messages(obs)
        content = msgs[0]["content"]
        assert isinstance(content, list)
        kinds = [p["type"] for p in content]
        assert "text" in kinds and "image_url" in kinds
        img = next(p for p in content if p["type"] == "image_url")
        assert img["image_url"]["url"].startswith("data:image/jpeg;base64,")

    def test_text_only_when_no_frame(self):
        d = LLMRouterDecider()
        msgs = d._build_messages(AmbientObservation(frame_b64=None))
        assert isinstance(msgs[0]["content"], str)

    def test_decide_parses_router_response(self):
        class FakeResp:
            content = "SPEAK\n用户回来了\n说：欢迎回来"

        class FakeRouter:
            async def chat(self, messages, temperature=0.2, max_tokens=200, **kw):
                return FakeResp()

        d = LLMRouterDecider(router=FakeRouter())
        out = asyncio.run(d.decide(AmbientObservation(frame_b64=_BLACK)))
        assert out.action == AmbientAction.SPEAK
        assert out.utterance == "欢迎回来"

    def test_decide_falls_back_to_text_on_multimodal_error(self):
        class FakeResp:
            content = "SILENT\n无事发生"

        class FlakyRouter:
            def __init__(self):
                self.n = 0

            async def chat(self, messages, **kw):
                self.n += 1
                # 第一次(多模态)抛错，第二次(纯文本降级)成功
                if self.n == 1 and isinstance(messages[0]["content"], list):
                    raise RuntimeError("vision not supported")
                return FakeResp()

        r = FlakyRouter()
        d = LLMRouterDecider(router=r)
        out = asyncio.run(d.decide(AmbientObservation(frame_b64=_BLACK)))
        assert out.action == AmbientAction.SILENT
        assert r.n == 2  # 确实降级重试了
