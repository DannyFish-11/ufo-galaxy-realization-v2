"""
core/audio_pipeline.py
======================
原生音频理解管道 —— 把麦克风音频「原生」送给具备音频能力的模型。

设计与 ``core/vision_pipeline.py`` 对齐：统一路由的 chat() 只收文本 messages、
不携带原生媒体 content block；图像是经各自的 provider 专用调用（VisionPipeline）
原生送出的。音频此前**完全没有**原生通路。本模块补上：

- Gemini：``contents[].parts[].inline_data{mime_type,data}`` —— 与图像完全相同的
  inline_data 结构，原生支持音频字节。
- OpenAI 兼容（gpt-4o-audio 等）：``content:[{"type":"input_audio","input_audio":
  {"data","format"}}, {"type":"text"}]`` —— 原生音频 content block。

按已配置的 API Key 选择 provider；都没配置则优雅降级返回未配置错误。
payload 构造抽成纯函数（``build_gemini_payload`` / ``build_openai_audio_payload``）
以便单测。任何网络/解析失败都返回结构化错误，绝不抛出影响主流程。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger("Galaxy.AudioPipeline")


# ── 纯函数：原生音频 payload 构造（可单测，不依赖网络）────────────────────────

def _openai_audio_format(mime: str) -> str:
    """从 mime 推断 OpenAI input_audio 的 format 字段。"""
    m = (mime or "").lower()
    if "wav" in m:
        return "wav"
    if "mp3" in m or "mpeg" in m:
        return "mp3"
    if "webm" in m:
        return "webm"
    if "ogg" in m:
        return "ogg"
    if "m4a" in m or "mp4" in m or "aac" in m:
        return "m4a"
    return "wav"


def build_gemini_payload(audio_base64: str, mime: str, prompt: str) -> Dict[str, Any]:
    """Gemini generateContent 原生音频 payload（inline_data，与图像同构）。"""
    return {
        "contents": [
            {
                "parts": [
                    {"inline_data": {"mime_type": mime or "audio/webm", "data": audio_base64}},
                    {"text": prompt},
                ]
            }
        ],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2048},
    }


def build_openai_audio_payload(audio_base64: str, mime: str, prompt: str, model: str) -> Dict[str, Any]:
    """OpenAI 兼容 chat/completions 原生音频 payload（input_audio content block）。"""
    return {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {"data": audio_base64, "format": _openai_audio_format(mime)},
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        "max_tokens": 2048,
        "temperature": 0.2,
    }


_DEFAULT_PROMPT = "请听这段音频并简要描述/转写其内容（说话人在说什么、关键意图）。"


class AudioPipeline:
    """原生音频理解：把音频字节送给音频能力模型，返回文本理解/转写。"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        # Gemini（与 VisionPipeline 同源 key）
        self.gemini_api_key = self.config.get(
            "gemini_api_key", os.getenv("GEMINI_API_KEY", os.getenv("GOOGLE_API_KEY", ""))
        )
        self.gemini_model = self.config.get(
            "gemini_audio_model", os.getenv("GEMINI_AUDIO_MODEL", "gemini-2.0-flash")
        )
        # OpenAI 兼容音频模型
        self.openai_api_key = self.config.get("openai_api_key", os.getenv("OPENAI_API_KEY", ""))
        self.openai_api_base = self.config.get(
            "openai_api_base", os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
        )
        self.openai_audio_model = self.config.get(
            "openai_audio_model", os.getenv("OPENAI_AUDIO_MODEL", "gpt-4o-audio-preview")
        )
        self._client = None

    def available(self) -> bool:
        return bool(self.gemini_api_key or self.openai_api_key)

    async def _get_client(self):
        import httpx
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=60.0)
        return self._client

    async def understand(
        self,
        audio_base64: str,
        *,
        mime: str = "audio/webm",
        prompt: str = "",
    ) -> Dict[str, Any]:
        """原生理解一段音频，返回 ``{success, text, engine, error?}``。"""
        if not audio_base64:
            return {"success": False, "error": "no_audio", "text": ""}
        prompt = prompt or _DEFAULT_PROMPT

        # 优先 Gemini（inline_data 原生音频），再 OpenAI input_audio
        if self.gemini_api_key:
            out = await self._call_gemini(audio_base64, mime, prompt)
            if out is not None:
                return {"success": True, "text": out, "engine": "gemini"}
        if self.openai_api_key:
            out = await self._call_openai(audio_base64, mime, prompt)
            if out is not None:
                return {"success": True, "text": out, "engine": "openai"}
        return {"success": False, "error": "no_audio_capable_provider_configured", "text": ""}

    async def _call_gemini(self, audio_base64: str, mime: str, prompt: str) -> Optional[str]:
        try:
            client = await self._get_client()
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{self.gemini_model}:generateContent?key={self.gemini_api_key}"
            )
            payload = build_gemini_payload(audio_base64, mime, prompt)
            resp = await client.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=60.0)
            resp.raise_for_status()
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:  # noqa: BLE001
            logger.warning("Gemini 原生音频调用失败: %s", e)
            return None

    async def _call_openai(self, audio_base64: str, mime: str, prompt: str) -> Optional[str]:
        try:
            client = await self._get_client()
            payload = build_openai_audio_payload(audio_base64, mime, prompt, self.openai_audio_model)
            resp = await client.post(
                f"{self.openai_api_base}/chat/completions",
                headers={"Authorization": f"Bearer {self.openai_api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=60.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:  # noqa: BLE001
            logger.warning("OpenAI 原生音频调用失败: %s", e)
            return None


_pipeline: Optional[AudioPipeline] = None


def get_audio_pipeline() -> AudioPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = AudioPipeline()
    return _pipeline
