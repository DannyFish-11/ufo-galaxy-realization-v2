#!/usr/bin/env python3
"""
UFO Galaxy v5.0 - Autonomous Learning System

This module provides a comprehensive self-learning system with:
- Pattern recognition from multiple data sources
- Knowledge graph construction and management
- Multi-source search integration (Web, arXiv, GitHub)
- Emergence detection algorithms
- Feedback loop implementation

The system demonstrates emergent behavior through continuous learning
using a 5-stage learning loop: observe → analyze → experiment → validate → deploy

Components:
    - autonomous_learning_engine: Main learning engine with ML-based pattern recognition
    - knowledge_graph: NetworkX-based knowledge graph with 13 entity types and 38 relationships
    - learning_node: FastAPI service with WebSocket support for real-time learning
    - emergence_detector: Detects 4 types of emergent behavior
    - search_integrator: Multi-source search with result aggregation
    - feedback_loop: Continuous improvement through feedback collection

Example:
    >>> from learning import AutonomousLearningEngine
    >>> engine = AutonomousLearningEngine()
    >>> await engine.start()
    >>> # Learning happens automatically
    >>> await engine.stop()

Author: UFO Galaxy Team
Version: 5.0.0
License: MIT
"""

__version__ = "5.0.0"
__author__ = "UFO Galaxy Team"

# Core components
from .autonomous_learning_engine import (
    LearningStage,
    PatternType,
    LearningObservation,
    DiscoveredPattern,
    LearningExperiment,
    LearningCycle,
    PatternRecognizer,
    KnowledgeAccumulator,
    AutonomousLearningEngine
)

from .knowledge_graph import (
    EntityType,
    RelationshipType,
    Entity,
    Relationship,
    KnowledgeGraph
)

from .emergence_detector import (
    EmergenceType,
    EmergenceEvent,
    MetricBaseline,
    StatisticalAnomalyDetector,
    EmergenceDetector
)

from .search_integrator import (
    SearchSource,
    SearchResult,
    SearchQuery,
    RateLimiter,
    ResultCache,
    SearchIntegrator
)

from .feedback_loop import (
    FeedbackType,
    FeedbackTarget,
    FeedbackRecord,
    PerformanceMetric,
    MetricsTracker,
    ReinforcementLearner,
    FeedbackLoop
)

# Version info
def get_version() -> str:
    """Get the version of the learning system."""
    return __version__


def get_info() -> dict:
    """Get information about the learning system."""
    return {
        "name": "UFO Galaxy Autonomous Learning System",
        "version": __version__,
        "author": __author__,
        "components": [
            "autonomous_learning_engine",
            "knowledge_graph",
            "learning_node",
            "emergence_detector",
            "search_integrator",
            "feedback_loop"
        ],
        "features": [
            "5-stage learning loop",
            "13 entity types in knowledge graph",
            "38 relationship types",
            "4 emergence detection types",
            "Multi-source search integration",
            "Real-time WebSocket updates",
            "Reinforcement learning feedback"
        ]
    }


# Export all public classes
__all__ = [
    # Version
    "get_version",
    "get_info",
    
    # Autonomous Learning Engine
    "LearningStage",
    "PatternType",
    "LearningObservation",
    "DiscoveredPattern",
    "LearningExperiment",
    "LearningCycle",
    "PatternRecognizer",
    "KnowledgeAccumulator",
    "AutonomousLearningEngine",
    
    # Knowledge Graph
    "EntityType",
    "RelationshipType",
    "Entity",
    "Relationship",
    "KnowledgeGraph",
    
    # Emergence Detector
    "EmergenceType",
    "EmergenceEvent",
    "MetricBaseline",
    "StatisticalAnomalyDetector",
    "EmergenceDetector",
    
    # Search Integrator
    "SearchSource",
    "SearchResult",
    "SearchQuery",
    "RateLimiter",
    "ResultCache",
    "SearchIntegrator",
    
    # Feedback Loop
    "FeedbackType",
    "FeedbackTarget",
    "FeedbackRecord",
    "PerformanceMetric",
    "MetricsTracker",
    "ReinforcementLearner",
    "FeedbackLoop"
]
