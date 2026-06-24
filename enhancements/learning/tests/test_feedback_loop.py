#!/usr/bin/env python3
"""
Unit tests for enhancements/learning/feedback_loop.py

注：此前的版本来自另一套代码(galaxy-v5)，import 了不存在的类、断言了不同的枚举值、
并写死了 /mnt/okcomputer 路径 —— 完全跑不起来。本文件按【当前】feedback_loop 的真实
API 重写，可直接 python -m unittest 运行通过。
"""

import os
import sys
import unittest

# 让 `import feedback_loop` 在任意 CWD 下都能解析到同级目录的实现（不再写死绝对路径）。
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from feedback_loop import (  # noqa: E402
    FeedbackTarget,
    FeedbackType,
    FeedbackEntry,
    FeedbackRecord,
    FeedbackLoop,
    PerformanceMetric,
    MetricsTracker,
    ReinforcementLearner,
)


class TestEnums(unittest.TestCase):
    def test_feedback_types(self):
        names = {t.name for t in FeedbackType}
        self.assertEqual(names, {"POSITIVE", "NEGATIVE", "NEUTRAL", "CORRECTIVE"})

    def test_feedback_targets(self):
        names = {t.name for t in FeedbackTarget}
        self.assertEqual(names, {"SYSTEM", "MODEL", "STRATEGY", "BEHAVIOR", "USER"})


class TestFeedbackRecord(unittest.TestCase):
    def _record(self, success=True):
        return FeedbackRecord(
            record_id="r1", action="open_app", outcome="ok",
            success=success, reward=0.8, context={"k": "v"},
        )

    def test_to_dict_uses_declared_fields(self):
        d = self._record().to_dict()
        self.assertEqual(d["record_id"], "r1")
        self.assertEqual(d["action"], "open_app")
        self.assertTrue(d["success"])
        self.assertEqual(d["context"], {"k": "v"})
        self.assertIn("timestamp", d)

    def test_from_record_returns_feedback_entry(self):
        # 回归：from_record 必须返回 FeedbackEntry（此前误用 cls(...) 会 TypeError）。
        entry = FeedbackRecord.from_record(self._record(success=True))
        self.assertIsInstance(entry, FeedbackEntry)
        self.assertEqual(entry.feedback_id, "r1")
        self.assertEqual(entry.feedback_type, FeedbackType.POSITIVE)
        self.assertEqual(entry.content, "open_app -> ok")
        self.assertEqual(entry.metadata, {"k": "v"})

    def test_from_record_negative_on_failure(self):
        entry = FeedbackRecord.from_record(self._record(success=False))
        self.assertEqual(entry.feedback_type, FeedbackType.NEGATIVE)


class TestFeedbackLoop(unittest.TestCase):
    def _entry(self, ft=FeedbackType.POSITIVE):
        return FeedbackEntry(
            feedback_id="f1", feedback_type=ft, source="test",
            target="system", content="good", confidence=0.9,
        )

    def test_add_and_recent(self):
        loop = FeedbackLoop()
        loop.add_feedback(self._entry())
        loop.add_feedback(self._entry(FeedbackType.NEGATIVE))
        self.assertEqual(len(loop.get_recent_feedback()), 2)
        pos = loop.get_recent_feedback(feedback_type=FeedbackType.POSITIVE)
        self.assertEqual(len(pos), 1)

    def test_stats_and_clear(self):
        loop = FeedbackLoop()
        loop.add_feedback(self._entry())
        stats = loop.get_feedback_stats()
        self.assertEqual(stats["total_feedback"], 1)
        self.assertEqual(stats["by_type"].get("POSITIVE"), 1)
        loop.clear_history()
        self.assertEqual(loop.get_feedback_stats()["total_feedback"], 0)

    def test_handler_invoked(self):
        loop = FeedbackLoop()
        seen = []
        loop.register_handler(FeedbackType.POSITIVE, lambda fb: seen.append(fb))
        loop.add_feedback(self._entry())
        self.assertEqual(len(seen), 1)

    def test_history_cap(self):
        loop = FeedbackLoop(max_history=3)
        for _ in range(5):
            loop.add_feedback(self._entry())
        self.assertEqual(len(loop.get_recent_feedback(limit=999)), 3)


class TestMetrics(unittest.TestCase):
    def test_record_and_average(self):
        tracker = MetricsTracker()
        for v in (10.0, 20.0, 30.0):
            tracker.record_metric(PerformanceMetric(metric_name="latency", value=v, unit="ms"))
        self.assertEqual(len(tracker.get_metrics("latency")), 3)
        self.assertEqual(tracker.get_average("latency"), 20.0)
        self.assertIsNone(tracker.get_average("missing"))
        tracker.clear_metrics("latency")
        self.assertEqual(tracker.get_metrics("latency"), [])


class TestReinforcementLearner(unittest.TestCase):
    def test_q_update_and_choice(self):
        rl = ReinforcementLearner()
        self.assertEqual(rl.get_q_value("s", "a"), 0.0)
        rl.update_q_value("s", "a", reward=1.0, next_state="s2")
        self.assertGreater(rl.get_q_value("s", "a"), 0.0)
        # epsilon=0 → 纯利用，必选 Q 值最高的动作
        rl.update_q_value("s", "b", reward=0.0, next_state="s2")
        self.assertEqual(rl.choose_action("s", ["a", "b"], epsilon=0.0), "a")
        self.assertIn("a", rl.get_policy("s"))


if __name__ == "__main__":
    unittest.main()
