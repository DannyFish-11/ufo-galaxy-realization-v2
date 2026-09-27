"""core/meta/operators/harness_rsi.py — Harness-RSI：编辑脚手架，不碰权重。

可写面只有 ``config/genomes/``（:data:`core.meta.kernel.WRITABLE_SURFACES`），而且阶段一
只写 ``instructions`` 一格 —— ``model`` 一格只读（Kernel 在可写面检查里拒绝）。

它从哪儿拿提案
==============
算子读的是 lesson 型 artifact 里 ``kind == "harness_proposal"`` 的那些：一条带前置条件的
操作性假设，「把 instructions 的某个字段换成这个值，会更好」。提案可以由人
（``scripts/meta_rsi.py propose``）或由元层自己的供给通道（设计规格 §04H）写进存储；算子
不关心来源，只关心它是不是一条合法的、还没被消费过的提案。

它写什么
========
**从不改 ``default``。** 默认 Genome 钉着「与原先硬编码逐字节一致」（G9），改它等于让那条
回归测试永远红。算子写的是一份进化 Genome ``config/genomes/rsi/``：

* ``base: "default"`` —— 继承式合并（G1），只声明被改的那一格；
* ``parent_id`` 指向改动前的内容 id，``version`` 单调递增（G11）；
* 生效即写指针 ``config/genomes/active.json``；环境变量 ``GALAXY_GENOME`` 永远压过指针（G3）。

回滚是 Kernel 的事：补丁带着每个文件的改动前内容，``revert_patch`` 整包恢复。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.genome import ACTIVE_POINTER, DEFAULT_GENOME, GENOME_SCHEMA_VERSION, GenomeError, load_genome, merge_overrides
from core.meta.artifacts import Artifact
from core.meta.kernel import REPO_ROOT, FileChange, PatchProposal, SignalBundle
from core.meta.store import ArtifactStore

PROPOSAL_KIND = "harness_proposal"
EVOLVED_GENOME = "rsi"
GENOMES_REL = "config/genomes"


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _nest(path: Sequence[str], value: Any) -> Dict[str, Any]:
    node: Any = value
    for key in reversed(path):
        node = {key: node}
    return node


def _well_formed(payload: Dict[str, Any]) -> bool:
    path = payload.get("path")
    return bool(payload.get("component")) and isinstance(path, list) and bool(path) and "value" in payload


def proposal_payload(component: str, path: Sequence[str], value: Any, rationale: str) -> Dict[str, Any]:
    """一条 Harness 提案的 lesson 载荷。``value`` 为 ``None`` 表示删除该键（交还继承值）。"""
    return {
        "kind": PROPOSAL_KIND,
        "hypothesis": rationale,
        "preconditions": {"component": component, "path": list(path)},
        "component": component,
        "path": list(path),
        "value": value,
    }


class HarnessRSIOperator:
    name = "harness_rsi"
    scope = "harness"
    version = "1"

    def __init__(self, *, root: Path = REPO_ROOT, evolved: str = EVOLVED_GENOME) -> None:
        self.root = root
        self.evolved = evolved
        self.rejections: List[Tuple[str, str]] = []

    # -- 采集 ---------------------------------------------------------------

    def collect(self, store: ArtifactStore) -> SignalBundle:
        """还没被任何补丁消费过的 Harness 提案。"""
        consumed = {p for patch in store.list("patch") for p in patch.lineage.parents}
        pending = [
            a
            for a in store.list("lesson")
            if a.payload.get("kind") == PROPOSAL_KIND and a.artifact_id not in consumed and _well_formed(a.payload)
        ]
        return SignalBundle(lessons=tuple(sorted(pending, key=lambda a: a.created_at)))

    # -- 提案 ---------------------------------------------------------------

    def _read(self, rel: str) -> Optional[str]:
        path = self.root / rel
        return path.read_text(encoding="utf-8") if path.is_file() else None

    def _proposal(self, lesson: Artifact) -> Tuple[Optional[PatchProposal], str]:
        payload = lesson.payload
        component = str(payload.get("component") or "")
        path = [str(p) for p in payload.get("path") or []]
        # 只读格（model）照样成补丁：拒绝由 Kernel 的可写面检查作出并落 lesson，不由提案者自己判。
        genomes_root = self.root / GENOMES_REL
        try:
            parent = load_genome(
                self.evolved if (genomes_root / self.evolved).is_dir() else DEFAULT_GENOME, root=genomes_root
            )
        except GenomeError as exc:
            return None, f"当前 Genome 不合法，不在其上提案：{exc}"

        manifest_rel = f"{GENOMES_REL}/{self.evolved}/genome.json"
        component_rel = f"{GENOMES_REL}/{self.evolved}/components/{component}.json"
        pointer_rel = f"{GENOMES_REL}/{ACTIVE_POINTER}"
        manifest_before, component_before, pointer_before = map(self._read, (manifest_rel, component_rel, pointer_rel))

        # 进化 Genome 自己那一层只存差异（G1）。合并后的整体过不过契约（G2）由验证器判：
        # 验证阶梯会跑 tests/test_genome.py 里「生效中的 Genome 满足组件契约」那一条。
        own = json.loads(component_before) if component_before else {}
        own_after = merge_overrides(own, _nest(path, payload.get("value")))
        if own_after == own:
            return None, "提案与现状相同"

        manifest = (
            json.loads(manifest_before)
            if manifest_before
            else {
                "genome_schema_version": GENOME_SCHEMA_VERSION,
                "genome_id": f"galaxy:{self.evolved}",
                "base": DEFAULT_GENOME,
                "version": 0,
                "components": [],
            }
        )
        manifest["version"] = int(manifest.get("version", 0)) + 1
        manifest["parent_id"] = parent.content_id
        if not any(c.get("id") == component for c in manifest["components"]):
            manifest["components"].append({"id": component, "source": f"./components/{component}.json"})

        changes = (
            FileChange(component_rel, component_before, _dump(own_after)),
            FileChange(manifest_rel, manifest_before, _dump(manifest)),
            FileChange(pointer_rel, pointer_before, _dump({"genome": self.evolved})),
        )
        slot = f"{self.evolved}:{component}." + ".".join(path)
        rationale = str(payload.get("hypothesis") or "")
        return PatchProposal("harness", slot, changes, rationale, parents=(lesson.artifact_id,)), ""

    def propose(self, signals: SignalBundle) -> List[PatchProposal]:
        proposals: List[PatchProposal] = []
        self.rejections = []
        for lesson in signals.lessons:
            if lesson.payload.get("kind") != PROPOSAL_KIND:
                continue
            proposal, reason = self._proposal(lesson)
            if proposal is None:
                self.rejections.append((lesson.artifact_id, reason))  # 空操作与无从下手的提案：跳过，看下一条
            else:
                proposals.append(proposal)
                break  # 一轮只提一处：下一条提案要在这一处生效之后的内容上算
        return proposals


__all__ = ["EVOLVED_GENOME", "PROPOSAL_KIND", "HarnessRSIOperator", "proposal_payload"]
