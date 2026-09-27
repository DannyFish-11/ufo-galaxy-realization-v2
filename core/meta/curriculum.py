"""core/meta/curriculum.py — 横轴：选最有信息量的下一次练习（M7）。

阶段一 Model-RSI 不开写，六个有序算子对里只剩 D → H 与 H → D，横轴退化成「下一轮跑哪个
算子」这一个二选一 —— 这正是 Curriculum 要学的东西（设计规格 §05B）。

它怎么选
========
1. **没有材料的不选**：一个算子采集不到信号（Harness 没有待验证的提案，Data 没有轨迹），跑它
   是空转；Data-RSI 的轨迹若早于最近一次 model 生效（M→D），跑它会被 Kernel 拒，同样不选。
2. **没试过的先试**：一轮都没跑过的算子，统计表对它什么都说不出，先给它一轮。
3. **其余按 UCB**：``trusted / rounds + sqrt(2 ln N / rounds)`` —— 前一项是这个算子的补丁拿到
   trusted 裁决的频率，后一项是「试得越少越值得再试」。确定性、可复算，平局按名字。

这是**调度统计**，不是裁决：补丁生不生效永远只看四值 verdict（G7）。这里的数只决定下一轮
先练哪一个。

可审计
======
每次选择落成一件 ``task`` artifact（产生者 ``kernel``）：候选、每个候选的统计与指标、没被选的
原因、选中的理由都在 payload 里 —— 「上一轮为什么选了这个」随时答得上来
（``scripts/meta_rsi.py curriculum --history``）。

纵轴启动条件
============
设计规格定了三条同时成立才碰纵轴（让元层改元层自己）：① 横轴跑满两个算子版本；
② Curriculum 的选择相对随机基线有可测增益；③ 单轮验证成本压在 L0/L1 档。:func:`vertical_axis_readiness`
把三条逐条算出来，只报事实，不替人开闸。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

from core.meta.artifacts import create_artifact
from core.meta.kernel import freshness_violation
from core.meta.store import ArtifactStore

#: 阶段一可写的算子（model_rsi 不开写，不进横轴）。
HORIZONTAL_ARMS: Tuple[str, ...] = ("data_rsi", "harness_rsi")
_TRUSTED_OUTCOMES = ("committed", "shadow")
_CHEAP_LEVELS = ("L0", "L1")


@dataclass
class ArmStats:
    operator: str
    rounds: int = 0
    trusted: int = 0
    outcomes: Dict[str, int] = field(default_factory=dict)
    versions: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operator": self.operator,
            "rounds": self.rounds,
            "trusted": self.trusted,
            "outcomes": dict(self.outcomes),
            "versions": list(self.versions),
        }


def arm_table(store: ArtifactStore) -> Dict[str, ArmStats]:
    """从存储里的 patch 与 lesson 数出每个算子的历史。只数，不读任何文本。"""
    table = {name: ArmStats(name) for name in HORIZONTAL_ARMS}
    outcome_of: Dict[str, str] = {}
    for lesson in store.list("lesson"):
        parents = lesson.lineage.parents
        if lesson.lineage.operator == "kernel" and parents:
            outcome_of[parents[0]] = str(lesson.payload.get("outcome", ""))
    versions: Dict[str, set] = {name: set() for name in HORIZONTAL_ARMS}
    for patch in store.list("patch"):
        stats = table.get(str(patch.lineage.operator))
        if stats is None:
            continue
        outcome = outcome_of.get(patch.artifact_id, "pending")
        stats.rounds += 1
        stats.outcomes[outcome] = stats.outcomes.get(outcome, 0) + 1
        stats.trusted += outcome in _TRUSTED_OUTCOMES
        versions[stats.operator].add(str(patch.lineage.operator_version or ""))
    for name, stats in table.items():
        stats.versions = tuple(sorted(v for v in versions[name] if v))
    return table


def _ucb(stats: ArmStats, total_rounds: int) -> float:
    return stats.trusted / stats.rounds + math.sqrt(2.0 * math.log(max(total_rounds, 1)) / stats.rounds)


@dataclass
class CurriculumChoice:
    operator: Optional[str]
    reason: str
    candidates: Dict[str, Dict[str, Any]]
    task_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operator": self.operator,
            "reason": self.reason,
            "candidates": self.candidates,
            "task_id": self.task_id,
        }


def choose_next(
    store: ArtifactStore, operators: Mapping[str, Any], *, record: bool = True
) -> Tuple[CurriculumChoice, Dict[str, Any]]:
    """选下一轮跑哪个算子。返回选择与各算子已采集的信号（选中的那个直接拿去跑，不重采）。"""
    table = arm_table(store)
    total = sum(s.rounds for s in table.values())
    candidates: Dict[str, Dict[str, Any]] = {}
    signals: Dict[str, Any] = {}
    eligible: List[Tuple[Tuple[int, float, str], str]] = []
    for name in HORIZONTAL_ARMS:
        op = operators.get(name)
        row: Dict[str, Any] = table[name].to_dict()
        candidates[name] = row
        if op is None:
            row["skipped"] = "未登记"
            continue
        bundle = op.collect(store)
        signals[name] = bundle
        if not bundle.ids:
            row["skipped"] = "没有材料：采集不到信号，跑它是空转"
            continue
        stale = freshness_violation(op.scope, bundle, store)
        if stale:
            row["skipped"] = f"信号不新鲜：{stale}"
            continue
        row["material"] = len(bundle.ids)
        if table[name].rounds == 0:
            row["index"] = None
            key = (0, 0.0, name)  # 没试过的先试
        else:
            row["index"] = round(_ucb(table[name], total), 6)
            key = (1, -row["index"], name)
        eligible.append((key, name))

    if not eligible:
        choice = CurriculumChoice(None, "没有一个算子有可用的新鲜材料，这一轮不跑", candidates)
    else:
        (tier, _neg, _), chosen = min(eligible)
        reason = (
            "从没跑过，统计表对它说不出任何东西，先给它一轮"
            if tier == 0
            else f"UCB 指数最高（{candidates[chosen]['index']}）：trusted 频率与「试得少」两项之和"
        )
        choice = CurriculumChoice(chosen, reason, candidates)
    if record:
        task = create_artifact(
            "task",
            {"kind": "curriculum_choice", **{k: v for k, v in choice.to_dict().items() if k != "task_id"}},
            operator="kernel",
        )
        choice.task_id = store.put(task)
    return choice, signals


def choice_history(store: ArtifactStore, limit: int = 10) -> List[Dict[str, Any]]:
    tasks = [a for a in store.list("task") if a.payload.get("kind") == "curriculum_choice"]
    return [{"task_id": a.artifact_id, "at": a.created_at, **a.payload} for a in tasks[-limit:]]


def vertical_axis_readiness(store: ArtifactStore) -> Dict[str, Any]:
    """纵轴的三条启动条件，逐条如实报出。"""
    table = arm_table(store)
    versions_ok = all(len(table[name].versions) >= 2 for name in HORIZONTAL_ARMS)

    rounds = sum(s.rounds for s in table.values())
    trusted = sum(s.trusted for s in table.values())
    chosen = [h["operator"] for h in choice_history(store, limit=10_000) if h.get("operator")]
    # 随机基线：均匀随机选算子时的期望 trusted 频率 = 各算子 trusted 频率的平均。
    per_arm = [s.trusted / s.rounds for s in table.values() if s.rounds]
    baseline = sum(per_arm) / len(per_arm) if per_arm else None
    observed = trusted / rounds if rounds else None
    gain_ok = bool(chosen) and baseline is not None and observed is not None and observed > baseline

    levels = [str(p.payload.get("verify_level", "")) for p in store.list("patch")]
    cheap_ok = bool(levels) and all(level in _CHEAP_LEVELS for level in levels)
    return {
        "ready": versions_ok and gain_ok and cheap_ok,
        "conditions": {
            "horizontal_two_versions": {
                "met": versions_ok,
                "versions": {n: list(table[n].versions) for n in HORIZONTAL_ARMS},
            },
            "curriculum_beats_random": {
                "met": gain_ok,
                "observed_trusted_rate": observed,
                "uniform_random_baseline": baseline,
                "curriculum_rounds": len(chosen),
            },
            "verification_is_cheap": {"met": cheap_ok, "levels_used": sorted(set(levels))},
        },
    }


__all__ = [
    "HORIZONTAL_ARMS",
    "ArmStats",
    "CurriculumChoice",
    "arm_table",
    "choice_history",
    "choose_next",
    "vertical_axis_readiness",
]
