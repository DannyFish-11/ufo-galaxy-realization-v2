#!/usr/bin/env python3
"""
Unit tests for Learning Node Service
"""

import asyncio
import unittest
from datetime import datetime

import sys
sys.path.insert(0, '/mnt/okcomputer/output/ufo-galaxy-v5/enhancements/learning')

# Import models from learning_node
from learning_node import (
    LearnRequest,
    LearnResponse,
    KnowledgeQueryRequest,
    PatternResponse,
    FeedbackRequest,
    StatusResponse,
    LearningNodeState
)


class TestLearnRequest(unittest.TestCase):
    """Test LearnRequest model."""
    
    def test_request_creation(self):
        """Test creating a learn request."""
        request = LearnRequest(
            content="Test content to learn",
            source="api",
            metadata={'key': 'value'}
        )
        
        self.assertEqual(request.content, "Test content to learn")
        self.assertEqual(request.source, "api")
        self.assertEqual(request.metadata['key'], "value")
    
    def test_default_values(self):
        """Test default values."""
        request = LearnRequest(content="Test")
        
        self.assertEqual(request.source, "api")
        self.assertEqual(request.metadata, {})


class TestLearnResponse(unittest.TestCase):
    """Test LearnResponse model."""
    
    def test_response_creation(self):
        """Test creating a learn response."""
        response = LearnResponse(
            success=True,
            observation_id="obs_123",
            patterns_found=3,
            message="Learning successful"
        )
        
        self.assertTrue(response.success)
        self.assertEqual(response.observation_id, "obs_123")
        self.assertEqual(response.patterns_found, 3)


class TestKnowledgeQueryRequest(unittest.TestCase):
    """Test KnowledgeQueryRequest model."""
    
    def test_request_creation(self):
        """Test creating a knowledge query request."""
        request = KnowledgeQueryRequest(
            query="machine learning",
            entity_types=["concept", "technology"],
            min_confidence=0.7,
            limit=20
        )
        
        self.assertEqual(request.query, "machine learning")
        self.assertEqual(len(request.entity_types), 2)
        self.assertEqual(request.min_confidence, 0.7)
    
    def test_default_values(self):
        """Test default values."""
        request = KnowledgeQueryRequest(query="test")
        
        self.assertIsNone(request.entity_types)
        self.assertEqual(request.min_confidence, 0.0)
        self.assertEqual(request.limit, 10)


class TestPatternResponse(unittest.TestCase):
    """Test PatternResponse model."""
    
    def test_response_creation(self):
        """Test creating a pattern response."""
        response = PatternResponse(
            id="p1",
            pattern_type="semantic",
            description="Test pattern",
            confidence=0.85,
            frequency=5,
            examples=["ex1", "ex2"],
            created_at=datetime.now().isoformat()
        )
        
        self.assertEqual(response.id, "p1")
        self.assertEqual(response.pattern_type, "semantic")
        self.assertEqual(response.confidence, 0.85)


class TestFeedbackRequest(unittest.TestCase):
    """Test FeedbackRequest model."""
    
    def test_request_creation(self):
        """Test creating a feedback request."""
        request = FeedbackRequest(
            target_type="pattern",
            target_id="pattern_1",
            rating=0.8,
            comment="Great pattern!"
        )
        
        self.assertEqual(request.target_type, "pattern")
        self.assertEqual(request.target_id, "pattern_1")
        self.assertEqual(request.rating, 0.8)
    
    def test_rating_validation(self):
        """Test rating validation."""
        # Valid ratings
        FeedbackRequest(target_type="p", target_id="1", rating=1.0)
        FeedbackRequest(target_type="p", target_id="1", rating=-1.0)
        FeedbackRequest(target_type="p", target_id="1", rating=0.0)


class TestStatusResponse(unittest.TestCase):
    """Test StatusResponse model."""
    
    def test_response_creation(self):
        """Test creating a status response."""
        response = StatusResponse(
            status="healthy",
            learning_active=True,
            current_stage="analyze",
            total_observations=100,
            total_patterns=25,
            total_knowledge_items=50,
            uptime_seconds=3600.0
        )
        
        self.assertEqual(response.status, "healthy")
        self.assertTrue(response.learning_active)
        self.assertEqual(response.total_observations, 100)


class TestLearningNodeState(unittest.TestCase):
    """Test LearningNodeState class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.state = LearningNodeState()
    
    def test_initialization(self):
        """Test state initialization."""
        self.assertIsNone(self.state.engine)
        self.assertIsNone(self.state.knowledge_graph)
        self.assertIsNone(self.state.emergence_detector)
        self.assertIsNone(self.state.started_at)
        self.assertEqual(len(self.state.active_connections), 0)
        self.assertFalse(self.state._initialized)
    
    def test_get_uptime_before_start(self):
        """Test uptime before initialization."""
        uptime = self.state.get_uptime()
        self.assertEqual(uptime, 0.0)


class TestIntegration(unittest.TestCase):
    """Integration tests for learning node."""
    
    def test_model_serialization(self):
        """Test model serialization/deserialization."""
        # Create request
        request = LearnRequest(
            content="Test content",
            source="test",
            metadata={'test': True}
        )
        
        # Convert to dict (simulating JSON)
        data = request.model_dump()
        
        # Recreate from dict
        recreated = LearnRequest(**data)
        
        self.assertEqual(recreated.content, request.content)
        self.assertEqual(recreated.source, request.source)


def run_tests():
    """Run all tests."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestLearnRequest))
    suite.addTests(loader.loadTestsFromTestCase(TestLearnResponse))
    suite.addTests(loader.loadTestsFromTestCase(TestKnowledgeQueryRequest))
    suite.addTests(loader.loadTestsFromTestCase(TestPatternResponse))
    suite.addTests(loader.loadTestsFromTestCase(TestFeedbackRequest))
    suite.addTests(loader.loadTestsFromTestCase(TestStatusResponse))
    suite.addTests(loader.loadTestsFromTestCase(TestLearningNodeState))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegration))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    exit(0 if success else 1)
