"""Signal quality and freshness metadata for multimodal perception signals."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class QualityFlag(str, Enum):
    """Quality flags for a modality signal."""

    OK = "ok"
    DEGRADED = "degraded"
    MISSING = "missing"
    STALE = "stale"
    PERMISSION_DENIED = "permission_denied"
    DEVICE_UNAVAILABLE = "device_unavailable"


@dataclass
class SignalQuality:
    """Quality and freshness descriptor for a single modality signal."""

    flag: QualityFlag = QualityFlag.MISSING
    freshness_ms: Optional[float] = None  # milliseconds since last update
    confidence: float = 0.0  # 0.0–1.0
    message: Optional[str] = None

    @property
    def is_usable(self) -> bool:
        """True when the signal is OK or degraded (but not missing/stale/denied)."""
        return self.flag in (QualityFlag.OK, QualityFlag.DEGRADED)

    @classmethod
    def ok(
        cls, freshness_ms: float = 0.0, confidence: float = 1.0
    ) -> "SignalQuality":
        return cls(flag=QualityFlag.OK, freshness_ms=freshness_ms, confidence=confidence)

    @classmethod
    def missing(cls, reason: Optional[str] = None) -> "SignalQuality":
        return cls(flag=QualityFlag.MISSING, confidence=0.0, message=reason)

    @classmethod
    def degraded(
        cls, reason: Optional[str] = None, confidence: float = 0.5
    ) -> "SignalQuality":
        return cls(flag=QualityFlag.DEGRADED, confidence=confidence, message=reason)

    @classmethod
    def stale(cls, freshness_ms: float, confidence: float = 0.3) -> "SignalQuality":
        return cls(
            flag=QualityFlag.STALE,
            freshness_ms=freshness_ms,
            confidence=confidence,
            message=f"Stale signal ({freshness_ms:.0f} ms)",
        )

    @classmethod
    def permission_denied(cls) -> "SignalQuality":
        return cls(
            flag=QualityFlag.PERMISSION_DENIED,
            confidence=0.0,
            message="Permission denied",
        )

    @classmethod
    def device_unavailable(cls) -> "SignalQuality":
        return cls(
            flag=QualityFlag.DEVICE_UNAVAILABLE,
            confidence=0.0,
            message="Device unavailable",
        )
