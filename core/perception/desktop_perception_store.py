"""
core/perception/desktop_perception_store.py
============================================
桌面端连续感知的「最新帧」存储（隐蔽上下文来源）。

电脑端 Electron 壳通过 getUserMedia 持续采集摄像头/麦克风/屏幕，并以
base64 帧 POST 到网关 /api/perception/desktop/*。本模块是这些帧的进程内
最新值存储（单例），带 TTL 新鲜度判定：

- 当一次正常请求进入 OpenClawd.process() 且本身不带图像时，若存在「新鲜」
  的桌面帧，则把它作为原生多模态上下文注入——于是模型「真的看到了摄像头」。
- 不新鲜（超过 TTL）的帧不会被注入，避免把过期画面喂给模型。

设计原则：轻量、线程安全（简单锁）、永不抛出影响主流程；不持久化、不落盘。
默认 TTL 10s；GALAXY_DESKTOP_PERCEPTION_TTL 可调。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("Galaxy.DesktopPerceptionStore")


def _default_ttl() -> float:
    try:
        return max(1.0, float(os.getenv("GALAXY_DESKTOP_PERCEPTION_TTL", "10")))
    except (ValueError, TypeError):
        return 10.0


class DesktopPerceptionStore:
    """进程内单例：保存桌面端最近一次的摄像头帧 / 屏幕帧 / 音频片段。"""

    _instance: Optional["DesktopPerceptionStore"] = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.ttl_sec = _default_ttl()
        # image (camera or screen)
        self._image_b64: Optional[str] = None
        self._image_mime: str = "image/jpeg"
        self._image_source: str = "desktop_camera"
        self._image_ts: float = 0.0
        self._screen: Optional[Dict[str, Any]] = None
        # audio (microphone)
        self._audio_b64: Optional[str] = None
        self._audio_mime: str = "audio/webm"
        self._audio_ts: float = 0.0
        # counters (diagnostics)
        self._frames_received: int = 0
        self._audio_received: int = 0

    @classmethod
    def get_instance(cls) -> "DesktopPerceptionStore":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── 写入（由 /api/perception/desktop/* 路由调用）────────────────────────

    def update_frame(
        self,
        image_b64: str,
        *,
        mime: str = "image/jpeg",
        source: str = "desktop_camera",
        screen: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not image_b64:
            return
        with self._lock:
            self._image_b64 = image_b64
            self._image_mime = mime or "image/jpeg"
            self._image_source = source or "desktop_camera"
            self._screen = screen
            self._image_ts = time.time()
            self._frames_received += 1

    def update_audio(self, audio_b64: str, *, mime: str = "audio/webm") -> None:
        if not audio_b64:
            return
        with self._lock:
            self._audio_b64 = audio_b64
            self._audio_mime = mime or "audio/webm"
            self._audio_ts = time.time()
            self._audio_received += 1

    # ── 读取 / 新鲜度 ───────────────────────────────────────────────────────

    def _fresh(self, ts: float) -> bool:
        return ts > 0.0 and (time.time() - ts) <= self.ttl_sec

    def has_fresh_frame(self) -> bool:
        with self._lock:
            return bool(self._image_b64) and self._fresh(self._image_ts)

    def status(self) -> Dict[str, Any]:
        with self._lock:
            now = time.time()
            return {
                "ttl_sec": self.ttl_sec,
                "frames_received": self._frames_received,
                "audio_received": self._audio_received,
                "image_fresh": self._fresh(self._image_ts),
                "image_age_sec": round(now - self._image_ts, 2) if self._image_ts else None,
                "image_source": self._image_source if self._image_b64 else None,
                "audio_fresh": self._fresh(self._audio_ts),
                "audio_age_sec": round(now - self._audio_ts, 2) if self._audio_ts else None,
            }

    def build_multimodal_context(self, existing: Optional[Any] = None) -> Optional[Any]:
        """用最新「新鲜」帧/音频构建（或合并进）MultiModalContext。

        - 仅当确有新鲜帧/音频时返回非 None。
        - 若 ``existing`` 已带图像，则不覆盖（尊重显式请求），返回 None。
        - 任何异常都返回 None（绝不影响主请求流程）。
        """
        try:
            from core.schemas.multimodal import (
                MultiModalContext, MultiModalImage, MultiModalAudio,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("multimodal schema unavailable: %s", exc)
            return None

        with self._lock:
            has_img = bool(self._image_b64) and self._fresh(self._image_ts)
            has_aud = bool(self._audio_b64) and self._fresh(self._audio_ts)
            if not has_img and not has_aud:
                return None
            img_b64, img_mime, img_src, screen = (
                self._image_b64, self._image_mime, self._image_source, self._screen,
            )
            aud_b64, aud_mime = self._audio_b64, self._audio_mime

        # 若调用方已带图像，尊重之，不注入（避免覆盖显式上传）
        existing_images = list(getattr(existing, "images", []) or []) if existing is not None else []
        if existing_images:
            return None

        images = []
        if has_img:
            images.append(MultiModalImage(mime=img_mime, data=img_b64, source=img_src))
        audio = []
        if has_aud:
            audio.append(MultiModalAudio(mime=aud_mime, data=aud_b64, source="desktop_microphone"))

        metadata = {"injected_by": "desktop_perception_store", "ambient": True}
        if existing is not None:
            try:
                existing_audio = list(getattr(existing, "audio", []) or [])
                audio = existing_audio + audio
                if getattr(existing, "metadata", None):
                    metadata = {**existing.metadata, **metadata}
                if screen is None:
                    screen = getattr(existing, "screen", None)
            except Exception:  # noqa: BLE001
                pass

        return MultiModalContext(
            images=images,
            audio=audio,
            screen=screen,
            metadata=metadata,
        )


def get_desktop_perception_store() -> DesktopPerceptionStore:
    return DesktopPerceptionStore.get_instance()
