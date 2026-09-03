"""
core/perception/desktop_perception_store.py
============================================
桌面端连续感知的「最新帧」存储（隐蔽上下文来源）。

电脑端壳（Tauri / Electron）在【第一态】持续原生采集 **摄像头 / 屏幕 / 麦克风 /
系统播放声**，以 base64 帧 POST 到网关 /api/perception/desktop/*。本模块是这些帧的
进程内最新值存储（单例），带 TTL 新鲜度判定，并把四路【一体化】合并成单个
MultiModalContext：

- 摄像头帧（source=desktop_camera）与屏幕帧（source=desktop_screen）分槽存放，互不覆盖；
  屏幕帧还可附带结构化 screen 上下文（如前台窗口 UIA 树）。
- 麦克风（source=desktop_microphone）与系统播放声（source=desktop_system_audio）同样
  **分槽**。这不是冗余：麦克风回答"用户说了什么"，系统声回答"用户此刻在听什么"
  （视频、网课、游戏、会议的声音）。合成一槽会互相覆盖，而且一旦混流就再也分不出
  "这段声音是人说的还是扬声器放的"——那正是模型最需要区分的一件事。
  系统播放声只能在电脑端本机采集（浏览器的 getUserMedia 拿不到系统输出），
  见 ``core/multimodal/system_audio_ingest.py``。
- 当一次正常请求进入 OpenClawd.process() 且本身不带图像时，把【新鲜】的摄像头帧 +
  屏幕帧 + 屏幕结构 + 麦克风 + 系统声一起作为原生多模态上下文注入——模型同时
  「看到摄像头、看到屏幕、听到用户、听到用户在听的东西」，即第一态的连续原生多模态
  一体化感知。
- 不新鲜（超过 TTL）的项不会被注入，避免把过期画面/声音喂给模型。

设计原则：轻量、线程安全（简单锁）、永不抛出影响主流程；不持久化、不落盘。
默认 TTL 10s；GALAXY_DESKTOP_PERCEPTION_TTL 可调。

隐私急停（privacy pause）
------------------------
本类是**全部**桌面感知数据的唯一进出口，因此隐私闸门只能落在这里：写入口只有
``update_frame`` / ``update_audio`` / ``update_system_audio`` 三个，而读出口有六个
（``has_fresh_frame`` / ``latest_frame_snapshot`` / ``take_fresh_audio_for_autoinject``
/ ``take_fresh_system_audio_for_autoinject`` / ``snapshot_media``
/ ``build_multimodal_context``），下游消费方至少四处
（ambient_attention_loop、computer_use_loop、session_memory_facade、
multimodal/ingest_runtime）。闸门若放在任一消费方，其余几路照旧能看到屏幕 ——
那是**假的**隐私模式。

急停语义（刻意比"停掉某个循环"更强）：
* ``pause()`` 之后**拒收**新的帧/音频（在写入口就挡掉，数据根本不进内存）；
* 同时**立即清空**已缓存的帧、音频与屏幕结构 —— 否则消费方还能读到暂停前
  那一帧，"暂停"名不副实；
* 六条读路径全部返回空，构成第二道防线（即便某条路径将来新增了缓存）；
* 系统播放声走**同一道**闸门，不另开旁路 —— 它比麦克风更敏感：等于把用户正在听的
  一切内容（会议、私信语音、视频）完整送出去；
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
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.DesktopPerceptionStore")


def _default_ttl() -> float:
    try:
        return max(1.0, float(os.getenv("GALAXY_DESKTOP_PERCEPTION_TTL", "10")))
    except (ValueError, TypeError):
        return 10.0


def _keyframe_ring_size() -> int:
    """滚动关键帧环的长度。0 = 关闭（只留"最新一帧"的旧行为）。

    这个环是"视频"在本仓里唯一真实的来源：此前每来一帧就覆盖上一帧，上一帧当场
    消失，于是「刚才屏幕上发生了什么」「动画卡在哪一步」结构上无法回答 —— 模型
    永远只看得到提问那一瞬间。环把同一个 TTL 窗口内的帧留下来，不延长保留时间、
    不新增落盘，只是不再自我覆盖。
    """
    try:
        n = int(os.getenv("GALAXY_PERCEPTION_KEYFRAMES", "4"))
    except ValueError:
        return 4
    return max(0, min(n, 16))  # 上限 16:每帧是整屏 base64,再多就是几十 MB 常驻内存


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
        # 滚动关键帧环（分槽，与上面的"最新帧"同槽同闸门）。元素为 (b64, mime, ts)。
        self._ring_size: int = _keyframe_ring_size()
        self._scr_ring: Deque[Tuple[str, str, float]] = deque(maxlen=self._ring_size or 1)
        self._cam_ring: Deque[Tuple[str, str, float]] = deque(maxlen=self._ring_size or 1)
        # audio (麦克风：听人说话)
        self._audio_b64: Optional[str] = None
        self._audio_mime: str = "audio/webm"
        self._audio_ts: float = 0.0
        # system audio (系统播放声：听"用户正在听什么"——视频/游戏/网课的声音)
        # 与麦克风【分槽】,不是冗余:两者语义完全不同。麦克风回答"用户说了什么",
        # 系统声回答"用户此刻在听什么"。混在一槽里会互相覆盖,而且一旦混流就再也
        # 分不出"这段声音是人说的还是扬声器放的"。
        self._sys_audio_b64: Optional[str] = None
        self._sys_audio_mime: str = "audio/webm"
        self._sys_audio_ts: float = 0.0
        # counters (diagnostics)
        self._cam_received: int = 0
        self._scr_received: int = 0
        self._audio_received: int = 0
        self._sys_audio_received: int = 0
        # 自动注入去重：已被对话自动注入消费过的音频时间戳，避免同一片段反复转写
        self._audio_autoinject_consumed_ts: float = 0.0
        self._sys_audio_autoinject_consumed_ts: float = 0.0
        # ── 隐私急停 ──
        self._paused: bool = _privacy_default_paused()
        self._paused_at: float = time.time() if self._paused else 0.0
        self._pause_reason: str = "privacy_default" if self._paused else ""
        #: 每次 pause/resume 自增,供消费方重置帧差指纹(见模块 docstring)
        self._epoch: int = 0
        #: 暂停期间被拒收的写入次数(诊断用:证明闸门真的在挡)
        self._rejected_frames: int = 0
        self._rejected_audio: int = 0
        self._rejected_system_audio: int = 0
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
        self._sys_audio_b64 = None
        self._sys_audio_ts = 0.0
        # 关键帧环也必须清:它保存的正是"暂停前那一段发生了什么",漏清等于隐私急停
        # 只挡住了当下这一帧,却把此前几秒的完整过程留在内存里等人来读。
        self._scr_ring.clear()
        self._cam_ring.clear()

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
            "rejected_system_audio": self._rejected_system_audio,
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

        判定与写入必须在**同一次持锁**内完成。此前分成两次持锁(先查 paused、
        释放锁、再取锁写入),中间存在 TOCTOU 空隙:用户按下暂停的瞬间若有一帧
        正在途中,pause() 会在空隙里完成"置位 + 清缓存",随后这一帧落在 wipe
        之后 —— 暂停期间读闸门还挡得住,但**一恢复就能读出来**,而那恰恰是
        用户想遮住的那一帧。已用受控交错实测复现过。
        """
        with self._lock:
            if self._paused:
                self._rejected_frames += 1
                return
            if not image_b64:
                # 即便没有像素帧，也允许只更新结构化屏幕上下文（如纯 UIA 树）。
                if screen is not None:
                    self._screen_meta = screen
                    self._scr_ts = time.time()
                return
            if _is_screen_source(source):
                self._scr_b64 = image_b64
                self._scr_mime = mime or "image/jpeg"
                self._scr_ts = time.time()
                self._scr_received += 1
                self._push_ring_unlocked(self._scr_ring, image_b64, self._scr_mime, self._scr_ts)
                if screen is not None:
                    self._screen_meta = screen
            else:
                self._cam_b64 = image_b64
                self._cam_mime = mime or "image/jpeg"
                self._cam_ts = time.time()
                self._cam_received += 1
                self._push_ring_unlocked(self._cam_ring, image_b64, self._cam_mime, self._cam_ts)
                # 旧链路偶尔把 screen 结构挂在摄像头帧上，也一并保留
                if screen is not None:
                    self._screen_meta = screen

    def _push_ring_unlocked(
        self,
        ring: "Deque[Tuple[str, str, float]]",
        image_b64: str,
        mime: str,
        ts: float,
    ) -> None:
        """把一帧压进滚动环。调用方必须已持有锁，且必须已过隐私闸门。

        与上一帧逐字相同就不压 —— 静止画面下采集仍在跑，不去重的话环会被同一帧的
        若干份拷贝填满，抽出来的"关键帧序列"实际是一张图重复 N 次：白烧 token，
        还会让模型以为"这段时间什么都没变"其实是我们没留下证据。
        """
        if self._ring_size <= 0:
            return
        if ring and ring[-1][0] == image_b64:
            return
        ring.append((image_b64, mime, ts))

    def _fresh_keyframes_unlocked(self, ring: "Deque[Tuple[str, str, float]]") -> List[Tuple[str, str, float]]:
        """取环里仍在 TTL 窗口内的帧。过期帧不进模型（与最新帧同一条新鲜度规则）。"""
        return [item for item in ring if self._fresh(item[2])]

    def update_audio(self, audio_b64: str, *, mime: str = "audio/webm") -> None:
        """隐私暂停期间拒收。判定与写入同一次持锁(理由见 update_frame)。"""
        with self._lock:
            if self._paused:
                self._rejected_audio += 1
                return
            if not audio_b64:
                return
            self._audio_b64 = audio_b64
            self._audio_mime = mime or "audio/webm"
            self._audio_ts = time.time()
            self._audio_received += 1

    def update_system_audio(self, audio_b64: str, *, mime: str = "audio/webm") -> None:
        """存最新一段【系统播放声】(扬声器输出的回环采集)。

        隐私暂停期间拒收 —— 系统声比麦克风更敏感:它等于把用户正在听的一切内容
        (会议、私信语音、视频)完整送出去,所以必须走同一道闸门,而不是另开一条
        绕过隐私急停的旁路。判定与写入同一次持锁(理由见 ``update_frame``)。
        """
        with self._lock:
            if self._paused:
                self._rejected_system_audio += 1
                return
            if not audio_b64:
                return
            self._sys_audio_b64 = audio_b64
            self._sys_audio_mime = mime or "audio/webm"
            self._sys_audio_ts = time.time()
            self._sys_audio_received += 1

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

    def take_fresh_system_audio_for_autoinject(self):
        """取一段「新鲜且未被自动注入消费过」的**系统播放声**。

        与麦克风那条各自独立去重:两路的到达节奏不同,共用一个消费水位会让先到的
        那路把后到的那路一起标记为"已消费",另一路从此永远取不到东西。

        返回 ``(audio_b64, mime)``;隐私暂停或无可用音频则返回 ``(None, None)``。
        """
        with self._lock:
            if self._paused:
                return None, None
            if (
                self._sys_audio_b64
                and self._fresh(self._sys_audio_ts)
                and self._sys_audio_ts > self._sys_audio_autoinject_consumed_ts
            ):
                self._sys_audio_autoinject_consumed_ts = self._sys_audio_ts
                return self._sys_audio_b64, self._sys_audio_mime
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
                    "system_audio_b64": None,
                    "system_audio_mime": self._sys_audio_mime,
                    "privacy_paused": True,
                }
            cam_fresh = bool(self._cam_b64) and self._fresh(self._cam_ts)
            scr_fresh = bool(self._scr_b64) and self._fresh(self._scr_ts)
            aud_fresh = bool(self._audio_b64) and self._fresh(self._audio_ts)
            sys_fresh = bool(self._sys_audio_b64) and self._fresh(self._sys_audio_ts)
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
                "system_audio_b64": self._sys_audio_b64 if sys_fresh else None,
                "system_audio_mime": self._sys_audio_mime,
            }

    def status(self) -> Dict[str, Any]:
        with self._lock:
            now = time.time()
            return {
                "ttl_sec": self.ttl_sec,
                "camera_received": self._cam_received,
                "screen_received": self._scr_received,
                "audio_received": self._audio_received,
                "system_audio_received": self._sys_audio_received,
                "camera_fresh": self._fresh(self._cam_ts),
                "camera_age_sec": round(now - self._cam_ts, 2) if self._cam_ts else None,
                "screen_fresh": self._fresh(self._scr_ts),
                "screen_age_sec": round(now - self._scr_ts, 2) if self._scr_ts else None,
                "screen_meta_present": self._screen_meta is not None,
                "audio_fresh": self._fresh(self._audio_ts),
                "audio_age_sec": round(now - self._audio_ts, 2) if self._audio_ts else None,
                "system_audio_fresh": self._fresh(self._sys_audio_ts),
                "system_audio_age_sec": (round(now - self._sys_audio_ts, 2) if self._sys_audio_ts else None),
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
                MultiModalVideo,
                MultiModalVideoFrame,
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
            sys_fresh = bool(self._sys_audio_b64) and self._fresh(self._sys_audio_ts)
            meta_fresh = self._screen_meta is not None and self._fresh(self._scr_ts)
            if not (cam_fresh or scr_fresh or aud_fresh or sys_fresh or meta_fresh):
                return None
            cam = (self._cam_b64, self._cam_mime) if cam_fresh else (None, None)
            scr = (self._scr_b64, self._scr_mime) if scr_fresh else (None, None)
            screen_meta = self._screen_meta if meta_fresh else None
            aud = (self._audio_b64, self._audio_mime) if aud_fresh else (None, None)
            sysaud = (self._sys_audio_b64, self._sys_audio_mime) if sys_fresh else (None, None)
            # 屏幕的滚动关键帧:同一把锁内取,取出来就是不可变元组的普通列表。
            # 只做屏幕不做摄像头 —— "这段时间发生了什么"几乎总是在问屏幕上的过程
            # (点了没反应、动画卡住、报错一闪而过);摄像头再来一路只是翻倍烧 token。
            scr_keyframes = self._fresh_keyframes_unlocked(self._scr_ring)

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
        if sysaud[0]:
            # source 必须与麦克风那条区分开:模型要能判断"这段是人在说话"还是
            # "这段是屏幕里在放的声音",两者混成同一个 source 就无从分辨了。
            audio.append(
                MultiModalAudio(
                    mime=sysaud[1] or "audio/webm",
                    data=sysaud[0],
                    source="desktop_system_audio",
                )
            )

        # 视频:≥2 帧才有意义 —— 一帧的"序列"就是那张静止图,已经在 images 里了,
        # 再包一层只会把同一张图发两遍。
        video = []
        if len(scr_keyframes) >= 2:
            t0 = scr_keyframes[0][2]
            video.append(
                MultiModalVideo(
                    source="desktop_screen",
                    frames=[
                        MultiModalVideoFrame(
                            data=b64,
                            mime=fmime or "image/jpeg",
                            offset_ms=max(0, int((fts - t0) * 1000)),
                        )
                        for b64, fmime, fts in scr_keyframes
                    ],
                    duration_ms=max(0, int((scr_keyframes[-1][2] - t0) * 1000)),
                    sampled_from=len(scr_keyframes),
                )
            )

        metadata = {
            "injected_by": "desktop_perception_store",
            "ambient": True,
            "modalities": [
                m
                for m, on in (
                    ("camera", bool(cam[0])),
                    ("screen", bool(scr[0])),
                    ("audio", bool(aud[0])),
                    ("system_audio", bool(sysaud[0])),
                    ("screen_video", bool(video)),
                )
                if on
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
            video=video,
            screen=screen,
            metadata=metadata,
        )


def get_desktop_perception_store() -> DesktopPerceptionStore:
    return DesktopPerceptionStore.get_instance()
