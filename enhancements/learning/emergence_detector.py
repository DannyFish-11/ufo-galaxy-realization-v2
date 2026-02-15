"""
Emergence Detector for UFO Galaxy v5.0

This module detects emergent behaviors and patterns in the learning system.
Emergent behaviors are complex patterns that arise from the interaction
of simpler components.

Author: UFO Galaxy Team
Version: 5.0.0
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
import numpy as np

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class EmergenceType(Enum):
    """Types of emergent behaviors."""
    SYNERGY = auto()          # Multiple patterns combining to create new behavior
    ADAPTATION = auto()       # System adapting to new conditions
    SELF_ORGANIZATION = auto() # Spontaneous order formation
    FEEDBACK_LOOP = auto()    # Positive/negative feedback emergence
    COLLECTIVE = auto()       # Collective behavior from individual actions


@dataclass
class EmergenceEvent:
    """Represents an emergence event."""
    event_id: str
    event_type: EmergenceType
    timestamp: datetime
    source: str
    data: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'event_id': self.event_id,
            'event_type': self.event_type.name,
            'timestamp': self.timestamp.isoformat(),
            'source': self.source,
            'data': self.data,
            'confidence': self.confidence
        }


@dataclass
class MetricBaseline:
    """Baseline metrics for anomaly detection."""
    metric_name: str
    mean: float
    std: float
    min_value: float
    max_value: float
    sample_count: int
    last_updated: datetime = field(default_factory=datetime.now)
    
    def is_anomaly(self, value: float, threshold: float = 2.0) -> bool:
        """Check if a value is anomalous based on standard deviations."""
        if self.std == 0:
            return value != self.mean
        z_score = abs(value - self.mean) / self.std
        return z_score > threshold
    
    def update(self, value: float):
        """Update baseline with new value using online algorithm."""
        self.sample_count += 1
        delta = value - self.mean
        self.mean += delta / self.sample_count
        delta2 = value - self.mean
        # Welford's online algorithm for variance
        if self.sample_count > 1:
            self.std = np.sqrt(
                ((self.sample_count - 2) * self.std ** 2 + delta * delta2) / 
                (self.sample_count - 1)
            )
        self.min_value = min(self.min_value, value)
        self.max_value = max(self.max_value, value)
        self.last_updated = datetime.now()


class StatisticalAnomalyDetector:
    """Detects statistical anomalies in metric streams."""
    
    def __init__(self, threshold: float = 2.0, min_samples: int = 10):
        self.threshold = threshold
        self.min_samples = min_samples
        self._baselines: Dict[str, MetricBaseline] = {}
        self._anomalies: List[Dict[str, Any]] = []
        logger.info("StatisticalAnomalyDetector initialized")
    
    def add_metric(self, metric_name: str, value: float) -> Optional[Dict[str, Any]]:
        """Add a metric value and check for anomaly."""
        if metric_name not in self._baselines:
            self._baselines[metric_name] = MetricBaseline(
                metric_name=metric_name,
                mean=value,
                std=0.0,
                min_value=value,
                max_value=value,
                sample_count=1
            )
            return None
        
        baseline = self._baselines[metric_name]
        
        # Check for anomaly only if we have enough samples
        anomaly = None
        if baseline.sample_count >= self.min_samples:
            if baseline.is_anomaly(value, self.threshold):
                anomaly = {
                    'metric_name': metric_name,
                    'value': value,
                    'mean': baseline.mean,
                    'std': baseline.std,
                    'z_score': abs(value - baseline.mean) / baseline.std if baseline.std > 0 else 0,
                    'timestamp': datetime.now().isoformat()
                }
                self._anomalies.append(anomaly)
        
        # Update baseline
        baseline.update(value)
        
        return anomaly
    
    def get_baseline(self, metric_name: str) -> Optional[MetricBaseline]:
        """Get baseline for a metric."""
        return self._baselines.get(metric_name)
    
    def get_all_baselines(self) -> Dict[str, MetricBaseline]:
        """Get all baselines."""
        return self._baselines.copy()
    
    def get_recent_anomalies(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent anomalies."""
        return self._anomalies[-limit:]
    
    def clear_anomalies(self):
        """Clear anomaly history."""
        self._anomalies.clear()


@dataclass
class EmergentBehavior:
    """Represents a detected emergent behavior."""
    id: str
    emergence_type: EmergenceType
    description: str
    contributing_patterns: List[str]
    confidence: float
    detected_at: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'emergence_type': self.emergence_type.name,
            'description': self.description,
            'contributing_patterns': self.contributing_patterns,
            'confidence': self.confidence,
            'detected_at': self.detected_at.isoformat(),
            'metadata': self.metadata
        }


class EmergenceDetector:
    """
    Detects emergent behaviors from pattern interactions.
    
    Uses statistical analysis and correlation detection to identify
    when multiple patterns combine to create new, unexpected behaviors.
    """
    
    def __init__(
        self,
        min_confidence: float = 0.6,
        correlation_threshold: float = 0.7,
        min_patterns_for_emergence: int = 2
    ):
        self.min_confidence = min_confidence
        self.correlation_threshold = correlation_threshold
        self.min_patterns_for_emergence = min_patterns_for_emergence
        
        self._detected_behaviors: Dict[str, EmergentBehavior] = {}
        self._pattern_interactions: Dict[Tuple[str, str], int] = {}
        self._behavior_history: List[Dict[str, Any]] = []
        
        logger.info("EmergenceDetector initialized")
    
    async def detect_emergence(
        self,
        patterns: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None
    ) -> List[EmergentBehavior]:
        """
        Detect emergent behaviors from a set of patterns.
        
        Args:
            patterns: List of discovered patterns
            context: Optional context information
            
        Returns:
            List of detected emergent behaviors
        """
        if len(patterns) < self.min_patterns_for_emergence:
            logger.debug("Insufficient patterns for emergence detection")
            return []
        
        detected = []
        
        # Detect synergy emergence
        synergy_behaviors = await self._detect_synergy(patterns)
        detected.extend(synergy_behaviors)
        
        # Detect feedback loops
        feedback_behaviors = await self._detect_feedback_loops(patterns)
        detected.extend(feedback_behaviors)
        
        # Detect self-organization
        self_org_behaviors = await self._detect_self_organization(patterns)
        detected.extend(self_org_behaviors)
        
        # Store detected behaviors
        for behavior in detected:
            self._detected_behaviors[behavior.id] = behavior
            self._behavior_history.append({
                'timestamp': datetime.now().isoformat(),
                'behavior_id': behavior.id,
                'type': behavior.emergence_type.name
            })
        
        logger.info(f"Detected {len(detected)} emergent behaviors")
        return detected
    
    async def _detect_synergy(
        self,
        patterns: List[Dict[str, Any]]
    ) -> List[EmergentBehavior]:
        """Detect synergistic emergence from pattern combinations."""
        behaviors = []
        
        # Find patterns that frequently co-occur
        pattern_ids = [p.get('id', str(i)) for i, p in enumerate(patterns)]
        
        for i, p1 in enumerate(patterns):
            for j, p2 in enumerate(patterns[i+1:], i+1):
                # Check for correlation
                correlation = self._calculate_pattern_correlation(p1, p2)
                
                if correlation > self.correlation_threshold:
                    # Record interaction
                    key = (pattern_ids[i], pattern_ids[j])
                    self._pattern_interactions[key] = self._pattern_interactions.get(key, 0) + 1
                    
                    # Create emergent behavior if threshold met
                    if self._pattern_interactions[key] >= 3:
                        behavior = EmergentBehavior(
                            id=f"synergy_{pattern_ids[i]}_{pattern_ids[j]}",
                            emergence_type=EmergenceType.SYNERGY,
                            description=f"Synergistic behavior from patterns {pattern_ids[i]} and {pattern_ids[j]}",
                            contributing_patterns=[pattern_ids[i], pattern_ids[j]],
                            confidence=correlation,
                            detected_at=datetime.now(),
                            metadata={
                                'correlation': correlation,
                                'interaction_count': self._pattern_interactions[key]
                            }
                        )
                        behaviors.append(behavior)
        
        return behaviors
    
    async def _detect_feedback_loops(
        self,
        patterns: List[Dict[str, Any]]
    ) -> List[EmergentBehavior]:
        """Detect feedback loop emergence."""
        behaviors = []
        
        # Look for patterns that reference each other
        for i, pattern in enumerate(patterns):
            pattern_id = pattern.get('id', str(i))
            related = pattern.get('related_patterns', [])
            
            for related_id in related:
                # Check if the related pattern also references this one
                for other in patterns:
                    if other.get('id') == related_id:
                        other_related = other.get('related_patterns', [])
                        if pattern_id in other_related:
                            behavior = EmergentBehavior(
                                id=f"feedback_{pattern_id}_{related_id}",
                                emergence_type=EmergenceType.FEEDBACK_LOOP,
                                description=f"Feedback loop between {pattern_id} and {related_id}",
                                contributing_patterns=[pattern_id, related_id],
                                confidence=0.8,
                                detected_at=datetime.now()
                            )
                            behaviors.append(behavior)
        
        return behaviors
    
    async def _detect_self_organization(
        self,
        patterns: List[Dict[str, Any]]
    ) -> List[EmergentBehavior]:
        """Detect self-organization emergence."""
        behaviors = []
        
        # Check for clustering in pattern space
        if len(patterns) >= 5:
            # Simple clustering detection based on pattern types
            type_counts: Dict[str, int] = {}
            for p in patterns:
                ptype = p.get('pattern_type', 'unknown')
                type_counts[ptype] = type_counts.get(ptype, 0) + 1
            
            # If one type dominates, it might indicate self-organization
            total = len(patterns)
            for ptype, count in type_counts.items():
                ratio = count / total
                if ratio > 0.6:  # More than 60% of same type
                    behavior = EmergentBehavior(
                        id=f"self_org_{ptype}_{datetime.now().timestamp()}",
                        emergence_type=EmergenceType.SELF_ORGANIZATION,
                        description=f"Self-organization around {ptype} patterns",
                        contributing_patterns=[p.get('id', '') for p in patterns if p.get('pattern_type') == ptype],
                        confidence=ratio,
                        detected_at=datetime.now(),
                        metadata={'dominant_type': ptype, 'ratio': ratio}
                    )
                    behaviors.append(behavior)
        
        return behaviors
    
    def _calculate_pattern_correlation(
        self,
        pattern1: Dict[str, Any],
        pattern2: Dict[str, Any]
    ) -> float:
        """Calculate correlation between two patterns."""
        # Simple text-based correlation
        desc1 = pattern1.get('description', '').lower().split()
        desc2 = pattern2.get('description', '').lower().split()
        
        if not desc1 or not desc2:
            return 0.0
        
        set1 = set(desc1)
        set2 = set(desc2)
        
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        
        if union == 0:
            return 0.0
        
        return intersection / union
    
    def get_detected_behaviors(
        self,
        emergence_type: Optional[EmergenceType] = None,
        min_confidence: float = 0.0
    ) -> List[EmergentBehavior]:
        """Get detected emergent behaviors."""
        behaviors = list(self._detected_behaviors.values())
        
        if emergence_type:
            behaviors = [b for b in behaviors if b.emergence_type == emergence_type]
        
        behaviors = [b for b in behaviors if b.confidence >= min_confidence]
        
        return sorted(behaviors, key=lambda x: x.confidence, reverse=True)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get emergence detection statistics."""
        type_counts = {}
        for b in self._detected_behaviors.values():
            type_name = b.emergence_type.name
            type_counts[type_name] = type_counts.get(type_name, 0) + 1
        
        return {
            'total_behaviors': len(self._detected_behaviors),
            'by_type': type_counts,
            'total_interactions': len(self._pattern_interactions),
            'history_length': len(self._behavior_history)
        }
