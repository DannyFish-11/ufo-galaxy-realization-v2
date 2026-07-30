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

隐私急停（privacy pause）
------------------------
本类是**全部**桌面感知数据的唯一进出口，因此隐私闸门只能落在这里：写入口只有
``update_frame`` / ``update_audio`` 两个，而读出口有五个
（``has_fresh_frame`` / ``latest_frame_snapshot`` / ``take_fresh_audio_for_autoinject``
/ ``snapshot_media`` / ``build_multimodal_context``），下游消费方至少四处
（ambient_attention_loop、computer_use_loop、session_memory_facade、
multimodal/ingest_runtime）。闸门若放在任一消费方，其余几路照旧能看到屏幕 ——
那是**假的**隐私模式。

急停语义（刻意比"停掉某个循环"更强）：
* ``pause()`` 之后**拒收**新的帧/音频（在写入口就挡掉，数据根本不进内存）；
* 同时**立即清空**已缓存的帧、音频与屏幕结构 —— 否则消费方还能读到暂停前
  那一帧，"暂停"名不副实；
* 五条读路径全部返回空，构成第二道防线（即便某条路径将来新增了缓存）；
* ``epoch`` 在每次 pause/resume 时自增。消费方（如 ambient 循环的 ``FrameGate``）
  据此丢弃自己的帧差指纹。这一条的动机是**隐私**而非性能：若保留暂停前的指纹，
  恢复后的新帧会与它做差，等于让智能体推断出"被遮住那段时间里画面变了多少"。
  用户主动遮起来的内容不该以差异信号的形式渗出，故跨隐私边界不携带视觉状态。
  代价是恢复后的第一拍必然判为"有变化"（FrameGate 对第一帧的既定语义），
  这是刻意接受的。

默认状态由 ``GALAXY_PERCEPTION_PRIVACY_DEFAULT`` 决定：默认 ``active``（放行）；
设为 ``paused``/``1``/``true`` 则进程一起来就处于隐私暂停（隐私优先部署）。
闸门本身**始终生效**，不藏在任何 feature flag 之后。
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


def _privacy_default_paused() -> bool:
    """进程启动时是否直接处于隐私暂停(隐私优先部署)。默认放行。"""
    raw = os.getenv("GALAXY_PERCEPTION_PRIVACY_DEFAULT", "").strip().lower()
    return raw in ("paused", "pause", "1", "true", "yes", "on")


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
        # ── 隐私急停 ──
        self._paused: bool = _privacy_default_paused()
        self._paused_at: float = time.time() if self._paused else 0.0
        self._pause_reason: str = "privacy_default" if self._paused else ""
        #: 每次 pause/resume 自增,供消费方重置帧差指纹(见模块 docstring)
        self._epoch: int = 0
        #: 暂停期间被拒收的写入次数(诊断用:证明闸门真的在挡)
        self._rejected_frames: int = 0
        self._rejected_audio: int = 0
        if self._paused:
            logger.warning("桌面感知处于隐私暂停(GALAXY_PERCEPTION_PRIVACY_DEFAULT):启动即不采集")

    # ── 隐私急停 ──────────────────────────────────────────────────────────

    def _wipe_unlocked(self) -> None:
        """清空全部已缓存的感知数据。调用方必须已持有锁。

        暂停时不清缓存,消费方仍能读到暂停前那一帧 —— 那不叫暂停。
        """
        self._cam_b64 = None
        self._cam_ts = 0.0
        self._scr_b64 = None
        self._scr_ts = 0.0
        self._screen_meta = None
        self._audio_b64 = None
        self._audio_ts = 0.0

    def pause(self, reason: str = "user") -> Dict[str, Any]:
        """立即切断感知:拒收后续帧/音频,并清空已缓存内容。幂等。"""
        with self._lock:
            already = self._paused
            self._paused = True
            if not already:
                self._paused_at = time.time()
                self._pause_reason = str(reason or "user")
                self._epoch += 1
            self._wipe_unlocked()
            status = self._privacy_status_unlocked()
        if not already:
            logger.warning("桌面感知已暂停(隐私急停):reason=%s;已清空缓存帧与音频", reason)
        return status

    def resume(self, reason: str = "user") -> Dict[str, Any]:
        """恢复感知。epoch 自增,消费方据此重置帧差指纹,避免"一恢复就误触发"。"""
        with self._lock:
            already = not self._paused
            self._paused = False
            if not already:
                self._pause_reason = ""
                self._paused_at = 0.0
                self._epoch += 1
            status = self._privacy_status_unlocked()
        if not already:
            logger.warning("桌面感知已恢复:reason=%s epoch=%s", reason, status["epoch"])
        return status

    @property
    def paused(self) -> bool:
        with self._lock:
            return self._paused

    @property
    def epoch(self) -> int:
        """pause/resume 世代号。变化即表示感知连续性已断,消费方应重置状态。"""
        with self._lock:
            return self._epoch

    def _privacy_status_unlocked(self) -> Dict[str, Any]:
        return {
            "paused": self._paused,
            "reason": self._pause_reason,
            "paused_at": self._paused_at or None,
            "paused_for_sec": round(time.time() - self._paused_at, 2) if self._paused_at else None,
            "epoch": self._epoch,
            "rejected_frames": self._rejected_frames,
            "rejected_audio": self._rejected_audio,
        }

    def privacy_status(self) -> Dict[str, Any]:
        with self._lock:
            return self._privacy_status_unlocked()

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
        """按 source 分槽存放：含 'screen' → 屏幕槽（含结构化 screen 上下文）；否则摄像头槽。

        隐私暂停期间**拒收**:数据在写入口就被挡掉,根本不进内存。
        """
        with self._lock:
            if self._paused:
                self._rejected_frames += 1
                return
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
        """隐私暂停期间拒收(同 update_frame)。"""
        with self._lock:
            if self._paused:
                self._rejected_audio += 1
                return
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
        """摄像头或屏幕任一有新鲜帧即为 True。隐私暂停时恒为 False。"""
        with self._lock:
            if self._paused:
                return False
            return (bool(self._cam_b64) and self._fresh(self._cam_ts)) or (
                bool(self._scr_b64) and self._fresh(self._scr_ts)
            )

    def latest_frame_snapshot(self) -> Tuple[Optional[str], str, str]:
        """返回最近一帧（摄像头或屏幕，取更新的那张）的 (b64, mime, source)，供「现在看一下」用。

        隐私暂停时返回空帧 —— "现在看一下"在暂停期间必须看不到东西。
        """
        with self._lock:
            if self._paused:
                return None, "image/jpeg", "desktop_camera"
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
            if self._paused:
                return None, None
            if self._audio_b64 and self._fresh(self._audio_ts) and self._audio_ts > self._audio_autoinject_consumed_ts:
                self._audio_autoinject_consumed_ts = self._audio_ts
                return self._audio_b64, self._audio_mime
        return None, None

    def snapshot_media(self) -> Dict[str, Any]:
        """返回当前最新【摄像头/屏幕/音频】快照（仅新鲜项有值），供统一记忆层等消费。

        隐私暂停时全部字段为空(保留键名,调用方无需改判空逻辑)。
        """
        with self._lock:
            if self._paused:
                return {
                    "image_b64": None,
                    "image_mime": self._cam_mime,
                    "camera_b64": None,
                    "camera_mime": self._cam_mime,
                    "screen_b64": None,
                    "screen_mime": self._scr_mime,
                    "screen_meta": None,
                    "audio_b64": None,
                    "audio_mime": self._audio_mime,
                    "privacy_paused": True,
                }
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
                "privacy": self._privacy_status_unlocked(),
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
            # 这条是【每次对话请求】的隐性注入路径:漏掉它,模型仍会在每一轮
            # 对话里看到屏幕与摄像头,隐私暂停就形同虚设。
            if self._paused:
                return None
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
