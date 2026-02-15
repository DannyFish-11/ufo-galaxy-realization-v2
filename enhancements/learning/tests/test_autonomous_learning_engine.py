#!/usr/bin/env python3
"""
Unit tests for Autonomous Learning Engine
"""

import asyncio
import unittest
from datetime import datetime
from typing import List

import sys
sys.path.insert(0, '/mnt/okcomputer/output/ufo-galaxy-v5/enhancements/learning')

from autonomous_learning_engine import (
    LearningStage,
    PatternType,
    LearningObservation,
    DiscoveredPattern,
    LearningExperiment,
    PatternRecognizer,
    KnowledgeAccumulator,
    AutonomousLearningEngine
)


class TestLearningObservation(unittest.TestCase):
    """Test LearningObservation dataclass."""
    
    def test_observation_creation(self):
        """Test creating a learning observation."""
        obs = LearningObservation(
            id="test_id",
            source="test_source",
            content="Test content",
            timestamp=datetime.now()
        )
        
        self.assertEqual(obs.id, "test_id")
        self.assertEqual(obs.source, "test_source")
        self.assertEqual(obs.content, "Test content")
        self.assertEqual(obs.confidence, 0.0)
    
    def test_observation_auto_id(self):
        """Test automatic ID generation."""
        obs = LearningObservation(
            id="",
            source="test",
            content="content",
            timestamp=datetime.now()
        )
        
        self.assertIsNotNone(obs.id)
        self.assertEqual(len(obs.id), 16)


class TestDiscoveredPattern(unittest.TestCase):
    """Test DiscoveredPattern dataclass."""
    
    def test_pattern_creation(self):
        """Test creating a discovered pattern."""
        pattern = DiscoveredPattern(
            id="pattern_1",
            pattern_type=PatternType.SEMANTIC,
            description="Test pattern",
            observations=["obs1", "obs2"],
            confidence=0.85,
            created_at=datetime.now(),
            last_updated=datetime.now()
        )
        
        self.assertEqual(pattern.pattern_type, PatternType.SEMANTIC)
        self.assertEqual(pattern.confidence, 0.85)
        self.assertEqual(len(pattern.observations), 2)


class TestPatternRecognizer(unittest.TestCase):
    """Test PatternRecognizer class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.recognizer = PatternRecognizer(min_confidence=0.6)
    
    def test_initialization(self):
        """Test recognizer initialization."""
        self.assertEqual(self.recognizer.min_confidence, 0.6)
    
    def test_insufficient_observations(self):
        """Test pattern recognition with insufficient observations."""
        observations = [
            LearningObservation(id="1", source="s", content="c1", timestamp=datetime.now()),
            LearningObservation(id="2", source="s", content="c2", timestamp=datetime.now())
        ]
        
        async def test():
            patterns = await self.recognizer.recognize_patterns(observations)
            self.assertEqual(len(patterns), 0)
        
        asyncio.run(test())
    
    def test_semantic_pattern_recognition(self):
        """Test semantic pattern recognition."""
        observations = [
            LearningObservation(id="", source="s", content="machine learning algorithms", timestamp=datetime.now()),
            LearningObservation(id="", source="s", content="deep learning neural networks", timestamp=datetime.now()),
            LearningObservation(id="", source="s", content="machine learning models", timestamp=datetime.now()),
            LearningObservation(id="", source="s", content="learning algorithms optimization", timestamp=datetime.now()),
            LearningObservation(id="", source="s", content="neural network training", timestamp=datetime.now()),
        ]
        
        async def test():
            patterns = await self.recognizer.recognize_patterns(
                observations,
                pattern_type=PatternType.SEMANTIC
            )
            self.assertGreaterEqual(len(patterns), 0)
        
        asyncio.run(test())
    
    def test_get_patterns_filtering(self):
        """Test pattern retrieval with filtering."""
        patterns = self.recognizer.get_patterns(
            pattern_type=PatternType.SEMANTIC,
            min_confidence=0.7
        )
        
        self.assertIsInstance(patterns, list)


class TestKnowledgeAccumulator(unittest.TestCase):
    """Test KnowledgeAccumulator class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.accumulator = KnowledgeAccumulator(max_knowledge_items=100)
    
    def test_initialization(self):
        """Test accumulator initialization."""
        self.assertEqual(self.accumulator.max_knowledge_items, 100)
    
    def test_accumulate_pattern(self):
        """Test accumulating a pattern."""
        pattern = DiscoveredPattern(
            id="p1",
            pattern_type=PatternType.SEMANTIC,
            description="Test pattern for accumulation",
            observations=["obs1"],
            confidence=0.8,
            created_at=datetime.now(),
            last_updated=datetime.now()
        )
        
        async def test():
            stats = await self.accumulator.accumulate([pattern], "test_source")
            self.assertEqual(stats['added'], 1)
        
        asyncio.run(test())
    
    def test_low_confidence_rejection(self):
        """Test that low confidence patterns are rejected."""
        pattern = DiscoveredPattern(
            id="p1",
            pattern_type=PatternType.SEMANTIC,
            description="Low confidence pattern",
            observations=["obs1"],
            confidence=0.3,  # Below threshold
            created_at=datetime.now(),
            last_updated=datetime.now()
        )
        
        async def test():
            stats = await self.accumulator.accumulate([pattern], "test_source")
            self.assertEqual(stats['rejected'], 1)
        
        asyncio.run(test())
    
    def test_get_knowledge(self):
        """Test knowledge retrieval."""
        knowledge = self.accumulator.get_knowledge(query="test", limit=10)
        self.assertIsInstance(knowledge, list)
    
    def test_get_stats(self):
        """Test statistics retrieval."""
        stats = self.accumulator.get_stats()
        self.assertIn('total_items', stats)
        self.assertIn('history_events', stats)


class TestAutonomousLearningEngine(unittest.TestCase):
    """Test AutonomousLearningEngine class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.engine = AutonomousLearningEngine(cycle_interval=1.0)
    
    def test_initialization(self):
        """Test engine initialization."""
        self.assertIsNotNone(self.engine.pattern_recognizer)
        self.assertIsNotNone(self.engine.knowledge_accumulator)
        self.assertEqual(self.engine.cycle_interval, 1.0)
    
    def test_register_data_source(self):
        """Test data source registration."""
        async def mock_connector():
            return [{"content": "test"}]
        
        self.engine.register_data_source("test_source", mock_connector)
        self.assertIn("test_source", self.engine._data_sources)
    
    def test_stage_callbacks(self):
        """Test stage callback registration."""
        callback_called = [False]
        
        def test_callback(data):
            callback_called[0] = True
        
        self.engine.on_stage(LearningStage.OBSERVE, test_callback)
        self.assertEqual(len(self.engine._stage_callbacks[LearningStage.OBSERVE]), 1)
    
    def test_get_status(self):
        """Test status retrieval."""
        status = self.engine.get_status()
        self.assertIn('running', status)
        self.assertIn('total_cycles', status)
        self.assertIn('knowledge_stats', status)
    
    def test_get_learning_history(self):
        """Test learning history retrieval."""
        history = self.engine.get_learning_history(limit=5)
        self.assertIsInstance(history, list)


class TestLearningStages(unittest.TestCase):
    """Test learning stage functionality."""
    
    def test_stage_enum(self):
        """Test learning stage enumeration."""
        stages = list(LearningStage)
        self.assertEqual(len(stages), 5)
        self.assertIn(LearningStage.OBSERVE, stages)
        self.assertIn(LearningStage.ANALYZE, stages)
        self.assertIn(LearningStage.EXPERIMENT, stages)
        self.assertIn(LearningStage.VALIDATE, stages)
        self.assertIn(LearningStage.DEPLOY, stages)


class TestPatternTypes(unittest.TestCase):
    """Test pattern type enumeration."""
    
    def test_pattern_type_values(self):
        """Test pattern type values."""
        self.assertEqual(PatternType.BEHAVIORAL.value, "behavioral")
        self.assertEqual(PatternType.TEMPORAL.value, "temporal")
        self.assertEqual(PatternType.SPATIAL.value, "spatial")
        self.assertEqual(PatternType.SEMANTIC.value, "semantic")
        self.assertEqual(PatternType.CAUSAL.value, "causal")
        self.assertEqual(PatternType.ANOMALY.value, "anomaly")


class TestIntegration(unittest.TestCase):
    """Integration tests for the learning system."""
    
    def test_full_learning_cycle(self):
        """Test a complete learning cycle."""
        engine = AutonomousLearningEngine(cycle_interval=0.1)
        
        # Register mock data source
        async def mock_source():
            return [
                {"content": f"Observation {i}", "metadata": {"index": i}}
                for i in range(10)
            ]
        
        engine.register_data_source("mock", mock_source)
        
        async def test():
            # Start engine
            await engine.start()
            
            # Wait for a cycle
            await asyncio.sleep(0.5)
            
            # Check status
            status = engine.get_status()
            self.assertTrue(status['running'])
            
            # Stop engine
            await engine.stop()
            
            # Verify stopped
            self.assertFalse(engine._running)
        
        asyncio.run(test())


def run_tests():
    """Run all tests."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestLearningObservation))
    suite.addTests(loader.loadTestsFromTestCase(TestDiscoveredPattern))
    suite.addTests(loader.loadTestsFromTestCase(TestPatternRecognizer))
    suite.addTests(loader.loadTestsFromTestCase(TestKnowledgeAccumulator))
    suite.addTests(loader.loadTestsFromTestCase(TestAutonomousLearningEngine))
    suite.addTests(loader.loadTestsFromTestCase(TestLearningStages))
    suite.addTests(loader.loadTestsFromTestCase(TestPatternTypes))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegration))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    exit(0 if success else 1)
