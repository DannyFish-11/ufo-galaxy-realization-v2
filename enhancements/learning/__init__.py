#!/usr/bin/env python3
"""
Galaxy v5.0 - Autonomous Learning System

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

Author: Galaxy Team
Version: 5.0.0
License: MIT
"""

__version__ = "5.0.0"
__author__ = "Galaxy Team"

import logging as _logging
_logger = _logging.getLogger(__name__)

# Core components — conditional imports for graceful degradation
try:
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
except ImportError as _e:
    _logger.warning(f"autonomous_learning_engine 不可用: {_e}")
    LearningStage = PatternType = LearningObservation = DiscoveredPattern = None
    LearningExperiment = LearningCycle = PatternRecognizer = KnowledgeAccumulator = None
    AutonomousLearningEngine = None

try:
    from .knowledge_graph import (
        EntityType,
        RelationshipType,
        Entity,
        Relationship,
        KnowledgeGraph
    )
except ImportError as _e:
    _logger.warning(f"knowledge_graph 不可用: {_e}")
    EntityType = RelationshipType = Entity = Relationship = KnowledgeGraph = None

try:
    from .emergence_detector import (
        EmergenceType,
        EmergenceEvent,
        MetricBaseline,
        StatisticalAnomalyDetector,
        EmergenceDetector
    )
except ImportError as _e:
    _logger.warning(f"emergence_detector 不可用: {_e}")
    EmergenceType = EmergenceEvent = MetricBaseline = StatisticalAnomalyDetector = EmergenceDetector = None

try:
    from .search_integrator import (
        SearchSource,
        SearchResult,
        SearchQuery,
        RateLimiter,
        ResultCache,
        SearchIntegrator
    )
except ImportError as _e:
    _logger.warning(f"search_integrator 不可用: {_e}")
    SearchSource = SearchResult = SearchQuery = RateLimiter = ResultCache = SearchIntegrator = None

try:
    from .feedback_loop import (
        FeedbackType,
        FeedbackTarget,
        FeedbackRecord,
        PerformanceMetric,
        MetricsTracker,
        ReinforcementLearner,
        FeedbackLoop
    )
except ImportError as _e:
    _logger.warning(f"feedback_loop 不可用: {_e}")
    FeedbackType = FeedbackTarget = FeedbackRecord = PerformanceMetric = None
    MetricsTracker = ReinforcementLearner = FeedbackLoop = None

# Version info
def get_version() -> str:
    """Get the version of the learning system."""
    return __version__


def get_info() -> dict:
    """Get information about the learning system."""
    return {
        "name": "Galaxy Autonomous Learning System",
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
