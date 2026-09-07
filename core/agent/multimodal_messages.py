"""core/agent/multimodal_messages.py — 通用对话路径的原生多模态消息构造。

把 MultiModalContext 里的图像构造成 **OpenAI 风格 content 数组**(text + image_url
data URL),让图像在普通 chat 里也能**原生送达模型**(不再被文本摘要化)。

这个数组是仓内的**规范表示**;发出去之前由 ``core.modality.to_native`` 翻译成
各条协议的原生形状(Anthropic 的 base64 source 块 / Responses 的 input_image /
Ollama 的 message 级 images)。

**2026-09-06 起默认开。** 此前默认关,理由写在这里:"仅对 OpenAI 兼容 provider
安全,别的适配器会对 ``m["content"]`` 做字符串拼接,收到数组会崩"。那句话当时是
对的 —— 而它描述的是一个**没修的缺陷**,不是一条该长期存在的限制。现在四条传输
都过 ``core.modality``,那个理由不再成立,所以默认跟着改。

关掉它(``GALAXY_NATIVE_MM_CHAT=0``)仍然有效:图会被压成文字摘要,行为回到以前。
留这个开关是给"上游临时不认某种部件"那种时候用的,不是给日常用的。
"""

from __future__ import annotations

import os
from typing import Any, List, Union

MULTIMODAL_TASK_KEY = "__multimodal_context__"
"""执行路径上 task dict 里承载 MultiModalContext 的键名。

task dict 会被 ``json.dumps`` 成 user 消息，而 MultiModalContext 是 pydantic 对象、
根本不可序列化。约定这个键之后，消费端（``agent_factory._execute_single_task``）先把它
摘出来交给 :func:`build_user_message_content`，剩下的部分才 dumps —— 生产端和消费端
共用同一个常量，改名不会漏掉一边。
"""


def native_mm_enabled() -> bool:
    return os.getenv("GALAXY_NATIVE_MM_CHAT", "1").strip().lower() in ("1", "true", "yes", "on")


def native_audio_wanted(multimodal_context: Any = None) -> bool:
    """这一轮**要不要把音频原样发给模型**。默认不要。

    ## 为什么图像默认发、音频默认不发

    不是保守,是这两件事的性价比不一样:

    * 图像:ASR 那样的"转成文字"没有对应物,不发原生就是**什么都没有**;
    * 音频:本仓的 ASR(``core/asr/``)已经把"他说了什么"转成文字进主链了,
      而那是绝大多数轮次真正需要的东西。原生音频多出来的只有**文字丢掉的那部分**
      —— 语气、情绪、环境声、多人重叠、音乐。

    多出来的这部分不是不值钱,是**不是每轮都值那个钱**:音频 token 贵、吃上下文,
    而且只有少数型号收(见 core.modality.MODEL_MODALITIES)。所以默认走 ASR,
    需要时再升级。

    ## 什么算"需要时"

    两条,都要是**显式**的 —— 系统不去猜"这一轮大概需要听语气":

    * ``GALAXY_NATIVE_AUDIO_CHAT=1`` —— 用户在设置里说"一律发";
    * 这一次请求的 ``metadata`` 里带 ``want_native_audio`` —— 调用方(上层判断
      这一轮需要语气/环境声,或者用户就是这么要求的)自己点名。

    判据只此一处。散着写的话,"这一轮到底发没发音频"会变成一个没人答得上来的问题。
    """
    if os.getenv("GALAXY_NATIVE_AUDIO_CHAT", "0").strip().lower() in ("1", "true", "yes", "on"):
        return True
    meta = getattr(multimodal_context, "metadata", None) or {}
    try:
        return bool(meta.get("want_native_audio"))
    except AttributeError:  # metadata 不是 dict 的历史数据
        return False


#: 一次请求最多附几段音频。比图像更紧:一段几十秒的录音就能顶掉整个上下文。
MAX_AUDIO_CLIPS = 2


#: 单次请求最多附多少张【静止图】(视频关键帧另有 MAX_KEYFRAMES 上限)。
MAX_IMAGES = 4


def _audio_format(mime: str) -> str:
    """mime → OpenAI ``input_audio`` 的 format 字段。

    换算本身在 ``core.audio_pipeline._openai_audio_format`` —— 那条路早就在用它,
    这里转调而不是照抄一份:同一个换算写两遍,总有一天两边认的格式不一样,
    而症状是"某种录音格式在对话里发不出去、在那条旁路里却好好的"。
    """
    from core.audio_pipeline import _openai_audio_format

    return _openai_audio_format(mime or "")


def _dedupe_against(parts: List[dict], seen_urls: set) -> List[dict]:
    """丢掉与已附静止图逐字相同的关键帧（连同它前面那行标注）。

    关键帧序列的最后一帧几乎必然就是"当前这一帧" —— 它已经作为静止图附过一次。
    不去重就是把同一张整屏截图发两遍：钱翻倍，而模型多看一遍也不会多知道什么。
    """
    out: List[dict] = []
    for i in range(0, len(parts) - 1, 2):
        label, image = parts[i], parts[i + 1]
        url = image.get("image_url", {}).get("url")
        if url in seen_urls:
            continue
        seen_urls.add(url)
        out.extend([label, image])
    return out


def build_user_message_content(text: str, multimodal_context: Any) -> Union[str, List[dict]]:
    """有图像/视频且启用时返回 OpenAI content 数组;否则返回纯文本 ``text``。"""
    if not native_mm_enabled() or multimodal_context is None:
        return text
    images = getattr(multimodal_context, "images", None) or []
    videos = getattr(multimodal_context, "video", None) or []
    audio = (getattr(multimodal_context, "audio", None) or []) if native_audio_wanted(multimodal_context) else []
    if not images and not videos and not audio:
        return text
    content: List[dict] = [{"type": "text", "text": text}]
    seen_urls: set = set()
    for im in images[:MAX_IMAGES]:
        mime = getattr(im, "mime", "image/jpeg") or "image/jpeg"
        data = getattr(im, "data", "") or ""
        if data:
            url = f"data:{mime};base64,{data}"
            seen_urls.add(url)
            content.append({"type": "image_url", "image_url": {"url": url}})
    # 视频排在静止图之后:静止图是"此刻",关键帧序列是"这段时间里发生了什么",
    # 后者带自己的时间戳标注,放在末尾不会被误读成对前面那张图的说明。
    if videos:
        from core.video_keyframes import build_video_content_parts

        for vid in videos[:1]:  # 一次一段:两段视频的时间轴叠在一个 content 数组里没法区分
            content.extend(_dedupe_against(build_video_content_parts(vid), seen_urls))
    # 音频排在最后。形状用 OpenAI 的 ``input_audio`` —— 那是仓内的规范表示,
    # 各条传输由 core.modality.to_native 各自翻译(装不下的会如实摘掉并留痕)。
    for clip in audio[:MAX_AUDIO_CLIPS]:
        data = getattr(clip, "data", "") or ""
        if not data:
            continue
        content.append(
            {
                "type": "input_audio",
                "input_audio": {"data": data, "format": _audio_format(getattr(clip, "mime", ""))},
            }
        )
    return content if len(content) > 1 else text
