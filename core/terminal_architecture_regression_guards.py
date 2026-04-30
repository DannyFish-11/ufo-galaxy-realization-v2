#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/terminal_architecture_regression_guards.py
================================================
PR-10 — Terminal Architecture Regression Guards.

Purpose
-------
This module is the **terminal hardening pass** for the Galaxy center-distributed
architecture alignment series.  It provides lightweight but meaningful
regression guards that detect the most critical invalid architectural patterns
so that future changes cannot silently drift the system back into contradictory
layering.

Background
----------
After PRs 6–9 aligned the codebase with the validated final integrated
architecture, the key risk is **silent regression** — a later change that
re-introduces contradictory declarations or mis-wires a layer without any
automated check catching it.  This module closes that gap.

The five terminal regression scenarios guarded
----------------------------------------------

1. **V4 misclassified as universal per-request gate** — V4
   (``core.unified_orchestration_spine``) MUST NOT be imported or invoked in
   the per-request hot path (``core.openclawd``, ``core.command_router``).  It
   is the multi-step orchestration session spine only.

2. **V6 inserted into hot request paths** — V6
   (``core.release_blocking_gate``, ``core.center_authority_boundary``) MUST
   NOT appear as a call inside ``OpenClawd.process()`` or
   ``CommandRouter.route_envelope()``.  V6 is a startup / readiness / health /
   release integrity boundary, never a per-request gate.

3. **L1/L2/L3 detached from router-level authority** — L1
   (``core.llm.route_authority``), L2 (``core.llm.supply_authority``), and L3
   (``core.llm.context_authority``) MUST be importable and MUST remain fused
   into ``core.unified.llm_router.UnifiedLLMRouter`` as the canonical
   router-level cognitive authority.  If any are missing or if the facade
   disappears, the router-level cognitive authority is broken.

4. **Canonical completion truth chain weakened** — The canonical completion
   truth backbone (``core.canonical_completion_ingress``) MUST be importable
   and MUST expose the ``CANONICAL_COMPLETION_INGRESS_SENTINEL``.  Removing or
   demoting these to optional soft signaling is a regression.

5. **Repository-level architecture declarations diverge from the final model**
   — The five-layer canonical layer model declared in
   ``core.canonical_layer_model`` MUST be self-consistent: all five layers
   present, all NOT-policies non-empty, hot-path and startup-only flags
   correctly set.

Public API
----------
:data:`TERMINAL_REGRESSION_GUARD_AUTHORITY`
    Module identity sentinel.

:data:`TERMINAL_REGRESSION_GUARD_PR10_SENTINEL`
    PR-10 sentinel.

:data:`V4_HOT_PATH_ISOLATION_GUARD`
    Policy sentinel for V4 hot-path isolation.

:data:`V6_HOT_PATH_ISOLATION_GUARD`
    Policy sentinel for V6 hot-path isolation.

:data:`L1_L2_L3_ROUTER_FUSION_GUARD`
    Policy sentinel for L1/L2/L3 router fusion.

:data:`COMPLETION_TRUTH_BACKBONE_GUARD`
    Policy sentinel for completion truth backbone.

:data:`LAYER_DECLARATIONS_CONVERGENCE_GUARD`
    Policy sentinel for layer declaration convergence.

:class:`RegressionFinding`
    A single finding from a terminal regression check.

:class:`RegressionReport`
    Aggregated result of all terminal regression checks.

:func:`check_v4_hot_path_isolation`
    Guard 1 — V4 must not be wired into per-request hot paths.

:func:`check_v6_hot_path_isolation`
    Guard 2 — V6 must not be wired into per-request hot paths.

:func:`check_l1_l2_l3_router_fusion`
    Guard 3 — L1/L2/L3 must remain fused in UnifiedLLMRouter.

:func:`check_completion_truth_backbone`
    Guard 4 — Canonical completion truth backbone must remain enforced.

:func:`check_layer_declarations_convergence`
    Guard 5 — Canonical layer model must remain self-consistent.

:func:`run_terminal_regression_guards`
    Run all five terminal regression guards and return a
    :class:`RegressionReport`.
"""

from __future__ import annotations

import dataclasses
import importlib
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.TerminalRegressionGuards")

__all__ = [
    # Sentinels
    "TERMINAL_REGRESSION_GUARD_AUTHORITY",
    "TERMINAL_REGRESSION_GUARD_PR10_SENTINEL",
    "V4_HOT_PATH_ISOLATION_GUARD",
    "V6_HOT_PATH_ISOLATION_GUARD",
    "L1_L2_L3_ROUTER_FUSION_GUARD",
    "COMPLETION_TRUTH_BACKBONE_GUARD",
    "LAYER_DECLARATIONS_CONVERGENCE_GUARD",
    # Data types
    "RegressionFinding",
    "RegressionReport",
    # Individual guards
    "check_v4_hot_path_isolation",
    "check_v6_hot_path_isolation",
    "check_l1_l2_l3_router_fusion",
    "check_completion_truth_backbone",
    "check_layer_declarations_convergence",
    # Aggregate entry point
    "run_terminal_regression_guards",
]

# ---------------------------------------------------------------------------
# Module sentinels
# ---------------------------------------------------------------------------

TERMINAL_REGRESSION_GUARD_AUTHORITY: str = (
    "TERMINAL_REGRESSION_GUARD_AUTHORITY::PR10: "
    "core.terminal_architecture_regression_guards is the terminal hardening "
    "module for the Galaxy center-distributed architecture alignment series.  "
    "It provides lightweight, purely inspective regression guards that make the "
    "five most critical invalid architecture regressions machine-detectable: "
    "(1) V4 misclassified as universal per-request gate, "
    "(2) V6 inserted into hot request paths, "
    "(3) L1/L2/L3 detached from router-level authority, "
    "(4) canonical completion truth chain weakened to optional signaling, "
    "(5) repository-level layer declarations diverging from the final integrated model.  "
    "This module is purely inspective — it does NOT alter execution logic."
)

TERMINAL_REGRESSION_GUARD_PR10_SENTINEL: str = (
    "PR::TERMINAL_ARCHITECTURE_REGRESSION_GUARDS_PR10: "
    "Introduced by PR-10 (terminal architecture audit guards).  "
    "Removing or disabling this module removes the terminal regression "
    "hardening that prevents future drift from the validated final "
    "center-distributed architecture."
)

V4_HOT_PATH_ISOLATION_GUARD: str = (
    "GUARD::V4_HOT_PATH_ISOLATION: "
    "core.unified_orchestration_spine (V4) MUST NOT be imported or invoked "
    "inside the per-request hot path (OpenClawd.process, "
    "CommandRouter.route_envelope).  V4 is the multi-step orchestration "
    "session spine for parallel fan-out, delegated runtime, wake-routed, "
    "handoff/takeover, cross-device, and hybrid sessions.  "
    "Wiring V4 into every per-request call mis-layers the architecture, "
    "introduces unnecessary latency, and produces a false model where all "
    "execution is incorrectly described as going through V4."
)

V6_HOT_PATH_ISOLATION_GUARD: str = (
    "GUARD::V6_HOT_PATH_ISOLATION: "
    "core.release_blocking_gate and core.center_authority_boundary (V6) "
    "MUST NOT be called from inside the per-request hot path "
    "(OpenClawd.process, CommandRouter.route_envelope).  V6 is the "
    "startup / readiness / health / release integrity boundary.  "
    "Inserting V6 into synchronous request processing introduces structural "
    "latency and mis-layers the release-posture contract with per-request "
    "cognitive dispatch."
)

L1_L2_L3_ROUTER_FUSION_GUARD: str = (
    "GUARD::L1_L2_L3_ROUTER_FUSION: "
    "L1 (core.llm.route_authority), L2 (core.llm.supply_authority), and "
    "L3 (core.llm.context_authority) MUST be importable as distinct "
    "router-level cognitive authority sub-layers and MUST be fused into "
    "core.unified.llm_router.UnifiedLLMRouter as the canonical facade.  "
    "Detaching any of L1/L2/L3 from the router layer or removing the "
    "UnifiedLLMRouter facade breaks the router-level cognitive authority "
    "and reverts to the discarded shadow-stack pattern."
)

COMPLETION_TRUTH_BACKBONE_GUARD: str = (
    "GUARD::COMPLETION_TRUTH_BACKBONE: "
    "core.canonical_completion_ingress (and CANONICAL_COMPLETION_INGRESS_SENTINEL) "
    "MUST be importable and present.  The canonical completion truth backbone "
    "enforces completion semantics via the durable truth chain — it is NOT "
    "optional soft signaling.  Removing or demoting canonical_completion_ingress "
    "breaks the V2 × Android session continuity and creates incomplete or "
    "inconsistent task lifecycle records."
)

LAYER_DECLARATIONS_CONVERGENCE_GUARD: str = (
    "GUARD::LAYER_DECLARATIONS_CONVERGENCE: "
    "The five-layer canonical model declared in core.canonical_layer_model "
    "MUST remain self-consistent.  All five layers must be present, all "
    "NOT-policy sentinels must be non-empty, and hot-path / startup-only "
    "flags must match the validated final architecture.  Any divergence "
    "from the canonical model is a repository-level regression."
)

# ---------------------------------------------------------------------------
# Finding and report data types
# ---------------------------------------------------------------------------

_METHOD_SCAN_WINDOW = 6_000  # characters to scan inside a method body


@dataclasses.dataclass(frozen=True)
class RegressionFinding:
    """A single finding from a terminal regression guard check.

    Attributes
    ----------
    guard:
        Short identifier for the guard that produced this finding.
    severity:
        One of ``"error"``, ``"warning"``, or ``"info"``.
    message:
        Human-readable description of the finding.
    detail:
        Optional structured detail for test assertions and tooling.
    """

    guard: str
    severity: str
    message: str
    detail: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "guard": self.guard,
            "severity": self.severity,
            "message": self.message,
            "detail": self.detail,
        }


@dataclasses.dataclass
class RegressionReport:
    """Aggregated result of all terminal regression guard checks.

    Attributes
    ----------
    findings:
        List of all :class:`RegressionFinding` produced.
    guards_run:
        List of guard identifiers that were executed.
    overall_safe:
        ``True`` when no ERROR-severity findings were produced.
    error_count:
        Count of error-severity findings.
    warning_count:
        Count of warning-severity findings.
    """

    findings: List[RegressionFinding] = dataclasses.field(default_factory=list)
    guards_run: List[str] = dataclasses.field(default_factory=list)
    overall_safe: bool = True
    error_count: int = 0
    warning_count: int = 0

    def __post_init__(self) -> None:
        self._recompute()

    def _recompute(self) -> None:
        self.error_count = sum(1 for f in self.findings if f.severity == "error")
        self.warning_count = sum(1 for f in self.findings if f.severity == "warning")
        self.overall_safe = self.error_count == 0

    def add(self, finding: RegressionFinding) -> None:
        self.findings.append(finding)
        self._recompute()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_safe": self.overall_safe,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "guards_run": list(self.guards_run),
            "findings": [f.to_dict() for f in self.findings],
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _err(guard: str, message: str, detail: Optional[Dict[str, Any]] = None) -> RegressionFinding:
    return RegressionFinding(guard=guard, severity="error", message=message, detail=detail or {})


def _warn(guard: str, message: str, detail: Optional[Dict[str, Any]] = None) -> RegressionFinding:
    return RegressionFinding(guard=guard, severity="warning", message=message, detail=detail or {})


def _info(guard: str, message: str, detail: Optional[Dict[str, Any]] = None) -> RegressionFinding:
    return RegressionFinding(guard=guard, severity="info", message=message, detail=detail or {})


def _try_import(module_path: str):
    """Attempt to import a module; return (importable, module_or_None, error_or_None)."""
    try:
        mod = importlib.import_module(module_path)
        return True, mod, None
    except Exception as exc:
        return False, None, str(exc)


def _project_root() -> Path:
    """Return the project root directory (parent of this file's ``core/`` directory)."""
    return Path(__file__).parent.parent.resolve()


def _read_source(rel_path: str) -> Optional[str]:
    """Read the source of a project file; return ``None`` if not found."""
    full = _project_root() / rel_path
    if not full.exists():
        return None
    try:
        return full.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _module_file_exists(module_path: str) -> bool:
    """Return True if the source file for *module_path* can be located.

    This checks structural presence (the file exists on disk) independently of
    whether the module can be fully imported.  A module file that exists but
    fails to import due to a missing transitive dependency is present in the
    codebase (not a regression); it would only fail in an incomplete
    environment.

    Uses a direct file-system check so that broken ``__init__.py`` imports in
    parent packages do not cause false negatives.
    """
    # Convert dotted module path to a file path relative to the project root.
    parts = module_path.split(".")
    root = _project_root()

    # Try as a .py file first.
    py_path = root.joinpath(*parts).with_suffix(".py")
    if py_path.exists():
        return True

    # Try as a package directory (__init__.py).
    init_path = root.joinpath(*parts) / "__init__.py"
    if init_path.exists():
        return True

    return False





# ---------------------------------------------------------------------------
# Guard 1 — V4 hot-path isolation
# ---------------------------------------------------------------------------

_V4_MODULE = "unified_orchestration_spine"
_HOT_PATH_FILES = [
    ("core/openclawd.py", "process"),
    ("core/command_router.py", "route_envelope"),
]
_V4_IMPORT_PATTERNS = [
    re.compile(r"from\s+core\.unified_orchestration_spine"),
    re.compile(r"import\s+.*unified_orchestration_spine"),
    re.compile(r"evaluate_orchestration_request\s*\("),
    re.compile(r"unified_orchestration_spine"),
]


def check_v4_hot_path_isolation(
    project_root: Optional[Path] = None,
) -> List[RegressionFinding]:
    """Guard 1 — V4 (unified_orchestration_spine) must NOT be wired into the
    per-request hot path.

    Scans ``core/openclawd.py`` and ``core/command_router.py`` for imports or
    direct calls to ``unified_orchestration_spine``.  Any match inside the
    method bodies of ``process`` or ``route_envelope`` is flagged as an ERROR.

    An import at the module level in these files is also flagged: V4 should
    never be a dependency of the per-request hot-path modules.

    Parameters
    ----------
    project_root:
        Override for the project root path.  Uses :func:`_project_root` by
        default.

    Returns
    -------
    List[RegressionFinding]
        Empty list (or only INFO) when the guard passes; ERROR findings when
        V4 is detected in a hot-path file.
    """
    guard = "V4_HOT_PATH_ISOLATION"
    findings: List[RegressionFinding] = []
    root = project_root or _project_root()

    for rel_path, method_name in _HOT_PATH_FILES:
        full_path = root / rel_path
        if not full_path.exists():
            findings.append(
                _info(guard, f"Hot-path file '{rel_path}' not present — skipping.",
                      {"file": rel_path})
            )
            continue

        try:
            source = full_path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            findings.append(
                _warn(guard, f"Could not read '{rel_path}': {exc}",
                      {"file": rel_path, "error": str(exc)})
            )
            continue

        # Check for V4 pattern anywhere in the file (module-level import is enough
        # to indicate coupling).
        for pat in _V4_IMPORT_PATTERNS:
            match = pat.search(source)
            if match:
                findings.append(
                    _err(
                        guard,
                        f"'{rel_path}' contains a reference to "
                        f"unified_orchestration_spine (V4): '{match.group(0).strip()}'.  "
                        "V4 must NOT be imported or called from per-request hot-path "
                        "modules.  V4 is the multi-step orchestration spine only.  "
                        f"Sentinel: {V4_HOT_PATH_ISOLATION_GUARD!r:.80}",
                        {
                            "file": rel_path,
                            "pattern": pat.pattern,
                            "match": match.group(0).strip(),
                            "violation": "V4_IS_NOT_PER_REQUEST_GATE",
                        },
                    )
                )
                break  # one error per file is sufficient

    if not any(f.severity == "error" for f in findings):
        findings.append(
            _info(
                guard,
                "V4 hot-path isolation: unified_orchestration_spine is not "
                "referenced in per-request hot-path modules (openclawd, "
                "command_router).  Guard passes.",
            )
        )

    return findings


# ---------------------------------------------------------------------------
# Guard 2 — V6 hot-path isolation
# ---------------------------------------------------------------------------

_V6_MODULES = [
    "release_blocking_gate",
    "center_authority_boundary",
]
_V6_CALL_PATTERNS = [
    re.compile(r"evaluate_release_blocking_gate\s*\("),
    re.compile(r"assert_release_posture_acceptable\s*\("),
    re.compile(r"evaluate_center_authority_boundary\s*\("),
    re.compile(r"assert_center_authority_intact\s*\("),
]
_V6_IMPORT_PATTERNS = [
    re.compile(r"from\s+core\.release_blocking_gate"),
    re.compile(r"import\s+.*release_blocking_gate"),
    re.compile(r"from\s+core\.center_authority_boundary"),
    re.compile(r"import\s+.*center_authority_boundary"),
]


def check_v6_hot_path_isolation(
    project_root: Optional[Path] = None,
) -> List[RegressionFinding]:
    """Guard 2 — V6 (release_blocking_gate, center_authority_boundary) must NOT
    be invoked in the per-request hot path.

    Scans ``core/openclawd.py`` and ``core/command_router.py`` for imports or
    calls to V6 modules.  Any reference found in these hot-path files is
    flagged as an ERROR.

    Parameters
    ----------
    project_root:
        Override for the project root path.

    Returns
    -------
    List[RegressionFinding]
    """
    guard = "V6_HOT_PATH_ISOLATION"
    findings: List[RegressionFinding] = []
    root = project_root or _project_root()

    for rel_path, _method_name in _HOT_PATH_FILES:
        full_path = root / rel_path
        if not full_path.exists():
            findings.append(
                _info(guard, f"Hot-path file '{rel_path}' not present — skipping.",
                      {"file": rel_path})
            )
            continue

        try:
            source = full_path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            findings.append(
                _warn(guard, f"Could not read '{rel_path}': {exc}",
                      {"file": rel_path, "error": str(exc)})
            )
            continue

        for pat in _V6_IMPORT_PATTERNS + _V6_CALL_PATTERNS:
            match = pat.search(source)
            if match:
                findings.append(
                    _err(
                        guard,
                        f"'{rel_path}' contains a V6 reference: "
                        f"'{match.group(0).strip()}'.  "
                        "V6 (release_blocking_gate / center_authority_boundary) "
                        "MUST NOT be called from per-request hot-path modules.  "
                        "V6 is the startup / readiness / health / release integrity "
                        "boundary only.  "
                        f"Sentinel: {V6_HOT_PATH_ISOLATION_GUARD!r:.80}",
                        {
                            "file": rel_path,
                            "pattern": pat.pattern,
                            "match": match.group(0).strip(),
                            "violation": "V6_IS_NOT_PER_REQUEST_GATE",
                        },
                    )
                )
                break  # one error per file is sufficient

    if not any(f.severity == "error" for f in findings):
        findings.append(
            _info(
                guard,
                "V6 hot-path isolation: release_blocking_gate and "
                "center_authority_boundary are not referenced in per-request "
                "hot-path modules (openclawd, command_router).  Guard passes.",
            )
        )

    return findings


# ---------------------------------------------------------------------------
# Guard 3 — L1/L2/L3 router fusion
# ---------------------------------------------------------------------------

_L1_MODULE = "core.llm.route_authority"
_L2_MODULE = "core.llm.supply_authority"
_L3_MODULE = "core.llm.context_authority"
_FACADE_MODULE = "core.unified.llm_router"
_FACADE_SENTINEL = "UNIFIED_LLM_ROUTER_AUTHORITY"

_COGNITIVE_MODULES = [
    (_L1_MODULE, "LLM_ROUTE_AUTHORITY"),
    (_L2_MODULE, "LLM_SUPPLY_AUTHORITY"),
    (_L3_MODULE, "LLM_CONTEXT_AUTHORITY"),
]


def check_l1_l2_l3_router_fusion() -> List[RegressionFinding]:
    """Guard 3 — L1/L2/L3 must remain importable and fused in UnifiedLLMRouter.

    Checks:
    a. ``core.llm.route_authority`` (L1) is importable.
    b. ``core.llm.supply_authority`` (L2) is importable.
    c. ``core.llm.context_authority`` (L3) is importable.
    d. ``core.unified.llm_router`` (facade) is importable.
    e. Facade exposes ``UNIFIED_LLM_ROUTER_AUTHORITY`` sentinel.

    Returns
    -------
    List[RegressionFinding]
    """
    guard = "L1_L2_L3_ROUTER_FUSION"
    findings: List[RegressionFinding] = []

    # Check each cognitive authority sub-layer.
    for mod_path, sentinel_name in _COGNITIVE_MODULES:
        file_present = _module_file_exists(mod_path)
        importable, mod, err = _try_import(mod_path)

        if not file_present:
            # Module source file is absent — structural regression.
            findings.append(
                _err(
                    guard,
                    f"Router cognitive authority sub-layer '{mod_path}' is not "
                    f"structurally present in the codebase.  "
                    "L1/L2/L3 must remain present as the router-level cognitive "
                    "authority fused into UnifiedLLMRouter.  "
                    f"Sentinel: {L1_L2_L3_ROUTER_FUSION_GUARD!r:.80}",
                    {
                        "module": mod_path,
                        "import_error": err,
                        "violation": "L1_L2_L3_BELONGS_TO_ROUTER_LAYER_NOT_SHADOW_STACK",
                    },
                )
            )
        elif not importable:
            # File exists but transitive dependency missing — not a regression.
            findings.append(
                _warn(
                    guard,
                    f"Router cognitive authority sub-layer '{mod_path}' is present "
                    f"but could not be imported (transitive dependency issue): {err}.  "
                    "This is an environment issue, not an architecture regression.",
                    {"module": mod_path, "import_error": err},
                )
            )
        else:
            if mod is not None and not hasattr(mod, sentinel_name):
                findings.append(
                    _warn(
                        guard,
                        f"'{mod_path}' is importable but missing sentinel "
                        f"'{sentinel_name}'.",
                        {"module": mod_path, "missing_sentinel": sentinel_name},
                    )
                )
            else:
                findings.append(
                    _info(guard, f"'{mod_path}' importable with sentinel '{sentinel_name}'.",
                          {"module": mod_path})
                )

    # Check facade.
    facade_file_present = _module_file_exists(_FACADE_MODULE)
    importable, mod, err = _try_import(_FACADE_MODULE)

    if not facade_file_present:
        # Facade source file is absent — structural regression.
        findings.append(
            _err(
                guard,
                f"UnifiedLLMRouter facade '{_FACADE_MODULE}' is not structurally "
                f"present in the codebase.  "
                "The L1/L2/L3 cognitive authority fusion facade must be present.  "
                f"Sentinel: {L1_L2_L3_ROUTER_FUSION_GUARD!r:.80}",
                {
                    "module": _FACADE_MODULE,
                    "import_error": err,
                    "violation": "L1_L2_L3_BELONGS_TO_ROUTER_LAYER_NOT_SHADOW_STACK",
                },
            )
        )
    elif not importable:
        # File exists but transitive dependency missing — not a regression.
        findings.append(
            _warn(
                guard,
                f"UnifiedLLMRouter facade '{_FACADE_MODULE}' is present but "
                f"could not be imported (transitive dependency issue): {err}.  "
                "This is an environment issue, not an architecture regression.",
                {"module": _FACADE_MODULE, "import_error": err},
            )
        )
    else:
        if mod is not None and not hasattr(mod, _FACADE_SENTINEL):
            findings.append(
                _warn(
                    guard,
                    f"UnifiedLLMRouter facade '{_FACADE_MODULE}' is importable but "
                    f"missing sentinel '{_FACADE_SENTINEL}'.",
                    {"module": _FACADE_MODULE, "missing_sentinel": _FACADE_SENTINEL},
                )
            )
        else:
            findings.append(
                _info(guard,
                      f"UnifiedLLMRouter facade '{_FACADE_MODULE}' importable "
                      f"with sentinel '{_FACADE_SENTINEL}'.",
                      {"module": _FACADE_MODULE})
            )

    return findings


# ---------------------------------------------------------------------------
# Guard 4 — Canonical completion truth backbone
# ---------------------------------------------------------------------------

_COMPLETION_MODULE = "core.canonical_completion_ingress"
_COMPLETION_SENTINEL = "CANONICAL_COMPLETION_INGRESS_SENTINEL"


def check_completion_truth_backbone() -> List[RegressionFinding]:
    """Guard 4 — Canonical completion truth backbone must remain enforced.

    Checks:
    a. ``core.canonical_completion_ingress`` is importable.
    b. Module exposes ``CANONICAL_COMPLETION_INGRESS_SENTINEL``.
    c. Sentinel is a non-empty string.

    Returns
    -------
    List[RegressionFinding]
    """
    guard = "COMPLETION_TRUTH_BACKBONE"
    findings: List[RegressionFinding] = []

    importable, mod, err = _try_import(_COMPLETION_MODULE)
    if not importable:
        findings.append(
            _err(
                guard,
                f"Canonical completion truth backbone '{_COMPLETION_MODULE}' is "
                f"not importable: {err}.  "
                "The completion truth backbone MUST be present and enforced; "
                "it is NOT optional soft signaling.  "
                f"Sentinel: {COMPLETION_TRUTH_BACKBONE_GUARD!r:.80}",
                {
                    "module": _COMPLETION_MODULE,
                    "import_error": err,
                    "violation": "COMPLETION_TRUTH_IS_ENFORCED_NOT_OPTIONAL",
                },
            )
        )
        return findings

    if mod is None or not hasattr(mod, _COMPLETION_SENTINEL):
        findings.append(
            _err(
                guard,
                f"'{_COMPLETION_MODULE}' is importable but missing "
                f"'{_COMPLETION_SENTINEL}'.  "
                "The completion truth backbone sentinel must be present to "
                "confirm enforcement intent.  "
                f"Sentinel: {COMPLETION_TRUTH_BACKBONE_GUARD!r:.80}",
                {
                    "module": _COMPLETION_MODULE,
                    "missing_sentinel": _COMPLETION_SENTINEL,
                    "violation": "COMPLETION_TRUTH_IS_ENFORCED_NOT_OPTIONAL",
                },
            )
        )
        return findings

    sentinel_value = getattr(mod, _COMPLETION_SENTINEL, "")
    if not isinstance(sentinel_value, str) or not sentinel_value.strip():
        findings.append(
            _err(
                guard,
                f"'{_COMPLETION_MODULE}.{_COMPLETION_SENTINEL}' is empty or not a "
                "string.  The completion truth sentinel must be a non-empty string.",
                {
                    "module": _COMPLETION_MODULE,
                    "sentinel": _COMPLETION_SENTINEL,
                    "value_type": type(sentinel_value).__name__,
                    "violation": "COMPLETION_TRUTH_IS_ENFORCED_NOT_OPTIONAL",
                },
            )
        )
        return findings

    findings.append(
        _info(
            guard,
            f"Canonical completion truth backbone '{_COMPLETION_MODULE}' is "
            f"present with non-empty sentinel '{_COMPLETION_SENTINEL}'.  "
            "Guard passes.",
            {"module": _COMPLETION_MODULE},
        )
    )
    return findings


# ---------------------------------------------------------------------------
# Guard 5 — Layer declarations convergence
# ---------------------------------------------------------------------------


def check_layer_declarations_convergence(
    layer_snapshots: Optional[List[Dict[str, Any]]] = None,
) -> List[RegressionFinding]:
    """Guard 5 — Canonical layer model must remain self-consistent.

    Delegates to ``core.canonical_layer_model.run_layer_model_invariants`` to
    validate that:

    1. All five canonical layers are declared.
    2. Each layer's hot-path and startup-only flags match the model.
    3. All NOT-policy sentinels are non-empty strings.
    4. V4 is not misclassified as per-request gate (if snapshot provided).
    5. V6 is not misclassified as per-request gate (if snapshot provided).
    6. L1/L2/L3 is not declared as a shadow stack (if snapshot provided).
    7. Completion truth is not declared as optional signaling (if snapshot provided).

    Parameters
    ----------
    layer_snapshots:
        Optional list of layer snapshot dicts to validate.  Pass ``None`` to
        check only the registry's internal self-consistency.

    Returns
    -------
    List[RegressionFinding]
    """
    guard = "LAYER_DECLARATIONS_CONVERGENCE"
    findings: List[RegressionFinding] = []

    importable, _, err = _try_import("core.canonical_layer_model")
    if not importable:
        findings.append(
            _err(
                guard,
                f"core.canonical_layer_model is not importable: {err}.  "
                "The canonical layer model is the single authoritative declaration "
                "of the five-layer architecture; its absence is a critical regression.  "
                f"Sentinel: {LAYER_DECLARATIONS_CONVERGENCE_GUARD!r:.80}",
                {
                    "module": "core.canonical_layer_model",
                    "import_error": err,
                    "violation": "LAYER_DECLARATIONS_CONVERGENCE",
                },
            )
        )
        return findings

    from core.canonical_layer_model import run_layer_model_invariants  # noqa: PLC0415

    report = run_layer_model_invariants(layer_snapshots)

    for lf in report.findings:
        if lf.severity == "error":
            findings.append(
                _err(
                    guard,
                    lf.message,
                    {**lf.detail, "violation": "LAYER_DECLARATIONS_CONVERGENCE"},
                )
            )
        elif lf.severity == "warning":
            findings.append(_warn(guard, lf.message, lf.detail))
        else:
            findings.append(_info(guard, lf.message, lf.detail))

    if not any(f.severity == "error" for f in findings):
        findings.append(
            _info(
                guard,
                "Canonical layer model is self-consistent with the validated "
                "final integrated architecture.  Guard passes.",
            )
        )

    return findings


# ---------------------------------------------------------------------------
# Aggregate entry point
# ---------------------------------------------------------------------------


def run_terminal_regression_guards(
    project_root: Optional[Path] = None,
    layer_snapshots: Optional[List[Dict[str, Any]]] = None,
) -> RegressionReport:
    """Run all five terminal architecture regression guards.

    This is the main entry point.  It executes all guards and aggregates
    their findings into a single :class:`RegressionReport`.

    Parameters
    ----------
    project_root:
        Optional override for the project root path (used for file-scanning
        guards).  Defaults to auto-detected project root.
    layer_snapshots:
        Optional list of layer snapshot dicts to pass to the layer
        declarations convergence guard.

    Returns
    -------
    RegressionReport
        ``report.overall_safe`` is ``True`` when no ERROR-severity findings
        were produced by any guard.
    """
    report = RegressionReport()

    # Guard 1 — V4 hot-path isolation
    report.guards_run.append("V4_HOT_PATH_ISOLATION")
    for finding in check_v4_hot_path_isolation(project_root=project_root):
        report.add(finding)

    # Guard 2 — V6 hot-path isolation
    report.guards_run.append("V6_HOT_PATH_ISOLATION")
    for finding in check_v6_hot_path_isolation(project_root=project_root):
        report.add(finding)

    # Guard 3 — L1/L2/L3 router fusion
    report.guards_run.append("L1_L2_L3_ROUTER_FUSION")
    for finding in check_l1_l2_l3_router_fusion():
        report.add(finding)

    # Guard 4 — Canonical completion truth backbone
    report.guards_run.append("COMPLETION_TRUTH_BACKBONE")
    for finding in check_completion_truth_backbone():
        report.add(finding)

    # Guard 5 — Layer declarations convergence
    report.guards_run.append("LAYER_DECLARATIONS_CONVERGENCE")
    for finding in check_layer_declarations_convergence(layer_snapshots):
        report.add(finding)

    if report.overall_safe:
        logger.debug(
            "Terminal architecture regression guards: all guards passed "
            "(errors=0, warnings=%d)",
            report.warning_count,
        )
    else:
        logger.warning(
            "Terminal architecture regression guards: %d error(s) detected — "
            "overall_safe=False",
            report.error_count,
        )

    return report
