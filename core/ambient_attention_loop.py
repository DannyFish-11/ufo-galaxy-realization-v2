"""core/ambient_attention_loop.py — 常驻注意力循环（自发在场）
==============================================================

设计哲学（见项目总体设计定稿）
------------------------------
三态里的 SILENT 不是"睡着",而是"在场但不表达"——眼睛耳朵持续开着,只是
不说话。系统此前的唯一缺陷是:一切都由对话驱动,用户不开口,持续采集的帧
就躺在 ``DesktopPerceptionStore`` 缓存里没人看。本模块补上设计承诺却缺失的
那个器官——**自发注意力**:给 SILENT→LIMINAL 一个由感知自身驱动的入口。

架构（自发注意力的通用形态,与具体模型无关）::

    持续感知(已有,不新建采集)
       │  DesktopPerceptionStore（Electron 每 2s 推帧/音频）
       ▼
    门控层(零模型开销): 帧差检测 + 音频新鲜度 + 冷却 + 场景去重
       │  画面没变 / 冷却期内 → 这一拍免费跳过,不惊动模型
       ▼
    决策 tick(注意力头): 帧+音频+最近记忆 → 主脑三选一(严格格式)
       │  决策脑可插拔(AmbientDecider);默认走系统统一 LLM 路由,
       │  与你在面板/克隆界面选好的主脑一致 —— 循环本身模型无关。
       ▼
    三选一路由:
       SPEAK    → speak_response（与 handle_request 同一条 canonical TTS 路径）
       DELEGATE → handle_request(source="ambient") 正门 → LIMINAL 执行分支
                  （OpenClawd 内部可调用 Node_107 工具链）
       SILENT   → 只记录理由,不打扰（无请求进门,主体留在 SILENT）
       ▼
    观察+决策写回记忆（选择性摄入,不全存）:
       工作记忆(WorkingMemory, ambient 专用会话) —— 喂面板/下次决策/对话注入
       终身记忆(UnifiedMemory, 仅 salient) —— 过目不忘

工程纪律
--------
1. 不新建采集,只消费 ``DesktopPerceptionStore``。
2. 不新建记忆层,只接线已有 ``WorkingMemory`` / ``UnifiedMemory``。
3. SILENT = 无请求进门；SPEAK 用 canonical TTS；DELEGATE 走 ``handle_request`` 正门。
4. 循环不选模型,决策脑走系统统一路由。
5. 默认关闭(``GALAXY_AMBIENT_LOOP``),隐私跟随现有感知授权,不破坏既有行为。
6. 冷却 + 场景去重兜住"话痨";全路径优雅降级,任何子步失败都不影响主流程。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol

logger = logging.getLogger("Galaxy.Ambient")

# 默认参数（均可由环境变量覆盖）
_DEFAULT_INTERVAL_S = 2.0  # 循环节拍
_DEFAULT_COOLDOWN_S = 20.0  # 开口/委托后的冷却
_DEFAULT_DIFF_THRESHOLD = 0.06  # 帧差阈值（0..1，归一化平均像素差）
_AMBIENT_SESSION = "ambient"  # 工作记忆专用会话
_RECENT_MEMORY_N = 5  # 每次决策带上的最近记忆条数


# ---------------------------------------------------------------------------
# 三选一决策
# ---------------------------------------------------------------------------
class AmbientAction(str, Enum):
    """注意力头的三选一——即"这一拍主体该处于哪个存在状态"的具象化。"""

    SPEAK = "speak"  # 值得主动开口 → MANIFEST
    SILENT = "silent"  # 看到了但不打扰 → 留在 SILENT（应是绝大多数情况）
    DELEGATE = "delegate"  # 该派活儿而非嘴上说 → LIMINAL 执行分支


@dataclass
class AmbientDecision:
    """一次注意力决策的结构化结果。"""

    action: AmbientAction
    rationale: str = ""  # 为什么这么决定（记录 + 面板显示）
    utterance: str = ""  # SPEAK 时要说的话
    task: str = ""  # DELEGATE 时要委托的任务
    salient: bool = False  # 是否值得写入终身记忆

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action.value,
            "rationale": self.rationale,
            "utterance": self.utterance,
            "task": self.task,
            "salient": self.salient,
        }


@dataclass
class AmbientObservation:
    """一拍观察的输入快照。

    frame_b64 是【主帧】(屏幕优先、否则摄像头)——供门控/记忆/路由沿用,保持兼容。
    screen_b64 / camera_b64 是【分路】原始帧:决策脑同时把两路都发给模型(融合看),
    修复"在场循环每拍只看一路视觉"的缺陷。两者可同时存在(屏幕+摄像头都在采)。
    """

    frame_b64: Optional[str] = None
    frame_mime: str = "image/jpeg"
    frame_source: str = ""
    screen_b64: Optional[str] = None
    screen_mime: str = "image/jpeg"
    camera_b64: Optional[str] = None
    camera_mime: str = "image/jpeg"
    audio_b64: Optional[str] = None
    audio_mime: str = "audio/webm"
    audio_transcript: Optional[str] = None  # 听:能力驱动桥接转写(asr_bridge)后的文字
    screen_meta: Optional[Dict[str, Any]] = None
    recent_memory: List[str] = field(default_factory=list)
    #: 手表报上来的「现在能不能打扰他」(见 core/interruptibility_registry)。
    #: 空串 = 没有可用证据 —— 注意「没有证据」既不构成放行、也不构成阻拦,
    #: 此时循环的行为与接手表之前完全一致。
    interruptibility_note: str = ""


# ---------------------------------------------------------------------------
# 决策脑接口（可插拔：档位 A 用 Gemma 系主脑；档位 B 换 MiniCPM-o 全模态，循环不改）
# ---------------------------------------------------------------------------
class AmbientDecider(Protocol):
    async def decide(self, obs: AmbientObservation) -> AmbientDecision:  # pragma: no cover - 协议
        ...


# 严格三选一输出格式：第一行必须是三个动作词之一，后续行给理由/内容。
_DECISION_FORMAT = (
    "你是一个桌面 AI 的『注意力头』。你持续在场地看着用户的摄像头/屏幕、听着麦克风，"
    "但你的唯一任务不是描述画面，而是判断【此刻该不该主动介入】。\n"
    "严格从以下三选一，且第一行只能是这三个词之一：\n"
    "SPEAK   —— 此刻确实值得你主动开口（如用户明显卡住、出现你被托付留意的事、用户回到座位）。\n"
    "SILENT  —— 看到了但不值得打扰（用户在正常操作、只是光线/无关变化）。这应是绝大多数情况的答案。\n"
    "DELEGATE—— 不该嘴上说，而该派一个后台任务（如反复报错需查日志、需要 OCR 提取屏幕文字）。\n"
    "输出格式（严格）：\n"
    "第一行：SPEAK 或 SILENT 或 DELEGATE\n"
    "第二行起：理由（一句话）。若为 SPEAK，另起一行以『说：』开头写出你要说的话；"
    "若为 DELEGATE，另起一行以『派：』开头写出要委托的任务。\n"
    "克制是美德——拿不准就选 SILENT。"
)


class LLMRouterDecider:
    """默认决策脑：走系统统一 LLM 路由（与面板/克隆界面选好的主脑一致）。

    多模态:构造 OpenAI 风格的 image_url content part;路由的 Ollama 适配器会
    自动转成 Ollama 的 images 字段(见 multi_llm_router._to_ollama_messages),
    因此对 OpenAI 兼容后端与本地 Ollama 后端都成立——真正模型无关。
    图像发送失败时优雅降级为纯文本(带上屏幕结构化上下文)。
    """

    def __init__(self, router: Optional[Any] = None) -> None:
        self._router = router

    def _get_router(self):
        if self._router is None:
            from core.multi_llm_router import get_llm_router

            self._router = get_llm_router()
        return self._router

    @staticmethod
    def _image_part(image_b64: str, mime: str) -> Dict[str, Any]:
        url = image_b64 if image_b64.startswith("data:") else f"data:{mime or 'image/jpeg'};base64,{image_b64}"
        return {"type": "image_url", "image_url": {"url": url}}

    def _build_messages(self, obs: AmbientObservation) -> List[Dict[str, Any]]:
        text_lines = [_DECISION_FORMAT, ""]
        if obs.recent_memory:
            text_lines.append("最近你注意到的（供连续性参考）：")
            text_lines.extend(f"- {m}" for m in obs.recent_memory[-_RECENT_MEMORY_N:])
            text_lines.append("")
        if obs.screen_meta:
            title = obs.screen_meta.get("window_title") or obs.screen_meta.get("title")
            if title:
                text_lines.append(f"当前活动窗口：{title}")
        # 听:asr_bridge 已转写出文字 → 直接把用户说的话交给模型判断；
        # 未转写(native 待服务/转写失败)则只提示"有声音"。
        if obs.audio_transcript:
            text_lines.append(f"（麦克风此刻听到：「{obs.audio_transcript}」）")
        elif obs.audio_b64:
            text_lines.append("（麦克风此刻有新的声音输入。）")

        # 可打扰性:把「克制是美德」从祈使句变成可测量的输入。
        # 没有可用证据时是空串 —— 不写模棱两可的话进提示词。
        if obs.interruptibility_note:
            text_lines.append(obs.interruptibility_note)

        # 融合看:屏幕 + 摄像头两路都发给模型(此前只发一路)。仅当统一模态协商层
        # 判定当前模型【看得见】(vision 可用)时才附图——换到无视觉模型自动省掉图像,
        # 不给瞎子发图、不白烧 token。协商层不可用时保守按"能看"处理,不回退视觉。
        images: List[tuple] = []
        if self._vision_usable():
            if obs.screen_b64:
                images.append(("屏幕截图", obs.screen_b64, obs.screen_mime))
            if obs.camera_b64:
                images.append(("摄像头画面", obs.camera_b64, obs.camera_mime))
            # 兼容:调用方只塞了 frame_b64(未分路)时,仍发主帧。
            if not images and obs.frame_b64:
                images.append(("画面", obs.frame_b64, obs.frame_mime))

        if len(images) > 1:
            text_lines.append("（以下依次是：" + "、".join(lbl for lbl, _, _ in images) + "）")
        text_lines.append("现在，请判断此刻该 SPEAK / SILENT / DELEGATE。")
        text = "\n".join(text_lines)

        if images:
            content: List[Dict[str, Any]] = [{"type": "text", "text": text}]
            for _lbl, b64, mime in images:
                content.append(self._image_part(b64, mime))
            return [{"role": "user", "content": content}]
        return [{"role": "user", "content": text}]

    @staticmethod
    def _vision_usable() -> bool:
        """当前模型是否看得见(经统一模态协商层)。协商不可用时保守返回 True,不回退视觉。"""
        try:
            from core.modality_capability import negotiate

            return negotiate().vision_in.usable
        except Exception:  # noqa: BLE001
            return True

    async def decide(self, obs: AmbientObservation) -> AmbientDecision:
        router = self._get_router()
        messages = self._build_messages(obs)
        try:
            resp = await router.chat(messages, temperature=0.2, max_tokens=200)
            text = (resp.content or "").strip()
        except Exception as exc:  # noqa: BLE001 — 多模态发送失败等
            # 纯文本降级重试一次
            logger.debug("Ambient decider 多模态调用失败,降级纯文本: %s", exc)
            try:
                fallback = [
                    {
                        "role": "user",
                        "content": (
                            messages[0]["content"][0]["text"]
                            if isinstance(messages[0]["content"], list)
                            else messages[0]["content"]
                        ),
                    }
                ]
                resp = await router.chat(fallback, temperature=0.2, max_tokens=200)
                text = (resp.content or "").strip()
            except Exception as exc2:  # noqa: BLE001
                logger.debug("Ambient decider 纯文本降级也失败: %s", exc2)
                return AmbientDecision(action=AmbientAction.SILENT, rationale=f"决策不可用: {exc2}")
        return parse_decision(text)


def parse_decision(text: str) -> AmbientDecision:
    """把主脑的自由文本解析成严格三选一。

    第一行的第一个可辨识词决定 action;拿不准一律 SILENT(克制优先)。
    """
    if not text:
        return AmbientDecision(action=AmbientAction.SILENT, rationale="空响应")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    head = lines[0].upper() if lines else "SILENT"

    if head.startswith("SPEAK"):
        action = AmbientAction.SPEAK
    elif head.startswith("DELEGATE"):
        action = AmbientAction.DELEGATE
    elif head.startswith("SILENT"):
        action = AmbientAction.SILENT
    else:
        # 首行不规范：在全文里找线索，否则保守 SILENT
        upper = text.upper()
        if "DELEGATE" in upper:
            action = AmbientAction.DELEGATE
        elif "SPEAK" in upper:
            action = AmbientAction.SPEAK
        else:
            action = AmbientAction.SILENT

    rationale = ""
    utterance = ""
    task = ""
    for ln in lines[1:]:
        if ln.startswith("说：") or ln.startswith("说:"):
            utterance = ln.split("：", 1)[-1].split(":", 1)[-1].strip()
        elif ln.startswith("派：") or ln.startswith("派:"):
            task = ln.split("：", 1)[-1].split(":", 1)[-1].strip()
        elif not rationale:
            rationale = ln

    # SPEAK 但没给出要说的话 → 用理由兜底；仍为空则降级 SILENT（不空口说白话）
    if action == AmbientAction.SPEAK and not utterance:
        utterance = rationale
        if not utterance:
            return AmbientDecision(action=AmbientAction.SILENT, rationale="SPEAK 无内容,降级沉默")
    # DELEGATE 但没给出任务 → 用理由兜底；仍为空则降级 SILENT
    if action == AmbientAction.DELEGATE and not task:
        task = rationale
        if not task:
            return AmbientDecision(action=AmbientAction.SILENT, rationale="DELEGATE 无任务,降级沉默")

    salient = action in (AmbientAction.SPEAK, AmbientAction.DELEGATE)
    return AmbientDecision(action=action, rationale=rationale, utterance=utterance, task=task, salient=salient)


# ---------------------------------------------------------------------------
# 帧差门控（零模型开销）
# ---------------------------------------------------------------------------
def _perceptual_signature(frame_b64: str) -> Optional[Any]:
    """把一帧 base64 图像压成一个 16x16 灰度指纹（numpy 数组）。

    用 PIL 解码 + 下采样;不可用时返回 None(调用方退回字节级启发式)。
    """
    try:
        import io

        import numpy as np
        from PIL import Image

        raw = base64.b64decode(frame_b64)
        img = Image.open(io.BytesIO(raw)).convert("L").resize((16, 16))
        return np.asarray(img, dtype="float32") / 255.0
    except Exception:  # noqa: BLE001 — PIL 缺失/解码失败
        return None


def _byte_similarity(a: str, b: str) -> float:
    """字节级相似度兜底（PIL 不可用时）：采样若干字节位比较。0..1，越大越像。"""
    if not a or not b:
        return 0.0
    la, lb = len(a), len(b)
    if la == 0 or lb == 0:
        return 0.0
    len_ratio = min(la, lb) / max(la, lb)
    n = min(256, min(la, lb))
    step = max(1, min(la, lb) // n)
    same = sum(1 for i in range(0, min(la, lb), step) if a[i] == b[i])
    total = len(range(0, min(la, lb), step))
    byte_ratio = same / total if total else 0.0
    return 0.5 * len_ratio + 0.5 * byte_ratio


class FrameGate:
    """维护上一帧指纹，判断新帧是否"变化足够大到值得惊动模型"。"""

    def __init__(self, threshold: float = _DEFAULT_DIFF_THRESHOLD) -> None:
        self.threshold = threshold
        self._prev_sig: Optional[Any] = None
        self._prev_b64: Optional[str] = None

    def reset(self) -> None:
        """丢弃上一帧指纹,让下一帧被当作"第一帧"。

        用于跨越隐私边界(暂停→恢复)后:留着暂停前的指纹去比恢复后的新帧,
        等于泄露"被遮住那段时间里画面变了多少"。注意这会让恢复后的第一拍
        必然判定为"有变化"(第一帧的既定语义),这是刻意接受的代价。
        """
        self._prev_sig = None
        self._prev_b64 = None

    def changed(self, frame_b64: Optional[str]) -> bool:
        if not frame_b64:
            return False
        sig = _perceptual_signature(frame_b64)
        if sig is not None:
            import numpy as np

            if self._prev_sig is None:
                self._prev_sig = sig
                self._prev_b64 = frame_b64
                return True  # 第一帧视为变化
            diff = float(np.mean(np.abs(sig - self._prev_sig)))
            self._prev_sig = sig
            self._prev_b64 = frame_b64
            return diff > self.threshold
        # 字节级兜底
        if self._prev_b64 is None:
            self._prev_b64 = frame_b64
            return True
        sim = _byte_similarity(frame_b64, self._prev_b64)
        self._prev_b64 = frame_b64
        return sim < 0.995


# ---------------------------------------------------------------------------
# 常驻注意力循环
# ---------------------------------------------------------------------------
def _ai_is_speaking() -> bool:
    """AI 是否正在(或刚刚)朗读（反自激励门控用）。降级安全:取不到就当没在说。

    两个来源取并集,因为单靠 ``is_speaking()`` 挡不住:它只反映
    ``speech_output._active_speaker``,而那个变量只在【流式】朗读路径上被设置——
    整段批处理(``GALAXY_TTS_STREAMING=0``)和原生发声两条路径都不设它,那两种模式
    下 ``is_speaking()`` 恒为 False,本门形同虚设。``voice_echo_guard`` 登记在
    "文字真的变成声音"的那一刻,三条发声路径一视同仁;它还带一段尾巴时间,能覆盖
    "声音已播完、但麦克风侧那段缓冲刚转写出来"的滞后窗口。
    """
    try:
        from core.speech_output import is_speaking

        if bool(is_speaking()):
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        from core.voice_echo_guard import recently_spoke

        return bool(recently_spoke())
    except Exception:  # noqa: BLE001
        return False


def _interruptibility_note() -> str:
    """手表报的「现在能不能打扰他」,取一行提示词;拿不到就空串。

    登记处不可用(没装手表、模块导入失败)时返回空串,循环行为与接手表
    之前完全一致 —— **没有证据既不放行也不阻拦**。
    """
    try:
        from core.interruptibility_registry import get_interruptibility_registry

        return get_interruptibility_registry().prompt_line()
    except Exception:  # noqa: BLE001 — 可打扰性是增强项,永远不该拖垮本拍
        return ""


def _interruptibility_blocked() -> bool:
    """此刻是否**明确**不宜主动开口(手表 band=blocked)。

    只有明确的 BLOCKED 才是 True。UNKNOWN / 陈旧 / 没有手表一律 False。
    """
    try:
        from core.interruptibility_registry import get_interruptibility_registry

        return get_interruptibility_registry().is_blocked()
    except Exception:  # noqa: BLE001
        return False


def _apply_interruptibility_gate(decision: AmbientDecision) -> AmbientDecision:
    """手表说「明确别打扰」时,把 SPEAK 降级为 SILENT。

    这是提示词之外的**硬闸**:提示词只是建议,模型可能无视它;
    用户开着勿扰或正在睡觉时,主动开口是不可接受的失败模式。

    刻意**不拦 DELEGATE**:委托是后台静默干活,不发出声音、不占用户注意力,
    正是"此刻别说话"时最该做的事。拦掉它等于把"别吵我"误读成"别干活"。

    也刻意**不拦用户显式发起的请求** —— 那条路根本不经过本函数
    (走 handle_request 正门)。这里管的只有自发注意力。

    降级是**有界延迟**而非丢弃:循环每一拍都会重新判断,勿扰一解除,
    同样的情形会重新有机会 SPEAK。
    """
    if decision.action != AmbientAction.SPEAK:
        return decision
    if not _interruptibility_blocked():
        return decision
    logger.info("Ambient SPEAK 被可打扰性硬闸降级为 SILENT(手表报告 blocked)")
    return AmbientDecision(
        action=AmbientAction.SILENT,
        # 保留原本要说的话在理由里:事后查日志能看出"它本来想说什么、
        # 为什么没说",而不是凭空少了一拍。
        rationale=f"手表报告此刻不宜打扰,原判 SPEAK 已降级(原拟发言:{decision.utterance[:60]})",
        salient=False,
    )


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "").strip() or default)
    except (TypeError, ValueError):
        return default


class AmbientAttentionLoop:
    """自发注意力循环。所有协作者可注入，便于单测。"""

    def __init__(
        self,
        *,
        decider: Optional[AmbientDecider] = None,
        perception_store: Optional[Any] = None,
        working_memory: Optional[Any] = None,
        unified_memory: Optional[Any] = None,
        event_bus: Optional[Any] = None,
        interval_s: Optional[float] = None,
        cooldown_s: Optional[float] = None,
        diff_threshold: Optional[float] = None,
        session_id: str = _AMBIENT_SESSION,
    ) -> None:
        self._decider = decider
        self._store = perception_store
        self._wm = working_memory
        self._um = unified_memory
        self._bus = event_bus
        self.interval_s = (
            interval_s if interval_s is not None else _float_env("GALAXY_AMBIENT_INTERVAL_S", _DEFAULT_INTERVAL_S)
        )
        self.cooldown_s = (
            cooldown_s if cooldown_s is not None else _float_env("GALAXY_AMBIENT_COOLDOWN_S", _DEFAULT_COOLDOWN_S)
        )
        _thr = (
            diff_threshold
            if diff_threshold is not None
            else _float_env("GALAXY_AMBIENT_DIFF_THRESHOLD", _DEFAULT_DIFF_THRESHOLD)
        )
        # 屏幕与摄像头【各一个】门控:任一路变化足够大就值得惊动模型。此前只有一个
        # 门控盯"主帧"(屏幕优先),摄像头单独变化(如用户走进画面)根本不会触发。
        self._gate = FrameGate(_thr)
        self._cam_gate = FrameGate(_thr)
        self.session_id = session_id

        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_action_ts = 0.0
        self._last_audio_hash = ""
        #: 上次见到的感知世代号;与 store.epoch 不一致即表示中间发生过隐私暂停,
        #: 需重置帧差门控(见 _gather_observation)。初值 -1 保证首拍必对齐一次。
        self._perception_epoch: int = -1
        self._recent_rationales: List[str] = []
        self.ticks = 0
        self.decisions = 0

    # ── 懒加载协作者（避免导入期副作用）──
    def _get_store(self):
        if self._store is None:
            from core.perception.desktop_perception_store import get_desktop_perception_store

            self._store = get_desktop_perception_store()
        return self._store

    def _get_wm(self):
        if self._wm is None:
            from core.cognitive.working_memory import get_working_memory

            self._wm = get_working_memory()
        return self._wm

    def _get_um(self):
        if self._um is None:
            try:
                from core.memory.unified import get_unified_memory

                self._um = get_unified_memory()
            except Exception:  # noqa: BLE001
                self._um = None
        return self._um

    def _get_decider(self) -> AmbientDecider:
        if self._decider is None:
            self._decider = LLMRouterDecider()
        return self._decider

    def _get_bus(self):
        if self._bus is None:
            try:
                from core.state_event_bus import get_state_event_bus

                self._bus = get_state_event_bus()
            except Exception:  # noqa: BLE001
                self._bus = None
        return self._bus

    # ── 门控：这一拍是否值得惊动模型 ──
    def _gather_observation(self) -> Optional[AmbientObservation]:
        """从感知库读一份快照（只读，不消费对话音频）；被门控挡下返回 None。"""
        store = self._get_store()

        # 隐私世代号:pause/resume 会让它自增。世代一变说明中间发生过隐私暂停,
        # 此时把两路帧差指纹与音频哈希一并清掉。
        #
        # 理由是【隐私】,不是省一次模型调用 —— 恰恰相反:FrameGate 对第一帧本就
        # 返回 True(见 changed() 的"第一帧视为变化"),所以 reset 之后恢复的
        # 第一拍一定会触发一次。这是可接受的(恢复后重新看一眼环境本就合理)。
        #
        # 真正的问题在于:若保留暂停前那枚指纹,恢复后的新帧会跟它做差 ——
        # 等于让智能体能推断出"我被遮住的那段时间里屏幕变化了多少"。用户主动
        # 遮起来的内容,不该以差异信号的形式渗出来。故跨隐私边界不携带视觉状态。
        try:
            epoch = store.epoch
            if epoch != self._perception_epoch:
                self._perception_epoch = epoch
                self._gate.reset()
                self._cam_gate.reset()
                self._last_audio_hash = ""
                logger.info("Ambient: 感知世代变更(epoch=%s),已重置帧差门控与音频哈希", epoch)
        except AttributeError:
            # 老版本 store 没有 epoch —— 不因此中断本拍
            pass

        try:
            media = store.snapshot_media()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Ambient: snapshot_media 失败: %s", exc)
            return None

        # 隐私暂停期间 snapshot_media 全空,这一拍直接跳过,连门控都不用更新
        # (没有新数据可比),也不该把"空"当成"画面变了"。
        if media.get("privacy_paused"):
            return None

        # 分路取帧:屏幕、摄像头各自原始帧(可同时存在)。主帧(frame_b64)屏幕优先,
        # 供门控指纹的主记录/记忆/路由沿用,保持既有行为兼容。
        screen_b64 = media.get("screen_b64")
        camera_b64 = media.get("camera_b64") or media.get("image_b64")
        frame_b64 = screen_b64 or camera_b64
        frame_mime = media.get("screen_mime") if screen_b64 else media.get("camera_mime", "image/jpeg")
        frame_source = "desktop_screen" if screen_b64 else "desktop_camera"
        audio_b64 = media.get("audio_b64")

        # 门控更新必须【每拍都做】,不能被冷却提前 return 跳过——否则冷却期内
        # _gate 的 prev_sig / 音频哈希都停在冷却开始前那一帧,冷却一结束,新帧
        # 会跟一个 20 秒前的旧帧比对,几乎必然超阈值 → 冷却刚过就无条件触发一次
        # 模型调用,与屏幕当前是否真的变化无关。故先更新门控,再判冷却。
        # 屏幕、摄像头【两路各自门控】,任一路变化足够大即算"值得看一眼"。
        screen_changed = self._gate.changed(screen_b64)
        camera_changed = self._cam_gate.changed(camera_b64)
        frame_changed = screen_changed or camera_changed
        audio_new = False
        if audio_b64:
            ah = hashlib.sha1(audio_b64.encode("utf-8", "ignore")).hexdigest()[:16]
            if ah != self._last_audio_hash:
                # 反自激励(anti-echo):AI 正在朗读时,TTS 从扬声器播出会被麦克风
                # 采到 → 进感知库音频槽 → 若当作"新音频"触发,就会把 AI 自己说的话
                # 转写成文字、当成用户输入喂回下一拍 → AI 对自己说的话做反应 → 无限
                # 自言自语。故朗读期间的音频只更新去重哈希、不作为触发信号。
                self._last_audio_hash = ah
                if not _ai_is_speaking():
                    audio_new = True

        # 冷却期内：门控已更新,但不采取行动（防话痨/防委托风暴）。
        if time.time() - self._last_action_ts < self.cooldown_s:
            return None

        if not frame_changed and not audio_new:
            return None  # 什么都没变 → 这一拍免费跳过

        # 注意:转写(ASR)是 CPU 密集的同步调用,绝不能在这里(会在 async tick 内
        # 同步执行)直接跑——否则整个事件循环被 Whisper 卡住整段转写时长,期间
        # 流式播放推进、barge-in、其它请求全部停摆。故此处只做【快速门控】,把
        # 音频原样带出,转写移到 tick() 里用 asyncio.to_thread 离线到线程池。
        audio_for_obs = audio_b64 if audio_new else None
        return AmbientObservation(
            frame_b64=frame_b64,
            frame_mime=frame_mime or "image/jpeg",
            frame_source=frame_source,
            screen_b64=screen_b64,
            screen_mime=media.get("screen_mime", "image/jpeg"),
            camera_b64=camera_b64,
            camera_mime=media.get("camera_mime", "image/jpeg"),
            audio_b64=audio_for_obs,
            audio_mime=media.get("audio_mime", "audio/webm"),
            audio_transcript=None,  # 由 tick() 异步补上
            screen_meta=media.get("screen_meta"),
            recent_memory=list(self._recent_rationales[-_RECENT_MEMORY_N:]),
            interruptibility_note=_interruptibility_note(),
        )

    async def _transcribe_async(self, obs: AmbientObservation) -> None:
        """听:把新音频离线到线程池转写,回填 obs.audio_transcript;不阻塞事件循环。

        关键:ambient 决策脑走 ``router.chat()``,它只有文本 + 图像 content block,
        **没有音频通路**(见 modality_bridge 文档:Ollama 不吃原生音频)。因此无论
        GALAXY_NATIVE_AUDIO 开关如何,ambient 想"听"就只能靠 ASR 桥转写成文字喂给
        决策脑——它是纯文本消费者。此前按 resolve_audio_in()=='asr_bridge' 短路:
        一旦有人开了原生音频门控,转写被跳过、原生音频又无处可送,常驻在场循环直接
        变【聋】(只知"有声音"、听不到内容)。故这里对 audio 一律尽力转写。
        (原生音频门控 GALAXY_NATIVE_AUDIO 管的是全模态服务通路——audio_pipeline /
        perception 路由——不是这个文本决策脑。)"""
        if not obs.audio_b64:
            return
        try:
            from core.modality_bridge import transcribe_b64

            obs.audio_transcript = await asyncio.to_thread(
                transcribe_b64,
                obs.audio_b64,
                mime=obs.audio_mime,
            )
        except Exception as exc:  # noqa: BLE001 — 听不可用不致命
            logger.debug("Ambient 听桥接失败(非致命): %s", exc)

    # ── 一拍：门控 → 决策 → 路由 → 记忆 → 事件（单测入口）──
    async def tick(self) -> Optional[AmbientDecision]:
        self.ticks += 1
        obs = self._gather_observation()
        if obs is None:
            return None

        # 听（转写）离线到线程池，不卡事件循环。
        await self._transcribe_async(obs)

        self._emit(
            "ambient.observed",
            {
                "has_frame": bool(obs.frame_b64),
                "frame_source": obs.frame_source,
                "has_audio": bool(obs.audio_b64),
                "recent_memory": obs.recent_memory,
            },
        )

        try:
            decision = await self._get_decider().decide(obs)
        except Exception as exc:  # noqa: BLE001 — 决策不可致命
            logger.debug("Ambient decide 异常,视为 SILENT: %s", exc)
            decision = AmbientDecision(action=AmbientAction.SILENT, rationale=f"决策异常: {exc}")

        decision = _apply_interruptibility_gate(decision)

        self.decisions += 1
        await self._route(decision, obs)
        self._record(decision, obs)
        self._emit("ambient.decision", decision.to_dict())
        return decision

    async def _route(self, decision: AmbientDecision, obs: AmbientObservation) -> None:
        if decision.action == AmbientAction.SPEAK:
            # hold 闸(对话政策唯一属主):用户说了"等一下别说话",自发开口同样闭嘴。
            try:
                from core.voice_dialog_policy import get_dialog_policy

                if get_dialog_policy().is_holding():
                    logger.debug("ambient SPEAK 被 hold 抑制")
                    return
            except Exception:  # noqa: BLE001 — 政策不可用不拦自发开口
                pass
            self._last_action_ts = time.time()
            try:
                from core.speech_output import speak_response

                # 与 handle_request 内部同一条 canonical TTS 路径。source="ambient"
                # 让 speak_response 的去重/开关策略统一生效。
                speak_response(decision.utterance, source="ambient")
            except Exception as exc:  # noqa: BLE001
                logger.debug("Ambient SPEAK 朗读失败(非致命): %s", exc)
        elif decision.action == AmbientAction.DELEGATE:
            # 关键:委托要走完整 OpenClawd 认知(可能几十秒),而 _delegate 是被 await
            # 的、会阻塞本拍直到返回。若在这里(委托【开始】时)打冷却时间戳,等委托
            # 几十秒后返回,20 秒冷却早已过期 → 场景持续变化时(如屏幕在放视频)下
            # 一拍立刻又委托 → 背靠背全认知委托风暴。故冷却时间戳必须在委托
            # 【返回后】再打,保证两次委托之间真有冷却间隔。
            await self._delegate(decision, obs)
            self._last_action_ts = time.time()
        # SILENT：无请求进门，主体留在 SILENT，仅记录（在 _record 里做）。

    async def _delegate(self, decision: AmbientDecision, obs: AmbientObservation) -> None:
        """DELEGATE → handle_request 正门（source="ambient"）→ LIMINAL 执行分支。

        携带当前帧作为 multimodal_context,让主体带着"它看到的东西"去执行,
        OpenClawd 内部可自主调用 Node_107 工具链完成委托。
        """
        try:
            from core.desktop_presence_runtime import get_desktop_presence_runtime

            mm_context = None
            if obs.frame_b64:
                try:
                    from core.schemas.multimodal import MultiModalContext, MultiModalImage

                    mm_context = MultiModalContext(
                        images=[
                            MultiModalImage(
                                mime=obs.frame_mime,
                                data=obs.frame_b64,
                                source=obs.frame_source,
                            )
                        ]
                    )
                except Exception:  # noqa: BLE001
                    mm_context = None

            # 委托会话的选择:
            #  - 默认(GALAXY_AMBIENT_SHARE_SESSION=1):续到用户**当前对话主线**上,
            #    让自发动作共享真实上下文(跨设备统一上下文的一部分:自发在场不再是
            #    一座孤岛)。仍不复用 self.session_id——那是 ambient 观察理由的滚动日志。
            #  - 无主线(刚启动、还没对话)或显式关闭 → 退回一次性隔离会话(旧行为),
            #    避免把理由日志与委托认知混在一起。
            import os as _os
            import uuid as _uuid

            session_id = f"ambient-delegate-{_uuid.uuid4().hex[:12]}"
            user_id = "ambient"
            if _os.getenv("GALAXY_AMBIENT_SHARE_SESSION", "1").strip().lower() not in (
                "0",
                "false",
                "no",
                "off",
            ):
                try:
                    from core.session_manager import get_session_manager

                    _sm = get_session_manager()
                    _primary = _sm.get_primary_session_id()
                    if _primary:
                        session_id = _primary
                        _sess = _sm.get_session(_primary)
                        user_id = getattr(_sess, "user_id", "") or "ambient"
                except Exception as exc:  # noqa: BLE001 — 解析失败退回隔离会话
                    logger.debug("Ambient 主线解析失败,退回隔离会话: %s", exc)
            runtime = get_desktop_presence_runtime()
            await runtime.handle_request(
                message=decision.task,
                source="ambient",
                session_id=session_id,
                user_id=user_id,
                multimodal_context=mm_context,
                entry_mode="local",
            )
        except Exception as exc:  # noqa: BLE001 — 委托失败不影响循环
            logger.debug("Ambient DELEGATE 经正门失败(非致命): %s", exc)

    def _record(self, decision: AmbientDecision, obs: AmbientObservation) -> None:
        """写回记忆:工作记忆(滚动,喂面板/下次决策/对话注入) + 终身记忆(仅 salient)。"""
        summary = decision.rationale or decision.utterance or decision.task or decision.action.value
        # 供下一拍决策做时间连续性参考
        self._recent_rationales.append(f"[{decision.action.value}] {summary}")
        if len(self._recent_rationales) > 20:
            self._recent_rationales = self._recent_rationales[-20:]

        # 工作记忆（角色标记为 ambient，与对话消息区分）
        try:
            self._get_wm().add(
                session_id=self.session_id,
                role="ambient",
                content=summary,
                metadata={
                    "action": decision.action.value,
                    "frame_source": obs.frame_source,
                    "has_audio": bool(obs.audio_b64),
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Ambient 工作记忆写入失败(非致命): %s", exc)

        # 终身记忆：只记 salient（SimpleMem 第一原则：选择性摄入，别把库灌成垃圾场）
        if decision.salient:
            um = self._get_um()
            if um is not None and getattr(um, "enabled", False):
                try:
                    um.remember(
                        summary,
                        modality="text",
                        tags=["ambient", decision.action.value],
                        metadata={"source": "ambient_attention_loop"},
                    )
                    # 可选：把 salient 帧本身也存进跨模态记忆（默认关，档位 A 省资源）
                    if obs.frame_b64 and _bool_env("GALAXY_AMBIENT_MEMORY_MEDIA", False):
                        um.remember_media(
                            obs.frame_b64,
                            modality="image",
                            mime=obs.frame_mime,
                            tags=["ambient"],
                            caption=summary,
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Ambient 终身记忆写入失败(非致命): %s", exc)

    def _emit(self, event_type: str, payload: Dict[str, Any]) -> None:
        bus = self._get_bus()
        if bus is None:
            return
        try:
            bus.publish(event_type, source="ambient_attention_loop", payload=payload)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Ambient 事件发布失败(非致命): %s", exc)

    # ── 生命周期 ──
    async def _run_loop(self) -> None:
        logger.info(
            "AmbientAttentionLoop 启动 | interval=%.1fs cooldown=%.1fs",
            self.interval_s,
            self.cooldown_s,
        )
        while self._running:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — 单拍异常不该杀死循环
                logger.debug("Ambient tick 异常(已吞,继续): %s", exc)
            try:
                await asyncio.sleep(self.interval_s)
            except asyncio.CancelledError:
                raise

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None
        logger.info("AmbientAttentionLoop 已停止 | ticks=%d decisions=%d", self.ticks, self.decisions)

    @property
    def running(self) -> bool:
        return self._running


# ---------------------------------------------------------------------------
# 单例
# ---------------------------------------------------------------------------
_loop_instance: Optional[AmbientAttentionLoop] = None


def get_ambient_loop() -> AmbientAttentionLoop:
    global _loop_instance
    if _loop_instance is None:
        _loop_instance = AmbientAttentionLoop()
    return _loop_instance


def reset_ambient_loop() -> None:
    """测试用：清空单例。"""
    global _loop_instance
    _loop_instance = None


def ambient_loop_enabled() -> bool:
    """总开关：**默认开**;``GALAXY_AMBIENT_LOOP=0`` 显式关闭。

    为什么可以默认开(所有者指令 + 实测支撑):

    - **不新增任何采集**。本循环只消费 :class:`DesktopPerceptionStore` 里
      已有的帧/音频,而那些帧本身受 Electron 首次启动的感知授权对话框把关。
      用户没授权 → store 里没有帧 → 门控在**零模型开销**处直接跳过
      (回归用例 ``test_no_perception_gates_out_no_decider_call`` 锁定了
      "无感知 → 决策脑一次都不会被调用")。所以"默认开"不等于"默认看你的屏幕",
      隐私边界仍然是那一次授权。
    - **静止画面不花钱**。门控是帧差 + 音频新鲜度 + 冷却 + 场景去重,画面没变
      的每一拍都免费跳过,不惊动主脑(``test_static_frame_gates_out_after_first``)。
    - **默认关的代价是功能等于不存在**:三态里的 SILENT 本该是"在场但不表达",
      默认关之后它退化成"睡着"——自发在场这个器官装上了却从不通电。

    仍然保留显式关闭:``GALAXY_AMBIENT_LOOP=0/false/no/off``。
    """
    return _bool_env("GALAXY_AMBIENT_LOOP", True)
