# docs/ — Document Index

This directory contains architecture, protocol, audit, and operational documents for
`ufo-galaxy-realization-v2`.  With 150+ documents, this index identifies which
documents are **authoritative and current** vs historical or superseded.

---

## ACTIVE — Start here (authoritative and current)

| Document | Purpose |
|----------|---------|
| [CLONE_TO_USE_REALITY.md](CLONE_TO_USE_REALITY.md) | **Authoritative quick-start** — canonical clone-to-use runtime truth |
| [UNIFIED_SUBJECT_ARCHITECTURE.md](UNIFIED_SUBJECT_ARCHITECTURE.md) | Unified subject architecture (DesktopPresenceRuntime + OpenClawd) |
| [LOCAL_EXECUTION_CHAIN.md](LOCAL_EXECUTION_CHAIN.md) | Local execution chain step-by-step |
| [CROSS_DEVICE_EXECUTION_CHAIN.md](CROSS_DEVICE_EXECUTION_CHAIN.md) | Cross-device execution chain step-by-step |
| [ANDROID_PROTOCOL_ALIGNMENT.md](ANDROID_PROTOCOL_ALIGNMENT.md) | AIP v3.0 protocol specification (authoritative) |
| [ARCHITECTURE_COMPLETION_SCORECARD.md](ARCHITECTURE_COMPLETION_SCORECARD.md) | Architecture completion evaluation framework + PR-9 scorecard |
| [MAINTAINER_RUNBOOK.md](MAINTAINER_RUNBOOK.md) | Maintainer operational reference |
| [TEST_STRATEGY.md](TEST_STRATEGY.md) | Test layout, markers, CI jobs |
| [DEPLOYMENT_SURFACES.md](DEPLOYMENT_SURFACES.md) | Docker/compose surface catalogue |
| [SYSTEM_AUDIT_REPORT_ZH.md](SYSTEM_AUDIT_REPORT_ZH.md) | **中文联排系统性审查报告**（双仓真实架构状态 + 问题清单） |

---

## ACTIVE — Architecture audit and gap tracking

| Document | Purpose |
|----------|---------|
| [DUAL_REPO_FULL_REAUDIT.md](DUAL_REPO_FULL_REAUDIT.md) | Full dual-repo re-audit (latest, most comprehensive) |
| [DUAL_REPO_GAP_MATRIX.md](DUAL_REPO_GAP_MATRIX.md) | Structured gap matrix (supersedes all prior versions) |
| [FOLLOWUP_IMPLEMENTATION_ROADMAP.md](FOLLOWUP_IMPLEMENTATION_ROADMAP.md) | Prioritized follow-up roadmap |
| [ANDROID_PROTOCOL_MATURITY_MATRIX.md](ANDROID_PROTOCOL_MATURITY_MATRIX.md) | Android long-tail protocol maturity matrix |
| [MULTI_DEVICE_RUNTIME_MATURITY.md](MULTI_DEVICE_RUNTIME_MATURITY.md) | Multi-device runtime component maturity |
| [UNIFIED_SCHEDULING_AUTHORITY_MAP.md](UNIFIED_SCHEDULING_AUTHORITY_MAP.md) | Scheduling/routing authority chain map |
| [TRUTH_PROJECTION_CONVERGENCE_MAP.md](TRUTH_PROJECTION_CONVERGENCE_MAP.md) | Truth/projection convergence audit |

---

## ACTIVE — Domain-specific references

| Document | Purpose |
|----------|---------|
| [CONFIGURATION_AUTHORITY.md](CONFIGURATION_AUTHORITY.md) | Configuration authority chain |
| [COMMAND_PROTOCOL.md](COMMAND_PROTOCOL.md) | Command protocol specification |
| [OBSERVABILITY.md](OBSERVABILITY.md) | Observability architecture |
| [WINDOWS_STATUS_BOARD.md](WINDOWS_STATUS_BOARD.md) | Status board v2 operator surface |
| [MESH_SESSION_CONTRACT.md](MESH_SESSION_CONTRACT.md) | Mesh session contract |
| [NATS_CONTROL_PLANE.md](NATS_CONTROL_PLANE.md) | NATS control plane |
| [WEBRTC_GATEWAY.md](WEBRTC_GATEWAY.md) | WebRTC gateway |

---

## HISTORICAL — Superseded by newer versions

| Document | Superseded by |
|----------|--------------|
| [REAUDIT_FRESH_PASS_2.md](REAUDIT_FRESH_PASS_2.md) | [DUAL_REPO_FULL_REAUDIT.md](DUAL_REPO_FULL_REAUDIT.md) |
| [REAUDIT_GAP_MATRIX_V2.md](REAUDIT_GAP_MATRIX_V2.md) | [DUAL_REPO_GAP_MATRIX.md](DUAL_REPO_GAP_MATRIX.md) |
| [DUAL_REPO_UNRESOLVED_AUDIT.md](DUAL_REPO_UNRESOLVED_AUDIT.md) | [DUAL_REPO_GAP_MATRIX.md](DUAL_REPO_GAP_MATRIX.md) |
| [REAUDIT_MULTI_DEVICE_MATURITY_V2.md](REAUDIT_MULTI_DEVICE_MATURITY_V2.md) | [MULTI_DEVICE_RUNTIME_MATURITY.md](MULTI_DEVICE_RUNTIME_MATURITY.md) |
| [REAUDIT_ANDROID_PROTOCOL_V2.md](REAUDIT_ANDROID_PROTOCOL_V2.md) | [ANDROID_PROTOCOL_MATURITY_MATRIX.md](ANDROID_PROTOCOL_MATURITY_MATRIX.md) |
| [REAUDIT_SCHEDULING_AUTHORITY_V2.md](REAUDIT_SCHEDULING_AUTHORITY_V2.md) | [UNIFIED_SCHEDULING_AUTHORITY_MAP.md](UNIFIED_SCHEDULING_AUTHORITY_MAP.md) |
| [REAUDIT_FOLLOWUP_ROADMAP_V2.md](REAUDIT_FOLLOWUP_ROADMAP_V2.md) | [FOLLOWUP_IMPLEMENTATION_ROADMAP.md](FOLLOWUP_IMPLEMENTATION_ROADMAP.md) |
| [REAUDIT_GAP_MATRIX_V2.md](REAUDIT_GAP_MATRIX_V2.md) | [DUAL_REPO_GAP_MATRIX.md](DUAL_REPO_GAP_MATRIX.md) |

---

## IMPLEMENTATION REPORTS — Historical context

Implementation reports document changes made in specific PRs.  They are preserved
for historical reference but are not maintained going forward.

`GALAXY_COMPLETE_FIX_REPORT.md`, `GALAXY_CORE_LOGIC_FIX_REPORT.md`,
`HARDWARE_TRIGGER_FIX_REPORT.md`, `IMPLEMENTATION_REPORT.md`, etc.

---

*To add a new document: place it in this directory and update the ACTIVE section above.*
*Mark any document you supersede by moving it to the HISTORICAL section.*
