"""core/modality.py — 多模态的**唯一的头**:能收什么 · 怎么装。

## 为什么要有这一个文件

在它之前,"多模态"这件事散在至少六处各说各的:

* ``ProviderConfig.multimodal / supports_vision / supports_audio`` —— 厂商级旗标,
  可"这家有能看图的型号"不等于"这一轮选中的型号能看图";
* ``OllamaAdapter._to_ollama_messages`` —— 只有 Ollama 那条自己会翻译;
* ``AnthropicAdapter`` —— 收到 content 数组会在抽 system 那一步当场炸;
* ``ResponsesAdapter`` —— 原样透传,而 Responses 的图像部件叫 ``input_image``;
* ``core/agent/multimodal_messages.py`` —— 只会造 OpenAI 那一种形状;
* ``core/vision_pipeline.py`` / ``core/audio_pipeline.py`` —— 自己拿 key 自己发。

散着的后果不是"代码重复",是**判断不一致**:选路那一步按厂商说"能看图"、发请求
那一步把图丢了或者发成对面不认的形状,而两边都不报错。这正是本仓最怕的形状。

所以这里收成一处。两节,回答两个问题:

1. **这个型号能收什么**(``input_modalities`` / ``can_receive``)
2. **这条协议怎么装**(``to_native``)

选路问第 1 个,适配器问第 2 个,除此之外没有第三个地方再判一次。

## 关于"不知道"

第 1 节的表**故意不写满**。厂商每周都在放新型号,把没核实过的模态能力写进表里,
就是拿一个编出来的事实去挡真实请求 —— 比不知道更糟。所以:

* 表里有 → ``source="model"``,这是核实过的型号级事实;
* 表里没有 → 回落到 registry 的厂商级声明,``source="provider"``,并**如实说明
  这是继承来的**;
* 两处都没有 → ``source="unknown"``,模态集合为空。**空与未知是两件事**,调用方
  拿得到区别。

要把某个型号从 ``provider`` 升到 ``model``,不靠猜:配好 key 跑
``python scripts/verify_provider_apis.py --probe-modalities``,它会拿一张 1×1 的
真图片去问每个型号,上游收不收由上游说了算。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("Galaxy.Modality")

# ---------------------------------------------------------------------------
# 模态的名字:只有这一份
# ---------------------------------------------------------------------------
TEXT = "text"
IMAGE = "image"
AUDIO = "audio"
VIDEO = "video"

#: 全部模态。顺序固定,便于比较与打印。
ALL_MODALITIES: Tuple[str, ...] = (TEXT, IMAGE, AUDIO, VIDEO)


# ---------------------------------------------------------------------------
# 第 1 节:这个型号能收什么
# ---------------------------------------------------------------------------
#: **型号级**输入模态。按前缀匹配(与 provider_registry.MODEL_QUIRKS 同一套规则:
#: 上游常在正式串后挂日期快照 ``gpt-6-astra-2026-09-01``,精确匹配会让快照串悄悄
#: 绕过判断)。
#:
#: 只登记**有依据**的型号 —— 依据写在旁边。没登记不是"不支持",是"没核实过",
#: 由厂商级声明兜底(见模块开头)。
MODEL_MODALITIES: Dict[str, Tuple[str, ...]] = {
    # 纯代码/纯文本档:这些型号的定位本身就排除了图像输入,把它们从多模态候选里
    # 摘出去,免得带图的请求选中一个看不见图的型号 —— 那时上游要么报错、要么
    # 干脆忽略图像正常作答,而后者**不会有任何人发现**。
    "gpt-5.3-codex": (TEXT,),
    "qwen3.8-coder": (TEXT,),
    "qwen3.7-coder": (TEXT,),
    # Perplexity 的 sonar 系是检索问答,收文本、给带引文的文本。
    "sonar": (TEXT,),
    "sonar-pro": (TEXT,),
    "sonar-reasoning-pro": (TEXT,),
    "sonar-deep-research": (TEXT,),
    # DeepSeek 的对话线一直是纯文本(它的视觉能力在另一条产品线 deepseek-ocr,
    # 本仓走 core/vision_pipeline.py 那条,不在这张表里)。
    "deepseek-v4-pro": (TEXT,),
    "deepseek-v4-flash": (TEXT,),
}

#: 厂商级旗标 → 模态集合的换算。registry 里那几个布尔就是在说这件事,
#: 这里只是把它翻译成同一套词汇,不另立第二套判据。
_PROVIDER_FLAG_TO_MODALITY = (
    ("supports_vision", IMAGE),
    ("supports_audio", AUDIO),
)


@dataclass(frozen=True)
class ModalitySupport:
    """一次模态能力查询的结果 —— **带出处**。

    ``source`` 三态,不许抹平:

    * ``"model"``    型号级核实过的事实
    * ``"provider"`` 从这家的厂商级声明继承来的(可能比真相宽,也可能比真相窄)
    * ``"unknown"``  两处都没有。此时 ``modalities`` 是 ``(TEXT,)`` —— 文本是
                     所有对话型号的下限,但**不要**把它读成"只支持文本",
                     它的意思是"除了文本以外的都没核实过"。
    """

    modalities: Tuple[str, ...]
    source: str

    def can(self, modality: str) -> bool:
        return modality in self.modalities

    @property
    def is_known(self) -> bool:
        return self.source != "unknown"


def _registry_entry(provider: str) -> Optional[Dict[str, Any]]:
    from core.provider_registry import PROVIDER_REGISTRY

    name = (provider or "").strip().lower()
    for entry in PROVIDER_REGISTRY:
        if entry.get("name") == name:
            return entry
    return None


def _model_level(model: str) -> Optional[Tuple[str, ...]]:
    name = (model or "").strip()
    if not name:
        return None
    for key, mods in MODEL_MODALITIES.items():
        if name == key or name.startswith(key + "-"):
            return mods
    return None


def input_modalities(model: str, provider: str = "", cfg: Any = None) -> ModalitySupport:
    """这个型号**能收**哪些模态,以及这个结论是从哪来的。

    ``cfg`` 给了就优先读它(``ProviderConfig`` 上的 multimodal / supports_vision /
    supports_audio)—— 用户自己加的端点、本地 Ollama 都只有 cfg,没有 registry 条目。
    """
    mods = _model_level(model)
    if mods is not None:
        return ModalitySupport(mods, "model")

    flags: Dict[str, Any] = {}
    if cfg is not None:
        for field, _ in _PROVIDER_FLAG_TO_MODALITY:
            if getattr(cfg, field, None):
                flags[field] = True
        if getattr(cfg, "multimodal", False):
            flags["multimodal"] = True
    else:
        entry = _registry_entry(provider)
        if entry:
            extra = entry.get("extra") or {}
            for field, _ in _PROVIDER_FLAG_TO_MODALITY:
                if extra.get(field):
                    flags[field] = True
            if extra.get("multimodal"):
                flags["multimodal"] = True

    if not flags:
        return ModalitySupport((TEXT,), "unknown")

    out: List[str] = [TEXT]
    for field, modality in _PROVIDER_FLAG_TO_MODALITY:
        if flags.get(field):
            out.append(modality)
    if flags.get("multimodal") and IMAGE not in out:
        # registry 里绝大多数条目只写了笼统的 multimodal。它在本仓一直被当作
        # "能看图"用(选路的 has_multimodal 硬过滤读的就是它),这里保持同一读法,
        # 不新造一种解释 —— 但出处标成 provider,提醒这不是型号级事实。
        out.append(IMAGE)
    return ModalitySupport(tuple(out), "provider")


def can_receive(modality: str, model: str, provider: str = "", cfg: Any = None) -> bool:
    """这一轮要送 ``modality``,这个型号收不收。"""
    return input_modalities(model, provider, cfg).can(modality)


def modalities_in(messages: Sequence[Any]) -> Tuple[str, ...]:
    """这批消息里**实际带着**哪些模态。

    判据是消息本身,不是调用方的自述:调用方说"这是多模态请求"而消息里其实没有图,
    会把请求推给一个更贵的型号却什么也没多做;反过来更糟 —— 带着图却按纯文本选路,
    图会在发出前被丢掉,而没有人会发现。
    """
    found = {TEXT}
    for m in messages or ():
        if not isinstance(m, dict):
            continue
        if m.get("images"):
            found.add(IMAGE)
        content = m.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            ptype = part.get("type") or ""
            if ptype in ("image_url", "image", "input_image"):
                found.add(IMAGE)
            elif ptype in ("input_audio", "audio"):
                found.add(AUDIO)
            elif ptype in ("video", "input_video"):
                found.add(VIDEO)
    return tuple(m for m in ALL_MODALITIES if m in found)


# ---------------------------------------------------------------------------
# 第 2 节:这条协议怎么装
# ---------------------------------------------------------------------------
#: 仓内的**规范表示**是 OpenAI chat 的 content 数组
#: (``[{"type":"text",...},{"type":"image_url","image_url":{"url":"data:..."}}]``)——
#: ``core/agent/multimodal_messages.build_user_message_content`` 造的就是它,
#: 上游各处也都按它写。所以这里只做一件事:**把规范表示翻译成这条协议的原生形状**。
#:
#: 四条协议的差别全在这张表描述的范围内,没有别的:
#:
#:   openai     content 数组原样(它就是规范表示)
#:   anthropic  ``{"type":"image","source":{"type":"base64","media_type":..,"data":..}}``
#:   responses  ``{"type":"input_text"}`` / ``{"type":"input_image","image_url":"data:..."}``
#:   ollama     图像挂到 message 级 ``images: ["<纯 base64>"]``,文本拼回字符串
SUPPORTED_WIRE_PROTOCOLS: Tuple[str, ...] = ("openai", "anthropic", "responses", "ollama")


def _split_data_url(url: str) -> Tuple[str, str]:
    """``data:image/png;base64,XXXX`` → ``("image/png", "XXXX")``。

    不是 data URL 就返回 ``("", 原串)`` —— 调用方据此决定是当远程 URL 用还是丢掉。
    """
    if not isinstance(url, str) or not url.startswith("data:"):
        return "", url or ""
    head, _, payload = url.partition(",")
    mime = head[5:].split(";", 1)[0] if len(head) > 5 else ""
    return mime, payload


def _part_image_url(part: Dict[str, Any]) -> str:
    """从规范表示的一个图像部件里取出 url。两种写法都收(嵌套的和平铺的)。"""
    iu = part.get("image_url")
    if isinstance(iu, dict):
        return iu.get("url") or ""
    if isinstance(iu, str):
        return iu
    return part.get("data") or part.get("image") or ""


def _to_anthropic(messages: Sequence[Any]) -> List[Any]:
    """规范表示 → Anthropic Messages 的 content 块。

    这条以前是**炸的**:``AnthropicAdapter`` 抽 system 时写的是
    ``system_text += m["content"]``,content 是数组时当场 TypeError;就算不炸,
    Anthropic 也不认 ``image_url`` 这种块类型,图会被上游拒。
    """
    out: List[Any] = []
    for m in messages:
        if not isinstance(m, dict) or not isinstance(m.get("content"), list):
            out.append(m)
            continue
        blocks: List[Dict[str, Any]] = []
        for part in m["content"]:
            if not isinstance(part, dict):
                blocks.append({"type": "text", "text": str(part)})
                continue
            ptype = part.get("type")
            if ptype in ("text", "input_text"):
                blocks.append({"type": "text", "text": part.get("text", "")})
            elif ptype in ("image_url", "image", "input_image"):
                mime, payload = _split_data_url(_part_image_url(part))
                if not payload:
                    continue
                if mime:
                    blocks.append(
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": mime, "data": payload},
                        }
                    )
                else:
                    # 远程 URL:Anthropic 有 url 型 source,直接给它,别自己去下载 ——
                    # 下载会把一次对话变成一次出网请求,而调用方没有同意过这件事。
                    blocks.append({"type": "image", "source": {"type": "url", "url": payload}})
        out.append({**m, "content": blocks})
    return out


def _to_responses(messages: Sequence[Any]) -> List[Any]:
    """规范表示 → Responses 的 input 部件。

    部件名与 chat 那条**不一样**:``input_text`` / ``input_image``,而且
    ``input_image`` 的 ``image_url`` 是一个**字符串**,不是对象。发成 chat 的形状
    不会报错,只会被当成没带图 —— 又一次"看起来接上了,其实没有"。
    """
    out: List[Any] = []
    for m in messages:
        if not isinstance(m, dict) or not isinstance(m.get("content"), list):
            out.append(m)
            continue
        parts: List[Dict[str, Any]] = []
        for part in m["content"]:
            if not isinstance(part, dict):
                parts.append({"type": "input_text", "text": str(part)})
                continue
            ptype = part.get("type")
            if ptype in ("text", "input_text"):
                parts.append({"type": "input_text", "text": part.get("text", "")})
            elif ptype in ("image_url", "image", "input_image"):
                url = _part_image_url(part)
                if url:
                    parts.append({"type": "input_image", "image_url": url})
        out.append({**m, "content": parts})
    return out


def _to_ollama(messages: Sequence[Any]) -> List[Any]:
    """规范表示 → Ollama /api/chat:图像挂 message 级 ``images``(纯 base64)。

    这一段是从 ``OllamaAdapter._to_ollama_messages`` 原样搬过来的 —— 它本来就是对的,
    搬过来只为了让四条协议的翻译在同一个地方,而不是一条在适配器里、三条在别处。
    """
    out: List[Any] = []
    for m in messages:
        if not isinstance(m, dict):
            out.append(m)
            continue
        content = m.get("content")
        imgs = list(m.get("images") or [])
        if isinstance(content, list):
            text_parts: List[str] = []
            for part in content:
                if not isinstance(part, dict):
                    text_parts.append(str(part))
                    continue
                ptype = part.get("type")
                if ptype in ("text", "input_text"):
                    text_parts.append(part.get("text", ""))
                elif ptype in ("image_url", "image", "input_image"):
                    url = _part_image_url(part)
                    if isinstance(url, str) and url:
                        imgs.append(url.split(",", 1)[1] if url.startswith("data:") else url)
            new_m = {**m, "content": "\n".join(t for t in text_parts if t)}
        else:
            new_m = {**m}
        if imgs:
            new_m["images"] = imgs
        elif "images" in new_m and not new_m["images"]:
            new_m.pop("images", None)
        out.append(new_m)
    return out


_WIRE = {
    "anthropic": _to_anthropic,
    "responses": _to_responses,
    "ollama": _to_ollama,
}


def to_native(protocol: str, messages: Sequence[Any]) -> List[Any]:
    """把规范表示翻译成 ``protocol`` 的原生形状。

    ``openai`` 原样返回 —— 规范表示就是它。不认识的协议名也原样返回并**留痕**:
    悄悄按 OpenAI 发出去,是把一个没实现的协议伪装成实现了。
    """
    proto = (protocol or "openai").strip().lower()
    if proto == "openai":
        return list(messages)
    fn = _WIRE.get(proto)
    if fn is None:
        logger.warning(
            "不认识的传输协议「%s」,消息按 OpenAI 规范形状原样发出。" "带多模态内容时对面很可能收不到 —— 支持的是:%s",
            protocol,
            "、".join(SUPPORTED_WIRE_PROTOCOLS),
        )
        return list(messages)
    return fn(messages)


def flatten_to_text(messages: Sequence[Any]) -> List[Any]:
    """把规范表示压成纯文本消息 —— **降级路径,必须留痕后才用**。

    给"这一轮选中的型号收不了图"那种情况准备的:与其把图发给一个看不见它的型号
    (上游多半不报错,照常作答,于是没人知道它其实没看见),不如显式压成文字并说出来。
    """
    out: List[Any] = []
    for m in messages:
        if not isinstance(m, dict) or not isinstance(m.get("content"), list):
            out.append(m)
            continue
        texts = [
            p.get("text", "") for p in m["content"] if isinstance(p, dict) and p.get("type") in ("text", "input_text")
        ]
        dropped = len(m["content"]) - len(texts)
        note = f"\n[本轮有 {dropped} 项图像/音频内容未发送:所选型号不接收它们]" if dropped else ""
        out.append({**m, "content": "\n".join(t for t in texts if t) + note})
    return out


def text_of(content: Any) -> str:
    """取出一条消息的文字部分。content 可能是字符串,也可能是块数组。

    存在的理由很小但很实在:适配器里那些 ``system_text += m["content"]`` 式的
    字符串拼接,在 content 变成数组的那一天会当场 TypeError。与其每处各写一遍
    ``isinstance`` 判断,不如问这里 —— 少一处各写各的,就少一处会漏改的地方。
    """
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return "" if content is None else str(content)
    out: List[str] = []
    for part in content:
        if isinstance(part, dict):
            if part.get("type") in ("text", "input_text"):
                out.append(part.get("text", ""))
        elif part is not None:
            out.append(str(part))
    return "\n".join(t for t in out if t)


def prepare(
    protocol: str,
    messages: Sequence[Any],
    *,
    model: str = "",
    provider: str = "",
    cfg: Any = None,
) -> List[Any]:
    """**适配器只调这一个函数。** 一次做完三件本来散在各处的事:

    1. 这批消息实际带着哪些模态(看消息本身,不听调用方自述);
    2. 这一轮选中的型号收不收 —— 收不了就**压成文字并说出来**;
    3. 翻译成这条协议的原生形状。

    第 2 步的分寸:只在**核实过**这个型号收不了的时候才压。``source="unknown"``
    (用户自己加的端点、没登记过的型号)一律照发 —— 未知不是"不支持",按"不支持"
    处理会让每一个用户自建的多模态端点永远收不到图,而且不留任何痕迹。
    """
    carried = modalities_in(messages)
    rich = [m for m in carried if m != TEXT]
    if rich:
        support = input_modalities(model, provider, cfg)
        blocked = [m for m in rich if support.is_known and not support.can(m)]
        if blocked:
            logger.warning(
                "这一轮带着 %s,但型号 %s(%s)不接收它们(依据来源:%s)。"
                "已压成文字发出 —— 直接发过去的话上游多半不报错、忽略掉,没人会发现它其实没看见。",
                "、".join(blocked),
                model or "(未指定)",
                provider or "(未指定)",
                support.source,
            )
            messages = flatten_to_text(messages)
    return to_native(protocol, messages)
