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


def native_mm_enabled() -> bool:
    return os.getenv("GALAXY_NATIVE_MM_CHAT", "0").strip().lower() in ("1", "true", "yes", "on")


def build_user_message_content(text: str, multimodal_context: Any) -> Union[str, List[dict]]:
    """有图像且启用时返回 OpenAI content 数组;否则返回纯文本 ``text``。"""
    if not native_mm_enabled() or multimodal_context is None:
        return text
    images = getattr(multimodal_context, "images", None) or []
    if not images:
        return text
    content: List[dict] = [{"type": "text", "text": text}]
    for im in images[:4]:  # 最多 4 张,控成本
        mime = getattr(im, "mime", "image/jpeg") or "image/jpeg"
        data = getattr(im, "data", "") or ""
        if data:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{data}"},
                }
            )
    return content if len(content) > 1 else text
