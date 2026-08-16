#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/cognitive/experience_guidance.py — 执行经验制导（对象锚定）
================================================================

**定位：把"策略→成败"的历史统计从文本锚定改为对象锚定。**

历史实现（``ExecutionPlanner._experience_strategy_adjust``）的做法是：
把结构化事实拼成中文散文写进统一记忆层，再用向量相似度召回 8 段文本，
最后用正则 ``策略\\[X\\] ... 结果\\[成功|失败\\]`` 把结构抠回来算"成功率"。
这条链路有三处硬伤：

1. **算出来的不是成功率。** 分母是"按语义相似度召回的至多 8 条"，
   不是该策略的实际执行总数——样本由 embedding 决定，措辞一变数字就变。
2. **没有类型过滤。** 共享的无类型文本命名空间里，任何写入方只要恰好
   写出同样的括号格式就会污染统计。
3. **格式字符串一改，学习静默停止。** 正则匹配不上只是 ``continue``，
   不报错、不告警。

本模块改为直接读 :class:`core.task_memory.TaskSummary` 的**类型化字段**
（``strategy: str`` / ``success: bool`` / ``task_type: str``），
作用域由 ``retrieve_similar()`` 的 **BM25 词法排序**（确定性、零依赖）提供。
全链路无正则、无 embedding、无新依赖，分母是真实计数而非相似度采样。

层级定位
--------
本模块产出的 :class:`ExperienceGuidance` 与 PR-18 的 ``PlannerBreadthGuidance``、
PR-19 的 ``MemoryPlannerGuidance`` **同级**，都是喂给
``ExecutionPlanner._pick_strategy()`` 的**建议输入**，而不是后置覆写。
它服从 ``memory_bias_layer`` 已确立的教条：

    MEMORY_BIAS_LAYER::POLICY_4 — Memory bias is the *lowest-priority*
    influence on execution strategy selection.

经验统计同样派生自历史记忆，因此同样是最低优先级：它**永不**覆盖
task_type 映射、显式关键词命中、认知预算偏好或记忆连续性偏好。

灰度
----
``GALAXY_EXPERIENCE_GUIDANCE`` = ``off`` | ``shadow`` | ``on``（默认 ``on``）。
``shadow`` 只计算并记录、不影响策略选择，用于上线前比对。
历史开关 ``GALAXY_EXPERIENCE_STRATEGY=0`` 继续作为总闸生效（向后兼容）。
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.Cognitive.ExperienceGuidance")

__all__ = [
    # Authority / policy sentinels
    "EXPERIENCE_GUIDANCE_IS_AUTHORITY",
    "EXPERIENCE_GUIDANCE_OBJECT_ANCHORED_POLICY",
    "EXPERIENCE_GUIDANCE_IS_ADVISORY_NOT_AUTHORITATIVE_POLICY",
    "EXPERIENCE_GUIDANCE_NEVER_OVERRIDES_EXPLICIT_SIGNALS_POLICY",
    "EXPERIENCE_GUIDANCE_PATTERN_MINER_BOUNDARY",
    # Modes
    "MODE_OFF",
    "MODE_SHADOW",
    "MODE_ON",
    "get_experience_guidance_mode",
    # Model
    "ExperienceGuidance",
    "StrategyStat",
    # Derivation
    "derive_experience_guidance",
    "build_experience_guidance_diagnostics",
    "get_experience_guidance_stats",
    # Tunables
    "DEFAULT_MIN_SAMPLES",
    "DEFAULT_MARGIN",
    "DEFAULT_COLD_START_FLOOR",
    "DEFAULT_SCOPE_K",
]


# ---------------------------------------------------------------------------
# Authority / policy sentinels
# ---------------------------------------------------------------------------

EXPERIENCE_GUIDANCE_IS_AUTHORITY: str = (
    "EXPERIENCE_GUIDANCE::AUTHORITY: "
    "This module is the sole derivation point for strategy-success statistics "
    "consumed by ExecutionPlanner._pick_strategy().  Consumers MUST NOT compute "
    "strategy success rates by parsing retrieved prose."
)

EXPERIENCE_GUIDANCE_OBJECT_ANCHORED_POLICY: str = (
    "EXPERIENCE_GUIDANCE::POLICY_1: "
    "Strategy statistics MUST be aggregated from typed TaskSummary fields "
    "(strategy: str, success: bool).  Regex extraction of structure from "
    "similarity-retrieved text is forbidden — the denominator of such a sample "
    "is decided by embedding similarity, not by the actual execution population."
)

EXPERIENCE_GUIDANCE_IS_ADVISORY_NOT_AUTHORITATIVE_POLICY: str = (
    "EXPERIENCE_GUIDANCE::POLICY_2: "
    "ExperienceGuidance is strictly advisory.  It is an input to "
    "_pick_strategy() alongside breadth and memory guidance, never a post-hoc "
    "override of the strategy that selection already produced."
)

EXPERIENCE_GUIDANCE_NEVER_OVERRIDES_EXPLICIT_SIGNALS_POLICY: str = (
    "EXPERIENCE_GUIDANCE::POLICY_3: "
    "Experience statistics are memory-derived and therefore inherit "
    "MEMORY_BIAS_LAYER::POLICY_4 — lowest priority.  They MUST NOT override "
    "task-type mapping, explicit keyword matches, activation-budget strategy "
    "preference, or memory continuity preference."
)

EXPERIENCE_GUIDANCE_PATTERN_MINER_BOUNDARY: str = (
    "EXPERIENCE_GUIDANCE::BOUNDARY_PATTERN_MINER: "
    "PatternMiner._mine_strategy_patterns() also aggregates strategy success "
    "rates from typed TaskMemory records, and is likewise object-anchored.  The "
    "two are NOT interchangeable and neither supersedes the other:\n"
    "  PatternMiner      — coarse, task_type-level, mined periodically, subject "
    "to activation decay, consumed by AdaptivePredictor → desktop_presence_runtime. "
    "Answers 'which strategy wins for this KIND of task, historically'.\n"
    "  ExperienceGuidance — per-message scope via BM25 lexical ranking, computed "
    "synchronously at decision time with no staleness, consumed by "
    "ExecutionPlanner._pick_strategy(). Answers 'which strategy wins for THIS "
    "task, right now'.\n"
    "AdaptivePredictor is not wired into core/agent/ at all.  Consolidating both "
    "onto one shared aggregation authority is tracked follow-up work; until then "
    "neither may be described as the single source of strategy statistics."
)


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

MODE_OFF: str = "off"
"""Disabled entirely — derivation returns a neutral, non-influencing guidance."""

MODE_SHADOW: str = "shadow"
"""Compute and log the candidate, but never influence strategy selection."""

MODE_ON: str = "on"
"""Compute and allow the candidate to influence strategy selection."""

_VALID_MODES = (MODE_OFF, MODE_SHADOW, MODE_ON)

_ENV_MODE = "GALAXY_EXPERIENCE_GUIDANCE"
_ENV_LEGACY_KILL_SWITCH = "GALAXY_EXPERIENCE_STRATEGY"


def get_experience_guidance_mode() -> str:
    """Resolve the current rollout mode.

    Precedence:
      1. Legacy kill switch ``GALAXY_EXPERIENCE_STRATEGY`` in ("0","false","no")
         forces :data:`MODE_OFF` — preserves the historical opt-out contract.
      2. ``GALAXY_EXPERIENCE_GUIDANCE`` selects off / shadow / on.
      3. Default :data:`MODE_ON` — the historical behaviour was active by
         default, so defaulting to shadow would silently disable a live feature.

    An unrecognised value degrades to :data:`MODE_ON` with a warning rather than
    raising: strategy selection must never fail because of a typo in an env var.
    """
    legacy = os.getenv(_ENV_LEGACY_KILL_SWITCH, "1").strip().lower()
    if legacy in ("0", "false", "no", "off"):
        return MODE_OFF

    raw = os.getenv(_ENV_MODE, MODE_ON).strip().lower()
    if raw in _VALID_MODES:
        return raw
    logger.warning(
        "%s=%r is not one of %s — falling back to %r",
        _ENV_MODE,
        raw,
        _VALID_MODES,
        MODE_ON,
    )
    return MODE_ON


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

DEFAULT_MIN_SAMPLES: int = 5
"""Minimum executions of a strategy before its success rate is trusted.

The historical implementation used 3 out of a top-8 similarity sample.  Because
the population is now exact rather than embedding-sampled, the threshold is
raised to 5 — a real count of 5 is far stronger evidence than a sampled 3.
"""

DEFAULT_MARGIN: float = 0.34
"""Required success-rate advantage before switching away from the current
strategy.  Kept at the historical value so this change alters *what the numbers
mean*, not *how eagerly the planner switches*."""

DEFAULT_COLD_START_FLOOR: float = 0.60
"""When the current strategy has no qualifying samples, a candidate must clear
this absolute success rate before it may influence selection.

The historical implementation switched on *any* qualifying candidate when the
current strategy had no data (``cur is None``), which let a 34%-success strategy
win purely by being the only one with records."""

DEFAULT_SCOPE_K: int = 64
"""Upper bound on BM25-ranked similar tasks pulled for aggregation."""

DEFAULT_SCOPE_MIN_SCORE: float = 0.15
"""Relative BM25 score floor (fraction of top hit) for scope membership."""


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class StrategyStat:
    """Exact success statistics for one strategy over the scoped population."""

    strategy: str = ""
    successes: int = 0
    total: int = 0

    @property
    def rate(self) -> float:
        """Success rate in [0.0, 1.0]; 0.0 when there are no samples."""
        return (self.successes / self.total) if self.total else 0.0

    def qualifies(self, min_samples: int) -> bool:
        return self.total >= min_samples

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy,
            "successes": self.successes,
            "total": self.total,
            "rate": round(self.rate, 4),
        }


@dataclass
class ExperienceGuidance:
    """Planner guidance derived from exact strategy-success statistics.

    Shape mirrors :class:`~core.cognitive.memory_bias_layer.MemoryPlannerGuidance`
    and ``PlannerBreadthGuidance`` so ``_pick_strategy`` consumes all three the
    same way.

    Attributes
    ----------
    candidate_strategy:
        Strategy the statistics favour, or ``""`` when none qualifies.
    candidate_rate / candidate_n:
        Exact success rate and sample count for the candidate.
    current_strategy / current_rate / current_n:
        The same, for the strategy selection would otherwise produce.
    influenced_by_experience:
        True only when a qualifying candidate exists **and** the mode is
        :data:`MODE_ON`.  In :data:`MODE_SHADOW` the candidate is populated but
        this stays False, so the planner ignores it.
    scope_size:
        Number of historical task records the statistics were aggregated over.
    mode:
        Rollout mode this guidance was derived under.
    diagnostic_note:
        Human-readable explanation of the decision.
    """

    candidate_strategy: str = ""
    candidate_rate: float = 0.0
    candidate_n: int = 0
    current_strategy: str = ""
    current_rate: float = 0.0
    current_n: int = 0
    influenced_by_experience: bool = False
    scope_size: int = 0
    mode: str = MODE_OFF
    diagnostic_note: str = ""
    stats: List[StrategyStat] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "candidate_strategy": self.candidate_strategy,
            "candidate_rate": round(self.candidate_rate, 4),
            "candidate_n": self.candidate_n,
            "current_strategy": self.current_strategy,
            "current_rate": round(self.current_rate, 4),
            "current_n": self.current_n,
            "influenced_by_experience": self.influenced_by_experience,
            "scope_size": self.scope_size,
            "mode": self.mode,
            "diagnostic_note": self.diagnostic_note,
            "stats": [s.to_dict() for s in self.stats],
        }


# ---------------------------------------------------------------------------
# Derivation
# ---------------------------------------------------------------------------


_STATS_LOCK = threading.Lock()
_STATS: Dict[str, Any] = {
    "derivations": 0,
    "influenced": 0,
    "declined_by_reason": {},
    "scope_sizes": [],
}
_SCOPE_SAMPLE_CAP = 500
"""Bounded: this is a long-lived process counter, not an unbounded log."""


def _note_outcome(guidance: "ExperienceGuidance") -> None:
    """Accumulate the evidence needed to judge the thresholds.

    ``DEFAULT_MIN_SAMPLES`` / ``DEFAULT_MARGIN`` / ``DEFAULT_COLD_START_FLOOR``
    were chosen by judgement, not by data — nothing so far says they are right.
    What they control is *how often this layer speaks at all*, so the first thing
    anyone tuning them needs is that rate, plus why it stayed quiet when it did.
    Reading it out of logs is possible; having it as a number is what makes the
    question answerable instead of merely arguable.
    """
    try:
        with _STATS_LOCK:
            _STATS["derivations"] += 1
            if getattr(guidance, "influenced_by_experience", False):
                _STATS["influenced"] += 1
            else:
                note = (getattr(guidance, "diagnostic_note", "") or "unspecified").split(";")[0].strip()
                _STATS["declined_by_reason"][note] = _STATS["declined_by_reason"].get(note, 0) + 1
            sizes = _STATS["scope_sizes"]
            if len(sizes) < _SCOPE_SAMPLE_CAP:
                sizes.append(int(getattr(guidance, "scope_size", 0) or 0))
    except Exception as exc:  # noqa: BLE001 — instrumentation must never break planning
        logger.debug("experience guidance stats skipped: %s", exc)


def get_experience_guidance_stats(*, reset: bool = False) -> Dict[str, Any]:
    """How often this layer actually spoke, and why it stayed quiet otherwise.

    ``reset=True`` returns the current window and starts a new one — that is how
    you measure "the last hour" rather than "since this process booted".  It is a
    parameter rather than a separate ``reset_...()`` function on purpose: a public
    reset with no production caller would be exactly the unused surface the wiring
    guard exists to catch, and it caught it here.
    """
    with _STATS_LOCK:
        sizes = list(_STATS["scope_sizes"])
        derivations = _STATS["derivations"]
        influenced = _STATS["influenced"]
        declined = dict(_STATS["declined_by_reason"])
        if reset:
            _STATS["derivations"] = 0
            _STATS["influenced"] = 0
            _STATS["declined_by_reason"] = {}
            _STATS["scope_sizes"] = []
    return {
        "derivations": derivations,
        "influenced": influenced,
        "influence_rate": round(influenced / derivations, 4) if derivations else 0.0,
        "declined_by_reason": declined,
        "median_scope_size": sorted(sizes)[len(sizes) // 2] if sizes else 0,
        "thresholds": {
            "min_samples": DEFAULT_MIN_SAMPLES,
            "margin": DEFAULT_MARGIN,
            "cold_start_floor": DEFAULT_COLD_START_FLOOR,
        },
    }


def _neutral(
    mode: str,
    note: str,
    current_strategy: str = "",
    scope_size: int = 0,
) -> ExperienceGuidance:
    """A guidance that provably cannot influence selection.

    ``scope_size`` is still reported so diagnostics can tell "there was no
    history at all" apart from "there was history, but none of it was usable" —
    a scope of 0 in the latter case would send a debugger down the wrong path.
    """
    guidance = ExperienceGuidance(
        current_strategy=current_strategy,
        influenced_by_experience=False,
        scope_size=scope_size,
        mode=mode,
        diagnostic_note=note,
    )
    _note_outcome(guidance)
    return guidance


def _scoped_records(memory: Any, message: str, task_type: str, min_samples: int) -> Tuple[List[Any], str]:
    """Collect the population to aggregate over, plus a label for how it was scoped.

    Primary scope is BM25 lexical similarity to *message* — deterministic, and
    it answers "similar tasks" without an embedding model.  When that scope is
    too thin to support any conclusion, widen to recent records (optionally
    filtered by ``task_type``) rather than drawing conclusions from 1–2 rows.
    """
    records: List[Any] = []
    try:
        records = list(memory.retrieve_similar(message, k=DEFAULT_SCOPE_K, min_score=DEFAULT_SCOPE_MIN_SCORE) or [])
    except Exception as exc:  # noqa: BLE001 — scope derivation must never break planning
        logger.debug("retrieve_similar failed: %s", exc)

    scope_kind = "similar"

    # Widening is deliberately restricted to a *typed* population.
    #
    # If the lexical scope is too thin we may fall back to "recent tasks OF THE
    # SAME task_type" — that is a real, nameable population.  We do NOT fall back
    # to "recent tasks of any kind": that answers a different question ("which
    # strategy has been working lately") while being reported as a conclusion
    # about *this* task.  Presenting a loosely-related sample as if it were the
    # relevant population is precisely the defect this module exists to remove,
    # so when there is no task_type to scope by, we return the thin scope and let
    # the min_samples gate decline to conclude anything.
    if len(records) < min_samples and task_type:
        try:
            widened = list(memory.get_recent_summaries(n=DEFAULT_SCOPE_K, task_type=task_type) or [])
        except Exception as exc:  # noqa: BLE001
            logger.debug("get_recent_summaries failed: %s", exc)
            widened = []
        if widened:
            # Merge without double-counting: summary_id is the record identity.
            seen = {getattr(r, "summary_id", id(r)) for r in records}
            for r in widened:
                key = getattr(r, "summary_id", id(r))
                if key not in seen:
                    seen.add(key)
                    records.append(r)
            scope_kind = f"similar+task_type={task_type}"

    return records, scope_kind


def _aggregate(records: List[Any]) -> Dict[str, StrategyStat]:
    """Aggregate exact per-strategy statistics from typed fields.

    No regex, no text parsing: ``strategy`` is already a string field and
    ``success`` is already a bool.
    """
    stats: Dict[str, StrategyStat] = {}
    for rec in records:
        strategy = (getattr(rec, "strategy", "") or "").strip()
        if not strategy:
            continue
        stat = stats.get(strategy)
        if stat is None:
            stat = StrategyStat(strategy=strategy)
            stats[strategy] = stat
        stat.total += 1
        if bool(getattr(rec, "success", False)):
            stat.successes += 1
    return stats


def _select_candidate(
    stats: Dict[str, StrategyStat],
    current_strategy: str,
    min_samples: int,
    margin: float,
    cold_start_floor: float,
) -> Tuple[Optional[StrategyStat], str]:
    """Pick the qualifying strategy that beats *current* by *margin*.

    Returns ``(candidate_or_None, reason)``.
    """
    qualifying = [s for s in stats.values() if s.qualifies(min_samples)]
    if not qualifying:
        return None, f"no strategy reached min_samples={min_samples}"

    current_stat = stats.get(current_strategy)

    # Deterministic ordering: rate desc, then sample count desc, then name asc.
    # Without the tie-breakers, two equally-rated strategies would be chosen by
    # dict insertion order — i.e. by history, not by evidence.
    best = sorted(qualifying, key=lambda s: (-s.rate, -s.total, s.strategy))[0]

    if best.strategy == current_strategy:
        return None, "current strategy is already the best-performing option"

    if current_stat is not None and current_stat.qualifies(min_samples):
        if best.rate > current_stat.rate + margin:
            return best, (
                f"{best.strategy} {best.rate:.2f} (n={best.total}) beats "
                f"{current_strategy} {current_stat.rate:.2f} (n={current_stat.total}) "
                f"by more than margin={margin}"
            )
        return None, (
            f"{best.strategy} {best.rate:.2f} does not beat "
            f"{current_strategy} {current_stat.rate:.2f} by margin={margin}"
        )

    # Cold start: current strategy has no trustworthy history of its own.
    if best.rate >= cold_start_floor:
        return best, (
            f"{current_strategy or '(none)'} has no qualifying samples; "
            f"{best.strategy} {best.rate:.2f} (n={best.total}) clears "
            f"cold-start floor={cold_start_floor}"
        )
    return None, (
        f"{current_strategy or '(none)'} has no qualifying samples and "
        f"{best.strategy} {best.rate:.2f} is below cold-start floor={cold_start_floor}"
    )


def derive_experience_guidance(
    message: str,
    current_strategy: str,
    *,
    task_type: str = "",
    min_samples: int = DEFAULT_MIN_SAMPLES,
    margin: float = DEFAULT_MARGIN,
    cold_start_floor: float = DEFAULT_COLD_START_FLOOR,
    memory: Optional[Any] = None,
) -> ExperienceGuidance:
    """Derive strategy guidance from exact task-execution history.

    This is a **synchronous, CPU-bound** call (BM25 ranking over in-memory
    records).  Async callers must offload it — see
    ``ExecutionPlanner.execute()``, which wraps it in ``asyncio.to_thread``.

    Args:
        message:          Current task text; scopes the population via BM25.
        current_strategy: Strategy selection has already produced.
        task_type:        Optional type filter used when widening the scope.
        min_samples:      Minimum executions before a rate is trusted.
        margin:           Required advantage over the current strategy.
        cold_start_floor: Absolute rate required when current has no samples.
        memory:           Injectable TaskMemory (tests); defaults to the singleton.

    Returns:
        An :class:`ExperienceGuidance`.  Never raises — any failure degrades to
        a neutral guidance, because a statistics failure must not break task
        execution.
    """
    mode = get_experience_guidance_mode()
    if mode == MODE_OFF:
        return _neutral(mode, "experience guidance disabled", current_strategy)

    if not message:
        return _neutral(mode, "empty message — no scope to aggregate over", current_strategy)

    try:
        if memory is None:
            from core.task_memory import get_task_memory

            memory = get_task_memory()

        records, scope_kind = _scoped_records(memory, message, task_type, min_samples)
        if not records:
            return _neutral(mode, "no historical task records", current_strategy)

        stats = _aggregate(records)
        if not stats:
            return _neutral(mode, "no records carry a strategy field", current_strategy, scope_size=len(records))

        candidate, reason = _select_candidate(stats, current_strategy, min_samples, margin, cold_start_floor)

        current_stat = stats.get(current_strategy, StrategyStat(strategy=current_strategy))
        ordered_stats = sorted(stats.values(), key=lambda s: (-s.rate, -s.total, s.strategy))

        guidance = ExperienceGuidance(
            current_strategy=current_strategy,
            current_rate=current_stat.rate,
            current_n=current_stat.total,
            scope_size=len(records),
            mode=mode,
            # The scope label travels with the reason: a rate means nothing
            # without knowing which population it was computed over.
            diagnostic_note=f"[scope={scope_kind}] {reason}",
            stats=ordered_stats,
        )

        if candidate is not None:
            guidance.candidate_strategy = candidate.strategy
            guidance.candidate_rate = candidate.rate
            guidance.candidate_n = candidate.total
            # MODE_SHADOW computes everything but never influences selection.
            guidance.influenced_by_experience = mode == MODE_ON
            if mode == MODE_SHADOW:
                logger.info(
                    "ExperienceGuidance[shadow]: would switch %s → %s (%s)",
                    current_strategy,
                    candidate.strategy,
                    reason,
                )
            else:
                logger.info(
                    "ExperienceGuidance: %s → %s (%s)",
                    current_strategy,
                    candidate.strategy,
                    reason,
                )

        _note_outcome(guidance)
        return guidance

    except Exception as exc:  # noqa: BLE001 — statistics must never break execution
        logger.debug("derive_experience_guidance failed, returning neutral: %s", exc)
        return _neutral(mode, f"derivation failed: {exc}", current_strategy)


def build_experience_guidance_diagnostics(
    guidance: Optional[ExperienceGuidance],
    *,
    applied: bool = False,
) -> Dict[str, Any]:
    """Build an observability payload for an experience guidance decision.

    Never raises on bad input — diagnostics must not be able to break a request.
    """
    if guidance is None:
        return {
            "influenced_by_experience": False,
            "applied": False,
            "mode": get_experience_guidance_mode(),
            "diagnostic_note": "no guidance derived",
        }
    try:
        payload = guidance.to_dict()
        payload["applied"] = bool(applied)
        return payload
    except Exception as exc:  # noqa: BLE001
        return {
            "influenced_by_experience": False,
            "applied": False,
            "diagnostic_note": f"diagnostics failed: {exc}",
        }
