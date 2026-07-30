"""core/voice_duplex_session.py —— 双工语音会话(持续上行 + 持续下行)。

这一层解决什么
--------------
现有语音链路是**回合制**的:麦克风攒够一段 → Whisper 整段转写 → 大脑生成整段回复 →
TTS 整段合成播放。每一步都要等上一步结束,所以"同一时刻边说边听"在架构上就不可能 ——
不是调参问题,是拓扑问题。

双工会话把这条链路换成**一条持续开着的连接**:音频不断往上走,音频/文字不断往下来,
两个方向互不阻塞。用户说到一半模型就能开始应答,模型说到一半用户插话也能立刻被听见。

三层的分工(与已落地的两层是叠加关系,不是替代)
------------------------------------------------
* ``acoustic_echo_canceller`` —— 信号层:把扬声器的声音从麦克风里减掉。**双工比回合制
  更需要它**:回合制下 AI 说话时麦克风的内容最终会被丢掉,双工下那些字节会实时上行进
  模型,不做 AEC 等于让模型一直听见自己在说话。
* ``voice_echo_guard`` —— 文本层:兜住 AEC 消不掉的非线性残余回声。
* 本模块 —— 传输/编排层:让"同时"这件事在拓扑上成为可能。

诚实边界
--------
* **默认关闭**(``GALAXY_VOICE_DUPLEX=0``)。它需要一个支持 realtime 的 provider 与
  对应的 key;默认打开会让所有没配 key 的部署直接失去语音功能。这是刻意的保守默认,
  不是"没接上"—— 接线在 ``VoiceLoop.start()`` 里,开关一开就走这条路(见
  ``tests/test_voice_duplex_session.py::TestVoiceLoopWiring``)。
* **真实 provider 连接在本仓库的测试环境里无法验证**(没有 key、没有出网)。可验证的是
  协议编解码(抽成纯函数)、会话状态机、以及跑在**本地真 WebSocket 服务端**上的完整
  会话流程 —— 那不是 mock,是真的建连、真的收发帧。
* 已实现两个适配器:OpenAI Realtime 与 Gemini Live(``BidiGenerateContent``)。两家不只是
  字段名不同,是**结构不同** —— 配置帧的位置与时机、音频上行的载体、下行 parts 的混合
  数组、回合边界的表达、鉴权方式(Gemini 的 key 在 URL query 里)全都不一样,所以是两份
  实现而不是参数化的一份。未登记的 provider 名显式抛错,**绝不**静默退回某个默认实现。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

logger = logging.getLogger("Galaxy.VoiceDuplex")

_BACKGROUND_TASKS: set = set()

#: 下行事件队列上限。满了丢**最旧**的:双工场景里过期的音频块没有价值,
#: 而阻塞上行会直接毁掉实时性。
_EVENT_QUEUE_MAX = 256


# 统一走 core.config_flags —— 这里原先是 5 份逐字相同的本地 _flag 副本,
# 其中一个真 bug(空值把开关打开)因此要修 5 遍。详见该模块 docstring。
from core.config_flags import flag as _flag  # noqa: E402  (保留 _flag 名字以免动全部调用点)


def safe_endpoint(url: str) -> str:
    """把 realtime URL 收敛成**可以安全打日志**的 ``scheme://host:port``。

    为什么必须有这个函数
    --------------------
    realtime 的 URL 是**带凭据的**:本模块 Gemini 那一支就是

        wss://generativelanguage.googleapis.com/ws/...BidiGenerateContent?key={key}

    —— API key 直接拼在 query 里。所以任何"把 url 原样打出来"的日志都是明文泄露密钥。
    我自己就在加"本地端点免 key"那段时踩了这个坑(CodeQL alert 1025 指的正是那一行),
    而且它不只是静态分析的洁癖:本地网关用 query 带 token 很常见,用户把
    ``GALAXY_REALTIME_URL`` 设成那种形式时,日志就会把 token 原样记下来。

    只保留 scheme/host/port:诊断要回答的是"连的是哪台机器",这三样就够了;path / query /
    fragment / userinfo 一律丢掉 —— 它们才是凭据可能藏身的地方。
    """
    from urllib.parse import urlsplit

    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").strip()
        if not host:
            return "(无效地址)"
        scheme = (parts.scheme or "ws").strip()
        port = parts.port  # 解析失败会抛 ValueError,一并被下面接住
    except Exception as exc:  # noqa: BLE001 —— 打日志不该成为崩溃来源
        logger.debug("解析 realtime URL 失败: %s", exc)
        return "(无效地址)"
    return f"{scheme}://{host}:{port}" if port else f"{scheme}://{host}"


def is_local_endpoint(url: str) -> bool:
    """这个 realtime 端点是不是**本机/本网**的服务(因而不需要云端 API key)。

    为什么需要这个判断
    ------------------
    ``from_env()`` 原先无条件要求 key,拿不到就返回 None 并告警"缺少 API key"。但本地
    服务根本没有 key 这个概念 —— B 档切换后 ``core.native_modal`` 会把 MiniCPM-o 官方
    server 拉起来(默认 ``localhost:32550``),这时:

        GALAXY_REALTIME_URL=ws://localhost:32550/...   # 指向本地
        GALAXY_NATIVE_AUDIO=1                          # 原生听/说已就绪
        (没有云端 key)

    旧逻辑一律判"缺 key → 退回回合制",于是**本地服务配好了也起不来**,而且日志把人引去
    配云端 key —— 那是完全无关的一件事。这是纯逻辑错误,与任何 provider 的协议无关。

    判据取"回环 / 私网 / .local",也就是"这台机器或这个局域网里的服务"。刻意**不**用
    "只要显式设了 URL 就免 key":那样会把指向云端的自定义 URL 也放过去,拿空 key 建连换
    一个 401,反而更难查。
    """
    from urllib.parse import urlsplit

    try:
        host = (urlsplit(url).hostname or "").strip().lower()
    except Exception as exc:  # noqa: BLE001 —— URL 畸形不该让调用方崩
        logger.debug("解析 realtime URL 失败(按非本地处理): %s", exc)
        return False
    if not host:
        return False
    if host in ("localhost", "::1") or host.endswith(".local"):
        return True
    try:
        import ipaddress

        return ipaddress.ip_address(host).is_loopback or ipaddress.ip_address(host).is_private
    except ValueError:
        return False  # 不是 IP 字面量,又不在上面的名字里 → 当作远端


def duplex_enabled() -> bool:
    """双工语音是否启用。**默认关闭** —— 它需要 realtime provider 与 key。"""
    return _flag("GALAXY_VOICE_DUPLEX", "0")


def ducking_enabled() -> bool:
    """用户开口时是否压低音量(而不是立刻掐断)。双工路径默认开启。

    默认开启的理由:立刻掐断在用户只是"嗯"了一声时是错的,而压音是**非承诺性**的 ——
    先压低(低延迟、听感自然),等最终转写到了再决定是真打断还是继续说。
    """
    return _flag("GALAXY_VOICE_DUCKING", "1")


def duck_gain() -> float:
    """压音时的增益(0~1)。默认 0.25(约 −12 dB):明显压下去但仍听得见。"""
    raw = os.getenv("GALAXY_VOICE_DUCK_GAIN", "").strip()
    if not raw:
        return 0.25
    try:
        return max(0.0, min(1.0, float(raw)))
    except ValueError:
        logger.warning("GALAXY_VOICE_DUCK_GAIN=%r 不是合法数值,已退回 0.25", raw)
        return 0.25


class DuplexEventType(str, Enum):
    """下行事件类型(provider 无关)。"""

    SESSION_OPEN = "session_open"
    USER_SPEECH_STARTED = "user_speech_started"  # 服务端 VAD 判定用户开口
    USER_SPEECH_STOPPED = "user_speech_stopped"
    PARTIAL_TRANSCRIPT = "partial_transcript"
    FINAL_TRANSCRIPT = "final_transcript"
    ASSISTANT_TEXT_DELTA = "assistant_text_delta"
    ASSISTANT_AUDIO_DELTA = "assistant_audio_delta"
    RESPONSE_DONE = "response_done"
    ERROR = "error"
    SESSION_CLOSED = "session_closed"


@dataclass
class DuplexEvent:
    """一条下行事件。``raw`` 保留原始帧,便于排查 provider 侧的意外字段。"""

    type: DuplexEventType
    text: str = ""
    audio_b64: str = ""
    error: str = ""
    ts: float = field(default_factory=time.time)
    raw: Optional[Dict[str, Any]] = field(default=None, repr=False)


@dataclass
class DuplexSessionConfig:
    """双工会话参数。

    ``api_key`` 刻意**不**带默认值也不从这里读环境变量 —— 由 ``from_env`` 统一负责,
    避免出现"某处忘了传 key 就静默用了空字符串去建连"。
    """

    url: str
    api_key: str
    model: str = "gpt-4o-realtime-preview"
    voice: str = "alloy"
    sample_rate: int = 16000
    instructions: str = ""
    #: 服务端 VAD 的静音判定阈值(毫秒)。双工下回合边界由服务端判,不再靠本地攒够时长。
    silence_ms: int = 500

    #: provider 名(决定用哪个 ProtocolAdapter)
    provider: str = "openai_realtime"

    @classmethod
    def from_env(cls) -> Optional["DuplexSessionConfig"]:
        """从配置构造;缺 key 或缺 url 时返回 None 并**说明缺什么**。

        返回 None 而不是抛异常:双工默认关闭,缺配置是预期情形而非错误。但原因要能
        从日志里看到 —— 否则"开了开关却没生效"完全无从排查。

        provider 由 ``GALAXY_REALTIME_PROVIDER`` 选,默认 ``openai_realtime``。两家的
        默认 URL、默认模型、鉴权方式都不同(Gemini 的 key 在 URL query 里,没有
        Authorization 头),所以要分开组。

        密钥为什么不用 ``os.getenv``
        ----------------------------
        原先这里是 ``os.getenv("GALAXY_REALTIME_API_KEY") or os.getenv("OPENAI_API_KEY")``,
        有两个真问题:

        1. **只覆盖第三层。** 本仓库解析云端 key 的权威顺序是
           面板/Dashboard → CredentialVault → 环境变量;裸 ``os.getenv`` 跳过前两层。
           ``GALAXY_SECRET_BACKEND=vault`` 时 key 只在 vault 里,双工层会直接瞎掉,
           而系统其余部分照常工作 —— 这种"只有一处瞎了"最难排查。
        2. **不过滤占位符。** ``main.py`` 启动时会把 ``.env``(含
           ``your_openai_api_key_here`` 这种未编辑模板)灌进 ``os.environ``。于是双工层
           把模板文字当真 key,拿去连 ``wss://api.openai.com/v1/realtime``,换来一个
           401 —— 而正确行为是认出"这不是真 key",安静退回回合制。路由器一直是过滤的
           (``PLACEHOLDER_PREFIXES``),只有这里漏了。

        现在统一走 ``core.secret_resolution.resolve_secret()``,与路由器同序、共用同一份
        占位符判据。**非密钥项**(provider/url/model/voice)仍读环境变量:它们不是
        secret,面板保存后会经 ``main.py`` 注回 ``os.environ``,没有 vault 那一层。
        """
        from core.secret_resolution import resolve_secret

        provider = (os.getenv("GALAXY_REALTIME_PROVIDER") or "openai_realtime").strip()
        url = (os.getenv("GALAXY_REALTIME_URL") or "").strip()
        model = (os.getenv("GALAXY_REALTIME_MODEL") or "").strip()

        if provider == "gemini_live":
            # 专用键优先于通用键:专门给双工配的那把先用,没配才退回该家的通用 key。
            key = resolve_secret("GALAXY_REALTIME_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY")
            model = model or "gemini-2.0-flash-exp"
            voice = (os.getenv("GALAXY_REALTIME_VOICE") or "Puck").strip()
            if not url and key:
                url = (
                    "wss://generativelanguage.googleapis.com/ws/"
                    "google.ai.generativelanguage.v1alpha.GenerativeService."
                    f"BidiGenerateContent?key={key}"
                )
            missing = "GALAXY_REALTIME_API_KEY 或 GOOGLE_API_KEY"
        else:
            key = resolve_secret("GALAXY_REALTIME_API_KEY", "OPENAI_API_KEY")
            model = model or "gpt-4o-realtime-preview"
            voice = (os.getenv("GALAXY_REALTIME_VOICE") or "alloy").strip()
            if not url:
                url = f"wss://api.openai.com/v1/realtime?model={model}"
            missing = "GALAXY_REALTIME_API_KEY 或 OPENAI_API_KEY"

        if not key and is_local_endpoint(url):
            # 本地服务不需要 key。B 档切过去之后 core.native_modal 会把 MiniCPM-o
            # 官方 server 拉起来(默认 localhost:32550),这条路径正是给它用的。
            # 只打 scheme://host:port —— realtime URL 可能在 query 里带凭据
            # (本模块 Gemini 那一支就是 ?key=…),原样打出来就是明文泄露。
            logger.info(
                "双工语音:realtime 端点是本地服务(%s),无需 API key。",
                safe_endpoint(url),
            )
            return cls(url=url, api_key="", model=model, voice=voice, provider=provider)

        if not key:
            # 区分"没填"与"填的是占位符" —— 后者用户以为自己配好了,不说清会白查很久。
            from core.secret_resolution import describe_source

            sources = {n: describe_source(n) for n in ("GALAXY_REALTIME_API_KEY", missing.split(" 或 ")[-1])}
            if "placeholder" in sources.values():
                logger.warning(
                    "双工语音已开启,但 API key 是【未编辑的占位符模板】(%s),不是真密钥;"
                    "本次退回回合制语音链路。请在面板「模型」tab 填入真实 key。",
                    sources,
                )
            else:
                logger.warning("双工语音已开启但缺少 API key(%s),本次退回回合制语音链路。", missing)
            if os.environ.get("GALAXY_NATIVE_AUDIO") == "1":
                # 这一句是为了不误导:此时本地原生听/说其实**已经通了**(B 档
                # native_modal 注册的那条),缺的只是"真流式双工"这一层。只说"缺 key"会让
                # 人以为语音整个是瞎的,跑去折腾云端配置。
                logger.info(
                    "补充:本地原生听/说已就绪(GALAXY_NATIVE_AUDIO=1),回合制语音走的是原生通路而非 "
                    "Whisper/TTS 桥。若要用本地服务跑双工,把 GALAXY_REALTIME_URL 指向它即可(本地端点免 key)。"
                )
            return None
        return cls(url=url, api_key=key, model=model, voice=voice, provider=provider)


# ── 协议适配:全部是纯函数,不碰网络,可完整单测 ────────────────────────────


class ProtocolAdapter:
    """provider 帧格式适配器。

    已实现:``OpenAIRealtimeAdapter``、``GeminiLiveAdapter``。新增 provider 时要在
    ``_ADAPTERS`` 里登记 —— 未登记的名字显式抛错,绝不静默退回默认实现。
    """

    name = "abstract"

    def session_update(self, cfg: DuplexSessionConfig) -> Dict[str, Any]:
        raise NotImplementedError

    def audio_frame(self, pcm16: bytes) -> Dict[str, Any]:
        raise NotImplementedError

    def text_frame(self, text: str) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def interrupt_frame(self) -> Dict[str, Any]:
        raise NotImplementedError

    def decode(self, msg: Dict[str, Any]) -> Optional[DuplexEvent]:
        raise NotImplementedError

    def headers(self, cfg: DuplexSessionConfig) -> Dict[str, str]:
        raise NotImplementedError


class OpenAIRealtimeAdapter(ProtocolAdapter):
    """OpenAI Realtime(``wss://api.openai.com/v1/realtime``)的帧格式。"""

    name = "openai_realtime"

    def headers(self, cfg: DuplexSessionConfig) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {cfg.api_key}",
            "OpenAI-Beta": "realtime=v1",
        }

    def session_update(self, cfg: DuplexSessionConfig) -> Dict[str, Any]:
        session: Dict[str, Any] = {
            "modalities": ["text", "audio"],
            "voice": cfg.voice,
            "input_audio_format": "pcm16",
            "output_audio_format": "pcm16",
            "input_audio_transcription": {"model": "whisper-1"},
            # 服务端 VAD:双工下回合边界由服务端判。本地不再"攒够 3 秒再转写"——
            # 那正是回合制延迟的来源。
            "turn_detection": {
                "type": "server_vad",
                "silence_duration_ms": int(cfg.silence_ms),
            },
        }
        if cfg.instructions:
            session["instructions"] = cfg.instructions
        return {"type": "session.update", "session": session}

    def audio_frame(self, pcm16: bytes) -> Dict[str, Any]:
        return {
            "type": "input_audio_buffer.append",
            "audio": base64.b64encode(pcm16).decode("ascii"),
        }

    def text_frame(self, text: str) -> List[Dict[str, Any]]:
        return [
            {
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": text}],
                },
            },
            {"type": "response.create"},
        ]

    def interrupt_frame(self) -> Dict[str, Any]:
        """双工下的 barge-in:让服务端**停止当前回复**,而不是本地掐断播放。

        回合制的 ``interrupt_speech()`` 只是停掉本地播放器,模型那边还在继续生成
        (token 照烧、上下文照涨)。双工下必须让服务端也停。
        """
        return {"type": "response.cancel"}

    _MAP = {
        "session.created": DuplexEventType.SESSION_OPEN,
        "session.updated": DuplexEventType.SESSION_OPEN,
        "input_audio_buffer.speech_started": DuplexEventType.USER_SPEECH_STARTED,
        "input_audio_buffer.speech_stopped": DuplexEventType.USER_SPEECH_STOPPED,
        "response.done": DuplexEventType.RESPONSE_DONE,
        "error": DuplexEventType.ERROR,
    }

    def decode(self, msg: Dict[str, Any]) -> Optional[DuplexEvent]:
        """把一帧服务端消息翻成 ``DuplexEvent``;不认识的帧返回 None(而不是报错)。

        provider 会不断加新事件类型,对未知帧报错会让会话动不动就断。未知帧只在
        debug 级别记一笔。
        """
        t = str(msg.get("type") or "")
        if not t:
            return None

        if t == "response.audio.delta":
            return DuplexEvent(DuplexEventType.ASSISTANT_AUDIO_DELTA, audio_b64=str(msg.get("delta") or ""), raw=msg)
        if t in ("response.text.delta", "response.audio_transcript.delta"):
            return DuplexEvent(DuplexEventType.ASSISTANT_TEXT_DELTA, text=str(msg.get("delta") or ""), raw=msg)
        if t == "conversation.item.input_audio_transcription.delta":
            return DuplexEvent(DuplexEventType.PARTIAL_TRANSCRIPT, text=str(msg.get("delta") or ""), raw=msg)
        if t == "conversation.item.input_audio_transcription.completed":
            return DuplexEvent(DuplexEventType.FINAL_TRANSCRIPT, text=str(msg.get("transcript") or ""), raw=msg)
        if t == "error":
            err = msg.get("error") or {}
            detail = err.get("message") if isinstance(err, dict) else str(err)
            return DuplexEvent(DuplexEventType.ERROR, error=str(detail or "unknown"), raw=msg)

        mapped = self._MAP.get(t)
        if mapped is not None:
            return DuplexEvent(mapped, raw=msg)
        logger.debug("双工会话:未识别的服务端帧类型 %s(已忽略)", t)
        return None


class GeminiLiveAdapter(ProtocolAdapter):
    """Gemini Live(``BidiGenerateContent``)的帧格式。

    与 OpenAI Realtime 的差别不只是字段名,是**结构不同**:

    - 配置不叫 ``session.update`` 而是连接后的**第一帧** ``setup``,且必须先发完它再发
      任何音频 —— 顺序错了服务端会直接断开;
    - 音频上行走 ``realtimeInput.mediaChunks[]``,每块带自己的 ``mimeType``(采样率写在
      mime 里,如 ``audio/pcm;rate=16000``),不是像 OpenAI 那样在 session 里统一声明;
    - 下行是 ``serverContent.modelTurn.parts[]`` 的**混合数组** —— 同一个 parts 里既可能
      是 ``inlineData``(音频)也可能是 ``text``,得逐个 part 分派,而不是一个 part 一种事件;
    - 回合边界由 ``serverContent.turnComplete`` / ``interrupted`` 标志给出,不是独立的
      事件类型。

    鉴权也不同:Gemini 走 URL 上的 ``?key=``,没有 Authorization 头。
    """

    name = "gemini_live"

    def headers(self, cfg: DuplexSessionConfig) -> Dict[str, str]:
        # key 在 URL query 里(见 from_env 组 URL 的地方),不走请求头
        return {}

    def session_update(self, cfg: DuplexSessionConfig) -> Dict[str, Any]:
        setup: Dict[str, Any] = {
            "model": f"models/{cfg.model}" if not cfg.model.startswith("models/") else cfg.model,
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": cfg.voice}}},
            },
        }
        if cfg.instructions:
            setup["systemInstruction"] = {"parts": [{"text": cfg.instructions}]}
        return {"setup": setup}

    def audio_frame(self, pcm16: bytes) -> Dict[str, Any]:
        return {
            "realtimeInput": {
                "mediaChunks": [
                    {
                        "mimeType": "audio/pcm;rate=16000",
                        "data": base64.b64encode(pcm16).decode("ascii"),
                    }
                ]
            }
        }

    def text_frame(self, text: str) -> List[Dict[str, Any]]:
        # Gemini 一帧即可:clientContent 带 turnComplete 就等于"说完了,该你了",
        # 不需要 OpenAI 那种 create item + response.create 的两步。
        return [
            {
                "clientContent": {
                    "turns": [{"role": "user", "parts": [{"text": text}]}],
                    "turnComplete": True,
                }
            }
        ]

    def interrupt_frame(self) -> Dict[str, Any]:
        """Gemini 没有显式的 cancel 帧 —— 它靠**新的用户输入**打断当前回合。

        发一个 ``turnComplete`` 的空 turn 即表示"我要说话了",服务端据此中止当前生成。
        这与 OpenAI 的 ``response.cancel`` 语义等价,但机制不同,不能照抄。
        """
        return {"clientContent": {"turns": [], "turnComplete": True}}

    def decode(self, msg: Dict[str, Any]) -> Optional[DuplexEvent]:
        if msg.get("setupComplete") is not None:
            return DuplexEvent(DuplexEventType.SESSION_OPEN, raw=msg)

        err = msg.get("error")
        if err:
            detail = err.get("message") if isinstance(err, dict) else str(err)
            return DuplexEvent(DuplexEventType.ERROR, error=str(detail or "unknown"), raw=msg)

        sc = msg.get("serverContent")
        if not isinstance(sc, dict):
            logger.debug("Gemini Live:未识别的服务端帧(已忽略): %s", list(msg)[:3])
            return None

        # 被用户打断 —— 对齐成"用户开口"
        if sc.get("interrupted"):
            return DuplexEvent(DuplexEventType.USER_SPEECH_STARTED, raw=msg)
        if sc.get("turnComplete"):
            return DuplexEvent(DuplexEventType.RESPONSE_DONE, raw=msg)

        turn = sc.get("modelTurn")
        if isinstance(turn, dict):
            # parts 是混合数组:音频优先(它才是要立刻播的),其次文本
            for part in turn.get("parts") or []:
                if not isinstance(part, dict):
                    continue
                inline = part.get("inlineData")
                if isinstance(inline, dict) and inline.get("data"):
                    return DuplexEvent(
                        DuplexEventType.ASSISTANT_AUDIO_DELTA,
                        audio_b64=str(inline.get("data")),
                        raw=msg,
                    )
            for part in turn.get("parts") or []:
                if isinstance(part, dict) and part.get("text"):
                    return DuplexEvent(DuplexEventType.ASSISTANT_TEXT_DELTA, text=str(part["text"]), raw=msg)

        # 用户语音的转写(Gemini 把它放在 inputTranscription 里)
        it = sc.get("inputTranscription")
        if isinstance(it, dict) and it.get("text"):
            return DuplexEvent(DuplexEventType.FINAL_TRANSCRIPT, text=str(it["text"]), raw=msg)

        logger.debug("Gemini Live:serverContent 里没有可识别的内容(已忽略)")
        return None


#: 已实现的适配器。新增 provider 时在这里登记 —— 未登记的显式抛错,
#: **绝不**静默退回某个默认实现(那会让用户以为在用 A、实际发的是 B 的帧)。
_ADAPTERS = {
    OpenAIRealtimeAdapter.name: OpenAIRealtimeAdapter,
    GeminiLiveAdapter.name: GeminiLiveAdapter,
}


def get_adapter(name: str = "openai_realtime") -> ProtocolAdapter:
    cls = _ADAPTERS.get(name)
    if cls is None:
        raise ValueError(f"未实现的双工 provider 适配器: {name}(已实现: {', '.join(sorted(_ADAPTERS))})")
    return cls()


# ── 会话 ─────────────────────────────────────────────────────────────────────


class DuplexSession:
    """一条持续开着的双工语音会话。

    用法::

        sess = DuplexSession(cfg)
        await sess.connect()
        await sess.send_audio(pcm16_bytes)      # 可以一直调,不阻塞下行
        async for ev in sess.events():
            ...
        await sess.close()

    上行与下行是**两个独立的协程**:下行有一个常驻读循环把帧解码后塞进队列,上行直接
    发送。这样"边说边听"在实现上才真的成立 —— 如果上行要等下行读完一帧,那还是回合制。
    """

    def __init__(self, config: DuplexSessionConfig, adapter: Optional[ProtocolAdapter] = None) -> None:
        self.config = config
        # 适配器按 config.provider 选 —— 写死默认值会让 GALAXY_REALTIME_PROVIDER
        # 形同虚设:用户以为在用 Gemini,实际发的是 OpenAI 的帧。
        self.adapter = adapter or get_adapter(config.provider)
        self._ws: Any = None
        self._reader: Optional[asyncio.Task] = None
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=_EVENT_QUEUE_MAX)
        self._connected = False
        self._closing = False
        # 观测
        self.frames_sent = 0
        self.frames_received = 0
        self.events_emitted = 0
        self.events_dropped = 0
        self.bytes_uplinked = 0
        self.last_error = ""

    # ── 生命周期 ──────────────────────────────────────────────────────────

    async def connect(self) -> bool:
        """建连并下发会话配置。返回是否成功;失败时如实记录原因,不抛出。"""
        if self._connected:
            return True
        try:
            import websockets
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"websockets_missing: {exc}"
            logger.warning("双工会话不可用(缺 websockets): %s", exc)
            return False
        try:
            self._ws = await websockets.connect(
                self.config.url,
                additional_headers=self.adapter.headers(self.config),
                max_size=16 * 1024 * 1024,
            )
            await self._send_json(self.adapter.session_update(self.config))
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"connect_failed: {exc}"
            logger.warning("双工会话建连失败,退回回合制语音: %s", exc)
            await self._hard_close()
            return False

        self._connected = True
        self._closing = False
        self._reader = asyncio.ensure_future(self._read_loop())
        _BACKGROUND_TASKS.add(self._reader)
        self._reader.add_done_callback(_BACKGROUND_TASKS.discard)
        logger.info("双工语音会话已建立(%s, model=%s)", self.adapter.name, self.config.model)
        return True

    async def close(self) -> None:
        """关闭会话。幂等、永不抛出。"""
        self._closing = True
        self._connected = False
        reader, self._reader = self._reader, None
        if reader is not None:
            reader.cancel()
            try:
                await reader
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        await self._hard_close()
        await self._emit(DuplexEvent(DuplexEventType.SESSION_CLOSED))

    async def _hard_close(self) -> None:
        ws, self._ws = self._ws, None
        if ws is None:
            return
        try:
            await ws.close()
        except Exception as exc:  # noqa: BLE001
            logger.debug("关闭双工连接失败(忽略): %s", exc)

    @property
    def connected(self) -> bool:
        return self._connected

    # ── 上行 ──────────────────────────────────────────────────────────────

    async def _send_json(self, payload: Dict[str, Any]) -> bool:
        ws = self._ws
        if ws is None:
            return False
        try:
            await ws.send(json.dumps(payload, ensure_ascii=False))
            self.frames_sent += 1
            return True
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"send_failed: {exc}"
            logger.debug("双工上行发送失败: %s", exc)
            return False

    async def send_audio(self, pcm16: bytes) -> bool:
        """上行一块 16-bit PCM。

        调用方**应当**送已经过 AEC 的音频:双工下这些字节会实时进模型,不做回声消除
        等于让模型一直听见自己在说话(比回合制更严重 —— 回合制下那段音频最终会被丢掉)。
        """
        if not pcm16 or not self._connected:
            return False
        ok = await self._send_json(self.adapter.audio_frame(pcm16))
        if ok:
            self.bytes_uplinked += len(pcm16)
        return ok

    async def send_text(self, text: str) -> bool:
        """上行一段文字(供面板/键盘输入与语音共用同一条会话)。"""
        if not text or not self._connected:
            return False
        ok = True
        for frame in self.adapter.text_frame(text):
            ok = await self._send_json(frame) and ok
        return ok

    async def interrupt(self) -> bool:
        """barge-in:让**服务端**停止当前回复。

        与回合制的 ``interrupt_speech()`` 有本质区别:那个只停本地播放器,模型那边还在
        继续生成(token 照烧、上下文照涨)。双工下必须让服务端也停。
        """
        if not self._connected:
            return False
        return await self._send_json(self.adapter.interrupt_frame())

    # ── 下行 ──────────────────────────────────────────────────────────────

    async def _emit(self, ev: DuplexEvent) -> None:
        """把事件塞进队列。满了丢**最旧**的 —— 过期音频块没有价值,而阻塞上行会毁掉
        实时性。丢弃有计数,不静默。"""
        try:
            self._queue.put_nowait(ev)
        except asyncio.QueueFull:
            try:
                self._queue.get_nowait()
                self.events_dropped += 1
                self._queue.put_nowait(ev)
            except Exception:  # noqa: BLE001
                self.events_dropped += 1
                return
        self.events_emitted += 1

    async def _read_loop(self) -> None:
        """常驻下行读循环:收帧 → 解码 → 入队。与上行完全解耦。"""
        ws = self._ws
        if ws is None:
            return
        try:
            async for raw in ws:
                self.frames_received += 1
                try:
                    msg = json.loads(raw)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("双工下行帧不是合法 JSON(忽略): %s", exc)
                    continue
                if not isinstance(msg, dict):
                    continue
                ev = self.adapter.decode(msg)
                if ev is None:
                    continue
                if ev.type is DuplexEventType.ERROR:
                    self.last_error = ev.error
                    logger.warning("双工会话服务端报错: %s", ev.error)
                # 把 AI 说出口的文字登记进反自激励门 —— 双工下同样需要:AEC 消不掉
                # 非线性残余回声,残余转写出来后仍要能判出"这是我自己说的"。
                if ev.type is DuplexEventType.ASSISTANT_TEXT_DELTA and ev.text:
                    self._note_spoken(ev.text)
                await self._emit(ev)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            if not self._closing:
                self.last_error = f"read_loop: {exc}"
                logger.warning("双工下行读循环异常结束: %s", exc)
        finally:
            self._connected = False
            if not self._closing:
                # 服务端**正常**关闭连接时,上面的 async for 会安静地结束、不抛异常。
                # 若这里什么都不做,后果是完全静默的:上行的 send_audio 从此每次返回
                # False(没人看返回值),用户的声音再也传不上去;而下行消费方还在
                # await 一个永远不会再有事件的队列上,任务就此挂死。症状是"助手突然
                # 不理人了",日志里一点线索都没有。
                #
                # 所以:升 WARNING,并**补发** SESSION_CLOSED —— 消费方靠它退出循环。
                self.last_error = self.last_error or "server_closed_connection"
                logger.warning(
                    "双工会话已断开(服务端关闭连接),语音上行已失效。"
                    "已发出 SESSION_CLOSED;调用方应重建会话或退回回合制。"
                )
                try:
                    await self._emit(DuplexEvent(DuplexEventType.SESSION_CLOSED))
                except Exception as exc:  # noqa: BLE001
                    logger.debug("补发 SESSION_CLOSED 失败(忽略): %s", exc)

    @staticmethod
    def _note_spoken(text: str) -> None:
        try:
            from core.voice_echo_guard import note_utterance

            note_utterance(text)
        except Exception as exc:  # noqa: BLE001
            logger.debug("双工:登记已说出口文本失败(非致命): %s", exc)

    async def events(self) -> AsyncIterator[DuplexEvent]:
        """异步迭代下行事件,直到会话关闭。"""
        while True:
            ev = await self._queue.get()
            yield ev
            if ev.type is DuplexEventType.SESSION_CLOSED:
                return

    async def next_event(self, timeout: Optional[float] = None) -> Optional[DuplexEvent]:
        """取一条事件;超时返回 None。供不想用异步迭代的调用方。"""
        try:
            if timeout is None:
                return await self._queue.get()
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    # ── 观测 ──────────────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        return {
            "connected": self._connected,
            "adapter": self.adapter.name,
            "model": self.config.model,
            "frames_sent": self.frames_sent,
            "frames_received": self.frames_received,
            "events_emitted": self.events_emitted,
            "events_dropped": self.events_dropped,
            "bytes_uplinked": self.bytes_uplinked,
            "queue_depth": self._queue.qsize(),
            "last_error": self.last_error or None,
        }


async def open_duplex_session(
    config: Optional[DuplexSessionConfig] = None,
    adapter: Optional[ProtocolAdapter] = None,
) -> Optional[DuplexSession]:
    """按环境配置建立一条双工会话;不可用时返回 None(调用方退回回合制)。

    返回 None 的每种情形都有日志:开关没开、缺 key、建连失败 —— 否则"开了开关却没生效"
    完全无从排查。
    """
    if config is None:
        if not duplex_enabled():
            logger.debug("双工语音未启用(GALAXY_VOICE_DUPLEX 未开),走回合制链路")
            return None
        config = DuplexSessionConfig.from_env()
        if config is None:
            return None
    sess = DuplexSession(config, adapter=adapter)
    if not await sess.connect():
        return None
    return sess


def pcm16_from_float(samples: Any) -> bytes:
    """float32/float64 [-1,1] → 16-bit PCM 字节(上行格式)。

    限幅后再转,不做自动增益:溢出翻转会变成刺耳爆音,而且会污染模型的听觉输入。
    """
    import numpy as np

    arr = np.asarray(samples, dtype=np.float64).reshape(-1)
    if arr.size == 0:
        return b""
    return (np.clip(arr, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


def float_from_pcm16(data: bytes) -> Any:
    """16-bit PCM 字节 → float32 [-1,1](下行播放/分析用)。"""
    import numpy as np

    if not data:
        return np.zeros(0, dtype=np.float32)
    return (np.frombuffer(data, dtype="<i2").astype(np.float32) / 32767.0).astype(np.float32)


#: 供 VoiceLoop 在双工模式下把上行音频接过去的回调类型
UplinkHook = Callable[[bytes], Any]


#: 下行播放缓冲上限(秒)。满了丢**最旧**的:过期音频没有价值,而让 play() 等待
#: 会把事件循环连带上行一起卡住。
_PLAYER_BUFFER_SEC = 2.0

#: ducking 的增益爬坡时长(毫秒)。瞬间切换会有爆音,50ms 是听感上"干净且够快"的常用值。
_DUCK_RAMP_MS = 50.0


class PcmPlayer:
    """下行原始 PCM 的播放器(回调驱动,``play()`` 绝不阻塞)。

    为什么不能用 ``OutputStream.write()``
    -------------------------------------
    双工下行是**连续的 PCM 流**,不是一个个音频文件,所以现有 TTS 引擎那套
    ``_play_audio(path)`` 用不上 —— 为每个 20ms 的音频块写一个临时文件再播,延迟和
    IO 开销都不可接受。

    但直接用 ``stream.write()`` 也不行:按 sounddevice 的契约它**会阻塞**到所有帧都写进
    设备缓冲为止。而 ``play()`` 是从 ``_duplex_downlink`` 里调的,跑在事件循环上 ——
    一阻塞,同一个循环上的**上行**也跟着停。那就等于用一个"实时"播放器把双工性质亲手
    毁掉:模型说话时用户的声音传不上去,退化成半双工。

    所以改成**回调驱动**:``sounddevice`` 的音频线程主动来取,``play()`` 只是往一个有界
    环形缓冲里追加,纯内存操作、不等待任何人。这也是音频输出的标准做法。

    没有 sounddevice / 没有输出设备时**如实不可用**并记一次 WARNING,不静默假装在播 ——
    "以为在说话其实一点声音都没有"是最难排查的一类症状。
    """

    def __init__(self, sample_rate: int = 16000) -> None:
        self.sample_rate = int(sample_rate)
        self._stream: Any = None
        self._unavailable_reason = ""
        self._lock = threading.Lock()
        self._buf: Any = None  # numpy 1-D 待播样本
        self._np: Any = None
        self.blocks_played = 0
        self.blocks_dropped = 0
        self.samples_underrun = 0  # 缓冲空、只能输出静音的样本数(可听为卡顿)
        # ── ducking(压音)──
        self._gain = 1.0  # 当前增益
        self._target_gain = 1.0  # 目标增益
        self.duck_events = 0

    @property
    def _max_samples(self) -> int:
        return int(_PLAYER_BUFFER_SEC * self.sample_rate)

    @property
    def _ramp_samples(self) -> int:
        """增益爬坡长度(样本)。**不能瞬间切换** —— 幅度突变在听感上是"啪"的一声爆音。"""
        return max(1, int(self.sample_rate * _DUCK_RAMP_MS / 1000.0))

    # ── ducking ───────────────────────────────────────────────────────────

    def duck(self, gain: Optional[float] = None) -> None:
        """压低音量(不停止播放)。用户开口时用,比整段掐断温和得多。"""
        g = duck_gain() if gain is None else float(gain)
        with self._lock:
            if self._target_gain != g:
                self.duck_events += 1
            self._target_gain = max(0.0, min(1.0, g))

    def unduck(self) -> None:
        """恢复原音量。"""
        with self._lock:
            self._target_gain = 1.0

    @property
    def ducked(self) -> bool:
        with self._lock:
            return self._target_gain < 1.0

    def start(self) -> bool:
        if self._stream is not None:
            return True
        try:
            import numpy as np
            import sounddevice as sd

            self._np = np
            self._buf = np.zeros(0, dtype=np.float32)

            def _cb(outdata, frames, _time_info, status) -> None:  # noqa: ANN001
                # 音频线程:只调 _fill(取数 + 增益 + 补静音),绝不做 IO / 日志 / 加重锁
                if status:
                    pass
                self._fill(outdata, frames)

            self._stream = sd.OutputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                callback=_cb,
            )
            self._stream.start()
            logger.info("双工下行播放器已启动(回调驱动, sr=%d)", self.sample_rate)
            return True
        except Exception as exc:  # noqa: BLE001
            self._unavailable_reason = str(exc)
            logger.warning("双工下行播放器不可用(模型的回复将听不到): %s", exc)
            self._stream = None
            return False

    def _fill(self, outdata: Any, frames: int) -> None:
        """填一个输出块:取数 → 施加增益爬坡 → 不足补静音。

        抽成方法(而不是留在 ``start()`` 的闭包里)是为了**让测试驱动真正的这段代码**。
        本环境没有音频设备,若把逻辑埋在只有 ``sd.OutputStream`` 才会调用的闭包里,测试
        就只能另写一份等价实现去测 —— 那测的是副本不是本体,两边一旦漂移就完全测不出来。
        """
        np = self._np
        with self._lock:
            have = min(frames, self._buf.size)
            if have:
                outdata[:have, 0] = self._buf[:have]
                self._buf = self._buf[have:]
            if have < frames:
                outdata[have:, 0] = 0.0
                self.samples_underrun += frames - have

            # 增益爬坡:本块最多向目标靠拢 frames/ramp_n,再在块内线性插值。
            # 一步切到目标会产生幅度突变,听感上就是"啪"的一声爆音。
            g0 = self._gain
            delta = self._target_gain - g0
            max_delta = frames / self._ramp_samples
            g1 = self._target_gain if abs(delta) <= max_delta else g0 + (max_delta if delta > 0 else -max_delta)
            if have and not (g0 == 1.0 and g1 == 1.0):
                outdata[:have, 0] *= np.linspace(g0, g1, have, endpoint=False, dtype=np.float32)
            self._gain = g1

    def play(self, pcm16: bytes) -> bool:
        """把一块 PCM 追加到播放缓冲。**不阻塞**、永不抛出。"""
        if not pcm16:
            return False
        if self._stream is None or self._np is None:
            self.blocks_dropped += 1
            return False
        try:
            np = self._np
            samples = float_from_pcm16(pcm16)
            with self._lock:
                self._buf = np.concatenate((self._buf, samples))
                # 有界:生产快于消费时丢最旧的,而不是让 play() 等下去
                extra = self._buf.size - self._max_samples
                if extra > 0:
                    self._buf = self._buf[extra:]
                    self.blocks_dropped += 1
            self.blocks_played += 1
            return True
        except Exception as exc:  # noqa: BLE001
            self.blocks_dropped += 1
            logger.debug("双工下行入缓冲失败(丢弃本块): %s", exc)
            return False

    def stop(self) -> None:
        stream, self._stream = self._stream, None
        with self._lock:
            if self._np is not None:
                self._buf = self._np.zeros(0, dtype=self._np.float32)
        if stream is None:
            return
        try:
            stream.stop()
            stream.close()
        except Exception as exc:  # noqa: BLE001
            logger.debug("关闭双工播放器失败(忽略): %s", exc)

    def status(self) -> Dict[str, Any]:
        with self._lock:
            buffered = int(self._buf.size) if self._buf is not None else 0
            gain = round(self._gain, 4)
            target = round(self._target_gain, 4)
        return {
            "available": self._stream is not None,
            "unavailable_reason": self._unavailable_reason or None,
            "blocks_played": self.blocks_played,
            "blocks_dropped": self.blocks_dropped,
            "buffered_samples": buffered,
            "samples_underrun": self.samples_underrun,
            # ducking 的实时状态:压音是"听得见但不明显"的行为,不摊出来就无从判断
            # "到底压了没有""是不是忘了恢复"
            "gain": gain,
            "target_gain": target,
            "ducked": target < 1.0,
            "duck_events": self.duck_events,
        }
