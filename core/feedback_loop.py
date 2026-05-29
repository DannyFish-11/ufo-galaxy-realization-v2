"""
core/feedback_loop.py
=====================
PR-FEEDBACK-LOOP: Execution Result → Evaluation → Learning → Improvement.

Closes the loop between action execution and Agent improvement:
  1. Observe: Record execution result (success/failure/duration).
  2. Evaluate: Assess quality (was it what the user wanted?).
  3. Learn: Update preferences, identify patterns.
  4. Improve: Adjust future behavior.

Integrates with:
  - UserPreferenceMemory — updates device/action preferences
  - TaskMemory — records execution summary
  - StateEventBus — emits feedback events for observability

Usage::
    from core.feedback_loop import get_feedback_loop

    loop = get_feedback_loop()
    loop.record_result(
        task_id="task_123",
        device_id="phone_01",
        action="adb_screenshot",
        success=True,
        duration_ms=500,
        user_input="截图",
    )
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.FeedbackLoop")

DEFAULT_FEEDBACK_PATH = Path.home() / ".galaxy" / "feedback_history.json"


@dataclass
class FeedbackEntry:
    """A single feedback entry."""

    task_id: str
    device_id: str
    action: str
    success: bool
    duration_ms: int
    user_input: str = ""
    error_message: str = ""
    timestamp: float = field(default_factory=time.time)
    evaluation: str = ""  # "good", "bad", "slow", "unexpected"
    context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ActionQuality:
    """Aggregated quality metrics for an action."""

    action: str
    total_executions: int = 0
    success_count: int = 0
    failure_count: int = 0
    avg_duration_ms: float = 0.0
    failure_reasons: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    last_failed: float = 0.0
    trend: str = "stable"  # improving, degrading, stable

    def record(self, success: bool, duration_ms: int, error: str = "") -> None:
        self.total_executions += 1
        if success:
            self.success_count += 1
        else:
            self.failure_count += 1
            self.last_failed = time.time()
            if error:
                self.failure_reasons[error[:100]] += 1

        # Update rolling average
        self.avg_duration_ms = (
            self.avg_duration_ms * (self.total_executions - 1) + duration_ms
        ) / self.total_executions

        # Update trend
        if self.total_executions >= 5:
            recent_rate = self.success_count / self.total_executions
            if recent_rate > 0.9:
                self.trend = "improving"
            elif recent_rate < 0.5:
                self.trend = "degrading"
            else:
                self.trend = "stable"


from collections import defaultdict


class FeedbackLoop:
    """Execution feedback collection and learning loop."""

    MAX_HISTORY = 1000

    def __init__(self, path: Optional[Path] = None):
        self._path = path or DEFAULT_FEEDBACK_PATH
        self._history: List[FeedbackEntry] = []
        self._action_quality: Dict[str, ActionQuality] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._history = [FeedbackEntry(**e) for e in data.get("history", [])]
                for aq_data in data.get("action_quality", {}).values():
                    aq = ActionQuality(**aq_data)
                    self._action_quality[aq.action] = aq
                logger.info("Feedback history loaded: %d entries", len(self._history))
            except Exception as exc:
                logger.debug("Feedback load failed: %s", exc)

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "history": [e.to_dict() for e in self._history[-self.MAX_HISTORY :]],
                "action_quality": {
                    k: asdict(v) for k, v in self._action_quality.items()
                },
            }
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            logger.debug("Feedback save failed: %s", exc)

    # ── Recording ──

    def record_result(
        self,
        *,
        task_id: str,
        device_id: str,
        action: str,
        success: bool,
        duration_ms: int,
        user_input: str = "",
        error_message: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record an execution result and trigger learning."""
        entry = FeedbackEntry(
            task_id=task_id,
            device_id=device_id,
            action=action,
            success=success,
            duration_ms=duration_ms,
            user_input=user_input,
            error_message=error_message,
            context=context or {},
        )
        self._history.append(entry)

        # Update action quality
        if action not in self._action_quality:
            self._action_quality[action] = ActionQuality(action=action)
        self._action_quality[action].record(success, duration_ms, error_message)

        # Emit state event
        self._emit_feedback_event(entry)

        # Update user preferences
        self._update_preferences(entry)

        # Trim history
        if len(self._history) > self.MAX_HISTORY:
            self._history = self._history[-self.MAX_HISTORY :]

        self._save()

        logger.debug(
            "Feedback: %s on %s: %s (%.0fms)",
            action,
            device_id,
            "OK" if success else "FAIL",
            duration_ms,
        )

    def record_user_evaluation(self, task_id: str, evaluation: str) -> None:
        """Record explicit user feedback (good/bad/etc)."""
        for entry in reversed(self._history):
            if entry.task_id == task_id:
                entry.evaluation = evaluation
                self._save()
                logger.info("User evaluation for %s: %s", task_id, evaluation)
                return
        logger.debug("Task %s not found for user evaluation", task_id)

    # ── Learning ──

    def _update_preferences(self, entry: FeedbackEntry) -> None:
        """Update UserPreferenceMemory based on feedback."""
        try:
            from core.user_preference_memory import get_user_preference_memory  # noqa: PLC0415

            prefs = get_user_preference_memory()
            prefs.record_device_usage(
                device_id=entry.device_id,
                action=entry.action,
                success=entry.success,
            )
            if entry.user_input:
                prefs.record_command(entry.user_input, entry.action)
        except Exception:
            pass

    def _emit_feedback_event(self, entry: FeedbackEntry) -> None:
        """Emit feedback event on state event bus."""
        try:
            from core.state_event_bus import emit as _emit, StateEventType  # noqa: PLC0415

            event_type = StateEventType.TASK_SUCCEEDED if entry.success else StateEventType.TASK_FAILED
            _emit(
                event_type,
                source="feedback_loop",
                payload={
                    "action": entry.action,
                    "device_id": entry.device_id,
                    "duration_ms": entry.duration_ms,
                    "error": entry.error_message[:200] if entry.error_message else "",
                },
                trace_id=entry.task_id,
            )
        except Exception:
            pass

    # ── Query ──

    def get_action_quality(self, action: str) -> Optional[Dict[str, Any]]:
        """Get quality metrics for an action."""
        aq = self._action_quality.get(action)
        if aq is None:
            return None
        total = aq.total_executions
        return {
            "action": aq.action,
            "total": total,
            "success_rate": aq.success_count / total if total > 0 else 0,
            "avg_duration_ms": round(aq.avg_duration_ms, 1),
            "trend": aq.trend,
            "top_failure_reasons": sorted(
                aq.failure_reasons.items(), key=lambda x: x[1], reverse=True
            )[:3],
        }

    def get_recent_failures(self, n: int = 10) -> List[Dict[str, Any]]:
        """Get recent failure entries."""
        failures = [e for e in self._history if not e.success]
        return [e.to_dict() for e in failures[-n:]]

    def get_improvement_suggestions(self) -> List[str]:
        """Generate improvement suggestions based on feedback history."""
        suggestions = []

        for action, aq in self._action_quality.items():
            if aq.total_executions < 3:
                continue

            success_rate = aq.success_count / aq.total_executions

            if success_rate < 0.5:
                suggestions.append(
                    f"Action '{action}' has low success rate ({success_rate:.0%}). "
                    f"Consider using a different device or approach."
                )

            if aq.avg_duration_ms > 5000:
                suggestions.append(
                    f"Action '{action}' is slow (avg {aq.avg_duration_ms:.0f}ms). "
                    f"Consider optimizing or using a faster device."
                )

            if aq.trend == "degrading":
                suggestions.append(
                    f"Action '{action}' reliability is declining. "
                    f"Top failure: {aq.failure_reasons.most_common(1)}"
                )

        return suggestions

    def get_statistics(self) -> Dict[str, Any]:
        """Get overall feedback statistics."""
        total = len(self._history)
        if total == 0:
            return {"total_executions": 0}

        successes = sum(1 for e in self._history if e.success)
        return {
            "total_executions": total,
            "overall_success_rate": successes / total,
            "unique_actions": len(self._action_quality),
            "avg_duration_ms": round(
                sum(e.duration_ms for e in self._history) / total, 1
            ),
            "action_breakdown": {
                action: {
                    "total": aq.total_executions,
                    "success_rate": (
                        aq.success_count / aq.total_executions if aq.total_executions > 0 else 0
                    ),
                }
                for action, aq in self._action_quality.items()
            },
        }


# Singleton
_feedback_loop: Optional[FeedbackLoop] = None


def get_feedback_loop() -> FeedbackLoop:
    """Return the module-level :class:`FeedbackLoop` singleton."""
    global _feedback_loop
    if _feedback_loop is None:
        _feedback_loop = FeedbackLoop()
    return _feedback_loop
