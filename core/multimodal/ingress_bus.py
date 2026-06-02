"""core/multimodal/ingress_bus.py — Continuous Host Perception Bus (Runtime Shell Layer)

**Unified-Subject Architecture — Runtime Shell Ownership**
------------------------------------------------------------
``MultimodalIngressBus`` is owned by the runtime shell
(:class:`~core.desktop_presence_runtime.DesktopPresenceRuntime`).  It provides
*continuous host perception* for the Windows desktop environment: audio, video,
and system signals are merged into a ``PerceptionFrame`` stream.

This is the **continuous sensory layer** of the subject — the shell's ongoing
ambient awareness of the host device.  It is independent of any individual
request and runs as a background loop.

Do NOT confuse with ``core/perception/multimodal_bus.py`` (``MultimodalBus``),
which handles *request-bound* multimodal payload fusion inside ``OpenClawd``:

.. code-block:: text

    Runtime shell (DesktopPresenceRuntime)
        └─ MultimodalIngressBus (this module)
              └─ Continuous: audio + video + system → PerceptionFrame
              └─ Available to OpenClawd as ambient context

    Subject core (OpenClawd)
        └─ MultimodalBus.ingest(multimodal_context=request_payload)
              └─ Per-request: fuse caller-attached images/audio → fusion_summary

Merges audio, video, and system signals into a single PerceptionFrame
stream for downstream consumption.  Missing modalities are tolerated:
quality flags and default values are used when a source is absent or stale.

Usage::

    bus = MultimodalIngressBus(tick_ms=200)

    # Wire up sources
    audio_pipeline.add_callback(bus.update_audio)
    video_pipeline.add_callback(bus.update_video)

    # Consume frames
    q = bus.subscribe()
    asyncio.create_task(bus.run())
    frame = await q.get()   # PerceptionFrame
"""
from __future__ import annotations

import asyncio
import itertools
import logging
import os
import shutil
import time
from typing import Any, Callable, Dict, List, Optional

from .audio_features import AudioState
from .video_features import VideoState
from .perception_frame import PerceptionFrame, SystemSignals
from .signal_quality import SignalQuality, QualityFlag

logger = logging.getLogger(__name__)


class MultimodalIngressBus:
    """Merges audio / video / system signals into a PerceptionFrame stream.

    The bus runs a periodic tick loop that composes a PerceptionFrame from
    the latest signal snapshots and dispatches it to all registered
    subscribers and callbacks.

    Thread safety: signal updates (update_audio / update_video /
    update_system) are safe to call from any thread or asyncio task.
    Subscription and emission must happen within the same event loop.
    """

    # PR-ACTIVE-PERCEPTION: scan toolchain every N ticks (not every tick)
    _TOOLCHAIN_SCAN_INTERVAL = 30   # ~30 ticks × 200 ms = 6 s
    _OPPORTUNITY_SCAN_INTERVAL = 150  # ~150 ticks × 200 ms = 30 s

    def __init__(self, tick_ms: int = 200) -> None:
        self._tick_ms = tick_ms
        self._frame_counter = itertools.count()

        # Latest snapshots ------------------------------------------------
        self._audio: Optional[AudioState] = None
        self._audio_quality: SignalQuality = SignalQuality.missing("No audio source")
        self._audio_ts: Optional[float] = None

        self._video: Optional[VideoState] = None
        self._video_quality: SignalQuality = SignalQuality.missing("No video source")
        self._video_ts: Optional[float] = None

        self._system: Optional[SystemSignals] = None
        self._system_quality: SignalQuality = SignalQuality.missing("No system source")
        self._system_ts: Optional[float] = None

        # Staleness threshold
        self._stale_threshold_ms: float = 2000.0

        # Consumers -------------------------------------------------------
        self._running = False
        self._subscribers: List[asyncio.Queue] = []
        self._callbacks: List[Callable[[PerceptionFrame], None]] = []

        # PR-ACTIVE-PERCEPTION: tool-chain cache + tick counters -----------
        self._tick_count: int = 0
        self._cached_toolchain: Dict[str, Any] = {}
        # async callback for autonomous goal submission (set by shell)
        self._goal_submitter: Optional[Callable[[str], None]] = None

    # ------------------------------------------------------------------
    # Signal injection
    # ------------------------------------------------------------------

    def update_audio(
        self, state: AudioState, quality: SignalQuality
    ) -> None:
        """Ingest a new AudioState snapshot."""
        self._audio = state
        self._audio_quality = quality
        self._audio_ts = time.monotonic()

    def update_video(
        self, state: VideoState, quality: SignalQuality
    ) -> None:
        """Ingest a new VideoState snapshot."""
        self._video = state
        self._video_quality = quality
        self._video_ts = time.monotonic()

    def update_system(
        self,
        signals: SystemSignals,
        quality: Optional[SignalQuality] = None,
    ) -> None:
        """Ingest new system signals."""
        self._system = signals
        self._system_quality = quality if quality is not None else SignalQuality.ok()
        self._system_ts = time.monotonic()

    # ------------------------------------------------------------------
    # Subscription
    # ------------------------------------------------------------------

    def add_callback(self, cb: Callable[[PerceptionFrame], None]) -> None:
        """Register a synchronous callback invoked for each frame."""
        self._callbacks.append(cb)

    def subscribe(self) -> asyncio.Queue:
        """Return an asyncio.Queue that receives each PerceptionFrame."""
        q: asyncio.Queue = asyncio.Queue(maxsize=50)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        """Remove a previously-subscribed queue."""
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    # ------------------------------------------------------------------
    # Frame construction
    # ------------------------------------------------------------------

    def _apply_staleness(
        self, ts: Optional[float], quality: SignalQuality
    ) -> SignalQuality:
        """Downgrade quality to STALE when the signal has not been updated."""
        if ts is None:
            return quality
        age_ms = (time.monotonic() - ts) * 1000.0
        if age_ms > self._stale_threshold_ms and quality.flag == QualityFlag.OK:
            return SignalQuality.stale(
                freshness_ms=age_ms,
                confidence=quality.confidence * 0.5,
            )
        return quality

    # ------------------------------------------------------------------
    # PR-ACTIVE-PERCEPTION: tool-chain snapshot (lightweight, cached)
    # ------------------------------------------------------------------

    def _scan_toolchain(self) -> Dict[str, Any]:
        """Return a snapshot of available tools on the host.

        Checks are cheap (shutil.which / os.path.exists) and results are
        cached for ``_TOOLCHAIN_SCAN_INTERVAL`` ticks.
        """
        tc: Dict[str, Any] = {}
        # Programming runtimes
        tc["python"] = bool(shutil.which("python") or shutil.which("python3"))
        tc["node"] = bool(shutil.which("node"))
        tc["docker"] = bool(shutil.which("docker"))
        # Editors / IDEs (common install paths)
        tc["vscode"] = bool(
            shutil.which("code")
            or os.path.exists(os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"))
        )
        # Version control
        tc["git"] = bool(shutil.which("git"))
        # Browsers
        tc["chrome"] = bool(
            shutil.which("chrome")
            or os.path.exists(os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"))
        )
        tc["edge"] = bool(shutil.which("msedge"))
        # Shell
        tc["powershell"] = bool(shutil.which("powershell"))
        tc["bash"] = bool(shutil.which("bash"))
        return tc

    # ------------------------------------------------------------------
    # Frame construction
    # ------------------------------------------------------------------

    def build_frame(self) -> PerceptionFrame:
        """Compose a PerceptionFrame from the current snapshots."""
        aq = self._apply_staleness(self._audio_ts, self._audio_quality)
        vq = self._apply_staleness(self._video_ts, self._video_quality)
        sq = self._apply_staleness(self._system_ts, self._system_quality)

        # PR-ACTIVE-PERCEPTION: inject cached toolchain into system signals
        system = self._system if sq.is_usable else None
        if system is not None:
            system.toolchain = self._cached_toolchain
        elif sq.is_usable:
            # system is usable but None — create minimal with toolchain
            system = SystemSignals(toolchain=self._cached_toolchain)

        return PerceptionFrame(
            frame_id=next(self._frame_counter),
            audio=self._audio if aq.is_usable else None,
            audio_quality=aq,
            video=self._video if vq.is_usable else None,
            video_quality=vq,
            system=system,
            system_quality=sq,
        )

    # ------------------------------------------------------------------
    # Emission
    # ------------------------------------------------------------------

    async def _emit(self, frame: PerceptionFrame) -> None:
        """Dispatch a frame to all callbacks and subscriber queues."""
        for cb in list(self._callbacks):
            try:
                cb(frame)
            except Exception as exc:
                logger.debug("Ingress bus callback error: %s", exc)

        for q in list(self._subscribers):
            try:
                q.put_nowait(frame)
            except asyncio.QueueFull:
                pass  # slow consumer — drop rather than block

    # ------------------------------------------------------------------
    # Tick loop
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # PR-ACTIVE-PERCEPTION: opportunity analysis (invoked by tick loop)
    # ------------------------------------------------------------------

    def _analyze_opportunity(self, frame: PerceptionFrame) -> Optional[str]:
        """Inspect the current frame and decide whether an autonomous goal
        should be submitted.  Returns a natural-language goal string, or
        *None* when there is nothing to do.

        This is a **thin hook** — heavy logic lives in the cognitive layers
        (memory_bias_layer, task_memory, etc.).  Here we only detect
        high-confidence triggers that warrant interrupting the silent state.
        """
        if frame.system is None:
            return None

        tc = frame.system.toolchain
        extra = frame.system.extra

        # Trigger 1: high CPU for extended period → suggest diagnostics
        cpu = frame.system.cpu_load
        if cpu is not None and cpu > 0.85:
            return "系统CPU使用率很高，帮我诊断一下"

        # Trigger 2: memory pressure
        mem = frame.system.memory_load
        if mem is not None and mem > 0.90:
            return "内存快用完了，帮我清理一下"

        # Trigger 3: time-based (simple wall-clock checks)
        hour = time.localtime().tm_hour
        minute = time.localtime().tm_min
        if hour == 9 and 0 <= minute <= 5:
            return "早上好，帮我看看今天的日程安排"

        # No trigger → remain silent
        return None

    async def run(self) -> None:
        """Tick loop: emits a PerceptionFrame every tick_ms milliseconds.

        PR-ACTIVE-PERCEPTION: every ``_TOOLCHAIN_SCAN_INTERVAL`` ticks the
        tool-chain cache is refreshed; every ``_OPPORTUNITY_SCAN_INTERVAL``
        ticks an opportunity-analysis runs and may submit an autonomous goal
        via the ``_goal_submitter`` callback registered by the shell.
        """
        self._running = True
        logger.info(
            "Multimodal ingress bus started (tick=%d ms, toolchain_scan=%d ticks, "
            "opportunity_scan=%d ticks)",
            self._tick_ms, self._TOOLCHAIN_SCAN_INTERVAL, self._OPPORTUNITY_SCAN_INTERVAL,
        )
        try:
            while self._running:
                self._tick_count += 1

                # --- periodic toolchain refresh --------------------------------
                if self._tick_count % self._TOOLCHAIN_SCAN_INTERVAL == 0:
                    try:
                        self._cached_toolchain = self._scan_toolchain()
                    except Exception as exc:
                        logger.debug("Tool-chain scan error: %s", exc)

                frame = self.build_frame()
                await self._emit(frame)

                # --- periodic opportunity analysis -----------------------------
                if self._tick_count % self._OPPORTUNITY_SCAN_INTERVAL == 0:
                    try:
                        goal = self._analyze_opportunity(frame)
                        if goal and self._goal_submitter is not None:
                            logger.info("Active-perception trigger: %s", goal)
                            self._goal_submitter(goal)
                    except Exception as exc:
                        logger.debug("Opportunity analysis error: %s", exc)

                await asyncio.sleep(self._tick_ms / 1000.0)
        finally:
            self._running = False
            logger.info("Multimodal ingress bus stopped")

    def stop(self) -> None:
        """Signal the tick loop to stop."""
        self._running = False

    # ------------------------------------------------------------------
    # Async generator interface
    # ------------------------------------------------------------------

    async def stream(self):
        """Async generator: yields PerceptionFrames from the bus."""
        q = self.subscribe()
        task = asyncio.create_task(self.run())
        try:
            while not task.done() or not q.empty():
                try:
                    yield await asyncio.wait_for(
                        q.get(), timeout=self._tick_ms / 1000.0 * 3
                    )
                except asyncio.TimeoutError:
                    if task.done():
                        break
        finally:
            self.stop()
            await task
