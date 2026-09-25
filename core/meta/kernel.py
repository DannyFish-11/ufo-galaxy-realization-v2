"""core/meta/kernel.py — Loop Kernel：一个骨架，三个算子都必须实例化它。

论文的定义：一个**被学习信号闭合**、并**被权威边界切过一次**的循环。两个词都是结构要求：
闭合 = 产出回流成下一轮输入；切一次 = 循环里恰好有一处不由循环自己决定 —— 那一刀就是裁决。

五个阶段
========
::

    1 采集  → task · trace          （SignalBundle，由调用方或 M6 的轨迹采集给出）
    2 提案  → patch                 （算子；只能写自己的那一个可写面）
    3 验证  → score                 （验证器；在隔离工作区里跑，提案者写不了）
    4 裁决  → verdict               （权威边界；四值 EvidenceTrustLevel，不是分数） ← 唯一的那一刀
    5 生效或回滚 → lesson            （只有 trusted 且档位为 on 才落到真实目录；lesson 回流）

算子之间的区别只在**写什么**，不在怎么跑、怎么验、怎么审计。

硬约束（全部可机械检查）
========================
* **G4 无回滚句柄不受理** —— 补丁的每一处改动都带着改动前的内容；patch artifact 缺
  ``rollback`` 即构造失败（:func:`core.meta.artifacts.validate_artifact`）。
* **G5 单一可写面** —— 补丁的 scope 必须等于算子的 scope；改动路径必须落在该 scope 的
  可写面内（:data:`WRITABLE_SURFACES`）。
* **G6 算子不得改验证器** —— 任何 scope 都写不了 :data:`VERIFIER_SURFACES`（守卫门、测试、
  打分逻辑、执法函数、元层自身）。静态一侧由 :mod:`core.meta.guards` 钉住两张表不相交。
* **G7 只有 trusted 生效** —— provisional 留证但不生效。
* **G8 三态灰度** —— off 拒绝运行；shadow 全程只在隔离工作区里验证，永不生效。
* **新鲜度（M→D）** —— Data-RSI 读的是当前模型的轨迹。Model-RSI 一旦生效，此前的轨迹
  描述的都是不存在的旧模型：Data-RSI 提案时其 trace 必须晚于最近一次 model 可写面的生效。
  六个有序算子对里只有这一对不成立（规格 §05 的推导）。

隔离
====
验证在一个临时的 ``git worktree``（HEAD）里跑：补丁先落在那里，验证器的子进程也以那里
为工作目录。正在运行的代码树在裁决之前一个字节都不会动。仓库不是 git 检出时拒绝运行
（无法隔离就不验证，而不是在活树上试）。
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, Sequence, Tuple

from core.execution_evidence_model import EvidenceTrustLevel, classify_execution_evidence
from core.meta import meta_rsi_mode
from core.meta.artifacts import Artifact, create_artifact
from core.meta.store import ArtifactStore

logger = logging.getLogger("Galaxy.Meta.Kernel")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

LOOP_KERNEL_IS_CUT_ONCE: str = (
    "META_KERNEL::CLOSED_BY_SIGNAL_CUT_ONCE_BY_AUTHORITY: core/meta/kernel.py runs "
    "collect → propose → verify → adjudicate → commit/rollback.  The only step the "
    "loop does not decide for itself is adjudication: classify_execution_evidence() "
    "turns the verifier's observations into a four-valued verdict.  Only 'trusted' "
    "in mode 'on' reaches the live tree."
)

#: 算子名 → 它唯一的可写面。
OPERATOR_SCOPES: Dict[str, str] = {"data_rsi": "data", "harness_rsi": "harness", "model_rsi": "model"}

#: 每个可写面能写的路径前缀（G5）。Model-RSI 阶段一不开写：没有训练栈，且权重加载路径
#: 绕过了 core/execution_isolation（见 core/weights_admission.py 文件头）。
WRITABLE_SURFACES: Dict[str, Tuple[str, ...]] = {
    "data": ("config/eval_cases/", "config/assessment_claims.json"),
    "harness": ("config/genomes/",),
    "model": (),
}

#: 验证器所在之处：任何可写面都不得触碰（G6）。
VERIFIER_SURFACES: Tuple[str, ...] = (
    "scripts/",
    "tests/",
    ".github/",
    "core/eval/scorer.py",
    "core/eval/runner.py",
    "core/execution_evidence_model.py",
    "core/engineering_verification.py",
    "core/verification_ladder.py",
    "core/verdict_independence.py",
    "core/assessment_freshness.py",
    "core/meta/",
)

#: 验证默认跑到阶梯的哪一档（见 core.verification_ladder）。
DEFAULT_VERIFY_LEVEL = "L1"


# ---------------------------------------------------------------------------
# 补丁
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FileChange:
    """一处文件改动。``before`` 就是回滚句柄：``None`` 表示文件原本不存在。"""

    path: str
    before: Optional[str]
    after: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "before_sha256": _sha(self.before),
            "after_sha256": _sha(self.after),
            "after": self.after,
        }


@dataclass(frozen=True)
class PatchProposal:
    """算子的产出：一处改动 + 回滚句柄 + 理由。"""

    scope: str
    slot: str
    changes: Tuple[FileChange, ...]
    rationale: str
    parents: Tuple[str, ...] = ()
    verify_level: str = DEFAULT_VERIFY_LEVEL

    def payload(self) -> Dict[str, Any]:
        return {
            "scope": self.scope,
            "slot": self.slot,
            "rationale": self.rationale,
            "verify_level": self.verify_level,
            "changes": [c.to_dict() for c in self.changes],
            "rollback": {"kind": "restore_files", "files": {c.path: c.before for c in self.changes}},
        }


@dataclass(frozen=True)
class SignalBundle:
    """采集阶段的产出：本轮算子读的 task / trace / lesson。"""

    tasks: Tuple[Artifact, ...] = ()
    traces: Tuple[Artifact, ...] = ()
    lessons: Tuple[Artifact, ...] = ()

    @property
    def ids(self) -> Tuple[str, ...]:
        return tuple(a.artifact_id for a in self.tasks + self.traces + self.lessons)


class RSIOperator(Protocol):
    """算子协议。``name`` 必须是 data_rsi / harness_rsi / model_rsi 之一，``scope`` 与之对应。"""

    name: str
    scope: str
    version: str

    def propose(self, signals: SignalBundle) -> List[PatchProposal]: ...


def _sha(text: Optional[str]) -> Optional[str]:
    return None if text is None else hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# 可写面检查（G5 / G6）
# ---------------------------------------------------------------------------


def _normalize(path: str) -> str:
    text = path.replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text


def write_surface_violation(scope: str, paths: Sequence[str]) -> str:
    """补丁的改动路径是否越过了这个 scope 的可写面；越界返回原因，合法返回空串。"""
    if scope not in WRITABLE_SURFACES:
        return f"未知的可写面 {scope!r}"
    allowed = WRITABLE_SURFACES[scope]
    if not allowed:
        return f"{scope} 可写面阶段一不开写"
    for raw in paths:
        path = _normalize(raw)
        if not path or path.startswith("/") or ".." in path.split("/"):
            return f"路径不合法：{raw!r}"
        if any(path == v.rstrip("/") or path.startswith(v) for v in VERIFIER_SURFACES):
            return f"{path} 属于验证器 —— 算子不得改判卷标准（G6）"
        if not any(path == a.rstrip("/") or path.startswith(a) for a in allowed):
            return f"{path} 不在 {scope} 的可写面 {allowed} 内（G5）"
        if _read_only_genome_component(path):
            return f"{path} 是 Genome 的只读格 —— 阶段一「谁能想什么」不开写（设计规格 §04F）"
    return ""


def _read_only_genome_component(path: str) -> bool:
    from core.genome import READ_ONLY_COMPONENTS

    parts = path.split("/")
    return (
        len(parts) == 5
        and parts[:2] == ["config", "genomes"]
        and parts[3] == "components"
        and parts[4].rsplit(".", 1)[0] in READ_ONLY_COMPONENTS
    )


# ---------------------------------------------------------------------------
# 隔离工作区
# ---------------------------------------------------------------------------


class SandboxUnavailable(RuntimeError):
    """无法建立隔离工作区（例如不是 git 检出）。"""


def _mirror_writable_surfaces(live_root: Path, sandbox_root: Path) -> None:
    """把活树上算子可写面的**当前**内容镜像进工作区。

    工作区取自 HEAD，而此前生效的补丁写在活树上、未必进了 git。不镜像的话，下一个补丁
    的「改动前内容」在工作区里对不上，一律被判为过期 —— 循环就只能跑一轮。
    """
    for prefix in {p for prefixes in WRITABLE_SURFACES.values() for p in prefixes}:
        live, mirror = live_root / prefix, sandbox_root / prefix
        if prefix.endswith("/"):
            if mirror.exists():
                shutil.rmtree(mirror)
            if live.is_dir():
                shutil.copytree(live, mirror, ignore=shutil.ignore_patterns("__pycache__"))
        elif live.is_file():
            mirror.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(live, mirror)
        elif mirror.exists():
            mirror.unlink()


class GitWorktreeSandbox:
    """HEAD 的一个临时 git worktree。补丁先落在这里，验证也在这里跑。"""

    def __init__(self, repo_root: Path = REPO_ROOT) -> None:
        self.repo_root = repo_root
        self.path: Optional[Path] = None

    def __enter__(self) -> "GitWorktreeSandbox":
        base = Path(tempfile.mkdtemp(prefix="galaxy-meta-sandbox-"))
        target = base / "tree"
        proc = subprocess.run(
            ["git", "worktree", "add", "--detach", str(target), "HEAD"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if proc.returncode != 0:
            shutil.rmtree(base, ignore_errors=True)
            raise SandboxUnavailable(f"无法建立隔离工作区：{proc.stderr.strip() or proc.stdout.strip()}")
        self.path = target
        _mirror_writable_surfaces(self.repo_root, target)
        return self

    def __exit__(self, *exc: Any) -> None:
        if self.path is None:
            return
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(self.path)],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        shutil.rmtree(self.path.parent, ignore_errors=True)
        self.path = None


def apply_changes(root: Path, changes: Sequence[FileChange]) -> str:
    """把改动落到 *root* 下；落之前核对每个文件当前内容等于 ``before``。

    核对不过返回原因、且一个文件都不写 —— 补丁是基于旧内容算的，照写就是覆盖别人的改动。
    """
    for change in changes:
        target = root / _normalize(change.path)
        current = target.read_text(encoding="utf-8") if target.is_file() else None
        if current != change.before:
            return f"{change.path} 的当前内容与补丁记录的改动前内容不一致 —— 补丁已过期"
    for change in changes:
        target = root / _normalize(change.path)
        if change.after is None:
            if target.is_file():
                target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(change.after, encoding="utf-8")
    return ""


# ---------------------------------------------------------------------------
# 验证器与权威边界
# ---------------------------------------------------------------------------


class LadderVerifier:
    """默认验证器：在隔离工作区里按改动路径跑验证阶梯的某一档。只产出观测。"""

    def run(self, proposal: PatchProposal, workspace: Path) -> List[Any]:
        from core.engineering_verification import verify

        return verify(
            f"ladder:{proposal.verify_level}",
            target_files=[c.path for c in proposal.changes],
            proposal_id=f"meta-{uuid.uuid4().hex[:12]}",
            cwd=workspace,
        )


class EvidenceAuthority:
    """默认权威边界：观测 → 证据状态 → classify_execution_evidence()。四值，不是分数。"""

    def adjudicate(self, observations: Sequence[Any]) -> Tuple[EvidenceTrustLevel, str, bool]:
        from core.engineering_verification import evidence_for

        state, complete, _ = evidence_for(observations)
        return classify_execution_evidence(state, truth_chain_complete=complete), state.value, complete


# ---------------------------------------------------------------------------
# 一轮循环
# ---------------------------------------------------------------------------


@dataclass
class PatchOutcome:
    patch_id: str
    outcome: str
    reason: str = ""
    score_id: str = ""
    verdict_id: str = ""
    lesson_id: str = ""
    level: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class CycleReport:
    mode: str
    operator: str
    status: str
    reason: str = ""
    outcomes: List[PatchOutcome] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "operator": self.operator,
            "status": self.status,
            "reason": self.reason,
            "outcomes": [o.to_dict() for o in self.outcomes],
        }


def freshness_violation(operator_scope: str, signals: SignalBundle, store: ArtifactStore) -> str:
    """M→D：Data-RSI 读的轨迹必须晚于最近一次 model 可写面的生效。"""
    if operator_scope != "data":
        return ""
    last_model = store.last_commit_at("model")
    if not last_model:
        return ""
    stale = [t.artifact_id for t in signals.traces if t.created_at < last_model]
    if stale:
        return (
            f"{len(stale)} 条轨迹早于最近一次 model 生效（{last_model}）—— 它们描述的是已经不存在的旧模型，"
            "Data-RSI 必须先重采集（M→D 是六个有序对里唯一不成立的那一对）"
        )
    return ""


def _stale_claims() -> List[str]:
    """R9：当前过期的结论 id。问不出来时返回空表并告警（不把"没问"当成"都新鲜"去比）。"""
    try:
        from core.assessment_freshness import freshness_report

        return list(freshness_report().get("stale") or [])
    except Exception as exc:  # noqa: BLE001
        logger.warning("结论保鲜复验失败，本次生效不比对: %s", exc)
        return []


def _lesson(
    store: ArtifactStore,
    proposal: PatchProposal,
    parents: Tuple[str, ...],
    outcome: str,
    reason: str,
    level: str,
    stale_claims: Sequence[str] = (),
) -> str:
    lesson = create_artifact(
        "lesson",
        {
            "stale_claims": list(stale_claims),
            "hypothesis": proposal.rationale,
            "preconditions": {
                "scope": proposal.scope,
                "slot": proposal.slot,
                "paths": [c.path for c in proposal.changes],
                "verify_level": proposal.verify_level,
            },
            "outcome": outcome,
            "reason": reason,
            "level": level,
        },
        parents=parents,
        operator="kernel",
    )
    return store.put(lesson)


def run_cycle(
    operator: RSIOperator,
    signals: SignalBundle,
    *,
    store: Optional[ArtifactStore] = None,
    verifier: Optional[Any] = None,
    authority: Optional[Any] = None,
    mode: Optional[str] = None,
    sandbox_factory: Optional[Callable[[], Any]] = None,
    live_root: Path = REPO_ROOT,
    stale_claims: Optional[Callable[[], List[str]]] = None,
) -> CycleReport:
    """跑一轮：采集（给定）→ 提案 → 验证 → 裁决 → 生效或回滚 → lesson。

    ``stale_claims``：生效前后各问一次「哪些结论过期了」，差集记进 lesson（R9：能力改了，系统对
    自己的描述随之失效，这要自己报出来）。缺省在活树就是本仓库时用
    :func:`core.assessment_freshness.freshness_report`，否则不比对。
    """
    mode = mode or meta_rsi_mode()
    name = getattr(operator, "name", "")
    report = CycleReport(mode=mode, operator=name, status="ok")
    if mode == "off":
        report.status, report.reason = "disabled", "GALAXY_META_RSI=off：元层不运行"
        return report
    if OPERATOR_SCOPES.get(name) != getattr(operator, "scope", None):
        report.status, report.reason = "rejected", f"算子 {name!r} 与作用域 {getattr(operator, 'scope', None)!r} 不匹配"
        return report

    store = store or ArtifactStore()
    verifier = verifier or LadderVerifier()
    authority = authority or EvidenceAuthority()
    sandbox_factory = sandbox_factory or GitWorktreeSandbox
    if stale_claims is None and live_root == REPO_ROOT:
        stale_claims = _stale_claims

    stale = freshness_violation(operator.scope, signals, store)
    if stale:
        report.status, report.reason = "stale_signals", stale
        return report

    for proposal in operator.propose(signals):  # 2 提案
        paths = [c.path for c in proposal.changes]
        violation = ""
        if proposal.scope != operator.scope:
            violation = f"补丁作用域 {proposal.scope!r} ≠ 算子作用域 {operator.scope!r}：越界写入（G5）"
        elif not proposal.changes:
            violation = "空补丁"
        else:
            violation = write_surface_violation(operator.scope, paths)
        parents = tuple(proposal.parents) or signals.ids
        patch = create_artifact(
            "patch",
            proposal.payload(),
            parents=parents,
            operator=name,
            operator_version=getattr(operator, "version", None),
        )
        patch_id = store.put(patch)
        if violation:
            lesson_id = _lesson(store, proposal, (patch_id,), "rejected", violation, "")
            report.outcomes.append(PatchOutcome(patch_id, "rejected", violation, lesson_id=lesson_id))
            continue

        # 3 验证：在隔离工作区里落补丁、跑验证器。活树此时一个字节都没动。
        try:
            with sandbox_factory() as sandbox:
                if sandbox.path is None:
                    raise SandboxUnavailable("隔离工作区没有建立")
                workspace = Path(sandbox.path)
                stale_reason = apply_changes(workspace, proposal.changes)
                observations = [] if stale_reason else verifier.run(proposal, workspace)
        except SandboxUnavailable as exc:
            lesson_id = _lesson(store, proposal, (patch_id,), "unverifiable", str(exc), "")
            report.outcomes.append(PatchOutcome(patch_id, "unverifiable", str(exc), lesson_id=lesson_id))
            continue
        if stale_reason:
            lesson_id = _lesson(store, proposal, (patch_id,), "stale_patch", stale_reason, "")
            report.outcomes.append(PatchOutcome(patch_id, "stale_patch", stale_reason, lesson_id=lesson_id))
            continue

        archive_refs = tuple(o.evidence_ref for o in observations if getattr(o, "evidence_ref", ""))
        score = create_artifact(
            "score",
            {"observations": [o.to_dict() for o in observations], "verify_level": proposal.verify_level},
            parents=(patch_id,),
            operator="verifier",
            evidence=archive_refs,
        )
        score_id = store.put(score)

        # 4 裁决：唯一的那一刀。
        level, evidence_state, chain_complete = authority.adjudicate(observations)
        verdict = create_artifact(
            "verdict",
            {
                "level": level.value,
                "evidence_state": evidence_state,
                "truth_chain_complete": chain_complete,
                "mode": mode,
            },
            parents=(patch_id, score_id),
            operator="authority",
            evidence=(score_id,) + archive_refs,
        )
        verdict_id = store.put(verdict)

        # 5 生效或回滚。
        newly_stale: List[str] = []
        if level is not EvidenceTrustLevel.trusted:
            outcome, reason = "rolled_back", f"裁决为 {level.value}，不生效（G7）"
        elif mode != "on":
            outcome, reason = "shadow", "shadow 档：裁决为 trusted，但永不生效"
        else:
            stale_before = set(stale_claims()) if stale_claims else set()
            live_reason = apply_changes(live_root, proposal.changes)
            if live_reason:
                outcome, reason = "stale_patch", live_reason
            else:
                store.record_commit(proposal.scope, patch_id, verdict_id, _now())
                outcome, reason = "committed", "trusted，已生效"
                newly_stale = sorted(set(stale_claims()) - stale_before) if stale_claims else []
                if newly_stale:
                    reason += f"；因此失效、需要人重新推导的结论：{', '.join(newly_stale)}"
        lesson_id = _lesson(store, proposal, (patch_id, verdict_id), outcome, reason, level.value, newly_stale)
        report.outcomes.append(PatchOutcome(patch_id, outcome, reason, score_id, verdict_id, lesson_id, level.value))
        logger.info("元层循环 | operator=%s patch=%s level=%s outcome=%s", name, patch_id, level.value, outcome)
    return report


def revert_patch(patch_id: str, *, store: Optional[ArtifactStore] = None, live_root: Path = REPO_ROOT) -> str:
    """整包回退一个已生效的补丁：把每个文件恢复成改动前的内容。返回原因，成功返回空串。

    只在文件当前内容仍等于补丁写入的内容时才回退 —— 之后又被改过的文件不动，免得覆盖别人的改动。
    """
    store = store or ArtifactStore()
    patch = store.get(patch_id)
    if patch is None or patch.artifact_type != "patch":
        return f"找不到补丁 {patch_id}"
    changes = patch.payload.get("changes") or []
    restore = (patch.payload.get("rollback") or {}).get("files") or {}
    reverse = [FileChange(path=c["path"], before=c.get("after"), after=restore.get(c["path"])) for c in changes]
    reason = apply_changes(live_root, reverse)
    if not reason:
        store.record_commit(str(patch.payload.get("scope", "")), patch_id, f"revert:{patch_id}", _now())
    return reason


__all__ = [
    "DEFAULT_VERIFY_LEVEL",
    "LOOP_KERNEL_IS_CUT_ONCE",
    "OPERATOR_SCOPES",
    "VERIFIER_SURFACES",
    "WRITABLE_SURFACES",
    "CycleReport",
    "EvidenceAuthority",
    "FileChange",
    "GitWorktreeSandbox",
    "LadderVerifier",
    "PatchOutcome",
    "PatchProposal",
    "RSIOperator",
    "SandboxUnavailable",
    "SignalBundle",
    "apply_changes",
    "freshness_violation",
    "revert_patch",
    "run_cycle",
    "write_surface_violation",
]
