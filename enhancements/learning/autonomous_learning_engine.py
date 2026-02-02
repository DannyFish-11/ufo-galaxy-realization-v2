#!/usr/bin/env python3
"""
Autonomous Learning Engine for UFO Galaxy v5.0

This module implements a self-learning system with a 5-stage learning loop:
observe → analyze → experiment → validate → deploy

The system demonstrates emergent behavior through continuous pattern recognition
from multiple data sources and knowledge accumulation.

Author: UFO Galaxy Team
Version: 5.0.0
"""

import asyncio
import json
import logging
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable, Set, Tuple, AsyncIterator
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from collections import deque
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import DBSCAN
from sklearn.decomposition import PCA
import aiohttp

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class LearningStage(Enum):
    """Five stages of the learning loop."""
    OBSERVE = auto()
    ANALYZE = auto()
    EXPERIMENT = auto()
    VALIDATE = auto()
    DEPLOY = auto()


class PatternType(Enum):
    """Types of patterns that can be recognized."""
    BEHAVIORAL = "behavioral"
    TEMPORAL = "temporal"
    SPATIAL = "spatial"
    SEMANTIC = "semantic"
    CAUSAL = "causal"
    ANOMALY = "anomaly"


@dataclass
class LearningObservation:
    """Represents a single observation in the learning system."""
    id: str
    source: str
    content: str
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)
    embeddings: Optional[np.ndarray] = None
    confidence: float = 0.0
    
    def __post_init__(self):
        if not self.id:
            self.id = hashlib.md5(
                f"{self.source}:{self.content}:{self.timestamp}".encode()
            ).hexdigest()[:16]


@dataclass
class DiscoveredPattern:
    """Represents a discovered pattern."""
    id: str
    pattern_type: PatternType
    description: str
    observations: List[str]
    confidence: float
    created_at: datetime
    last_updated: datetime
    frequency: int = 1
    examples: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LearningExperiment:
    """Represents an experiment in the learning system."""
    id: str
    hypothesis: str
    pattern_id: str
    status: str  # pending, running, completed, failed
    results: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None


@dataclass
class LearningCycle:
    """Represents a complete learning cycle."""
    id: str
    stage: LearningStage
    observations: List[LearningObservation]
    patterns: List[DiscoveredPattern]
    experiments: List[LearningExperiment]
    start_time: datetime
    end_time: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class PatternRecognizer:
    """
    Pattern recognition engine using ML techniques.
    
    Supports multiple pattern types including behavioral, temporal,
    semantic, and anomaly detection.
    """
    
    def __init__(self, min_confidence: float = 0.6):
        self.min_confidence = min_confidence
        self.vectorizer = TfidfVectorizer(max_features=1000, stop_words='english')
        self.pca = PCA(n_components=50)
        self.clusterer = DBSCAN(eps=0.5, min_samples=3)
        self._patterns: Dict[str, DiscoveredPattern] = {}
        self._observation_buffer: deque = deque(maxlen=10000)
        logger.info("PatternRecognizer initialized")
    
    async def recognize_patterns(
        self,
        observations: List[LearningObservation],
        pattern_type: Optional[PatternType] = None
    ) -> List[DiscoveredPattern]:
        """
        Recognize patterns from observations.
        
        Args:
            observations: List of observations to analyze
            pattern_type: Optional specific pattern type to look for
            
        Returns:
            List of discovered patterns
        """
        if len(observations) < 3:
            logger.warning("Insufficient observations for pattern recognition")
            return []
        
        # Add to buffer
        self._observation_buffer.extend(observations)
        
        patterns = []
        
        # Semantic pattern recognition
        if pattern_type is None or pattern_type == PatternType.SEMANTIC:
            semantic_patterns = await self._recognize_semantic_patterns(observations)
            patterns.extend(semantic_patterns)
        
        # Temporal pattern recognition
        if pattern_type is None or pattern_type == PatternType.TEMPORAL:
            temporal_patterns = await self._recognize_temporal_patterns(observations)
            patterns.extend(temporal_patterns)
        
        # Anomaly detection
        if pattern_type is None or pattern_type == PatternType.ANOMALY:
            anomaly_patterns = await self._detect_anomalies(observations)
            patterns.extend(anomaly_patterns)
        
        # Store patterns
        for pattern in patterns:
            self._patterns[pattern.id] = pattern
        
        logger.info(f"Recognized {len(patterns)} patterns from {len(observations)} observations")
        return patterns
    
    async def _recognize_semantic_patterns(
        self,
        observations: List[LearningObservation]
    ) -> List[DiscoveredPattern]:
        """Recognize semantic patterns using clustering."""
        if len(observations) < 5:
            return []
        
        try:
            # Extract text content
            texts = [obs.content for obs in observations]
            
            # Vectorize
            vectors = self.vectorizer.fit_transform(texts).toarray()
            
            # Reduce dimensions
            if vectors.shape[1] > 50:
                vectors = self.pca.fit_transform(vectors)
            
            # Cluster
            labels = self.clusterer.fit_predict(vectors)
            
            patterns = []
            unique_labels = set(labels) - {-1}  # Exclude noise
            
            for label in unique_labels:
                cluster_indices = [i for i, l in enumerate(labels) if l == label]
                cluster_obs = [observations[i] for i in cluster_indices]
                
                if len(cluster_obs) >= 3:
                    pattern = DiscoveredPattern(
                        id=f"semantic_{label}_{datetime.now().timestamp()}",
                        pattern_type=PatternType.SEMANTIC,
                        description=f"Semantic cluster {label} with {len(cluster_obs)} observations",
                        observations=[obs.id for obs in cluster_obs],
                        confidence=min(0.95, 0.6 + len(cluster_obs) * 0.05),
                        created_at=datetime.now(),
                        last_updated=datetime.now(),
                        frequency=len(cluster_obs),
                        examples=[obs.content[:200] for obs in cluster_obs[:3]]
                    )
                    patterns.append(pattern)
            
            return patterns
            
        except Exception as e:
            logger.error(f"Error in semantic pattern recognition: {e}")
            return []
    
    async def _recognize_temporal_patterns(
        self,
        observations: List[LearningObservation]
    ) -> List[DiscoveredPattern]:
        """Recognize temporal patterns from timestamps."""
        if len(observations) < 5:
            return []
        
        try:
            # Sort by timestamp
            sorted_obs = sorted(observations, key=lambda x: x.timestamp)
            timestamps = [obs.timestamp for obs in sorted_obs]
            
            # Calculate time differences in seconds
            time_diffs = []
            for i in range(1, len(timestamps)):
                diff = (timestamps[i] - timestamps[i-1]).total_seconds()
                time_diffs.append(diff)
            
            if not time_diffs:
                return []
            
            # Look for periodic patterns
            patterns = []
            mean_diff = np.mean(time_diffs)
            std_diff = np.std(time_diffs)
            
            # If low variance, might be periodic
            if std_diff / mean_diff < 0.3 and mean_diff > 0:
                pattern = DiscoveredPattern(
                    id=f"temporal_periodic_{datetime.now().timestamp()}",
                    pattern_type=PatternType.TEMPORAL,
                    description=f"Periodic pattern with interval ~{mean_diff:.0f}s",
                    observations=[obs.id for obs in observations],
                    confidence=min(0.9, 0.7 + 1 / (1 + std_diff / mean_diff)),
                    created_at=datetime.now(),
                    last_updated=datetime.now(),
                    frequency=len(observations),
                    metadata={
                        'mean_interval': mean_diff,
                        'std_interval': std_diff,
                        'periodicity_score': 1 / (1 + std_diff / mean_diff)
                    }
                )
                patterns.append(pattern)
            
            return patterns
            
        except Exception as e:
            logger.error(f"Error in temporal pattern recognition: {e}")
            return []
    
    async def _detect_anomalies(
        self,
        observations: List[LearningObservation]
    ) -> List[DiscoveredPattern]:
        """Detect anomalous observations."""
        if len(observations) < 10:
            return []
        
        try:
            # Simple statistical anomaly detection
            texts = [obs.content for obs in observations]
            vectors = self.vectorizer.fit_transform(texts).toarray()
            
            # Calculate distances to centroid
            centroid = np.mean(vectors, axis=0)
            distances = np.linalg.norm(vectors - centroid, axis=1)
            
            # Find outliers (beyond 2 std)
            threshold = np.mean(distances) + 2 * np.std(distances)
            outlier_indices = [i for i, d in enumerate(distances) if d > threshold]
            
            patterns = []
            if outlier_indices:
                outlier_obs = [observations[i] for i in outlier_indices]
                pattern = DiscoveredPattern(
                    id=f"anomaly_{datetime.now().timestamp()}",
                    pattern_type=PatternType.ANOMALY,
                    description=f"Detected {len(outlier_indices)} anomalous observations",
                    observations=[obs.id for obs in outlier_obs],
                    confidence=min(0.95, 0.6 + len(outlier_indices) * 0.05),
                    created_at=datetime.now(),
                    last_updated=datetime.now(),
                    frequency=len(outlier_obs),
                    examples=[obs.content[:200] for obs in outlier_obs[:3]],
                    metadata={
                        'outlier_count': len(outlier_indices),
                        'threshold': threshold,
                        'mean_distance': np.mean(distances)
                    }
                )
                patterns.append(pattern)
            
            return patterns
            
        except Exception as e:
            logger.error(f"Error in anomaly detection: {e}")
            return []
    
    def get_patterns(
        self,
        pattern_type: Optional[PatternType] = None,
        min_confidence: Optional[float] = None
    ) -> List[DiscoveredPattern]:
        """Get stored patterns with optional filtering."""
        patterns = list(self._patterns.values())
        
        if pattern_type:
            patterns = [p for p in patterns if p.pattern_type == pattern_type]
        
        if min_confidence:
            patterns = [p for p in patterns if p.confidence >= min_confidence]
        
        return sorted(patterns, key=lambda x: x.confidence, reverse=True)


class KnowledgeAccumulator:
    """
    Accumulates and refines knowledge over time.
    
    Implements knowledge consolidation, deduplication, and
    confidence scoring.
    """
    
    def __init__(self, max_knowledge_items: int = 10000):
        self.max_knowledge_items = max_knowledge_items
        self._knowledge: Dict[str, Dict[str, Any]] = {}
        self._knowledge_history: deque = deque(maxlen=1000)
        self._confidence_threshold = 0.5
        logger.info("KnowledgeAccumulator initialized")
    
    async def accumulate(
        self,
        patterns: List[DiscoveredPattern],
        source: str
    ) -> Dict[str, Any]:
        """
        Accumulate knowledge from discovered patterns.
        
        Args:
            patterns: List of patterns to accumulate
            source: Source identifier
            
        Returns:
            Accumulation statistics
        """
        stats = {
            'added': 0,
            'updated': 0,
            'merged': 0,
            'rejected': 0
        }
        
        for pattern in patterns:
            if pattern.confidence < self._confidence_threshold:
                stats['rejected'] += 1
                continue
            
            knowledge_key = self._generate_knowledge_key(pattern)
            
            if knowledge_key in self._knowledge:
                # Update existing knowledge
                existing = self._knowledge[knowledge_key]
                existing['confidence'] = max(existing['confidence'], pattern.confidence)
                existing['frequency'] += pattern.frequency
                existing['sources'].add(source)
                existing['last_updated'] = datetime.now().isoformat()
                existing['pattern_ids'].add(pattern.id)
                stats['updated'] += 1
            else:
                # Check for similar knowledge to merge
                merged = await self._try_merge(pattern, source)
                if merged:
                    stats['merged'] += 1
                else:
                    # Add new knowledge
                    self._knowledge[knowledge_key] = {
                        'key': knowledge_key,
                        'pattern_type': pattern.pattern_type.value,
                        'description': pattern.description,
                        'confidence': pattern.confidence,
                        'frequency': pattern.frequency,
                        'sources': {source},
                        'created_at': datetime.now().isoformat(),
                        'last_updated': datetime.now().isoformat(),
                        'pattern_ids': {pattern.id},
                        'examples': pattern.examples,
                        'metadata': pattern.metadata
                    }
                    stats['added'] += 1
        
        # Manage capacity
        await self._consolidate_if_needed()
        
        logger.info(f"Knowledge accumulation: {stats}")
        return stats
    
    def _generate_knowledge_key(self, pattern: DiscoveredPattern) -> str:
        """Generate a unique key for knowledge item."""
        content = f"{pattern.pattern_type.value}:{pattern.description}"
        return hashlib.md5(content.encode()).hexdigest()[:16]
    
    async def _try_merge(
        self,
        pattern: DiscoveredPattern,
        source: str
    ) -> bool:
        """Try to merge pattern with existing similar knowledge."""
        for key, knowledge in self._knowledge.items():
            similarity = self._calculate_similarity(pattern, knowledge)
            if similarity > 0.8:
                # Merge
                knowledge['confidence'] = max(
                    knowledge['confidence'],
                    pattern.confidence
                )
                knowledge['frequency'] += pattern.frequency
                knowledge['sources'].add(source)
                knowledge['pattern_ids'].add(pattern.id)
                knowledge['examples'].extend(pattern.examples)
                knowledge['examples'] = knowledge['examples'][:5]  # Keep top 5
                return True
        return False
    
    def _calculate_similarity(
        self,
        pattern: DiscoveredPattern,
        knowledge: Dict[str, Any]
    ) -> float:
        """Calculate similarity between pattern and knowledge."""
        # Simple text similarity
        pattern_words = set(pattern.description.lower().split())
        knowledge_words = set(knowledge['description'].lower().split())
        
        if not pattern_words or not knowledge_words:
            return 0.0
        
        intersection = pattern_words & knowledge_words
        union = pattern_words | knowledge_words
        
        return len(intersection) / len(union)
    
    async def _consolidate_if_needed(self):
        """Consolidate knowledge if capacity exceeded."""
        if len(self._knowledge) > self.max_knowledge_items:
            # Sort by confidence * frequency
            sorted_items = sorted(
                self._knowledge.items(),
                key=lambda x: x[1]['confidence'] * x[1]['frequency'],
                reverse=True
            )
            
            # Keep top items
            self._knowledge = dict(sorted_items[:self.max_knowledge_items])
            
            # Record history
            self._knowledge_history.append({
                'timestamp': datetime.now().isoformat(),
                'action': 'consolidation',
                'items_removed': len(sorted_items) - self.max_knowledge_items
            })
            
            logger.info(f"Knowledge consolidated, removed {len(sorted_items) - self.max_knowledge_items} items")
    
    def get_knowledge(
        self,
        query: Optional[str] = None,
        min_confidence: float = 0.0,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Query accumulated knowledge."""
        items = list(self._knowledge.values())
        
        if query:
            query_lower = query.lower()
            items = [
                item for item in items
                if query_lower in item['description'].lower() or
                any(query_lower in ex.lower() for ex in item.get('examples', []))
            ]
        
        items = [item for item in items if item['confidence'] >= min_confidence]
        
        # Sort by relevance (confidence * frequency)
        items.sort(key=lambda x: x['confidence'] * x['frequency'], reverse=True)
        
        return items[:limit]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get knowledge accumulation statistics."""
        return {
            'total_items': len(self._knowledge),
            'history_events': len(self._knowledge_history),
            'avg_confidence': np.mean([k['confidence'] for k in self._knowledge.values()]) if self._knowledge else 0,
            'sources': len(set(
                source for k in self._knowledge.values() for source in k['sources']
            ))
        }


class AutonomousLearningEngine:
    """
    Main autonomous learning engine implementing the 5-stage learning loop.
    
    Stages:
    1. OBSERVE: Collect data from multiple sources
    2. ANALYZE: Recognize patterns using ML
    3. EXPERIMENT: Test hypotheses
    4. VALIDATE: Verify results
    5. DEPLOY: Apply learned knowledge
    
    The engine demonstrates emergent behavior through continuous
    feedback loops and self-improvement mechanisms.
    """
    
    def __init__(
        self,
        pattern_recognizer: Optional[PatternRecognizer] = None,
        knowledge_accumulator: Optional[KnowledgeAccumulator] = None,
        cycle_interval: float = 60.0
    ):
        self.pattern_recognizer = pattern_recognizer or PatternRecognizer()
        self.knowledge_accumulator = knowledge_accumulator or KnowledgeAccumulator()
        self.cycle_interval = cycle_interval
        
        self._current_stage = LearningStage.OBSERVE
        self._cycles: List[LearningCycle] = []
        self._observations: List[LearningObservation] = []
        self._experiments: List[LearningExperiment] = []
        self._running = False
        self._task: Optional[asyncio.Task] = None
        
        # Callbacks for each stage
        self._stage_callbacks: Dict[LearningStage, List[Callable]] = {
            stage: [] for stage in LearningStage
        }
        
        # Data source connectors
        self._data_sources: Dict[str, Callable] = {}
        
        logger.info("AutonomousLearningEngine initialized")
    
    def register_data_source(self, name: str, connector: Callable):
        """Register a data source connector."""
        self._data_sources[name] = connector
        logger.info(f"Registered data source: {name}")
    
    def on_stage(self, stage: LearningStage, callback: Callable):
        """Register a callback for a specific learning stage."""
        self._stage_callbacks[stage].append(callback)
    
    async def start(self):
        """Start the autonomous learning loop."""
        if self._running:
            logger.warning("Learning engine already running")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._learning_loop())
        logger.info("Autonomous learning engine started")
    
    async def stop(self):
        """Stop the autonomous learning loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Autonomous learning engine stopped")
    
    async def _learning_loop(self):
        """Main learning loop implementing the 5 stages."""
        while self._running:
            try:
                cycle_id = f"cycle_{datetime.now().timestamp()}"
                cycle = LearningCycle(
                    id=cycle_id,
                    stage=self._current_stage,
                    observations=[],
                    patterns=[],
                    experiments=[],
                    start_time=datetime.now()
                )
                
                # Stage 1: OBSERVE
                logger.info(f"[{cycle_id}] Starting OBSERVE stage")
                observations = await self._observe_stage()
                cycle.observations = observations
                self._observations.extend(observations)
                await self._trigger_callbacks(LearningStage.OBSERVE, observations)
                
                # Stage 2: ANALYZE
                logger.info(f"[{cycle_id}] Starting ANALYZE stage")
                self._current_stage = LearningStage.ANALYZE
                patterns = await self._analyze_stage(observations)
                cycle.patterns = patterns
                await self._trigger_callbacks(LearningStage.ANALYZE, patterns)
                
                # Stage 3: EXPERIMENT
                logger.info(f"[{cycle_id}] Starting EXPERIMENT stage")
                self._current_stage = LearningStage.EXPERIMENT
                experiments = await self._experiment_stage(patterns)
                cycle.experiments = experiments
                self._experiments.extend(experiments)
                await self._trigger_callbacks(LearningStage.EXPERIMENT, experiments)
                
                # Stage 4: VALIDATE
                logger.info(f"[{cycle_id}] Starting VALIDATE stage")
                self._current_stage = LearningStage.VALIDATE
                validation_results = await self._validate_stage(experiments)
                await self._trigger_callbacks(LearningStage.VALIDATE, validation_results)
                
                # Stage 5: DEPLOY
                logger.info(f"[{cycle_id}] Starting DEPLOY stage")
                self._current_stage = LearningStage.DEPLOY
                deployment_results = await self._deploy_stage(validation_results)
                await self._trigger_callbacks(LearningStage.DEPLOY, deployment_results)
                
                # Complete cycle
                cycle.end_time = datetime.now()
                self._cycles.append(cycle)
                
                # Reset to observe for next cycle
                self._current_stage = LearningStage.OBSERVE
                
                logger.info(f"[{cycle_id}] Learning cycle completed")
                
                # Wait for next cycle
                await asyncio.sleep(self.cycle_interval)
                
            except Exception as e:
                logger.error(f"Error in learning loop: {e}")
                await asyncio.sleep(self.cycle_interval)
    
    async def _observe_stage(self) -> List[LearningObservation]:
        """Stage 1: Collect observations from data sources."""
        observations = []
        
        for source_name, connector in self._data_sources.items():
            try:
                data = await connector()
                if isinstance(data, list):
                    for item in data:
                        obs = LearningObservation(
                            id="",
                            source=source_name,
                            content=str(item.get('content', item)),
                            timestamp=datetime.now(),
                            metadata=item.get('metadata', {})
                        )
                        observations.append(obs)
                else:
                    obs = LearningObservation(
                        id="",
                        source=source_name,
                        content=str(data),
                        timestamp=datetime.now()
                    )
                    observations.append(obs)
                    
            except Exception as e:
                logger.error(f"Error collecting from {source_name}: {e}")
        
        return observations
    
    async def _analyze_stage(
        self,
        observations: List[LearningObservation]
    ) -> List[DiscoveredPattern]:
        """Stage 2: Analyze observations and recognize patterns."""
        patterns = await self.pattern_recognizer.recognize_patterns(observations)
        
        # Accumulate knowledge from patterns
        await self.knowledge_accumulator.accumulate(patterns, "analysis")
        
        return patterns
    
    async def _experiment_stage(
        self,
        patterns: List[DiscoveredPattern]
    ) -> List[LearningExperiment]:
        """Stage 3: Create and run experiments based on patterns."""
        experiments = []
        
        for pattern in patterns:
            if pattern.confidence > 0.7:
                experiment = LearningExperiment(
                    id=f"exp_{pattern.id}_{datetime.now().timestamp()}",
                    hypothesis=f"Pattern {pattern.id} represents a valid insight",
                    pattern_id=pattern.id,
                    status="running"
                )
                
                # Simulate experiment execution
                await asyncio.sleep(0.1)
                
                # Generate results based on pattern confidence
                success = pattern.confidence > 0.8
                experiment.status = "completed" if success else "failed"
                experiment.results = {
                    'success': success,
                    'confidence_validation': pattern.confidence,
                    'test_samples': len(pattern.observations)
                }
                experiment.completed_at = datetime.now()
                
                experiments.append(experiment)
        
        return experiments
    
    async def _validate_stage(
        self,
        experiments: List[LearningExperiment]
    ) -> Dict[str, Any]:
        """Stage 4: Validate experiment results."""
        validation_results = {
            'validated': [],
            'rejected': [],
            'needs_review': []
        }
        
        for exp in experiments:
            if exp.status == "completed" and exp.results.get('success'):
                validation_results['validated'].append(exp)
            elif exp.status == "failed":
                validation_results['rejected'].append(exp)
            else:
                validation_results['needs_review'].append(exp)
        
        return validation_results
    
    async def _deploy_stage(self, validation_results: Dict[str, Any]) -> Dict[str, Any]:
        """Stage 5: Deploy validated knowledge."""
        deployment_results = {
            'deployed': [],
            'deployment_stats': {}
        }
        
        for exp in validation_results['validated']:
            # Find associated pattern
            pattern_id = exp.pattern_id
            
            deployment_results['deployed'].append({
                'experiment_id': exp.id,
                'pattern_id': pattern_id,
                'deployment_time': datetime.now().isoformat()
            })
        
        deployment_results['deployment_stats'] = {
            'total_deployed': len(deployment_results['deployed']),
            'total_validated': len(validation_results['validated']),
            'total_rejected': len(validation_results['rejected'])
        }
        
        return deployment_results
    
    async def _trigger_callbacks(self, stage: LearningStage, data: Any):
        """Trigger callbacks for a learning stage."""
        for callback in self._stage_callbacks[stage]:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(data)
                else:
                    callback(data)
            except Exception as e:
                logger.error(f"Error in stage callback: {e}")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current learning engine status."""
        return {
            'running': self._running,
            'current_stage': self._current_stage.name if self._current_stage else None,
            'total_cycles': len(self._cycles),
            'total_observations': len(self._observations),
            'total_experiments': len(self._experiments),
            'data_sources': list(self._data_sources.keys()),
            'knowledge_stats': self.knowledge_accumulator.get_stats()
        }
    
    def get_learning_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent learning cycles."""
        cycles = self._cycles[-limit:]
        return [
            {
                'id': c.id,
                'stage': c.stage.name,
                'observations_count': len(c.observations),
                'patterns_count': len(c.patterns),
                'experiments_count': len(c.experiments),
                'start_time': c.start_time.isoformat(),
                'end_time': c.end_time.isoformat() if c.end_time else None
            }
            for c in cycles
        ]


# Example usage and testing
async def demo():
    """Demonstrate the autonomous learning engine."""
    engine = AutonomousLearningEngine(cycle_interval=5.0)
    
    # Register mock data sources
    async def mock_web_search():
        return [
            {'content': 'Machine learning breakthrough in 2024', 'metadata': {'source': 'web'}},
            {'content': 'New AI architecture shows promise', 'metadata': {'source': 'web'}},
            {'content': 'Deep learning advances continue', 'metadata': {'source': 'web'}}
        ]
    
    async def mock_arxiv():
        return [
            {'content': 'Attention mechanisms in neural networks', 'metadata': {'source': 'arxiv'}},
            {'content': 'Transformer architecture improvements', 'metadata': {'source': 'arxiv'}}
        ]
    
    engine.register_data_source('web_search', mock_web_search)
    engine.register_data_source('arxiv', mock_arxiv)
    
    # Add stage callbacks
    def on_observe(data):
        print(f"[OBSERVE] Collected {len(data)} observations")
    
    def on_analyze(data):
        print(f"[ANALYZE] Discovered {len(data)} patterns")
    
    engine.on_stage(LearningStage.OBSERVE, on_observe)
    engine.on_stage(LearningStage.ANALYZE, on_analyze)
    
    # Start engine
    await engine.start()
    
    # Run for a few cycles
    await asyncio.sleep(12)
    
    # Get status
    print("\n=== Learning Engine Status ===")
    print(json.dumps(engine.get_status(), indent=2, default=str))
    
    # Get learning history
    print("\n=== Learning History ===")
    print(json.dumps(engine.get_learning_history(), indent=2, default=str))
    
    # Get knowledge
    print("\n=== Accumulated Knowledge ===")
    knowledge = engine.knowledge_accumulator.get_knowledge(limit=5)
    print(json.dumps(knowledge, indent=2, default=str))
    
    # Stop engine
    await engine.stop()


if __name__ == "__main__":
    asyncio.run(demo())
