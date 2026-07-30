"""可打扰性登记处 —— 手表报上来的「现在能不能打扰他」。

## 这块解决什么

常驻注意力循环(``core/ambient_attention_loop.py``)的决策提示词里写着
「克制是美德——拿不准就选 SILENT」。那只是一句**祈使句**:模型无从知道
此刻用户是在发呆还是在跑步、在开会还是在睡觉。手表能知道,于是这里把
那句话变成一个**可测量的输入**。

## 隐私边界(所有者拍板)

心率/运动/睡眠这些原始信号**只在手表本地参与运算,从不上传**。上来的
只有一个标量报告(见 galaxy-wearos 的 ``com.galaxy.wear.sensing``)。
本模块只认那几个字段,多余字段一律丢弃 —— 就算某天手表侧被改坏了往上
塞生物数据,也进不了这里。

## 三条不能含糊的语义

1. **UNKNOWN ≠ FREE**。「没有传感证据」不是「可以打扰」。
   :meth:`InterruptibilityRegistry.is_blocked` 对 UNKNOWN 返回 False
   (不阻拦),但 :meth:`prompt_line` 对 UNKNOWN 返回空串(不误导模型)。
   这两件事必须分开:不阻拦 ≠ 有理由放行。
2. **陈旧即不存在**。手表掉线后,最后一条报告不能被无限期当成现状。
   超过 :data:`STALE_AFTER_S` 一律视为没有数据。手表侧每 10 分钟发一次
   心跳(``InterruptibilityUplinkPolicy.HEARTBEAT_MS``),这里给到 25 分钟,
   容得下两次丢包。
3. **有界延迟,不是丢弃**(bounded deferral)。BLOCKED 的语义是「此刻别
   **主动**开口」,不是「把这件事扔掉」。用户**显式发起**的请求完全不受
   这个分数约束。
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

#: 手表侧 ``InterruptibilityBand`` 的线上字符串。跨仓协议,改动即漂移
#: (手表侧由 ``InterruptibilityWireContractTest`` 钉死)。
KNOWN_BANDS = ("unknown", "blocked", "busy", "neutral", "free")

#: 超过这么久没收到新报告,就当作没有数据(手表心跳周期 10 分钟)。
STALE_AFTER_S = 25 * 60.0

#: 原因标签的数量与长度上限。手表是可信端,但登记处不该无条件相信任何
#: 上行内容 —— 否则一条畸形报文就能把提示词撑爆。
_MAX_REASONS = 8
_MAX_REASON_LEN = 32

#: 粗粒度标签 → 中文说法。未登记的标签原样透传(前向兼容,不吞掉新标签)。
_REASON_LABELS = {
    "dnd": "已开勿扰",
    "likely_asleep": "极可能在睡",
    "attending": "正抬腕在看",
    "high_motion": "运动量大",
    "moderate_motion": "有一定活动",
    "still": "静止",
    "elevated_arousal": "心率高于其个人静息",
    "calm": "平静",
    "recent_interaction": "刚交互过",
    "no_sensor_data": "无传感证据",
}


@dataclass(frozen=True)
class InterruptibilitySnapshot:
    """一条已校验的报告。"""

    score: float
    band: str
    reasons: tuple = field(default_factory=tuple)
    confidence: float = 0.0
    device_id: str = ""
    received_at: float = 0.0

    @property
    def usable(self) -> bool:
        """有没有值得据此行动的证据。

        UNKNOWN 或零置信度 = 手表在,但说不出个所以然 —— 这条报告本身是
        有意义的(至少说明手表在线),但**不能**拿来当判断依据。
        """
        return self.band != "unknown" and self.confidence > 0.0

    def is_stale(self, now: Optional[float] = None) -> bool:
        return (now if now is not None else time.time()) - self.received_at > STALE_AFTER_S

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": round(self.score, 2),
            "band": self.band,
            "reasons": list(self.reasons),
            "confidence": round(self.confidence, 2),
            "device_id": self.device_id,
            "received_at": self.received_at,
        }


def _coerce_unit(value: Any, default: float = 0.0) -> float:
    """任何东西 → [0,1] 的 float。转不动就取默认值,不抛异常炸掉 WS 主流程。"""
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return default


def _coerce_reasons(value: Any) -> tuple:
    if not isinstance(value, (list, tuple)):
        return ()
    out: List[str] = []
    for item in value[:_MAX_REASONS]:
        if isinstance(item, str) and item:
            out.append(item[:_MAX_REASON_LEN])
    return tuple(out)


class InterruptibilityRegistry:
    """按设备存最新一条报告;读的时候只认新鲜的那条。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_device: Dict[str, InterruptibilitySnapshot] = {}

    # ── 写 ──────────────────────────────────────────────────────────────

    def record(
        self,
        payload: Dict[str, Any],
        device_id: str = "",
        now: Optional[float] = None,
    ) -> Optional[InterruptibilitySnapshot]:
        """收下一条上行报告。band 不认识就整条拒收(协议漂移要看得见)。"""
        if not isinstance(payload, dict):
            return None

        band = str(payload.get("band") or "").strip().lower()
        if band not in KNOWN_BANDS:
            # 不静默吞:手表侧新增档位而这里没跟上,是必须被人看见的漂移。
            logger.warning(
                "可打扰性上报的 band=%r 不在已知集合 %s 内(协议漂移?),整条拒收",
                band,
                KNOWN_BANDS,
            )
            return None

        snapshot = InterruptibilitySnapshot(
            score=_coerce_unit(payload.get("score"), 0.5),
            band=band,
            reasons=_coerce_reasons(payload.get("reasons")),
            confidence=_coerce_unit(payload.get("confidence"), 0.0),
            device_id=str(device_id or payload.get("device") or ""),
            received_at=now if now is not None else time.time(),
        )
        with self._lock:
            self._by_device[snapshot.device_id] = snapshot
        return snapshot

    # ── 读 ──────────────────────────────────────────────────────────────

    def current(self, now: Optional[float] = None) -> Optional[InterruptibilitySnapshot]:
        """最新且未过期的那条;一条都没有则 None。

        多块手表时取**最新**那条 —— 人只有一个,后报的更接近现状。
        """
        ts = now if now is not None else time.time()
        with self._lock:
            fresh = [s for s in self._by_device.values() if not s.is_stale(ts)]
        if not fresh:
            return None
        return max(fresh, key=lambda s: s.received_at)

    def is_blocked(self, now: Optional[float] = None) -> bool:
        """此刻是否明确不宜**主动**开口。

        只有 BLOCKED 才返回 True。UNKNOWN/陈旧/没有手表一律 False ——
        「不知道」不构成阻拦的理由,正如它不构成放行的理由。
        """
        snapshot = self.current(now)
        return bool(snapshot and snapshot.band == "blocked")

    def prompt_line(self, now: Optional[float] = None) -> str:
        """给决策脑的一行提示;没有可用证据时返回空串(**不写模棱两可的话**)。

        NEUTRAL 也返回空串:它的信息量是零,写进提示词只会占 token、
        还可能被模型当成某种暗示。
        """
        snapshot = self.current(now)
        if snapshot is None or not snapshot.usable:
            return ""

        labels = "、".join(_REASON_LABELS.get(r, r) for r in snapshot.reasons)
        detail = f"({labels})" if labels else ""
        hedge = "，但证据不足、仅供参考" if snapshot.confidence < 0.5 else ""

        if snapshot.band == "blocked":
            return f"（手表：此刻明确不宜打扰{detail}{hedge}。除非极其紧要，请选 SILENT。）"
        if snapshot.band == "busy":
            return f"（手表：用户此刻偏忙{detail}{hedge}。除非要紧，倾向 SILENT。）"
        if snapshot.band == "free":
            return f"（手表：用户此刻大概率可被打扰{detail}{hedge}。）"
        return ""

    # ── 运维 ────────────────────────────────────────────────────────────

    def snapshot_all(self, now: Optional[float] = None) -> Dict[str, Any]:
        """给面板/诊断看的全量视图,含陈旧标记(陈旧也要看得见,不能藏起来)。"""
        ts = now if now is not None else time.time()
        with self._lock:
            items = list(self._by_device.values())
        return {
            "devices": [{**s.to_dict(), "stale": s.is_stale(ts)} for s in items],
            "stale_after_s": STALE_AFTER_S,
        }

    def clear(self) -> None:
        with self._lock:
            self._by_device.clear()


_registry: Optional[InterruptibilityRegistry] = None
_registry_lock = threading.Lock()


def get_interruptibility_registry() -> InterruptibilityRegistry:
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = InterruptibilityRegistry()
    return _registry


def reset_interruptibility_registry() -> None:
    """测试用:丢掉单例,避免用例之间互相污染。"""
    global _registry
    with _registry_lock:
        _registry = None
