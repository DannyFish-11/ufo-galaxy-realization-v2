"""Lightweight video feature extraction producing VideoState snapshots.

Features: motion_level, scene_change_rate, face_presence (optional),
          video_freshness_ms.

No heavy CV inference — uses frame differencing and Haar cascades only.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np


@dataclass
class VideoState:
    """Lightweight video state features emitted every ~200–500 ms."""

    motion_level: float = 0.0           # Normalised motion intensity [0, 1]
    scene_change_rate: float = 0.0      # Scene changes per second (rolling 10 s)
    face_presence: Optional[float] = None  # 1.0/0.0 if detection enabled, else None
    video_freshness_ms: float = float("inf")  # ms since previous frame
    timestamp: float = field(default_factory=time.monotonic)


class VideoFeatureExtractor:
    """Extracts lightweight video features from consecutive BGR/grayscale frames.

    Designed to be called at the feature-extraction sample rate (~3–5 fps),
    not necessarily at the raw capture rate.
    """

    # Normalisation factor for mean absolute difference (0–255 → 0–1).
    # Clamp at 25 / 255 ≈ 10 % to avoid saturation on extreme scene changes.
    _MOTION_SCALE = 10.0

    def __init__(
        self,
        fps: float = 5.0,
        scene_change_threshold: float = 0.35,
    ) -> None:
        self.fps = fps
        self.scene_change_threshold = scene_change_threshold

        self._prev_gray: Optional[np.ndarray] = None
        self._prev_mean: Optional[float] = None
        self._scene_change_times: List[float] = []
        self._last_update_ts: Optional[float] = None

    def process_frame(
        self,
        frame: np.ndarray,
        enable_face: bool = False,
    ) -> VideoState:
        """Extract features from one frame.

        Args:
            frame:       BGR (H×W×3) or grayscale (H×W) uint8 or float32 array.
            enable_face: When True, attempt OpenCV Haar-cascade face detection.

        Returns:
            VideoState snapshot.
        """
        now = time.monotonic()
        gray = self._to_gray(frame)

        motion_level = self._compute_motion(gray)
        scene_change_rate = self._compute_scene_change_rate(gray, now)

        freshness_ms = (
            (now - self._last_update_ts) * 1000.0
            if self._last_update_ts is not None
            else 0.0
        )
        self._prev_gray = gray
        self._last_update_ts = now

        face_presence: Optional[float] = None
        if enable_face:
            face_presence = self._detect_faces(frame)

        return VideoState(
            motion_level=float(np.clip(motion_level * self._MOTION_SCALE, 0.0, 1.0)),
            scene_change_rate=scene_change_rate,
            face_presence=face_presence,
            video_freshness_ms=max(freshness_ms, 0.0),
            timestamp=now,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_gray(frame: np.ndarray) -> np.ndarray:
        """Convert any frame format to float32 grayscale [0, 255]."""
        f = frame.astype(np.float32)
        if f.ndim == 3 and f.shape[2] >= 3:
            # Weighted luma from BGR or RGB — intentionally channel-agnostic
            return 0.299 * f[:, :, 0] + 0.587 * f[:, :, 1] + 0.114 * f[:, :, 2]
        if f.ndim == 3 and f.shape[2] == 1:
            return f[:, :, 0]
        # Already 2-D
        return f

    def _compute_motion(self, gray: np.ndarray) -> float:
        """Mean absolute difference between consecutive gray frames, normalised."""
        if self._prev_gray is None or self._prev_gray.shape != gray.shape:
            return 0.0
        diff = np.abs(gray - self._prev_gray)
        return float(np.mean(diff)) / 255.0

    def _compute_scene_change_rate(self, gray: np.ndarray, now: float) -> float:
        """Update the scene-change counter and return changes-per-second."""
        current_mean = float(np.mean(gray))
        if self._prev_mean is not None:
            rel_change = abs(current_mean - self._prev_mean) / (
                max(self._prev_mean, 1e-6)
            )
            if rel_change > self.scene_change_threshold:
                self._scene_change_times.append(now)
        self._prev_mean = current_mean

        # Retain only changes within the last 10 s
        cutoff = now - 10.0
        self._scene_change_times = [
            t for t in self._scene_change_times if t > cutoff
        ]
        window = (
            now - self._scene_change_times[0]
            if self._scene_change_times
            else 0.0
        )
        return len(self._scene_change_times) / max(window, 1.0)

    @staticmethod
    def _detect_faces(frame: np.ndarray) -> Optional[float]:
        """Haar-cascade face detection. Returns 1.0/0.0 or None on failure."""
        try:
            import cv2  # optional dependency

            gray = (
                cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                if frame.ndim == 3
                else frame
            )
            cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            cascade = cv2.CascadeClassifier(cascade_path)
            faces = cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=3, minSize=(30, 30)
            )
            return 1.0 if len(faces) > 0 else 0.0
        except Exception:
            return None
