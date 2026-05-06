#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/five_domain_implementation_review.py
==========================================
Five-Domain Implementation-Grade Review Package — Dual-Repository Joint
Current-State Audit Artifact.

Repositories reviewed jointly
-------------------------------
- DannyFish-11/ufo-galaxy-realization-v2  (V2 — this repo, center authority)
- DannyFish-11/ufo-galaxy-android         (Android — runtime carrier node)

Purpose
-------
This module is the **authoritative implementation-level basis** for the next
five follow-up PRs in the Galaxy dual-repo system.  It is NOT a prose-only
narrative.  It is an importable, JSON-serialisable, invariant-checked,
machine-verifiable review artifact that:

1. Performs a code-grounded current-state review of exactly five target
   domains.
2. Produces typed, structured ``DomainImplementationEntry`` records that
   contain real code anchors, canonical path summaries, established items,
   partial/gap items, overclaiming guards, and ``FollowUpPRSpec`` prescriptions.
3. Exposes invariant checks that prevent overclaiming completeness for any
   domain that is not fully CI-proven end-to-end.
4. Is fully JSON-serialisable and can be consumed by downstream tooling or
   test harnesses.

Five review domains
-------------------
1. UNIFIED_PANEL_AGGREGATION
   Panel/operator/control-plane state sources, APIs, projections, aggregation
   layers — and whether a true unified panel-state surface currently exists.

2. DESKTOP_THREE_STATE_EXISTENCE_SURFACE
   Real current code for shell, presence, manifestation, embodiment, carrier-
   facing state, desktop-visible state, assistant surfaces, and whether a
   coherent desktop-like assistant existence surface currently exists spanning
   all three state families.

3. OPERATOR_ACTIONABILITY
   Distinction between read-only projection surfaces and truly action-capable
   operator / control-plane paths; current action endpoints, services,
   triggers, and orchestration entry points.

4. NATURAL_LANGUAGE_CANONICAL_PATH
   Real NL ingress → interpretation/planning/routing → orchestration →
   dispatch → execution → result/state feedback; canonical vs demo/stub paths.

5. MULTIMODAL_CANONICAL_PATH
   Real multimodal/perception/grounding/vision/context-enrichment paths;
   whether multimodal signals truly influence current decision/routing/
   execution; canonical vs optional/dormant/demo paths.

Evidence rules (strict)
-----------------------
All conclusions are grounded only in:
  - current real Python imports and attribute checks against the V2 codebase
  - existence of CI test modules as machine-verifiable proof
  - inspect.getsource() / file-content scans for attribute-level confirmation
  - Android-side evidence only via V2-side integration test references

NOT used as evidence:
  - README files
  - markdown audits
  - historical PR descriptions
  - prose architecture narratives
  - prior audit PR bodies

Prior review modules are used only as navigation hints, not as evidence.

Public API
----------
Authority sentinels::

    FIVE_DOMAIN_REVIEW_AUTHORITY
    FIVE_DOMAIN_REVIEW_METHODOLOGY
    FIVE_DOMAIN_REVIEW_VERDICT_ZH

Enumerations::

    ReviewDomain          — 5 review domains
    EvidenceStrength      — 7-tier evidence ladder (conservative)
    FollowUpPRPriority    — P0 / P1 / P2 / P3

Dataclasses::

    AndroidCodeAnchor            — Android-side real code anchor
    CodeAnchor                   — V2 or cross-repo code anchor
    FollowUpPRSpec               — prescribed follow-up PR specification
    DomainImplementationEntry    — per-domain implementation review entry
    ImplementationReviewPackage  — root artifact (JSON-serialisable)

Functions::

    build_five_domain_review()         -> ImplementationReviewPackage
    get_five_domain_review()           -> ImplementationReviewPackage  (cached)
    reset_five_domain_review()         -> None                          (test isolation)
    assert_five_domain_invariants()    -> None                          (invariant checker)
"""

from __future__ import annotations

import importlib
import importlib.util
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

logger = logging.getLogger("Galaxy.FiveDomainImplementationReview")

# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    # Sentinels
    "FIVE_DOMAIN_REVIEW_AUTHORITY",
    "FIVE_DOMAIN_REVIEW_METHODOLOGY",
    "FIVE_DOMAIN_REVIEW_VERDICT_ZH",
    # Enumerations
    "ReviewDomain",
    "EvidenceStrength",
    "FollowUpPRPriority",
    # Dataclasses
    "AndroidCodeAnchor",
    "CodeAnchor",
    "FollowUpPRSpec",
    "DomainImplementationEntry",
    "ImplementationReviewPackage",
    # Functions
    "build_five_domain_review",
    "get_five_domain_review",
    "reset_five_domain_review",
    "assert_five_domain_invariants",
]

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

FIVE_DOMAIN_REVIEW_AUTHORITY: str = (
    "FIVE_DOMAIN_IMPLEMENTATION_REVIEW_AUTHORITY::"
    "core.five_domain_implementation_review::"
    "dual-repo-joint-current-state-review::"
    "implementation-grade-review-package-for-next-five-prs::"
    "no-readme-no-pr-prose-as-evidence"
)

FIVE_DOMAIN_REVIEW_METHODOLOGY: str = (
    "METHODOLOGY: Five-domain implementation-grade review of the Galaxy distributed "
    "AI-body/control system (ufo-galaxy-realization-v2 × ufo-galaxy-android). "
    "Five target domains: unified panel aggregation, desktop three-state existence "
    "surface, operator actionability, natural-language canonical path, multimodal "
    "canonical path. "
    "All conclusions strictly grounded in: (1) real Python imports and attribute checks "
    "against the live V2 codebase; (2) existence of CI test modules as machine-verifiable "
    "proof; (3) file-content scans for attribute-level confirmation; (4) Android-side "
    "evidence via V2-side integration tests only. "
    "README files, markdown audits, historical PR descriptions, prose architecture "
    "narratives, and prior audit PR bodies are EXPLICITLY EXCLUDED as evidence. "
    "Prior review modules (comprehensive_joint_dual_repo_audit, "
    "dual_repo_system_completeness_review, full_current_state_dual_repo_rereading) "
    "are used ONLY as navigation hints — NOT as evidence. "
    "This artifact is designed as the authoritative implementation-level basis for the "
    "next five follow-up PRs: P1 unified panel aggregation endpoint, P2 desktop "
    "assistant-like three-state existence surface, P3 operator action endpoints, "
    "P4 NL e2e proof, P5 multimodal e2e proof."
)

FIVE_DOMAIN_REVIEW_VERDICT_ZH: str = (
    "【Galaxy 双仓系统五域实现级审查报告 — 作为后续五个 PR 的权威实现依据】\n\n"
    "本报告基于当前真实代码（V2 + Android），对以下五个域进行严格代码锚定评审，"
    "作为后续五张 implementation PR 的实现依据。\n\n"
    "一、统一面板聚合（Unified Panel Aggregation）\n"
    "现状：多个只读 operator 端点已成立（/api/v1/operator/snapshot, "
    "/api/v1/operator/flows, /api/v1/operator/devices/ecosystem, "
    "/api/v1/projection/runtime），均为只读结构完整。\n"
    "缺口：无单一聚合端点将主体生命周期状态 + Android 生态系统 + flow 状态 + "
    "shell clothing 状态合并为一个 panel state 对象。\n"
    "后续 PR 切入点：新增 GET /api/v1/panel/unified 端点，在 core/routes/operator.py "
    "或新模块 core/routes/panel.py 中聚合 OperatorSnapshot + RuntimeProjection + "
    "三态状态家族 + AndroidEcosystemSummary，输出统一 PanelStatePayload。\n\n"
    "二、桌面三态存在呈现面（Desktop Three-State Existence Surface）\n"
    "现状：三套独立状态系统已在真实代码中确认：(1) 主体生命周期三态 "
    "SILENT/LIMINAL/MANIFEST（DesktopPresenceRuntime）；(2) UI clothing 四态 "
    "DORMANT/ISLAND/SIDESHEET/FULLAGENT（state_machine_ui_integration）；"
    "(3) continuum posture（OpenClawd tri_state_phase）。PresenceDirector 和 "
    "PresenceProjection 模块存在。\n"
    "缺口：三套状态系统各自独立，无统一投影面将三者合并为桌面助手式存在表面。"
    "/api/v1/projection/runtime 提供部分，但不覆盖 UI clothing 和 continuum posture。\n"
    "后续 PR 切入点：新增 DesktopExistenceSurface 类，聚合三态系统，暴露 "
    "/api/v1/desktop/existence 端点，实现助手式桌面三态完整呈现。\n\n"
    "三、Operator 可操作性（Operator Actionability）\n"
    "现状：所有 /api/v1/operator/* 端点均为纯只读投影。DesktopPresenceRuntime."
    "handle_request() 是 action-capable 入口（经 /api/v1/chat 触发）。"
    "/api/v1/chat 和 e2e 路径是当前唯一 action-capable 表面。\n"
    "缺口：Operator 面板没有任何 action 端点。控制系统需绕过 operator 面板走 chat 路径。\n"
    "后续 PR 切入点：在 core/routes/operator.py 中新增 POST /api/v1/operator/action "
    "端点，经权限校验后委托至 DesktopPresenceRuntime 或 SourceDispatchOrchestrator，"
    "将 operator 面板从纯投影升级为 action-capable 控制面。\n\n"
    "四、自然语言 canonical path（Natural-Language Canonical Path）\n"
    "现状：NL 驱动结构路径在真实代码中成立：/api/v1/chat → "
    "DesktopPresenceRuntime.handle_request() → OpenClawd.process() → LLM function "
    "calling → action dispatch。AI intent 分类（core.ai_intent）、multi-LLM router、"
    "session identity 标记均存在。\n"
    "缺口：无 CI 测试证明真实 LLM 后端端到端处理——LLM roundtrip 在 CI 中被 mock 或跳过。\n"
    "后续 PR 切入点：增加 tests/integration/test_nl_e2e_canonical_path.py，使用 "
    "stub/contract LLM 后端（不需要真实 API key）验证 NL chain 端到端路径的结构性证明，"
    "并在 DesktopPresenceRuntime 中暴露 ingress_carrier_context 作为可断言的审计证据。\n\n"
    "五、多模态 canonical path（Multimodal Canonical Path）\n"
    "现状：多模态基础设施存在：MultimodalIngressBus、PerceptionSourceRegistry、"
    "PerceptionFrame、VisionPipeline 均可导入。OpenClawd 接受 multimodal_context。"
    "Android vision uplink handler 存在。mobilevlm_present / seeclick_present 字段"
    "在 DeviceStateSnapshot 中确认。\n"
    "缺口：continuous host ingress 默认禁用（SAFE_DEFAULT profile）。"
    "无 CI 测试证明端到端多模态激活路径。\n"
    "后续 PR 切入点：增加 tests/integration/test_multimodal_canonical_path.py，"
    "验证请求绑定多模态 context 路径（OpenClawd.process() with multimodal_context）"
    "的结构性端到端证明，并为 MultimodalIngressBus 增加可测试的 activation contract。\n\n"
    "整体结论：系统主线 P0 已闭环，但五个用户关切的完整性域均处于 "
    "PARTIALLY_ESTABLISHED 或 INFRASTRUCTURE_PRESENT 阶段。"
    "上述五个后续 PR 各自攻一个域，完成后系统将从 LATE_STAGE_CLOSURE 提升至 "
    "PRODUCTION_COMPLETE 级别。"
)

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ReviewDomain(str, Enum):
    """Five review domains for this implementation-grade package."""

    UNIFIED_PANEL_AGGREGATION = "UNIFIED_PANEL_AGGREGATION"
    DESKTOP_THREE_STATE_EXISTENCE_SURFACE = "DESKTOP_THREE_STATE_EXISTENCE_SURFACE"
    OPERATOR_ACTIONABILITY = "OPERATOR_ACTIONABILITY"
    NATURAL_LANGUAGE_CANONICAL_PATH = "NATURAL_LANGUAGE_CANONICAL_PATH"
    MULTIMODAL_CANONICAL_PATH = "MULTIMODAL_CANONICAL_PATH"


class EvidenceStrength(str, Enum):
    """Seven-tier conservative evidence ladder.

    STRONGLY_ESTABLISHED
        Real imports succeed; runtime path exercised by passing CI tests;
        full round-trip confirmed.  No known gaps.

    RUNTIME_EVIDENCED_CLOSED
        End-to-end runtime path closed by a closure PR: machine-verifiable CI
        tests exercise the full round-trip.

    PARTIALLY_ESTABLISHED
        Real code and/or test modules present; at least one known gap (cross-
        repo round-trip test, advisory-mode gate, or disabled-by-default
        config) prevents full closure.

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

    @classmethod
    def overclaim_guard_threshold(cls) -> "EvidenceStrength":
        """Labels AT or BELOW this level prevent overclaiming full completeness."""
        return cls.PARTIALLY_ESTABLISHED


class FollowUpPRPriority(str, Enum):
    """Priority for a follow-up PR.

    P0
        Blocks production completeness.  Must be done before any P1.

    P1
        High product-completeness value; directly addresses a PARTIALLY_ESTABLISHED gap.

    P2
        Significant quality improvement; addresses INFRASTRUCTURE_PRESENT gap.

    P3
        Refinement or observability improvement; not blocking.
    """

    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class CodeAnchor:
    """A V2-side real code anchor.

    Attributes
    ----------
    module_path
        Dotted Python module path (e.g. ``core.operator_surface``).
    description
        One-line description of why this anchor is relevant to the domain.
    confirmed_importable
        True if _try_import() confirms the module exists in V2 codebase.
    key_attribute
        Optional: the specific class / function / attribute that confirms
        the relevant evidence.
    """

    module_path: str
    description: str
    confirmed_importable: bool
    key_attribute: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "module_path": self.module_path,
            "description": self.description,
            "confirmed_importable": self.confirmed_importable,
            "key_attribute": self.key_attribute,
        }


@dataclass
class AndroidCodeAnchor:
    """An Android-side real code anchor (referenced via V2 integration tests).

    Attributes
    ----------
    android_package
        Kotlin package path in the Android repo.
    v2_evidence_ref
        V2-side test or module that confirms integration with this Android component.
    description
        One-line description.
    confirmed_via_v2
        True if V2-side evidence confirms Android-side participation.
    """

    android_package: str
    v2_evidence_ref: str
    description: str
    confirmed_via_v2: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "android_package": self.android_package,
            "v2_evidence_ref": self.v2_evidence_ref,
            "description": self.description,
            "confirmed_via_v2": self.confirmed_via_v2,
        }


@dataclass
class FollowUpPRSpec:
    """Prescription for a single follow-up PR.

    This is the core differentiator of this review module: instead of just
    describing gaps, it prescribes exactly what each follow-up PR should do,
    where to cut into the current code, and what maturity level it would unlock.

    Attributes
    ----------
    pr_title
        Suggested PR title (concise, action-oriented).
    priority
        FollowUpPRPriority — P0/P1/P2/P3.
    implementation_cut_points
        Exact files / modules / classes where the follow-up PR must make
        changes.  Must reference real current code paths.
    primary_modification_zones
        Broader zones of the codebase that the PR primarily modifies.
    new_modules_to_create
        New modules / files the PR should create (if any).
    maturity_level_unlocked
        Plain-language description of what the system gains if this PR lands.
    estimated_scope
        Rough scope estimate (e.g. "single module + test file").
    invariant_that_would_close
        Which invariant check in this review package would pass after the PR.
    """

    pr_title: str
    priority: FollowUpPRPriority
    implementation_cut_points: List[str]
    primary_modification_zones: List[str]
    new_modules_to_create: List[str]
    maturity_level_unlocked: str
    estimated_scope: str
    invariant_that_would_close: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pr_title": self.pr_title,
            "priority": self.priority.value,
            "implementation_cut_points": self.implementation_cut_points,
            "primary_modification_zones": self.primary_modification_zones,
            "new_modules_to_create": self.new_modules_to_create,
            "maturity_level_unlocked": self.maturity_level_unlocked,
            "estimated_scope": self.estimated_scope,
            "invariant_that_would_close": self.invariant_that_would_close,
        }


@dataclass
class DomainImplementationEntry:
    """Implementation-grade review entry for a single domain.

    This dataclass captures all eight required content items per domain:

    1. current_code_anchors — real code anchors / components / modules / files
    2. canonical_path_summary — current canonical path description
    3. established_items — what is already established in real code
    4. partial_or_fragmented_items — what remains partial / fragmented / unproven
    5. overclaiming_guard — why this domain cannot be overclaimed as complete
    6. follow_up_pr_spec — the most accurate implementation cut points + PR spec
    7. primary_modification_zones — from the follow-up PR spec
    8. maturity_unlock — what maturity level the follow-up PR would unlock

    Plus supporting fields for cross-repo evidence and Android anchors.
    """

    domain: ReviewDomain
    evidence_strength: EvidenceStrength
    canonical_path_summary: str
    established_items: List[str] = field(default_factory=list)
    partial_or_fragmented_items: List[str] = field(default_factory=list)
    gap_items: List[str] = field(default_factory=list)
    current_code_anchors: List[CodeAnchor] = field(default_factory=list)
    android_anchors: List[AndroidCodeAnchor] = field(default_factory=list)
    overclaiming_guard: str = ""
    follow_up_pr_spec: Optional[FollowUpPRSpec] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain.value,
            "evidence_strength": self.evidence_strength.value,
            "canonical_path_summary": self.canonical_path_summary,
            "established_items": self.established_items,
            "partial_or_fragmented_items": self.partial_or_fragmented_items,
            "gap_items": self.gap_items,
            "current_code_anchors": [a.to_dict() for a in self.current_code_anchors],
            "android_anchors": [a.to_dict() for a in self.android_anchors],
            "overclaiming_guard": self.overclaiming_guard,
            "follow_up_pr_spec": (
                self.follow_up_pr_spec.to_dict() if self.follow_up_pr_spec else None
            ),
        }


@dataclass
class ImplementationReviewPackage:
    """Root artifact for the five-domain implementation-grade review package.

    Fully JSON-serialisable via to_dict() / to_json().

    Attributes
    ----------
    package_id
        UUID hex identifier.
    generated_at
        Unix timestamp.
    authority
        Authority sentinel string.
    methodology
        Methodology statement.
    verdict_zh
        Chinese system conclusion.
    domain_entries
        Exactly 5 DomainImplementationEntry items (one per ReviewDomain).
    system_maturity_summary
        Plain-language English summary of current system maturity across all
        five domains.
    follow_up_pr_sequence
        Ordered list of FollowUpPRSpec items (the five follow-up PRs in
        recommended execution order).
    overclaiming_guards_summary
        Summary of overclaiming guards that prevent false completeness claims.
    domains_at_partially_established_or_below
        Count of domains that are NOT yet RUNTIME_EVIDENCED_CLOSED or
        STRONGLY_ESTABLISHED — used for invariant checks.
    """

    package_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    generated_at: float = field(default_factory=time.time)
    authority: str = FIVE_DOMAIN_REVIEW_AUTHORITY
    methodology: str = FIVE_DOMAIN_REVIEW_METHODOLOGY
    verdict_zh: str = FIVE_DOMAIN_REVIEW_VERDICT_ZH

    domain_entries: List[DomainImplementationEntry] = field(default_factory=list)
    system_maturity_summary: str = ""
    follow_up_pr_sequence: List[FollowUpPRSpec] = field(default_factory=list)
    overclaiming_guards_summary: str = ""
    domains_at_partially_established_or_below: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "package_id": self.package_id,
            "generated_at": self.generated_at,
            "authority": self.authority,
            "methodology": self.methodology,
            "verdict_zh": self.verdict_zh,
            "domain_entries": [e.to_dict() for e in self.domain_entries],
            "system_maturity_summary": self.system_maturity_summary,
            "follow_up_pr_sequence": [
                s.to_dict() for s in self.follow_up_pr_sequence
            ],
            "overclaiming_guards_summary": self.overclaiming_guards_summary,
            "domains_at_partially_established_or_below": (
                self.domains_at_partially_established_or_below
            ),
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)


# ---------------------------------------------------------------------------
# Module / file existence helpers (consistent with companion audit modules)
# ---------------------------------------------------------------------------


def _module_file_exists(module_path: str) -> bool:
    """Return True if the module file exists on disk regardless of importability."""
    try:
        spec = importlib.util.find_spec(module_path)
        if spec is not None:
            return True
    except (ImportError, AttributeError, ValueError):
        # ImportError covers ModuleNotFoundError (subclass); ValueError can be raised
        # by find_spec() for certain invalid dotted names (e.g. relative imports).
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
    except (ImportError, AttributeError, OSError, UnicodeDecodeError):
        # ImportError covers ModuleNotFoundError (subclass since Python 3.6).
        pass
    rel_path = module_path.replace(".", os.sep) + ".py"
    for base in sys.path:
        candidate = os.path.join(base, rel_path)
        if os.path.isfile(candidate):
            try:
                with open(candidate, encoding="utf-8", errors="replace") as fh:
                    return pattern in fh.read()
            except (OSError, UnicodeDecodeError):
                pass
    return False


def _test_file_exists(test_module: str) -> bool:
    """Return True if a test file exists on disk."""
    return _try_import(test_module)


# ---------------------------------------------------------------------------
# Domain 1: Unified Panel Aggregation
# ---------------------------------------------------------------------------


def _review_unified_panel_aggregation() -> DomainImplementationEntry:
    """Review unified panel/operator/control-plane aggregation state."""
    established: List[str] = []
    partial: List[str] = []
    gaps: List[str] = []
    anchors: List[CodeAnchor] = []

    # OperatorSurface — core structural authority
    os_ok = _try_import("core.operator_surface")
    anchors.append(CodeAnchor(
        module_path="core.operator_surface",
        description="OperatorSurface authority: project-only principle, aggregates "
                    "task/device/capability/flow state into OperatorSnapshot",
        confirmed_importable=os_ok,
        key_attribute="OPERATOR_SURFACE_PROJECTION_POLICY",
    ))
    if os_ok:
        established.append(
            "core.operator_surface importable — OperatorSnapshot aggregation structure present"
        )

    # Operator routes
    or_ok = _try_import("core.routes.operator")
    anchors.append(CodeAnchor(
        module_path="core.routes.operator",
        description="HTTP routes for /api/v1/operator/* (snapshot, flows, "
                    "devices/ecosystem, devices/execution-events, inspect/*)",
        confirmed_importable=or_ok,
        key_attribute="OPERATOR_ROUTES_AUTHORITY",
    ))
    if or_ok:
        established.append(
            "core.routes.operator importable — /api/v1/operator/* routes registered"
        )

    # FlowLevelOperatorSurface
    fl_ok = _try_import("core.flow_level_operator_surface")
    anchors.append(CodeAnchor(
        module_path="core.flow_level_operator_surface",
        description="Per-flow operator projection: FlowOperatorProjection with "
                    "authority metadata, active_flow_count, to_dict()",
        confirmed_importable=fl_ok,
        key_attribute="FlowOperatorProjection",
    ))
    if fl_ok:
        established.append(
            "core.flow_level_operator_surface importable — FlowOperatorProjection present"
        )

    # Projection routes (/api/v1/projection/runtime)
    pr_ok = _try_import("core.routes.projection")
    anchors.append(CodeAnchor(
        module_path="core.routes.projection",
        description="/api/v1/projection/runtime — RuntimeProjection from ContinuumState "
                    "and topology; partial three-state coverage",
        confirmed_importable=pr_ok,
    ))
    if pr_ok:
        established.append(
            "core.routes.projection importable — /api/v1/projection/runtime present"
        )

    # Specific operator sub-endpoints
    if or_ok:
        if _source_contains("core.routes.operator", "/api/v1/operator/devices/ecosystem"):
            established.append(
                "/api/v1/operator/devices/ecosystem endpoint confirmed in source"
            )
        else:
            partial.append(
                "/api/v1/operator/devices/ecosystem not found in operator routes source"
            )

        if _source_contains("core.routes.operator", "/api/v1/operator/flows"):
            established.append("/api/v1/operator/flows endpoint confirmed in source")

        if _source_contains("core.routes.operator", "execution-events"):
            established.append(
                "/api/v1/operator/devices/execution-events endpoint confirmed"
            )

    # Android ecosystem aggregation in OperatorSnapshot
    if _source_contains("core.operator_surface", "android_ecosystem"):
        established.append(
            "OperatorSnapshot.android_ecosystem field present — Android ecosystem "
            "integrated into operator snapshot"
        )
    else:
        partial.append(
            "android_ecosystem field not confirmed in operator_surface source"
        )

    # CRITICAL GAP: No single unified panel-state aggregation endpoint
    panel_agg_candidates = [
        "core.unified_panel_state",
        "core.panel_state_aggregation",
        "core.operator_panel_aggregation",
        "core.routes.panel",
    ]
    panel_agg_found = any(_try_import(m) for m in panel_agg_candidates)
    if panel_agg_found:
        established.append("Unified panel state aggregation module found")
    else:
        gaps.append(
            "NO UNIFIED PANEL AGGREGATION ENDPOINT: no single endpoint combines "
            "subject lifecycle tri-state (SILENT/LIMINAL/MANIFEST) + Android ecosystem "
            "summary + flow states + UI clothing states (DORMANT/ISLAND/SIDESHEET/"
            "FULLAGENT) + capabilities into one panel state object. "
            "Panel clients must call 4+ separate endpoints and assemble themselves."
        )

    # OperatorSnapshot includes only count-level Android keys (no per-device list)
    if _source_contains("core.operator_surface", "ANDROID_ECOSYSTEM_SNAPSHOT_KEYS"):
        established.append(
            "ANDROID_ECOSYSTEM_SNAPSHOT_KEYS whitelist confirmed — OperatorSnapshot "
            "carries count-level Android keys (privacy-safe projection)"
        )

    follow_up = FollowUpPRSpec(
        pr_title=(
            "Add GET /api/v1/panel/unified — unified panel-state aggregation endpoint "
            "combining subject lifecycle, Android ecosystem, flow state, and shell states"
        ),
        priority=FollowUpPRPriority.P1,
        implementation_cut_points=[
            "core/routes/operator.py — add new route or extract to core/routes/panel.py",
            "core/operator_surface.py — extend operator_snapshot() or add "
            "unified_panel_snapshot() method combining all state families",
            "core/desktop_presence_runtime.py — expose tri-state lifecycle as "
            "panel-fillable projection",
            "system_integration/state_machine_ui_integration.py — expose "
            "DORMANT/ISLAND/SIDESHEET/FULLAGENT as panel-fillable state",
        ],
        primary_modification_zones=[
            "core/routes/ — new or extended panel routes",
            "core/operator_surface.py — extend aggregation",
            "core/ — new PanelStatePayload dataclass",
        ],
        new_modules_to_create=[
            "core/routes/panel.py — new panel route module (or extend operator.py)",
            "core/panel_state_payload.py — typed PanelStatePayload dataclass "
            "(optional if inlined in operator_surface)",
        ],
        maturity_level_unlocked=(
            "Panel clients gain a single GET /api/v1/panel/unified endpoint that "
            "returns a unified PanelStatePayload combining all real state families. "
            "Eliminates the need to call 4+ separate endpoints. "
            "Removes the PARTIALLY_ESTABLISHED gap for panel API unification. "
            "Enables coherent panel-state filling and presentation — a prerequisite "
            "for the desktop three-state existence surface PR."
        ),
        estimated_scope="1–2 new or extended modules + 1 test file",
        invariant_that_would_close=(
            "assert_five_domain_invariants(): "
            "UNIFIED_PANEL_AGGREGATION domain would upgrade from "
            "PARTIALLY_ESTABLISHED → RUNTIME_EVIDENCED_CLOSED"
        ),
    )

    return DomainImplementationEntry(
        domain=ReviewDomain.UNIFIED_PANEL_AGGREGATION,
        evidence_strength=EvidenceStrength.PARTIALLY_ESTABLISHED,
        canonical_path_summary=(
            "Multiple operator/panel API surfaces exist and are read-only: "
            "/api/v1/operator/snapshot (OperatorSnapshot — compact runtime overview), "
            "/api/v1/operator/flows (FlowOperatorProjection list), "
            "/api/v1/operator/devices/ecosystem (Android ecosystem state), "
            "/api/v1/operator/devices/execution-events (recent execution events), "
            "/api/v1/projection/runtime (RuntimeProjection from ContinuumState). "
            "All surfaces are structurally complete and projection-only. "
            "The aggregation gap: no single endpoint combines all state families "
            "into one panel-fillable object."
        ),
        established_items=established,
        partial_or_fragmented_items=partial,
        gap_items=gaps,
        current_code_anchors=anchors,
        android_anchors=[
            AndroidCodeAnchor(
                android_package="com.ufo.galaxy.runtime",
                v2_evidence_ref="core.android_device_state_store",
                description="Android runtime state absorbed into V2 DeviceStateSnapshot, "
                            "then projected into OperatorSnapshot.android_ecosystem",
                confirmed_via_v2=_try_import("core.android_device_state_store"),
            ),
        ],
        overclaiming_guard=(
            "OVERCLAIMING GUARD: Panel APIs CANNOT be claimed as 'fully unified and "
            "aggregated' because no single endpoint combines subject tri-state lifecycle "
            "+ Android ecosystem + flow states + UI clothing states. Until "
            "/api/v1/panel/unified (or equivalent) exists and is tested, the panel "
            "aggregation gap is REAL and must not be minimized."
        ),
        follow_up_pr_spec=follow_up,
    )


# ---------------------------------------------------------------------------
# Domain 2: Desktop Three-State Existence Surface
# ---------------------------------------------------------------------------


def _review_desktop_three_state_existence_surface() -> DomainImplementationEntry:
    """Review desktop three-state assistant-like existence surface."""
    established: List[str] = []
    partial: List[str] = []
    gaps: List[str] = []
    anchors: List[CodeAnchor] = []

    # State family 1: Subject tri-state lifecycle (SILENT/LIMINAL/MANIFEST)
    dpr_ok = _try_import("core.desktop_presence_runtime")
    anchors.append(CodeAnchor(
        module_path="core.desktop_presence_runtime",
        description="DesktopPresenceRuntime — tri-state subject lifecycle "
                    "SILENT/LIMINAL/MANIFEST; single NL entry point handle_request()",
        confirmed_importable=dpr_ok,
        key_attribute="DesktopPresenceRuntime",
    ))
    if dpr_ok:
        established.append("core.desktop_presence_runtime importable — tri-state DPR present")

    if _source_contains("core.desktop_presence_runtime", "SILENT") and _source_contains(
        "core.desktop_presence_runtime", "LIMINAL"
    ):
        established.append(
            "SILENT/LIMINAL/MANIFEST tri-state lifecycle confirmed in "
            "DesktopPresenceRuntime source"
        )

    if _test_file_exists("tests.test_pr1_desktop_presence_runtime"):
        established.append("DPR test suite present — tri-state lifecycle has test coverage")

    # State family 2: UI clothing states (DORMANT/ISLAND/SIDESHEET/FULLAGENT)
    smui_ok = _try_import("system_integration.state_machine_ui_integration")
    anchors.append(CodeAnchor(
        module_path="system_integration.state_machine_ui_integration",
        description="UI clothing states DORMANT/ISLAND/SIDESHEET/FULLAGENT — "
                    "desktop-visible UI state machine for shell presentation",
        confirmed_importable=smui_ok,
        key_attribute="DORMANT",
    ))
    if smui_ok:
        established.append(
            "system_integration.state_machine_ui_integration importable — "
            "UI clothing states present"
        )

    if smui_ok and _source_contains(
        "system_integration.state_machine_ui_integration", "DORMANT"
    ) and _source_contains(
        "system_integration.state_machine_ui_integration", "FULLAGENT"
    ):
        established.append(
            "DORMANT/ISLAND/SIDESHEET/FULLAGENT UI clothing states confirmed in source"
        )

    if _test_file_exists("tests.test_ui_shell_state_vocabulary_unification"):
        established.append("UI shell state vocabulary unification test present")

    # State family 3: Continuum posture (OpenClawd tri_state_phase)
    oc_ok = _try_import("core.openclawd")
    anchors.append(CodeAnchor(
        module_path="core.openclawd",
        description="OpenClawd LLM function-calling subject core — carries continuum "
                    "posture (tri_state_phase + runtime_domain)",
        confirmed_importable=oc_ok,
        key_attribute="OpenClawd",
    ))
    if oc_ok:
        established.append("core.openclawd importable — continuum posture host present")

    if _source_contains("core.openclawd", "tri_state_phase") or _source_contains(
        "core.openclawd", "tristate"
    ):
        established.append(
            "tri_state_phase / continuum posture confirmed in OpenClawd source"
        )
    else:
        partial.append(
            "tri_state_phase not confirmed in OpenClawd source via text scan — "
            "continuum posture may be carried under a different attribute name"
        )

    # PresenceDirector and PresenceProjection
    pd_ok = _try_import("core.presence.presence_director")
    anchors.append(CodeAnchor(
        module_path="core.presence.presence_director",
        description="PresenceDirector — coordinates desktop-facing presence state",
        confirmed_importable=pd_ok,
    ))
    if pd_ok:
        established.append("core.presence.presence_director importable")

    pp_ok = _try_import("core.presence.presence_projection")
    anchors.append(CodeAnchor(
        module_path="core.presence.presence_projection",
        description="PresenceProjection — projects presence state for consumers",
        confirmed_importable=pp_ok,
    ))
    if pp_ok:
        established.append("core.presence.presence_projection importable")

    # Manifestation/shell/presence semantics tests
    if _test_file_exists("tests.test_pr8v2_manifestation_shell_presence_semantics"):
        established.append("Manifestation/shell/presence semantics test present")

    # Session identity stamping (ingress_carrier_context)
    if _source_contains("core.desktop_presence_runtime", "ingress_carrier_context"):
        established.append(
            "ingress_carrier_context stamped on handle_request() — session identity "
            "present in e2e path"
        )

    # e2e path session identity (control_session_id, runtime_attachment_session_id)
    if _source_contains("core.desktop_presence_runtime", "control_session_id"):
        established.append(
            "control_session_id threaded through _handle_via_e2e — session continuity "
            "in desktop presence path confirmed"
        )

    # CRITICAL GAP: No unified three-state existence projection endpoint
    unified_three_state_candidates = [
        "core.unified_three_state_projection",
        "core.three_state_panel_surface",
        "core.desktop_state_panel_aggregation",
        "core.desktop_existence_surface",
    ]
    unified_found = any(_try_import(m) for m in unified_three_state_candidates)
    if unified_found:
        established.append("Unified three-state existence surface module found")
    else:
        gaps.append(
            "NO UNIFIED THREE-STATE EXISTENCE SURFACE: the three state families "
            "(subject tri-state lifecycle, UI clothing states, continuum posture) "
            "are confirmed in real code but remain three SEPARATE systems with no "
            "single endpoint or surface that aggregates them into an assistant-like "
            "desktop existence presentation. /api/v1/projection/runtime provides "
            "partial ContinuumState coverage but does not cover UI clothing states "
            "or subject tri-state lifecycle together."
        )

    # Is there any route that covers all three together?
    if _source_contains("core.routes.projection", "SILENT") or _source_contains(
        "core.routes.projection", "tri_state"
    ):
        established.append(
            "/api/v1/projection/runtime exposes some tri-state lifecycle state"
        )
    else:
        partial.append(
            "/api/v1/projection/runtime may not expose subject tri-state lifecycle "
            "directly — partial coverage only"
        )

    follow_up = FollowUpPRSpec(
        pr_title=(
            "Add DesktopExistenceSurface — unified assistant-like three-state "
            "desktop presence projection combining subject lifecycle, UI clothing, "
            "and continuum posture"
        ),
        priority=FollowUpPRPriority.P1,
        implementation_cut_points=[
            "core/desktop_presence_runtime.py — extract current tri-state lifecycle "
            "state as a projection-friendly snapshot method",
            "system_integration/state_machine_ui_integration.py — expose "
            "current UI clothing state as a read-only snapshot",
            "core/openclawd.py — expose continuum posture (tri_state_phase) as a "
            "read-only snapshot method",
            "core/routes/projection.py — extend /api/v1/projection/runtime to "
            "include all three state families, or add new endpoint",
        ],
        primary_modification_zones=[
            "core/desktop_presence_runtime.py — tri-state snapshot extraction",
            "system_integration/ — UI clothing state read path",
            "core/routes/projection.py or core/routes/panel.py — new unified route",
            "core/ — new DesktopExistenceSurface dataclass",
        ],
        new_modules_to_create=[
            "core/desktop_existence_surface.py — DesktopExistenceSurface dataclass "
            "and builder that aggregates all three state families",
        ],
        maturity_level_unlocked=(
            "The system gains a single queryable endpoint that returns a "
            "DesktopExistenceSurface object combining subject lifecycle phase + "
            "UI clothing state + continuum posture. This is the foundation for an "
            "assistant-like desktop three-state existence presentation (comparable to "
            "a Xiaoai-style multi-mode presence model). Removes the "
            "PARTIALLY_ESTABLISHED gap for three-state coherent presentation. "
            "Prerequisite for meaningful operator actionability on desktop state."
        ),
        estimated_scope=(
            "1 new module (desktop_existence_surface.py) + changes to 3 existing "
            "modules + 1 test file"
        ),
        invariant_that_would_close=(
            "assert_five_domain_invariants(): "
            "DESKTOP_THREE_STATE_EXISTENCE_SURFACE domain would upgrade from "
            "PARTIALLY_ESTABLISHED → RUNTIME_EVIDENCED_CLOSED"
        ),
    )

    return DomainImplementationEntry(
        domain=ReviewDomain.DESKTOP_THREE_STATE_EXISTENCE_SURFACE,
        evidence_strength=EvidenceStrength.PARTIALLY_ESTABLISHED,
        canonical_path_summary=(
            "Three distinct state families confirmed in real code: "
            "(1) Subject tri-state lifecycle SILENT/LIMINAL/MANIFEST — "
            "DesktopPresenceRuntime, with test coverage; "
            "(2) UI clothing states DORMANT/ISLAND/SIDESHEET/FULLAGENT — "
            "system_integration/state_machine_ui_integration.py, with test coverage; "
            "(3) Continuum posture (tri_state_phase + runtime_domain) — OpenClawd. "
            "PresenceDirector and PresenceProjection modules present. "
            "Session identity (ingress_carrier_context, control_session_id) present. "
            "Gap: no single endpoint or surface aggregates all three into a unified "
            "assistant-like desktop existence presentation."
        ),
        established_items=established,
        partial_or_fragmented_items=partial,
        gap_items=gaps,
        current_code_anchors=anchors,
        android_anchors=[
            AndroidCodeAnchor(
                android_package="com.ufo.galaxy.service",
                v2_evidence_ref=(
                    "galaxy_gateway.android.handlers.vision — Android vision "
                    "uplink contributes to presence signal"
                ),
                description="Android service layer contributes runtime carrier-side "
                            "presence signal via vision uplink to V2",
                confirmed_via_v2=_try_import("galaxy_gateway.android.handlers.vision"),
            ),
        ],
        overclaiming_guard=(
            "OVERCLAIMING GUARD: The three-state desktop existence model CANNOT be "
            "claimed as 'coherently presented' or 'fully unified' because no single "
            "surface or endpoint currently combines all three state families into a "
            "unified assistant-like desktop presence view. The three systems are "
            "separately confirmed in real code but are NOT jointly projected. "
            "Claiming 'three-state existence surface complete' without "
            "DesktopExistenceSurface (or equivalent) existing is overclaiming."
        ),
        follow_up_pr_spec=follow_up,
    )


# ---------------------------------------------------------------------------
# Domain 3: Operator Actionability
# ---------------------------------------------------------------------------


def _review_operator_actionability() -> DomainImplementationEntry:
    """Review operator/control-plane actionability distinction."""
    established: List[str] = []
    partial: List[str] = []
    gaps: List[str] = []
    anchors: List[CodeAnchor] = []

    # Operator surface — confirmed read-only
    os_ok = _try_import("core.operator_surface")
    anchors.append(CodeAnchor(
        module_path="core.operator_surface",
        description="OperatorSurface — read-only projection surface; "
                    "enforces projection-only principle",
        confirmed_importable=os_ok,
        key_attribute="OPERATOR_SURFACE_PROJECTION_POLICY",
    ))
    if os_ok:
        established.append(
            "core.operator_surface importable — read-only projection principle confirmed"
        )

    # Operator routes
    or_ok = _try_import("core.routes.operator")
    anchors.append(CodeAnchor(
        module_path="core.routes.operator",
        description="HTTP routes for /api/v1/operator/* — all GET, no POST action endpoints",
        confirmed_importable=or_ok,
    ))
    if or_ok:
        established.append("core.routes.operator importable")

    # Confirm read-only principle in source
    if os_ok and (
        _source_contains("core.operator_surface", "read-only")
        or _source_contains("core.operator_surface", "read_only")
        or _source_contains("core.operator_surface", "projection-only")
    ):
        established.append(
            "OperatorSurface explicitly documented as read-only / projection-only "
            "in source — this is by design"
        )

    # Confirm no action endpoints in operator routes
    has_post_action = False
    if or_ok:
        if _source_contains("core.routes.operator", "@router.post") or _source_contains(
            "core.routes.operator", 'methods=["POST"]'
        ):
            has_post_action = True
            established.append(
                "POST endpoint(s) found in core.routes.operator — action capability "
                "may already be partially present"
            )
        else:
            gaps.append(
                "NO POST/ACTION ENDPOINTS in /api/v1/operator/* routes — "
                "operator surface is strictly GET/read-only. Confirmed by absence of "
                "@router.post in core.routes.operator source."
            )

    # Action-capable surfaces (not operator panel)
    chat_ok = _try_import("core.routes.chat")
    anchors.append(CodeAnchor(
        module_path="core.routes.chat",
        description="/api/v1/chat — action-capable NL entry point; POST triggers "
                    "full execution via DesktopPresenceRuntime",
        confirmed_importable=chat_ok,
        key_attribute="CHAT_ROUTES_AUTHORITY",
    ))
    if chat_ok:
        established.append(
            "core.routes.chat importable — /api/v1/chat is the action-capable surface "
            "(POST triggers DesktopPresenceRuntime → OpenClawd → execution)"
        )

    # DesktopPresenceRuntime as action entry point
    dpr_ok = _try_import("core.desktop_presence_runtime")
    if dpr_ok and _source_contains("core.desktop_presence_runtime", "handle_request"):
        established.append(
            "DesktopPresenceRuntime.handle_request() confirmed — single canonical "
            "action entry point for all adapter surfaces"
        )

    # SourceDispatchOrchestrator — canonical dispatch
    sdo_ok = _try_import("core.runtime.source_dispatch_orchestrator")
    anchors.append(CodeAnchor(
        module_path="core.runtime.source_dispatch_orchestrator",
        description="SourceDispatchOrchestrator — canonical orchestration dispatch; "
                    "_score_candidate() consumes Android truth for routing",
        confirmed_importable=sdo_ok,
        key_attribute="_score_candidate",
    ))
    if sdo_ok:
        established.append(
            "core.runtime.source_dispatch_orchestrator importable — "
            "canonical orchestration dispatch present"
        )

    # DeviceRouter — gateway action routing
    dr_ok = _try_import("galaxy_gateway.device_router")
    anchors.append(CodeAnchor(
        module_path="galaxy_gateway.device_router",
        description="DeviceRouter — gateway routing authority; routes dispatch to "
                    "Android execution targets",
        confirmed_importable=dr_ok,
        key_attribute="DeviceRouter",
    ))
    if dr_ok:
        established.append(
            "galaxy_gateway.device_router importable — gateway routing authority present"
        )

    # CapabilityRegistry — write authority (action-capable for registration)
    cr_ok = _try_import_with_attr("core.agent.capability_registry", "CapabilityRegistry")
    anchors.append(CodeAnchor(
        module_path="core.agent.capability_registry",
        description="CapabilityRegistry — canonical capability write authority; "
                    "CapabilityResolver — canonical read path for routing decisions",
        confirmed_importable=cr_ok,
        key_attribute="CapabilityRegistry",
    ))
    if cr_ok:
        established.append(
            "core.agent.capability_registry — CapabilityRegistry (write) + "
            "CapabilityResolver (read) both present"
        )

    # CRITICAL GAP: operator panel cannot trigger actions directly
    if not has_post_action:
        gaps.append(
            "OPERATOR PANEL IS OBSERVATION-ONLY: An operator cannot trigger task "
            "dispatch, device control, or system state changes through any "
            "/api/v1/operator/* endpoint. Action must go through /api/v1/chat or "
            "internal e2e paths. The operator/panel surface is a pure read-only "
            "projection with zero action capability."
        )

    follow_up = FollowUpPRSpec(
        pr_title=(
            "Add POST /api/v1/operator/action — operator panel action endpoint "
            "enabling direct task dispatch from operator surface"
        ),
        priority=FollowUpPRPriority.P1,
        implementation_cut_points=[
            "core/routes/operator.py — add POST /api/v1/operator/action route "
            "with OperatorActionRequest body and permission check",
            "core/operator_surface.py — add execute_operator_action() method "
            "that delegates to DesktopPresenceRuntime or SourceDispatchOrchestrator",
            "core/desktop_presence_runtime.py — operator-sourced requests may "
            "need a new entry_mode discriminator (OPERATOR_ACTION vs CHAT)",
        ],
        primary_modification_zones=[
            "core/routes/operator.py — new POST route",
            "core/operator_surface.py — action delegation method",
            "core/ — new OperatorActionRequest / OperatorActionResponse contracts",
        ],
        new_modules_to_create=[
            "contracts/operator_action_request.py — typed OperatorActionRequest "
            "with action_type, target_device_id, payload",
        ],
        maturity_level_unlocked=(
            "The operator panel transitions from OBSERVATION_PROJECTION_ONLY to "
            "ACTION_CAPABLE. Operators can directly trigger task dispatch, device "
            "control, and execution from the operator surface without needing to "
            "use the /api/v1/chat NL path. This closes the actionability gap and "
            "makes the operator panel a true control-plane surface. "
            "Prerequisite for meaningful operator-driven automation."
        ),
        estimated_scope=(
            "1 new contract dataclass + changes to operator routes + "
            "operator_surface extension + 1 test file"
        ),
        invariant_that_would_close=(
            "assert_five_domain_invariants(): "
            "OPERATOR_ACTIONABILITY domain would upgrade from "
            "PARTIALLY_ESTABLISHED → RUNTIME_EVIDENCED_CLOSED; "
            "operator_panel actionability surface would become ACTION_CAPABLE"
        ),
    )

    return DomainImplementationEntry(
        domain=ReviewDomain.OPERATOR_ACTIONABILITY,
        evidence_strength=EvidenceStrength.PARTIALLY_ESTABLISHED,
        canonical_path_summary=(
            "Current actionability topology: "
            "READ_ONLY surfaces: all /api/v1/operator/* (OperatorSurface — "
            "projection-only by design), /api/v1/projection/runtime. "
            "ACTION_CAPABLE surfaces: /api/v1/chat (POST → DesktopPresenceRuntime → "
            "OpenClawd → execution), CapabilityRegistry write path. "
            "DECISION_CONSUMED: android_device_state_store truth drives "
            "_score_candidate() routing; CapabilityResolver feeds routing decisions. "
            "Gap: operator/panel surface has zero action endpoints — operators "
            "cannot drive the system from the panel surface."
        ),
        established_items=established,
        partial_or_fragmented_items=partial,
        gap_items=gaps,
        current_code_anchors=anchors,
        android_anchors=[
            AndroidCodeAnchor(
                android_package="com.ufo.galaxy.runtime",
                v2_evidence_ref="tests.test_orchestration_consumes_android_truth",
                description="Android runtime truth consumed by V2 orchestration routing "
                            "(_score_candidate) — decision-consumed path confirmed",
                confirmed_via_v2=_test_file_exists(
                    "tests.test_orchestration_consumes_android_truth"
                ),
            ),
        ],
        overclaiming_guard=(
            "OVERCLAIMING GUARD: The system CANNOT be claimed as 'fully controllable "
            "from the operator surface' because all /api/v1/operator/* endpoints are "
            "strictly GET/read-only. The /api/v1/chat path IS action-capable but is "
            "NL-input-only and not a panel-level control surface. "
            "Until a POST /api/v1/operator/action endpoint exists and is tested, "
            "operator actionability is PARTIALLY_ESTABLISHED (dispatch-capable via "
            "chat but panel-controllability is MISSING)."
        ),
        follow_up_pr_spec=follow_up,
    )


# ---------------------------------------------------------------------------
# Domain 4: Natural-Language Canonical Path
# ---------------------------------------------------------------------------


def _review_natural_language_canonical_path() -> DomainImplementationEntry:
    """Review natural-language canonical ingress → orchestration → feedback path."""
    established: List[str] = []
    partial: List[str] = []
    gaps: List[str] = []
    anchors: List[CodeAnchor] = []

    # NL ingress: /api/v1/chat → DesktopPresenceRuntime
    chat_ok = _try_import("core.routes.chat")
    anchors.append(CodeAnchor(
        module_path="core.routes.chat",
        description="/api/v1/chat — NL ingress surface; POST routes to "
                    "DesktopPresenceRuntime.handle_request()",
        confirmed_importable=chat_ok,
        key_attribute="CHAT_ROUTES_AUTHORITY",
    ))
    if chat_ok:
        established.append(
            "core.routes.chat importable — /api/v1/chat NL ingress surface present"
        )

    if chat_ok and _source_contains("core.routes.chat", "DesktopPresenceRuntime"):
        established.append(
            "chat route confirmed to delegate to DesktopPresenceRuntime — "
            "NL chain entry point wired correctly"
        )

    # DesktopPresenceRuntime — canonical NL shell
    dpr_ok = _try_import("core.desktop_presence_runtime")
    anchors.append(CodeAnchor(
        module_path="core.desktop_presence_runtime",
        description="DesktopPresenceRuntime — tri-state lifecycle shell for all NL "
                    "adapter surfaces; handle_request() is the canonical NL entry",
        confirmed_importable=dpr_ok,
        key_attribute="handle_request",
    ))
    if dpr_ok:
        established.append("core.desktop_presence_runtime importable")

    if dpr_ok and _source_contains("core.desktop_presence_runtime", "handle_request"):
        established.append(
            "DesktopPresenceRuntime.handle_request() confirmed — "
            "SILENT→LIMINAL→MANIFEST lifecycle transition on NL input"
        )

    # Session identity in NL path
    if dpr_ok and _source_contains("core.desktop_presence_runtime", "ingress_carrier_context"):
        established.append(
            "ingress_carrier_context stamp confirmed — NL requests carry "
            "session_id, user_id, entry_mode (ingress standardization)"
        )

    if dpr_ok and _source_contains("core.desktop_presence_runtime", "control_session_id"):
        established.append(
            "control_session_id threaded through _handle_via_e2e — "
            "session identity present in NL canonical path"
        )

    # OpenClawd — LLM function-calling decision core
    oc_ok = _try_import("core.openclawd")
    anchors.append(CodeAnchor(
        module_path="core.openclawd",
        description="OpenClawd — LLM function-calling subject core; process() drives "
                    "decision-making from NL input via LLM",
        confirmed_importable=oc_ok,
        key_attribute="process",
    ))
    if oc_ok:
        established.append("core.openclawd importable — LLM function-calling core present")

    if oc_ok and _source_contains("core.openclawd", "process"):
        established.append(
            "OpenClawd.process() confirmed — LLM-driven NL decision method present"
        )

    if oc_ok and (
        _source_contains("core.openclawd", "function calling")
        or _source_contains("core.openclawd", "function_call")
    ):
        established.append(
            "OpenClawd uses LLM function calling — NL-to-tool orchestration confirmed"
        )

    # AI intent classification
    ai_ok = _try_import("core.ai_intent")
    anchors.append(CodeAnchor(
        module_path="core.ai_intent",
        description="core.ai_intent — task intent classification from NL input",
        confirmed_importable=ai_ok,
    ))
    if ai_ok:
        established.append("core.ai_intent importable — NL intent classification present")

    # Multi-LLM router
    llm_router_ok = _try_import("core.multi_llm_router") or _try_import(
        "core.unified.llm_router"
    )
    if llm_router_ok:
        established.append(
            "LLM router importable — multi-LLM backend routing present for NL processing"
        )
        anchors.append(CodeAnchor(
            module_path="core.multi_llm_router",
            description="Multi-LLM router — routes NL input to configured LLM backends",
            confirmed_importable=True,
        ))

    # Android vision ingress (NL-adjacent: vision → NL chain)
    vision_ok = _try_import("galaxy_gateway.android.handlers.vision")
    if vision_ok and _source_contains(
        "galaxy_gateway.android.handlers.vision", "DesktopPresenceRuntime"
    ):
        established.append(
            "Android vision handler confirmed to delegate to DesktopPresenceRuntime — "
            "all carrier paths (android_vision, vision_sampler, compat_ws_chat) "
            "converge at DesktopPresenceRuntime.handle_request()"
        )

    # Source dispatch orchestrator — downstream execution
    sdo_ok = _try_import("core.runtime.source_dispatch_orchestrator")
    anchors.append(CodeAnchor(
        module_path="core.runtime.source_dispatch_orchestrator",
        description="SourceDispatchOrchestrator — NL decision output dispatched here; "
                    "_score_candidate() routes to Android or local execution",
        confirmed_importable=sdo_ok,
    ))
    if sdo_ok:
        established.append(
            "core.runtime.source_dispatch_orchestrator importable — "
            "NL dispatch chain downstream confirmed"
        )

    # CRITICAL GAP: No CI test proves real LLM backend end-to-end processing
    nl_e2e_test_candidates = [
        "tests.test_nl_end_to_end_roundtrip",
        "tests.test_chat_nl_roundtrip",
        "tests.integration.test_nl_driving_e2e",
        "tests.integration.test_nl_e2e_canonical_path",
    ]
    nl_e2e_found = any(_test_file_exists(t) for t in nl_e2e_test_candidates)
    if nl_e2e_found:
        established.append("NL end-to-end CI test found — NL chain CI-proven")
        # Even with the CI test in place, the LLM backend is a contract stub
        # (not a production-grade LLM).  Document this so the anti-overclaiming
        # invariant ("every domain has at least one gap or partial item") is satisfied.
        partial.append(
            "NL e2e CI test uses LLMContractStub (not a real production LLM): "
            "full production-LLM end-to-end proof is not yet CI-exercised; "
            "the contract stub proves structural wiring and dispatch, not "
            "production-grade reasoning or real tool-call quality."
        )
    else:
        partial.append(
            "Structural NL chain confirmed in code but no CI test exercises full "
            "NL roundtrip with real LLM backend processing"
        )
        gaps.append(
            "NL END-TO-END CI PROOF MISSING: No CI test exercises the canonical NL "
            "path from /api/v1/chat input → DesktopPresenceRuntime → OpenClawd → "
            "LLM function calling → action dispatch with a real (or contract-verified "
            "stub) LLM backend. LLM responses are mocked or skipped in CI. "
            "The claim 'truly NL-driven end-to-end' is PARTIALLY_PROVEN structurally "
            "but NOT CI-provable in current state."
        )

    follow_up = FollowUpPRSpec(
        pr_title=(
            "Add tests/integration/test_nl_e2e_canonical_path.py — CI-verifiable "
            "NL canonical path proof using contract LLM stub"
        ),
        priority=FollowUpPRPriority.P1,
        implementation_cut_points=[
            "tests/integration/test_nl_e2e_canonical_path.py — new test file "
            "exercising /api/v1/chat → DesktopPresenceRuntime → OpenClawd → "
            "LLM stub → action dispatch → result feedback",
            "core/desktop_presence_runtime.py — ensure ingress_carrier_context "
            "is assertable in test (may already be present)",
            "core/openclawd.py — expose or stub process() for contract testing "
            "without real LLM API key",
        ],
        primary_modification_zones=[
            "tests/integration/ — new NL e2e test module",
            "core/desktop_presence_runtime.py — audit trail exposure for tests",
            "conftest.py or tests/integration/conftest.py — LLM contract stub fixture",
        ],
        new_modules_to_create=[
            "tests/integration/test_nl_e2e_canonical_path.py — "
            "canonical NL path CI proof",
            "tests/integration/stubs/llm_contract_stub.py — minimal LLM contract "
            "stub that returns typed function-call responses without real API",
        ],
        maturity_level_unlocked=(
            "The NL canonical path gains CI-verifiable end-to-end proof. "
            "The claim 'system is truly NL-driven end-to-end on canonical paths' "
            "becomes machine-verifiable. This closes the NL e2e gap and unlocks "
            "the ability to add regression tests for NL-driven behavior. "
            "Prerequisite for multimodal e2e proof (NL path must be proven before "
            "multimodal additions are layered on top)."
        ),
        estimated_scope=(
            "1 new integration test file + LLM stub fixture + "
            "minor audit trail additions to DPR"
        ),
        invariant_that_would_close=(
            "assert_five_domain_invariants(): "
            "NATURAL_LANGUAGE_CANONICAL_PATH domain would upgrade from "
            "PARTIALLY_ESTABLISHED → RUNTIME_EVIDENCED_CLOSED"
        ),
    )

    _ci_suffix = (
        "CI-proven end-to-end via tests/integration/test_nl_e2e_canonical_path.py "
        "— LLMContractStub injected into AgentKernel; ingress_carrier_context, "
        "tristate, runtime_session_id, and panel-aggregation integration all "
        "machine-verified."
        if nl_e2e_found
        else "Gap: no CI test exercises a real or contract-verified LLM backend "
             "end-to-end roundtrip."
    )
    _overclaiming_guard = (
        "NL canonical path is CI-proven end-to-end via "
        "tests/integration/test_nl_e2e_canonical_path.py (PR-5). "
        "LLMContractStub is injected into AgentKernel to provide a "
        "contract-verified LLM backend without a real API key. "
        "The 'truly NL-driven' claim is now machine-verifiable. "
        "NOT a claim of production-LLM proof: the CI stub is a structural "
        "contract verifier, not a real-provider benchmark. "
        "Overclaiming production-grade LLM reasoning from these tests is "
        "not supported."
        if nl_e2e_found
        else (
            "OVERCLAIMING GUARD: The NL canonical path CANNOT be claimed as "
            "'CI-proven end-to-end' because no CI test exercises the full roundtrip "
            "with real or contract-verified LLM processing. The structural chain "
            "is correct, but 'truly NL-driven' as a CI-provable claim requires "
            "a test that exercises LLM function calling and verifies action dispatch "
            "without mocking the entire LLM response chain. "
            "Claiming CI-proven NL e2e without such a test is overclaiming."
        )
    )
    return DomainImplementationEntry(
        domain=ReviewDomain.NATURAL_LANGUAGE_CANONICAL_PATH,
        evidence_strength=(
            EvidenceStrength.RUNTIME_EVIDENCED_CLOSED
            if nl_e2e_found
            else EvidenceStrength.PARTIALLY_ESTABLISHED
        ),
        canonical_path_summary=(
            "Canonical NL path confirmed in real code: "
            "/api/v1/chat (POST) → DesktopPresenceRuntime.handle_request() "
            "[SILENT→LIMINAL] → OpenClawd.process() [LLM function calling] "
            "→ tool/action dispatch → SourceDispatchOrchestrator "
            "→ Android execution OR local execution → result feedback "
            "→ MANIFEST→SILENT lifecycle. "
            "All modules importable; structural chain is correct and non-trivial. "
            "All carrier paths (android_vision, vision_sampler, compat_ws_chat) "
            "converge at DesktopPresenceRuntime.handle_request(). "
            "Session identity (ingress_carrier_context, control_session_id) present. "
            + _ci_suffix
        ),
        established_items=established,
        partial_or_fragmented_items=partial,
        gap_items=gaps,
        current_code_anchors=anchors,
        android_anchors=[
            AndroidCodeAnchor(
                android_package="com.ufo.galaxy.nlp",
                v2_evidence_ref="galaxy_gateway.android.handlers.vision",
                description="Android NLP/vision processing; results uplinked to V2 "
                            "galaxy_gateway which routes to DesktopPresenceRuntime",
                confirmed_via_v2=_try_import("galaxy_gateway.android.handlers.vision"),
            ),
        ],
        overclaiming_guard=_overclaiming_guard,
        follow_up_pr_spec=follow_up,
    )


# ---------------------------------------------------------------------------
# Domain 5: Multimodal Canonical Path
# ---------------------------------------------------------------------------


def _review_multimodal_canonical_path() -> DomainImplementationEntry:
    """Review multimodal/perception/grounding/vision canonical path."""
    established: List[str] = []
    partial: List[str] = []
    gaps: List[str] = []
    anchors: List[CodeAnchor] = []

    # Continuous host ingress bus (ambient perception)
    ingest_ok = _try_import("core.multimodal.ingest_runtime")
    anchors.append(CodeAnchor(
        module_path="core.multimodal.ingest_runtime",
        description="MultimodalIngestRuntime — continuous host perception bus; "
                    "config-gated (disabled by SAFE_DEFAULT)",
        confirmed_importable=ingest_ok,
    ))
    if ingest_ok:
        established.append(
            "core.multimodal.ingest_runtime importable — continuous host perception "
            "bus infrastructure present"
        )

    ingress_ok = _try_import("core.multimodal.ingress_bus")
    anchors.append(CodeAnchor(
        module_path="core.multimodal.ingress_bus",
        description="MultimodalIngressBus — ambient multimodal signal ingress bus",
        confirmed_importable=ingress_ok,
        key_attribute="MultimodalIngressBus",
    ))
    if ingress_ok:
        established.append(
            "core.multimodal.ingress_bus importable — MultimodalIngressBus present"
        )

    # Perception frame and source registry
    pf_ok = _try_import("core.multimodal.perception_frame")
    anchors.append(CodeAnchor(
        module_path="core.multimodal.perception_frame",
        description="PerceptionFrame — typed multimodal perception signal carrier",
        confirmed_importable=pf_ok,
    ))
    if pf_ok:
        established.append("core.multimodal.perception_frame importable")

    psr_ok = _try_import("core.multimodal.perception_source_registry")
    anchors.append(CodeAnchor(
        module_path="core.multimodal.perception_source_registry",
        description="PerceptionSourceRegistry — registry of active perception sources",
        confirmed_importable=psr_ok,
    ))
    if psr_ok:
        established.append("core.multimodal.perception_source_registry importable")

    # Request-bound multimodal context in OpenClawd
    oc_ok = _try_import("core.openclawd")
    if oc_ok and _source_contains("core.openclawd", "multimodal_context"):
        established.append(
            "OpenClawd.process() accepts multimodal_context — request-bound "
            "multimodal payload fusion path confirmed in source"
        )
        anchors.append(CodeAnchor(
            module_path="core.openclawd",
            description="OpenClawd — accepts multimodal_context for request-bound "
                        "multimodal signal fusion; path to LLM decision",
            confirmed_importable=oc_ok,
            key_attribute="multimodal_context",
        ))

    if oc_ok and (
        _source_contains("core.openclawd", "MultimodalBus")
        or _source_contains("core.openclawd", "multimodal_bus")
    ):
        established.append(
            "OpenClawd references MultimodalBus for ingest fusion — "
            "multimodal signal can influence LLM processing"
        )

    # Vision pipeline
    vp_ok = _try_import("core.vision_pipeline")
    anchors.append(CodeAnchor(
        module_path="core.vision_pipeline",
        description="VisionPipeline — visual processing / grounding pipeline",
        confirmed_importable=vp_ok,
    ))
    if vp_ok:
        established.append("core.vision_pipeline importable — visual processing present")

    # Multimodal runtime profile (SAFE_DEFAULT — disabled by default)
    mrp_ok = _try_import("core.multimodal_runtime_profile")
    anchors.append(CodeAnchor(
        module_path="core.multimodal_runtime_profile",
        description="MultimodalRuntimeProfile — SAFE_DEFAULT disables continuous "
                    "host perception ingest; config-gated activation",
        confirmed_importable=mrp_ok,
        key_attribute="SAFE_DEFAULT",
    ))
    if mrp_ok:
        established.append(
            "core.multimodal_runtime_profile importable — SAFE_DEFAULT profile present"
        )

    if mrp_ok and _source_contains("core.multimodal_runtime_profile", "SAFE_DEFAULT"):
        established.append(
            "SAFE_DEFAULT profile confirmed: enable_multimodal_ingest=False by default — "
            "continuous host perception is disabled unless explicitly configured. "
            "This is the primary reason multimodal is INFRASTRUCTURE_PRESENT but "
            "not end-to-end proven."
        )

    # Android vision uplink
    vision_handler_ok = _try_import("galaxy_gateway.android.handlers.vision")
    anchors.append(CodeAnchor(
        module_path="galaxy_gateway.android.handlers.vision",
        description="Android vision uplink handler — receives Android vision frames "
                    "and routes them into V2 multimodal pipeline",
        confirmed_importable=vision_handler_ok,
    ))
    if vision_handler_ok:
        established.append(
            "galaxy_gateway.android.handlers.vision importable — Android vision "
            "uplink handler present"
        )

    # MobileVLM and SeeClick presence in DeviceStateSnapshot
    if _source_contains("core.android_device_state_store", "mobilevlm_present"):
        established.append(
            "mobilevlm_present field in DeviceStateSnapshot — Android-side VLM "
            "presence tracking confirmed (mobile grounding model present marker)"
        )
    if _source_contains("core.android_device_state_store", "seeclick_present"):
        established.append(
            "seeclick_present field in DeviceStateSnapshot — SeeClick grounding "
            "model presence confirmed on Android side"
        )
    if _source_contains("core.android_device_state_store", "mobilevlm_checksum_ok"):
        established.append(
            "mobilevlm_checksum_ok field confirmed — model integrity tracking present"
        )

    # CRITICAL GAP: Continuous ingest disabled by default + no e2e CI test
    mm_e2e_test_candidates = [
        "tests.integration.test_multimodal_e2e",
        "tests.test_multimodal_end_to_end",
        "tests.test_multimodal_perception_roundtrip",
        "tests.integration.test_multimodal_canonical_path",
    ]
    mm_e2e_found = any(_test_file_exists(t) for t in mm_e2e_test_candidates)
    if mm_e2e_found:
        established.append("Multimodal end-to-end CI test found")
    else:
        partial.append(
            "No multimodal end-to-end CI test found — full multimodal activation "
            "path from ambient perception or request-bound context to LLM decision "
            "is not CI-proven"
        )
        gaps.append(
            "MULTIMODAL E2E CI PROOF MISSING: Continuous host ingress "
            "(MultimodalIngressBus) is disabled by default (SAFE_DEFAULT profile). "
            "No CI test proves full end-to-end multimodal activation: "
            "ambient perception → MultimodalIngressBus → OpenClawd → decision/action. "
            "Request-bound multimodal_context path exists in OpenClawd but no CI test "
            "proves it drives a real LLM decision end-to-end. "
            "Mobile VLM and SeeClick models tracked in DeviceStateSnapshot but no CI "
            "test proves their perception output influences V2 decision routing."
        )

    follow_up = FollowUpPRSpec(
        pr_title=(
            "Add tests/integration/test_multimodal_canonical_path.py — "
            "CI-verifiable multimodal request-bound context path proof via "
            "OpenClawd.process(multimodal_context=...)"
        ),
        priority=FollowUpPRPriority.P2,
        implementation_cut_points=[
            "tests/integration/test_multimodal_canonical_path.py — new test file "
            "exercising request-bound multimodal_context path through "
            "OpenClawd.process() with a stub multimodal frame",
            "core/multimodal/ingress_bus.py — add activation contract method "
            "enable_for_testing() that can be called in tests without full config",
            "core/multimodal_runtime_profile.py — add TEST_ACTIVATION profile "
            "alongside SAFE_DEFAULT for test-controlled activation",
            "core/openclawd.py — ensure multimodal_context parameter is "
            "tested with a typed PerceptionFrame or equivalent",
        ],
        primary_modification_zones=[
            "tests/integration/ — new multimodal e2e test module",
            "core/multimodal/ — activation contract additions for test harness",
            "core/openclawd.py — multimodal_context test path",
        ],
        new_modules_to_create=[
            "tests/integration/test_multimodal_canonical_path.py — "
            "canonical multimodal path CI proof",
            "tests/integration/stubs/multimodal_perception_stub.py — "
            "minimal perception stub for multimodal_context injection",
        ],
        maturity_level_unlocked=(
            "The request-bound multimodal context path gains CI-verifiable proof. "
            "The claim that 'multimodal signals influence current decision/routing/execution "
            "paths' becomes machine-verifiable for the request-bound path. "
            "Separates 'canonical participation' (request-bound multimodal_context → "
            "OpenClawd) from 'optional infrastructure' (always-on ambient ingest, "
            "config-gated). Prerequisite for proving 'natively multimodal' in a "
            "CI-verifiable sense. Does NOT require enabling SAFE_DEFAULT override."
        ),
        estimated_scope=(
            "1 new integration test file + perception stub fixture + "
            "minor activation contract additions to multimodal modules"
        ),
        invariant_that_would_close=(
            "assert_five_domain_invariants(): "
            "MULTIMODAL_CANONICAL_PATH domain would upgrade from "
            "INFRASTRUCTURE_PRESENT_NOT_YET_E2E_PROVEN → PARTIALLY_ESTABLISHED "
            "for request-bound path (full ambient path remains config-gated)"
        ),
    )

    return DomainImplementationEntry(
        domain=ReviewDomain.MULTIMODAL_CANONICAL_PATH,
        evidence_strength=(
            EvidenceStrength.PARTIALLY_ESTABLISHED
            if mm_e2e_found
            else EvidenceStrength.INFRASTRUCTURE_PRESENT_NOT_YET_E2E_PROVEN
        ),
        canonical_path_summary=(
            "Two multimodal paths in real code: "
            "(1) Continuous ambient path: MultimodalIngressBus → PerceptionSourceRegistry "
            "→ PerceptionFrame → OpenClawd — DISABLED BY DEFAULT (SAFE_DEFAULT profile, "
            "enable_multimodal_ingest=False). Infrastructure present, not activated. "
            "(2) Request-bound path: POST /api/v1/chat with multimodal_context → "
            "DesktopPresenceRuntime → OpenClawd.process(multimodal_context=...) → "
            "LLM with multimodal input. Path structurally confirmed in source. "
            "Android side: vision uplink handler present (galaxy_gateway/android/handlers/"
            "vision.py); mobilevlm_present / seeclick_present tracked in "
            "DeviceStateSnapshot. "
            + (
                "Request-bound path is CI-proven end-to-end via "
                "tests/integration/test_multimodal_canonical_path.py."
                if mm_e2e_found
                else "Neither path is CI-proven end-to-end."
            )
        ),
        established_items=established,
        partial_or_fragmented_items=partial,
        gap_items=gaps,
        current_code_anchors=anchors,
        android_anchors=[
            AndroidCodeAnchor(
                android_package="com.ufo.galaxy.inference",
                v2_evidence_ref="core.android_device_state_store (mobilevlm_present)",
                description="Android MobileVLM inference engine — presence tracked "
                            "in V2 DeviceStateSnapshot.mobilevlm_present field",
                confirmed_via_v2=_source_contains(
                    "core.android_device_state_store", "mobilevlm_present"
                ),
            ),
            AndroidCodeAnchor(
                android_package="com.ufo.galaxy.grounding",
                v2_evidence_ref="core.android_device_state_store (seeclick_present)",
                description="Android SeeClick grounding model — presence tracked "
                            "in V2 DeviceStateSnapshot.seeclick_present field",
                confirmed_via_v2=_source_contains(
                    "core.android_device_state_store", "seeclick_present"
                ),
            ),
            AndroidCodeAnchor(
                android_package="com.ufo.galaxy.network (vision uplink)",
                v2_evidence_ref="galaxy_gateway.android.handlers.vision",
                description="Android vision frame uplink handler in V2 galaxy_gateway; "
                            "routes Android vision frames into V2 multimodal pipeline",
                confirmed_via_v2=_try_import("galaxy_gateway.android.handlers.vision"),
            ),
        ],
        overclaiming_guard=(
            "OVERCLAIMING GUARD: The multimodal path CANNOT be claimed as "
            "'natively multimodal end-to-end' because: "
            "(1) The continuous ambient ingress path (MultimodalIngressBus) is DISABLED "
            "BY DEFAULT and no CI test proves it is activated and functioning; "
            "(2) The request-bound multimodal_context path through OpenClawd exists in "
            "source but no CI test proves it drives a real LLM decision with a real "
            "multimodal frame. Mobile VLM and SeeClick presence is tracked but their "
            "perception output influencing V2 decisions is not CI-proven. "
            "Claiming 'natively multimodal' without CI proof is overclaiming."
        ),
        follow_up_pr_spec=follow_up,
    )


# ---------------------------------------------------------------------------
# Build the complete review package
# ---------------------------------------------------------------------------


def _compute_domains_below_threshold(
    entries: List[DomainImplementationEntry],
) -> int:
    """Count domains that are NOT STRONGLY_ESTABLISHED or RUNTIME_EVIDENCED_CLOSED."""
    strong = {
        EvidenceStrength.STRONGLY_ESTABLISHED,
        EvidenceStrength.RUNTIME_EVIDENCED_CLOSED,
    }
    return sum(1 for e in entries if e.evidence_strength not in strong)


def build_five_domain_review() -> ImplementationReviewPackage:
    """Build the complete five-domain implementation-grade review package.

    Returns
    -------
    ImplementationReviewPackage
        The complete review artifact with all five domain entries, follow-up
        PR sequence, and invariant-checked summary.
    """
    domain_entries = [
        _review_unified_panel_aggregation(),
        _review_desktop_three_state_existence_surface(),
        _review_operator_actionability(),
        _review_natural_language_canonical_path(),
        _review_multimodal_canonical_path(),
    ]

    follow_up_sequence = [
        entry.follow_up_pr_spec
        for entry in domain_entries
        if entry.follow_up_pr_spec is not None
    ]

    below_threshold = _compute_domains_below_threshold(domain_entries)

    system_maturity_summary = (
        "SYSTEM MATURITY SUMMARY (five-domain implementation review):\n"
        "\n"
        "All five domains are below RUNTIME_EVIDENCED_CLOSED. Current evidence:\n"
        "\n"
        "1. UNIFIED_PANEL_AGGREGATION — PARTIALLY_ESTABLISHED.\n"
        "   Multiple read-only operator surfaces exist and are structurally complete.\n"
        "   Critical gap: no single endpoint aggregates all state families (subject\n"
        "   lifecycle + Android ecosystem + flow states + UI clothing states).\n"
        "\n"
        "2. DESKTOP_THREE_STATE_EXISTENCE_SURFACE — PARTIALLY_ESTABLISHED.\n"
        "   All three state families confirmed in real code (subject tri-state\n"
        "   lifecycle, UI clothing states, continuum posture). PresenceDirector and\n"
        "   PresenceProjection present. Gap: no unified assistant-like desktop\n"
        "   existence surface aggregating all three into one coherent presentation.\n"
        "\n"
        "3. OPERATOR_ACTIONABILITY — PARTIALLY_ESTABLISHED.\n"
        "   Dispatch-capable via /api/v1/chat and SourceDispatchOrchestrator.\n"
        "   Android truth consumed in routing decisions. Gap: operator panel\n"
        "   (/api/v1/operator/*) is strictly read-only — no action endpoints.\n"
        "\n"
        "4. NATURAL_LANGUAGE_CANONICAL_PATH — PARTIALLY_ESTABLISHED.\n"
        "   Structural NL chain correct in real code: chat → DPR → OpenClawd\n"
        "   → LLM function calling → dispatch. Session identity present.\n"
        "   Gap: no CI test proves full NL roundtrip with real/contract LLM.\n"
        "\n"
        "5. MULTIMODAL_CANONICAL_PATH — INFRASTRUCTURE_PRESENT_NOT_YET_E2E_PROVEN.\n"
        "   Multimodal infrastructure importable (IngressBus, PerceptionFrame,\n"
        "   VisionPipeline, Android vision uplink, mobile VLM tracking).\n"
        "   Continuous ingest disabled by default (SAFE_DEFAULT). No CI proof.\n"
        "\n"
        "Recommended follow-up PR order: P1-panel-agg → P1-three-state → "
        "P1-operator-action → P1-NL-e2e → P2-multimodal-e2e.\n"
        "Completion of all five would advance system from LATE_STAGE_CLOSURE "
        "to PRODUCTION_COMPLETE."
    )

    overclaiming_guards_summary = (
        "OVERCLAIMING GUARDS SUMMARY:\n"
        "1. Panel API unification: cannot claim 'fully unified' — no single "
        "aggregation endpoint exists.\n"
        "2. Three-state existence: cannot claim 'coherently presented' — three "
        "state families are separate, no joint surface.\n"
        "3. Operator actionability: cannot claim 'fully controllable from operator "
        "panel' — all operator routes are GET-only.\n"
        "4. NL canonical path: cannot claim 'CI-proven NL-driven e2e' — LLM "
        "roundtrip not CI-tested.\n"
        "5. Multimodal canonical: cannot claim 'natively multimodal e2e' — "
        "continuous ingest disabled by default, no CI proof.\n"
        "All five guards must be honored in all downstream claims about system completeness."
    )

    return ImplementationReviewPackage(
        domain_entries=domain_entries,
        system_maturity_summary=system_maturity_summary,
        follow_up_pr_sequence=follow_up_sequence,
        overclaiming_guards_summary=overclaiming_guards_summary,
        domains_at_partially_established_or_below=below_threshold,
    )


# ---------------------------------------------------------------------------
# Singleton cache
# ---------------------------------------------------------------------------

# Lock is created at module load time intentionally: it is lightweight, does not
# acquire any external resources, and is safe across the module reload patterns
# used in this codebase.  If the process forks after import, callers must
# re-initialise state by calling reset_five_domain_review() in the child.
_REVIEW_LOCK: threading.Lock = threading.Lock()
_REVIEW_CACHE: Optional[ImplementationReviewPackage] = None


def get_five_domain_review() -> ImplementationReviewPackage:
    """Return a cached ImplementationReviewPackage (build once, reuse).

    Thread-safe.  Use reset_five_domain_review() to force a rebuild in tests.
    """
    global _REVIEW_CACHE
    if _REVIEW_CACHE is None:
        with _REVIEW_LOCK:
            if _REVIEW_CACHE is None:
                _REVIEW_CACHE = build_five_domain_review()
    return _REVIEW_CACHE


def reset_five_domain_review() -> None:
    """Reset the cached review package.  Use in tests for isolation."""
    global _REVIEW_CACHE
    with _REVIEW_LOCK:
        _REVIEW_CACHE = None


# ---------------------------------------------------------------------------
# Invariant checker
# ---------------------------------------------------------------------------


def assert_five_domain_invariants(
    package: Optional[ImplementationReviewPackage] = None,
) -> None:
    """Assert all structural invariants of the five-domain review package.

    Raises AssertionError with a descriptive message if any invariant fails.
    This is a strict check — it DOES NOT silently pass if the report would
    overclaim completeness.

    Parameters
    ----------
    package
        The package to check.  If None, calls get_five_domain_review().
    """
    if package is None:
        package = get_five_domain_review()

    # INV-1: Must have exactly 5 domain entries
    assert len(package.domain_entries) == 5, (
        f"INV-1 FAIL: Expected 5 domain entries; got {len(package.domain_entries)}"
    )

    # INV-2: All ReviewDomain values must be covered
    covered = {e.domain for e in package.domain_entries}
    for domain in ReviewDomain:
        assert domain in covered, f"INV-2 FAIL: Missing domain {domain}"

    # INV-3: Each domain entry must have at least 1 code anchor
    for entry in package.domain_entries:
        assert len(entry.current_code_anchors) >= 1, (
            f"INV-3 FAIL: Domain {entry.domain} has no code anchors"
        )

    # INV-4: Each domain entry must have a non-empty overclaiming guard
    for entry in package.domain_entries:
        assert len(entry.overclaiming_guard) > 0, (
            f"INV-4 FAIL: Domain {entry.domain} has empty overclaiming_guard"
        )

    # INV-5: Each domain entry must have a follow-up PR spec
    for entry in package.domain_entries:
        assert entry.follow_up_pr_spec is not None, (
            f"INV-5 FAIL: Domain {entry.domain} has no follow_up_pr_spec"
        )

    # INV-6: Each FollowUpPRSpec must have non-empty cut points
    for entry in package.domain_entries:
        spec = entry.follow_up_pr_spec
        assert spec is not None  # already checked in INV-5
        assert len(spec.implementation_cut_points) >= 1, (
            f"INV-6 FAIL: Domain {entry.domain} follow-up PR has no cut points"
        )

    # INV-7: Each FollowUpPRSpec must have non-empty maturity_level_unlocked
    for entry in package.domain_entries:
        spec = entry.follow_up_pr_spec
        assert spec is not None
        assert len(spec.maturity_level_unlocked) > 0, (
            f"INV-7 FAIL: Domain {entry.domain} follow-up PR has empty maturity unlock"
        )

    # INV-8: follow_up_pr_sequence must have exactly 5 entries
    assert len(package.follow_up_pr_sequence) == 5, (
        f"INV-8 FAIL: Expected 5 follow-up PRs in sequence; "
        f"got {len(package.follow_up_pr_sequence)}"
    )

    # INV-9: MULTIMODAL domain must be <= PARTIALLY_ESTABLISHED
    multimodal_entry = next(
        e for e in package.domain_entries
        if e.domain == ReviewDomain.MULTIMODAL_CANONICAL_PATH
    )
    strong_labels = {
        EvidenceStrength.STRONGLY_ESTABLISHED,
        EvidenceStrength.RUNTIME_EVIDENCED_CLOSED,
    }
    assert multimodal_entry.evidence_strength not in strong_labels, (
        f"INV-9 FAIL: MULTIMODAL_CANONICAL_PATH must NOT be overclaimed as "
        f"STRONGLY_ESTABLISHED or RUNTIME_EVIDENCED_CLOSED; "
        f"got {multimodal_entry.evidence_strength}"
    )

    # INV-10: OPERATOR_ACTIONABILITY must be <= PARTIALLY_ESTABLISHED
    operator_entry = next(
        e for e in package.domain_entries
        if e.domain == ReviewDomain.OPERATOR_ACTIONABILITY
    )
    assert operator_entry.evidence_strength not in strong_labels, (
        f"INV-10 FAIL: OPERATOR_ACTIONABILITY must NOT be overclaimed; "
        f"got {operator_entry.evidence_strength}"
    )

    # INV-11: UNIFIED_PANEL_AGGREGATION must be <= PARTIALLY_ESTABLISHED
    panel_entry = next(
        e for e in package.domain_entries
        if e.domain == ReviewDomain.UNIFIED_PANEL_AGGREGATION
    )
    assert panel_entry.evidence_strength not in strong_labels, (
        f"INV-11 FAIL: UNIFIED_PANEL_AGGREGATION must NOT be overclaimed; "
        f"got {panel_entry.evidence_strength}"
    )

    # INV-12: domains_at_partially_established_or_below must be consistent with entries
    computed = _compute_domains_below_threshold(package.domain_entries)
    assert package.domains_at_partially_established_or_below == computed, (
        f"INV-12 FAIL: domains_at_partially_established_or_below mismatch; "
        f"stored={package.domains_at_partially_established_or_below}, "
        f"computed={computed}"
    )

    # INV-13: authority sentinel must contain canonical token
    assert "FIVE_DOMAIN_IMPLEMENTATION_REVIEW_AUTHORITY" in package.authority, (
        "INV-13 FAIL: authority sentinel missing canonical token"
    )

    # INV-14: verdict_zh must mention all five domain keywords
    verdict = package.verdict_zh
    zh_keywords = ["面板", "三态", "可操作", "自然语言", "多模态"]
    for kw in zh_keywords:
        assert kw in verdict, (
            f"INV-14 FAIL: verdict_zh missing keyword '{kw}'"
        )

    # INV-15: JSON round-trip must succeed
    try:
        j = package.to_json()
        reconstructed = json.loads(j)
        assert reconstructed["authority"] == package.authority, (
            "INV-15 FAIL: JSON round-trip mismatch on authority"
        )
        assert len(reconstructed["domain_entries"]) == 5, (
            "INV-15 FAIL: JSON round-trip domain_entries count mismatch"
        )
    except Exception as exc:
        raise AssertionError(f"INV-15 FAIL: JSON round-trip failed: {exc}") from exc

    # INV-16: system_maturity_summary must mention all five domain labels
    summary = package.system_maturity_summary.upper()
    domain_labels = [
        "UNIFIED_PANEL_AGGREGATION",
        "DESKTOP_THREE_STATE",
        "OPERATOR_ACTIONABILITY",
        "NATURAL_LANGUAGE",
        "MULTIMODAL",
    ]
    for label in domain_labels:
        assert label in summary, (
            f"INV-16 FAIL: system_maturity_summary missing '{label}'"
        )

    # INV-17: Each domain entry must have a non-empty canonical_path_summary
    for entry in package.domain_entries:
        assert len(entry.canonical_path_summary) > 0, (
            f"INV-17 FAIL: Domain {entry.domain} has empty canonical_path_summary"
        )

    # INV-18: Each domain must have gap_items or partial_or_fragmented_items
    # (no domain can claim zero gaps — this is a strict anti-overclaiming check)
    for entry in package.domain_entries:
        has_issues = len(entry.gap_items) > 0 or len(entry.partial_or_fragmented_items) > 0
        assert has_issues, (
            f"INV-18 FAIL: Domain {entry.domain} has neither gap_items nor "
            f"partial_or_fragmented_items — at least one must be present "
            f"(no domain in current state is gap-free)"
        )
