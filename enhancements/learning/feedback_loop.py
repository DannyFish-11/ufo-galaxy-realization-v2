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


@dataclass
class FeedbackRecord:
    """Represents a processed feedback record with analysis."""
    record_id: str
    entry: FeedbackEntry
    processed_at: datetime = field(default_factory=datetime.now)
    analysis_result: Dict[str, Any] = field(default_factory=dict)
    action_taken: Optional[str] = None
    effectiveness_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'record_id': self.record_id,
            'entry': self.entry.to_dict(),
            'processed_at': self.processed_at.isoformat(),
            'analysis_result': self.analysis_result,
            'action_taken': self.action_taken,
            'effectiveness_score': self.effectiveness_score
        }


class FeedbackLoop:
    """
    Manages feedback loops in the learning system.

    Collects, processes, and applies feedback to improve system behavior.
    """

    def __init__(self, max_history: int = 1000):
        self.max_history = max_history
        self._feedback_history: List[FeedbackEntry] = []
        self._feedback_records: List[FeedbackRecord] = []
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

    def add_record(self, record: FeedbackRecord) -> None:
        """Add a processed feedback record."""
        self._feedback_records.append(record)

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
