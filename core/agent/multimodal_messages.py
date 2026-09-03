"""core/agent/multimodal_messages.py — 通用对话路径的原生多模态消息构造。

把 MultiModalContext 里的图像构造成 **OpenAI 风格 content 数组**(text + image_url
data URL),让图像在普通 chat 里也能**原生送达模型**(不再被文本摘要化)。

⚠️ 仅对 **OpenAI 兼容 provider** 安全(它们原样转发 messages)。Gemini 等适配器会对
``m["content"]`` 做字符串拼接,收到数组会崩——因此默认**关闭**,需 OpenAI 兼容主链
且显式开启 ``GALAXY_NATIVE_MM_CHAT=1`` 才生效。关闭时返回纯文本,行为与原先一致。
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
    return os.getenv("GALAXY_NATIVE_MM_CHAT", "0").strip().lower() in ("1", "true", "yes", "on")


#: 单次请求最多附多少张【静止图】(视频关键帧另有 MAX_KEYFRAMES 上限)。
MAX_IMAGES = 4


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
    if not images and not videos:
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
    return content if len(content) > 1 else text
