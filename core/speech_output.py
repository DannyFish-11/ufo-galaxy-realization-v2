"""
core/speech_output.py — 集中式语音输出(TTS)
=============================================

让 AI 的回复**默认朗读出来**,且不分渠道:语音对话、面板打字、自发目标……只要 handle_request
产出回复,就在这里集中朗读一次。与"听"对称——"说"也默认启用。

- **默认开**;``GALAXY_SPEAK=0`` 关闭。
- **非阻塞**:后台任务朗读,不拖慢请求返回。
- **去重**:短窗口内同一句不重复念(避免多路径重复触发双声)。
- **集中**:语音回路(VoiceLoop)不再各自 TTS,统一走这里,避免一句念两遍。
- **优雅降级**:复用 EdgeTTSEngine;缺 edge-tts / 无音频设备时静默降级,绝不抛出。
- 过长截断(念太久没意义);``GALAXY_TTS_VOICE`` 选嗓音,``GALAXY_SPEAK_MAX_CHARS`` 调长度。
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import os
import time
from typing import Any, Optional

logger = logging.getLogger("Galaxy.SpeechOutput")

# 真流式请求上下文里已经有 IncrementalSpeaker 在边生成边念时,请求收尾处
# handle_request 的集中 speak_response 必须闭嘴,否则同一回答念两遍。
# 用 contextvars:只在建立了增量朗读会话的那条请求链路上抑制,语音回路/
# ambient/其它请求完全不受影响。
_suppress_final = contextvars.ContextVar("galaxy_suppress_final_speak", default=False)


def suppress_final_speak_in_context() -> None:
    """在当前请求上下文里抑制集中式 speak_response(增量朗读已接管)。"""
    _suppress_final.set(True)


def speak_enabled() -> bool:
    """默认朗读;GALAXY_SPEAK=0/false/no/off 关闭。"""
    return os.getenv("GALAXY_SPEAK", "1").strip().lower() not in ("0", "false", "no", "off")


_engine: Optional[Any] = None
_engine_failed = False
_last_text = ""
_last_ts = 0.0
_active_speaker: Optional[Any] = None  # 当前 StreamingSpeaker（供 barge-in 打断）
_runtime_warned = False  # 运行期合成/播放失败首次升 WARNING(此后降 debug 防刷屏)


def _log_speak_failure(kind: str, exc: BaseException) -> None:
    """朗读运行期失败:首次 WARNING(用户看得见"为什么不说话"),后续 debug。"""
    global _runtime_warned
    if not _runtime_warned:
        _runtime_warned = True
        logger.warning("%s失败(语音降级为静默;同类失败此后仅记 debug): %s", kind, exc)
    else:
        logger.debug("%s失败(降级): %s", kind, exc)


def _streaming_enabled() -> bool:
    """分句流式朗读默认开；GALAXY_TTS_STREAMING=0 回到整段批处理。"""
    return os.getenv("GALAXY_TTS_STREAMING", "1").strip().lower() not in ("0", "false", "no", "off")


def _max_chars() -> int:
    try:
        return max(80, int(os.getenv("GALAXY_SPEAK_MAX_CHARS", "600") or 600))
    except (ValueError, TypeError):
        return 600


def _get_engine() -> Optional[Any]:
    global _engine, _engine_failed
    if _engine is not None or _engine_failed:
        return _engine
    # 引擎选择:GALAXY_TTS_ENGINE = edge(默认,联网·音质好) | melo(离线·中英混读自然) |
    # piper(离线·纯 CPU·最轻) | auto(优先 edge,无网退 melo 再退 piper)。
    # A 档无卡断网:melo 音质更好,piper 更轻;二者都完全离线。
    choice = os.getenv("GALAXY_TTS_ENGINE", "edge").strip().lower()

    def _try_piper():
        try:
            from core.tts.piper_engine import PiperTTSEngine
            eng = PiperTTSEngine()
            return eng if eng.available() else None
        except Exception as exc:  # noqa: BLE001
            logger.info("Piper TTS 不可用: %s", exc)
            return None

    def _try_melo():
        try:
            from core.tts.melo_engine import MeloTTSEngine
            eng = MeloTTSEngine()
            return eng if eng.available() else None
        except Exception as exc:  # noqa: BLE001
            logger.info("Melo TTS 不可用: %s", exc)
            return None

    def _try_edge():
        try:
            # EdgeTTSEngine 构造器不校验依赖(edge_tts 懒导入在 synthesize 里),
            # 缺包时构造照样"成功"→ 选择器误以为引擎可用,既不落到 melo/piper,
            # 也不触发下面的"TTS 引擎不可用"告警,最终每次合成静默失败——
            # 真机表现就是"字出来了、一句话都不说"。故在这里先验一次导入。
            import edge_tts  # noqa: F401
            from core.tts import EdgeTTSEngine
            voice = os.getenv("GALAXY_TTS_VOICE", "zh-CN-XiaoxiaoNeural")
            return EdgeTTSEngine(voice=voice)
        except Exception as exc:  # noqa: BLE001
            logger.info("Edge TTS 不可用: %s", exc)
            return None

    if choice == "melo":
        _engine = _try_melo() or _try_piper() or _try_edge()
    elif choice == "piper":
        _engine = _try_piper() or _try_melo() or _try_edge()
    elif choice == "auto":
        _engine = _try_edge() or _try_melo() or _try_piper()
    else:  # edge(默认)
        _engine = _try_edge()

    if _engine is None:
        logger.warning("TTS 引擎不可用(语音输出降级;装 edge-tts / melotts / piper-tts 可启用)")
        _engine_failed = True
    return _engine


def speak_response(text: str, *, source: str = "") -> None:
    """默认朗读一段回复。非阻塞、去重、降级安全;永不抛出影响主流程。

    Args:
        text: 要朗读的回复文本。
        source: 请求来源("voice"/"chat"/"openclawd"/"e2e"…);自动化测试(e2e)不发声。
    """
    global _last_text, _last_ts
    if not speak_enabled():
        return
    if _suppress_final.get():  # 本请求已由增量朗读(边生成边念)接管,不再整段重念
        return
    text = (text or "").strip()
    if not text:
        return
    if source in ("e2e", "test"):  # 自动化/测试路径不发声
        return
    # 去重:3 秒内同一句不重复念(多渠道可能重复触发)。
    now = time.monotonic()
    if text == _last_text and (now - _last_ts) < 3.0:
        return
    _last_text, _last_ts = text, now

    spoken = text[: _max_chars()]
    engine = _get_engine()
    if engine is None:
        return

    async def _run() -> None:
        # 播放前后把"正在朗读"同步到桌面三态覆盖层(u_speaking)——此前 TTS 播放
        # 与覆盖层完全脱节：_speaking 只在相位事件里被动带一手且 MANIFEST 一进入
        # 就被强制置 False，而实际播放发生在那之后，覆盖层永远等不到真实信号，
        # 三态动画不随"AI 说话"运转。finally 确保异常/提前返回也一定复位。
        try:
            from core.lumiv_websocket_bridge import set_ai_speaking as _set_speaking
        except Exception:
            _set_speaking = None  # type: ignore
        global _active_speaker
        if _streaming_enabled():
            # 分句流式：第一句就绪即开口，感知延迟 ≈ 第一句合成时长；可被打断。
            from core.streaming_speech import StreamingSpeaker

            async def _synth(chunk: str) -> str:
                return await engine.synthesize(chunk)

            async def _play(path: str) -> None:
                await engine._play_audio(path)
                _rm(path)

            async def _stop() -> None:
                await engine.stop()

            def _rm(path: str) -> None:
                try:
                    os.remove(path)
                except OSError:
                    pass

            # discard:被打断时清理已合成但没播的临时 mp3,避免每次 barge-in 泄漏文件。
            speaker = StreamingSpeaker(
                _synth, _play, stop=_stop, on_speaking=_set_speaking, discard=_rm,
            )
            _active_speaker = speaker
            try:
                await speaker.speak(spoken)
                # StreamingSpeaker 对每句的合成/播放失败都内部吞掉(debug)后跳过,
                # 缺 edge-tts / 无音频设备时 speak() 会"成功"返回但一句没播——
                # 从外面看就是彻底静默。这里兜底:整段零句播出且不是被打断,升告警。
                if speaker.chunks_spoken == 0 and not getattr(speaker, "_interrupted", False):
                    _log_speak_failure(
                        "流式语音输出",
                        RuntimeError(
                            "整段一句都未播出——每句合成/播放均失败。"
                            "常见原因:未安装 edge-tts(pip install edge-tts)、"
                            "无法访问微软 TTS 服务、或无音频设备"
                        ),
                    )
            except Exception as exc:  # noqa: BLE001
                _log_speak_failure("流式语音输出", exc)
            finally:
                if _active_speaker is speaker:
                    _active_speaker = None
            return

        # 回退：整段批处理（GALAXY_TTS_STREAMING=0）。
        if _set_speaking is not None:
            _set_speaking(True)
        try:
            await engine.synthesize_and_play(spoken)
        except Exception as exc:  # noqa: BLE001
            _log_speak_failure("语音输出", exc)
        finally:
            if _set_speaking is not None:
                _set_speaking(False)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_run())  # 非阻塞:后台朗读
    except RuntimeError:
        # 无运行中的事件循环:同步兜底(尽量不长阻塞)。
        try:
            asyncio.run(_run())
        except Exception:  # noqa: BLE001
            pass


def begin_incremental_speech(*, source: str = "") -> Optional[Any]:
    """建立【边生成边念】会话(真流式 TTS)。

    供流式消费端(/chat/stream)在 token 开始流出前调用:拿到会话后把每段增量
    feed() 进来,凑满一句立即合成播放;级联换档/failover/工具轮时 reset();
    生成结束 finish()。返回 None 表示不可用(朗读关闭/引擎缺失/测试来源/无事件
    循环),调用方直接跳过即可——一切行为退回"生成完再念"的旧路径。

    会话建立成功后,调用方【必须】随后在同一请求上下文里执行
    :func:`suppress_final_speak_in_context`,否则 handle_request 收尾的集中
    speak_response 会把整段再念一遍。
    """
    if not speak_enabled() or source in ("e2e", "test"):
        return None
    if not _streaming_enabled():
        return None  # 用户显式选择整段批处理,尊重
    engine = _get_engine()
    if engine is None:
        return None
    try:
        from core.streaming_speech import IncrementalSpeaker
    except Exception as exc:  # noqa: BLE001
        logger.debug("IncrementalSpeaker 不可用(降级整段): %s", exc)
        return None
    try:
        from core.lumiv_websocket_bridge import set_ai_speaking as _set_speaking
    except Exception:  # noqa: BLE001
        _set_speaking = None  # type: ignore

    def _rm(path: str) -> None:
        try:
            os.remove(path)
        except OSError:
            pass

    async def _synth(chunk: str) -> str:
        return await engine.synthesize(chunk)

    async def _play(path: str) -> None:
        await engine._play_audio(path)
        _rm(path)

    async def _stop() -> None:
        await engine.stop()

    speaker = IncrementalSpeaker(
        _synth, _play, stop=_stop, on_speaking=_set_speaking, discard=_rm,
    )
    if not speaker.start():
        return None  # 无运行中事件循环(同步环境),降级整段
    global _active_speaker
    _active_speaker = speaker  # 供 barge-in(interrupt_speech)掐断

    def _clear_active(_task) -> None:
        global _active_speaker
        if _active_speaker is speaker:
            _active_speaker = None
    try:
        speaker._player_task.add_done_callback(_clear_active)
    except Exception:  # noqa: BLE001
        pass
    return speaker


def interrupt_speech() -> None:
    """barge-in：用户一开口就掐断 AI 正在进行的朗读。非阻塞、降级安全。

    语音回路在 VAD 检测到用户说话时调用此函数，实现"你一开口它就闭嘴"。
    """
    speaker = _active_speaker
    if speaker is None:
        return
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(speaker.interrupt())
    except RuntimeError:
        try:
            asyncio.run(speaker.interrupt())
        except Exception:  # noqa: BLE001
            pass


def is_speaking() -> bool:
    """AI 当前是否正在朗读（供 VAD/回路判断是否需要 barge-in）。"""
    speaker = _active_speaker
    return bool(speaker is not None and getattr(speaker, "speaking", False))
