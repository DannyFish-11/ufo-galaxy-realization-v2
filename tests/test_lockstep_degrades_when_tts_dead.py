"""tests/test_lockstep_degrades_when_tts_dead.py
==================================================
桌面对话"文字又一大段往外蹦、没锁字符"的回归防护(有界锁步)。

根因:锁步(GALAXY_TEXT_VOICE_LOCKSTEP,三态开关,默认 auto=本次走 TTS 即锁步)把
"可见文字"押在"TTS 真的念出某句"上(chat.py 只在句子被 on_sentence_start 回调后
才让该句文字上屏)。可 TTS 运行期常静默失败
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


# ===========================================================================
# 三态开关(auto)与平滑露出 —— 见 core/routes/chat.py 锁步段
# ===========================================================================


class _LiveSpeaker:
    """TTS 正常:feed 到句末即回调 on_sentence_start(模拟真的开口念)。"""

    def __init__(self, on_sentence_start=None, **_kw):
        self.on_sentence_start = on_sentence_start
        self._player_task = None
        self.buf = ""
        self.fed = []

    def feed(self, t):
        self.fed.append(t)
        self.buf += t
        while True:
            idx = max(self.buf.find(p) for p in ("。", "，", ",", "!"))
            if idx < 0:
                break
            sent, self.buf = self.buf[: idx + 1], self.buf[idx + 1 :]
            if self.on_sentence_start:
                self.on_sentence_start(sent)

    def reset(self):
        self.buf = ""

    def finish(self):
        if self.buf and self.on_sentence_start:
            self.on_sentence_start(self.buf)
            self.buf = ""


def test_auto_mode_locksteps_when_response_uses_tts(monkeypatch):
    """未设开关(auto)+ 本次走 TTS → 必须锁步:文字随语音露出,不是一上来就逐字直出。

    判据用外部可观察结果:锁步下首个 delta 只可能在 speaker 回调之后出现,
    因此流出的文字必须【落在已被念出的句子范围内】,而不是原始 token 序列。
    """
    monkeypatch.delenv("GALAXY_TEXT_VOICE_LOCKSTEP", raising=False)  # auto
    monkeypatch.setenv("GALAXY_LOCKSTEP_GRACE_S", "5")  # 不让它降级
    monkeypatch.setenv("GALAXY_LOCKSTEP_STALL_S", "30")
    monkeypatch.setenv("GALAXY_CHAT_TIMEOUT_S", "20")

    spoken = []

    def _factory(**kw):
        sp = _LiveSpeaker(**kw)
        orig = sp.on_sentence_start

        def _tap(t):
            spoken.append(t)
            if orig:
                orig(t)

        sp.on_sentence_start = _tap
        return sp

    tokens = ["你好", "呀,", "今天", "天气", "不错", "。"]
    frames, full = _run_stream(monkeypatch, _factory, tokens)

    assert spoken, "TTS 正常时应有句子被念出"
    deltas = [f.get("text", "") for f in frames if f.get("type") == "delta"]
    assert "".join(deltas) == full, f"锁步下全文仍须完整流出; got {deltas!r} vs {full!r}"
    # auto 生效的判别式:非锁步时 delta 恒等于原始 token 序列(见 forced_off 用例断言),
    # 锁步时文字来自"被念出的句子"经节奏切分,必然不等于 token 序列。
    assert deltas != tokens, f"未设开关却走了直出路径 —— auto 未生效; got {deltas!r}"


def test_forced_off_disables_lockstep_even_with_tts(monkeypatch):
    """显式 off → 即使走 TTS 也不锁步:文字逐字直出(delta 数应与 token 数一致)。"""
    monkeypatch.setenv("GALAXY_TEXT_VOICE_LOCKSTEP", "off")
    monkeypatch.setenv("GALAXY_CHAT_TIMEOUT_S", "20")

    tokens = ["你好", "呀,", "今天", "天气", "不错", "。"]
    frames, full = _run_stream(monkeypatch, lambda **k: _LiveSpeaker(**k), tokens)

    deltas = [f.get("text", "") for f in frames if f.get("type") == "delta"]
    assert "".join(deltas) == full
    assert deltas == tokens, f"强制关闭时应逐 token 直出,未经锁步归一; got {deltas}"


def test_lockstep_reveal_is_smooth_not_whole_sentence_dumps(monkeypatch):
    """平滑露出:锁步下的 delta 不得是"整句砸屏"(真机抱怨的一句一句蹦)。

    判据:被念出的句子远长于单个 delta —— 即一句话被拆成多个 delta 逐步流出。
    """
    monkeypatch.delenv("GALAXY_TEXT_VOICE_LOCKSTEP", raising=False)
    monkeypatch.setenv("GALAXY_LOCKSTEP_GRACE_S", "5")
    monkeypatch.setenv("GALAXY_LOCKSTEP_STALL_S", "30")
    monkeypatch.setenv("GALAXY_LOCKSTEP_CPS", "8")  # 慢速,便于观察拆分
    monkeypatch.setenv("GALAXY_LOCKSTEP_DRAIN_S", "3.0")
    monkeypatch.setenv("GALAXY_CHAT_TIMEOUT_S", "20")

    # 一整句长文本:锁步时它会被一次性放进待吐区,平滑露出应把它拆成多段。
    tokens = ["这是一段很长的话用来验证平滑露出是否真的把整句拆成了多个小段流出。"]
    frames, full = _run_stream(monkeypatch, lambda **k: _LiveSpeaker(**k), tokens)

    deltas = [f.get("text", "") for f in frames if f.get("type") == "delta"]
    assert "".join(deltas) == full, f"平滑露出不得吞字; got {deltas}"
    assert len(deltas) >= 5, f"整句应被切成多段平滑流出,而不是一次性砸屏; got {len(deltas)} 段 {deltas}"
    assert max(len(d) for d in deltas) < len(full) // 2, f"存在一次吐掉半句以上的砸屏段; got {deltas}"


# ══════════════════════════════════════════════════════════════════════════
# lockstep 帧 —— 把「声音与文字脱钩」这件事变成前端看得见的
#
# 上面那两条钉的是**行为**:降级之后文字得逐字流出。但降级这件事本身此前
# **对前端是隐形的** —— SSE 只有 phase/delta/reset/meta/done/error 六种帧,
# 没有一帧说"锁步没了"。于是用户看到的是节奏突然变了,不知道为什么,也不知道
# 此刻声音和文字已经不同步。
#
# 本仓的规矩是降级必须留痕。下面这组钉的就是那道痕。
# ══════════════════════════════════════════════════════════════════════════


def _lockstep_frames(frames):
    return [f for f in frames if f.get("type") == "lockstep"]


class _LiveSpeakerForFrames:
    """凑满一句就"开口念" —— 与上面 _LiveSpeaker 同构,独立一份免相互牵动。"""

    def __init__(self, on_sentence_start):
        self._cb = on_sentence_start
        self._buf = ""
        self.chunks_spoken = 0
        self._player_task = None

    def feed(self, t):
        self._buf += t
        while True:
            hit = -1
            for ch in "。!?！?;;\n":
                i = self._buf.find(ch)
                if i >= 0 and (hit < 0 or i < hit):
                    hit = i
            if hit < 0:
                break
            sent, self._buf = self._buf[: hit + 1], self._buf[hit + 1 :]
            self.chunks_spoken += 1
            if self._cb:
                self._cb(sent)

    def reset(self):
        self._buf = ""

    def finish(self):
        if self._buf.strip() and self._cb:
            self.chunks_spoken += 1
            self._cb(self._buf)
        self._buf = ""


def test_engaged_frame_comes_before_any_text(monkeypatch):
    """锁步生效时必须开场就说 —— 面板那条「正在说」指示灯据此点亮。

    它必须早于第一个 delta:晚于文字的话,第一句上屏时前端还不知道该不该点灯,
    只能靠"文字来得快不快"去猜,而那恰恰是猜不准的。
    """
    monkeypatch.setenv("GALAXY_TEXT_VOICE_LOCKSTEP", "1")
    monkeypatch.setenv("GALAXY_LOCKSTEP_GRACE_S", "5.0")
    monkeypatch.setenv("GALAXY_CHAT_TIMEOUT_S", "10")

    frames, _ = _run_stream(
        monkeypatch,
        lambda on_sentence_start=None, **k: _LiveSpeakerForFrames(on_sentence_start),
        ["你好", "呀。", "今天", "不错", "。"],
    )
    ls = _lockstep_frames(frames)
    assert ls, "锁步生效却一帧都没发 —— 前端无从知道该不该点灯"
    assert ls[0]["state"] == "engaged"

    types = [f.get("type") for f in frames]
    assert "delta" in types, f"应该有文字流出; got {types}"
    assert types.index("lockstep") < types.index("delta"), f"状态帧必须早于第一个 delta; got {types}"


def test_degraded_frame_precedes_the_catchup_burst(monkeypatch):
    """TTS 死 → 必须先报 degraded,**再**补吐那一大段。

    顺序是这条测试的全部意义:反过来的话,前端会把紧跟着涌来的一大段补吐
    当成正常的逐句露出,于是"声音已经跟不上了"这个事实被那一段文字盖过去。
    """
    monkeypatch.setenv("GALAXY_TEXT_VOICE_LOCKSTEP", "1")
    monkeypatch.setenv("GALAXY_LOCKSTEP_GRACE_S", "0.15")
    monkeypatch.setenv("GALAXY_CHAT_TIMEOUT_S", "10")

    class _DeadSpeaker:
        def __init__(self):
            self.chunks_spoken = 0
            self._player_task = None

        def feed(self, t):
            pass

        def reset(self):
            pass

        def finish(self):
            pass

    frames, full = _run_stream(monkeypatch, lambda **k: _DeadSpeaker(), ["你好", "呀,", "今天", "天气", "不错", "。"])

    ls = _lockstep_frames(frames)
    states = [f["state"] for f in ls]
    assert states[0] == "engaged", f"开场应报 engaged; got {states}"
    assert "degraded" in states, f"TTS 死了却没报降级 —— 那道痕没留下; got {states}"

    deg = next(f for f in ls if f["state"] == "degraded")
    assert deg.get("reason") == "no_first_sentence"

    seq = [f.get("type") for f in frames]
    deg_i = [i for i, f in enumerate(frames) if f.get("type") == "lockstep" and f.get("state") == "degraded"][0]
    first_delta_i = seq.index("delta")
    assert deg_i < first_delta_i, f"降级帧必须早于补吐的那一段文字; got {seq}"


def test_degraded_reason_distinguishes_midstall_from_no_first_sentence(monkeypatch):
    """两种降级原因要分开 —— 「一句都没念出来」和「念了一半卡住」要人做的事不同。"""
    monkeypatch.setenv("GALAXY_TEXT_VOICE_LOCKSTEP", "1")
    monkeypatch.setenv("GALAXY_LOCKSTEP_GRACE_S", "5.0")  # 首句宽限设大 → 只能走中途卡住
    monkeypatch.setenv("GALAXY_LOCKSTEP_STALL_S", "0.15")
    monkeypatch.setenv("GALAXY_CHAT_TIMEOUT_S", "10")

    class _StallAfterFirst:
        """念完第一句就再也不开口。"""

        def __init__(self, on_sentence_start):
            self._cb = on_sentence_start
            self._buf = ""
            self.chunks_spoken = 0
            self._player_task = None

        def feed(self, t):
            self._buf += t
            if self.chunks_spoken == 0 and "。" in self._buf:
                i = self._buf.index("。")
                sent, self._buf = self._buf[: i + 1], self._buf[i + 1 :]
                self.chunks_spoken = 1
                if self._cb:
                    self._cb(sent)

        def reset(self):
            self._buf = ""

        def finish(self):
            pass

    frames, _ = _run_stream(
        monkeypatch,
        lambda on_sentence_start=None, **k: _StallAfterFirst(on_sentence_start),
        # 尾巴要够长:中途卡住的判据是「喂进去但没露出的 > 8 字」,
        # 尾巴刚好 8 字的话严格大于不成立,降级永不触发(第一版就栽在这)。
        ["第一句。", "第二句", "较长", "内容", "还有", "第三句", "结尾。"],
    )
    deg = [f for f in _lockstep_frames(frames) if f["state"] == "degraded"]
    assert deg, "中途卡住却没报降级"
    assert deg[0].get("reason") == "mid_stall", f"应报 mid_stall 而不是 {deg[0].get('reason')!r}"


def test_off_when_there_is_no_tts_at_all(monkeypatch):
    """纯文字轮次要明确报 off,而不是什么都不发。

    三态而不是两态的理由就在这:「本轮没有同步这回事」与「曾经同步、现在掉了」
    是两件事。只发 engaged/degraded 的话,前端分不出「还没收到帧」和「不适用」。
    """
    monkeypatch.setenv("GALAXY_CHAT_TIMEOUT_S", "10")
    monkeypatch.delenv("GALAXY_TEXT_VOICE_LOCKSTEP", raising=False)

    frames, _ = _run_stream(monkeypatch, lambda **k: None, ["纯", "文字", "。"])
    ls = _lockstep_frames(frames)
    assert ls and ls[0]["state"] == "off", f"没有 TTS 时应报 off; got {[f.get('state') for f in ls]}"
    assert ls[0].get("reason") == "no_speaker"


def test_off_when_lockstep_is_switched_off_by_config(monkeypatch):
    """有 TTS 但人把锁步关了 —— 与「根本没有 TTS」分成两个原因,排查时不用猜。"""
    monkeypatch.setenv("GALAXY_TEXT_VOICE_LOCKSTEP", "0")
    monkeypatch.setenv("GALAXY_CHAT_TIMEOUT_S", "10")

    frames, _ = _run_stream(
        monkeypatch,
        lambda on_sentence_start=None, **k: _LiveSpeakerForFrames(on_sentence_start),
        ["关掉了", "锁步", "。"],
    )
    ls = _lockstep_frames(frames)
    assert ls and ls[0]["state"] == "off"
    assert ls[0].get("reason") == "disabled_by_config"


def test_every_emitted_value_is_in_the_declared_vocabulary(monkeypatch):
    """发出去的 state/reason 必须都在常量表里。

    这一条防的是手写字符串漂:哪天有人在 chat.py 里直接写个 "stalled",
    前端那边的联合类型不认识,而它不会报任何错 —— 只是那条指示灯从此不动了。
    """
    import core.routes.chat as chat_mod

    monkeypatch.setenv("GALAXY_TEXT_VOICE_LOCKSTEP", "1")
    monkeypatch.setenv("GALAXY_LOCKSTEP_GRACE_S", "0.15")
    monkeypatch.setenv("GALAXY_CHAT_TIMEOUT_S", "10")

    class _DeadSpeaker:
        def __init__(self):
            self.chunks_spoken = 0
            self._player_task = None

        def feed(self, t):
            pass

        def reset(self):
            pass

        def finish(self):
            pass

    frames, _ = _run_stream(monkeypatch, lambda **k: _DeadSpeaker(), ["会", "降级", "。"])
    for f in _lockstep_frames(frames):
        assert f["state"] in chat_mod.LOCKSTEP_STATES, f"未登记的 state: {f['state']!r}"
        if "reason" in f:
            assert f["reason"] in chat_mod.LOCKSTEP_REASONS, f"未登记的 reason: {f['reason']!r}"


class TestTheSilentPathAlsoLeavesATrace:
    """**一句都没念出来时,收尾那条路也必须留痕并把文字吐出去。**

    锁步有两条路:循环里那条(runtime 逐个吐 delta)和收尾那条(非流式适配器,
    整段一次返回)。前者遇到「首句宽限内一句都没念出来」会发 degraded;后者从前
    **什么都不发** —— 它靠一句注释把责任推给客户端:「done 的 response=全文 会把
    气泡快照到权威全文」。

    那是一条**没写进契约的要求**。SSE 文档里 delta 才是文字通道,只累加 delta 的
    客户端因此拿到一个空气泡 —— 而空气泡跟「它想了想没什么好说的」长得一模一样。
    实测撞到过:这台机器没有可用发声器,面板画了个空气泡。

    同一条规则两条路给出不同行为,是这个仓库最常栽的那种不一致。
    """

    def test_the_tail_path_emits_degraded_and_the_text(self):
        """收尾那条路的源码里必须同时有「报降级」和「把 text 吐出去」。"""
        import re
        from pathlib import Path as _P

        src = _P(__file__).resolve().parent.parent / "core/routes/chat.py"
        code = src.read_text(encoding="utf-8")
        # 只看收尾那一段:从「锁步收尾(TTS 正常)」到下一个 elif 分支
        start = code.index("锁步收尾(TTS 正常)")
        end = code.index("elif _lockstep and _ls_degraded", start)
        tail = code[start:end]
        assert re.search(
            r"revealed_chars == 0 and text", tail
        ), "收尾那条路没有「一个字都没露出来」这个判断 —— 那种情况会静默丢掉整轮答复"
        assert '"state": "degraded"' in tail, "一句都没念出来却不报 degraded —— 降级没有留痕"
        assert '"reason": "no_first_sentence"' in tail, "报了降级却不说为什么"
        assert re.search(
            r'"type": "delta", "text": text', tail
        ), "报了降级却没把权威全文吐出去 —— 只认 delta 的客户端还是拿到空气泡"

    def test_both_paths_use_the_same_reason_word(self):
        """两条路对同一件事必须用同一个词,否则排查时对不上。"""
        from core.routes.chat import LOCKSTEP_REASONS

        assert "no_first_sentence" in LOCKSTEP_REASONS
