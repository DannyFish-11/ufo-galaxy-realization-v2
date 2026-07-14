"""
core/perception/desktop_perception_store.py
============================================
桌面端连续感知的「最新帧」存储（隐蔽上下文来源）。

电脑端壳（Tauri / Electron）在【第一态】持续原生采集 **摄像头 / 屏幕 / 麦克风**，
以 base64 帧 POST 到网关 /api/perception/desktop/*。本模块是这些帧的进程内最新值
存储（单例），带 TTL 新鲜度判定，并把三路【一体化】合并成单个 MultiModalContext：

- 摄像头帧（source=desktop_camera）与屏幕帧（source=desktop_screen）分槽存放，互不覆盖；
  屏幕帧还可附带结构化 screen 上下文（如前台窗口 UIA 树）。
- 当一次正常请求进入 OpenClawd.process() 且本身不带图像时，把【新鲜】的摄像头帧 +
  屏幕帧 + 屏幕结构 + 音频一起作为原生多模态上下文注入——模型同时「看到摄像头、看到
  屏幕、听到麦克风」，即第一态的连续原生多模态一体化感知。
- 不新鲜（超过 TTL）的项不会被注入，避免把过期画面/声音喂给模型。

设计原则：轻量、线程安全（简单锁）、永不抛出影响主流程；不持久化、不落盘。
默认 TTL 10s；GALAXY_DESKTOP_PERCEPTION_TTL 可调。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("Galaxy.DesktopPerceptionStore")


def _default_ttl() -> float:
    try:
        return max(1.0, float(os.getenv("GALAXY_DESKTOP_PERCEPTION_TTL", "10")))
    except (ValueError, TypeError):
        return 10.0


def _is_screen_source(source: str) -> bool:
    return "screen" in (source or "").lower()


class DesktopPerceptionStore:
    """进程内单例：保存桌面端最近一次的【摄像头帧 / 屏幕帧 / 音频片段】（分槽，不互相覆盖）。"""

    _instance: Optional["DesktopPerceptionStore"] = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.ttl_sec = _default_ttl()
        # camera (摄像头：看物理环境)
        self._cam_b64: Optional[str] = None
        self._cam_mime: str = "image/jpeg"
        self._cam_ts: float = 0.0
        # screen (屏幕：看屏幕内容；可附带结构化 screen 上下文，如 UIA 树)
        self._scr_b64: Optional[str] = None
        self._scr_mime: str = "image/jpeg"
        self._scr_ts: float = 0.0
        self._screen_meta: Optional[Dict[str, Any]] = None
        # audio (麦克风)
        self._audio_b64: Optional[str] = None
        self._audio_mime: str = "audio/webm"
        self._audio_ts: float = 0.0
        # counters (diagnostics)
        self._cam_received: int = 0
        self._scr_received: int = 0
        self._audio_received: int = 0
        # 自动注入去重：已被对话自动注入消费过的音频时间戳，避免同一片段反复转写
        self._audio_autoinject_consumed_ts: float = 0.0

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
        """按 source 分槽存放：含 'screen' → 屏幕槽（含结构化 screen 上下文）；否则摄像头槽。"""
        if not image_b64:
            # 即便没有像素帧，也允许只更新结构化屏幕上下文（如纯 UIA 树）。
            if screen is not None:
                with self._lock:
                    self._screen_meta = screen
                    self._scr_ts = time.time()
            return
        with self._lock:
            if _is_screen_source(source):
                self._scr_b64 = image_b64
                self._scr_mime = mime or "image/jpeg"
                self._scr_ts = time.time()
                self._scr_received += 1
                if screen is not None:
                    self._screen_meta = screen
            else:
                self._cam_b64 = image_b64
                self._cam_mime = mime or "image/jpeg"
                self._cam_ts = time.time()
                self._cam_received += 1
                # 旧链路偶尔把 screen 结构挂在摄像头帧上，也一并保留
                if screen is not None:
                    self._screen_meta = screen

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
        """摄像头或屏幕任一有新鲜帧即为 True。"""
        with self._lock:
            return (bool(self._cam_b64) and self._fresh(self._cam_ts)) or (
                bool(self._scr_b64) and self._fresh(self._scr_ts)
            )

    def latest_frame_snapshot(self) -> Tuple[Optional[str], str, str]:
        """返回最近一帧（摄像头或屏幕，取更新的那张）的 (b64, mime, source)，供「现在看一下」用。"""
        with self._lock:
            if self._scr_ts >= self._cam_ts and self._scr_b64:
                return self._scr_b64, self._scr_mime, "desktop_screen"
            if self._cam_b64:
                return self._cam_b64, self._cam_mime, "desktop_camera"
            if self._scr_b64:
                return self._scr_b64, self._scr_mime, "desktop_screen"
            return None, "image/jpeg", "desktop_camera"

    def take_fresh_audio_for_autoinject(self):
        """取一段「新鲜且未被自动注入消费过」的音频，用于对话自动注入。

        返回 ``(audio_b64, mime)``；没有可用音频则返回 ``(None, None)``。
        """
        with self._lock:
            if self._audio_b64 and self._fresh(self._audio_ts) and self._audio_ts > self._audio_autoinject_consumed_ts:
                self._audio_autoinject_consumed_ts = self._audio_ts
                return self._audio_b64, self._audio_mime
        return None, None

    def snapshot_media(self) -> Dict[str, Any]:
        """返回当前最新【摄像头/屏幕/音频】快照（仅新鲜项有值），供统一记忆层等消费。"""
        with self._lock:
            cam_fresh = bool(self._cam_b64) and self._fresh(self._cam_ts)
            scr_fresh = bool(self._scr_b64) and self._fresh(self._scr_ts)
            aud_fresh = bool(self._audio_b64) and self._fresh(self._audio_ts)
            return {
                # 兼容旧字段名（image_* 指摄像头帧）+ 新增 screen_* 字段
                "image_b64": self._cam_b64 if cam_fresh else None,
                "image_mime": self._cam_mime,
                "camera_b64": self._cam_b64 if cam_fresh else None,
                "camera_mime": self._cam_mime,
                "screen_b64": self._scr_b64 if scr_fresh else None,
                "screen_mime": self._scr_mime,
                "screen_meta": self._screen_meta if scr_fresh else None,
                "audio_b64": self._audio_b64 if aud_fresh else None,
                "audio_mime": self._audio_mime,
            }

    def status(self) -> Dict[str, Any]:
        with self._lock:
            now = time.time()
            return {
                "ttl_sec": self.ttl_sec,
                "camera_received": self._cam_received,
                "screen_received": self._scr_received,
                "audio_received": self._audio_received,
                "camera_fresh": self._fresh(self._cam_ts),
                "camera_age_sec": round(now - self._cam_ts, 2) if self._cam_ts else None,
                "screen_fresh": self._fresh(self._scr_ts),
                "screen_age_sec": round(now - self._scr_ts, 2) if self._scr_ts else None,
                "screen_meta_present": self._screen_meta is not None,
                "audio_fresh": self._fresh(self._audio_ts),
                "audio_age_sec": round(now - self._audio_ts, 2) if self._audio_ts else None,
            }

    def build_multimodal_context(self, existing: Optional[Any] = None) -> Optional[Any]:
        """把【新鲜】的摄像头帧 + 屏幕帧 + 屏幕结构 + 音频【一体化】合并成 MultiModalContext。

        - 仅当确有新鲜帧/音频时返回非 None。
        - 若 ``existing`` 已带图像，则不覆盖（尊重显式请求），返回 None。
        - 任何异常都返回 None（绝不影响主请求流程）。
        """
        try:
            from core.schemas.multimodal import (
                MultiModalAudio,
                MultiModalContext,
                MultiModalImage,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("multimodal schema unavailable: %s", exc)
            return None

        with self._lock:
            cam_fresh = bool(self._cam_b64) and self._fresh(self._cam_ts)
            scr_fresh = bool(self._scr_b64) and self._fresh(self._scr_ts)
            aud_fresh = bool(self._audio_b64) and self._fresh(self._audio_ts)
            meta_fresh = self._screen_meta is not None and self._fresh(self._scr_ts)
            if not (cam_fresh or scr_fresh or aud_fresh or meta_fresh):
                return None
            cam = (self._cam_b64, self._cam_mime) if cam_fresh else (None, None)
            scr = (self._scr_b64, self._scr_mime) if scr_fresh else (None, None)
            screen_meta = self._screen_meta if meta_fresh else None
            aud = (self._audio_b64, self._audio_mime) if aud_fresh else (None, None)

        # 若调用方已带图像，尊重之，不注入（避免覆盖显式上传）
        existing_images = list(getattr(existing, "images", []) or []) if existing is not None else []
        if existing_images:
            return None

        # 一体化：摄像头 + 屏幕 两张图同时进 images（多模态模型一次同时看到两路）
        images = []
        if cam[0]:
            images.append(MultiModalImage(mime=cam[1] or "image/jpeg", data=cam[0], source="desktop_camera"))
        if scr[0]:
            images.append(MultiModalImage(mime=scr[1] or "image/jpeg", data=scr[0], source="desktop_screen"))
        audio = []
        if aud[0]:
            audio.append(MultiModalAudio(mime=aud[1] or "audio/webm", data=aud[0], source="desktop_microphone"))

        metadata = {
            "injected_by": "desktop_perception_store",
            "ambient": True,
            "modalities": [
                m for m, on in (("camera", bool(cam[0])), ("screen", bool(scr[0])), ("audio", bool(aud[0]))) if on
            ],
        }
        screen = screen_meta
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
