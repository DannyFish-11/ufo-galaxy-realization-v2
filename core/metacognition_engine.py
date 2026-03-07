"""
UFO Galaxy - 元认知引擎
========================

提供思维追踪、决策评估、认知反思和策略优化能力。
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("UFO-Galaxy.MetaCognition")


class ThoughtType(str, Enum):
    PERCEPTION = "perception"
    ANALYSIS = "analysis"
    DECISION = "decision"
    ACTION = "action"
    REFLECTION = "reflection"


class CognitiveBias(str, Enum):
    CONFIRMATION = "confirmation"
    ANCHORING = "anchoring"
    AVAILABILITY = "availability"
    OVERCONFIDENCE = "overconfidence"
    SUNK_COST = "sunk_cost"
    RECENCY = "recency"


@dataclass
class Thought:
    thought_id: str
    thought_type: ThoughtType
    content: str
    context: Dict[str, Any]
    quality_score: float = 0.0
    biases_detected: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "thought_id": self.thought_id,
            "thought_type": self.thought_type.value,
            "content": self.content,
            "context": self.context,
            "quality_score": self.quality_score,
            "biases_detected": self.biases_detected,
            "timestamp": self.timestamp,
        }


@dataclass
class Decision:
    decision_id: str
    decision_content: str
    alternatives: List[str]
    reasoning: str
    confidence: float
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "decision_id": self.decision_id,
            "decision_content": self.decision_content,
            "alternatives": self.alternatives,
            "reasoning": self.reasoning,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
        }


class MetaCognitionEngine:
    """元认知引擎 - 思维追踪、决策评估和认知优化"""

    def __init__(self):
        self.thought_history: List[Thought] = []
        self.decision_history: List[Decision] = []
        logger.info("元认知引擎已初始化")

    def track_thought(
        self, thought_type: str, content: str, context: Optional[Dict] = None
    ) -> Thought:
        t_type = ThoughtType(thought_type) if isinstance(thought_type, str) else thought_type
        thought = Thought(
            thought_id=f"thought_{uuid.uuid4().hex[:12]}",
            thought_type=t_type,
            content=content,
            context=context or {},
            quality_score=self._assess_quality(content, context),
            biases_detected=self._detect_biases(content, context),
        )
        self.thought_history.append(thought)
        return thought

    def track_decision(
        self,
        decision_content: str,
        alternatives: Optional[List[str]] = None,
        reasoning: str = "",
        confidence: float = 0.5,
    ) -> Decision:
        decision = Decision(
            decision_id=f"decision_{uuid.uuid4().hex[:12]}",
            decision_content=decision_content,
            alternatives=alternatives or [],
            reasoning=reasoning,
            confidence=max(0.0, min(1.0, confidence)),
        )
        self.decision_history.append(decision)
        return decision

    def evaluate_decision(self, decision_id: str, outcome: str) -> dict:
        decision = next((d for d in self.decision_history if d.decision_id == decision_id), None)
        if not decision:
            return {"error": f"Decision {decision_id} not found"}
        success_score = 0.7 if "success" in outcome.lower() else 0.3
        return {
            "overall_quality": round((success_score + decision.confidence) / 2, 2),
            "success_score": success_score,
            "confidence_match": round(1.0 - abs(success_score - decision.confidence), 2),
            "reasoning_quality": 0.6 if decision.reasoning else 0.3,
        }

    def reflect(self, time_window: Optional[float] = None) -> dict:
        cutoff = time.time() - time_window if time_window else 0
        recent_thoughts = [t for t in self.thought_history if t.timestamp >= cutoff]
        recent_decisions = [d for d in self.decision_history if d.timestamp >= cutoff]
        avg_quality = (
            sum(t.quality_score for t in recent_thoughts) / len(recent_thoughts)
            if recent_thoughts else 0.0
        )
        return {
            "thought_count": len(recent_thoughts),
            "decision_count": len(recent_decisions),
            "average_quality": round(avg_quality, 2),
            "common_biases": self._get_common_biases(recent_thoughts),
            "timestamp": time.time(),
        }

    def optimize_strategy(self, task_description: str, current_strategy: str) -> dict:
        return {
            "task": task_description,
            "current_strategy": current_strategy,
            "optimized_strategy": current_strategy,
            "improvements": [],
            "confidence": 0.5,
        }

    def get_cognitive_state(self) -> dict:
        return {
            "total_thoughts": len(self.thought_history),
            "total_decisions": len(self.decision_history),
            "recent_quality": self.reflect(time_window=3600).get("average_quality", 0),
        }

    def _assess_quality(self, content: str, context: Optional[Dict]) -> float:
        score = 0.5
        if content and len(content) > 20:
            score += 0.2
        if context:
            score += 0.1
        return min(1.0, score)

    def _detect_biases(self, content: str, context: Optional[Dict]) -> List[str]:
        return []

    def _get_common_biases(self, thoughts: List[Thought]) -> List[str]:
        all_biases = [b for t in thoughts for b in t.biases_detected]
        return list(set(all_biases))
