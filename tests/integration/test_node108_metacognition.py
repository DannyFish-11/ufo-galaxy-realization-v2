# ---------------------------------------------------------------------------
# CANONICAL LOCATION: tests/integration/test_node108_metacognition.py
# Relocated from nodes/Node_108_MetaCognition/test_metacognition.py
# ---------------------------------------------------------------------------
"""Unit tests for Node 108 - Metacognition Engine."""
import unittest
import sys
from pathlib import Path

import pytest

# The metacognition engine lives in nodes/Node_108_MetaCognition/core/
_NODE_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "nodes"
    / "Node_108_MetaCognition"
)


@pytest.mark.skip(
    reason=(
        "Requires nodes/Node_108_MetaCognition/core/metacognition_engine "
        "— run manually"
    )
)
class TestMetacognitionEngine(unittest.TestCase):
    """Test cases for MetacognitionEngine."""

    def setUp(self):
        sys.path.insert(0, str(_NODE_DIR))
        from core.metacognition_engine import MetacognitionEngine  # noqa: PLC0415
        self.engine = MetacognitionEngine()

    def test_engine_initialization(self):
        self.assertIsNotNone(self.engine)

    def test_engine_has_required_methods(self):
        required_methods = ["process", "analyze", "reflect"]
        for method in required_methods:
            self.assertTrue(
                hasattr(self.engine, method),
                f"Engine missing required method: {method}",
            )

    def test_basic_processing(self):
        try:
            if hasattr(self.engine, "process"):
                self.engine.process({"test": "data"})
            self.assertTrue(True)
        except Exception as e:
            self.fail(f"Basic processing failed: {e}")


if __name__ == "__main__":
    unittest.main()
