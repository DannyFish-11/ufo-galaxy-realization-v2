# docs/ — Document Index

This directory contains architecture, protocol, audit, and operational documents for
`ufo-galaxy-realization-v2`. With 272 documents, this index identifies which
documents are **authoritative and current** vs historical or superseded.

---

## Document Status Legend

| Status | Meaning | Count |
|--------|---------|-------|
| **ACTIVE** | Current, authoritative, maintained | 216 |
| **HISTORICAL** | Records historical decisions; valuable reference but may be outdated | 55 |
| **SUPERSEDED** | Replaced by a newer document; includes redirect link | 7 |
| **DEPRECATED** | No longer used; retirement notice at top | 1 |

---

## ACTIVE — Core Authoritative Documents (Start Here)

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
| [DEPLOYMENT_COMPLETE.md](DEPLOYMENT_COMPLETE.md) | Complete deployment guide (Gateway → NATS → Node_71) |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Deployment environment variables and configuration |
| [ACCEPTANCE_CHECKLIST.md](ACCEPTANCE_CHECKLIST.md) | System deployment acceptance checklist |
| [troubleshooting.md](troubleshooting.md) | Troubleshooting guide |
| [SYSTEM_AUDIT_REPORT_ZH.md](SYSTEM_AUDIT_REPORT_ZH.md) | **中文联排系统性审查报告** (双仓真实架构状态 + 问题清单) |
| [FINAL_INTEGRATED_SYSTEM_AUDIT.md](FINAL_INTEGRATED_SYSTEM_AUDIT.md) | Galaxy 系统最终整合审查报告 |
| [DASHBOARD_RETIREMENT_AND_MIGRATION.md](DASHBOARD_RETIREMENT_AND_MIGRATION.md) | Dashboard retirement declaration and migration guide |

---

## ACTIVE — Architecture Audit and Gap Tracking

| Document | Purpose |
|----------|---------|
| [DUAL_REPO_FULL_REAUDIT.md](DUAL_REPO_FULL_REAUDIT.md) | Full dual-repo re-audit (latest, most comprehensive) |
| [DUAL_REPO_GAP_MATRIX.md](DUAL_REPO_GAP_MATRIX.md) | Structured gap matrix (supersedes all prior versions) |
| [FOLLOWUP_IMPLEMENTATION_ROADMAP.md](FOLLOWUP_IMPLEMENTATION_ROADMAP.md) | Prioritized follow-up roadmap |
| [ANDROID_PROTOCOL_MATURITY_MATRIX.md](ANDROID_PROTOCOL_MATURITY_MATRIX.md) | Android long-tail protocol maturity matrix |
| [MULTI_DEVICE_RUNTIME_MATURITY.md](MULTI_DEVICE_RUNTIME_MATURITY.md) | Multi-device runtime component maturity |
| [UNIFIED_SCHEDULING_AUTHORITY_MAP.md](UNIFIED_SCHEDULING_AUTHORITY_MAP.md) | Scheduling/routing authority chain map |
| [TRUTH_PROJECTION_CONVERGENCE_MAP.md](TRUTH_PROJECTION_CONVERGENCE_MAP.md) | Truth/projection convergence audit |
| [DUAL_REPO_COGNITION_AUDIT_ZH.md](DUAL_REPO_COGNITION_AUDIT_ZH.md) | 双仓联合认知审查 (中文版) |
| [CODE_EVIDENCE_DUAL_REPO_SYSTEM_AUDIT.md](CODE_EVIDENCE_DUAL_REPO_SYSTEM_AUDIT.md) | 双仓联合纯代码证据审查 |
| [GALAXY_SYSTEM_FORMAL_BASELINE_COGNITION_ZH.md](GALAXY_SYSTEM_FORMAL_BASELINE_COGNITION_ZH.md) | Galaxy 双仓系统正式基线认知文档 |
| [MATURITY_REVIEW_2026Q2_DUAL_COORD.md](MATURITY_REVIEW_2026Q2_DUAL_COORD.md) | 双坐标系成熟度映射审查 2026Q2 |
| [DUAL_REPO_SYSTEM_COMPLETENESS_REVIEW.md](DUAL_REPO_SYSTEM_COMPLETENESS_REVIEW.md) | 双仓系统完整性审查 |
| [DUAL_REPO_COGNITIVE_MAP.md](DUAL_REPO_COGNITIVE_MAP.md) | 双仓认知地图 |

---

## ACTIVE — Architecture Baseline and Governance

| Document | Purpose |
|----------|---------|
| [ARCHITECTURE_BASELINE.md](ARCHITECTURE_BASELINE.md) | Architecture baseline — terminal state after PR-11 |
| [ARCHITECTURE_STATUS_SURFACE.md](ARCHITECTURE_STATUS_SURFACE.md) | Architecture status surface |
| [LEGACY_SURFACES.md](LEGACY_SURFACES.md) | Authoritative registry of retired legacy surfaces |
| [LEGACY_DECOMMISSION_AUDIT.md](LEGACY_DECOMMISSION_AUDIT.md) | PR-516 legacy system decommission audit |
| [LEGACY_PURGE_HARDENING.md](LEGACY_PURGE_HARDENING.md) | PR-10 final legacy purge and baseline hardening |
| [MAINLINE_CONVERGENCE.md](MAINLINE_CONVERGENCE.md) | PR-8 system convergence and mainline integration |
| [ARCHITECTURE_GAP_CLOSURE.md](ARCHITECTURE_GAP_CLOSURE.md) | Architecture gap closure: multi-device runtime, compatibility, convergence |
| [AUTHORITATIVE_PATH_CONVERGENCE_AUDIT.md](AUTHORITATIVE_PATH_CONVERGENCE_AUDIT.md) | Authoritative path convergence audit |
| [BOUNDED_SUBJECT_PLATFORM_BOUNDARY_V1.md](BOUNDED_SUBJECT_PLATFORM_BOUNDARY_V1.md) | Bounded subject platform boundary v1 |
| [CANONICAL_TASK_EXECUTION_SPINE.md](CANONICAL_TASK_EXECUTION_SPINE.md) | PR-A: canonical task & execution spine |
| [COMPLETE_SYSTEM_USABILITY_CLOSURE_PLAN.md](COMPLETE_SYSTEM_USABILITY_CLOSURE_PLAN.md) | Complete system usability closure plan |
| [CONTRACT_TRUTH_POLICY_CLOSURE.md](CONTRACT_TRUTH_POLICY_CLOSURE.md) | Contract truth policy closure |

---

## ACTIVE — Configuration, Migration, and Policy

| Document | Purpose |
|----------|---------|
| [CONFIGURATION_AUTHORITY.md](CONFIGURATION_AUTHORITY.md) | Configuration authority chain |
| [CONFIGURATION_ENTRY_UNIFICATION.md](CONFIGURATION_ENTRY_UNIFICATION.md) | Configuration entry unification |
| [CONFIG_GOVERNANCE.md](CONFIG_GOVERNANCE.md) | Configuration governance |
| [ADR_STATUS_BOARD_CONFIG_AUTHORITY.md](ADR_STATUS_BOARD_CONFIG_AUTHORITY.md) | ADR: status board as sole desktop configuration entry surface |
| [migration/DEPRECATION_POLICY.md](migration/DEPRECATION_POLICY.md) | Deprecation policy |
| [migration/LEGACY_SURFACE_INVENTORY.md](migration/LEGACY_SURFACE_INVENTORY.md) | Legacy surface inventory |
| [migration/REMOVAL_CRITERIA.md](migration/REMOVAL_CRITERIA.md) | Removal criteria |
| [migration/unified_migration_matrix.md](migration/unified_migration_matrix.md) | Unified migration matrix (U1–U33 + PR-8) |
| [COMPATIBILITY_TOGGLES.md](COMPATIBILITY_TOGGLES.md) | Compatibility toggles |
| [COMPATIBILITY_RETIREMENT_IMPACT_MAP.md](COMPATIBILITY_RETIREMENT_IMPACT_MAP.md) | Compatibility retirement impact map |
| [COMPAT_FALLBACK_AUTHORITY_BOUNDARY.md](COMPAT_FALLBACK_AUTHORITY_BOUNDARY.md) | Compatibility fallback authority boundary |

---

## ACTIVE — Domain-Specific References

| Document | Purpose |
|----------|---------|
| [COMMAND_PROTOCOL.md](COMMAND_PROTOCOL.md) | Command protocol specification |
| [V2_ANDROID_TRUTH_CONTRACT.md](V2_ANDROID_TRUTH_CONTRACT.md) | Canonical Android truth contract and fallback semantics for V2 governance |
| [OBSERVABILITY.md](OBSERVABILITY.md) | Observability architecture |
| [OBSERVABILITY_HISTORY.md](OBSERVABILITY_HISTORY.md) | PR-14 observability and history layer |
| [WINDOWS_STATUS_BOARD.md](WINDOWS_STATUS_BOARD.md) | Status board v2 operator surface |
| [MESH_SESSION_CONTRACT.md](MESH_SESSION_CONTRACT.md) | Mesh session contract |
| [MESH_MEMBERSHIP_CONTRACT.md](MESH_MEMBERSHIP_CONTRACT.md) | Mesh membership contract |
| [MESH_SESSION_COORDINATOR.md](MESH_SESSION_COORDINATOR.md) | Mesh session coordinator |
| [LIVE_MESH_SESSION_COORDINATOR.md](LIVE_MESH_SESSION_COORDINATOR.md) | Live mesh session coordinator |
| [NATS_CONTROL_PLANE.md](NATS_CONTROL_PLANE.md) | NATS control plane |
| [WEBRTC_GATEWAY.md](WEBRTC_GATEWAY.md) | WebRTC gateway |
| [HANDOFF_ENVELOPE_V2.md](HANDOFF_ENVELOPE_V2.md) | Handoff envelope V2 |
| [CANONICAL_DEVICE_IDENTITY_CONTRACT.md](CANONICAL_DEVICE_IDENTITY_CONTRACT.md) | Canonical device identity contract |
| [INGRESS_NORMALIZATION_CONTRACT.md](INGRESS_NORMALIZATION_CONTRACT.md) | Ingress normalization contract |
| [CROSS_DEVICE_CONTROL_PLANE_ARCHITECTURE.md](CROSS_DEVICE_CONTROL_PLANE_ARCHITECTURE.md) | Cross-device control plane architecture |
| [CROSS_DEVICE_ROLE_ROUTING_POLICY.md](CROSS_DEVICE_ROLE_ROUTING_POLICY.md) | Cross-device role routing policy |
| [DISTRIBUTED_TASK_MERGE_RECOVERY.md](DISTRIBUTED_TASK_MERGE_RECOVERY.md) | Distributed task merge recovery |
| [CROSS_PLANE_CONTRACT_MAP.md](CROSS_PLANE_CONTRACT_MAP.md) | Cross-plane contract map |
| [CROSS_RUNTIME_RESULT_MERGE_CONTRACT.md](CROSS_RUNTIME_RESULT_MERGE_CONTRACT.md) | Cross-runtime result merge contract |
| [CROSS_REPO_SIGNAL_CLOSURE_VALIDATION_MATRIX.md](CROSS_REPO_SIGNAL_CLOSURE_VALIDATION_MATRIX.md) | Cross-repo signal closure validation matrix |

---

## ACTIVE — Execution, Policy, and Decision

| Document | Purpose |
|----------|---------|
| [EXECUTION_POLICY_ENFORCEMENT.md](EXECUTION_POLICY_ENFORCEMENT.md) | Execution policy enforcement |
| [EXECUTION_POLICY_SCHEMA.md](EXECUTION_POLICY_SCHEMA.md) | Execution policy schema |
| [EXECUTION_POLICY_ALIGNMENT_SURFACE.md](EXECUTION_POLICY_ALIGNMENT_SURFACE.md) | Execution policy alignment surface |
| [EXECUTION_READINESS_GATE.md](EXECUTION_READINESS_GATE.md) | Execution readiness gate |
| [EXECUTION_TRACE_CONTRACT.md](EXECUTION_TRACE_CONTRACT.md) | Execution trace contract |
| [EXECUTION_OBSERVABILITY_UNIFICATION.md](EXECUTION_OBSERVABILITY_UNIFICATION.md) | Execution observability unification |
| [EXECUTION_INTENT_PROFILE.md](EXECUTION_INTENT_PROFILE.md) | Execution intent profile |
| [EXECUTION_ENVELOPE_CONSOLIDATION.md](EXECUTION_ENVELOPE_CONSOLIDATION.md) | Execution envelope consolidation |
| [DECISION_DIFF_TELEMETRY.md](DECISION_DIFF_TELEMETRY.md) | Decision diff telemetry |
| [DECISION_EXECUTION_POLICY.md](DECISION_EXECUTION_POLICY.md) | Decision execution policy |
| [DECISION_GATE_SPEC.md](DECISION_GATE_SPEC.md) | Decision gate specification |
| [FALLBACK_DECISION_TRACE.md](FALLBACK_DECISION_TRACE.md) | Fallback decision trace |
| [DELIVERY_SEMANTICS_AND_RELIABILITY_CONTRACT.md](DELIVERY_SEMANTICS_AND_RELIABILITY_CONTRACT.md) | Delivery semantics and reliability contract |

---

## ACTIVE — Desktop and UI

| Document | Purpose |
|----------|---------|
| [DESKTOP_STATUS_BOARD_UI.md](DESKTOP_STATUS_BOARD_UI.md) | Desktop status board UI |
| [DESKTOP_PIPELINE_ARCHITECTURE.md](DESKTOP_PIPELINE_ARCHITECTURE.md) | Desktop pipeline architecture |
| [DESKTOP_SEMANTIC_CLOSURE.md](DESKTOP_SEMANTIC_CLOSURE.md) | Desktop semantic closure |
| [DESKTOP_CONTROL_SURFACE.md](DESKTOP_CONTROL_SURFACE.md) | Desktop control surface |
| [DESKTOP_CONSUMPTION_ADAPTER.md](DESKTOP_CONSUMPTION_ADAPTER.md) | Desktop consumption adapter |
| [DESKTOP_DISPLAY_BOUNDARIES.md](DESKTOP_DISPLAY_BOUNDARIES.md) | Desktop display boundaries |
| [ONEAPI_SYSTEM_POSITION.md](ONEAPI_SYSTEM_POSITION.md) | OneAPI system position |
| [MODEL_ROUTING_AUTHORITY.md](MODEL_ROUTING_AUTHORITY.md) | Model routing authority |
| [MODEL_SUPPLY_TOPOLOGY.md](MODEL_SUPPLY_TOPOLOGY.md) | Model supply topology |
| [MODEL_TOPOLOGY_BRIDGE.md](MODEL_TOPOLOGY_BRIDGE.md) | Model topology bridge |
| [SKY_GROWN_CONSTELLATION_TOPOLOGY.md](SKY_GROWN_CONSTELLATION_TOPOLOGY.md) | Sky-grown constellation topology |

---

## ACTIVE — Agent and System Architecture

| Document | Purpose |
|----------|---------|
| [AGENTIC_OS_ARCHITECTURE.md](AGENTIC_OS_ARCHITECTURE.md) | Distributed agentic OS — global domain topology |
| [AGENT_RESPONSIBILITY_AND_DISPATCH_GOVERNANCE.md](AGENT_RESPONSIBILITY_AND_DISPATCH_GOVERNANCE.md) | Agent responsibility & dispatch governance |
| [AI_AGENT_SYSTEM_DESIGN.md](AI_AGENT_SYSTEM_DESIGN.md) | Galaxy AI agent system design |
| [AI_OS_ARCHITECTURE_DESIGN.md](AI_OS_ARCHITECTURE_DESIGN.md) | AI Native OS architecture design review |
| [UNIFIED_STARTUP.md](UNIFIED_STARTUP.md) | Unified startup flow |
| [MANIFEST_STAGE.md](MANIFEST_STAGE.md) | Manifest stage |
| [NODE_ACTIVE_MANIFEST.md](NODE_ACTIVE_MANIFEST.md) | Node active manifest |
| [NODE_SYSTEM_AUDIT.md](NODE_SYSTEM_AUDIT.md) | Node system audit |
| [V2_UNIFIED_STATE_CONTRACT.md](V2_UNIFIED_STATE_CONTRACT.md) | V2 unified state contract |
| [DURABLE_RUNTIME_SESSION_SNAPSHOT.md](DURABLE_RUNTIME_SESSION_SNAPSHOT.md) | Durable runtime session snapshot |
| [DATA_FLOW.md](DATA_FLOW.md) | Data flow documentation |
| [MULTIMODAL_INGRESS.md](MULTIMODAL_INGRESS.md) | Multimodal ingress |

---

## ACTIVE — Android and Protocol

| Document | Purpose |
|----------|---------|
| [ANDROID_COMPAT.md](ANDROID_COMPAT.md) | Android compatibility layer |
| [ANDROID_EVALUATOR_ARTIFACT_GOVERNANCE_INTEGRATION.md](ANDROID_EVALUATOR_ARTIFACT_GOVERNANCE_INTEGRATION.md) | Android evaluator artifact governance integration |
| [ANDROID_TRUTH_RECONCILIATION_REVIEWER_GUIDE.md](ANDROID_TRUTH_RECONCILIATION_REVIEWER_GUIDE.md) | Android participant truth reconciliation reviewer guide |
| [ANDROID_V2_JOINT_CONTINUITY_CONTRACT.md](ANDROID_V2_JOINT_CONTINUITY_CONTRACT.md) | Android-V2 joint continuity contract |
| [V2_ANDROID_RUNTIME_CLOSURE_AUDIT.md](V2_ANDROID_RUNTIME_CLOSURE_AUDIT.md) | V2 Android runtime closure audit |
| [MULTI_DEVICE_CONTROL_INTEGRITY_RESIDUAL_MAP.md](MULTI_DEVICE_CONTROL_INTEGRITY_RESIDUAL_MAP.md) | Multi-device control integrity residual map |
| [MULTI_DEVICE_E2E_ACCEPTANCE_MATRIX.md](MULTI_DEVICE_E2E_ACCEPTANCE_MATRIX.md) | Multi-device E2E acceptance matrix |
| [DEVICE_FORMATION_AND_MULTI_DEVICE_GROUPS.md](DEVICE_FORMATION_AND_MULTI_DEVICE_GROUPS.md) | Device formation and multi-device groups |

---

## ACTIVE — Liminal, Graph, and Advanced

| Document | Purpose |
|----------|---------|
| [LIMINAL_PROJECTION_ENGINE.md](LIMINAL_PROJECTION_ENGINE.md) | Liminal projection engine |
| [LIMINAL_SPACE_MAPPING.md](LIMINAL_SPACE_MAPPING.md) | Liminal space mapping |
| [GRAPH_RUNTIME_CONVERGENCE.md](GRAPH_RUNTIME_CONVERGENCE.md) | Graph runtime convergence |
| [CAPABILITY_NETWORK_RUNTIME_CONVERGENCE.md](CAPABILITY_NETWORK_RUNTIME_CONVERGENCE.md) | Capability + network runtime convergence |
| [CAPABILITY_RUNTIME_STATE.md](CAPABILITY_RUNTIME_STATE.md) | Capability runtime state |

---

## ACTIVE — `architecture/` — Canonical Architecture Documents

| Document | Purpose |
|----------|---------|
| [architecture/SOURCE_OF_TRUTH.md](architecture/SOURCE_OF_TRUTH.md) | Architecture source of truth |
| [architecture/CANONICAL_CONCEPT_MODEL_V1.md](architecture/CANONICAL_CONCEPT_MODEL_V1.md) | Canonical concept model v1 |
| [architecture/CANONICAL_ENTRYPOINTS.md](architecture/CANONICAL_ENTRYPOINTS.md) | Canonical entrypoints |
| [architecture/CANONICAL_SESSION_AXIS_V1.md](architecture/CANONICAL_SESSION_AXIS_V1.md) | Canonical session axis v1 |
| [architecture/ANDROID_RUNTIME_PROFILE_ALIGNMENT_CONSTITUTION_V1.md](architecture/ANDROID_RUNTIME_PROFILE_ALIGNMENT_CONSTITUTION_V1.md) | Android runtime profile alignment constitution v1 |
| [architecture/ARCHITECTURE_FREEZE_IMPLEMENTATION_GUARDRAILS.md](architecture/ARCHITECTURE_FREEZE_IMPLEMENTATION_GUARDRAILS.md) | Architecture freeze implementation guardrails |
| [architecture/UNIFIED_CENTER_DISTRIBUTED_RUNTIME_ARCHITECTURE_FREEZE_V1.md](architecture/UNIFIED_CENTER_DISTRIBUTED_RUNTIME_ARCHITECTURE_FREEZE_V1.md) | Unified center-distributed runtime architecture freeze v1 |
| [architecture/UNIFIED_GOVERNED_SYSTEM_CONSTITUTION_V1.md](architecture/UNIFIED_GOVERNED_SYSTEM_CONSTITUTION_V1.md) | Unified governed system constitution v1 |
| [architecture/module_ownership_map.md](architecture/module_ownership_map.md) | Module ownership map |
| [architecture/unified_device_registration_runtime_participation_v1.md](architecture/unified_device_registration_runtime_participation_v1.md) | Unified device registration runtime participation v1 |
| [architecture/unified_system_contract.md](architecture/unified_system_contract.md) | Unified system contract |

---

## ACTIVE — `joint_system_review/` — Dual-Repo Joint Review Documents

| Document | Purpose |
|----------|---------|
| [joint_system_review/00_index.md](joint_system_review/00_index.md) | 双仓联合代码审查索引 |
| [joint_system_review/01_system_positioning.md](joint_system_review/01_system_positioning.md) | 系统定位 |
| [joint_system_review/02_responsibility_boundary.md](joint_system_review/02_responsibility_boundary.md) | 职责边界 |
| [joint_system_review/03_key_flows.md](joint_system_review/03_key_flows.md) | 关键流程 |
| [joint_system_review/04_cross_repo_contract.md](joint_system_review/04_cross_repo_contract.md) | 跨仓合约 |
| [joint_system_review/05_maturity_assessment.md](joint_system_review/05_maturity_assessment.md) | 成熟度评估 |
| [joint_system_review/DEEP_JOINT_REVIEW_2026.md](joint_system_review/DEEP_JOINT_REVIEW_2026.md) | 双仓联合深度系统审查 2026 |
| [joint_system_review/CURRENT_STATE_BACKBONE_MAP_DUAL_REPO_ZH_2026-05.md](joint_system_review/CURRENT_STATE_BACKBONE_MAP_DUAL_REPO_ZH_2026-05.md) | 当前状态主骨架澄清 |
| [joint_system_review/NEXT_STAGE_DUAL_REPO_FOLLOW_THROUGH_CONVERGENCE_2026-05.md](joint_system_review/NEXT_STAGE_DUAL_REPO_FOLLOW_THROUGH_CONVERGENCE_2026-05.md) | 下一阶段双仓收口基线 |
| [joint_system_review/PRE_IMPLEMENTATION_DUAL_REPO_EXECUTION_BASELINE_2026-05.md](joint_system_review/PRE_IMPLEMENTATION_DUAL_REPO_EXECUTION_BASELINE_2026-05.md) | 实施前双仓执行基线 |
| [joint_system_review/V2_DUAL_REPO_INTEGRITY_LINKAGE_BASELINE_2026-05.md](joint_system_review/V2_DUAL_REPO_INTEGRITY_LINKAGE_BASELINE_2026-05.md) | V2 双仓完整性链接基线 |
| [joint_system_review/ANDROID_LOCAL_TO_DISTRIBUTED_PARTICIPATION_AUDIT_2026-05.md](joint_system_review/ANDROID_LOCAL_TO_DISTRIBUTED_PARTICIPATION_AUDIT_2026-05.md) | Android 本地到分布式参与审计 |
| [joint_system_review/DUAL_REPO_CLOSURE_GOVERNANCE_OPERABILITY_AUDIT_2026-05.md](joint_system_review/DUAL_REPO_CLOSURE_GOVERNANCE_OPERABILITY_AUDIT_2026-05.md) | 双仓闭包治理可操作性审计 |
| [joint_system_review/DUAL_REPO_TWO_LAYER_INCOMPLETE_REVIEW_2026-05.md](joint_system_review/DUAL_REPO_TWO_LAYER_INCOMPLETE_REVIEW_2026-05.md) | 双仓两层不完整审查 |
| [joint_system_review/FINAL_COGNITIVE_REVIEW_PR993_DUAL_REPO_ZH.md](joint_system_review/FINAL_COGNITIVE_REVIEW_PR993_DUAL_REPO_ZH.md) | PR993 最终认知审查 |
| [joint_system_review/FINAL_ENHANCED_COGNITIVE_REVIEW_DUAL_REPO_REALCODE_ZH.md](joint_system_review/FINAL_ENHANCED_COGNITIVE_REVIEW_DUAL_REPO_REALCODE_ZH.md) | 最终增强认知审查 (真实代码) |
| [joint_system_review/FINAL_SYSTEM_CHAIN_RESPONSIBILITY_REVIEW_ZH.md](joint_system_review/FINAL_SYSTEM_CHAIN_RESPONSIBILITY_REVIEW_ZH.md) | 最终系统链责任审查 |
| [joint_system_review/MASTER_CHAIN_AND_RESPONSIBILITY_PANORAMA_ZH.md](joint_system_review/MASTER_CHAIN_AND_RESPONSIBILITY_PANORAMA_ZH.md) | 主链与责任全景 |

---

## ACTIVE — `ugcp/` — Unified Governance and Control Protocol

| Document | Purpose |
|----------|---------|
| [ugcp/README.md](ugcp/README.md) | UGCP 文档集索引 |
| [ugcp/UGCP_CONSTITUTION_V1.md](ugcp/UGCP_CONSTITUTION_V1.md) | UGCP 宪法 v1 — 规则与权限链语言 |
| [ugcp/UGCP_CANONICAL_AUTHORITY_CHAIN_V1.md](ugcp/UGCP_CANONICAL_AUTHORITY_CHAIN_V1.md) | UGCP 权威权限链 v1 |
| [ugcp/UGCP_CANONICAL_VOCABULARY_V1.md](ugcp/UGCP_CANONICAL_VOCABULARY_V1.md) | UGCP 权威词汇表 v1 |
| [ugcp/UGCP_PHASE_GRAPH_V1.md](ugcp/UGCP_PHASE_GRAPH_V1.md) | UGCP 阶段图 v1 |
| [ugcp/UGCP_CONTROL_TRANSFER_PROFILE_V1.md](ugcp/UGCP_CONTROL_TRANSFER_PROFILE_V1.md) | UGCP 控制转移 Profile v1 |
| [ugcp/UGCP_COORDINATION_PROFILE_V1.md](ugcp/UGCP_COORDINATION_PROFILE_V1.md) | UGCP 协调 Profile v1 |
| [ugcp/UGCP_TRUTH_EVENT_MODEL_V1.md](ugcp/UGCP_TRUTH_EVENT_MODEL_V1.md) | UGCP Truth/事件模型 v1 |
| [ugcp/UGCP_CONFORMANCE_SURFACES_V1.md](ugcp/UGCP_CONFORMANCE_SURFACES_V1.md) | UGCP 合规面 v1 |
| [ugcp/UGCP_PROTOCOL_CONSISTENCY_RULES_V1.md](ugcp/UGCP_PROTOCOL_CONSULTANCY_RULES_V1.md) | UGCP 协议一致性规则 v1 |
| [ugcp/UGCP_SESSION_AXIS_V1.md](ugcp/UGCP_SESSION_AXIS_V1.md) | UGCP 会话轴 v1 |
| [ugcp/UGCP_SHARED_SCHEMA_MAPPINGS_V1.md](ugcp/UGCP_SHARED_SCHEMA_MAPPINGS_V1.md) | UGCP 共享 Schema 映射 v1 |
| [ugcp/UGCP_DEVICE_NODE_DOMAIN_GOVERNANCE_V1.md](ugcp/UGCP_DEVICE_NODE_DOMAIN_GOVERNANCE_V1.md) | UGCP 设备节点域治理 v1 |
| [ugcp/UGCP_ANDROID_ALIGNMENT_NOTES_V1.md](ugcp/UGCP_ANDROID_ALIGNMENT_NOTES_V1.md) | UGCP Android 对齐注记 v1 |
| [ugcp/CROSS_REPO_HOMOMORPHIC_MAPPING_V1.md](ugcp/CROSS_REPO_HOMOMORPHIC_MAPPING_V1.md) | 跨仓同态映射 v1 |

---

## ACTIVE — `reports/` — Report Archive

| Document | Purpose |
|----------|---------|
| [reports/README.md](reports/README.md) | 报告目录索引 |
| [reports/INDEX.md](reports/INDEX.md) | 报告归档索引 |
| [reports/ARCHITECTURE_REVIEW.md](reports/ARCHITECTURE_REVIEW.md) | 架构审查报告 (historical snapshot) |
| [reports/EVAL_FIXES.md](reports/EVAL_FIXES.md) | 评估修复摘要 |
| [reports/FULL_SYSTEM_AUDIT.md](reports/FULL_SYSTEM_AUDIT.md) | 完整系统审计 (historical snapshot) |
| [reports/IMPLEMENTATION_SUMMARY.md](reports/IMPLEMENTATION_SUMMARY.md) | 实现摘要 |
| [reports/L4_SYSTEM_STATUS_REPORT.md](reports/L4_SYSTEM_STATUS_REPORT.md) | L4 系统状态报告 |
| [reports/R4_IMPLEMENTATION_SUMMARY.md](reports/R4_IMPLEMENTATION_SUMMARY.md) | R4 实现摘要 |
| [reports/SECURITY_FIXES.md](reports/SECURITY_FIXES.md) | 安全修复报告 |
| [reports/SQL_FIXES.md](reports/SQL_FIXES.md) | SQL 修复报告 |
| [reports/SYSTEM_DESIGN_INTEGRATION_SUMMARY.md](reports/SYSTEM_DESIGN_INTEGRATION_SUMMARY.md) | 系统设计集成摘要 |
| [reports/SYSTEM_INTEGRITY_REPORT.md](reports/SYSTEM_INTEGRITY_REPORT.md) | 系统完整性报告 |
| [reports/UI_ASSETS.md](reports/UI_ASSETS.md) | UI 资产报告 |
| [reports/UI_L4_INTEGRATION_REPORT.md](reports/UI_L4_INTEGRATION_REPORT.md) | UI L4 集成报告 |
| [reports/README_UI_L4_INTEGRATION.md](reports/README_UI_L4_INTEGRATION.md) | UI L4 集成 README |

---

## SUPERSEDED — Replaced by Newer Documents

| Document | Superseded By | Status |
|----------|--------------|--------|
| [REAUDIT_FRESH_PASS_2.md](REAUDIT_FRESH_PASS_2.md) | [DUAL_REPO_FULL_REAUDIT.md](DUAL_REPO_FULL_REAUDIT.md) | SUPERSEDED |
| [REAUDIT_GAP_MATRIX_V2.md](REAUDIT_GAP_MATRIX_V2.md) | [DUAL_REPO_GAP_MATRIX.md](DUAL_REPO_GAP_MATRIX.md) | SUPERSEDED |
| [DUAL_REPO_UNRESOLVED_AUDIT.md](DUAL_REPO_UNRESOLVED_AUDIT.md) | [DUAL_REPO_GAP_MATRIX.md](DUAL_REPO_GAP_MATRIX.md) | SUPERSEDED |
| [REAUDIT_MULTI_DEVICE_MATURITY_V2.md](REAUDIT_MULTI_DEVICE_MATURITY_V2.md) | [MULTI_DEVICE_RUNTIME_MATURITY.md](MULTI_DEVICE_RUNTIME_MATURITY.md) | SUPERSEDED |
| [REAUDIT_ANDROID_PROTOCOL_V2.md](REAUDIT_ANDROID_PROTOCOL_V2.md) | [ANDROID_PROTOCOL_MATURITY_MATRIX.md](ANDROID_PROTOCOL_MATURITY_MATRIX.md) | SUPERSEDED |
| [REAUDIT_SCHEDULING_AUTHORITY_V2.md](REAUDIT_SCHEDULING_AUTHORITY_V2.md) | [UNIFIED_SCHEDULING_AUTHORITY_MAP.md](UNIFIED_SCHEDULING_AUTHORITY_MAP.md) | SUPERSEDED |
| [REAUDIT_FOLLOWUP_ROADMAP_V2.md](REAUDIT_FOLLOWUP_ROADMAP_V2.md) | [FOLLOWUP_IMPLEMENTATION_ROADMAP.md](FOLLOWUP_IMPLEMENTATION_ROADMAP.md) | SUPERSEDED |

---

## HISTORICAL — PR Implementation Reports (Historical Context)

These documents record changes made in specific PRs. They are preserved for
historical reference but are **not maintained** going forward.

| Document | Context |
|----------|---------|
| [GALAXY_COMPLETE_FIX_REPORT.md](GALAXY_COMPLETE_FIX_REPORT.md) | Galaxy system completeness fix report (2026-02-05) |
| [GALAXY_CORE_LOGIC_FIX_REPORT.md](GALAXY_CORE_LOGIC_FIX_REPORT.md) | Galaxy core logic layer fix report |
| [HARDWARE_TRIGGER_FIX_REPORT.md](HARDWARE_TRIGGER_FIX_REPORT.md) | Hardware trigger system fix report |
| [IMPLEMENTATION_REPORT.md](IMPLEMENTATION_REPORT.md) | Galaxy node system fix report |

---

## HISTORICAL — Early System Documents

These documents represent earlier stages of the system and are preserved for
reference. Current practice should consult ACTIVE documents above.

| Document | Context |
|----------|---------|
| [API_CONFIG_REPORT.md](API_CONFIG_REPORT.md) | Early API configuration report |
| [COMMUNICATION_LAYER.md](COMMUNICATION_LAYER.md) | Communication layer (early version) |
| [COMM_PROTOCOL_V2.md](COMM_PROTOCOL_V2.md) | Communication protocol V2 (M2 unified event schema) |
| [GUARDRAILS.md](GUARDRAILS.md) | Guardrails specification |
| [HICLAW_IMPROVEMENTS.md](HICLAW_IMPROVEMENTS.md) | HiClaw improvements |
| [KEY_ROTATION.md](KEY_ROTATION.md) | Key rotation documentation |
| [MEMORY_FRESHNESS.md](MEMORY_FRESHNESS.md) | Memory freshness |
| [NODE_SYSTEM_AUDIT.md](NODE_SYSTEM_AUDIT.md) | Node system audit |
| [GEMINI_RENDERING_PROTOCOL.md](GEMINI_RENDERING_PROTOCOL.md) | Gemini rendering protocol |
| [GITHUB_ADDONS.md](GITHUB_ADDONS.md) | GitHub addons |
| [system/DUAL_REPO_FULL_SYSTEM_BASELINE_V3.md](system/DUAL_REPO_FULL_SYSTEM_BASELINE_V3.md) | Dual-repo full system baseline V3 (historical) |
| [acceptance/u1_u33_final_acceptance.md](acceptance/u1_u33_final_acceptance.md) | U1–U33 final acceptance |
| [MATURITY_PROGRESS_REVIEW_2024.md](MATURITY_PROGRESS_REVIEW_2024.md) | 2024 maturity progress review |
| [JOINT_CODE_INVESTIGATION_REVIEW.md](JOINT_CODE_INVESTIGATION_REVIEW.md) | Joint code investigation review |
| [JOINT_CODE_REVIEW_DUAL_REPO_2026Q2.md](JOINT_CODE_REVIEW_DUAL_REPO_2026Q2.md) | Joint code review dual-repo 2026Q2 |
| [JOINT_DUAL_REPO_COGNITION_CLOSURE_BASELINE_ZH.md](JOINT_DUAL_REPO_COGNITION_CLOSURE_BASELINE_ZH.md) | Joint dual-repo cognition closure baseline |
| [JOINT_SYSTEM_REVIEW_V2_ANDROID_2026Q2.md](JOINT_SYSTEM_REVIEW_V2_ANDROID_2026Q2.md) | Joint system review V2 Android 2026Q2 |
| [review/COGNITION_AND_JOINT_REVIEW_UNIFIED_DISTRIBUTED_SYSTEM.md](review/COGNITION_AND_JOINT_REVIEW_UNIFIED_DISTRIBUTED_SYSTEM.md) | Cognition and joint review unified distributed system |
| [MCP_ADDON_CONTRACT.md](MCP_ADDON_CONTRACT.md) | MCP addon contract |
| [CONTINUUM_OBSERVABILITY.md](CONTINUUM_OBSERVABILITY.md) | Continuum observability |
| [LOCAL_RUNTIME_HOST_CONTRACT.md](LOCAL_RUNTIME_HOST_CONTRACT.md) | Local runtime host contract |
| [FORMAL_SYSTEM_BOUNDARY_OUTPUT_V1.md](FORMAL_SYSTEM_BOUNDARY_OUTPUT_V1.md) | Formal system boundary output v1 |
| [FULL_SYSTEM_JOINT_REVIEW.md](FULL_SYSTEM_JOINT_REVIEW.md) | Full system joint review |
| [CENTER_DISTRIBUTED_AGENT_SYSTEM_REVIEW.md](CENTER_DISTRIBUTED_AGENT_SYSTEM_REVIEW.md) | Center-governed distributed agent system review |
| [windows_mcp_server.md](windows_mcp_server.md) | Windows MCP server |
| [command_protocol.md](command_protocol.md) | Command routing protocol (legacy entry) |
| [ENTRYPOINT_AND_SURFACE_DEMOTION.md](ENTRYPOINT_AND_SURFACE_DEMOTION.md) | Entrypoint and surface demotion |
| [DISTRIBUTED_SUBJECT_CONTRACT_V1.md](DISTRIBUTED_SUBJECT_CONTRACT_V1.md) | Distributed subject contract v1 |
| [DISTRIBUTED_RELEASE_GATE_SKELETON.md](DISTRIBUTED_RELEASE_GATE_SKELETON.md) | Distributed release gate skeleton |
| [DIAGNOSTICS_INSPECTION_INTERACTION.md](DIAGNOSTICS_INSPECTION_INTERACTION.md) | Diagnostics inspection interaction |
| [V2_READINESS_GOVERNANCE_EVIDENCE_MATRIX.md](V2_READINESS_GOVERNANCE_EVIDENCE_MATRIX.md) | V2 readiness governance evidence matrix |

---

## HISTORICAL — Migration Documents

| Document | Context |
|----------|---------|
| [migration/README.md](migration/README.md) | Migration directory index (historical) |

---

## DEPRECATED

| Document | Reason | Redirect To |
|----------|--------|-------------|
| [pulls/README.md](pulls/README.md) | PR documentation index no longer maintained; use git log instead | N/A |

---

## Statistics

| Status | Count |
|--------|-------|
| **ACTIVE** | 216 |
| **HISTORICAL** | 55 |
| **SUPERSEDED** | 7 |
| **DEPRECATED** | 1 |
| **Total** | **272** |

---

*To add a new document: place it in the appropriate directory and update this index.*
*Mark any document you supersede by updating its status in this index.*
