#!/usr/bin/env python3
"""
Unit tests for Feedback Loop
"""

import unittest
from datetime import datetime, timedelta

import sys
sys.path.insert(0, '/mnt/okcomputer/output/ufo-galaxy-v5/enhancements/learning')

from feedback_loop import (
    FeedbackType,
    FeedbackTarget,
    FeedbackRecord,
    PerformanceMetric,
    MetricsTracker,
    ReinforcementLearner,
    FeedbackLoop
)


class TestFeedbackType(unittest.TestCase):
    """Test FeedbackType enumeration."""
    
    def test_feedback_types(self):
        """Test all feedback types exist."""
        types = list(FeedbackType)
        self.assertEqual(len(types), 4)
        
        self.assertIn(FeedbackType.EXPLICIT, types)
        self.assertIn(FeedbackType.IMPLICIT, types)
        self.assertIn(FeedbackType.AUTOMATED, types)
        self.assertIn(FeedbackType.REINFORCEMENT, types)
    
    def test_type_values(self):
        """Test feedback type values."""
        self.assertEqual(FeedbackType.EXPLICIT.value, "explicit")
        self.assertEqual(FeedbackType.IMPLICIT.value, "implicit")
        self.assertEqual(FeedbackType.REINFORCEMENT.value, "reinforcement")


class TestFeedbackTarget(unittest.TestCase):
    """Test FeedbackTarget enumeration."""
    
    def test_feedback_targets(self):
        """Test all feedback targets exist."""
        targets = list(FeedbackTarget)
        self.assertEqual(len(targets), 6)
        
        self.assertIn(FeedbackTarget.PATTERN, targets)
        self.assertIn(FeedbackTarget.KNOWLEDGE, targets)
        self.assertIn(FeedbackTarget.EXPERIMENT, targets)
        self.assertIn(FeedbackTarget.DECISION, targets)
        self.assertIn(FeedbackTarget.RECOMMENDATION, targets)
        self.assertIn(FeedbackTarget.SYSTEM, targets)


class TestFeedbackRecord(unittest.TestCase):
    """Test FeedbackRecord dataclass."""
    
    def test_record_creation(self):
        """Test creating a feedback record."""
        record = FeedbackRecord(
            id="f1",
            feedback_type=FeedbackType.EXPLICIT,
            target_type=FeedbackTarget.PATTERN,
            target_id="pattern_1",
            rating=0.8,
            timestamp=datetime.now(),
            comment="Great pattern!",
            user_id="user_123"
        )
        
        self.assertEqual(record.feedback_type, FeedbackType.EXPLICIT)
        self.assertEqual(record.target_type, FeedbackTarget.PATTERN)
        self.assertEqual(record.rating, 0.8)
        self.assertFalse(record.processed)
    
    def test_record_auto_id(self):
        """Test automatic ID generation."""
        record = FeedbackRecord(
            id="",
            feedback_type=FeedbackType.IMPLICIT,
            target_type=FeedbackTarget.KNOWLEDGE,
            target_id="k1",
            rating=0.5,
            timestamp=datetime.now()
        )
        
        self.assertIsNotNone(record.id)
        self.assertEqual(len(record.id), 16)
    
    def test_record_to_dict(self):
        """Test record serialization."""
        record = FeedbackRecord(
            id="f1",
            feedback_type=FeedbackType.AUTOMATED,
            target_type=FeedbackTarget.EXPERIMENT,
            target_id="exp1",
            rating=-0.3,
            timestamp=datetime.now(),
            context={'metric': 'accuracy'}
        )
        
        data = record.to_dict()
        self.assertEqual(data['id'], "f1")
        self.assertEqual(data['feedback_type'], "automated")
        self.assertEqual(data['context']['metric'], "accuracy")
    
    def test_record_from_dict(self):
        """Test record deserialization."""
        data = {
            'id': 'f1',
            'feedback_type': 'explicit',
            'target_type': 'pattern',
            'target_id': 'p1',
            'rating': 0.9,
            'timestamp': datetime.now().isoformat(),
            'context': {},
            'comment': None,
            'user_id': None,
            'metadata': {},
            'processed': False
        }
        
        record = FeedbackRecord.from_dict(data)
        self.assertEqual(record.id, 'f1')
        self.assertEqual(record.rating, 0.9)


class TestPerformanceMetric(unittest.TestCase):
    """Test PerformanceMetric dataclass."""
    
    def test_metric_creation(self):
        """Test creating a performance metric."""
        metric = PerformanceMetric(
            name="accuracy",
            value=0.95,
            timestamp=datetime.now(),
            unit="percentage",
            tags={'model': 'v1'}
        )
        
        self.assertEqual(metric.name, "accuracy")
        self.assertEqual(metric.value, 0.95)
        self.assertEqual(metric.unit, "percentage")
    
    def test_metric_to_dict(self):
        """Test metric serialization."""
        metric = PerformanceMetric(
            name="latency",
            value=100.5,
            timestamp=datetime.now(),
            unit="ms"
        )
        
        data = metric.to_dict()
        self.assertEqual(data['name'], "latency")
        self.assertEqual(data['value'], 100.5)


class TestMetricsTracker(unittest.TestCase):
    """Test MetricsTracker class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.tracker = MetricsTracker(max_history=1000)
    
    def test_initialization(self):
        """Test tracker initialization."""
        self.assertEqual(self.tracker.max_history, 1000)
    
    def test_record_metric(self):
        """Test recording a metric."""
        metric = PerformanceMetric(
            name="accuracy",
            value=0.85,
            timestamp=datetime.now()
        )
        
        self.tracker.record(metric)
        
        history = self.tracker.get_history("accuracy")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].value, 0.85)
    
    def test_record_value_convenience(self):
        """Test convenience method for recording values."""
        self.tracker.record_value("latency", 50.0, unit="ms")
        
        history = self.tracker.get_history("latency")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].unit, "ms")
    
    def test_get_statistics(self):
        """Test statistics calculation."""
        # Record multiple values
        for i in range(10):
            self.tracker.record_value("metric1", 10.0 + i)
        
        stats = self.tracker.get_statistics("metric1")
        
        self.assertIn('count', stats)
        self.assertIn('mean', stats)
        self.assertIn('std', stats)
        self.assertIn('min', stats)
        self.assertIn('max', stats)
        self.assertEqual(stats['count'], 10)
    
    def test_detect_trend_increasing(self):
        """Test trend detection - increasing."""
        for i in range(20):
            self.tracker.record_value("trend_metric", 10.0 + i * 0.5)
        
        trend = self.tracker.detect_trend("trend_metric", window_size=10)
        
        self.assertEqual(trend, "increasing")
    
    def test_detect_trend_decreasing(self):
        """Test trend detection - decreasing."""
        for i in range(20):
            self.tracker.record_value("trend_metric", 20.0 - i * 0.5)
        
        trend = self.tracker.detect_trend("trend_metric", window_size=10)
        
        self.assertEqual(trend, "decreasing")
    
    def test_detect_trend_stable(self):
        """Test trend detection - stable."""
        for i in range(20):
            self.tracker.record_value("trend_metric", 10.0 + (i % 3) * 0.01)
        
        trend = self.tracker.detect_trend("trend_metric", window_size=10)
        
        self.assertEqual(trend, "stable")
    
    def test_threshold_violation(self):
        """Test threshold violation detection."""
        violations = []
        
        def on_violation(name, value):
            violations.append((name, value))
        
        self.tracker.on_threshold_violation(on_violation)
        self.tracker.set_threshold("critical_metric", min_value=10.0, max_value=100.0)
        
        # Normal value
        self.tracker.record_value("critical_metric", 50.0)
        self.assertEqual(len(violations), 0)
        
        # Violation - too low
        self.tracker.record_value("critical_metric", 5.0)
        self.assertEqual(len(violations), 1)
        
        # Violation - too high
        self.tracker.record_value("critical_metric", 150.0)
        self.assertEqual(len(violations), 2)
    
    def test_get_all_metrics(self):
        """Test retrieving all metric names."""
        self.tracker.record_value("metric_a", 1.0)
        self.tracker.record_value("metric_b", 2.0)
        self.tracker.record_value("metric_c", 3.0)
        
        all_metrics = self.tracker.get_all_metrics()
        
        self.assertEqual(len(all_metrics), 3)
        self.assertIn("metric_a", all_metrics)
        self.assertIn("metric_b", all_metrics)
        self.assertIn("metric_c", all_metrics)


class TestReinforcementLearner(unittest.TestCase):
    """Test ReinforcementLearner class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.learner = ReinforcementLearner(
            learning_rate=0.1,
            discount_factor=0.9
        )
    
    def test_initialization(self):
        """Test learner initialization."""
        self.assertEqual(self.learner.learning_rate, 0.1)
        self.assertEqual(self.learner.discount_factor, 0.9)
    
    def test_get_action(self):
        """Test action selection."""
        actions = ["action_a", "action_b", "action_c"]
        
        action = self.learner.get_action("state_1", actions)
        
        self.assertIn(action, actions)
    
    def test_update_q_value(self):
        """Test Q-value update."""
        # Initial Q-value should be 0
        q_table = self.learner.get_q_table()
        self.assertEqual(len(q_table), 0)
        
        # Update with positive reward
        self.learner.update("state_1", "action_a", reward=1.0)
        
        q_table = self.learner.get_q_table()
        self.assertGreater(q_table["state_1"]["action_a"], 0)
    
    def test_update_with_next_state(self):
        """Test Q-value update with next state."""
        # Set up initial Q-values
        self.learner.update("state_2", "action_b", reward=0.5)
        
        # Update with next state
        self.learner.update("state_1", "action_a", reward=0.5, next_state="state_2")
        
        # Q-value should incorporate future reward
        q_table = self.learner.get_q_table()
        self.assertGreater(q_table["state_1"]["action_a"], 0)
    
    def test_get_policy(self):
        """Test policy retrieval."""
        # Set up Q-values
        self.learner.update("state_1", "action_a", reward=1.0)
        self.learner.update("state_1", "action_b", reward=0.5)
        
        policy = self.learner.get_policy("state_1")
        
        self.assertIn("action_a", policy)
        self.assertIn("action_b", policy)
        # Higher Q-value should have higher probability
        self.assertGreater(policy["action_a"], policy["action_b"])


class TestFeedbackLoop(unittest.TestCase):
    """Test FeedbackLoop class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.feedback_loop = FeedbackLoop()
    
    def test_initialization(self):
        """Test feedback loop initialization."""
        self.assertIsNotNone(self.feedback_loop.metrics)
        self.assertIsNotNone(self.feedback_loop.rl)
    
    def test_submit_feedback(self):
        """Test feedback submission."""
        import asyncio
        
        async def test():
            record = await self.feedback_loop.submit_feedback(
                target_type="pattern",
                target_id="pattern_1",
                rating=0.8,
                feedback_type="explicit",
                comment="Good pattern"
            )
            
            self.assertEqual(record['target_type'], "pattern")
            self.assertEqual(record['target_id'], "pattern_1")
            self.assertEqual(record['rating'], 0.8)
        
        asyncio.run(test())
    
    def test_get_feedback_for_target(self):
        """Test feedback retrieval for target."""
        import asyncio
        
        async def test():
            # Submit multiple feedback
            for i in range(5):
                await self.feedback_loop.submit_feedback(
                    target_type="pattern",
                    target_id="target_1",
                    rating=0.5 + i * 0.1
                )
            
            feedback = self.feedback_loop.get_feedback_for_target("target_1")
            
            self.assertEqual(len(feedback), 5)
        
        asyncio.run(test())
    
    def test_get_feedback_summary(self):
        """Test feedback summary."""
        import asyncio
        
        async def test():
            # Submit mixed feedback
            await self.feedback_loop.submit_feedback(
                target_type="pattern", target_id="target_2", rating=0.8
            )
            await self.feedback_loop.submit_feedback(
                target_type="pattern", target_id="target_2", rating=0.9
            )
            await self.feedback_loop.submit_feedback(
                target_type="pattern", target_id="target_2", rating=-0.2
            )
            
            summary = self.feedback_loop.get_feedback_summary("target_2")
            
            self.assertEqual(summary['feedback_count'], 3)
            self.assertIn('average_rating', summary)
            self.assertIn('positive_ratio', summary)
        
        asyncio.run(test())
    
    def test_record_performance(self):
        """Test performance recording."""
        self.feedback_loop.record_performance("accuracy", 0.95, unit="percentage")
        
        stats = self.feedback_loop.metrics.get_statistics("accuracy")
        self.assertEqual(stats['count'], 1)
        self.assertEqual(stats['latest'], 0.95)
    
    def test_get_performance_report(self):
        """Test performance report generation."""
        # Record some metrics
        self.feedback_loop.record_performance("metric1", 10.0)
        self.feedback_loop.record_performance("metric2", 20.0)
        
        report = self.feedback_loop.get_performance_report()
        
        self.assertIn('generated_at', report)
        self.assertIn('metrics', report)
        self.assertIn('metric1', report['metrics'])
        self.assertIn('metric2', report['metrics'])
    
    def test_get_rl_state(self):
        """Test RL state retrieval."""
        # Perform some RL updates
        self.feedback_loop.rl.update("s1", "a1", 1.0)
        self.feedback_loop.rl.update("s2", "a2", 0.5)
        
        state = self.feedback_loop.get_rl_state()
        
        self.assertIn('q_table_size', state)
        self.assertIn('history_size', state)
        self.assertEqual(state['q_table_size'], 2)
    
    def test_get_stats(self):
        """Test feedback loop statistics."""
        import asyncio
        
        async def test():
            # Submit some feedback
            await self.feedback_loop.submit_feedback(
                target_type="pattern", target_id="p1", rating=0.8
            )
            await self.feedback_loop.submit_feedback(
                target_type="knowledge", target_id="k1", rating=0.5
            )
            
            stats = self.feedback_loop.get_stats()
            
            self.assertIn('total_feedback', stats)
            self.assertIn('unique_targets', stats)
            self.assertIn('feedback_by_type', stats)
            self.assertEqual(stats['total_feedback'], 2)
        
        asyncio.run(test())
    
    def test_improvement_callback(self):
        """Test improvement opportunity callback."""
        import asyncio
        
        opportunities = []
        
        def on_opportunity(opp):
            opportunities.append(opp)
        
        self.feedback_loop.on_improvement_opportunity(on_opportunity)
        
        async def test():
            # Submit negative feedback multiple times
            for i in range(10):
                await self.feedback_loop.submit_feedback(
                    target_type="pattern",
                    target_id="bad_pattern",
                    rating=-0.5
                )
            
            # Should trigger improvement opportunity
            self.assertGreater(len(opportunities), 0)
        
        asyncio.run(test())


class TestIntegration(unittest.TestCase):
    """Integration tests for feedback loop."""
    
    def test_full_feedback_workflow(self):
        """Test complete feedback workflow."""
        import asyncio
        
        feedback_loop = FeedbackLoop()
        
        async def test():
            # 1. Submit various feedback
            await feedback_loop.submit_feedback(
                target_type="pattern",
                target_id="pattern_1",
                rating=0.9,
                feedback_type="explicit",
                comment="Excellent!"
            )
            
            # 2. Record performance metrics
            for i in range(10):
                feedback_loop.record_performance("accuracy", 0.8 + i * 0.01)
            
            # 3. RL update
            feedback_loop.rl.update("state_1", "action_1", reward=1.0)
            
            # 4. Get reports
            report = feedback_loop.get_performance_report()
            stats = feedback_loop.get_stats()
            
            # Verify
            self.assertEqual(stats['total_feedback'], 1)
            self.assertIn('accuracy', report['metrics'])
        
        asyncio.run(test())


def run_tests():
    """Run all tests."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestFeedbackType))
    suite.addTests(loader.loadTestsFromTestCase(TestFeedbackTarget))
    suite.addTests(loader.loadTestsFromTestCase(TestFeedbackRecord))
    suite.addTests(loader.loadTestsFromTestCase(TestPerformanceMetric))
    suite.addTests(loader.loadTestsFromTestCase(TestMetricsTracker))
    suite.addTests(loader.loadTestsFromTestCase(TestReinforcementLearner))
    suite.addTests(loader.loadTestsFromTestCase(TestFeedbackLoop))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegration))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    exit(0 if success else 1)
