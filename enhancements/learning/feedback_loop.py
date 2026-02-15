"""
Feedback Loop Module for UFO Galaxy v5.0

This module implements feedback loop mechanisms for the learning system.

Author: UFO Galaxy Team
Version: 5.0.0
"""

import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto

logger = logging.getLogger(__name__)


class FeedbackTarget(Enum):
    """Targets for feedback."""
    SYSTEM = auto()
    MODEL = auto()
    STRATEGY = auto()
    BEHAVIOR = auto()
    USER = auto()


class FeedbackType(Enum):
    """Types of feedback."""
    POSITIVE = auto()
    NEGATIVE = auto()
    NEUTRAL = auto()
    CORRECTIVE = auto()


@dataclass
class FeedbackEntry:
    """Represents a feedback entry."""
    feedback_id: str
    feedback_type: FeedbackType
    source: str
    target: str
    content: str
    confidence: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FeedbackRecord:
    """Represents a feedback record for autonomous learning."""
    record_id: str
    action: str
    outcome: str
    success: bool
    reward: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)
    context: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'record_id': self.record_id,
            'action': self.action,
            'outcome': self.outcome,
            'success': self.success,
            'reward': self.reward,
            'timestamp': self.timestamp.isoformat(),
            'context': self.context
        }
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'feedback_id': self.feedback_id,
            'feedback_type': self.feedback_type.name,
            'source': self.source,
            'target': self.target,
            'content': self.content,
            'confidence': self.confidence,
            'timestamp': self.timestamp.isoformat(),
            'metadata': self.metadata
        }
    
    @classmethod
    def from_record(cls, record: 'FeedbackRecord') -> 'FeedbackEntry':
        """Create FeedbackEntry from FeedbackRecord."""
        feedback_type = FeedbackType.POSITIVE if record.success else FeedbackType.NEGATIVE
        return cls(
            feedback_id=record.record_id,
            feedback_type=feedback_type,
            source='autonomous_learning',
            target='system',
            content=f"{record.action} -> {record.outcome}",
            confidence=abs(record.reward),
            timestamp=record.timestamp,
            metadata=record.context
        )


class FeedbackLoop:
    """
    Manages feedback loops in the learning system.
    
    Collects, processes, and applies feedback to improve system behavior.
    """
    
    def __init__(self, max_history: int = 1000):
        self.max_history = max_history
        self._feedback_history: List[FeedbackEntry] = []
        self._feedback_handlers: Dict[FeedbackType, List] = {
            ft: [] for ft in FeedbackType
        }
        logger.info("FeedbackLoop initialized")
    
    def add_feedback(self, feedback: FeedbackEntry) -> None:
        """Add feedback entry."""
        self._feedback_history.append(feedback)
        if len(self._feedback_history) > self.max_history:
            self._feedback_history = self._feedback_history[-self.max_history:]
        
        # Notify handlers
        for handler in self._feedback_handlers.get(feedback.feedback_type, []):
            try:
                handler(feedback)
            except Exception as e:
                logger.error(f"Feedback handler error: {e}")
    
    def register_handler(self, feedback_type: FeedbackType, handler) -> None:
        """Register a feedback handler."""
        self._feedback_handlers[feedback_type].append(handler)
    
    def get_recent_feedback(
        self,
        feedback_type: Optional[FeedbackType] = None,
        limit: int = 100
    ) -> List[FeedbackEntry]:
        """Get recent feedback entries."""
        entries = self._feedback_history
        if feedback_type:
            entries = [e for e in entries if e.feedback_type == feedback_type]
        return entries[-limit:]
    
    def get_feedback_stats(self) -> Dict[str, Any]:
        """Get feedback statistics."""
        type_counts = {}
        for entry in self._feedback_history:
            type_name = entry.feedback_type.name
            type_counts[type_name] = type_counts.get(type_name, 0) + 1
        
        return {
            'total_feedback': len(self._feedback_history),
            'by_type': type_counts
        }
    
    def clear_history(self) -> None:
        """Clear feedback history."""
        self._feedback_history.clear()


@dataclass
class PerformanceMetric:
    """Represents a performance metric."""
    metric_name: str
    value: float
    unit: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    context: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'metric_name': self.metric_name,
            'value': self.value,
            'unit': self.unit,
            'timestamp': self.timestamp.isoformat(),
            'context': self.context
        }


class MetricsTracker:
    """Tracks performance metrics over time."""
    
    def __init__(self, max_history: int = 10000):
        self.max_history = max_history
        self._metrics: Dict[str, List[PerformanceMetric]] = {}
        logger.info("MetricsTracker initialized")
    
    def record_metric(self, metric: PerformanceMetric) -> None:
        """Record a performance metric."""
        if metric.metric_name not in self._metrics:
            self._metrics[metric.metric_name] = []
        
        self._metrics[metric.metric_name].append(metric)
        
        # Trim history
        if len(self._metrics[metric.metric_name]) > self.max_history:
            self._metrics[metric.metric_name] = self._metrics[metric.metric_name][-self.max_history:]
    
    def get_metrics(self, metric_name: str, limit: int = 100) -> List[PerformanceMetric]:
        """Get recent metrics by name."""
        return self._metrics.get(metric_name, [])[-limit:]
    
    def get_average(self, metric_name: str, window: int = 100) -> Optional[float]:
        """Get average value of a metric over a window."""
        metrics = self.get_metrics(metric_name, window)
        if not metrics:
            return None
        return sum(m.value for m in metrics) / len(metrics)
    
    def clear_metrics(self, metric_name: Optional[str] = None) -> None:
        """Clear metrics history."""
        if metric_name:
            self._metrics.pop(metric_name, None)
        else:
            self._metrics.clear()


class ReinforcementLearner:
    """Implements reinforcement learning for system improvement."""
    
    def __init__(self, learning_rate: float = 0.1, discount_factor: float = 0.9):
        self.learning_rate = learning_rate
        self.discount_factor = discount_factor
        self._q_table: Dict[str, Dict[str, float]] = {}
        self._state_visits: Dict[str, int] = {}
        logger.info("ReinforcementLearner initialized")
    
    def get_q_value(self, state: str, action: str) -> float:
        """Get Q-value for state-action pair."""
        return self._q_table.get(state, {}).get(action, 0.0)
    
    def update_q_value(
        self,
        state: str,
        action: str,
        reward: float,
        next_state: str
    ) -> None:
        """Update Q-value using Q-learning algorithm."""
        if state not in self._q_table:
            self._q_table[state] = {}
        
        current_q = self.get_q_value(state, action)
        
        # Get max Q-value for next state
        next_q_values = self._q_table.get(next_state, {}).values()
        max_next_q = max(next_q_values) if next_q_values else 0.0
        
        # Q-learning update
        new_q = current_q + self.learning_rate * (
            reward + self.discount_factor * max_next_q - current_q
        )
        
        self._q_table[state][action] = new_q
        self._state_visits[state] = self._state_visits.get(state, 0) + 1
    
    def choose_action(
        self,
        state: str,
        available_actions: List[str],
        epsilon: float = 0.1
    ) -> str:
        """Choose action using epsilon-greedy policy."""
        import random
        
        if random.random() < epsilon:
            # Explore: random action
            return random.choice(available_actions)
        else:
            # Exploit: best action
            q_values = {a: self.get_q_value(state, a) for a in available_actions}
            return max(q_values, key=q_values.get)
    
    def get_policy(self, state: str) -> Dict[str, float]:
        """Get policy (Q-values) for a state."""
        return self._q_table.get(state, {}).copy()
