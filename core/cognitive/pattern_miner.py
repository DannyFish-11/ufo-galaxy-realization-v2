"""
core.cognitive.pattern_miner — Hierarchical Pattern Mining with Activation Decay
================================================================================
PR-26 — Experience-Driven Pattern Discovery & Recursive Abstraction

Inspired by:
- ExpeL (Zhao et al., 2024): contrastive experience extraction from
  success-vs-failure trajectories.
- Generative Agents (Park et al., 2023): recursive abstraction of observations
  into higher-level insights ("Klaus painted" → "Klaus loves art" → ...).
- Soar/ACT-R: base-level activation — memories compete for retrieval via
  activation scores that decay over time and boost on access.

What PatternMiner does
----------------------
1. **Scans** TaskMemory periodically (every 10 min) and incrementally
   (on each new task completion).
2. **Discovers** three pattern types from execution history:
   - temporal patterns  —  time-based regularities ("9am weather checks")
   - strategy patterns  —  strategy effectiveness per task type
   - sequence patterns  —  common task sequences / chains
3. **Contrasts** success vs failure trajectories to extract conditional rules
   (ExpeL-style: "for task_type=X, strategy=A has 95% success vs strategy=B at 40%").
4. **Abstracts recursively** — when N similar low-level patterns accumulate,
   they merge into a higher-level pattern (Generative Agents-style).
5. **Decays activation** — patterns fade if not reinforced (Soar-style).
   Dead patterns are pruned automatically.

Pattern lifecycle
-----------------
    DISCOVERED → (validated) → CONFIRMED → (abstracted) → ABSTRACT
        ↑___________________________↓
              reinforcement
              (activation boost)

    Any state → (activation < 0.01 after decay) → DELETED

Integration
-----------
- Consumes TaskMemory records + ReflectionEngine reflection events
- Emits `cognitive.pattern.discovered` / `cognitive.pattern.confirmed` events
- Patterns queried by AdaptivePredictor for pre-execution recommendations
- Feeds into memory_bias_layer as an additional signal source
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("Galaxy.Cognitive.PatternMiner")

# ── Constants ────────────────────────────────────────────────────────────

_PATTERN_EVENT_DISCOVERED = "cognitive.pattern.discovered"
_PATTERN_EVENT_CONFIRMED = "cognitive.pattern.confirmed"
_PATTERN_EVENT_ABSTRACTED = "cognitive.pattern.abstracted"

# Mining parameters
_MIN_RECORDS_FOR_MINING = 5       # min TaskMemory records to start mining
_MIN_PATTERN_SUPPORT = 3          # min occurrences for a pattern to survive
_CONFIRMATION_THRESHOLD = 0.75     # success rate to confirm a strategy pattern
_TEMPORAL_BIN_MINUTES = 60        # time bucketing granularity
_ABSTRACTION_MERGE_THRESHOLD = 5   # min similar low-level patterns to abstract
_ACTIVATION_DECAY_PER_DAY = 0.92  # Soar-style base-level decay
_ACTIVATION_BOOST_ON_HIT = 0.15   # activation increase when pattern is validated
_ACTIVATION_BOOST_ON_ACCESS = 0.05  # activation increase when pattern is queried
_MAX_PATTERNS = 200               # cap to prevent unbounded growth

# Recursive abstraction levels
class AbstractionLevel(int, Enum):
    """Hierarchy of pattern abstraction."""
    RAW = 0         # Direct observation (e.g., "checked weather at 9am")
    TASK_TYPE = 1   # Task-type generalization (e.g., "weather queries")
    USER_HABIT = 2  # User habit inference (e.g., "morning information routine")
    DOMAIN = 3      # Cross-domain pattern (e.g., "time-sensitive info gathering")


# ── Data model ────────────────────────────────────────────────────────────


@dataclass
class BehaviorPattern:
    """A discovered behavior pattern with activation-based lifecycle.

    Attributes
    ----------
    pattern_id:       Unique identifier
    pattern_type:     'temporal', 'strategy', 'sequence', 'abstract'
    description:      Human-readable description
    level:            AbstractionLevel
    conditions:       Dict of conditions that trigger this pattern
                      e.g., {"task_type": "weather", "hour": 9}
    recommendation:   What to do when pattern matches
                      e.g., {"strategy": "single", "preheat_tools": ["weather"]}
    activation_score: Base-level activation [0.0, 1.0]
    confidence:       Statistical confidence [0.0, 1.0]
    support_count:    How many historical records support this pattern
    success_rate:     Success rate when pattern is followed (contrastive)
    source_patterns:  IDs of patterns that were merged into this (for abstracts)
    created_at:       Creation timestamp
    last_accessed:    Last time this pattern was queried/validated
    """

    pattern_id: str = ""
    pattern_type: str = "strategy"
    description: str = ""
    level: AbstractionLevel = AbstractionLevel.RAW
    conditions: Dict[str, Any] = field(default_factory=dict)
    recommendation: Dict[str, Any] = field(default_factory=dict)
    activation_score: float = 1.0
    confidence: float = 0.5
    support_count: int = 0
    success_rate: float = 0.0
    source_patterns: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "pattern_type": self.pattern_type,
            "description": self.description[:500],
            "level": self.level.name,
            "conditions": self.conditions,
            "recommendation": self.recommendation,
            "activation_score": round(self.activation_score, 4),
            "confidence": round(self.confidence, 4),
            "support_count": self.support_count,
            "success_rate": round(self.success_rate, 4),
            "source_patterns": self.source_patterns,
            "created_at": self.created_at,
            "last_accessed": self.last_accessed,
        }

    def decay(self, days: float = 1.0) -> None:
        """Decay activation score (Soar-style base-level activation)."""
        self.activation_score *= _ACTIVATION_DECAY_PER_DAY ** days
        self.activation_score = max(0.0, min(1.0, self.activation_score))

    def boost(self, amount: float = _ACTIVATION_BOOST_ON_HIT) -> None:
        """Boost activation when pattern is validated or accessed."""
        self.activation_score = min(1.0, self.activation_score + amount)
        self.last_accessed = time.time()


# ── Pattern Miner ─────────────────────────────────────────────────────────


class PatternMiner:
    """Hierarchical pattern mining with activation-based lifecycle.

    Usage::

        miner = get_pattern_miner()

        # Automatic: miner listens to task events and mines incrementally

        # Manual full scan
        miner.mine_full()

        # Query patterns for a task
        patterns = miner.match_patterns(task_type="weather", hour=9)
        for p in patterns:
            print(p.description)  # "User typically checks weather at 9am"
            print(p.recommendation)  # {"strategy": "single", ...}
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._patterns: Dict[str, BehaviorPattern] = {}
        self._pattern_counter = 0
        self._subscribed = False
        self._last_mine_time = 0.0
        self._mine_interval_s = 600.0  # 10 minutes
        self._pending_records: int = 0

    # ── Public API ──────────────────────────────────────────────────

    def subscribe_to_events(self) -> None:
        """Subscribe to state event bus for incremental mining."""
        if self._subscribed:
            return
        try:
            from core.state_event_bus import get_state_event_bus, StateEventType

            bus = get_state_event_bus()
            bus.subscribe(StateEventType.TASK_DONE, self._on_task_done)
            bus.subscribe(StateEventType.TASK_FAILED, self._on_task_failed)
            bus.subscribe("cognitive.reflection", self._on_reflection)
            self._subscribed = True
            logger.debug("PatternMiner subscribed to events")
        except Exception as exc:
            logger.warning("PatternMiner subscription failed (non-fatal): %s", exc)

    def mine_full(self) -> int:
        """Run full pattern mining scan on all TaskMemory records.

        Returns number of new patterns discovered.
        """
        try:
            records = self._fetch_all_records()
            if len(records) < _MIN_RECORDS_FOR_MINING:
                logger.debug(
                    "PatternMiner: insufficient records (%d < %d)",
                    len(records), _MIN_RECORDS_FOR_MINING,
                )
                return 0
            new_count = self._mine_all(records)
            self._last_mine_time = time.time()
            return new_count
        except Exception as exc:
            logger.debug("mine_full failed (non-fatal): %s", exc)
            return 0

    def mine_incremental(self) -> int:
        """Run incremental mining on recent records only.

        Called automatically on each task completion event.
        Returns number of new patterns discovered.
        """
        try:
            records = self._fetch_recent_records(n=50)
            if len(records) < 3:
                return 0
            new_count = self._mine_all(records)
            return new_count
        except Exception as exc:
            logger.debug("mine_incremental failed (non-fatal): %s", exc)
            return 0

    def match_patterns(
        self,
        task: str = "",
        task_type: str = "",
        hour: Optional[int] = None,
        strategy: str = "",
        min_activation: float = 0.1,
        limit: int = 10,
    ) -> List[BehaviorPattern]:
        """Find patterns matching given conditions, sorted by activation.

        Also boosts activation of accessed patterns (Soar-style
        retrieval practice effect).
        """
        matches: List[Tuple[float, BehaviorPattern]] = []

        with self._lock:
            for pat in self._patterns.values():
                if pat.activation_score < min_activation:
                    continue

                score = self._match_score(pat, task, task_type, hour, strategy)
                if score > 0:
                    matches.append((score, pat))
                    # Boost activation on access
                    pat.boost(_ACTIVATION_BOOST_ON_ACCESS)

        matches.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in matches[:limit]]

    def get_patterns_by_type(
        self, pattern_type: str, min_activation: float = 0.1
    ) -> List[BehaviorPattern]:
        """Get all patterns of a specific type above activation threshold."""
        with self._lock:
            results = [
                p for p in self._patterns.values()
                if p.pattern_type == pattern_type
                and p.activation_score >= min_activation
            ]
            results.sort(key=lambda p: p.activation_score, reverse=True)
            return results

    def decay_all(self, days: float = 1.0) -> int:
        """Decay all pattern activations and prune dead patterns.

        Returns number of patterns pruned.
        """
        with self._lock:
            for p in self._patterns.values():
                p.decay(days)

            before = len(self._patterns)
            dead = [
                pid for pid, p in self._patterns.items()
                if p.activation_score < 0.01
            ]
            for pid in dead:
                del self._patterns[pid]

            return len(dead)

    def to_dict_list(self) -> List[Dict[str, Any]]:
        """Export all patterns as JSON-safe list."""
        with self._lock:
            return [p.to_dict() for p in self._patterns.values()]

    # ── Internal: Mining ────────────────────────────────────────────

    def _mine_all(self, records: List[Dict[str, Any]]) -> int:
        """Run all mining algorithms. Returns total new patterns."""
        new_total = 0
        new_total += self._mine_temporal(records)
        new_total += self._mine_strategy_contrastive(records)
        new_total += self._mine_sequences(records)
        new_total += self._try_recursive_abstraction()
        if new_total > 0:
            logger.info(
                "PatternMiner: discovered %d new patterns (total stored: %d)",
                new_total, len(self._patterns),
            )
        return new_total

    def _mine_temporal(self, records: List[Dict[str, Any]]) -> int:
        """Discover temporal patterns: task types concentrated at specific hours.

        Example: "weather tasks cluster at 9am" → pattern with
        conditions={task_type: "weather", hour: 9}
        """
        # Group records by (task_type, hour_bin)
        hourly: Dict[Tuple[str, int], List[Dict]] = defaultdict(list)
        for r in records:
            ts = r.get("timestamp", 0)
            if ts > 0:
                hour = time.localtime(ts).tm_hour
                bin_hour = (hour // (_TEMPORAL_BIN_MINUTES // 60)) * (
                    _TEMPORAL_BIN_MINUTES // 60
                ) if _TEMPORAL_BIN_MINUTES >= 60 else hour
                tt = r.get("task_type", "") or self._infer_task_type(r.get("task", ""))
                hourly[(tt, bin_hour)].append(r)

        new_patterns = 0
        for (task_type, hour), group in hourly.items():
            if len(group) < _MIN_PATTERN_SUPPORT:
                continue
            if not task_type:
                continue

            success_count = sum(1 for r in group if r.get("success", True))
            success_rate = success_count / len(group)

            pattern_id = self._next_pattern_id()
            description = (
                f"'{task_type}' tasks frequently occur around {hour}:00 "
                f"({len(group)} occurrences, {success_rate*100:.0f}% success). "
                f"Consider pre-heating relevant tools at this time."
            )

            pat = BehaviorPattern(
                pattern_id=pattern_id,
                pattern_type="temporal",
                description=description,
                level=AbstractionLevel.RAW,
                conditions={"task_type": task_type, "hour": hour},
                recommendation={
                    "preheat": True,
                    "note": f"User frequently requests '{task_type}' around {hour}:00",
                },
                activation_score=min(1.0, 0.5 + len(group) * 0.05),
                confidence=min(0.95, len(group) * 0.1),
                support_count=len(group),
                success_rate=success_rate,
            )

            if self._add_pattern(pat):
                new_patterns += 1
                self._emit_pattern_event(_PATTERN_EVENT_DISCOVERED, pat)

        return new_patterns

    def _mine_strategy_contrastive(self, records: List[Dict[str, Any]]) -> int:
        """Discover strategy effectiveness patterns via contrastive learning.

        ExpeL-style: compare success rates across strategies for each task type.

        Example: "for 'weather' tasks, strategy='single' has 95% success
        (19/20) while strategy='swarm' has 50% (1/2)" → recommend 'single'.
        """
        # Group by task_type → strategy → outcomes
        strat_stats: Dict[str, Dict[str, Dict]] = defaultdict(
            lambda: defaultdict(lambda: {"success": 0, "fail": 0, "durations": []})
        )
        for r in records:
            tt = r.get("task_type", "") or self._infer_task_type(r.get("task", ""))
            strat = r.get("strategy", "unknown") or "unknown"
            if not tt or not strat or strat == "unknown":
                continue
            if r.get("success", True):
                strat_stats[tt][strat]["success"] += 1
            else:
                strat_stats[tt][strat]["fail"] += 1
            d = r.get("duration_ms", 0)
            if d > 0:
                strat_stats[tt][strat]["durations"].append(d)

        new_patterns = 0
        for task_type, strategies in strat_stats.items():
            if len(strategies) < 2:
                continue  # need at least 2 strategies to contrast

            # Find best and worst strategies
            strat_rates = {
                s: stats["success"] / max(stats["success"] + stats["fail"], 1)
                for s, stats in strategies.items()
            }
            best_strat = max(strat_rates, key=strat_rates.get)
            worst_strat = min(strat_rates, key=strat_rates.get)

            best_rate = strat_rates[best_strat]
            worst_rate = strat_rates[worst_strat]

            if best_rate < _CONFIRMATION_THRESHOLD:
                continue  # no strategy is reliably good enough

            total_support = sum(
                s["success"] + s["fail"] for s in strategies.values()
            )
            if total_support < _MIN_PATTERN_SUPPORT:
                continue

            # Only create pattern if there's meaningful contrast
            if best_rate - worst_rate < 0.2:
                continue

            pattern_id = self._next_pattern_id()
            avg_dur = ""
            durations = strategies[best_strat]["durations"]
            if durations:
                avg = sum(durations) / len(durations)
                avg_dur = f" avg_duration={avg:.0f}ms"

            description = (
                f"For '{task_type}' tasks, '{best_strat}' outperforms alternatives "
                f"({best_rate*100:.0f}% success vs worst at {worst_rate*100:.0f}%)."
                f"{avg_dur} Recommend '{best_strat}' for this task type."
            )

            pat = BehaviorPattern(
                pattern_id=pattern_id,
                pattern_type="strategy",
                description=description,
                level=AbstractionLevel.TASK_TYPE,
                conditions={"task_type": task_type},
                recommendation={
                    "strategy": best_strat,
                    "confidence": best_rate,
                    "avoid": worst_strat if worst_rate < 0.4 else None,
                },
                activation_score=min(1.0, best_rate),
                confidence=best_rate,
                support_count=total_support,
                success_rate=best_rate,
            )

            if self._add_pattern(pat):
                new_patterns += 1
                self._emit_pattern_event(_PATTERN_EVENT_CONFIRMED, pat)

        return new_patterns

    def _mine_sequences(self, records: List[Dict[str, Any]]) -> int:
        """Discover common task sequences (what tends to follow what).

        Example: after 'weather' task, 80% of the time next task is 'news'.
        """
        # Sort by timestamp
        sorted_records = sorted(records, key=lambda r: r.get("timestamp", 0))
        if len(sorted_records) < _MIN_PATTERN_SUPPORT * 2:
            return 0

        # Count transitions: task_type_A → task_type_B
        transitions: Dict[Tuple[str, str], int] = Counter()
        task_type_counts: Dict[str, int] = Counter()

        for i in range(len(sorted_records) - 1):
            tt1 = (
                sorted_records[i].get("task_type", "")
                or self._infer_task_type(sorted_records[i].get("task", ""))
            )
            tt2 = (
                sorted_records[i + 1].get("task_type", "")
                or self._infer_task_type(sorted_records[i + 1].get("task", ""))
            )
            if tt1 and tt2 and tt1 != tt2:
                transitions[(tt1, tt2)] += 1
                task_type_counts[tt1] += 1

        new_patterns = 0
        for (from_type, to_type), count in transitions.items():
            if count < _MIN_PATTERN_SUPPORT:
                continue
            total_from = task_type_counts.get(from_type, 1)
            probability = count / total_from
            if probability < 0.3:
                continue  # less than 30% follow-through is not a strong pattern

            pattern_id = self._next_pattern_id()
            description = (
                f"After '{from_type}' tasks, '{to_type}' frequently follows "
                f"({count} times, {probability*100:.0f}% probability). "
                f"Consider preparing '{to_type}' resources proactively."
            )

            pat = BehaviorPattern(
                pattern_id=pattern_id,
                pattern_type="sequence",
                description=description,
                level=AbstractionLevel.RAW,
                conditions={"preceding_task_type": from_type},
                recommendation={
                    "likely_next": to_type,
                    "probability": probability,
                    "prepare": True,
                },
                activation_score=min(1.0, probability + count * 0.02),
                confidence=probability,
                support_count=count,
            )

            if self._add_pattern(pat):
                new_patterns += 1
                self._emit_pattern_event(_PATTERN_EVENT_DISCOVERED, pat)

        return new_patterns

    def _try_recursive_abstraction(self) -> int:
        """Attempt to merge similar low-level patterns into higher-level ones.

        Generative Agents-style: "checked weather at 9am" +
        "checked news at 9am" + "checked email at 9am" →
        "User has morning information gathering routine".
        """
        # Group temporal patterns by hour
        temporal_by_hour: Dict[int, List[BehaviorPattern]] = defaultdict(list)
        strategy_by_task: Dict[str, List[BehaviorPattern]] = defaultdict(list)

        with self._lock:
            for pat in self._patterns.values():
                if pat.pattern_type == "temporal" and pat.level == AbstractionLevel.RAW:
                    hour = pat.conditions.get("hour")
                    if hour is not None:
                        temporal_by_hour[hour].append(pat)
                elif pat.pattern_type == "strategy" and pat.level == AbstractionLevel.TASK_TYPE:
                    tt = pat.conditions.get("task_type", "")
                    if tt:
                        strategy_by_task[tt].append(pat)

        new_patterns = 0

        # Abstract temporal patterns: multiple task_types at same hour
        for hour, patterns in temporal_by_hour.items():
            if len(patterns) >= _ABSTRACTION_MERGE_THRESHOLD:
                task_types = sorted(set(p.conditions.get("task_type", "") for p in patterns))
                pattern_id = self._next_pattern_id()
                description = (
                    f"User has a multi-task information routine around {hour}:00 "
                    f"involving: {', '.join(task_types)}. "
                    f"This suggests a structured morning/afternoon workflow."
                )

                pat = BehaviorPattern(
                    pattern_id=pattern_id,
                    pattern_type="abstract",
                    description=description,
                    level=AbstractionLevel.USER_HABIT,
                    conditions={"hour": hour, "task_types": task_types},
                    recommendation={
                        "note": f"Multi-task routine at {hour}:00 — prepare all: {task_types}",
                        "prepare_all": task_types,
                    },
                    activation_score=sum(p.activation_score for p in patterns) / len(patterns),
                    confidence=sum(p.confidence for p in patterns) / len(patterns),
                    support_count=sum(p.support_count for p in patterns),
                    source_patterns=[p.pattern_id for p in patterns],
                )

                if self._add_pattern(pat):
                    new_patterns += 1
                    self._emit_pattern_event(_PATTERN_EVENT_ABSTRACTED, pat)

        return new_patterns

    # ── Internal helpers ────────────────────────────────────────────

    def _add_pattern(self, pattern: BehaviorPattern) -> bool:
        """Add pattern if not duplicate. Returns True if added."""
        # Check for near-duplicate
        with self._lock:
            for existing in self._patterns.values():
                if (
                    existing.pattern_type == pattern.pattern_type
                    and existing.conditions == pattern.conditions
                    and existing.level == pattern.level
                ):
                    # Duplicate — boost existing instead
                    existing.boost(_ACTIVATION_BOOST_ON_HIT)
                    existing.support_count += pattern.support_count
                    return False

            # Capacity management
            if len(self._patterns) >= _MAX_PATTERNS:
                # Remove lowest activation
                lowest = min(self._patterns.values(), key=lambda p: p.activation_score)
                if lowest.activation_score < pattern.activation_score:
                    del self._patterns[lowest.pattern_id]
                else:
                    return False  # new pattern not good enough

            self._patterns[pattern.pattern_id] = pattern
            return True

    def _match_score(
        self,
        pat: BehaviorPattern,
        task: str,
        task_type: str,
        hour: Optional[int],
        strategy: str,
    ) -> float:
        """Compute match score between pattern and query conditions."""
        score = 0.0
        cond = pat.conditions

        # Task type match (strong signal)
        if task_type and cond.get("task_type") == task_type:
            score += 0.5
        elif task and cond.get("task_type"):
            if cond["task_type"].lower() in task.lower():
                score += 0.3

        # Hour match for temporal patterns
        if hour is not None and cond.get("hour") == hour:
            score += 0.3

        # Task keyword fallback
        if task and not task_type:
            task_lower = task.lower()
            for key in cond.values():
                if isinstance(key, str) and key.lower() in task_lower:
                    score += 0.2

        # Strategy match (for contrasting)
        if strategy and cond.get("strategy") == strategy:
            score += 0.1

        return score

    def _next_pattern_id(self) -> str:
        """Generate unique pattern ID."""
        self._pattern_counter += 1
        return f"pat_{self._pattern_counter:06d}_{int(time.time())%10000}"

    @staticmethod
    def _infer_task_type(task_text: str) -> str:
        """Infer task type from task description keywords."""
        text = task_text.lower()
        type_keywords = {
            "weather": ["weather", "forecast", "temperature", "rain", "sunny"],
            "news": ["news", "headline", "article", "报道", "新闻"],
            "search": ["search", "find", "look up", "查找", "搜索"],
            "email": ["email", "mail", "inbox", "邮件"],
            "calendar": ["calendar", "schedule", "appointment", "日程"],
            "code": ["code", "program", "script", "debug", "代码", "编程"],
            "translate": ["translate", "translation", "翻译"],
            "summarize": ["summarize", "summary", "总结", "摘要"],
            "weather_query": ["天气", "气温", "下雨"],
        }
        scores = {
            tt: sum(1 for kw in keywords if kw in text)
            for tt, keywords in type_keywords.items()
        }
        best = max(scores, key=scores.get)
        return best if scores[best] > 0 else "general"

    # ── Data fetching ───────────────────────────────────────────────

    @staticmethod
    def _fetch_all_records() -> List[Dict[str, Any]]:
        """Fetch all records from TaskMemory."""
        try:
            from core.task_memory import get_task_memory

            tm = get_task_memory()
            summaries = tm.get_recent_summaries(n=1000)
            return [s.to_dict() for s in summaries]
        except Exception as exc:
            logger.debug("_fetch_all_records failed: %s", exc)
            return []

    @staticmethod
    def _fetch_recent_records(n: int = 50) -> List[Dict[str, Any]]:
        """Fetch recent records from TaskMemory."""
        try:
            from core.task_memory import get_task_memory

            tm = get_task_memory()
            summaries = tm.get_recent_summaries(n=n)
            return [s.to_dict() for s in summaries]
        except Exception as exc:
            logger.debug("_fetch_recent_records failed: %s", exc)
            return []

    # ── Event emission ──────────────────────────────────────────────

    def _emit_pattern_event(self, event_type: str, pattern: BehaviorPattern) -> None:
        """Emit pattern discovery event on state event bus."""
        try:
            from core.state_event_bus import get_state_event_bus

            get_state_event_bus().publish(
                event_type,
                source="pattern_miner",
                payload=pattern.to_dict(),
                trace_id=f"pat_{int(time.time()*1000)%10**9}",
            )
        except Exception as exc:
            logger.debug("Pattern event emission failed (non-fatal): %s", exc)

    # ── Event bus callbacks ─────────────────────────────────────────

    def _on_task_done(self, event: Any) -> None:
        """Trigger incremental mining on task completion."""
        self._pending_records += 1
        if self._pending_records >= 5:
            self._pending_records = 0
            self.mine_incremental()
        elif time.time() - self._last_mine_time > self._mine_interval_s:
            self.mine_incremental()

    def _on_task_failed(self, event: Any) -> None:
        """Also trigger mining on failures (important for contrastive learning)."""
        self._on_task_done(event)

    def _on_reflection(self, event: Any) -> None:
        """Listen to reflection events for additional signals."""
        # Reflections can hint at new patterns to explore
        try:
            payload = getattr(event, "payload", {}) or {}
            if payload.get("reflection_type") == "retrospective" and not payload.get("success", True):
                # Failed tasks are rich mining signals
                self.mine_incremental()
        except Exception:
            pass


# ── Singleton accessors ───────────────────────────────────────────────────

_miner_instance: Optional[PatternMiner] = None
_miner_lock = threading.Lock()


def get_pattern_miner() -> PatternMiner:
    """Return the process-wide PatternMiner singleton."""
    global _miner_instance
    if _miner_instance is None:
        with _miner_lock:
            if _miner_instance is None:
                _miner_instance = PatternMiner()
                _miner_instance.subscribe_to_events()
                logger.debug("PatternMiner singleton initialised")
    return _miner_instance


def reset_pattern_miner() -> None:
    """Reset singleton (for testing only)."""
    global _miner_instance
    with _miner_lock:
        _miner_instance = None
