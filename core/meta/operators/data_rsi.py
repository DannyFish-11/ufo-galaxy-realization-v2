"""core/meta/operators/data_rsi.py — Data-RSI：放大已有能力，并标定这能力到哪为止。

可写面：``config/eval_cases/``（与 ``config/assessment_claims.json``，阶段一不写）。打分逻辑
（``core/eval/scorer.py``）在验证器侧，算子改不了 —— 用例可由算子生成，判卷标准不行（G6）。

输入：执行轨迹，不是散文
========================
轨迹来自 ``TaskMemory`` 的 ``TaskSummary`` —— 读的是**类型化字段**（``task`` / ``success`` /
``strategy`` / ``task_type``），不读 ``result_summary`` 的文字，全程不从检索到的文本里反解结构
（:mod:`core.semantic_anchoring` 的判据；执行经验制导被重写的原因就是这一条）。

每条摘要在采集时落成一件 ``trace`` artifact，``created_at`` 取**任务发生的时刻**而非采集时刻 ——
Kernel 的 M→D 新鲜度检查比的就是它：模型可写面生效之后，旧轨迹描述的是已不存在的旧模型。

产出：确定性的回归用例与边界用例
================================
按任务文本分组，只看次数，不打分：

* 同一任务观测到至少 :data:`MIN_OBSERVATIONS` 次、**全部成功** → 回归用例（``expect_success=True``，
  tag ``capability``）：「这件事它会做」被钉住，以后退化会红；
* **全部失败** → 边界用例（``expect_success=False``，tag ``boundary``）：「这件事它目前做不到」被
  如实记下，哪天做到了，这条会红 —— 能力边界移动了，要有人看一眼；
* 有成有败 → 不出用例：不稳定的东西钉成用例，只会让用例集本身变成噪声。

用例带 ``provenance``（来源 trace 的 artifact id 与观测次数），``EvalCase.from_dict`` 忽略它，
审计时能从用例追回到轨迹。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.meta.artifacts import Artifact, create_artifact
from core.meta.kernel import REPO_ROOT, FileChange, PatchProposal, SignalBundle
from core.meta.store import ArtifactStore

CASES_REL = "config/eval_cases/trajectories.jsonl"
MIN_OBSERVATIONS = 2
MAX_TRACES = 500


def _normalize(task: str) -> str:
    return " ".join(str(task or "").split())


def _case_id(task: str) -> str:
    return "traj_" + hashlib.sha256(task.encode("utf-8")).hexdigest()[:12]


def trace_payload(summary: Any) -> Dict[str, Any]:
    """一条 TaskSummary 的类型化字段 —— 不含结果文字。"""
    return {
        "summary_id": str(getattr(summary, "summary_id", "")),
        "task": _normalize(getattr(summary, "task", "")),
        "task_type": str(getattr(summary, "task_type", "") or ""),
        "strategy": str(getattr(summary, "strategy", "") or ""),
        "success": bool(getattr(summary, "success", False)),
        "occurred_at": float(getattr(summary, "timestamp", 0.0) or 0.0),
    }


def _load_existing(text: Optional[str]) -> Dict[str, Dict[str, Any]]:
    cases: Dict[str, Dict[str, Any]] = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            item = json.loads(line)
            cases[str(item["id"])] = item
    return cases


def _dump(cases: Dict[str, Dict[str, Any]]) -> str:
    return "".join(json.dumps(cases[k], ensure_ascii=False, sort_keys=True) + "\n" for k in sorted(cases))


def cases_from_traces(traces: Sequence[Artifact]) -> Dict[str, Dict[str, Any]]:
    """确定性：同样的轨迹集合，同样的用例。"""
    groups: Dict[str, List[Artifact]] = {}
    for trace in traces:
        task = trace.payload.get("task", "")
        if task:
            groups.setdefault(task, []).append(trace)
    cases: Dict[str, Dict[str, Any]] = {}
    for task, members in groups.items():
        outcomes = {bool(t.payload.get("success")) for t in members}
        if len(members) < MIN_OBSERVATIONS or len(outcomes) != 1:
            continue
        succeeded = outcomes == {True}
        task_types = sorted({t.payload.get("task_type", "") for t in members} - {""})
        cid = _case_id(task)
        cases[cid] = {
            "id": cid,
            "prompt": task,
            "expect_success": succeeded,
            "tags": ["from_trajectory", "capability" if succeeded else "boundary", *task_types],
            "provenance": {
                "traces": sorted(t.artifact_id for t in members),
                "observations": len(members),
            },
        }
    return cases


class DataRSIOperator:
    name = "data_rsi"
    scope = "data"
    version = "1"

    def __init__(self, *, root: Path = REPO_ROOT, summaries: Optional[Sequence[Any]] = None) -> None:
        self.root = root
        self._summaries = summaries  # 测试注入；缺省读 TaskMemory

    def _read_summaries(self) -> List[Any]:
        if self._summaries is not None:
            return list(self._summaries)
        from core.task_memory import get_task_memory

        return list(get_task_memory().get_recent_summaries(n=MAX_TRACES))

    def collect(self, store: ArtifactStore) -> SignalBundle:
        traces: List[Artifact] = []
        for summary in self._read_summaries():
            payload = trace_payload(summary)
            if not payload["task"]:
                continue
            occurred = datetime.fromtimestamp(payload["occurred_at"], tz=timezone.utc).isoformat()
            trace = create_artifact("trace", payload, operator="runtime", created_at=occurred)
            if store.get(trace.artifact_id) is None:
                store.put(trace)
            traces.append(store.get(trace.artifact_id) or trace)
        return SignalBundle(traces=tuple(traces))

    def propose(self, signals: SignalBundle) -> List[PatchProposal]:
        derived = cases_from_traces(signals.traces)
        path = self.root / CASES_REL
        before = path.read_text(encoding="utf-8") if path.is_file() else None
        merged = _load_existing(before)
        changed = [cid for cid, case in derived.items() if merged.get(cid) != case]
        if not changed:
            return []
        flipped = [
            cid for cid in changed if cid in merged and merged[cid]["expect_success"] != derived[cid]["expect_success"]
        ]
        merged.update({cid: derived[cid] for cid in changed})
        rationale = f"{len(changed)} 条轨迹用例（新增 {len(changed) - len(flipped)}，能力边界移动 {len(flipped)}）"
        parents: Tuple[str, ...] = tuple(sorted({t for cid in changed for t in derived[cid]["provenance"]["traces"]}))
        return [
            PatchProposal(
                "data", "eval_cases.trajectories", (FileChange(CASES_REL, before, _dump(merged)),), rationale, parents
            )
        ]


__all__ = ["CASES_REL", "MIN_OBSERVATIONS", "DataRSIOperator", "cases_from_traces", "trace_payload"]
