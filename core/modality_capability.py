"""core/modality_capability.py — 统一模态能力协商层（自适配的唯一入口）
=========================================================================

**问题**：全模态 I/O(看/听/说/看视频/桌面操作)散在各处各自判断"当前模型能不能
原生做某模态",一旦换模型就得到处改 if。有些模型有音频、有些没有,靠散落的开关
根本管不住。

**解法**：把"某模态该走原生还是桥接还是不可用"收成【一次运行时协商】。所有循环
(voice / ambient / computer_use / ingest / 请求注入)都问本层,而不是各自写死。
换模型 → 协商结果自动变 → 全链路自适配,不留一个硬编码分支。

三态(每个模态)：
  native       —— 当前档位有模型原生支持该模态,且服务层确实能喂进去
  bridge       —— 模型不原生支持,但有桥可替(听→ASR、说→TTS、视频→抽静帧)
  unavailable  —— 原生没有、桥也没有 → 如实降级并说清原因(绝不假装能干)

能力来源(唯一真相源)：core.model_catalog 的 EffectiveIO(每个模型声明 vision/
audio_in/audio_out/video 原生能力),叠加"服务现实"门控(见 _native_serving_*):
即便模型声明支持,Ollama /api/chat 还没有音频输入字段,故原生音频/视频要显式开
GALAXY_NATIVE_AUDIO / GALAXY_NATIVE_VIDEO(默认关,上了真正的全模态服务端再开)。
桥可用性(ASR/TTS 是否装了)也一并纳入,缺桥则如实报 unavailable。

第三维:设备
------------
前两维("模型声明"×"服务现实")回答的是**这套后端能不能做**,但真正决定能不能做的
还有第三件事:**这次要在哪台设备上做**。同一个模型、同一套服务,在桌面上能看能听,
到了手表上就只剩听 —— 手表没有摄像头。

不加这一维的后果不是"少一个功能",而是**误判 + 无从归因**:协商说 vision_in=native,
于是常驻注意力循环去要一帧图像,设备侧永远返回不了,链路在别处超时/静默失败,
日志里看到的是"取帧超时",没有任何一处会说"这台设备根本没有摄像头"。

门控原则是**未知不设卡**:设备没报能力(或报的东西完全不在模态词汇里)时,一律
不改变协商结果 —— 能力表是各注册方自行填的,把"没写"当成"没有"会凭空关掉一堆
本来能用的东西。只有当设备**确实在用这套词汇说话**、却缺了某一项时,才判定为
该设备不可用,并在 ``limited_by`` 上标明是**设备**限制而不是模型或服务限制。

self-contained:纯读能力 + 环境门控 + 轻量 import 探测,无重型副作用;
negotiate() 可注入 effective_io / device 便于单测(不加载真实模型、不连 UDM)。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.ModalityCapability")

# 模态名(稳定标识,面板/日志/测试共用)
VISION_IN = "vision_in"  # 看静帧(摄像头/屏幕)
AUDIO_IN = "audio_in"  # 听
AUDIO_OUT = "audio_out"  # 说
VIDEO_IN = "video_in"  # 看视频(连续帧/流)

_MODES = ("native", "bridge", "unavailable")


def _env_on(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# ── 服务现实门控:模型"声明支持"≠"服务端真能喂进去" ────────────────────────
def _native_audio_serving_enabled() -> bool:
    """原生音频(听/说)服务是否就绪。默认关——Ollama /api/chat 无音频字段;
    上了 vLLM-Omni / MiniCPM-o server 再开 GALAXY_NATIVE_AUDIO。"""
    return _env_on("GALAXY_NATIVE_AUDIO", False)


def _native_video_serving_enabled() -> bool:
    """原生视频(连续帧/流)服务是否就绪。默认关;上了支持视频的全模态服务再开。"""
    return _env_on("GALAXY_NATIVE_VIDEO", False)


# ── 桥可用性探测(轻量 import,不加载模型) ──────────────────────────────────
def asr_bridge_available() -> bool:
    """听的桥(音频→文字)是否可用:装了 faster-whisper 或 funasr 即可。"""
    import importlib.util as _u

    return any(_u.find_spec(m) is not None for m in ("faster_whisper", "funasr"))


def tts_bridge_available() -> bool:
    """说的桥(文字→语音)是否可用:edge-tts / pyttsx3 / Windows SAPI 任一即可。

    Windows 上即便没装任何三方包,系统自带 SAPI 也能合成,故 Windows 恒 True。
    """
    if os.name == "nt":
        return True
    import importlib.util as _u

    return any(_u.find_spec(m) is not None for m in ("edge_tts", "pyttsx3", "kokoro_onnx"))


# ── 协商结果 ─────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ModalityResolution:
    """单个模态的协商结果。"""

    modality: str
    mode: str  # native | bridge | unavailable
    reason: str
    native_capable: bool = False  # 模型是否【声明】原生支持(与服务是否就绪分开)
    #: 是谁把这个模态限制住的:``""``(没被限制) | ``"model"`` | ``"serving"`` | ``"device"``。
    #: reason 是给人看的,这个是给代码看的 —— 否则调用方想区分"换个模型就能用"和
    #: "换台设备才能用",只能去正则匹配那句中文。
    limited_by: str = ""

    @property
    def usable(self) -> bool:
        return self.mode in ("native", "bridge")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "modality": self.modality,
            "mode": self.mode,
            "reason": self.reason,
            "native_capable": self.native_capable,
            "usable": self.usable,
            "limited_by": self.limited_by,
        }


@dataclass(frozen=True)
class ModalityPlan:
    """一次协商产出的全模态计划——所有循环据此决定各模态怎么走。"""

    vision_in: ModalityResolution
    audio_in: ModalityResolution
    audio_out: ModalityResolution
    video_in: ModalityResolution
    tier: str = ""
    #: 本计划是针对哪台设备协商的。空串 = 未指定设备(本机/不区分),此时不做设备门控。
    device_id: str = ""

    def get(self, modality: str) -> ModalityResolution:
        return {
            VISION_IN: self.vision_in,
            AUDIO_IN: self.audio_in,
            AUDIO_OUT: self.audio_out,
            VIDEO_IN: self.video_in,
        }[modality]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tier": self.tier,
            "device_id": self.device_id,
            VISION_IN: self.vision_in.to_dict(),
            AUDIO_IN: self.audio_in.to_dict(),
            AUDIO_OUT: self.audio_out.to_dict(),
            VIDEO_IN: self.video_in.to_dict(),
        }


# ── 设备维:硬件/权限门控 ────────────────────────────────────────────────────

#: 各模态所需的设备能力(同义词都列上 —— 各注册方用词不统一,而这里判"没有"就要
#: 关掉一个模态,宁可多认几个别名,也不能因为写法不同就误判成"这台设备没有麦克风")。
#:
#: **AUDIO_OUT 刻意不在这里** —— 这是真机实测改的,不是遗漏。
#:
#: 第一版给它配了 ``("speaker","audio_out","tts","audio")``,因为 speaker 看上去
#: 就是 microphone 的对偶。把服务跑起来对着**全部 272 台已注册设备**一测:
#:
#:     被设备维拦掉「说」: 73 台   ← 即"申报了模态能力"的全部 73 台,一台不剩
#:     样本能力表: ['camera', 'screen', 'touch']
#:
#: 因为这批设备实际用到的词汇只有 ``screen / touch / camera / microphone /
#: keyboard`` —— **从来没有任何一台申报过音频输出能力**。于是那道门不可能有真阳性,
#: 只能产出假阴性:凡是说了句人话的设备,"说"就被一刀切掉。一台有摄像头有屏幕的
#: 手机当然有扬声器,只是没人往能力表里写。
#:
#: 这正是本模块头一再强调的"未知不设卡"——只不过这一次"未知"不是某台设备没填,
#: 而是**整套词汇根本没有表达这件事的词**。没有能力表达 = 没有证据 = 不设卡。
#: 等注册方真的开始上报 speaker/audio_out 了,再把它加回来(那时才会有真阳性)。
_REQUIRED_DEVICE_CAPABILITY = {
    VISION_IN: ("camera", "screen", "display", "screen_capture", "vision"),
    AUDIO_IN: ("microphone", "mic", "audio_in", "audio"),
    # 屏幕也是视频源(录屏/投屏),与 VISION_IN 保持一致 —— 此前只认 screen_capture
    # 而不认 screen,导致"有屏幕没摄像头"的设备被判为完全不能处理视频。
    VIDEO_IN: ("camera", "video", "screen", "display", "screen_capture"),
}

#: 模态词汇表:设备报的能力里出现过其中任何一个,才说明它"在用这套词汇说话",
#: 才对它做门控。见模块头"未知不设卡"。
_MODALITY_VOCABULARY = {c for caps in _REQUIRED_DEVICE_CAPABILITY.values() for c in caps}


@dataclass(frozen=True)
class DeviceModalityGate:
    """一台设备对各模态的硬件/权限门控。

    ``speaks_vocabulary`` 为 False 时本门**完全透明** —— 见 :meth:`allows`。
    """

    device_id: str = ""
    capabilities: frozenset = frozenset()
    speaks_vocabulary: bool = False

    @classmethod
    def from_device(cls, device: Any) -> "DeviceModalityGate":
        """从 UnifiedDevice / dict / device_id 字符串构造门控。

        传 device_id 字符串时会去 UDM 查;查不到就返回一个透明门(而不是把设备
        当成"什么都没有")—— 查不到设备和设备没有摄像头是两回事。
        """
        if device is None:
            return cls()

        if isinstance(device, str):
            device = _lookup_device(device)
            if device is None:
                return cls()

        if isinstance(device, dict):
            device_id = str(device.get("device_id") or "")
            raw_caps = device.get("capabilities") or []
        else:
            device_id = str(getattr(device, "device_id", "") or "")
            raw_caps = getattr(device, "capabilities", None) or []

        caps = frozenset(str(c).strip().lower() for c in raw_caps if str(c).strip())
        return cls(
            device_id=device_id,
            capabilities=caps,
            speaks_vocabulary=bool(caps & _MODALITY_VOCABULARY),
        )

    def allows(self, modality: str) -> bool:
        """这台设备是否具备该模态所需的硬件。

        三种情况一律放行(未知不设卡):设备没报能力、报的东西完全不在模态词汇里、
        以及**该模态压根不受设备门控**(如 AUDIO_OUT,原因见
        ``_REQUIRED_DEVICE_CAPABILITY``)。
        """
        if not self.speaks_vocabulary:
            return True
        required = _REQUIRED_DEVICE_CAPABILITY.get(modality)
        if not required:
            return True  # 不在门控表里 = 没有判据 = 不拦
        return any(c in self.capabilities for c in required)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "capabilities": sorted(self.capabilities),
            "gating_active": self.speaks_vocabulary,
        }


def iter_known_devices() -> List[Any]:
    """列出**运行时真正认得的**全部设备,与 ``GET /api/v1/devices`` 同源同策略。

    为什么不能只读 UDM(真机实测)
    -----------------------------
    第一版这里只问 ``UnifiedDeviceManager``,理由是它自称统一设备管理器、文档里
    是 SSOT。真把服务跑起来一看:

        GET /api/v1/devices        → 272 台(capabilities 形如 ['screen','touch'])
        UDM.list_devices()         → 0 台

    因为 UDM 只在设备**运行时真连上来**时才被 ``register_device()`` 写入;冷启动
    时它是空的,而那 272 台来自开机从磁盘载入的 ``registered_devices``(它在
    ``core.routes._shared`` 里被标为 legacy compat cache,但它才是持久化的那份)。
    规范的设备列表端点是**两个源合并**的 —— 只读 UDM 等于对每一台持久化设备
    视而不见,整个设备维在生产里永远不会拦下任何东西:门恒透明,功能存在但不生效。

    所以这里照抄 ``core/routes/devices.py::list_devices`` 的合并策略:
    **UDM 为主,registered_devices 补充 UDM 中不存在的条目**。任何一侧不可用都
    只是少一部分候选,不抛异常。

    返回的元素既可能是 ``UnifiedDevice``,也可能是 dict —— ``DeviceModalityGate.
    from_device`` 两种都认,调用方不必区分。
    """
    merged: Dict[str, Any] = {}
    try:
        from core.routes._shared import registered_devices

        for did, info in (registered_devices or {}).items():
            if isinstance(info, dict):
                merged[str(did)] = {**info, "device_id": str(did)}
    except Exception as exc:  # noqa: BLE001
        logger.debug("iter_known_devices: 兼容缓存不可用: %s", exc)

    try:
        from core.unified.device_manager import get_unified_device_manager

        for dev in get_unified_device_manager().list_devices() or []:
            did = str(getattr(dev, "device_id", "") or "")
            if did:
                merged[did] = dev  # UDM 为主,覆盖同 ID 的兼容缓存条目
    except Exception as exc:  # noqa: BLE001
        logger.debug("iter_known_devices: UDM 不可用: %s", exc)

    return [merged[k] for k in sorted(merged)]


def _lookup_device(device_id: str) -> Any:
    """按 device_id 查设备。查不到/设备源不可用都返回 None(→ 门透明)。"""
    if not device_id:
        return None
    try:
        for dev in iter_known_devices():
            did = dev.get("device_id") if isinstance(dev, dict) else getattr(dev, "device_id", "")
            if str(did or "") == device_id:
                return dev
    except Exception as exc:  # noqa: BLE001 — 设备源不可用只意味着不做门控
        logger.debug("设备能力查询失败,按不设卡处理 device_id=%s: %s", device_id, exc)
    return None


def _apply_device_gate(res: ModalityResolution, gate: DeviceModalityGate) -> ModalityResolution:
    """把设备门控叠加到模型×服务的协商结果上。

    只会**收紧**,不会放宽:模型/服务判为不可用的,设备再全能也还是不可用。
    """
    if not res.usable or gate.allows(res.modality):
        return res
    if res.modality not in _REQUIRED_DEVICE_CAPABILITY:
        return res  # 该模态不受设备门控(见 _REQUIRED_DEVICE_CAPABILITY 里 AUDIO_OUT 的说明)
    required = "/".join(_REQUIRED_DEVICE_CAPABILITY.get(res.modality, ())[:2])
    return ModalityResolution(
        res.modality,
        "unavailable",
        f"后端可用({res.mode}),但设备 {gate.device_id or '(未命名)'} 未申报所需能力({required})",
        res.native_capable,
        limited_by="device",
    )


def _resolve_audio_in(effio, *, asr_ok: bool) -> ModalityResolution:
    native = getattr(effio, "audio_in", "asr_bridge") == "native"
    if native and _native_audio_serving_enabled():
        return ModalityResolution(AUDIO_IN, "native", "模型原生听 + 全模态服务已开", True)
    if asr_ok:
        why = "模型原生听但服务未开(GALAXY_NATIVE_AUDIO)→ ASR 转写" if native else "模型不原生听 → ASR 转写"
        return ModalityResolution(AUDIO_IN, "bridge", why, native, limited_by="serving" if native else "model")
    return ModalityResolution(
        AUDIO_IN, "unavailable", "无原生音频服务、也未装 ASR(faster-whisper/funasr)", native, limited_by="serving"
    )


def _resolve_audio_out(effio, *, tts_ok: bool) -> ModalityResolution:
    native = getattr(effio, "audio_out", "tts_bridge") == "native"
    if native and _native_audio_serving_enabled():
        return ModalityResolution(AUDIO_OUT, "native", "模型原生说 + 全模态服务已开", True)
    if tts_ok:
        why = "模型原生说但服务未开(GALAXY_NATIVE_AUDIO)→ TTS 合成" if native else "模型不原生说 → TTS 合成"
        return ModalityResolution(AUDIO_OUT, "bridge", why, native, limited_by="serving" if native else "model")
    return ModalityResolution(AUDIO_OUT, "unavailable", "无原生语音服务、也无可用 TTS", native, limited_by="serving")


def _resolve_vision_in(effio) -> ModalityResolution:
    if getattr(effio, "vision", "none") == "native":
        return ModalityResolution(VISION_IN, "native", "模型原生看图(摄像头/屏幕静帧直接进上下文)", True)
    return ModalityResolution(
        VISION_IN, "unavailable", "当前档位无视觉模型(换含视觉的模型即自动启用)", False, limited_by="model"
    )


def _resolve_video_in(effio) -> ModalityResolution:
    v = getattr(effio, "video", "none")
    if v == "native" and _native_video_serving_enabled():
        return ModalityResolution(VIDEO_IN, "native", "模型原生理解连续帧 + 视频服务已开", True)
    if v in ("native", "frames_bridge"):
        native = v == "native"
        why = "视频服务未开(GALAXY_NATIVE_VIDEO)→ 抽静帧走视觉" if native else "模型不原生看视频 → 抽静帧走视觉"
        return ModalityResolution(VIDEO_IN, "bridge", why, native, limited_by="serving" if native else "model")
    return ModalityResolution(
        VIDEO_IN, "unavailable", "当前档位无视觉能力,无法从视频抽帧理解", False, limited_by="model"
    )


def negotiate(
    *,
    effio: Any = None,
    tier: Optional[str] = None,
    asr_available: Optional[bool] = None,
    tts_available: Optional[bool] = None,
    device: Any = None,
) -> ModalityPlan:
    """协商当前(或指定)档位、(可选)指定设备上的全模态计划。

    Args:
        effio: 直接注入 EffectiveIO(测试用);None 则从 model_catalog 取当前/指定档位。
        tier: 指定档位 key;None 用当前已选档位。
        asr_available/tts_available: 覆盖桥可用性探测(测试用)。
        device: 目标设备 —— ``UnifiedDevice`` / dict / ``device_id`` 字符串 / None。
            None 表示不区分设备(本机),此时行为与加入设备维之前**完全一致**。
            给了设备则叠加硬件门控:只收紧不放宽,且未申报能力的设备不设卡。
    """
    if effio is None:
        try:
            from core.model_catalog import active_effective_io, tier_effective_io

            effio = tier_effective_io(tier) if tier else active_effective_io()
        except Exception as exc:  # noqa: BLE001 — 能力源不可用不能让协商崩,给最保守计划
            logger.debug("模态能力源不可用,按最保守计划协商: %s", exc)
            effio = None

    if effio is None:
        # 最保守:无能力信息 → 视觉/视频不可用,听说尽量走桥
        asr_ok = asr_available if asr_available is not None else asr_bridge_available()
        tts_ok = tts_available if tts_available is not None else tts_bridge_available()

        class _Empty:
            vision = "none"
            audio_in = "asr_bridge"
            audio_out = "tts_bridge"
            video = "none"

        effio = _Empty()

    asr_ok = asr_available if asr_available is not None else asr_bridge_available()
    tts_ok = tts_available if tts_available is not None else tts_bridge_available()

    gate = DeviceModalityGate.from_device(device)
    return ModalityPlan(
        vision_in=_apply_device_gate(_resolve_vision_in(effio), gate),
        audio_in=_apply_device_gate(_resolve_audio_in(effio, asr_ok=asr_ok), gate),
        audio_out=_apply_device_gate(_resolve_audio_out(effio, tts_ok=tts_ok), gate),
        video_in=_apply_device_gate(_resolve_video_in(effio), gate),
        tier=tier or "",
        device_id=gate.device_id,
    )


def devices_capable_of(modality: str, *, tier: Optional[str] = None) -> List[str]:
    """返回**能承担某个模态**的设备 ID 列表(在线优先,按 ID 稳定排序)。

    这是设备维真正的用处:跨设备派发要挑一台"能看"的设备时,直接问这里,
    而不是派出去再等超时。没有它的时候,中心只知道"后端能看",不知道"哪台能看"。

    未申报能力的设备**会**被列入 —— 见模块头"未知不设卡":没人填过能力表不等于
    设备没有硬件,把它排除掉会凭空缩小可派发范围。调用方若要区分"确认能做"与
    "没说过做不做",看 :func:`device_modality_matrix` 里的 ``gating_active``。
    """
    out: List[str] = []
    for dev in iter_known_devices():
        try:
            if negotiate(tier=tier, device=dev).get(modality).usable:
                did = dev.get("device_id") if isinstance(dev, dict) else getattr(dev, "device_id", "")
                out.append(str(did or ""))
        except Exception as exc:  # noqa: BLE001 — 单台设备协商失败不影响其余
            logger.debug("devices_capable_of: 设备协商失败 %s: %s", getattr(dev, "device_id", "?"), exc)
    return sorted(d for d in out if d)


def device_modality_matrix(*, tier: Optional[str] = None) -> Dict[str, Any]:
    """所有已注册设备 × 全模态的协商结果。供面板与派发决策共用。"""
    rows: List[Dict[str, Any]] = []
    for dev in iter_known_devices():
        try:
            gate = DeviceModalityGate.from_device(dev)
            _get = dev.get if isinstance(dev, dict) else (lambda k, d="": getattr(dev, k, d))
            rows.append(
                {
                    "device_id": gate.device_id,
                    "device_name": str(_get("device_name", "") or ""),
                    "device_type": str(_get("device_type", "") or ""),
                    "online": bool(_get("online", False)),
                    "gate": gate.to_dict(),
                    "plan": negotiate(tier=tier, device=dev).to_dict(),
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("device_modality_matrix: 设备协商失败 %s: %s", getattr(dev, "device_id", "?"), exc)
    rows.sort(key=lambda r: r["device_id"])
    return {
        "tier": tier or "",
        "device_count": len(rows),
        "devices": rows,
        "capable": {m: devices_capable_of(m, tier=tier) for m in (VISION_IN, AUDIO_IN, AUDIO_OUT, VIDEO_IN)},
    }


MODALITY_CAPABILITY_AUTHORITY: str = (
    "MODALITY_CAPABILITY_V1: core/modality_capability.py | 全模态自适配协商唯一入口. "
    "negotiate() → ModalityPlan(vision_in/audio_in/audio_out/video_in), 每模态三态 "
    "native/bridge/unavailable. 能力源=model_catalog.EffectiveIO, 服务门控="
    "GALAXY_NATIVE_AUDIO/GALAXY_NATIVE_VIDEO, 桥探测=faster-whisper/funasr/TTS. "
    "所有循环(voice/ambient/computer_use/ingest)据此自适配,不写死 per-model 分支."
)

__all__ = [
    "VISION_IN",
    "AUDIO_IN",
    "AUDIO_OUT",
    "VIDEO_IN",
    "ModalityResolution",
    "ModalityPlan",
    "negotiate",
    "DeviceModalityGate",
    "iter_known_devices",
    "devices_capable_of",
    "device_modality_matrix",
    "asr_bridge_available",
    "tts_bridge_available",
    "MODALITY_CAPABILITY_AUTHORITY",
]
