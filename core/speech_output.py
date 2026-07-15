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
from typing import Any, Callable, Optional

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


# 运行期被证实失败的引擎类型(如 edge 合成时无法访问微软服务):拉黑后重选,
# 引擎链自动落到下一个。选择期看不出这类失败——构造/导入都成功,坏在合成那一刻。
_failed_engine_types: set = set()


def _get_engine() -> Optional[Any]:
    global _engine, _engine_failed
    if _engine is not None or _engine_failed:
        return _engine
    # 引擎选择:GALAXY_TTS_ENGINE = edge(默认,联网·音质好) | kokoro(离线·82M·
    # 纯 CPU 快于实时·中文) | melo(离线·中英混读自然) | piper(离线·最轻) |
    # sapi(Windows 自带·零依赖) | auto。每条链以 kokoro→sapi 收尾:
    # 无论装了什么、网络如何,最后总能出声,且优先高音质离线而非机器人音。
    choice = os.getenv("GALAXY_TTS_ENGINE", "edge").strip().lower()

    def _try_piper():
        if "PiperTTSEngine" in _failed_engine_types:
            return None
        try:
            from core.tts.piper_engine import PiperTTSEngine

            eng = PiperTTSEngine()
            return eng if eng.available() else None
        except Exception as exc:  # noqa: BLE001
            logger.info("Piper TTS 不可用: %s", exc)
            return None

    def _try_melo():
        if "MeloTTSEngine" in _failed_engine_types:
            return None
        try:
            from core.tts.melo_engine import MeloTTSEngine

            eng = MeloTTSEngine()
            return eng if eng.available() else None
        except Exception as exc:  # noqa: BLE001
            logger.info("Melo TTS 不可用: %s", exc)
            return None

    def _try_edge():
        if "EdgeTTSEngine" in _failed_engine_types:
            return None
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

    def _try_kokoro():
        if "KokoroTTSEngine" in _failed_engine_types:
            return None
        try:
            from core.tts.kokoro_engine import KokoroTTSEngine

            eng = KokoroTTSEngine()
            # available() 缺模型文件时自动踢后台拉取(拉完下次选择/重启即生效)
            return eng if eng.available() else None
        except Exception as exc:  # noqa: BLE001
            logger.info("Kokoro TTS 不可用: %s", exc)
            return None

    def _try_sapi():
        if "SapiTTSEngine" in _failed_engine_types:
            return None
        try:
            from core.tts.sapi_engine import SapiTTSEngine

            eng = SapiTTSEngine()
            return eng if eng.available() else None
        except Exception as exc:  # noqa: BLE001
            logger.info("SAPI TTS 不可用: %s", exc)
            return None

    def _try_indextts():
        if "IndexTTSEngine" in _failed_engine_types:
            return None
        try:
            from core.tts.indextts_engine import IndexTTSEngine

            eng = IndexTTSEngine()
            return eng if eng.available() else None
        except Exception as exc:  # noqa: BLE001
            logger.info("IndexTTS 不可用: %s", exc)
            return None

    if choice == "indextts":
        # 质量档(零样本克隆+情绪,自回归大模型):仅显式选择才启用,不进
        # 任何默认回退链——CPU 合成一句数秒到数十秒,拿它当日常对话嗓音会
        # 显著加重延迟。不可用/运行期失败仍落回默认链,绝不整段静默。
        _engine = _try_indextts() or _try_edge() or _try_melo() or _try_piper() or _try_kokoro() or _try_sapi()
    elif choice == "melo":
        _engine = _try_melo() or _try_piper() or _try_edge() or _try_kokoro() or _try_sapi()
    elif choice == "piper":
        _engine = _try_piper() or _try_melo() or _try_edge() or _try_kokoro() or _try_sapi()
    elif choice == "kokoro":
        _engine = _try_kokoro() or _try_sapi()
    elif choice == "sapi":
        _engine = _try_sapi()
    elif choice == "auto":
        _engine = _try_edge() or _try_kokoro() or _try_melo() or _try_piper() or _try_sapi()
    else:  # edge(默认)——运行期失败仍可经 demote 落到离线链;离线首选 kokoro(默认装机·神经音)
        _engine = _try_edge() or _try_kokoro() or _try_melo() or _try_piper() or _try_sapi()

    if _engine is None:
        logger.warning("TTS 引擎不可用(语音输出降级;装 edge-tts / melotts / piper-tts 可启用)")
        _engine_failed = True
    _note_engine_choice(_engine)
    return _engine


# 语音输出降级态(落到 SAPI 系统音 = 神经引擎全不可用)。供能力面板/诊断查询。
_tts_degraded_reason: Optional[str] = None


def get_tts_degraded_reason() -> Optional[str]:
    """当前语音输出是否处于"机器人音"降级态;None=用着神经引擎(自然音)。"""
    return _tts_degraded_reason


def _note_engine_choice(eng: Any) -> None:
    """落到系统音(SAPI)意味着 edge/kokoro 等神经引擎全不可用 —— 如实、醒目告知一次,
    不再"无声降级成机器人音、用户不知为何"(所有者反馈的"语音太僵")。"""
    global _tts_degraded_reason
    if eng is None:
        # 整条链解析到 None = 所有引擎(含 SAPI)都不可用 = 完全无声。绝不能让
        # get_tts_degraded_reason() 保持 None(那被定义为"自然音"),否则面板误报"正常"。
        _tts_degraded_reason = (
            "语音输出完全不可用:所有 TTS 引擎(edge/kokoro/melo/piper/SAPI)均不可用,"
            "当前无声。装一个可用引擎(如 pip install edge-tts / kokoro-onnx)后重启。"
        )
        return
    if type(eng).__name__ == "SapiTTSEngine":
        if _tts_degraded_reason is None:  # 一次性,避免刷屏
            _tts_degraded_reason = (
                "语音降级为系统音(SAPI 机器人音):edge-tts 云端不可达、且离线神经引擎"
                "(kokoro)模型未就绪。自然嗓音需 edge 可达,或等 kokoro 模型下载完成后重启"
                "(GALAXY_KOKORO_AUTOFETCH 默认开;网络受限时可手动预置模型)。"
            )
            logger.warning("\n%s\n🔊 %s\n%s", "=" * 66, _tts_degraded_reason, "=" * 66)
    else:
        # 用上了神经引擎(edge/kokoro/melo/piper)→ 清除降级态。
        _tts_degraded_reason = None


def demote_current_engine(reason: str = "", failed_engine: Any = None) -> Optional[Any]:
    """某个引擎【运行期】失败(合成/网络):拉黑【确实失败的那个】并重选下一个可用引擎。

    返回新引擎(None=链上已无可用)。选择期探不出的失败(edge 构造成功但云端
    不可达)靠这里自愈:第一句失败 → 换引擎 → 同句重试,用户最多丢一拍。

    failed_engine:调用方【实际失败的那个引擎实例】。并发朗读(chat 增量 + voice/ambient
    整段)共用同一全局引擎缓存:若 A 路已把 edge 降级成健康的 kokoro,B 路(还握着旧
    edge)再失败时【不能】按全局 _engine 去拉黑——那会误拉黑健康的 kokoro,一路拉到
    SAPI/静默。故传入失败实例:它已不是现役引擎时,直接返回现役,绝不重复/误拉黑。
    不传(旧调用/测试)则保持旧行为(按全局 _engine)。
    """
    global _engine, _engine_failed
    target = failed_engine if failed_engine is not None else _engine
    if target is None:
        return _engine
    # 并发保护:显式传了失败实例、而它已不是现役全局引擎 → 别人已降级过,返回现役健康引擎。
    if failed_engine is not None and _engine is not None and target is not _engine:
        return _engine
    _failed_engine_types.add(type(target).__name__)
    logger.warning(
        "TTS 引擎 %s 运行期失败(%s),拉黑并降级到下一引擎",
        type(target).__name__,
        (reason or "")[:120],
    )
    _engine = None
    _engine_failed = False
    return _get_engine()


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

            # 引擎经 holder 引用:合成运行期失败 → demote 换引擎 → 同句重试一次。
            holder = {"engine": engine}

            async def _synth(chunk: str) -> str:
                try:
                    return await holder["engine"].synthesize(chunk)
                except Exception as exc:  # noqa: BLE001
                    new_engine = demote_current_engine(str(exc), failed_engine=holder["engine"])
                    if new_engine is None:
                        raise
                    holder["engine"] = new_engine
                    return await new_engine.synthesize(chunk)

            async def _play(path: str) -> None:
                await holder["engine"]._play_audio(path)
                _rm(path)

            async def _stop() -> None:
                await holder["engine"].stop()

            def _rm(path: str) -> None:
                try:
                    os.remove(path)
                except OSError:
                    pass

            # discard:被打断时清理已合成但没播的临时 mp3,避免每次 barge-in 泄漏文件。
            speaker = StreamingSpeaker(
                _synth,
                _play,
                stop=_stop,
                on_speaking=_set_speaking,
                discard=_rm,
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

        # 回退：整段批处理（GALAXY_TTS_STREAMING=0）。失败同样降级换引擎重试一次。
        if _set_speaking is not None:
            _set_speaking(True)
        try:
            await engine.synthesize_and_play(spoken)
        except Exception as exc:  # noqa: BLE001
            new_engine = demote_current_engine(str(exc), failed_engine=engine)
            if new_engine is None:
                _log_speak_failure("语音输出", exc)
            else:
                try:
                    await new_engine.synthesize_and_play(spoken)
                except Exception as exc2:  # noqa: BLE001
                    _log_speak_failure("语音输出", exc2)
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


def begin_incremental_speech(
    *, source: str = "", on_sentence_start: Optional[Callable[[str], None]] = None
) -> Optional[Any]:
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

    # 引擎经 holder 引用:合成运行期失败(edge 云端不可达等)→ demote 换引擎
    # → 同句重试一次;play/stop 跟随换到新引擎。用户最多丢一拍,不再整段静默。
    holder = {"engine": engine}

    async def _synth(chunk: str) -> str:
        try:
            return await holder["engine"].synthesize(chunk)
        except Exception as exc:  # noqa: BLE001
            new_engine = demote_current_engine(str(exc), failed_engine=holder["engine"])
            if new_engine is None:
                raise
            holder["engine"] = new_engine
            return await new_engine.synthesize(chunk)

    async def _play(path: str) -> None:
        await holder["engine"]._play_audio(path)
        _rm(path)

    async def _stop() -> None:
        await holder["engine"].stop()

    speaker = IncrementalSpeaker(
        _synth,
        _play,
        stop=_stop,
        on_speaking=_set_speaking,
        discard=_rm,
        on_sentence_start=on_sentence_start,
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
