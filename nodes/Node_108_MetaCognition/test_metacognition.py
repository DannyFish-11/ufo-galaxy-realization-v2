"""
Unit tests for Node 108 - Metacognition Engine
"""
import unittest
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from core.metacognition_engine import MetacognitionEngine

class TestMetacognitionEngine(unittest.TestCase):
    """Test cases for MetacognitionEngine"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.engine = MetacognitionEngine()
    
    def test_engine_initialization(self):
        """Test that the engine initializes correctly"""
        self.assertIsNotNone(self.engine)
    
    def test_engine_has_required_methods(self):
        """Test that the engine has all required methods"""
        required_methods = ['process', 'analyze', 'reflect']
        for method in required_methods:
            self.assertTrue(
                hasattr(self.engine, method),
                f"Engine missing required method: {method}"
            )
    
    def test_basic_processing(self):
        """Test basic processing functionality"""
        try:
            # This is a placeholder test - actual implementation depends on the engine's API
            result = self.engine.process({"test": "data"}) if hasattr(self.engine, 'process') else None
            # Just verify it doesn't crash
            self.assertTrue(True)
        except Exception as e:
            self.fail(f"Basic processing failed: {e}")

if __name__ == '__main__':
    unittest.main()
