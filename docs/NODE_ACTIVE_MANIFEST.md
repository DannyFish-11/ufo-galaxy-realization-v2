# Galaxy Node Active Manifest

> **PR-6 — Node Registry Normalization & Startup Policy State Machine**
> **PR-7 — Node System Unification** (prior PR; PR-6 builds on its audit results)

This document records the **authoritative active-node set** and **startup policy
state machine** after PR-6 registry normalization.  It is the human-readable
companion to the machine-readable `node_dependencies.json` registry and the
`docs/node_audit_report.json` audit output.

---

## Startup Policy Semantics

`node_dependencies.json` carries an explicit `startup_policy` field on **every**
node entry (normalized in PR-6 — all 130 entries now carry an explicit value;
implicit defaults are no longer accepted as a governance practice).

The launcher (`launcher/node_startup.py`) respects this field to decide what to start.

| Policy | Meaning | Launcher behaviour |
|--------|---------|--------------------|
| `active` | Healthy, orchestrated, no issues | Started unconditionally |
| `optional` | Runnable, valid role, but config-drift node needing further verification | Started if available; failure does not abort system |
| `skip` | Archived, deleted, or unfinished stub | **Never started** — registry entry kept for audit tracking only |

### Startup Policy State Machine

States and legal transitions:

```
         ┌─────────────────────────────────────┐
         │  optional → active                  │
         │  (integration test + health check   │
         │   passes; maintainer promotes)      │
         ▼                                     │
    ┌─────────┐   active → optional        ┌──────────┐
    │ active  │ ─────────────────────────► │ optional │
    └─────────┘   (known issue / drift;    └──────────┘
         │         soft-fail tolerated)         │
         │                                      │
         │  active → skip                       │  optional → skip
         │  (node retired / archived /          │  (repair abandoned;
         │   identified as stub)                │   node archived)
         ▼                                      ▼
                        ┌──────┐
                        │ skip │
                        └──────┘
```

| Transition | Trigger | Required action |
|------------|---------|-----------------|
| `optional` → `active` | Node passes integration test and health check | Update `startup_policy` in `node_dependencies.json`; update manifest counts |
| `active` → `optional` | Node develops a known issue or config drift | Demote to allow soft-fail startup; open a tracking issue |
| `active` → `skip` | Node retired, archived, or confirmed stub | Update `startup_policy`; document reason in registry `description` |
| `optional` → `skip` | Repair attempt abandoned | Update `startup_policy`; document reason in registry `description` |

> **Note**: `skip` is a terminal/holding state.  A `skip` node must not be started by any launcher path.  To resurrect a skipped node, open a dedicated PR with a full implementation review.

---

## Active Node Counts (post PR-6 normalization)

> **PR-6 change**: All 95 previously-implicit `active` nodes now carry an
> explicit `"startup_policy": "active"` field.  The registry is fully
> normalized: every entry has an explicit startup policy.

| Category | Count |
|----------|-------|
| Total nodes in registry | 130 |
| `startup_policy = active` (keep nodes) | 95 |
| `startup_policy = optional` (repair nodes, now registered) | 29 |
| `startup_policy = skip` (archived / deleted / stubs) | 6 |

---

## Nodes Added to Registry by PR-7 (Repair — Config Drift Resolved)

These 30 nodes existed on disk but were absent from `node_dependencies.json`.
PR-7 adds them with `startup_policy: "optional"` so they participate in
orchestration without blocking system startup.  They should be promoted to
`"active"` once each has been individually verified.

| Node | Port | Group | Lines | Notes |
|------|------|-------|-------|-------|
| `Node_60_ReinforcementLearning` | 8060 | academic | 319 | Config drift resolved |
| `Node_63_FuzzyLogicEngine` | 8063 | academic | 399 | Config drift resolved |
| `Node_70_AutonomousLearning` | 8070 | academic | 503 | Config drift resolved |
| `Node_71_MultiDeviceCoordination` | 8071 | extended | 846 | Config drift resolved |
| `Node_75_DataPipeline` | 8075 | extended | 345 | Config drift resolved |
| `Node_76_AlertManager` | 8076 | extended | 335 | Config drift resolved |
| `Node_77_TaskScheduler` | 8077 | extended | 374 | Config drift resolved |
| `Node_78_DataValidator` | 8078 | extended | 303 | Config drift resolved |
| `Node_86_SpeechProcessor` | 8086 | extended | 635 | Config drift resolved |
| `Node_87_ImageAnalysis` | 8087 | extended | 597 | Config drift resolved |
| `Node_88_WorkflowEngine` | 8088 | extended | 597 | Config drift resolved |
| `Node_89_APIGateway` | 8089 | extended | 520 | Config drift resolved |
| `Node_93_VideoProcessor` | 8093 | extended | 485 | Config drift resolved |
| `Node_94_AudioAnalysis` | 8094 | extended | 450 | Config drift resolved |
| `Node_98_MultimodalFusion` | 8098 | extended | 318 | Config drift resolved |
| `Node_99_EmbeddingService` | 8099 | extended | 317 | Config drift resolved |
| `Node_107_FunctionCalling` | 8107 | development | 462 | Config drift resolved |
| `Node_108_MetaCognition` | 8108 | academic | 601 | Config drift resolved |
| `Node_109_ProactiveSensing` | 8109 | academic | 532 | Config drift resolved |
| `Node_114_DocumentIntelligence` | 8114 | development | 321 | Config drift resolved |
| `Node_115_PluginManager` | 8115 | development | 322 | Config drift resolved |
| `Node_116_ExternalToolWrapper` | 8116 | development | 498 | Config drift resolved |
| `Node_117_OpenCode` | 8117 | development | 472 | Config drift resolved |
| `Node_118_NodeFactory` | 8118 | development | 613 | Config drift resolved |
| `Node_119_BenchmarkEval` | 8119 | development | 430 | Config drift resolved |
| `Node_120_File` | 8120 | development | 748 | Config drift resolved |
| `Node_121_Web` | 8121 | development | 561 | Config drift resolved |
| `Node_122_Shell` | 8122 | development | 552 | Config drift resolved |
| `Node_124_LinuxDesktopAuto` | 8124 | extended | 456 | Config drift resolved |
| `Node_130_AutonomousCoding` | 8130 | development | 90 | Stub — `startup_policy: skip`, `audit_action: archive` until implementation is complete |

> **Note on `Node_130_AutonomousCoding`:** This node has only 90 lines in `main.py`
> and is classified as a stub by the audit.  It is registered for tracking but
> excluded from startup with `startup_policy: "skip"`.

---

## Nodes Demoted from Active Startup Path

### Archived (non-trivial placeholder, preserved for reference)

| Node | Port | Reason |
|------|------|--------|
| `Node_28_Reserved` | 8028 | Reserved placeholder slot — 252 lines but no active role |
| `Node_29_Reserved` | 8029 | Reserved placeholder slot — 262 lines but no active role |

### Deleted (minimal stub, no unique value)

| Node | Port | Reason |
|------|------|--------|
| `Node_30_Reserved` | 8030 | Reserved placeholder — 123 lines, no unique value |
| `Node_31_Reserved` | 8031 | Reserved placeholder — 123 lines, no unique value |
| `Node_32_Reserved` | 8032 | Reserved placeholder — 123 lines, no unique value |

All five Reserved nodes remain in `node_dependencies.json` with
`startup_policy: "skip"` so the registry is complete and auditable.

---

## Duplicate Role Nodes

The audit identified three duplicate-role clusters.  Resolution is deferred
to a later PR focused on deduplication; for now both nodes in each pair
remain active.

| Role | Nodes |
|------|-------|
| MemorySystem | `Node_80_MemorySystem`, `Node_100_MemorySystem` |
| MediaGen | `Node_125_MediaGen`, `Node_128_MediaGen` |
| Reserved | `Node_28–32_Reserved` (all demoted) |

---

## Nodes Requiring Further Action (Next Steps)

1. **Promote repair nodes** — Once each `startup_policy: "optional"` node has
   been integration-tested, update its entry to `startup_policy: "active"`.
2. **Resolve MemorySystem duplicate** — Decide canonical node between
   `Node_80_MemorySystem` and `Node_100_MemorySystem`.
3. **Resolve MediaGen duplicate** — Decide canonical node between
   `Node_125_MediaGen` and `Node_128_MediaGen`.
4. **Complete `Node_130_AutonomousCoding`** — Extend stub to a meaningful
   implementation before promoting to `optional` or `active`.
5. **Add `Node_26_Discord` Dockerfile** — Required for containerised deployment.

---

*Last updated: PR-6 — Node Registry Normalization & Startup Policy State Machine*
