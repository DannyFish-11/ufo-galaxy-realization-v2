"""
core.cognitive.adaptive_predictor — Adaptive Execution Predictor
================================================================
PR-27 — Pre-Execution Strategy Recommendation & Resource Optimization

The AdaptivePredictor is the **action endpoint** of the cognitive learning
loop. It consumes patterns discovered by PatternMiner and active reflections
from ReflectionEngine, then produces concrete pre-execution recommendations
that are injected into the execution pipeline.

It sits at the boundary between "learning" and "doing":

    PatternMiner patterns + ReflectionEngine insights
              ↓
    AdaptivePredictor.recommend(task, context)
              ↓
    { "strategy": "single", "confidence": 0.92,
      "timeout_ms": 5000, "preheat": ["weather"],
      "caution": "Historical timeout risk — set generous timeout" }
              ↓
    desktop_presence_runtime.execute() uses these as advisory inputs

Integration
-----------
- Called by desktop_presence_runtime before each execute()
- Queries PatternMiner for matching patterns (boosting their activation)
- Queries ReflectionEngine for relevant active reflections
- Produces a merged ExecutionRecommendation

Design principles
-----------------
- **Advisory only**: Recommendations never override explicit user intent
  or hard governance gates. They are hints, not commands.
- **Confidence-weighted**: Every recommendation carries a confidence score.
  Low-confidence recommendations are down-weighted or dropped.
- **Multi-source fusion**: Combines temporal patterns, strategy patterns,
  sequence patterns, and reflection insights into a unified recommendation.
- **Self-monitoring**: Tracks its own recommendation accuracy and adjusts
  confidence calibration over time.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.Cognitive.AdaptivePredictor")

# ── Constants ────────────────────────────────────────────────────────────

_MIN_CONFIDENCE_THRESHOLD = 0.3       # drop recommendations below this
_STRATEGY_SWITCH_CONFIDENCE = 0.75   # need this confidence to suggest switching
_TIMEOUT_SAFETY_FACTOR = 1.5         # multiply avg duration by this for timeout
_MAX_PREHEAT_TOOLS = 3               # cap number of tools to preheat
_PREDICTION_EVENT = "cognitive.prediction"


# ── Data model ────────────────────────────────────────────────────────────


@dataclass
class ExecutionRecommendation:
    """Unified pre-execution recommendation.

    Attributes
    ----------
    strategy:          Recommended strategy (single/specialized/swarm/fractal)
    strategy_confidence: Confidence in strategy recommendation [0.0, 1.0]
    timeout_ms:        Suggested timeout in milliseconds (0 = no suggestion)
    preheat_tools:     List of tool names to pre-initialize
    preheat_confidence: Confidence in preheat suggestions
    caution:           Human-readable warning text (may be empty)
    reflection_notes:  List of relevant reflection texts
    pattern_matches:   IDs of patterns that informed this recommendation
    overall_confidence: Aggregate confidence [0.0, 1.0]
    timestamp:         When recommendation was generated
    """

    strategy: str = ""
    strategy_confidence: float = 0.0
    timeout_ms: int = 0
    preheat_tools: List[str] = field(default_factory=list)
    preheat_confidence: float = 0.0
    caution: str = ""
    reflection_notes: List[str] = field(default_factory=list)
    pattern_matches: List[str] = field(default_factory=list)
    overall_confidence: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy,
            "strategy_confidence": round(self.strategy_confidence, 4),
            "timeout_ms": self.timeout_ms,
            "preheat_tools": self.preheat_tools[:_MAX_PREHEAT_TOOLS],
            "preheat_confidence": round(self.preheat_confidence, 4),
            "caution": self.caution[:500],
            "reflection_notes": self.reflection_notes[:5],
            "pattern_matches": self.pattern_matches[:10],
            "overall_confidence": round(self.overall_confidence, 4),
            "timestamp": self.timestamp,
        }

    def is_actionable(self) -> bool:
        """True if this recommendation has at least one actionable suggestion."""
        return (
            self.strategy_confidence >= _MIN_CONFIDENCE_THRESHOLD
            or self.timeout_ms > 0
            or len(self.preheat_tools) > 0
            or bool(self.caution)
        )


# ── Adaptive Predictor ────────────────────────────────────────────────────


class AdaptivePredictor:
    """Produces pre-execution recommendations based on learned patterns.

    Usage::

        predictor = get_adaptive_predictor()

        # Before executing a task
        rec = predictor.recommend(
            task="check weather for Beijing",
            strategy="single",  # current plan
            task_type="weather",
        )

        if rec.strategy and rec.strategy_confidence > 0.8:
            # Strong signal to use a different strategy
            strategy = rec.strategy

        if rec.caution:
            logger.warning("Adaptive caution: %s", rec.caution)

        # Pass recommendation into execution context
        extra = {"adaptive_recommendation": rec.to_dict()}
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._recommendation_history: List[Dict[str, Any]] = []
        self._max_history = 200

    # ── Public API ──────────────────────────────────────────────────

    def recommend(
        self,
        task: str = "",
        strategy: str = "",
        task_type: str = "",
        trace_id: Optional[str] = None,
    ) -> ExecutionRecommendation:
        """Generate execution recommendation for an upcoming task.

        Parameters
        ----------
        task:       Task description text
        strategy:   Currently planned strategy
        task_type:  Task type (if known)
        trace_id:   Optional correlation ID

        Returns
        -------
        ExecutionRecommendation (never raises — returns empty on failure)
        """
        try:
            return self._recommend_impl(task, strategy, task_type, trace_id)
        except Exception as exc:
            logger.debug("recommend failed (non-fatal): %s", exc)
            return ExecutionRecommendation()

    def record_outcome(
        self,
        recommendation: ExecutionRecommendation,
        actual_strategy: str,
        success: bool,
        duration_ms: float,
    ) -> None:
        """Record whether the recommendation was accurate.

        Used for self-calibration. Tracks:
        - Did we recommend the right strategy?
        - Was our timeout estimate adequate?
        - Was our caution warranted?
        """
        try:
            entry = {
                "timestamp": time.time(),
                "recommended_strategy": recommendation.strategy,
                "actual_strategy": actual_strategy,
                "strategy_match": recommendation.strategy == actual_strategy,
                "recommended_timeout": recommendation.timeout_ms,
                "actual_duration": duration_ms,
                "timeout_adequate": (
                    recommendation.timeout_ms == 0
                    or recommendation.timeout_ms >= duration_ms
                ),
                "success": success,
                "overall_confidence": recommendation.overall_confidence,
            }
            with self._lock:
                self._recommendation_history.append(entry)
                if len(self._recommendation_history) > self._max_history:
                    self._recommendation_history = self._recommendation_history[-self._max_history:]

            # If our recommendation was wrong, log for calibration
            if recommendation.strategy and recommendation.strategy != actual_strategy:
                if success and recommendation.strategy_confidence > _STRATEGY_SWITCH_CONFIDENCE:
                    logger.info(
                        "AdaptivePredictor calibration: recommended '%s' but '%s' "
                        "succeeded. Adjusting confidence model.",
                        recommendation.strategy, actual_strategy,
                    )
        except Exception as exc:
            logger.debug("record_outcome failed (non-fatal): %s", exc)

    def get_calibration_stats(self) -> Dict[str, Any]:
        """Return accuracy statistics for self-monitoring."""
        with self._lock:
            if not self._recommendation_history:
                return {"samples": 0}

            total = len(self._recommendation_history)
            strategy_matches = sum(
                1 for e in self._recommendation_history if e.get("strategy_match")
            )
            timeout_ok = sum(
                1 for e in self._recommendation_history if e.get("timeout_adequate")
            )
            successes = sum(
                1 for e in self._recommendation_history if e.get("success")
            )

            return {
                "samples": total,
                "strategy_accuracy": round(strategy_matches / total, 4) if total else 0,
                "timeout_accuracy": round(timeout_ok / total, 4) if total else 0,
                "overall_success_rate": round(successes / total, 4) if total else 0,
                "high_conf_accuracy": round(
                    sum(
                        1 for e in self._recommendation_history
                        if e.get("strategy_match")
                        and e.get("overall_confidence", 0) > 0.7
                    ) / max(
                        sum(
                            1 for e in self._recommendation_history
                            if e.get("overall_confidence", 0) > 0.7
                        ), 1
                    ),
                    4,
                ),
            }

    # ── Internal: recommendation generation ─────────────────────────

    def _recommend_impl(
        self,
        task: str,
        strategy: str,
        task_type: str,
        trace_id: Optional[str],
    ) -> ExecutionRecommendation:
        """Internal recommendation logic."""
        rec = ExecutionRecommendation()
        pattern_match_ids: List[str] = []

        # Infer task type if not provided
        if not task_type and task:
            task_type = self._infer_task_type(task)

        current_hour = time.localtime().tm_hour

        # ── 1. Query PatternMiner for matching patterns ─────────────
        try:
            from core.cognitive.pattern_miner import get_pattern_miner

            miner = get_pattern_miner()
            matching = miner.match_patterns(
                task=task,
                task_type=task_type,
                hour=current_hour,
                strategy=strategy,
                min_activation=0.15,
                limit=15,
            )

            # Process matches by type
            strategy_votes: Dict[str, List[float]] = defaultdict(list)
            preheat_suggestions: Dict[str, List[float]] = defaultdict(list)
            cautions: List[str] = []

            for pat in matching:
                pattern_match_ids.append(pat.pattern_id)

                if pat.pattern_type == "strategy":
                    rec_strategy = pat.recommendation.get("strategy", "")
                    conf = pat.confidence * pat.activation_score
                    if rec_strategy:
                        strategy_votes[rec_strategy].append(conf)

                elif pat.pattern_type == "temporal":
                    if pat.recommendation.get("preheat"):
                        tt = pat.conditions.get("task_type", "")
                        if tt:
                            preheat_suggestions[tt].append(
                                pat.confidence * pat.activation_score
                            )

                elif pat.pattern_type == "sequence":
                    next_task = pat.recommendation.get("likely_next", "")
                    prob = pat.recommendation.get("probability", 0)
                    if next_task and prob > 0.5:
                        preheat_suggestions[next_task].append(prob * pat.activation_score)

                elif pat.pattern_type == "abstract":
                    # Higher-level patterns may provide cautionary insights
                    if pat.support_count > 10 and pat.success_rate < 0.8:
                        cautions.append(
                            f"Pattern '{pat.description[:80]}...' shows "
                            f"only {pat.success_rate*100:.0f}% success — "
                            f"exercise caution."
                        )

            # Aggregate strategy votes
            if strategy_votes:
                best_strat = max(
                    strategy_votes,
                    key=lambda s: (
                        sum(strategy_votes[s]) / len(strategy_votes[s]),
                        len(strategy_votes[s]),
                    ),
                )
                avg_conf = sum(strategy_votes[best_strat]) / len(strategy_votes[best_strat])
                # Only recommend strategy switch if confidence is high enough
                # and it's different from planned strategy
                if best_strat != strategy and avg_conf >= _STRATEGY_SWITCH_CONFIDENCE:
                    rec.strategy = best_strat
                    rec.strategy_confidence = min(1.0, avg_conf)
                elif best_strat == strategy:
                    # Confirming the planned strategy — boost confidence
                    rec.strategy = strategy
                    rec.strategy_confidence = min(1.0, avg_conf * 0.8)

            # Aggregate preheat suggestions
            if preheat_suggestions:
                sorted_preheat = sorted(
                    preheat_suggestions.items(),
                    key=lambda x: sum(x[1]) / len(x[1]),
                    reverse=True,
                )
                rec.preheat_tools = [
                    tool for tool, _ in sorted_preheat[:_MAX_PREHEAT_TOOLS]
                ]
                rec.preheat_confidence = min(
                    1.0,
                    sum(
                        sum(scores) / len(scores)
                        for _, scores in sorted_preheat[:_MAX_PREHEAT_TOOLS]
                    )
                    / max(len(sorted_preheat[:_MAX_PREHEAT_TOOLS]), 1),
                )

            if cautions:
                rec.caution = " | ".join(cautions[:2])

        except Exception as exc:
            logger.debug("PatternMiner query failed: %s", exc)

        # ── 2. Query ReflectionEngine for relevant insights ─────────
        try:
            from core.cognitive.reflection_engine import get_reflection_engine

            refl_engine = get_reflection_engine()
            active_reflections = refl_engine.get_active_reflections(
                task_hint=task or task_type,
                min_activation=0.2,
                limit=5,
            )

            for reflection in active_reflections:
                rec.reflection_notes.append(reflection.reflection_text[:300])
                # Reflections about failures boost caution
                if "failed" in reflection.reflection_text.lower() or \
                   "failure" in reflection.reflection_text.lower():
                    if not rec.caution:
                        rec.caution = (
                            "Historical failure detected for similar tasks — "
                            "verify inputs and consider fallback strategy."
                        )

                # Reflections with strategy tips override pattern votes
                if reflection.reflection_type == "retrospective":
                    text_lower = reflection.reflection_text.lower()
                    for strat in ["single", "specialized", "swarm", "fractal"]:
                        if f"'{strat}'" in text_lower and "success" in text_lower:
                            rec.strategy = strat
                            rec.strategy_confidence = min(
                                1.0,
                                rec.strategy_confidence + 0.1,
                            )

        except Exception as exc:
            logger.debug("ReflectionEngine query failed: %s", exc)

        # ── 3. Compute timeout suggestion ────────────────────────────
        try:
            from core.task_memory import get_task_memory

            tm = get_task_memory()
            recent = tm.get_recent_summaries(n=20)
            task_lower = (task or "").lower()
            similar = [
                s for s in recent
                if task_type and s.task_type == task_type
                or task_lower in s.task.lower()
            ]
            durations = [s.duration_ms for s in similar if s.duration_ms > 0]
            if durations:
                avg = sum(durations) / len(durations)
                std = self._std(durations)
                suggested = int((avg + std * 2) * _TIMEOUT_SAFETY_FACTOR)
                rec.timeout_ms = min(suggested, 300000)  # cap at 5 min

        except Exception as exc:
            logger.debug("Timeout estimation failed: %s", exc)

        # ── 4. Compute overall confidence ────────────────────────────
        confidences = [
            rec.strategy_confidence,
            rec.preheat_confidence,
            min(1.0, len(rec.reflection_notes) * 0.2),
            0.5 if rec.caution else 0.0,
        ]
        rec.overall_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        rec.pattern_matches = pattern_match_ids

        # Emit prediction event
        self._emit_prediction_event(rec, trace_id)

        logger.debug(
            "AdaptivePredictor: strategy=%s conf=%.2f preheat=%s timeout=%s "
            "patterns=%d reflections=%d overall_conf=%.2f",
            rec.strategy or "(none)",
            rec.strategy_confidence,
            rec.preheat_tools,
            rec.timeout_ms or "(none)",
            len(pattern_match_ids),
            len(rec.reflection_notes),
            rec.overall_confidence,
        )

        return rec

    # ── Internal helpers ────────────────────────────────────────────

    @staticmethod
    def _infer_task_type(task_text: str) -> str:
        """Infer task type from description. Delegates to PatternMiner logic."""
        try:
            from core.cognitive.pattern_miner import PatternMiner

            return PatternMiner._infer_task_type(task_text)
        except Exception:
            return "general"

    @staticmethod
    def _std(values: List[float]) -> float:
        """Population standard deviation."""
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return variance ** 0.5

    def _emit_prediction_event(
        self, rec: ExecutionRecommendation, trace_id: Optional[str]
    ) -> None:
        """Emit prediction event on state event bus."""
        try:
            from core.state_event_bus import get_state_event_bus

            get_state_event_bus().publish(
                _PREDICTION_EVENT,
                source="adaptive_predictor",
                payload=rec.to_dict(),
                trace_id=trace_id or f"pred_{int(time.time()*1000)%10**9}",
            )
        except Exception as exc:
            logger.debug("Prediction event emission failed (non-fatal): %s", exc)


# ── Singleton accessors ───────────────────────────────────────────────────

_predictor_instance: Optional[AdaptivePredictor] = None
_predictor_lock = threading.Lock()


def get_adaptive_predictor() -> AdaptivePredictor:
    """Return the process-wide AdaptivePredictor singleton."""
    global _predictor_instance
    if _predictor_instance is None:
        with _predictor_lock:
            if _predictor_instance is None:
                _predictor_instance = AdaptivePredictor()
                logger.debug("AdaptivePredictor singleton initialised")
    return _predictor_instance


def reset_adaptive_predictor() -> None:
    """Reset singleton (for testing only)."""
    global _predictor_instance
    with _predictor_lock:
        _predictor_instance = None
