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

第四维:这次由谁来想
--------------------
前三维回答的是"本地这套后端 × 这台设备能不能做"。还有一件事同样决定结果:
**这一次的推理要交给谁** —— 本地那几个模型,还是某家云端 provider。

不加这一维的后果和不加设备维时一模一样,只是方向相反:本地档位是 A(gemma4:e2b,
无视觉)而 ``OPENAI_API_KEY`` 配着,协商说 ``vision_in=unavailable``、理由"当前档位
无视觉模型",于是常驻注意力循环**连截图都不去取** —— 那把能看图的 key 在整个会话里
一次都没被用来看过图。模型对、key 对、路由对,唯独没有一处问过"这次谁来想"。

所以 ``negotiate(locus=...)`` 接受一个**推理归属**:``None``/``"local"`` 表示本地
(与加入本维之前**完全一致**),给 provider 名字则把能力源换成
``core.provider_modality.provider_io()`` —— 那一侧的声明(见该模块:判据全部派生自
``PROVIDER_REGISTRY`` 已有字段,不臆造)。

**换的是能力源,不是桥**:ASR/TTS 始终跑在本机,与谁来想无关。所以远端不原生听时
仍然是 ``bridge`` 而不是 ``unavailable``。

**换的也不是设备**:设备维在最后照常叠加,且仍然只收紧 —— 云端再能看,手表上也
没有摄像头去采那一帧。

**谁该传 locus,谁不该**(这条边界是有意划的,别顺手接):

* 传:知道这一次交给谁的调用方 —— 观测端点(``GET /api/v1/modality/plan?locus=``)、
  渲染契约的通路位(``core.render_pathway``,那是**描述**不是控制)。
* 不传:常驻语音/注意力循环与 ``core.modality_bridge``。它们不是每段音频都过一次
  角色路由,拿"上一次角色路由恰好落在云端"去决定这段音频要不要走本地 ASR,会在
  某次把关角色路由到云端之后,把麦克风那条链整个跳掉 —— 而那次路由跟这段音频
  毫无关系。它们按本地那份能力源走,是对的。

**服务现实那道门按 locus 换主**:``GALAXY_NATIVE_AUDIO`` 说的是本地 Ollama
``/api/chat`` 还没有音频字段,对云端毫无意义 —— 拿它去卡 OpenAI Realtime,会把一个
真能吃音频的接口判成"服务未开"。远端那一侧的服务现实已经编码在 provider 声明里
(有 ``realtime_models`` 才算原生听说),所以远端不再看这个 env,``limited_by`` 也
相应报 ``"provider"`` 而不是 ``"serving"``:前者要换一家,后者开个环境变量就行,
对调用方是两件不同的事。

self-contained:纯读能力 + 环境门控 + 轻量 import 探测,无重型副作用;
negotiate() 可注入 effective_io / device / locus 便于单测(不加载真实模型、不连 UDM)。
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
    #: 是谁把这个模态限制住的:``""``(没被限制) | ``"model"`` | ``"serving"`` |
    #: ``"device"`` | ``"provider"``。
    #: reason 是给人看的,这个是给代码看的 —— 否则调用方想区分"换个模型就能用"和
    #: "换台设备才能用",只能去正则匹配那句中文。
    #:
    #: ``"provider"`` 与 ``"serving"`` 刻意分开:后者开个 ``GALAXY_NATIVE_AUDIO``
    #: 就能过,前者得换一家云端。合成一个的话,面板只能提示"服务未开",而用户开遍
    #: 所有环境变量也不会有任何变化。
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
    #: 这份计划假定**由谁来想**:``"local"`` 或某家 provider 名。见模块头"第四维"。
    #: 恒有值(默认 ``"local"``)—— 空串会让读的人分不清"本地"和"没协商过"。
    locus: str = "local"

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
            "locus": self.locus,
            VISION_IN: self.vision_in.to_dict(),
            AUDIO_IN: self.audio_in.to_dict(),
            AUDIO_OUT: self.audio_out.to_dict(),
            VIDEO_IN: self.video_in.to_dict(),
        }


# ── 推理归属维(第四维):这次由谁来想 ────────────────────────────────────────

LOCAL_LOCUS = "local"


@dataclass(frozen=True)
class ServingReality:
    """ "声明支持" 与 "真能喂进去" 之间那道门 —— 本地和远端不是同一道。

    本地这道门是 ``GALAXY_NATIVE_AUDIO`` / ``GALAXY_NATIVE_VIDEO``:模型声明会听,
    但 Ollama ``/api/chat`` 没有音频字段,所以默认关。远端那道门在 provider 声明
    里就已经算过了(有 realtime 接口才算原生听说),不该再被本地 env 卡一次。

    ``limit_label`` 决定被卡住时 ``limited_by`` 报什么 —— 见 ``ModalityResolution``。
    """

    audio_native_served: bool
    video_native_served: bool
    #: 声明了原生、却被这道门卡住时报什么:``"serving"``(开 env 就能过)|
    #: ``"provider"``(得换一家)。
    limit_label: str
    #: 能力源本身就说不会时报什么:``"model"``(换个模型)| ``"provider"``(换一家)。
    #: 与 ``limit_label`` 分开,是因为本地这两件事确实不同 —— "模型不会听"要换模型,
    #: "服务没开"改个环境变量就行。远端两者合一(都得换一家),但仍各报各的名字,
    #: 免得调用方以为远端也有个环境变量可以开。
    capability_label: str
    #: 声明了原生、却被这道门卡住时那句人话。
    audio_hint: str
    video_hint: str
    #: 能力源本身就说不会时那句人话。与 hint 分开:本地那种情形是"模型不原生听",
    #: 远端那种是"这家没有音频接口" —— 混用会让本地的日志说出"服务未开",
    #: 而那台机器上根本没有一个开关可开。
    audio_incapable_hint: str = "模型不原生听/说"
    video_incapable_hint: str = "模型不原生看视频"

    @property
    def is_remote(self) -> bool:
        return self.capability_label == "provider"

    @classmethod
    def local(cls) -> "ServingReality":
        return cls(
            audio_native_served=_native_audio_serving_enabled(),
            video_native_served=_native_video_serving_enabled(),
            limit_label="serving",
            capability_label="model",
            audio_hint="服务未开(GALAXY_NATIVE_AUDIO)",
            video_hint="视频服务未开(GALAXY_NATIVE_VIDEO)",
            audio_incapable_hint="模型不原生听/说",
            video_incapable_hint="模型不原生看视频",
        )

    @classmethod
    def remote(cls, provider: str) -> "ServingReality":
        # 远端没有"声明了但服务没开"这一档:provider_io 只在该家确实有对应接口时
        # 才报 native,所以声明本身就是服务现实。
        return cls(
            audio_native_served=True,
            video_native_served=True,
            limit_label="provider",
            capability_label="provider",
            audio_hint=f"{provider} 无原生音频接口",
            video_hint=f"{provider} 无原生视频接口",
            audio_incapable_hint=f"{provider} 无原生音频接口",
            video_incapable_hint=f"{provider} 无原生视频接口",
        )


def _locus_capability(locus: Optional[str]) -> tuple:
    """按推理归属取能力源。返回 ``(effio_or_None, locus_name, serving)``。

    ``effio_or_None`` 为 None 表示"这一维没给出能力信息",由调用方回落到本地档位 ——
    包括 locus 指了一家 registry 里**不存在**的 provider:那是配置写错,不是
    "这家什么都不会",按未知处理(未知不设卡,与设备维同一条)。
    """
    name = str(locus or "").strip().lower()
    if not name or name == LOCAL_LOCUS:
        return None, LOCAL_LOCUS, ServingReality.local()
    try:
        from core.provider_modality import provider_io  # noqa: PLC0415

        pio = provider_io(name)
    except Exception as exc:  # noqa: BLE001 — 远端能力源不可用不能让协商崩
        logger.debug("远端模态能力源不可用,按本地协商 locus=%s: %s", name, exc)
        pio = None
    if pio is None:
        logger.debug("provider 表里没有 %s,推理归属维不设卡", name)
        return None, LOCAL_LOCUS, ServingReality.local()
    return pio, pio.provider, ServingReality.remote(pio.provider)


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


def _resolve_audio_in(effio, *, asr_ok: bool, serving: Optional[ServingReality] = None) -> ModalityResolution:
    sv = serving or ServingReality.local()
    native = getattr(effio, "audio_in", "asr_bridge") == "native"
    if native and sv.audio_native_served:
        return ModalityResolution(AUDIO_IN, "native", "原生听 + 音频接口就绪", True)
    if asr_ok:
        why = f"声明原生听但{sv.audio_hint} → ASR 转写" if native else f"{sv.audio_incapable_hint} → ASR 转写"
        return ModalityResolution(
            AUDIO_IN, "bridge", why, native, limited_by=sv.limit_label if native else sv.capability_label
        )
    return ModalityResolution(
        AUDIO_IN, "unavailable", "无原生音频服务、也未装 ASR(faster-whisper/funasr)", native, limited_by=sv.limit_label
    )


def _resolve_audio_out(effio, *, tts_ok: bool, serving: Optional[ServingReality] = None) -> ModalityResolution:
    sv = serving or ServingReality.local()
    native = getattr(effio, "audio_out", "tts_bridge") == "native"
    if native and sv.audio_native_served:
        return ModalityResolution(AUDIO_OUT, "native", "原生说 + 音频接口就绪", True)
    if tts_ok:
        why = f"声明原生说但{sv.audio_hint} → TTS 合成" if native else f"{sv.audio_incapable_hint} → TTS 合成"
        return ModalityResolution(
            AUDIO_OUT, "bridge", why, native, limited_by=sv.limit_label if native else sv.capability_label
        )
    return ModalityResolution(
        AUDIO_OUT, "unavailable", "无原生语音服务、也无可用 TTS", native, limited_by=sv.limit_label
    )


def _resolve_vision_in(effio, *, serving: Optional[ServingReality] = None) -> ModalityResolution:
    sv = serving or ServingReality.local()
    if getattr(effio, "vision", "none") == "native":
        return ModalityResolution(VISION_IN, "native", "原生看图(摄像头/屏幕静帧直接进上下文)", True)
    # 视觉没有桥:抽帧只把视频降成静帧,变不出"看"这件事本身。所以能力源说没有就是没有,
    # 归因随 locus 走 —— 本地是换模型,远端是换 provider。
    why = (
        "这家不接受图像输入(换一家能看的即自动启用)" if sv.is_remote else "当前档位无视觉模型(换含视觉的模型即自动启用)"
    )
    return ModalityResolution(VISION_IN, "unavailable", why, False, limited_by=sv.capability_label)


def _resolve_video_in(effio, *, serving: Optional[ServingReality] = None) -> ModalityResolution:
    sv = serving or ServingReality.local()
    v = getattr(effio, "video", "none")
    if v == "native" and sv.video_native_served:
        return ModalityResolution(VIDEO_IN, "native", "原生理解连续帧 + 视频接口就绪", True)
    if v in ("native", "frames_bridge"):
        native = v == "native"
        why = f"声明原生但{sv.video_hint} → 抽静帧走视觉" if native else f"{sv.video_incapable_hint} → 抽静帧走视觉"
        return ModalityResolution(
            VIDEO_IN, "bridge", why, native, limited_by=sv.limit_label if native else sv.capability_label
        )
    return ModalityResolution(
        VIDEO_IN, "unavailable", "无视觉能力,无法从视频抽帧理解", False, limited_by=sv.capability_label
    )


def negotiate(
    *,
    effio: Any = None,
    tier: Optional[str] = None,
    asr_available: Optional[bool] = None,
    tts_available: Optional[bool] = None,
    device: Any = None,
    locus: Optional[str] = None,
) -> ModalityPlan:
    """协商当前(或指定)档位、(可选)指定设备、(可选)指定推理归属上的全模态计划。

    Args:
        effio: 直接注入 EffectiveIO(测试用);None 则按 locus 取能力源。
        tier: 指定档位 key;None 用当前已选档位。仅在 locus 为本地时有意义。
        asr_available/tts_available: 覆盖桥可用性探测(测试用)。
        device: 目标设备 —— ``UnifiedDevice`` / dict / ``device_id`` 字符串 / None。
            None 表示不区分设备(本机),此时行为与加入设备维之前**完全一致**。
            给了设备则叠加硬件门控:只收紧不放宽,且未申报能力的设备不设卡。
        locus: 这次由谁来想 —— ``None``/``"local"`` 为本地(与加入本维之前**完全
            一致**),给 provider 名则改用该家的模态声明当能力源。见模块头"第四维"。
            名字不在 provider 表里时按未知处理(退回本地),不静默当成"这家什么都不会"。

    显式传了 ``effio`` 时,它**压过** locus 的能力源:注入是为了不碰真实能力表地
    测协商逻辑,再去查 provider 表就把注入的那份架空了。此时 locus 仍然生效 ——
    它决定的是那道服务门归谁(见 :class:`ServingReality`)。
    """
    remote_io, locus_name, serving = _locus_capability(locus)

    if effio is None and remote_io is not None:
        effio = remote_io

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
        vision_in=_apply_device_gate(_resolve_vision_in(effio, serving=serving), gate),
        audio_in=_apply_device_gate(_resolve_audio_in(effio, asr_ok=asr_ok, serving=serving), gate),
        audio_out=_apply_device_gate(_resolve_audio_out(effio, tts_ok=tts_ok, serving=serving), gate),
        video_in=_apply_device_gate(_resolve_video_in(effio, serving=serving), gate),
        tier=tier or "",
        device_id=gate.device_id,
        locus=locus_name,
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
    "第四维 locus=这次由谁来想: local 用 model_catalog.EffectiveIO, provider 名用 "
    "core.provider_modality.provider_io(); 桥恒在本地, 设备维照常只收紧; "
    "limited_by 远端报 provider(得换一家)而非 serving(开 env 就行). "
    "所有循环(voice/ambient/computer_use/ingest)据此自适配,不写死 per-model 分支."
)

__all__ = [
    "VISION_IN",
    "AUDIO_IN",
    "AUDIO_OUT",
    "VIDEO_IN",
    "ModalityResolution",
    "ModalityPlan",
    "ServingReality",
    "LOCAL_LOCUS",
    "negotiate",
    "DeviceModalityGate",
    "iter_known_devices",
    "devices_capable_of",
    "device_modality_matrix",
    "asr_bridge_available",
    "tts_bridge_available",
    "MODALITY_CAPABILITY_AUTHORITY",
]
