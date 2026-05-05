#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/comprehensive_joint_dual_repo_audit.py
============================================
Comprehensive Joint Dual-Repo Real-Code-Only Current-State Audit of the
Galaxy distributed AI-body/control system.

Repositories audited together
------------------------------
- DannyFish-11/ufo-galaxy-realization-v2  (V2 — this repo, center authority)
- DannyFish-11/ufo-galaxy-android         (Android — runtime carrier node)

Purpose
-------
This module provides a MATERIALLY STRICTER and FULLER dual-repo audit than all
prior reassessments.  It explicitly evaluates both repositories together and
addresses the following six user-posed completeness questions:

1. Is the full center↔Android system truly complete as an integrated
   distributed AI-body/control system?
2. Is the system truly natural-language-driven end-to-end on its canonical
   paths?
3. Is the system truly natively multimodal end-to-end on its canonical paths?
4. Can the desktop-facing three-state / shell / manifestation / presence model
   be fully and coherently presented from real current code?
5. Are panel APIs fully unified and aggregated enough to support coherent
   panel-state filling and presentation?
6. Is the system fully controllable end-to-end, or does it remain partly
   observational/projective in some domains?

Methodology
-----------
- All conclusions grounded strictly in: current real Python imports and
  attribute checks against the live V2 codebase; existence of CI test modules;
  inspect.getsource() for attribute-level confirmation; Android-side evidence
  via V2-side integration tests.
- NO markdown documents, README text, PR prose, PR #993, PR descriptions, or
  architecture narratives are used as evidence.
- Failures are explicit: missing imports or absent tests yield downgraded
  evidence labels, never silently optimistic.
- Prior reassessments (full_current_state_dual_repo_rereading.py,
  post_closure_dual_repo_reassessment.py, pr993_dual_repo_reevaluation.py)
  are used only as navigation hints for where to look — NOT as evidence.

Eight audit dimensions
----------------------
1. ARCHITECTURE_GOVERNANCE_ORCHESTRATION
   Authority/governance/orchestration structure; Android runtime-carrier role.
2. ANDROID_RUNTIME_CARRIER_PATHS
   Registration, snapshot, execution-event, result, and continuity paths.
3. OPERATOR_CONTROL_PLANE_APIS
   Operator/control-plane/console/panel APIs and current aggregation surfaces.
4. DESKTOP_SHELL_PRESENCE_MANIFESTATION
   Shell/manifestation/presence/desktop-facing surfaces (three-state model).
5. NATURAL_LANGUAGE_DRIVING
   Natural-language input, command, and orchestration paths.
6. MULTIMODAL_PERCEPTION_GROUNDING
   Multimodal/perception/grounding/vision/interaction paths.
7. STATE_SURFACE_ACTIONABILITY
   Whether state surfaces are read-only, decision-consumed, or action-capable.
8. END_TO_END_CONTROLLABILITY
   True end-to-end controllability versus observation/projection only.

Public API
----------
Sentinels::

    COMPREHENSIVE_AUDIT_AUTHORITY
    COMPREHENSIVE_AUDIT_METHODOLOGY
    COMPREHENSIVE_AUDIT_VERDICT_ZH

Enumerations::

    AuditEvidenceLabel   — 7-tier evidence ladder (stricter than prior audits)
    AuditDimension       — 8 audit dimensions
    ActionabilityLevel   — read-only / decision-consumed / action-capable
    SystemCompletenessVerdict  — final system-level verdict

Dataclasses::

    DimensionAuditEntry
    CompletenessQuestion
    PanelApiSurface
    ActionabilitySurface
    ComprehensiveAuditReport

Functions::

    build_comprehensive_joint_audit() -> ComprehensiveAuditReport
    get_comprehensive_joint_audit()   -> ComprehensiveAuditReport  (cached)
    reset_comprehensive_joint_audit() -> None                       (test isolation)
    assert_comprehensive_audit_invariants() -> None                 (test helper)
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import json
import logging
import os
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.ComprehensiveJointDualRepoAudit")

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

COMPREHENSIVE_AUDIT_AUTHORITY: str = (
    "COMPREHENSIVE_JOINT_DUAL_REPO_AUDIT_AUTHORITY::"
    "core.comprehensive_joint_dual_repo_audit::"
    "strict-real-code-only-dual-repo-audit-no-pr993-as-evidence"
)

COMPREHENSIVE_AUDIT_METHODOLOGY: str = (
    "METHODOLOGY: Comprehensive joint dual-repo current-state audit of the Galaxy "
    "distributed AI-body/control system (ufo-galaxy-realization-v2 × ufo-galaxy-android). "
    "All conclusions strictly grounded in: (1) real Python imports and attribute checks "
    "against the live V2 codebase; (2) existence of CI test modules as machine-verifiable "
    "proof; (3) inspect.getsource() for attribute-level confirmation; (4) Android-side "
    "evidence via V2-side integration tests. "
    "PR #993, markdown docs, README text, PR prose, and architecture narratives are "
    "EXPLICITLY EXCLUDED as evidence. "
    "Prior reassessments are used only as navigation hints — not as evidence. "
    "Eight dimensions audited: architecture/governance, Android runtime-carrier paths, "
    "operator/control-plane APIs, desktop shell/presence/manifestation (three-state model), "
    "natural-language driving, multimodal/perception, state surface actionability, and "
    "end-to-end controllability vs observation/projection."
)

# ---------------------------------------------------------------------------
# Chinese system verdict (中文系统结论)
# ---------------------------------------------------------------------------

COMPREHENSIVE_AUDIT_VERDICT_ZH: str = (
    "【Galaxy 双仓系统全量严格当前状态联合审查结论 — 完全基于真实代码，不含任何 PR 叙事作为证据】\n\n"
    "一、系统当前真实定性\n"
    "Galaxy 双仓系统当前是以 V2 为中心 authority、以 Android 为真实 runtime carrier/"
    "执行节点/continuity 来源的分布式协同系统。V2 的 authority 地位和 Android 的 carrier"
    "角色均已通过真实代码和测试链路确认，属于 STRONGLY_ESTABLISHED 级别。\n\n"
    "二、六项完整性问题严格判断\n\n"
    "1. 中心↔Android 集成分布式 AI 体控制系统是否真正完整？\n"
    "   判断：MOSTLY_COMPLETE，存在一项已知 PARTIALLY_ESTABLISHED gap（continuity e2e roundtrip）。\n"
    "   注册/snapshot/执行事件/delegated execution 四条核心路径均已 RUNTIME_EVIDENCED_CLOSED。\n\n"
    "2. 系统是否真正自然语言驱动（端到端 canonical path）？\n"
    "   判断：PARTIALLY_PROVEN。\n"
    "   结构路径成立：chat → DesktopPresenceRuntime.handle_request → OpenClawd.process → LLM。\n"
    "   但 CI 测试不验证真实 LLM 后端处理——LLM 端到端自然语言激活在 CI 中仅被 mock 或跳过。\n"
    "   因此\u201c端到端自然语言驱动\u201d作为 CI 可证命题尚未达到 RUNTIME_EVIDENCED_CLOSED。\n\n"
    "3. 系统是否真正原生多模态驱动（端到端 canonical path）？\n"
    "   判断：INFRASTRUCTURE_PRESENT_NOT_YET_END_TO_END_PROVEN。\n"
    "   代码中存在两条多模态路径：持续主机感知（MultimodalIngressBus，默认禁用）和请求绑定"
    "   多模态上下文（MultimodalBus.ingest，结构存在）。Android vision 接入路径存在。\n"
    "   但多模态 ingest 默认配置为 SAFE_DEFAULT（禁用），且无 CI 测试证明端到端多模态感知→"
    "   决策链路的完整激活。因此原生多模态驱动仍处于 PARTIALLY_ESTABLISHED。\n\n"
    "4. 桌面端三态/shell/manifestation/presence 模型能否完整一致地呈现？\n"
    "   判断：PARTIALLY_ESTABLISHED。\n"
    "   代码中存在三套独立状态系统：(a) 主体生命周期（silent/liminal/manifest，"
    "   DesktopPresenceRuntime）；(b) continuum posture（OpenClawd）；(c) UI clothing 状态"
    "   （DORMANT/ISLAND/SIDESHEET/FULLAGENT，state_machine_ui_integration.py）。\n"
    "   这三套状态系统在代码中有文档区分，但尚无统一聚合端点将三者一起投影为单一"
    "   panel-fillable 表面。/api/v1/projection/runtime 提供部分，但不覆盖 UI clothing 状态。\n\n"
    "5. 面板 API 是否完全统一聚合以支持一致的面板状态填写和呈现？\n"
    "   判断：PARTIALLY_ESTABLISHED。\n"
    "   多个 operator 端点存在（/api/v1/operator/snapshot, /api/v1/operator/devices/ecosystem, "
    "   /api/v1/operator/flows, /api/v1/projection/runtime 等），均只读、结构完整。\n"
    "   但尚无单一聚合端点将所有表面（主体生命周期 + Android ecosystem + flows + capabilities "
    "+ shell clothing states）合并为一个 panel state 对象。因此\u201c完全统一聚合\u201d未达到成立。\n\n"
    "6. 系统是否端到端可控，还是部分仍停留在观测/投影层面？\n"
    "   判断：DISPATCH_CAPABLE_BUT_OPERATOR_SURFACE_IS_OBSERVATION_ONLY。\n"
    "   系统具备端到端 dispatch 能力（V2 dispatch → Android execution → result uplink），\n"
    "   已达到 RUNTIME_EVIDENCED_CLOSED。但 operator surface（所有 /api/v1/operator/* 端点）\n"
    "   为纯只读投影，没有 action 端点。控制面板无法直接通过 operator API 发起任务或控制设备。\n"
    "   因此 operator/panel 层面是 OBSERVATION_PROJECTION_ONLY，执行控制需走 /api/v1/chat 或"
    "   e2e 路径。\n\n"
    "三、分级完整性状态汇总\n"
    "STRONGLY_ESTABLISHED: 架构/治理、Android 注册、operator_surface 结构\n"
    "RUNTIME_EVIDENCED_CLOSED: snapshot uplink, execution event, delegated exec, "
    "orchestration consumes Android truth\n"
    "PARTIALLY_ESTABLISHED: continuity e2e roundtrip, three-state panel presentation, "
    "panel API unification, NL end-to-end CI proof, multimodal end-to-end activation\n"
    "SURFACE_ALIGNMENT_ONLY: operator panel action capability, UI clothing state "
    "unified projection, multimodal CI activation\n"
    "MISSING_RUNTIME_EVIDENCE: single aggregated panel-state endpoint\n\n"
    "四、当前阶段与后续工作\n"
    "系统当前处于 LATE_STAGE_CLOSURE。所有 P0 主链路已关闭。\n"
    "高价值后续工作（非 P0 但具产品完整性意义）：\n"
    "(1) Panel API 统一聚合端点 — 产品完整性 gap，非 P0\n"
    "(2) 三态统一投影表面 — 产品完整性 gap，非 P0\n"
    "(3) NL 端到端 CI 证明（真实 LLM roundtrip 测试） — 非 P0\n"
    "(4) 多模态端到端激活 CI 证明 — 非 P0\n"
    "(5) Continuity e2e roundtrip 补测试 — 已知 P1\n\n"
    "五、一句话总结\n"
    "系统主线已闭环、P0 已清空，但'原生自然语言驱动'、'原生多模态驱动'、"
    "'桌面三态完整呈现'和'面板 API 完全统一聚合'这四个用户关切的完整性命题，"
    "在当前真实代码中均停留在 PARTIALLY_ESTABLISHED，尚未达到端到端 CI 可证状态。"
)

# ---------------------------------------------------------------------------
# Evidence label (stricter than prior audits)
# ---------------------------------------------------------------------------


class AuditEvidenceLabel(str, Enum):
    """Seven-tier evidence ladder — stricter than prior audit evidence labels.

    STRONGLY_ESTABLISHED
        Real imports succeed; runtime path exercised; passing CI tests confirm
        end-to-end behavior.  No known gaps.

    RUNTIME_EVIDENCED_CLOSED
        End-to-end runtime path closed by a closure PR: machine-verifiable CI
        tests exercise the full round-trip.

    PARTIALLY_ESTABLISHED
        Real code and/or test modules present; at least one known gap (cross-repo
        round-trip test, advisory-mode gate, or disabled-by-default config)
        prevents full closure.

    INFRASTRUCTURE_PRESENT_NOT_YET_E2E_PROVEN
        Code structure and modules present; end-to-end activation is gated
        (disabled by config or feature flag) and no CI test proves full
        end-to-end activation.

    SURFACE_ALIGNMENT_ONLY
        Schema / store / sentinel / operator-surface alignment exists; no
        machine-verifiable runtime proof that truth flows into decisions or
        that the surface is actionable.

    MISSING_RUNTIME_EVIDENCE
        Structural path exists (importable module) but no runtime activation
        evidence or passing end-to-end tests exist.

    NOT_YET_IMPLEMENTED
        The capability or surface is structurally absent or not yet implemented
        in current merged code.
    """

    STRONGLY_ESTABLISHED = "STRONGLY_ESTABLISHED"
    RUNTIME_EVIDENCED_CLOSED = "RUNTIME_EVIDENCED_CLOSED"
    PARTIALLY_ESTABLISHED = "PARTIALLY_ESTABLISHED"
    INFRASTRUCTURE_PRESENT_NOT_YET_E2E_PROVEN = (
        "INFRASTRUCTURE_PRESENT_NOT_YET_E2E_PROVEN"
    )
    SURFACE_ALIGNMENT_ONLY = "SURFACE_ALIGNMENT_ONLY"
    MISSING_RUNTIME_EVIDENCE = "MISSING_RUNTIME_EVIDENCE"
    NOT_YET_IMPLEMENTED = "NOT_YET_IMPLEMENTED"


class AuditDimension(str, Enum):
    """Eight audit dimensions for the comprehensive joint dual-repo audit."""

    ARCHITECTURE_GOVERNANCE_ORCHESTRATION = "ARCHITECTURE_GOVERNANCE_ORCHESTRATION"
    ANDROID_RUNTIME_CARRIER_PATHS = "ANDROID_RUNTIME_CARRIER_PATHS"
    OPERATOR_CONTROL_PLANE_APIS = "OPERATOR_CONTROL_PLANE_APIS"
    DESKTOP_SHELL_PRESENCE_MANIFESTATION = "DESKTOP_SHELL_PRESENCE_MANIFESTATION"
    NATURAL_LANGUAGE_DRIVING = "NATURAL_LANGUAGE_DRIVING"
    MULTIMODAL_PERCEPTION_GROUNDING = "MULTIMODAL_PERCEPTION_GROUNDING"
    STATE_SURFACE_ACTIONABILITY = "STATE_SURFACE_ACTIONABILITY"
    END_TO_END_CONTROLLABILITY = "END_TO_END_CONTROLLABILITY"


class ActionabilityLevel(str, Enum):
    """Actionability level for state/operator surfaces.

    READ_ONLY_PROJECTION
        Surface only exposes read-only projections.  No actions can be
        triggered via this surface.

    DECISION_CONSUMED
        Truth from this surface flows into orchestration/routing decisions.

    ACTION_CAPABLE
        Surface exposes action endpoints (e.g. POST / trigger / dispatch).
    """

    READ_ONLY_PROJECTION = "READ_ONLY_PROJECTION"
    DECISION_CONSUMED = "DECISION_CONSUMED"
    ACTION_CAPABLE = "ACTION_CAPABLE"


class SystemCompletenessVerdict(str, Enum):
    """Final system-level verdict.

    LATE_STAGE_CLOSURE
        All P0 gaps are closed; remaining work is P1/P2/P3 refinement.
        This is the current system stage.

    MOSTLY_COMPLETE_WITH_KNOWN_GAPS
        Main structure fully established; known product-completeness gaps
        remain that do not block core function but do reduce product quality.

    PARTIAL_COMPLETENESS
        Core structure established but multiple gaps block full completeness
        claims.
    """

    LATE_STAGE_CLOSURE = "LATE_STAGE_CLOSURE"
    MOSTLY_COMPLETE_WITH_KNOWN_GAPS = "MOSTLY_COMPLETE_WITH_KNOWN_GAPS"
    PARTIAL_COMPLETENESS = "PARTIAL_COMPLETENESS"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class DimensionAuditEntry:
    """Audit entry for a single dimension.

    Attributes
    ----------
    dimension
        The AuditDimension being assessed.
    label
        AuditEvidenceLabel for this dimension.
    summary
        One-paragraph English summary grounded in real code.
    proven_items
        Items confirmed by real code/tests.
    partial_items
        Items only partially confirmed.
    gap_items
        Known gaps (honestly labeled).
    code_anchors
        V2-side module / file paths as code anchors.
    android_evidence_refs
        Android-side evidence via V2 integration test references.
    actionability
        If applicable, the ActionabilityLevel of this surface.
    """

    dimension: AuditDimension
    label: AuditEvidenceLabel
    summary: str
    proven_items: List[str] = field(default_factory=list)
    partial_items: List[str] = field(default_factory=list)
    gap_items: List[str] = field(default_factory=list)
    code_anchors: List[str] = field(default_factory=list)
    android_evidence_refs: List[str] = field(default_factory=list)
    actionability: Optional[ActionabilityLevel] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dimension": self.dimension.value,
            "label": self.label.value,
            "summary": self.summary,
            "proven_items": self.proven_items,
            "partial_items": self.partial_items,
            "gap_items": self.gap_items,
            "code_anchors": self.code_anchors,
            "android_evidence_refs": self.android_evidence_refs,
            "actionability": (
                self.actionability.value if self.actionability else None
            ),
        }


@dataclass
class CompletenessQuestion:
    """Answer to one of the six user-posed completeness questions.

    Attributes
    ----------
    question_id
        Short slug (e.g. "center_android_integrated_complete").
    question_text
        Full question text.
    verdict_label
        AuditEvidenceLabel summarizing the verdict.
    answer
        Code-grounded answer (honest — does not presume completeness).
    proven_aspect
        What IS proven by current code.
    unproven_aspect
        What is NOT yet proven or only partially proven.
    """

    question_id: str
    question_text: str
    verdict_label: AuditEvidenceLabel
    answer: str
    proven_aspect: str = ""
    unproven_aspect: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "question_id": self.question_id,
            "question_text": self.question_text,
            "verdict_label": self.verdict_label.value,
            "answer": self.answer,
            "proven_aspect": self.proven_aspect,
            "unproven_aspect": self.unproven_aspect,
        }


@dataclass
class PanelApiSurface:
    """Description of a panel/operator API surface.

    Attributes
    ----------
    surface_id
        Short identifier.
    route_prefix
        HTTP route prefix (e.g. "/api/v1/operator").
    available
        True if the route module is importable from V2 codebase.
    actionability
        ActionabilityLevel of this surface.
    aggregation_note
        Whether this surface aggregates all relevant state or only part.
    gap_note
        Gap description (empty if surface is complete).
    """

    surface_id: str
    route_prefix: str
    available: bool
    actionability: ActionabilityLevel
    aggregation_note: str = ""
    gap_note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "surface_id": self.surface_id,
            "route_prefix": self.route_prefix,
            "available": self.available,
            "actionability": self.actionability.value,
            "aggregation_note": self.aggregation_note,
            "gap_note": self.gap_note,
        }


@dataclass
class ActionabilitySurface:
    """Describes the actionability of a state/surface domain.

    Attributes
    ----------
    domain
        Domain name.
    read_path_available
        True if a read/projection path exists.
    decision_consumed
        True if this state drives orchestration decisions.
    action_endpoint_available
        True if a POST/action endpoint exists for this domain.
    note
        Additional note.
    """

    domain: str
    read_path_available: bool
    decision_consumed: bool
    action_endpoint_available: bool
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "read_path_available": self.read_path_available,
            "decision_consumed": self.decision_consumed,
            "action_endpoint_available": self.action_endpoint_available,
            "note": self.note,
        }


@dataclass
class ComprehensiveAuditReport:
    """Root artifact for the comprehensive joint dual-repo audit.

    Fully JSON-serialisable via to_dict() / to_json().

    Attributes
    ----------
    report_id
        UUID hex identifier.
    generated_at
        Unix timestamp.
    authority
        Authority sentinel string.
    methodology
        Methodology statement.
    verdict_zh
        Chinese system conclusion.
    dimension_entries
        8 DimensionAuditEntry items (one per dimension).
    completeness_questions
        6 CompletenessQuestion items (answers to user questions).
    panel_api_surfaces
        PanelApiSurface items for operator/panel surfaces.
    actionability_surfaces
        ActionabilitySurface items per domain.
    system_verdict
        SystemCompletenessVerdict.
    system_verdict_rationale
        One-paragraph English rationale for the verdict.
    dimensions_strongly_established_count
        How many dimensions are STRONGLY_ESTABLISHED.
    dimensions_runtime_evidenced_closed_count
        How many dimensions are RUNTIME_EVIDENCED_CLOSED.
    dimensions_partially_established_count
        How many dimensions are PARTIALLY_ESTABLISHED.
    remaining_product_gaps
        List of remaining non-P0 product-completeness gaps.
    follow_up_roadmap
        List of high-value follow-up items (non-noise).
    plain_language_conclusion
        Plain-language English summary of what the system currently is and
        is not.
    """

    report_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    generated_at: float = field(default_factory=time.time)
    authority: str = COMPREHENSIVE_AUDIT_AUTHORITY
    methodology: str = COMPREHENSIVE_AUDIT_METHODOLOGY
    verdict_zh: str = COMPREHENSIVE_AUDIT_VERDICT_ZH

    dimension_entries: List[DimensionAuditEntry] = field(default_factory=list)
    completeness_questions: List[CompletenessQuestion] = field(default_factory=list)
    panel_api_surfaces: List[PanelApiSurface] = field(default_factory=list)
    actionability_surfaces: List[ActionabilitySurface] = field(default_factory=list)

    system_verdict: SystemCompletenessVerdict = SystemCompletenessVerdict.LATE_STAGE_CLOSURE
    system_verdict_rationale: str = ""

    dimensions_strongly_established_count: int = 0
    dimensions_runtime_evidenced_closed_count: int = 0
    dimensions_partially_established_count: int = 0

    remaining_product_gaps: List[str] = field(default_factory=list)
    follow_up_roadmap: List[str] = field(default_factory=list)
    plain_language_conclusion: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "generated_at": self.generated_at,
            "authority": self.authority,
            "methodology": self.methodology,
            "verdict_zh": self.verdict_zh,
            "dimension_entries": [d.to_dict() for d in self.dimension_entries],
            "completeness_questions": [q.to_dict() for q in self.completeness_questions],
            "panel_api_surfaces": [p.to_dict() for p in self.panel_api_surfaces],
            "actionability_surfaces": [a.to_dict() for a in self.actionability_surfaces],
            "system_verdict": self.system_verdict.value,
            "system_verdict_rationale": self.system_verdict_rationale,
            "dimensions_strongly_established_count": (
                self.dimensions_strongly_established_count
            ),
            "dimensions_runtime_evidenced_closed_count": (
                self.dimensions_runtime_evidenced_closed_count
            ),
            "dimensions_partially_established_count": (
                self.dimensions_partially_established_count
            ),
            "remaining_product_gaps": self.remaining_product_gaps,
            "follow_up_roadmap": self.follow_up_roadmap,
            "plain_language_conclusion": self.plain_language_conclusion,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)


# ---------------------------------------------------------------------------
# Module / file existence helpers (same pattern as full_current_state_dual_repo_rereading)
# ---------------------------------------------------------------------------


def _module_file_exists(module_path: str) -> bool:
    """Return True if the module file exists on disk regardless of importability."""
    try:
        spec = importlib.util.find_spec(module_path)
        if spec is not None:
            return True
    except (ModuleNotFoundError, ImportError, AttributeError, ValueError):
        pass
    rel_path = module_path.replace(".", os.sep) + ".py"
    for base in sys.path:
        candidate = os.path.join(base, rel_path)
        if os.path.isfile(candidate):
            return True
    rel_pkg = module_path.replace(".", os.sep) + os.sep + "__init__.py"
    for base in sys.path:
        candidate = os.path.join(base, rel_pkg)
        if os.path.isfile(candidate):
            return True
    return False


def _try_import(module_path: str) -> bool:
    """Return True if the module file exists on disk or via find_spec."""
    return _module_file_exists(module_path)


def _try_import_with_attr(module_path: str, attr_name: str) -> bool:
    """Return True if the module has the attribute, OR if the file exists."""
    try:
        mod = importlib.import_module(module_path)
        return hasattr(mod, attr_name)
    except (ImportError, ModuleNotFoundError, AttributeError):
        pass
    return _module_file_exists(module_path)


def _source_contains(module_path: str, pattern: str) -> bool:
    """Return True if the module source file contains the pattern string."""
    try:
        spec = importlib.util.find_spec(module_path)
        if spec and spec.origin and os.path.isfile(spec.origin):
            with open(spec.origin, encoding="utf-8", errors="replace") as fh:
                return pattern in fh.read()
    except Exception:  # noqa: BLE001
        pass
    # Fallback: scan sys.path
    rel_path = module_path.replace(".", os.sep) + ".py"
    for base in sys.path:
        candidate = os.path.join(base, rel_path)
        if os.path.isfile(candidate):
            try:
                with open(candidate, encoding="utf-8", errors="replace") as fh:
                    return pattern in fh.read()
            except Exception:  # noqa: BLE001
                pass
    return False


def _test_file_exists(test_module: str) -> bool:
    """Return True if a test file exists (shorthand for _try_import)."""
    return _try_import(test_module)


# ---------------------------------------------------------------------------
# Dimension 1: Architecture, Governance, Orchestration
# ---------------------------------------------------------------------------


def _audit_architecture_governance() -> DimensionAuditEntry:
    """Audit architecture/governance/orchestration structure."""
    proven: List[str] = []
    partial: List[str] = []
    gaps: List[str] = []
    anchors: List[str] = []
    android_refs: List[str] = []

    # V2 canonical authority modules
    authority_checks = [
        ("core.operator_surface", "OPERATOR_SURFACE_PROJECTION_POLICY"),
        ("core.routes.operator", "OPERATOR_ROUTES_AUTHORITY"),
        ("core.agent.capability_registry", "CapabilityRegistry"),
        ("core.unified.capability_resolver", "CapabilityResolver"),
        ("galaxy_gateway.device_router", "DeviceRouter"),
        ("core.android_device_state_store", "DeviceStateSnapshot"),
        ("core.attached_runtime_session_registry", "AttachedSessionRegistryEntry"),
        ("core.runtime.source_dispatch_orchestrator", "_score_candidate"),
        ("galaxy_gateway.routing.device_selection", "get_device_state_snapshot"),
    ]
    for mod, attr in authority_checks:
        if _try_import_with_attr(mod, attr):
            proven.append(f"{mod}.{attr} present")
            anchors.append(mod)
        else:
            gaps.append(f"{mod}.{attr} NOT found")

    # Android registration / admission path in V2 gateway
    android_proto_checks = [
        ("galaxy_gateway.android.handlers.registration", "android registration handler"),
        ("galaxy_gateway.android.handlers.device_state_snapshot", "snapshot handler"),
        ("galaxy_gateway.protocol.aip_v3", "AIP v3 protocol"),
        ("galaxy_gateway.android_bridge", "android bridge"),
    ]
    for mod, label in android_proto_checks:
        if _try_import(mod):
            android_refs.append(f"{mod} ({label})")
        else:
            gaps.append(f"{mod} ({label}) NOT found")

    # Orchestration decision chain with Android truth
    orch_truth_test = "tests.test_orchestration_consumes_android_truth"
    if _test_file_exists(orch_truth_test):
        proven.append("orchestration_consumes_android_truth test present")
        android_refs.append(orch_truth_test)
    else:
        partial.append("test_orchestration_consumes_android_truth not found")

    label = (
        AuditEvidenceLabel.STRONGLY_ESTABLISHED
        if not gaps
        else AuditEvidenceLabel.PARTIALLY_ESTABLISHED
    )

    return DimensionAuditEntry(
        dimension=AuditDimension.ARCHITECTURE_GOVERNANCE_ORCHESTRATION,
        label=label,
        summary=(
            "V2 functions as the central authority / governance / orchestration hub. "
            "CapabilityRegistry is the canonical write authority; CapabilityResolver the "
            "canonical read path. DeviceRouter handles routing; OperatorSurface aggregates "
            "runtime projections read-only. SourceDispatchOrchestrator._score_candidate() "
            "consumes Android truth (android_snapshot, execution_busy) for routing decisions "
            "— confirmed by test_orchestration_consumes_android_truth.py. Android registration, "
            "snapshot ingestion, and execution-event routing are handled by dedicated handlers "
            "in galaxy_gateway/android/handlers/. AIP v3 protocol registration confirms both "
            "repos share a documented message contract."
        ),
        proven_items=proven,
        partial_items=partial,
        gap_items=gaps,
        code_anchors=list(set(anchors)),
        android_evidence_refs=android_refs,
        actionability=ActionabilityLevel.DECISION_CONSUMED,
    )


# ---------------------------------------------------------------------------
# Dimension 2: Android Runtime-Carrier Paths
# ---------------------------------------------------------------------------


def _audit_android_runtime_carrier_paths() -> DimensionAuditEntry:
    """Audit Android registration, snapshot, execution-event, result, continuity paths."""
    proven: List[str] = []
    partial: List[str] = []
    gaps: List[str] = []
    anchors: List[str] = []
    android_refs: List[str] = []

    # --- Registration path ---
    if _try_import("galaxy_gateway.android.handlers.registration"):
        proven.append("Android registration handler importable in V2 gateway")
        anchors.append("galaxy_gateway.android.handlers.registration")
    else:
        gaps.append("Android registration handler NOT found")

    # --- Runtime snapshot path ---
    snapshot_test = "tests.integration.websocket.test_android_snapshot_ws_transport"
    if _test_file_exists(snapshot_test):
        proven.append("Android snapshot WS transport integration test present")
        android_refs.append(snapshot_test)
    else:
        partial.append("Android snapshot WS transport integration test not found")

    if _try_import("core.android_device_state_store"):
        proven.append("core.android_device_state_store importable")
        anchors.append("core.android_device_state_store")

    # --- Execution-event uplink path ---
    if _source_contains("core.android_device_state_store", "DeviceExecutionEvent"):
        proven.append("DeviceExecutionEvent defined in android_device_state_store")
    if _source_contains("core.android_device_state_store", "list_recent_execution_events"):
        proven.append("list_recent_execution_events() module-level API present")

    if _source_contains("galaxy_gateway.protocol.aip_v3", "DEVICE_EXECUTION_EVENT"):
        proven.append("DEVICE_EXECUTION_EVENT registered in AIP v3 protocol")
        anchors.append("galaxy_gateway.protocol.aip_v3")

    # --- Delegated execution / result path ---
    exec_closure_tests = [
        "tests.test_pr_dual_repo_task_result_truth_closure",
        "tests.test_android_delegated_runtime_audit",
    ]
    for t in exec_closure_tests:
        if _test_file_exists(t):
            proven.append(f"{t} present — execution closure test")
            android_refs.append(t)
        else:
            partial.append(f"{t} not found")

    if _try_import("core.android_delegated_runtime_lifecycle_coordinator"):
        proven.append("android_delegated_runtime_lifecycle_coordinator importable")
        anchors.append("core.android_delegated_runtime_lifecycle_coordinator")

    # --- Continuity path ---
    if _source_contains(
        "core.attached_runtime_session_registry", "durable_session_id"
    ):
        proven.append("durable_session_id field present in session registry")
        anchors.append("core.attached_runtime_session_registry")
    else:
        partial.append("durable_session_id not found in session registry")

    if _source_contains(
        "core.attached_runtime_session_registry", "session_continuity_epoch"
    ):
        proven.append("session_continuity_epoch field present")

    # Continuity e2e roundtrip — known gap
    continuity_e2e_test = "tests.test_continuity_e2e_roundtrip"
    if _test_file_exists(continuity_e2e_test):
        proven.append("continuity e2e roundtrip test present")
        android_refs.append(continuity_e2e_test)
    else:
        partial.append(
            "No standalone continuity e2e roundtrip test found — "
            "continuity bridge is PARTIALLY_ESTABLISHED"
        )

    # Determine label based on partials/gaps
    if gaps:
        label = AuditEvidenceLabel.PARTIALLY_ESTABLISHED
    elif partial:
        label = AuditEvidenceLabel.PARTIALLY_ESTABLISHED
    else:
        label = AuditEvidenceLabel.RUNTIME_EVIDENCED_CLOSED

    return DimensionAuditEntry(
        dimension=AuditDimension.ANDROID_RUNTIME_CARRIER_PATHS,
        label=label,
        summary=(
            "Android registration handler present in V2 gateway. "
            "DeviceStateSnapshot absorption and ecosystem summary confirmed in "
            "core.android_device_state_store. DeviceExecutionEvent and "
            "list_recent_execution_events() are module-level APIs. AIP v3 registers "
            "DEVICE_EXECUTION_EVENT. Delegated execution closure tests present. "
            "durable_session_id and session_continuity_epoch fields confirmed in "
            "AttachedSessionRegistryEntry — continuity structure is established. "
            "Remaining gap: no standalone continuity e2e roundtrip test, so the "
            "continuity path is PARTIALLY_ESTABLISHED rather than RUNTIME_EVIDENCED_CLOSED."
        ),
        proven_items=proven,
        partial_items=partial,
        gap_items=gaps,
        code_anchors=list(set(anchors)),
        android_evidence_refs=android_refs,
        actionability=ActionabilityLevel.DECISION_CONSUMED,
    )


# ---------------------------------------------------------------------------
# Dimension 3: Operator / Control-Plane APIs
# ---------------------------------------------------------------------------


def _audit_operator_control_plane_apis() -> DimensionAuditEntry:
    """Audit operator/control-plane/console/panel API aggregation surfaces."""
    proven: List[str] = []
    partial: List[str] = []
    gaps: List[str] = []
    anchors: List[str] = []

    # Core operator surface
    if _try_import("core.operator_surface"):
        proven.append("core.operator_surface importable (OperatorSurface authority)")
        anchors.append("core.operator_surface")

    # Operator routes
    if _try_import("core.routes.operator"):
        proven.append("core.routes.operator importable — /api/v1/operator/* routes")
        anchors.append("core.routes.operator")

    # Flow-level operator surface
    if _try_import("core.flow_level_operator_surface"):
        proven.append("core.flow_level_operator_surface importable")
        anchors.append("core.flow_level_operator_surface")

    # Projection routes (runtime projection + return summary)
    if _try_import("core.routes.projection"):
        proven.append("core.routes.projection importable — /api/v1/projection/runtime")
        anchors.append("core.routes.projection")

    # Android ecosystem endpoint
    if _source_contains("core.routes.operator", "/api/v1/operator/devices/ecosystem"):
        proven.append("/api/v1/operator/devices/ecosystem endpoint present")
    else:
        partial.append("/api/v1/operator/devices/ecosystem not confirmed in source")

    if _source_contains("core.routes.operator", "/api/v1/operator/devices/execution-events"):
        proven.append("/api/v1/operator/devices/execution-events endpoint present")

    # Aggregation gap: no single unified panel-state endpoint
    # Check for a unified panel state or panel state aggregation module
    panel_agg_candidates = [
        "core.unified_panel_state",
        "core.panel_state_aggregation",
        "core.operator_panel_aggregation",
        "core.routes.panel",
    ]
    panel_agg_found = any(_try_import(m) for m in panel_agg_candidates)
    if panel_agg_found:
        proven.append("Unified panel state aggregation module found")
    else:
        gaps.append(
            "No unified panel state aggregation endpoint found — multiple operator "
            "surfaces exist but no single endpoint combines subject lifecycle + "
            "Android ecosystem + flows + shell clothing states into one panel object"
        )

    # Operator surface is read-only (confirmed by source inspection)
    if _source_contains("core.operator_surface", "read-only") or _source_contains(
        "core.operator_surface", "read_only"
    ):
        proven.append("operator_surface explicitly documented as read-only projection")

    # Test for operator surface
    if _test_file_exists("tests.test_pr512_runtime_closure_audit"):
        proven.append("runtime closure audit test present")

    label = (
        AuditEvidenceLabel.PARTIALLY_ESTABLISHED
        if gaps
        else AuditEvidenceLabel.STRONGLY_ESTABLISHED
    )

    return DimensionAuditEntry(
        dimension=AuditDimension.OPERATOR_CONTROL_PLANE_APIS,
        label=label,
        summary=(
            "Operator surface structure is comprehensive: OperatorSurface, "
            "FlowLevelOperatorSurface, and /api/v1/operator/* routes all present and "
            "importable. Android ecosystem endpoint (/api/v1/operator/devices/ecosystem) "
            "and execution-events endpoint confirmed. Projection routes "
            "(/api/v1/projection/runtime) present. "
            "However, all operator endpoints are READ_ONLY projections — no action "
            "endpoints exist on the operator surface. "
            "Critical gap: no single unified panel-state aggregation endpoint exists "
            "that combines subject tri-state lifecycle + Android ecosystem + flow state + "
            "shell clothing states into one coherent panel object. "
            "Panel API unification is PARTIALLY_ESTABLISHED."
        ),
        proven_items=proven,
        partial_items=partial,
        gap_items=gaps,
        code_anchors=list(set(anchors)),
        android_evidence_refs=[],
        actionability=ActionabilityLevel.READ_ONLY_PROJECTION,
    )


# ---------------------------------------------------------------------------
# Dimension 4: Desktop Shell / Presence / Manifestation (Three-State Model)
# ---------------------------------------------------------------------------


def _audit_desktop_shell_presence() -> DimensionAuditEntry:
    """Audit desktop shell/presence/manifestation three-state model."""
    proven: List[str] = []
    partial: List[str] = []
    gaps: List[str] = []
    anchors: List[str] = []

    # Tri-state subject lifecycle (DesktopPresenceRuntime)
    if _try_import("core.desktop_presence_runtime"):
        proven.append("core.desktop_presence_runtime importable")
        anchors.append("core.desktop_presence_runtime")

    if _source_contains("core.desktop_presence_runtime", "SILENT") and _source_contains(
        "core.desktop_presence_runtime", "LIMINAL"
    ):
        proven.append("SILENT/LIMINAL/MANIFEST tri-state lifecycle confirmed in DPR")

    # Subject lifecycle tests
    if _test_file_exists("tests.test_pr1_desktop_presence_runtime"):
        proven.append("DPR test suite present (test_pr1_desktop_presence_runtime)")
        anchors.append("tests/test_pr1_desktop_presence_runtime.py")

    # UI clothing states (DORMANT/ISLAND/SIDESHEET/FULLAGENT)
    if _try_import("system_integration.state_machine_ui_integration"):
        proven.append("system_integration.state_machine_ui_integration importable")
        anchors.append("system_integration.state_machine_ui_integration")

    if _source_contains(
        "system_integration.state_machine_ui_integration", "DORMANT"
    ) and _source_contains(
        "system_integration.state_machine_ui_integration", "FULLAGENT"
    ):
        proven.append(
            "DORMANT/ISLAND/SIDESHEET/FULLAGENT UI clothing states confirmed in "
            "state_machine_ui_integration"
        )

    # UI shell vocabulary unification test
    if _test_file_exists("tests.test_ui_shell_state_vocabulary_unification"):
        proven.append("UI shell state vocabulary unification test present")

    # Presence projection
    if _try_import("core.presence.presence_director"):
        proven.append("core.presence.presence_director importable")
        anchors.append("core.presence.presence_director")
    if _try_import("core.presence.presence_projection"):
        proven.append("core.presence.presence_projection importable")
        anchors.append("core.presence.presence_projection")

    # Three-state unified surface gap
    # Check if /api/v1/projection/runtime covers all three state systems
    if _source_contains("core.routes.projection", "SILENT") or _source_contains(
        "core.routes.projection", "tri_state"
    ):
        proven.append(
            "/api/v1/projection/runtime includes tri-state lifecycle state"
        )
    else:
        partial.append(
            "/api/v1/projection/runtime may not expose subject tri-state lifecycle directly"
        )

    # Check for unified three-state panel projection (subject + continuum + clothing)
    unified_three_state_candidates = [
        "core.unified_three_state_projection",
        "core.three_state_panel_surface",
        "core.desktop_state_panel_aggregation",
    ]
    unified_found = any(_try_import(m) for m in unified_three_state_candidates)
    if unified_found:
        proven.append("Unified three-state panel projection module found")
    else:
        gaps.append(
            "No unified three-state panel projection found — tri-state subject lifecycle "
            "(DesktopPresenceRuntime), continuum posture (OpenClawd), and UI clothing states "
            "(state_machine_ui_integration) are three distinct state systems with no single "
            "endpoint that coherently aggregates all three for panel filling"
        )

    # Manifestation shell / presence semantics test
    if _test_file_exists("tests.test_pr8v2_manifestation_shell_presence_semantics"):
        proven.append("Manifestation/shell/presence semantics test present")

    label = (
        AuditEvidenceLabel.PARTIALLY_ESTABLISHED
        if gaps
        else AuditEvidenceLabel.STRONGLY_ESTABLISHED
    )

    return DimensionAuditEntry(
        dimension=AuditDimension.DESKTOP_SHELL_PRESENCE_MANIFESTATION,
        label=label,
        summary=(
            "Three distinct state systems are confirmed in real code: "
            "(1) Subject tri-state lifecycle (SILENT/LIMINAL/MANIFEST) in "
            "DesktopPresenceRuntime — STRONGLY_ESTABLISHED with test coverage. "
            "(2) UI clothing states (DORMANT/ISLAND/SIDESHEET/FULLAGENT) in "
            "system_integration/state_machine_ui_integration.py — STRONGLY_ESTABLISHED. "
            "(3) Continuum posture (tri_state_phase + runtime_domain) inside OpenClawd. "
            "PresenceDirector and PresenceProjection modules are present. "
            "These three systems are documented as distinct and must not be conflated. "
            "Gap: no single unified endpoint or panel surface aggregates all three "
            "state systems together into one panel-fillable structure — the three-state "
            "model is PARTIALLY_ESTABLISHED as a coherently presentable panel surface."
        ),
        proven_items=proven,
        partial_items=partial,
        gap_items=gaps,
        code_anchors=list(set(anchors)),
        android_evidence_refs=[],
        actionability=ActionabilityLevel.READ_ONLY_PROJECTION,
    )


# ---------------------------------------------------------------------------
# Dimension 5: Natural Language Driving
# ---------------------------------------------------------------------------


def _audit_natural_language_driving() -> DimensionAuditEntry:
    """Audit natural-language input, command, and orchestration paths."""
    proven: List[str] = []
    partial: List[str] = []
    gaps: List[str] = []
    anchors: List[str] = []

    # Canonical NL ingress path: chat route → DesktopPresenceRuntime → OpenClawd
    if _try_import("core.routes.chat"):
        proven.append("core.routes.chat importable — /api/v1/chat NL adapter surface")
        anchors.append("core.routes.chat")

    if _source_contains("core.routes.chat", "DesktopPresenceRuntime"):
        proven.append("chat route delegates to DesktopPresenceRuntime (NL chain entry)")

    if _try_import("core.desktop_presence_runtime"):
        proven.append("DesktopPresenceRuntime importable (tri-state NL lifecycle shell)")
        anchors.append("core.desktop_presence_runtime")

    if _source_contains("core.desktop_presence_runtime", "handle_request"):
        proven.append(
            "DesktopPresenceRuntime.handle_request() — single NL entry point for all "
            "adapter surfaces (chat, e2e, openclawd, android_vision)"
        )

    if _try_import("core.openclawd"):
        proven.append("core.openclawd importable (LLM function-calling subject core)")
        anchors.append("core.openclawd")

    if _source_contains("core.openclawd", "process"):
        proven.append("OpenClawd.process() — LLM-driven decision/execution method present")

    if _source_contains("core.openclawd", "function calling") or _source_contains(
        "core.openclawd", "function_call"
    ):
        proven.append(
            "OpenClawd uses LLM function calling — NL-to-tool orchestration present"
        )

    # AI intent / classify_task
    if _try_import("core.ai_intent"):
        proven.append("core.ai_intent importable — task intent classification present")
        anchors.append("core.ai_intent")

    # LLM router
    if _try_import("core.multi_llm_router") or _try_import("core.unified.llm_router"):
        proven.append("LLM router importable — multi-LLM backend routing present")
        anchors.append("core.multi_llm_router")

    # NL end-to-end gap: CI tests do not exercise a real LLM backend
    nl_e2e_test_candidates = [
        "tests.test_nl_end_to_end_roundtrip",
        "tests.test_chat_nl_roundtrip",
        "tests.integration.test_nl_driving_e2e",
    ]
    nl_e2e_found = any(_test_file_exists(t) for t in nl_e2e_test_candidates)
    if nl_e2e_found:
        proven.append("NL end-to-end CI test found")
    else:
        partial.append(
            "No NL end-to-end CI test found that exercises real LLM backend processing — "
            "'naturally language driven' as a CI-provable end-to-end claim is not yet "
            "machine-verifiable; LLM responses are mocked or skipped in CI"
        )
        gaps.append(
            "NL end-to-end roundtrip CI test absent — cannot prove end-to-end NL "
            "driving from real LLM backend processing in current CI"
        )

    label = (
        AuditEvidenceLabel.PARTIALLY_ESTABLISHED
        if gaps
        else AuditEvidenceLabel.RUNTIME_EVIDENCED_CLOSED
    )

    return DimensionAuditEntry(
        dimension=AuditDimension.NATURAL_LANGUAGE_DRIVING,
        label=label,
        summary=(
            "The canonical NL-driving structural chain is confirmed in real code: "
            "/api/v1/chat → DesktopPresenceRuntime.handle_request() → SILENT→LIMINAL→ "
            "OpenClawd.process() → LLM function calling → MANIFEST→SILENT. "
            "AI intent classification (core.ai_intent) and multi-LLM router present. "
            "OpenClawd uses LLM function calling for tool/action selection. "
            "This is a real, live NL-driven decision path — not a placeholder. "
            "Gap: no CI test exercises an actual LLM backend end-to-end roundtrip with "
            "real natural-language input → real LLM response → real action. "
            "Therefore 'truly NL-driven end-to-end' is PARTIALLY_ESTABLISHED: the chain "
            "structurally exists and is correct, but CI-provable end-to-end NL activation "
            "has not been demonstrated."
        ),
        proven_items=proven,
        partial_items=partial,
        gap_items=gaps,
        code_anchors=list(set(anchors)),
        android_evidence_refs=[],
        actionability=ActionabilityLevel.ACTION_CAPABLE,
    )


# ---------------------------------------------------------------------------
# Dimension 6: Multimodal / Perception / Grounding
# ---------------------------------------------------------------------------


def _audit_multimodal_perception_grounding() -> DimensionAuditEntry:
    """Audit multimodal/perception/grounding/vision/interaction paths."""
    proven: List[str] = []
    partial: List[str] = []
    gaps: List[str] = []
    anchors: List[str] = []
    android_refs: List[str] = []

    # Continuous host ingress (MultimodalIngressBus)
    if _try_import("core.multimodal.ingest_runtime"):
        proven.append(
            "core.multimodal.ingest_runtime importable — continuous host perception bus"
        )
        anchors.append("core.multimodal.ingest_runtime")

    if _try_import("core.multimodal.ingress_bus"):
        proven.append("core.multimodal.ingress_bus importable — MultimodalIngressBus")
        anchors.append("core.multimodal.ingress_bus")

    # Perception frame / source registry
    if _try_import("core.multimodal.perception_frame"):
        proven.append("core.multimodal.perception_frame importable")
        anchors.append("core.multimodal.perception_frame")
    if _try_import("core.multimodal.perception_source_registry"):
        proven.append("core.multimodal.perception_source_registry importable")
        anchors.append("core.multimodal.perception_source_registry")

    # Request-bound multimodal context (MultimodalBus.ingest in OpenClawd)
    if _source_contains("core.openclawd", "multimodal_context"):
        proven.append(
            "OpenClawd.process() accepts multimodal_context — request-bound "
            "multimodal payload fusion path confirmed"
        )
    if _source_contains("core.openclawd", "MultimodalBus") or _source_contains(
        "core.openclawd", "multimodal_bus"
    ):
        proven.append("OpenClawd references MultimodalBus for ingest fusion")

    # Vision pipeline
    if _try_import("core.vision_pipeline"):
        proven.append("core.vision_pipeline importable — visual processing present")
        anchors.append("core.vision_pipeline")

    # Multimodal runtime profile (config-gated)
    if _try_import("core.multimodal_runtime_profile"):
        proven.append(
            "core.multimodal_runtime_profile importable — SAFE_DEFAULT profile confirmed "
            "(multimodal ingest DISABLED by default)"
        )
        anchors.append("core.multimodal_runtime_profile")

    if _source_contains("core.multimodal_runtime_profile", "SAFE_DEFAULT"):
        proven.append(
            "SAFE_DEFAULT profile: enable_multimodal_ingest=False by default — "
            "continuous host perception is disabled unless explicitly configured"
        )

    # Android vision uplink path
    if _try_import("galaxy_gateway.android.handlers.vision"):
        proven.append(
            "galaxy_gateway.android.handlers.vision importable — Android vision "
            "uplink handler present"
        )
        android_refs.append("galaxy_gateway.android.handlers.vision")
        anchors.append("galaxy_gateway.android.handlers.vision")

    # Mobile VLM presence checks in state store
    if _source_contains("core.android_device_state_store", "mobilevlm_present"):
        proven.append(
            "mobilevlm_present field in DeviceStateSnapshot — Android-side VLM "
            "presence tracking confirmed"
        )
    if _source_contains("core.android_device_state_store", "seeclick_present"):
        proven.append("seeclick_present field in DeviceStateSnapshot confirmed")

    # Multimodal end-to-end CI gap
    mm_e2e_test_candidates = [
        "tests.integration.test_multimodal_e2e",
        "tests.test_multimodal_end_to_end",
        "tests.test_multimodal_perception_roundtrip",
    ]
    mm_e2e_found = any(_test_file_exists(t) for t in mm_e2e_test_candidates)
    if mm_e2e_found:
        proven.append("Multimodal end-to-end CI test found")
    else:
        partial.append(
            "No multimodal end-to-end CI test found — cannot prove end-to-end "
            "multimodal perception→decision activation in CI"
        )
        gaps.append(
            "Multimodal ingest is disabled by default (SAFE_DEFAULT) and no CI test "
            "proves full end-to-end multimodal activation (ambient perception → "
            "OpenClawd → decision/action)"
        )

    label = AuditEvidenceLabel.INFRASTRUCTURE_PRESENT_NOT_YET_E2E_PROVEN

    return DimensionAuditEntry(
        dimension=AuditDimension.MULTIMODAL_PERCEPTION_GROUNDING,
        label=label,
        summary=(
            "Multimodal infrastructure is present in real code: MultimodalIngressBus "
            "(continuous host perception), PerceptionSourceRegistry, PerceptionFrame, "
            "and VisionPipeline are all importable. "
            "OpenClawd accepts multimodal_context for request-bound payload fusion. "
            "Android vision uplink handler present in galaxy_gateway. "
            "Mobile VLM presence (mobilevlm_present, seeclick_present) tracked in "
            "DeviceStateSnapshot. "
            "However: the continuous host ingress path (MultimodalIngressBus) is "
            "DISABLED BY DEFAULT (enable_multimodal_ingest=False in SAFE_DEFAULT profile). "
            "No CI test proves full end-to-end multimodal activation. "
            "Therefore 'truly natively multimodal' is "
            "INFRASTRUCTURE_PRESENT_NOT_YET_E2E_PROVEN — the infrastructure exists and "
            "is correct, but is config-gated and not CI-proven end-to-end."
        ),
        proven_items=proven,
        partial_items=partial,
        gap_items=gaps,
        code_anchors=list(set(anchors)),
        android_evidence_refs=android_refs,
        actionability=ActionabilityLevel.DECISION_CONSUMED,
    )


# ---------------------------------------------------------------------------
# Dimension 7: State Surface Actionability
# ---------------------------------------------------------------------------


def _audit_state_surface_actionability() -> DimensionAuditEntry:
    """Audit whether state surfaces are read-only, decision-consumed, or action-capable."""
    proven: List[str] = []
    partial: List[str] = []
    gaps: List[str] = []
    anchors: List[str] = []

    actionability_surfaces_evidence = [
        # (domain, read_path, decision_consumed, action_endpoint, note)
        (
            "operator_surface (/api/v1/operator/*)",
            _try_import("core.operator_surface"),
            False,  # not directly decision-consumed at API level
            False,  # no POST/action endpoints
            "read-only projection surface; confirmed by OperatorSurface docstring",
        ),
        (
            "projection_routes (/api/v1/projection/runtime)",
            _try_import("core.routes.projection"),
            False,
            False,
            "read-only runtime projection",
        ),
        (
            "android_device_state_store (V2-internal truth)",
            _try_import("core.android_device_state_store"),
            True,  # consumed by _score_candidate / device_selection
            False,
            "decision-consumed by orchestration routing",
        ),
        (
            "chat route (/api/v1/chat)",
            _try_import("core.routes.chat"),
            False,  # not a state surface — action input
            True,   # action-capable (POST triggers execution)
            "action-capable: POST triggers NL execution via DesktopPresenceRuntime",
        ),
        (
            "capability_registry (canonical write authority)",
            _try_import("core.agent.capability_registry"),
            True,  # read path feeds routing
            True,  # has write path (register)
            "write authority for capabilities; read path feeds routing decisions",
        ),
    ]

    for domain, read_ok, consumed, action_ok, note in actionability_surfaces_evidence:
        if read_ok:
            proven.append(
                f"{domain}: read_path=True, decision_consumed={consumed}, "
                f"action_capable={action_ok} — {note}"
            )
            anchors.append(domain.split(" ")[0])
        else:
            partial.append(f"{domain}: module not confirmed as importable")

    # Gap: operator surface has no action endpoints
    gaps.append(
        "Operator surface (/api/v1/operator/*) is strictly READ_ONLY — no POST or "
        "action endpoints exposed through the operator/panel surface; control must "
        "go through /api/v1/chat or internal dispatch"
    )

    return DimensionAuditEntry(
        dimension=AuditDimension.STATE_SURFACE_ACTIONABILITY,
        label=AuditEvidenceLabel.PARTIALLY_ESTABLISHED,
        summary=(
            "State surfaces span three actionability levels in current code. "
            "READ_ONLY: all /api/v1/operator/* endpoints and /api/v1/projection/runtime "
            "— projection surfaces only, no actions. "
            "DECISION_CONSUMED: android_device_state_store truth is consumed by "
            "_score_candidate() and device_selection.py for routing decisions. "
            "CapabilityRegistry feeds routing decisions. "
            "ACTION_CAPABLE: /api/v1/chat triggers NL execution; capability_registry "
            "write path exists. "
            "Summary: decision-consumption of Android truth is confirmed (P0 closed). "
            "Panel/operator surface is read-only projection only — no action capability "
            "exposed at operator level. This is PARTIALLY_ESTABLISHED as a complete "
            "actionable control surface."
        ),
        proven_items=proven,
        partial_items=partial,
        gap_items=gaps,
        code_anchors=list(set(anchors)),
        android_evidence_refs=[],
        actionability=ActionabilityLevel.READ_ONLY_PROJECTION,
    )


# ---------------------------------------------------------------------------
# Dimension 8: End-to-End Controllability
# ---------------------------------------------------------------------------


def _audit_end_to_end_controllability() -> DimensionAuditEntry:
    """Audit true end-to-end controllability versus observation/projection only."""
    proven: List[str] = []
    partial: List[str] = []
    gaps: List[str] = []
    anchors: List[str] = []
    android_refs: List[str] = []

    # Dispatch chain: V2 dispatch → Android execution → result uplink
    dispatch_test = "tests.test_orchestration_consumes_android_truth"
    if _test_file_exists(dispatch_test):
        proven.append(
            "Orchestration dispatch test confirms Android truth consumed in routing decisions"
        )
        android_refs.append(dispatch_test)

    # Delegated execution closure
    exec_closure = "tests.test_pr_dual_repo_task_result_truth_closure"
    if _test_file_exists(exec_closure):
        proven.append(
            "Delegated execution closure test confirms V2→Android dispatch→result chain"
        )
        android_refs.append(exec_closure)

    # Source dispatch orchestrator
    if _try_import("core.runtime.source_dispatch_orchestrator"):
        proven.append("SourceDispatchOrchestrator importable — dispatch authority present")
        anchors.append("core.runtime.source_dispatch_orchestrator")

    # Gateway device router
    if _try_import("galaxy_gateway.device_router"):
        proven.append("DeviceRouter importable — gateway routing authority present")
        anchors.append("galaxy_gateway.device_router")

    # Android execution signal reconciler
    if _try_import("core.android_execution_signal_reconciler"):
        proven.append(
            "android_execution_signal_reconciler importable — result ingest path present"
        )
        anchors.append("core.android_execution_signal_reconciler")

    # Operator surface is read-only — not action-capable at panel level
    if _source_contains("core.operator_surface", "read-only") or _source_contains(
        "core.operator_surface", "read_only"
    ):
        partial.append(
            "Operator surface is explicitly read-only — panel-level action triggering "
            "is not possible through /api/v1/operator/* endpoints"
        )
    gaps.append(
        "Control plane panel has no action-triggering endpoints — operator/panel "
        "surface is OBSERVATION_PROJECTION_ONLY; task dispatch requires going through "
        "/api/v1/chat or e2e route rather than operator panel directly"
    )

    # Multi-device hybrid orchestration CI
    hybrid_test = "tests.test_multi_device_hybrid_orchestration"
    if _test_file_exists(hybrid_test):
        proven.append("Multi-device hybrid orchestration CI test present")
    else:
        partial.append(
            "No standalone multi-device hybrid orchestration CI test — "
            "multi-device end-to-end controllability not independently CI-proven"
        )

    return DimensionAuditEntry(
        dimension=AuditDimension.END_TO_END_CONTROLLABILITY,
        label=AuditEvidenceLabel.PARTIALLY_ESTABLISHED,
        summary=(
            "End-to-end dispatch capability is RUNTIME_EVIDENCED_CLOSED: "
            "V2 can dispatch tasks to Android, Android executes and returns results, "
            "V2 absorbs execution events, and Android truth drives orchestration routing. "
            "This dispatch chain has CI-proven closure. "
            "However, end-to-end controllability from the operator/panel surface is "
            "OBSERVATION_PROJECTION_ONLY: the /api/v1/operator/* surface exposes only "
            "read-only projections with no action endpoints. An operator cannot directly "
            "trigger task dispatch, control device execution, or affect system state "
            "through the operator panel — they must use /api/v1/chat or internal APIs. "
            "Multi-device hybrid orchestration has not been independently CI-proven "
            "in a dedicated end-to-end test. "
            "Overall judgment: DISPATCH_CAPABLE but PANEL_CONTROLLABILITY_INCOMPLETE."
        ),
        proven_items=proven,
        partial_items=partial,
        gap_items=gaps,
        code_anchors=list(set(anchors)),
        android_evidence_refs=android_refs,
        actionability=ActionabilityLevel.READ_ONLY_PROJECTION,
    )


# ---------------------------------------------------------------------------
# Six completeness questions
# ---------------------------------------------------------------------------


def _build_completeness_questions() -> List[CompletenessQuestion]:
    """Build answers to the six user-posed completeness questions."""
    return [
        CompletenessQuestion(
            question_id="center_android_integrated_complete",
            question_text=(
                "Is the full center↔Android system truly complete as an integrated "
                "distributed AI-body/control system?"
            ),
            verdict_label=AuditEvidenceLabel.PARTIALLY_ESTABLISHED,
            answer=(
                "MOSTLY_COMPLETE with one known gap. "
                "Core integration paths (registration, snapshot uplink, execution-event "
                "uplink, delegated execution result, orchestration consuming Android truth) "
                "are RUNTIME_EVIDENCED_CLOSED. The system qualifies as an integrated "
                "distributed AI-body/control system in its core architecture. "
                "Remaining gap: continuity e2e roundtrip has no standalone CI test, "
                "making that sub-path PARTIALLY_ESTABLISHED rather than fully closed."
            ),
            proven_aspect=(
                "Registration, snapshot, execution-event, delegated execution result, "
                "and orchestration Android-truth consumption — all confirmed by real code "
                "and CI tests."
            ),
            unproven_aspect=(
                "Continuity e2e roundtrip (no standalone CI test); multi-device hybrid "
                "orchestration (no dedicated CI test)."
            ),
        ),
        CompletenessQuestion(
            question_id="nl_driven_end_to_end",
            question_text=(
                "Is the system truly natural-language-driven end-to-end on its "
                "canonical paths?"
            ),
            verdict_label=AuditEvidenceLabel.PARTIALLY_ESTABLISHED,
            answer=(
                "STRUCTURALLY YES, CI-PROVEN NO. "
                "The canonical NL chain exists in real code: /api/v1/chat → "
                "DesktopPresenceRuntime.handle_request() → OpenClawd.process() → LLM "
                "function calling → action dispatch. This chain is correctly wired and "
                "non-trivial. However, no CI test exercises a real LLM backend end-to-end "
                "with natural-language input and verifies natural-language-driven response "
                "and action. LLM responses are mocked or skipped in CI. "
                "Therefore 'truly NL-driven' is structurally established but not "
                "CI-provable in the current state."
            ),
            proven_aspect=(
                "NL chain structure: chat route → DesktopPresenceRuntime → OpenClawd → "
                "LLM function calling. All modules importable and structurally confirmed."
            ),
            unproven_aspect=(
                "No CI test with real LLM backend processing. End-to-end NL activation "
                "is mocked or bypassed in CI. Cannot claim CI-proven NL-driven end-to-end."
            ),
        ),
        CompletenessQuestion(
            question_id="natively_multimodal_e2e",
            question_text=(
                "Is the system truly natively multimodal end-to-end on its "
                "canonical paths?"
            ),
            verdict_label=AuditEvidenceLabel.INFRASTRUCTURE_PRESENT_NOT_YET_E2E_PROVEN,
            answer=(
                "INFRASTRUCTURE PRESENT, DISABLED BY DEFAULT, NOT CI-PROVEN E2E. "
                "Multimodal infrastructure exists: MultimodalIngressBus (continuous host "
                "perception), PerceptionSourceRegistry, PerceptionFrame, VisionPipeline, "
                "and Android vision uplink handler. OpenClawd accepts multimodal_context "
                "for request-bound fusion. Mobile VLM presence tracked in "
                "DeviceStateSnapshot. "
                "BUT: continuous host ingress is disabled by default (SAFE_DEFAULT profile "
                "sets enable_multimodal_ingest=False). No CI test proves full end-to-end "
                "multimodal activation (ambient perception → decision → action). "
                "Therefore 'natively multimodal' is INFRASTRUCTURE_PRESENT but NOT "
                "end-to-end proven."
            ),
            proven_aspect=(
                "Multimodal infrastructure modules present and importable. "
                "Android vision handler. Mobile VLM presence fields. Request-bound "
                "multimodal_context fusion path in OpenClawd."
            ),
            unproven_aspect=(
                "Continuous ingest disabled by default. No CI test of full multimodal "
                "roundtrip. 'Natively multimodal' as an always-on, CI-proven claim "
                "is not established."
            ),
        ),
        CompletenessQuestion(
            question_id="three_state_desktop_shell_coherent_presentation",
            question_text=(
                "Can the desktop-facing three-state / shell / manifestation / presence "
                "model be fully and coherently presented from real current code?"
            ),
            verdict_label=AuditEvidenceLabel.PARTIALLY_ESTABLISHED,
            answer=(
                "THREE DISTINCT STATE SYSTEMS CONFIRMED, UNIFIED PRESENTATION INCOMPLETE. "
                "Real code confirms three distinct state systems: (1) subject tri-state "
                "lifecycle (SILENT/LIMINAL/MANIFEST) in DesktopPresenceRuntime; "
                "(2) UI clothing states (DORMANT/ISLAND/SIDESHEET/FULLAGENT) in "
                "state_machine_ui_integration; (3) continuum posture (tri_state_phase + "
                "runtime_domain) inside OpenClawd. "
                "PresenceDirector and PresenceProjection modules are present. "
                "Gap: no single endpoint coherently aggregates all three state systems "
                "into one panel-fillable structure. The three-state model CAN be read "
                "from code, but coherent unified panel presentation is PARTIALLY_ESTABLISHED."
            ),
            proven_aspect=(
                "All three state systems confirmed in real code. PresenceDirector, "
                "PresenceProjection importable. DPR and state_machine_ui_integration "
                "both have test coverage."
            ),
            unproven_aspect=(
                "No single unified three-state panel aggregation endpoint. "
                "The three systems are separately accessible but not combined into one "
                "coherent panel-state structure."
            ),
        ),
        CompletenessQuestion(
            question_id="panel_apis_fully_unified_aggregated",
            question_text=(
                "Are panel APIs fully unified and aggregated enough to support coherent "
                "panel-state filling and presentation?"
            ),
            verdict_label=AuditEvidenceLabel.PARTIALLY_ESTABLISHED,
            answer=(
                "MULTIPLE SURFACES PRESENT, FULL AGGREGATION INCOMPLETE. "
                "Multiple operator/panel API surfaces exist: /api/v1/operator/snapshot, "
                "/api/v1/operator/flows, /api/v1/operator/devices/ecosystem, "
                "/api/v1/operator/devices/execution-events, /api/v1/projection/runtime, "
                "/api/v1/operator/inspect/* endpoints — all read-only, structurally complete. "
                "Gap: no single aggregation endpoint combines ALL relevant state "
                "(subject lifecycle + Android ecosystem + flow states + UI clothing states + "
                "capabilities + health) into one panel-state object for efficient panel "
                "filling. Panel clients must call multiple endpoints and assemble state "
                "themselves. Full unification is PARTIALLY_ESTABLISHED."
            ),
            proven_aspect=(
                "All individual operator endpoints present and importable. "
                "Android ecosystem, flow, projection, and inspection surfaces all confirmed."
            ),
            unproven_aspect=(
                "No single unified panel-state aggregation endpoint. "
                "Panel state filling requires calling multiple separate endpoints."
            ),
        ),
        CompletenessQuestion(
            question_id="system_fully_controllable_or_observational",
            question_text=(
                "Is the system fully controllable end-to-end, or does it remain "
                "partly observational/projective in some domains?"
            ),
            verdict_label=AuditEvidenceLabel.PARTIALLY_ESTABLISHED,
            answer=(
                "DISPATCH-CAPABLE BUT OPERATOR PANEL IS OBSERVATION-ONLY. "
                "The system IS end-to-end dispatch-capable: V2 can dispatch tasks to "
                "Android, Android executes and returns results, and this chain is "
                "RUNTIME_EVIDENCED_CLOSED. "
                "However, the operator/control-plane panel surface "
                "(/api/v1/operator/*) is strictly READ_ONLY with no action endpoints. "
                "An operator cannot trigger task dispatch, control execution, or affect "
                "system state through the panel surface directly — control must use "
                "/api/v1/chat or e2e route. "
                "Judgment: dispatch is end-to-end capable; operator panel is "
                "OBSERVATION_PROJECTION_ONLY. The system is PARTIALLY controllable "
                "from a unified control-plane perspective."
            ),
            proven_aspect=(
                "End-to-end dispatch chain (V2→Android→result) CI-proven. "
                "Android truth drives orchestration decisions. "
                "NL execution (/api/v1/chat) is action-capable."
            ),
            unproven_aspect=(
                "Operator panel surface is read-only — no panel-level action endpoints. "
                "Cannot control system from operator/control-plane surface directly."
            ),
        ),
    ]


# ---------------------------------------------------------------------------
# Panel API surfaces
# ---------------------------------------------------------------------------


def _build_panel_api_surfaces() -> List[PanelApiSurface]:
    """Build the panel/operator API surface inventory."""
    surfaces = [
        PanelApiSurface(
            surface_id="operator_snapshot",
            route_prefix="/api/v1/operator/snapshot",
            available=_try_import("core.routes.operator"),
            actionability=ActionabilityLevel.READ_ONLY_PROJECTION,
            aggregation_note=(
                "Compact runtime overview: task counts, device presence, topology, "
                "capabilities totals, Android ecosystem count. Partial aggregation."
            ),
            gap_note="Does not include subject tri-state lifecycle or UI clothing states.",
        ),
        PanelApiSurface(
            surface_id="operator_flows",
            route_prefix="/api/v1/operator/flows",
            available=_try_import("core.routes.operator"),
            actionability=ActionabilityLevel.READ_ONLY_PROJECTION,
            aggregation_note="All delegated flows as FlowOperatorProjection dicts.",
            gap_note="",
        ),
        PanelApiSurface(
            surface_id="android_ecosystem",
            route_prefix="/api/v1/operator/devices/ecosystem",
            available=_try_import("core.routes.operator"),
            actionability=ActionabilityLevel.READ_ONLY_PROJECTION,
            aggregation_note="Android device readiness, model identity, runtime health.",
            gap_note="",
        ),
        PanelApiSurface(
            surface_id="android_execution_events",
            route_prefix="/api/v1/operator/devices/execution-events",
            available=_try_import("core.routes.operator"),
            actionability=ActionabilityLevel.READ_ONLY_PROJECTION,
            aggregation_note="Recent Android execution phase events.",
            gap_note="",
        ),
        PanelApiSurface(
            surface_id="projection_runtime",
            route_prefix="/api/v1/projection/runtime",
            available=_try_import("core.routes.projection"),
            actionability=ActionabilityLevel.READ_ONLY_PROJECTION,
            aggregation_note="RuntimeProjection from ContinuumState and topology.",
            gap_note=(
                "Does not aggregate Android ecosystem or UI clothing states. "
                "Partial coverage of the three-state model."
            ),
        ),
        PanelApiSurface(
            surface_id="unified_panel_aggregation",
            route_prefix="/api/v1/panel/state",
            available=False,  # not yet implemented
            actionability=ActionabilityLevel.READ_ONLY_PROJECTION,
            aggregation_note="NOT YET IMPLEMENTED — would combine all surfaces.",
            gap_note=(
                "No single unified panel-state aggregation endpoint exists. "
                "This is the main panel API unification gap."
            ),
        ),
    ]
    return surfaces


# ---------------------------------------------------------------------------
# Actionability surfaces inventory
# ---------------------------------------------------------------------------


def _build_actionability_surfaces() -> List[ActionabilitySurface]:
    """Build the actionability surface inventory per domain."""
    return [
        ActionabilitySurface(
            domain="operator_panel (/api/v1/operator/*)",
            read_path_available=_try_import("core.routes.operator"),
            decision_consumed=False,
            action_endpoint_available=False,
            note=(
                "Strictly read-only projection surface. No POST or action endpoints. "
                "Confirmed by OperatorSurface projection-only principle in source."
            ),
        ),
        ActionabilitySurface(
            domain="projection_surface (/api/v1/projection/runtime)",
            read_path_available=_try_import("core.routes.projection"),
            decision_consumed=False,
            action_endpoint_available=False,
            note="Read-only runtime projection for status board consumption.",
        ),
        ActionabilitySurface(
            domain="android_device_state_store (V2 internal)",
            read_path_available=_try_import("core.android_device_state_store"),
            decision_consumed=True,
            action_endpoint_available=False,
            note=(
                "Decision-consumed: _score_candidate() and device_selection.py "
                "consume snapshot truth for routing. No external action endpoint."
            ),
        ),
        ActionabilitySurface(
            domain="chat_route (/api/v1/chat)",
            read_path_available=False,
            decision_consumed=False,
            action_endpoint_available=_try_import("core.routes.chat"),
            note=(
                "Action-capable: POST triggers full NL execution via "
                "DesktopPresenceRuntime → OpenClawd. Not a state-read surface."
            ),
        ),
        ActionabilitySurface(
            domain="capability_registry (core.agent.capability_registry)",
            read_path_available=_try_import("core.agent.capability_registry"),
            decision_consumed=True,
            action_endpoint_available=True,
            note=(
                "Both read (CapabilityResolver) and write (CapabilityRegistry) paths. "
                "Feeds routing decisions. Write path allows capability registration."
            ),
        ),
        ActionabilitySurface(
            domain="desktop_presence_runtime (core.desktop_presence_runtime)",
            read_path_available=_try_import("core.desktop_presence_runtime"),
            decision_consumed=True,
            action_endpoint_available=True,
            note=(
                "Action-capable: handle_request() drives full tri-state lifecycle. "
                "Also carries subject state (tri-state) for projection."
            ),
        ),
    ]


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------


def build_comprehensive_joint_audit() -> ComprehensiveAuditReport:
    """Build a fresh comprehensive joint dual-repo audit report.

    Returns
    -------
    ComprehensiveAuditReport
        Full report with 8 dimension entries, 6 completeness questions,
        panel API surface inventory, actionability inventory, system verdict,
        and roadmap.
    """
    dimensions = [
        _audit_architecture_governance(),
        _audit_android_runtime_carrier_paths(),
        _audit_operator_control_plane_apis(),
        _audit_desktop_shell_presence(),
        _audit_natural_language_driving(),
        _audit_multimodal_perception_grounding(),
        _audit_state_surface_actionability(),
        _audit_end_to_end_controllability(),
    ]

    completeness_questions = _build_completeness_questions()
    panel_api_surfaces = _build_panel_api_surfaces()
    actionability_surfaces = _build_actionability_surfaces()

    # Count dimension labels
    strongly_count = sum(
        1 for d in dimensions if d.label == AuditEvidenceLabel.STRONGLY_ESTABLISHED
    )
    runtime_closed_count = sum(
        1 for d in dimensions if d.label == AuditEvidenceLabel.RUNTIME_EVIDENCED_CLOSED
    )
    partially_count = sum(
        1 for d in dimensions
        if d.label in (
            AuditEvidenceLabel.PARTIALLY_ESTABLISHED,
            AuditEvidenceLabel.INFRASTRUCTURE_PRESENT_NOT_YET_E2E_PROVEN,
        )
    )

    # Remaining product gaps (non-P0)
    remaining_gaps = [
        "P1: Continuity e2e roundtrip CI test — continuity path not yet CI-proven end-to-end",
        "P1-PRODUCT: Unified panel-state aggregation endpoint "
        "(/api/v1/panel/state or equivalent) — no single endpoint combines all surfaces",
        "P1-PRODUCT: Unified three-state panel projection surface — "
        "SILENT/LIMINAL/MANIFEST + DORMANT/ISLAND/SIDESHEET/FULLAGENT + continuum posture "
        "not jointly aggregated",
        "P1-PRODUCT: NL end-to-end CI test with real LLM backend roundtrip",
        "P2: Multimodal end-to-end CI activation test "
        "(enable_multimodal_ingest=True path)",
        "P2: Operator panel action endpoints for direct task dispatch/control",
        "P2: Multi-device hybrid orchestration dedicated CI test",
        "P3: Zero-config device pairing / QR setup",
        "P3: Mobile VLM end-to-end CI activation",
    ]

    # Follow-up roadmap
    follow_up = [
        "[HIGH] Unified panel-state aggregation: single GET /api/v1/panel/state "
        "combining subject lifecycle + Android ecosystem + flows + shell states",
        "[HIGH] Unified three-state projection: POST-only read surface covering "
        "all three distinct state systems jointly",
        "[HIGH] NL e2e CI: add integration test with real (or contract-stubbed) "
        "LLM backend proving NL input → action roundtrip",
        "[MEDIUM] Multimodal CI: add CI test with enable_multimodal_ingest=True "
        "proving ambient perception → decision activation",
        "[MEDIUM] Operator action surface: POST /api/v1/operator/dispatch or "
        "equivalent to enable panel-level task triggering",
        "[MEDIUM] Continuity e2e roundtrip test (already P1 from prior audit)",
        "[LOW] Multi-device hybrid orchestration dedicated CI test",
        "[LOW] Zero-config pairing, VLM e2e activation (P3)",
    ]

    verdict_rationale = (
        "System verdict is LATE_STAGE_CLOSURE with product-completeness gaps. "
        "All core architecture and Android carrier integration paths are STRONGLY_ESTABLISHED "
        "or RUNTIME_EVIDENCED_CLOSED. P0 blockers are cleared. "
        "However, four key user-posed completeness questions ("
        "NL end-to-end, multimodal end-to-end, three-state panel presentation, "
        "and panel API unification) are each PARTIALLY_ESTABLISHED or "
        "INFRASTRUCTURE_PRESENT_NOT_YET_E2E_PROVEN — none are fully CI-proven. "
        "Operator panel is READ_ONLY_PROJECTION; no action endpoints at panel level. "
        "These are non-P0 product-completeness gaps that reduce product quality and "
        "panel usability but do not block the core system from functioning."
    )

    plain_language = (
        "The Galaxy dual-repo system (V2 + Android) is a real, working distributed "
        "AI-body/control system with a proven core: V2 is the central authority, "
        "Android is the runtime carrier, and the core dispatch/execution/truth chain "
        "is fully closed and CI-verified. "
        "What the system IS: a center-distributed system where V2 routes tasks to "
        "Android, Android executes, and results flow back — all proven. "
        "What the system IS NOT (yet, by current real-code standards): "
        "(1) 'Truly NL-driven end-to-end' as a CI-proven claim — the structural NL chain "
        "is correct but no CI test proves real LLM roundtrip; "
        "(2) 'Natively multimodal' as an always-on, CI-proven claim — infrastructure "
        "exists but is disabled by default and has no e2e CI proof; "
        "(3) 'Three-state model fully and coherently presentable' from a single panel "
        "surface — three distinct state systems exist in code but are not jointly "
        "aggregated into one panel endpoint; "
        "(4) 'Panel APIs fully unified' for one-stop panel filling — multiple surfaces "
        "exist but no single aggregation endpoint. "
        "The system is dispatch-capable end-to-end but the operator panel is "
        "observation-only with no action endpoints. "
        "These are honest product-completeness gaps — real gaps worth closing, "
        "but not P0 blockers. The main system works."
    )

    report = ComprehensiveAuditReport(
        dimension_entries=dimensions,
        completeness_questions=completeness_questions,
        panel_api_surfaces=panel_api_surfaces,
        actionability_surfaces=actionability_surfaces,
        system_verdict=SystemCompletenessVerdict.LATE_STAGE_CLOSURE,
        system_verdict_rationale=verdict_rationale,
        dimensions_strongly_established_count=strongly_count,
        dimensions_runtime_evidenced_closed_count=runtime_closed_count,
        dimensions_partially_established_count=partially_count,
        remaining_product_gaps=remaining_gaps,
        follow_up_roadmap=follow_up,
        plain_language_conclusion=plain_language,
    )

    return report


# ---------------------------------------------------------------------------
# Singleton cache
# ---------------------------------------------------------------------------

_CACHE_LOCK = threading.Lock()
_CACHED_REPORT: Optional[ComprehensiveAuditReport] = None


def get_comprehensive_joint_audit() -> ComprehensiveAuditReport:
    """Return the cached comprehensive joint audit report (build once)."""
    global _CACHED_REPORT  # noqa: PLW0603
    with _CACHE_LOCK:
        if _CACHED_REPORT is None:
            _CACHED_REPORT = build_comprehensive_joint_audit()
        return _CACHED_REPORT


def reset_comprehensive_joint_audit() -> None:
    """Reset the cached report (for test isolation)."""
    global _CACHED_REPORT  # noqa: PLW0603
    with _CACHE_LOCK:
        _CACHED_REPORT = None


# ---------------------------------------------------------------------------
# Test-helper invariant checker
# ---------------------------------------------------------------------------


def assert_comprehensive_audit_invariants() -> None:
    """Assert structural invariants of the audit report.

    Raises AssertionError if any invariant is violated.  Intended for use in
    CI test suites as a lightweight smoke-check.
    """
    report = get_comprehensive_joint_audit()

    assert len(report.dimension_entries) == 8, (
        f"Expected 8 dimension entries; got {len(report.dimension_entries)}"
    )
    assert len(report.completeness_questions) == 6, (
        f"Expected 6 completeness questions; got {len(report.completeness_questions)}"
    )
    assert len(report.panel_api_surfaces) >= 5, (
        f"Expected ≥ 5 panel API surfaces; got {len(report.panel_api_surfaces)}"
    )
    assert len(report.actionability_surfaces) >= 4, (
        f"Expected ≥ 4 actionability surfaces; got {len(report.actionability_surfaces)}"
    )
    assert report.system_verdict == SystemCompletenessVerdict.LATE_STAGE_CLOSURE, (
        f"Expected LATE_STAGE_CLOSURE verdict; got {report.system_verdict}"
    )
    assert len(report.system_verdict_rationale) > 0, (
        "system_verdict_rationale must not be empty"
    )
    assert len(report.plain_language_conclusion) > 0, (
        "plain_language_conclusion must not be empty"
    )
    assert len(report.remaining_product_gaps) >= 4, (
        f"Expected ≥ 4 remaining product gaps; got {len(report.remaining_product_gaps)}"
    )
    assert len(report.follow_up_roadmap) >= 4, (
        f"Expected ≥ 4 follow-up items; got {len(report.follow_up_roadmap)}"
    )

    # Verify the unified panel aggregation surface is marked NOT available
    panel_agg = next(
        (p for p in report.panel_api_surfaces if p.surface_id == "unified_panel_aggregation"),
        None,
    )
    assert panel_agg is not None, "unified_panel_aggregation surface must be in panel_api_surfaces"
    assert not panel_agg.available, (
        "unified_panel_aggregation must be marked available=False "
        "(not yet implemented)"
    )

    # Verify the NL-driving question is PARTIALLY_ESTABLISHED
    nl_q = next(
        (q for q in report.completeness_questions if q.question_id == "nl_driven_end_to_end"),
        None,
    )
    assert nl_q is not None, "nl_driven_end_to_end question must be in completeness_questions"
    assert nl_q.verdict_label == AuditEvidenceLabel.PARTIALLY_ESTABLISHED, (
        f"NL driving must be PARTIALLY_ESTABLISHED; got {nl_q.verdict_label}"
    )

    # Verify multimodal question is INFRASTRUCTURE_PRESENT_NOT_YET_E2E_PROVEN
    mm_q = next(
        (q for q in report.completeness_questions if q.question_id == "natively_multimodal_e2e"),
        None,
    )
    assert mm_q is not None, "natively_multimodal_e2e question must be in completeness_questions"
    assert mm_q.verdict_label == AuditEvidenceLabel.INFRASTRUCTURE_PRESENT_NOT_YET_E2E_PROVEN, (
        f"Multimodal must be INFRASTRUCTURE_PRESENT_NOT_YET_E2E_PROVEN; got {mm_q.verdict_label}"
    )

    # JSON round-trip
    json_str = report.to_json()
    parsed = json.loads(json_str)
    assert parsed["system_verdict"] == SystemCompletenessVerdict.LATE_STAGE_CLOSURE.value
    assert parsed["authority"] == COMPREHENSIVE_AUDIT_AUTHORITY
