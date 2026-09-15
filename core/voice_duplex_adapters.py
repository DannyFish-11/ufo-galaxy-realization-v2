"""core/voice_duplex_adapters.py —— 各家双工 provider 的帧格式适配

从 ``core/voice_duplex_session.py`` 拆出来的第二件独立的事(第一件是
``voice_duplex_capability.py``)。理由和上次一样,而且这次是被文件大小门禁逼出来的:
加了阶跃适配器与视频上行之后,那个文件从 1229 行涨到 1379 行,越过了基线。

**拆这一刀是有依据的,不是随便找个地方切。** 被拆走的这一整段原本就顶着一句
「全部是纯函数,不碰网络,可完整单测」—— 它和会话那半边的关注点本来就不同:
这边只回答"这一帧长什么样",那边回答"连接怎么维持、事件怎么派发"。

为什么不是把基线调高
--------------------
``scripts/check_file_complexity.py`` 给的两条出路是「拆分」或「``--update-baseline``
重记基线」。这个文件上一次涨到基线边上时,选的就是拆(拆出了
``voice_duplex_capability.py``,那个模块的 docstring 里写着"顺便让那个文件回到
复杂度基线内")。同一个文件、同一种涨法,没有理由这次改用抬基线 —— 那道门拦的
正是"每次多一点点"。

依赖方向
--------
本模块**不在运行期 import ``voice_duplex_session``**。适配器只读 ``DuplexSessionConfig``
的几个字段,所以那个类型只在 ``TYPE_CHECKING`` 下引入。反向(session → adapters)是
真的运行期依赖。这样才没有循环导入。

兼容
----
``DuplexEventType`` / ``DuplexEvent`` / ``ProtocolAdapter`` / 三个适配器 /
``get_adapter`` 仍然可以从 ``core.voice_duplex_session`` 导入 —— 那边做了再导出。
仓内既有的 import 一行都不用改。
"""

from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:  # pragma: no cover - 仅用于类型标注,运行期不导入(否则循环)
    from core.voice_duplex_session import DuplexSessionConfig

logger = logging.getLogger("Galaxy.VoiceDuplexAdapters")

__all__ = [
    "DuplexEvent",
    "DuplexEventType",
    "GeminiLiveAdapter",
    "OpenAIRealtimeAdapter",
    "ProtocolAdapter",
    "StepRealtimeAdapter",
    "get_adapter",
]


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


# ── 协议适配:全部是纯函数,不碰网络,可完整单测 ────────────────────────────


class ProtocolAdapter:
    """provider 帧格式适配器。

    已实现:``OpenAIRealtimeAdapter``、``GeminiLiveAdapter``、``StepRealtimeAdapter``。
    新增 provider 时要在 ``_ADAPTERS`` 里登记 —— 未登记的名字显式抛错,绝不静默退回
    默认实现。
    """

    name = "abstract"

    def session_update(self, cfg: DuplexSessionConfig) -> Dict[str, Any]:
        raise NotImplementedError

    def audio_frame(self, pcm16: bytes) -> Dict[str, Any]:
        raise NotImplementedError

    def video_frame(self, jpeg: bytes, mime: str = "image/jpeg") -> Optional[Dict[str, Any]]:
        """视频上行一帧。**返回 None 表示这家没有视频上行**,不是"出错了"。

        为什么默认返回 None 而不是 ``raise NotImplementedError``:各家双工接口在
        "收不收视频"这件事上真的不一样,而调用方(设备端摄像头)是**同一条**。
        让它变成一个可以问的事实(``supports_video_uplink()``),调用方就能在开采集前
        先问一句;抛异常则会把"这家不支持"和"这帧发失败了"混成同一种现象。
        """
        return None

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

    def video_frame(self, jpeg: bytes, mime: str = "image/jpeg") -> Optional[Dict[str, Any]]:
        """视频上行:和音频走**同一条** ``realtimeInput.mediaChunks[]``,只是 mime 不同。

        这正是 Gemini Live 那套"每块自带 mimeType"的设计换来的好处 —— 视频不需要另开
        通道、也不需要改 setup,塞一块 ``image/jpeg`` 进去就行。

        帧率由**调用方**控制。这里不做节流:节流要看的是采集侧的实际负载与配额,
        在协议适配器里拍一个数字,等于把一个产品决定藏进帧格式层。
        """
        return {
            "realtimeInput": {
                "mediaChunks": [
                    {
                        "mimeType": mime,
                        "data": base64.b64encode(jpeg).decode("ascii"),
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


class StepRealtimeAdapter(OpenAIRealtimeAdapter):
    """阶跃星辰(StepFun)Realtime 的帧格式。

    **为什么是继承而不是新写一份。** 阶跃这条 WS 面与 OpenAI Realtime 同构 ——
    官方的 Step-Realtime-Console 用的就是一份改过的 OpenAI SDK,端点形式也一样
    (``wss://api.stepfun.com/v1/realtime?model=<id>``)。既然帧格式相同,再抄一份
    ``session.update`` / ``input_audio_buffer.append`` / ``response.audio.delta``
    的映射,得到的是两份会各自漂移的实现。真正不同的只有下面这三处,就只改这三处。

    一、鉴权头没有 ``OpenAI-Beta``。那个头是 OpenAI 自家的 beta 标记,发给别家没有意义。

    二、``voice`` **必填**。官方文档把它列为必需参数(示例值 ``qingchunshaonv``、
    ``wenrounansheng``)。默认值从 registry 的 ``default_realtime_voice`` 取,
    ``from_env`` 保证它不会是空串。

    三、**不发 ``input_audio_transcription``**。OpenAI 那份在这里钉的是
    ``{"model": "whisper-1"}`` —— whisper-1 是 OpenAI 自己的模型名,阶跃认不认它我
    没有依据。往一个别家的 session 里塞一个我没核实过的模型名,失败方向是坏的:
    要么整个 session.update 被拒、要么被静默忽略,而**上行转写本来就不是双工的必需品**
    (回合边界由服务端 VAD 判,``conversation.item.input_audio_transcription.*``
    这一路只是给字幕用的)。所以宁可不要这项,也不要拿它去赌。

    ## 没核实到的部分,写在这里而不是假装知道

    这次能打开的一手来源只有官方 ``Step-Realtime-Console`` 仓库;
    ``platform.stepfun.com`` / ``platform.stepfun.ai`` / arxiv 在本环境都被出网代理
    挡住了。所以:

    * **事件名**没有逐条对照过官方文档 —— 是从"用的是改过的 OpenAI SDK"推的。
      若阶跃某个事件名不同,表现是 ``decode()`` 把它当未知帧忽略(debug 一行),
      会话不会断 —— 这个失败方向是安全的(见 ``OpenAIRealtimeAdapter.decode``)。
    * **默认型号 id**(``stepaudio-3-realtime-preview``)取自第三方仓库。
      连不上时是建连处的明确报错,不会静默换成别的型号。
    """

    name = "step_realtime"

    def headers(self, cfg: DuplexSessionConfig) -> Dict[str, str]:
        return {"Authorization": f"Bearer {cfg.api_key}"}

    def session_update(self, cfg: DuplexSessionConfig) -> Dict[str, Any]:
        frame = super().session_update(cfg)
        session = frame["session"]
        session.pop("input_audio_transcription", None)  # 见类 docstring 第三条
        if not session.get("voice"):
            # voice 必填。走到这里说明 cfg.voice 是空的 —— 与其发一个必然被拒的帧,
            # 不如在这里就说清楚缺什么。
            raise ValueError(
                "阶跃 realtime 要求必须指定 voice(如 qingchunshaonv / wenrounansheng);"
                "设 GALAXY_REALTIME_VOICE,或检查 PROVIDER_REGISTRY 里 step 的 "
                "default_realtime_voice"
            )
        return frame


#: 已实现的适配器。新增 provider 时在这里登记 —— 未登记的显式抛错,
#: **绝不**静默退回某个默认实现(那会让用户以为在用 A、实际发的是 B 的帧)。
_ADAPTERS = {
    OpenAIRealtimeAdapter.name: OpenAIRealtimeAdapter,
    GeminiLiveAdapter.name: GeminiLiveAdapter,
    StepRealtimeAdapter.name: StepRealtimeAdapter,
}


def get_adapter(name: str = "openai_realtime") -> ProtocolAdapter:
    cls = _ADAPTERS.get(name)
    if cls is None:
        raise ValueError(f"未实现的双工 provider 适配器: {name}(已实现: {', '.join(sorted(_ADAPTERS))})")
    return cls()
