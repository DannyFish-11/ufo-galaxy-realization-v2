"""core/meta/artifacts.py — 六型 artifact：task · trace · score · lesson · patch · verdict。

形状取自 ``CosmosMind-ai/rsi-harness`` 的 ``src/core/artifacts.ts``（源码实测），三个性质
原样保留：

* **内容寻址** —— ``artifact_id = f"{type}:{sha256(规范化 JSON)[:16]}"``。id 由内容算出，
  改内容必然换 id：想悄悄改一条已记录的结论，做不到。
* **lineage 是一等字段** —— 每件产物都说得出父产物是谁、哪个算子哪个版本产的。追责不靠日志。
* **evidence 是 lineage 的字段** —— 证据引用是结构字段而非散文，所以「没有 evidence 的
  verdict 不予受理」是可机械检查的（见 :func:`validate_artifact`）。

score 与 verdict 必须分开，这是整套设计的枢纽：

====== ============================= ===========================================
型     是什么                        谁能产生
====== ============================= ===========================================
task   一次待改进的作业              Kernel
trace  执行轨迹                      运行时
score  观测：退出码、失败用例、耗时  验证器（提案者不得写）
lesson 带前置条件的操作性假设        算子 / Kernel 回流
patch  一处改动 + 回滚句柄           算子
verdict 裁决：四值 EvidenceTrustLevel 只有权威边界
====== ============================= ===========================================
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

ARTIFACT_TYPES: Tuple[str, ...] = ("task", "trace", "score", "lesson", "patch", "verdict")
ARTIFACT_SCHEMA_VERSION: str = "1"

#: 算子名（lineage.operator 的合法取值）。``kernel`` / ``verifier`` / ``authority`` 是循环自身的角色。
OPERATORS: Tuple[str, ...] = ("data_rsi", "harness_rsi", "model_rsi", "kernel", "verifier", "authority", "runtime")

#: 只能由特定角色产生的型：提案者（算子）写不了 score 与 verdict。
PRODUCER_OF: Dict[str, Tuple[str, ...]] = {
    "score": ("verifier",),
    "verdict": ("authority",),
}

#: 四值裁决 —— 与 core.execution_evidence_model.EvidenceTrustLevel 同一组取值。
VERDICT_LEVELS: Tuple[str, ...] = ("trusted", "provisional", "quarantine", "rejected")


class ArtifactError(ValueError):
    """artifact 不合法：型不认得、产生者越权、verdict 没有证据……"""


@dataclass(frozen=True)
class Lineage:
    parents: Tuple[str, ...] = ()
    operator: Optional[str] = None
    operator_version: Optional[str] = None
    evidence: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "parents": list(self.parents),
            "operator": self.operator,
            "operator_version": self.operator_version,
            "evidence": list(self.evidence),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Lineage":
        return cls(
            parents=tuple(data.get("parents") or ()),
            operator=data.get("operator"),
            operator_version=data.get("operator_version"),
            evidence=tuple(data.get("evidence") or ()),
        )


@dataclass(frozen=True)
class Artifact:
    artifact_id: str
    artifact_type: str
    schema_version: str
    created_at: str
    content_hash: str
    lineage: Lineage
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type,
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "content_hash": self.content_hash,
            "lineage": self.lineage.to_dict(),
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Artifact":
        return cls(
            artifact_id=str(data["artifact_id"]),
            artifact_type=str(data["artifact_type"]),
            schema_version=str(data.get("schema_version", ARTIFACT_SCHEMA_VERSION)),
            created_at=str(data.get("created_at", "")),
            content_hash=str(data["content_hash"]),
            lineage=Lineage.from_dict(data.get("lineage") or {}),
            payload=dict(data.get("payload") or {}),
        )


def canonical_json(value: Any) -> str:
    """规范化 JSON：键排序、无多余空白、非 ASCII 原样 —— 同一内容永远得到同一串。"""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def content_hash(artifact_type: str, payload: Dict[str, Any], lineage: Lineage) -> str:
    body = {"type": artifact_type, "payload": payload, "lineage": lineage.to_dict()}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def validate_artifact(artifact_type: str, payload: Dict[str, Any], lineage: Lineage) -> None:
    """结构性检查；不合法抛 :class:`ArtifactError`。"""
    if artifact_type not in ARTIFACT_TYPES:
        raise ArtifactError(f"未知的 artifact 型 {artifact_type!r}，可选 {ARTIFACT_TYPES}")
    if lineage.operator is not None and lineage.operator not in OPERATORS:
        raise ArtifactError(f"未知的产生者 {lineage.operator!r}，可选 {OPERATORS}")
    allowed = PRODUCER_OF.get(artifact_type)
    if allowed and lineage.operator not in allowed:
        raise ArtifactError(f"{artifact_type} 只能由 {allowed} 产生，收到 {lineage.operator!r} —— 提案者不得写")
    if artifact_type == "verdict":
        if payload.get("level") not in VERDICT_LEVELS:
            raise ArtifactError(f"verdict 必须是四值之一 {VERDICT_LEVELS}，收到 {payload.get('level')!r} —— 不是分数")
        if not lineage.evidence:
            raise ArtifactError("没有 evidence 的 verdict 不予受理")
    if artifact_type == "patch" and not payload.get("rollback"):
        raise ArtifactError("没有回滚句柄的 patch 不予受理（G4）")


def create_artifact(
    artifact_type: str,
    payload: Dict[str, Any],
    *,
    parents: Tuple[str, ...] = (),
    operator: Optional[str] = None,
    operator_version: Optional[str] = None,
    evidence: Tuple[str, ...] = (),
    created_at: Optional[str] = None,
) -> Artifact:
    """造一件 artifact。id 由内容算出；不合法抛 :class:`ArtifactError`。"""
    lineage = Lineage(
        parents=tuple(parents), operator=operator, operator_version=operator_version, evidence=tuple(evidence)
    )
    validate_artifact(artifact_type, payload, lineage)
    digest = content_hash(artifact_type, payload, lineage)
    return Artifact(
        artifact_id=f"{artifact_type}:{digest[:16]}",
        artifact_type=artifact_type,
        schema_version=ARTIFACT_SCHEMA_VERSION,
        created_at=created_at or datetime.now(timezone.utc).isoformat(),
        content_hash=digest,
        lineage=lineage,
        payload=payload,
    )


def verify_integrity(artifact: Artifact) -> bool:
    """内容与 id 是否对得上 —— 被改过的 artifact 会在这里现形。"""
    digest = content_hash(artifact.artifact_type, artifact.payload, artifact.lineage)
    return digest == artifact.content_hash and artifact.artifact_id == f"{artifact.artifact_type}:{digest[:16]}"


__all__ = [
    "ARTIFACT_SCHEMA_VERSION",
    "ARTIFACT_TYPES",
    "OPERATORS",
    "PRODUCER_OF",
    "VERDICT_LEVELS",
    "Artifact",
    "ArtifactError",
    "Lineage",
    "canonical_json",
    "content_hash",
    "create_artifact",
    "validate_artifact",
    "verify_integrity",
]
