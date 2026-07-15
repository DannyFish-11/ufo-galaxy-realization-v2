"""tests/test_lockstep_degrades_when_tts_dead.py
==================================================
桌面对话"文字又一大段往外蹦、没锁字符"的回归防护(有界锁步)。

根因:锁步(GALAXY_TEXT_VOICE_LOCKSTEP,默认开)把"可见文字"押在"TTS 真的念出某句"上
(chat.py 只在句子被 on_sentence_start 回调时才逐句上屏)。可 TTS 运行期常静默失败
(edge 云端不可达/无音频设备)→ 一句都不会念 → 一字不上屏 → 整段憋到 done 帧一次性冒出。

修复:有界锁步——喂给 TTS 但尚未露出的 delta 缓起来,若首 delta 起 GALAXY_LOCKSTEP_GRACE_S
秒内【一句都没开口念】(revealed_chars==0),判 TTS 没在播 → 把缓存补吐、其后 delta 逐字
直出。本测试锁死:(1) TTS 死 → 文字仍在 done 之前逐字流出;(2) TTS 正常 → 仍逐句同步露出、
不误降级。
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _collect_frames(resp_iter):
    frames = []
    for line in resp_iter:
        if line and line.startswith("data: "):
            frames.append(json.loads(line[6:]))
    return frames


def _passthrough_boundary(result, metadata, is_operator_request):
    # 隔离 hidden/visible 流水线:foreground_response 直接取 response。
    return metadata, None, result.get("response", ""), False


def _run_stream(monkeypatch, speaker_factory, tokens):
    import core.desktop_presence_runtime as dpr
    import core.routes.chat as chat_mod
    import core.speech_output as so
    from core.llm_stream import current_stream

    full = "".join(tokens)

    class _Runtime:
        async def handle_request(self, *a, **k):
            s = current_stream()
            for tok in tokens:
                if s is not None:
                    s.feed(tok)
                await asyncio.sleep(0.05)  # 让消费循环有机会跑 + 越过 grace
            return {
                "success": True,
                "response": full,
                "metadata": {"model": "m", "session_id": k.get("session_id", "")},
                "intent": "chat",
                "runtime_session_id": "r1",
            }

    app = FastAPI()
    app.include_router(chat_mod.create_router(service_manager=None, config=None))
    client = TestClient(app)

    monkeypatch.setattr(so, "begin_incremental_speech", speaker_factory)
    monkeypatch.setattr(so, "suppress_final_speak_in_context", lambda *a, **k: None)
    monkeypatch.setattr(chat_mod, "_apply_hidden_visible_boundary", _passthrough_boundary)

    with patch.object(dpr, "get_desktop_presence_runtime", lambda: _Runtime()):
        with client.stream("POST", "/api/v1/chat/stream", json={"message": "hi", "session_id": "deg"}) as r:
            frames = _collect_frames(r.iter_lines())
    return frames, full


def test_lockstep_degrades_to_streaming_when_tts_dead(monkeypatch):
    """TTS 死(synth 永失败,一句未念)→ 文字必须在 done 之前逐字流出,而非全憋到 done。"""
    monkeypatch.setenv("GALAXY_TEXT_VOICE_LOCKSTEP", "1")
    monkeypatch.setenv("GALAXY_LOCKSTEP_GRACE_S", "0.15")  # 快速降级
    monkeypatch.setenv("GALAXY_CHAT_TIMEOUT_S", "10")

    class _DeadSpeaker:
        # TTS 死:on_sentence_start 从不回调,chunks_spoken 恒 0。
        def __init__(self):
            self.chunks_spoken = 0
            self._player_task = None
            self.fed = []

        def feed(self, t):
            self.fed.append(t)

        def reset(self):
            pass

        def finish(self):
            pass

    tokens = ["你好", "呀,", "今天", "天气", "不错", "。"]
    frames, full = _run_stream(monkeypatch, lambda **k: _DeadSpeaker(), tokens)

    types = [f.get("type") for f in frames]
    deltas = [f for f in frames if f.get("type") == "delta"]
    assert deltas, f"降级后应有 delta 帧在流中流出(不能全憋到 done); got {types}"
    # delta 必须出现在 done 之前 —— 证明是"边生成边上屏",不是收尾一次性快照。
    assert "done" in types, f"应有 done 帧; got {types}"
    assert types.index("delta") < types.index("done"), f"delta 必须早于 done; got {types}"
    streamed = "".join(d.get("text", "") for d in deltas)
    assert streamed == full, f"逐字流出的文字应覆盖全文; got {streamed!r} vs {full!r}"
    done = next(f for f in frames if f.get("type") == "done")
    assert done.get("response") == full


def test_lockstep_degrades_on_midstream_stall(monkeypatch):
    """TTS 念了第一句后【中途卡住】(不再开口)→ 不能挂到收尾再一次性冒出;
    应在 stall 宽限后 reset 前端文字并把全文逐字直出(语音继续尾随)。"""
    monkeypatch.setenv("GALAXY_TEXT_VOICE_LOCKSTEP", "1")
    monkeypatch.setenv("GALAXY_LOCKSTEP_GRACE_S", "5.0")  # 首句宽限设大,确保走的是"中途卡住"分支
    monkeypatch.setenv("GALAXY_LOCKSTEP_STALL_S", "0.15")
    monkeypatch.setenv("GALAXY_CHAT_TIMEOUT_S", "10")

    class _StallSpeaker:
        # 只在第一句开口回调一次,其后永远卡住(不再 reveal),chunks_spoken 停在 1。
        def __init__(self, on_sentence_start):
            self._cb = on_sentence_start
            self._buf = ""
            self._revealed_once = False
            self.chunks_spoken = 0
            self._player_task = None

        def feed(self, t):
            self._buf += t
            if not self._revealed_once and self._buf and self._buf[-1] in "。!?！?.":
                self._revealed_once = True
                sent = self._buf
                self._buf = ""
                self.chunks_spoken = 1
                if self._cb is not None:
                    self._cb(sent)

        def reset(self):
            self._buf = ""

        def finish(self):
            pass

    tokens = ["你好呀。", "第二句", "较长", "内容", "还有", "第三句", "结尾。"]
    frames, full = _run_stream(
        monkeypatch,
        lambda on_sentence_start=None, **k: _StallSpeaker(on_sentence_start),
        tokens,
    )

    types = [f.get("type") for f in frames]
    assert "done" in types
    # 中途卡住应触发一次 reset(清掉已露出的第一句),随后把全文逐字直出。
    assert "reset" in types, f"中途卡住应 reset 前端文字再全量重放; got {types}"
    # reset 之后拼起来的文字 == 权威全文(无重复、无丢失)。
    last_reset = len(types) - 1 - types[::-1].index("reset")
    after_reset = "".join(f.get("text", "") for f in frames[last_reset + 1 :] if f.get("type") == "delta")
    assert after_reset == full, f"reset 后重放的文字应等于全文; got {after_reset!r} vs {full!r}"
    # delta 必须早于 done(不是憋到收尾)。
    assert types.index("delta") < types.index("done")


def test_lockstep_stays_synced_when_tts_alive(monkeypatch):
    """TTS 正常(每凑满一句即"开口")→ 仍逐句同步露出,不误触降级。"""
    monkeypatch.setenv("GALAXY_TEXT_VOICE_LOCKSTEP", "1")
    monkeypatch.setenv("GALAXY_LOCKSTEP_GRACE_S", "2.0")
    monkeypatch.setenv("GALAXY_CHAT_TIMEOUT_S", "10")

    class _LiveSpeaker:
        # TTS 正常:凑满一句(以 。!?结尾)立刻"开口"→ 回调 on_sentence_start + chunks_spoken++。
        def __init__(self, on_sentence_start):
            self._cb = on_sentence_start
            self._buf = ""
            self.chunks_spoken = 0
            self._player_task = None

        def feed(self, t):
            self._buf += t
            if self._buf and self._buf[-1] in "。!?！?.":
                sent = self._buf
                self._buf = ""
                self.chunks_spoken += 1
                if self._cb is not None:
                    self._cb(sent)

        def reset(self):
            self._buf = ""

        def finish(self):
            if self._buf and self._cb is not None:
                self.chunks_spoken += 1
                self._cb(self._buf)
                self._buf = ""

    tokens = ["你好呀。", "今天", "天气", "不错!", "走", "吧?"]
    frames, full = _run_stream(
        monkeypatch,
        lambda on_sentence_start=None, **k: _LiveSpeaker(on_sentence_start),
        tokens,
    )

    types = [f.get("type") for f in frames]
    deltas = [f for f in frames if f.get("type") == "delta"]
    assert deltas, f"锁步正常也应逐句露出 delta; got {types}"
    assert types.index("delta") < types.index("done"), "delta 必须早于 done"
    streamed = "".join(d.get("text", "") for d in deltas)
    assert streamed == full, f"逐句露出的文字应覆盖全文; got {streamed!r} vs {full!r}"
    # 同步露出应是【多帧逐句】,而不是降级后的一大块补吐:至少 3 句 → ≥3 个 delta 帧。
    assert len(deltas) >= 3, f"应逐句多帧露出(未误降级为一次性补吐); got {len(deltas)} 帧"
