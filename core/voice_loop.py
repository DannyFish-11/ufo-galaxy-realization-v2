"""
core.voice_loop — 语音闭环协调器
==================================
完整的语音交互闭环：
    麦克风 → ASR → Galaxy处理 → TTS → 播放

依赖:
    pip install faster-whisper edge-tts sounddevice numpy

使用方式::

    import asyncio
    from core.voice_loop import VoiceLoop

    # galaxy_client 是处理文本并返回响应的 Galaxy 客户端
    voice_loop = VoiceLoop(galaxy_client)
    await voice_loop.start()  # 开始监听麦克风
    # 用户说话 → 自动识别 → Galaxy处理 → 语音回复
    # ...
    await voice_loop.stop()   # 停止监听
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("Galaxy.VoiceLoop")


class VoiceLoop:
    """语音交互闭环协调器。

    完整的语音交互流程：
        1. 麦克风录音 (AudioCaptureService)
        2. ASR语音识别 (WhisperASR) → 文字
        3. Galaxy处理 → 文字响应
        4. TTS语音合成 (EdgeTTSEngine) → 音频
        5. 播放音频

    使用方式::

        voice_loop = VoiceLoop(galaxy_client)
        await voice_loop.start()  # 开始监听
        # 用户说话 → 自动识别 → Galaxy处理 → 语音回复
        await voice_loop.stop()
    """

    def __init__(
        self,
        galaxy_client: Any,
        model_size: Optional[str] = None,
        voice: str = "zh-CN-XiaoxiaoNeural",
        language: str = "zh",
        sample_rate: int = 16000,
        chunk_duration_ms: int = 100,
        speak_responses: bool = True,
    ) -> None:
        """初始化语音闭环。

        Args:
            galaxy_client: Galaxy 客户端实例，需要实现 ``process(text, source)`` 方法。
            model_size: Whisper 模型大小 (tiny/base/small/medium/large)。
            voice: TTS 声音 ID。
            language: ASR 语言代码 (默认 "zh" 中文)。
            sample_rate: 音频采样率 (Hz)。
            chunk_duration_ms: 音频块时长 (毫秒)。
            speak_responses: 是否由本回路自行 TTS 朗读回复。集成进 Galaxy 时设 False——
                朗读已由 handle_request 经 core.speech_output 集中处理，避免一句念两遍。
        """
        self.galaxy = galaxy_client
        self.model_size = model_size
        self.voice = voice
        self.language = language
        self.sample_rate = sample_rate
        self.chunk_duration_ms = chunk_duration_ms
        self.speak_responses = speak_responses

        self.asr: Optional[Any] = None
        self.tts: Optional[Any] = None
        self.capture: Optional[Any] = None
        self._running: bool = False
        self._voice_input_handler: Optional[Callable[[str], asyncio.Future]] = None
        # 语义回合合并(GPT-Live 借鉴):悬垂片段暂存,等下一片段并进同一回合。
        self._pending_text: str = ""
        self._turn_seq: int = 0
        # 委托模式:后台任务句柄(防 GC;stop 时取消)。
        self._bg_tasks: set = set()
        # 双工模式状态(未启用时全为 None)
        self._duplex: Optional[Any] = None
        self._duplex_player: Optional[Any] = None
        self._duplex_loop: Optional[asyncio.AbstractEventLoop] = None

    async def start(self) -> None:
        """启动语音闭环。

        初始化 ASR、TTS 和音频捕获服务，开始监听麦克风。
        """
        if self._running:
            logger.warning("VoiceLoop already running")
            return

        # Lazy imports to avoid hard dependencies at module load time
        try:
            from core.asr import WhisperASR
            from core.multimodal.audio_capture_service import (
                AudioCaptureConfig,
                AudioCaptureService,
            )
            from core.tts import EdgeTTSEngine
        except ImportError as exc:
            # 语音(麦克风)是可选功能；依赖缺失时明确记录错误并给出修复命令
            err_msg = str(exc)
            if "faster-whisper" in err_msg or "faster_whisper" in err_msg:
                logger.error("语音依赖缺失: faster-whisper 未安装. " "运行: pip install faster-whisper 后重启")
            elif "sounddevice" in err_msg:
                logger.error("语音依赖缺失: sounddevice 未安装. " "运行: pip install sounddevice 后重启")
            elif "edge-tts" in err_msg or "edge_tts" in err_msg:
                logger.error("语音依赖缺失: edge-tts 未安装. " "运行: pip install edge-tts 后重启")
            else:
                logger.error("语音依赖缺失: %s. 运行: pip install faster-whisper", exc)
            raise

        logger.info("Starting VoiceLoop...")

        # 0. 双工优先:开关打开且会话建得起来 → 走持续上下行链路,不再初始化
        #    ASR/TTS(那是回合制的部件)。建不起来则如实退回回合制,原因已在
        #    open_duplex_session 里记过日志。
        if await self._try_start_duplex(AudioCaptureConfig, AudioCaptureService):
            return

        # 1. 初始化 ASR
        self.asr = WhisperASR(model_size=self.model_size)
        logger.info("ASR initialized: %s", self.asr)

        # 2. 初始化 TTS
        self.tts = EdgeTTSEngine(voice=self.voice)
        logger.info("TTS initialized: %s", self.tts)

        # 3. 初始化音频捕获服务
        capture_config = AudioCaptureConfig(
            sample_rate=self.sample_rate,
            chunk_duration_ms=self.chunk_duration_ms,
        )
        self.capture = AudioCaptureService(config=capture_config)

        # 4. 注册 ASR 回调
        self.capture.add_whisper_callback(self.asr, language=self.language)

        # 5. 注册语音输入处理回调
        self.capture.on_voice_input = self._on_voice_input

        # 6. 启动捕获
        await self.capture.start()
        self._running = True
        logger.info("VoiceLoop started — listening for voice input")

    # ── 双工路径 ──────────────────────────────────────────────────────────

    async def _try_start_duplex(self, AudioCaptureConfig, AudioCaptureService) -> bool:  # noqa: N803
        """尝试用双工会话取代回合制链路。返回是否真的启动了双工。

        为什么是"取代"而不是"并存":同一个麦克风的音频不能既攒着等 Whisper 整段转写、
        又实时流给 realtime 服务端 —— 两条路都要独占回合边界的判定权。所以这里二选一。

        上行刻意复用 ``AudioCaptureService``:AEC 挂在 ``AudioIngestPipeline._process_chunk``
        里,走这条路上行的音频**已经过回声消除**。双工比回合制更需要这一点 —— 回合制下
        AI 说话时采到的回声最终会被丢掉,双工下那些字节会实时进模型,不消回声等于让模型
        一直听见自己在说话。
        """
        try:
            from core.voice_duplex_session import (
                DuplexEventType,
                PcmPlayer,
                duplex_enabled,
                open_duplex_session,
                pcm16_from_float,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("双工模块不可用,走回合制: %s", exc)
            return False

        if not duplex_enabled():
            return False
        session = await open_duplex_session()
        if session is None:
            return False

        self._duplex = session
        self._duplex_player = PcmPlayer(sample_rate=self.sample_rate)
        self._duplex_player.start()

        # 上行:复用采集服务(因此复用 AEC),把每块样本转成 PCM16 发上去
        capture = AudioCaptureService(
            config=AudioCaptureConfig(
                sample_rate=self.sample_rate,
                chunk_duration_ms=self.chunk_duration_ms,
            )
        )

        def _uplink(state, _quality) -> None:
            try:
                pcm = pcm16_from_float(state.samples)
                if not pcm:
                    return
                loop = self._duplex_loop
                if loop is None:
                    return
                # 采集回调跑在采集线程/事件循环回调里,发送是 async → 跨线程安全调度
                asyncio.run_coroutine_threadsafe(session.send_audio(pcm), loop)
            except Exception as exc:  # noqa: BLE001 — 上行单块失败不能影响采集
                logger.debug("双工上行单块失败(跳过): %s", exc)

        self._duplex_loop = asyncio.get_running_loop()
        capture.add_asr_callback(_uplink)
        self.capture = capture
        await capture.start()

        task = asyncio.ensure_future(self._duplex_downlink(session, DuplexEventType))
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

        self._running = True
        logger.info("VoiceLoop 已以【双工】模式启动(持续上行 + 持续下行)")
        return True

    async def _duplex_downlink(self, session, DuplexEventType) -> None:  # noqa: N803
        """消费下行事件:播音频、推面板、按"先压音后决定"处理用户开口。

        为什么不是"一听见用户出声就 cancel"
        -----------------------------------
        最初就是那么写的,但那把回合制那边刚修好的毛病又犯了一遍:用户"嗯"一声也会把
        模型的回复整个取消掉。服务端 VAD 只告诉你"有人在出声",它分不出这是抢话还是
        积极倾听 —— 那是 ``classify_barge_in`` 的活。

        改成两段式,与人的实际反应一致:

        1. ``USER_SPEECH_STARTED`` → **压音**(ducking)。低延迟、听感自然,而且是
           **非承诺性**的:压低不等于放弃,还能回来。
        2. ``FINAL_TRANSCRIPT`` → 这时才知道用户到底说了什么:
           - 应答("嗯""对")→ **恢复音量继续说**,不打扰模型;
           - 真打断 → 让服务端 ``response.cancel``(只停本地播放没用,模型那边还在
             继续生成、token 照烧)。

        没有 ducking(播放器不可用/开关关掉)时退回原行为:开口即 cancel。
        """
        from core.voice_dialog_policy import (
            BARGE_IN_BACKCHANNEL,
            backchannel_tolerance_enabled,
            get_dialog_policy,
        )
        from core.voice_duplex_session import ducking_enabled

        try:
            async for ev in session.events():
                if ev.type is DuplexEventType.ASSISTANT_AUDIO_DELTA and ev.audio_b64:
                    import base64

                    self._duplex_player.play(base64.b64decode(ev.audio_b64))
                elif ev.type is DuplexEventType.USER_SPEECH_STARTED:
                    if ducking_enabled() and self._duplex_player is not None:
                        self._duplex_player.duck()
                    else:
                        await session.interrupt()
                elif ev.type is DuplexEventType.FINAL_TRANSCRIPT and ev.text:
                    self._emit_panel("user", ev.text)
                    kind = (
                        get_dialog_policy().classify_barge_in(ev.text)
                        if backchannel_tolerance_enabled()
                        else "interrupt"
                    )
                    if kind == BARGE_IN_BACKCHANNEL:
                        logger.info("双工:应答(非打断),恢复音量继续说: %s", ev.text[:20])
                        if self._duplex_player is not None:
                            self._duplex_player.unduck()
                    else:
                        await session.interrupt()
                        if self._duplex_player is not None:
                            self._duplex_player.unduck()
                elif ev.type is DuplexEventType.RESPONSE_DONE:
                    # 一个回合结束,音量必须回到正常 —— 否则下一段回复会一直是压着的
                    if self._duplex_player is not None:
                        self._duplex_player.unduck()
                    logger.debug("双工:一个回复回合结束")
                elif ev.type is DuplexEventType.SESSION_CLOSED:
                    return
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("双工下行消费异常结束: %s", exc)

    @staticmethod
    def _emit_panel(role: str, text: str) -> None:
        try:
            from core.lumiv_websocket_bridge import emit_conversation

            emit_conversation(role, text, source="voice")
        except Exception as exc:  # noqa: BLE001
            logger.debug("emit_conversation 跳过(非致命): %s", exc)

    async def _on_voice_input(self, text: str) -> None:
        """处理语音识别结果。

        流程:
            1. 发送给 Galaxy 处理
            2. TTS 合成并播放响应

        Args:
            text: ASR 识别出的文字。
        """
        if not self._running:
            return

        logger.info("Voice input: %s", text)

        # ── 反自激励门(必须在 barge-in 之前)──────────────────────────────
        # 扬声器放出去的 TTS 会被同一间屋子的麦克风重新采回来、被 VAD 判成"有人在
        # 说话"、被 Whisper 转写成文字流到这里。若不在此拦住,下面两件事都会发生:
        #   1. barge-in 把 AI 自己的朗读掐断(它把自己的回声当成"用户开口了");
        #   2. AI 自己说的话被当作用户输入送进大脑 → 对自己作答 → 自言自语闭环。
        # 判的是"这段文字是不是我刚说过的话"而不是"此刻是否在朗读",所以真正的
        # barge-in(用户说的是别的内容)完全不受影响。见 core.voice_echo_guard。
        try:
            from core.voice_echo_guard import VERDICT_SELF_ECHO, classify_asr_text

            verdict, score, reason = classify_asr_text(text)
            if verdict == VERDICT_SELF_ECHO:
                logger.info(
                    "反自激励:丢弃 AI 自己的回声(重合=%.2f, %s): %s",
                    score,
                    reason,
                    text[:40],
                )
                return  # 不打断、不处理——它本来就是我们自己在说话
        except Exception as _exc:  # noqa: BLE001 — 门失灵绝不能让助手变聋
            logger.warning("反自激励门不可用,按用户输入继续处理: %s", _exc)

        # ── barge-in:朗读期间用户出声,分"应答"与"真打断"两种处理 ──────────
        # 原先是"ASR 一出词就掐断"。但人在听别人说话时会一直出声("嗯""对""好""哦")
        # —— 那是积极倾听,不是抢话。全当打断的结果是 AI 每讲两句就被"嗯"一声掐断,
        # 对话根本进行不下去。所以:应答 → 继续说、且不送大脑;真打断 → 立刻掐断。
        try:
            from core.speech_output import interrupt_speech, is_speaking
            from core.voice_dialog_policy import (
                BARGE_IN_BACKCHANNEL,
                backchannel_tolerance_enabled,
            )

            if is_speaking():
                from core.voice_dialog_policy import get_dialog_policy as _gp

                kind = _gp().classify_barge_in(text) if backchannel_tolerance_enabled() else "interrupt"
                if kind == BARGE_IN_BACKCHANNEL:
                    # 继续说下去,也不把这声"嗯"当成一个用户回合送进大脑 ——
                    # 那会让 AI 对一句语义空的应答另起一段回复。
                    logger.info("应答(非打断),继续朗读: %s", text[:20])
                    return
                interrupt_speech()
                logger.info("Barge-in: 用户开口，打断 AI 朗读")
        except Exception as _exc:  # noqa: BLE001
            logger.debug("barge-in 跳过(非致命): %s", _exc)

        # ── 对话政策(GPT-Live 借鉴,政策集中在 core.voice_dialog_policy)──
        from core.voice_dialog_policy import delegation_enabled, get_dialog_policy

        policy = get_dialog_policy()

        # hold("等一下别说话"):安静等着,只认恢复口令或窗口到期;期间不处理、不出声。
        if policy.is_holding():
            if policy.check_resume_command(text):
                policy.release_hold()
                logger.info("hold 解除(用户口令): %s", text)
                if len(text.strip()) <= 10:
                    return  # 纯恢复口令("好了/继续")静默消化,不当内容送大脑
            else:
                logger.info("hold 中,忽略语音输入: %s", text[:40])
                return
        elif policy.check_hold_command(text):
            policy.hold()
            return  # 按 GPT-Live 行为:安静等着,不答话

        # 语义回合判定:悬垂结尾(连接词/逗号)→ 等一拍并入下一片段,不抢话。
        text = await self._resolve_turn(text)
        if text is None:
            return  # 已并入更新的回合,由后到的调用处理

        # A 融合:把语音对话实时推给面板"实时上下文"。此前只有默认【关闭】的
        # (已删除的旧 voice_conversation_bridge 曾调 emit_conversation)真正默认【开启】、
        # 驱动三态与朗读的正是本 VoiceLoop——它此前从不推送,导致默认配置下面板的
        # 语音实时显示永远是空的(PresencePanel 的"语音"标签形同虚设)。这里在本
        # (唯一默认活跃的)语音闭环里补上推送,让面板与语音真正一体。容错、永不抛出。
        try:
            from core.lumiv_websocket_bridge import emit_conversation

            emit_conversation("user", text, source="voice")
        except Exception as _exc:  # noqa: BLE001
            logger.debug("emit_conversation(user) 跳过(非致命): %s", _exc)

        # 委托模式(对话节奏 ⊥ 推理深度):heavy 回合立即口头致谢,重活丢后台跑,
        # 期间按节奏出捧哏;结果回来经既有链路(集中朗读/面板推送)自然回到对话。
        # quick 回合走原同步路径——闲聊不需要"我去查"的仪式感。
        if delegation_enabled() and policy.classify_turn(text) == "heavy":
            ack = policy.ack_phrase()
            try:
                from core.speech_output import speak_response

                speak_response(ack, source="voice")
            except Exception as _exc:  # noqa: BLE001
                logger.debug("委托致谢朗读跳过(非致命): %s", _exc)
            try:
                from core.lumiv_websocket_bridge import emit_conversation

                emit_conversation("ai", ack, source="voice")
            except Exception as _exc:  # noqa: BLE001
                logger.debug("emit_conversation(ack) 跳过(非致命): %s", _exc)
            task = asyncio.ensure_future(self._process_and_reply(text))
            self._bg_tasks.add(task)
            task.add_done_callback(self._bg_tasks.discard)
            bc = asyncio.ensure_future(self._backchannel_while(task))
            self._bg_tasks.add(bc)
            bc.add_done_callback(self._bg_tasks.discard)
            return

        await self._process_and_reply(text)

    async def _resolve_turn(self, text: str) -> Optional[str]:
        """语义回合合并:悬垂片段暂存、等一拍;新片段到来即接管合并。

        返回最终成句的回合文本;返回 None 表示本片段已并入更新的回合。
        """
        from core.voice_dialog_policy import end_of_turn_wait

        self._turn_seq += 1
        my_seq = self._turn_seq
        if self._pending_text:
            # 与暂存的悬垂片段合并成同一回合
            text = f"{self._pending_text} {text}".strip()
            self._pending_text = ""
        try:
            wait = end_of_turn_wait(text)
        except Exception as _exc:  # noqa: BLE001 — 政策失败不影响主链
            logger.debug("end_of_turn_wait 失败,按说完处理: %s", _exc)
            wait = 0.0
        if wait <= 0:
            return text
        self._pending_text = text
        logger.debug("回合疑似未说完,等待 %.1fs 并句: %s", wait, text[-20:])
        await asyncio.sleep(wait)
        if self._turn_seq != my_seq:
            return None  # 新片段已接管(合并发生在后到调用里)
        self._pending_text = ""
        return text

    async def _process_and_reply(self, text: str) -> None:
        """把一个成句回合交给 Galaxy 处理并回话(原 _on_voice_input 主体)。"""
        try:
            # 1. 发送给 Galaxy 处理
            if asyncio.iscoroutinefunction(self.galaxy.process):
                result = await self.galaxy.process(text, source="voice")
            else:
                result = self.galaxy.process(text, source="voice")

            response = ""
            if isinstance(result, dict):
                response = result.get("response", "")
            elif isinstance(result, str):
                response = result

            if not response:
                logger.debug("Empty response from Galaxy, skipping TTS")
                return

            logger.info("Galaxy response: %s", response[:100])

            # A 融合:AI 的语音回复也推给面板"实时上下文"。
            try:
                from core.lumiv_websocket_bridge import emit_conversation

                emit_conversation("ai", response, source="voice")
            except Exception as _exc:  # noqa: BLE001
                logger.debug("emit_conversation(ai) 跳过(非致命): %s", _exc)

            # 2. TTS 合成并播放(仅当本回路负责朗读;集成进 Galaxy 时由 handle_request 集中朗读,
            #    此处 speak_responses=False,避免同一句念两遍)。
            if self.tts is not None and self.speak_responses:
                await self.tts.synthesize_and_play(response)
                logger.info("TTS playback completed")

        except Exception as exc:
            logger.error("Voice input processing error: %s", exc)

    async def _backchannel_while(self, task: "asyncio.Future") -> None:
        """后台任务运行期间按政策节奏出捧哏(首次 ~5s,之后 ~12s,最多 2 次)。

        hold 中/AI 正在朗读时跳过本拍,绝不叠声。
        """
        import time as _time

        from core.voice_dialog_policy import get_dialog_policy

        policy = get_dialog_policy()
        start = _time.monotonic()
        emitted = 0
        try:
            while not task.done():
                await asyncio.sleep(0.5)
                if task.done():
                    break
                if policy.is_holding():
                    continue
                if not policy.should_backchannel(_time.monotonic() - start, emitted):
                    continue
                try:
                    from core.speech_output import is_speaking, speak_response

                    if is_speaking():
                        continue  # 不压着正在播的话
                    speak_response(policy.backchannel_phrase(), source="voice")
                    emitted += 1
                except Exception as _exc:  # noqa: BLE001
                    logger.debug("捧哏跳过(非致命): %s", _exc)
        except asyncio.CancelledError:  # stop() 取消属正常路径
            pass

    async def stop(self) -> None:
        """停止语音闭环。

        停止音频捕获服务并清理资源。
        """
        self._running = False

        # 取消委托/捧哏后台任务(生命周期对称,不留孤儿)
        for t in list(self._bg_tasks):
            t.cancel()
        self._bg_tasks.clear()

        if self.capture is not None:
            try:
                await self.capture.stop()
            except Exception as exc:
                logger.debug("Error stopping capture: %s", exc)

        # 双工资源的生命周期必须与回路对称:漏掉这里会留一条活着的 WebSocket 连接和
        # 一条打开的音频输出流 —— 前者继续计费/占额度,后者占着音频设备不放。
        player, self._duplex_player = self._duplex_player, None
        if player is not None:
            try:
                player.stop()
            except Exception as exc:  # noqa: BLE001
                logger.debug("关闭双工播放器失败(忽略): %s", exc)

        session, self._duplex = self._duplex, None
        if session is not None:
            try:
                await session.close()
            except Exception as exc:  # noqa: BLE001
                logger.debug("关闭双工会话失败(忽略): %s", exc)

        self._duplex_loop = None
        logger.info("VoiceLoop stopped")

    async def say(self, text: str) -> None:
        """直接让系统说一段话（不经过ASR）。

        Args:
            text: 要说的文字。
        """
        if self.tts is None:
            logger.warning("TTS not initialized, cannot speak")
            return

        logger.info("Saying: %s", text[:100])
        await self.tts.synthesize_and_play(text)

    async def process_once(self, audio_np, sample_rate: int = 16000) -> Dict[str, Any]:
        """处理单次音频输入（非流式）。

        适用于批量处理预录音频，而非实时麦克风输入。

        Args:
            audio_np: 音频numpy数组。
            sample_rate: 音频采样率。

        Returns:
            处理结果字典，包含 ``asr_text``、``response``、``audio_path``。
        """
        result: Dict[str, Any] = {
            "asr_text": "",
            "response": "",
            "audio_path": None,
            "success": False,
        }

        try:
            # 1. 听 —— 走 modality_bridge 这个"听的收口":B 档原生后端激活时先让全模态
            #    模型自己听懂,拿不到再回落 ASR。
            #
            #    此前这里是直接 self.asr.transcribe(...),完全绕过收口。后果是 B 档最核心
            #    的那件事没生效:切到 B 档后【说】确实走原生(speech_output 认
            #    register_native_speech_backend),而【听】永远是 Whisper —— 一半原生一半
            #    桥,且没有任何报错,用户以为模型在听,其实模型压根没收到音频。
            #
            #    ASR 的构造放进 fallback 里惰性执行:原生这条路走通时,Whisper 模型根本
            #    不必加载(那是几百 MB 的权重和可观的启动时间)。
            def _asr_fallback(pcm, sr, lang):
                if self.asr is None:
                    from core.asr import WhisperASR

                    self.asr = WhisperASR(model_size=self.model_size)
                return self.asr.transcribe(pcm, sample_rate=sr, language=lang)

            from core.modality_bridge import transcribe_pcm

            text = transcribe_pcm(
                audio_np,
                sample_rate=sample_rate,
                language=self.language,
                fallback=_asr_fallback,
            )
            result["asr_text"] = text
            logger.info("ASR: %s", text)

            if not text:
                result["note"] = "No speech detected"
                return result

            # 2. Galaxy 处理
            if asyncio.iscoroutinefunction(self.galaxy.process):
                gal_result = await self.galaxy.process(text, source="voice")
            else:
                gal_result = self.galaxy.process(text, source="voice")

            response = ""
            if isinstance(gal_result, dict):
                response = gal_result.get("response", "")
            elif isinstance(gal_result, str):
                response = gal_result
            result["response"] = response

            # 3. TTS
            if response and self.tts is None:
                from core.tts import EdgeTTSEngine

                self.tts = EdgeTTSEngine(voice=self.voice)

            if response and self.tts is not None:
                audio_path = await self.tts.synthesize(response)
                result["audio_path"] = audio_path

            result["success"] = True

        except Exception as exc:
            logger.error("Process once error: %s", exc)
            result["error"] = str(exc)

        return result

    @property
    def is_running(self) -> bool:
        """语音闭环是否正在运行。"""
        return self._running

    def __repr__(self) -> str:
        return (
            f"VoiceLoop(running={self._running}, "
            f"model_size={self.model_size}, voice={self.voice}, "
            f"language={self.language})"
        )
