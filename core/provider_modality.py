"""core/provider_modality.py — 云端 provider 的模态声明（远端这一侧的能力源）
=============================================================================

本地那一侧早就有能力源:``core.model_catalog.EffectiveIO`` —— 每个本地模型声明
自己看/听/说/看视频的原生能力,``tier_effective_io()`` 把**正在跑的**那几个合起来。
``core.modality_capability.negotiate()`` 据此决定每个模态走原生还是走桥。

**远端那一侧一直没有。** ``PROVIDER_REGISTRY`` 里只有一个 ``extra["multimodal"]``
布尔 —— 它说"这家不只会文字",但说不出**是哪个模态**。于是协商层拿不到任何可用的
远端判据,只能一律按本地档位作答。后果不是"少一个功能",是**误判**:

    本地档位 = A(gemma4:e2b,无视觉) + 配了 OPENAI_API_KEY
    negotiate().vision_in → unavailable,理由"当前档位无视觉模型"
    → 常驻注意力循环连截图都不去取
    → 那把能看图的云端 key 在整个会话里一次都没被用到看图

模型是对的、key 是对的、路由是对的,唯独没有任何一处**问过**"这次要交给谁想"。

声明从哪来:只从仓内已有的事实派生
----------------------------------
这里**不新增任何关于外部模型的事实**。每一格都从 ``PROVIDER_REGISTRY`` 里已经
存在的字段推出来,推导规则写在下面并由测试钉住:

===============  ========================================================
模态             判据(全部来自 registry 已有字段)
===============  ========================================================
``vision``       ``extra.multimodal`` 或 ``extra.supports_vision`` 为真
``audio_in``     该家列了 ``realtime_models``(有原生音频接口才算原生听)
``audio_out``    同上
``video``        与 :func:`core.model_catalog.effective_io` 同规则:
                 有原生视频则 native,否则有静帧视觉则 frames_bridge
``tools``        ``extra.supports_tools``,未声明按真(绝大多数家都支持)
===============  ========================================================

**为什么原生音频要拿 realtime_models 当判据而不是 multimodal 布尔**:走
Chat Completions 发过去的是文本,音频进不去 —— 能真正吃音频的是各家的 realtime /
Live 接口,而那批型号在 registry 里是**单独一列**(``realtime_models``,当初分开
就是因为它与文本型号走不同接口、下线节奏也不同)。拿 ``multimodal`` 判原生听,
会让协商层对着一个收不了音频的接口说"原生听",于是本地 ASR 桥被跳过,发出去的
请求里没有任何可听的东西 —— 又一次"看起来接上了,其实没有"。

**宁可少报,不可多报**:少报的代价是某个能力没被用上(可由
``scripts/probe_models.py`` 真机对账后补声明);多报的代价是链路在**别处**静默失败,
而失败点离原因十万八千里。这与本仓"不臆造数字"是同一条。

显式覆盖
--------
provider spec 里写 ``"modalities": {...}`` 即整格覆盖派生结果 —— 真机探测出来的
结论比推导权威。只写其中几个键也行,没写的仍走派生。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger("Galaxy.ProviderModality")

#: 与 ``EffectiveIO`` 逐字段同名同取值域 —— 协商层两侧共用一套词汇,才谈得上
#: "换个 locus 就换个能力源"。改这里必须同步 ``core.model_catalog.EffectiveIO``。
MODALITY_FIELDS: tuple = ("vision", "audio_in", "audio_out", "video")

VISION_VALUES: tuple = ("native", "none")
AUDIO_IN_VALUES: tuple = ("native", "asr_bridge")
AUDIO_OUT_VALUES: tuple = ("native", "tts_bridge")
VIDEO_VALUES: tuple = ("native", "frames_bridge", "none")

_VALUES_OF: Dict[str, tuple] = {
    "vision": VISION_VALUES,
    "audio_in": AUDIO_IN_VALUES,
    "audio_out": AUDIO_OUT_VALUES,
    "video": VIDEO_VALUES,
}


@dataclass(frozen=True)
class ProviderIO:
    """一家云端 provider 对外呈现的模态通路。

    刻意与 ``core.model_catalog.EffectiveIO`` **同形**:协商层按 locus 取其中一份
    当能力源,两份形状不一样的话,取哪一份就得写两套解析,分支立刻开始漂移。
    """

    provider: str
    vision: str = "none"
    audio_in: str = "asr_bridge"
    audio_out: str = "tts_bridge"
    tools: bool = True
    video: str = "none"
    #: 这份声明是派生来的还是 spec 里显式写的 —— 前者可被真机探测推翻,后者不该被。
    declared: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "vision": self.vision,
            "audio_in": self.audio_in,
            "audio_out": self.audio_out,
            "tools": self.tools,
            "video": self.video,
            "declared": self.declared,
        }


def _registry() -> list:
    """取 ``PROVIDER_REGISTRY``;取不到返回空表(→ 所有家按未知处理,不设卡)。"""
    try:
        from core.multi_llm_router import PROVIDER_REGISTRY  # noqa: PLC0415

        return list(PROVIDER_REGISTRY or [])
    except Exception as exc:  # noqa: BLE001 — provider 表不可用不能让协商崩
        logger.debug("provider 表不可用,远端模态一律按未知处理: %s", exc)
        return []


def provider_spec(name: str) -> Optional[Dict[str, Any]]:
    """按名字取 provider spec;没有这家返回 None(**不是**空 dict)。

    空 dict 会让调用方读到一堆默认值、以为查到了一家什么都不会的 provider;
    None 说的是"没这家",两者对协商是两回事。
    """
    if not name:
        return None
    key = str(name).strip().lower()
    for spec in _registry():
        if str(spec.get("name", "")).strip().lower() == key:
            return spec
    return None


def _derive(spec: Dict[str, Any]) -> Dict[str, Any]:
    """按模块头那张表从 registry 已有字段推出四个模态 + tools。"""
    extra = spec.get("extra") or {}
    has_vision = bool(extra.get("multimodal") or extra.get("supports_vision"))
    # 有 realtime/Live 接口才谈得上原生听说 —— 见模块头。
    has_realtime = bool(spec.get("realtime_models") or spec.get("default_realtime_model"))
    return {
        "vision": "native" if has_vision else "none",
        "audio_in": "native" if has_realtime else "asr_bridge",
        "audio_out": "native" if has_realtime else "tts_bridge",
        # 与 model_catalog.effective_io 同一条规则:原生视频 > 抽静帧 > 无。
        # registry 目前没有任何一家声明原生视频,所以这里只会落在后两档。
        "video": "frames_bridge" if has_vision else "none",
        "tools": bool(extra.get("supports_tools", True)),
    }


def _sanitise(field: str, value: Any, fallback: str) -> str:
    """覆盖值不在该字段取值域里时退回派生值,并留一条日志。

    静默接受一个拼错的值,等于让协商层拿着 ``"vision": "nativ"`` 判 unavailable ——
    看起来是"这家不支持",实际是打字错误。
    """
    v = str(value).strip().lower()
    if v in _VALUES_OF[field]:
        return v
    logger.warning("provider 模态声明取值非法,已退回派生值 field=%s value=%r", field, value)
    return fallback


def provider_io(name: str) -> Optional[ProviderIO]:
    """这家 provider 的模态通路;没有这家返回 None。

    spec 里的 ``modalities`` 逐键覆盖派生结果 —— 真机对账的结论比推导权威。
    """
    spec = provider_spec(name)
    if spec is None:
        return None

    derived = _derive(spec)
    override = spec.get("modalities") or {}
    if not isinstance(override, dict):
        logger.warning("provider %s 的 modalities 不是字典,已忽略: %r", name, override)
        override = {}

    values = dict(derived)
    for field in MODALITY_FIELDS:
        if field in override:
            values[field] = _sanitise(field, override[field], derived[field])
    if "tools" in override:
        values["tools"] = bool(override["tools"])

    return ProviderIO(
        provider=str(spec.get("name", name)),
        vision=values["vision"],
        audio_in=values["audio_in"],
        audio_out=values["audio_out"],
        tools=values["tools"],
        video=values["video"],
        declared=bool(override),
    )


def providers_native_in(field: str) -> list:
    """**原生**支持某个模态的 provider 名单(按名字稳定排序)。

    与 ``core.modality_capability.devices_capable_of`` 是同一件事的远端版本:
    要挑一家"能看"的云端时直接问这里,而不是发出去再等它把图丢掉。

    刻意只数 ``native``,不数桥
    --------------------------
    第一版写的是"取值不为 none 即入选",结果 ``audio_in`` 一栏把 17 家全列了进去 ——
    因为不原生听的那些取值是 ``asr_bridge``,而它压根不是这家的能力,是**本机**
    装了 ASR。一份"谁能听"的名单里出现从来没有音频接口的家,对派发决策没有任何
    信息量,却看起来像结论。桥在本地,与选哪家无关;这份名单要回答的是"换哪家能
    省掉那道桥"。
    """
    if field not in MODALITY_FIELDS:
        return []
    out = []
    for spec in _registry():
        io = provider_io(str(spec.get("name", "")))
        if io is None:
            continue
        if getattr(io, field, "none") == "native":
            out.append(io.provider)
    return sorted(set(out))


def provider_modality_matrix() -> Dict[str, Any]:
    """所有 provider × 全模态。供面板与派发决策共用,与设备矩阵对称。"""
    rows = [io.to_dict() for io in (provider_io(str(s.get("name", ""))) for s in _registry()) if io]
    rows.sort(key=lambda r: r["provider"])
    return {
        "provider_count": len(rows),
        "providers": rows,
        "native": {f: providers_native_in(f) for f in MODALITY_FIELDS},
    }


PROVIDER_MODALITY_AUTHORITY: str = (
    "PROVIDER_MODALITY_V1: core/provider_modality.py | 云端 provider 模态声明唯一入口. "
    "provider_io(name) → ProviderIO(vision/audio_in/audio_out/video/tools), 与 "
    "model_catalog.EffectiveIO 同形. 判据全部派生自 PROVIDER_REGISTRY 已有字段: "
    "vision←extra.multimodal|supports_vision, audio_in/out←realtime_models, "
    "video←与 effective_io 同规则, tools←extra.supports_tools. spec 里的 modalities "
    "逐键覆盖. core.modality_capability.negotiate(locus=...) 在远端路由时取本份当能力源."
)

__all__ = [
    "MODALITY_FIELDS",
    "VISION_VALUES",
    "AUDIO_IN_VALUES",
    "AUDIO_OUT_VALUES",
    "VIDEO_VALUES",
    "ProviderIO",
    "provider_spec",
    "provider_io",
    "providers_native_in",
    "provider_modality_matrix",
    "PROVIDER_MODALITY_AUTHORITY",
]
