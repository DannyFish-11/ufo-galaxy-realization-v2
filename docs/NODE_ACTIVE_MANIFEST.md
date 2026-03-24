# Galaxy Node Active Manifest

> **PR-6 — Node Registry Normalization & Startup Policy State Machine**
> **PR-7 — Node System Unification** (prior PR; PR-6 builds on its audit results)
> **PR-8 — Optional-Node Governance & Promotion Workflow** (this PR)

This document records the **authoritative active-node set**, **startup policy
state machine**, and **optional-node governance model** after PR-8.  It is the
human-readable companion to the machine-readable `node_dependencies.json`
registry and the `docs/node_audit_report.json` audit output.

---

## Startup Policy Semantics

`node_dependencies.json` carries an explicit `startup_policy` field on **every**
node entry (normalized in PR-6 — all 130 entries now carry an explicit value;
implicit defaults are no longer accepted as a governance practice).

The launcher (`launcher/node_startup.py`) respects this field to decide what to start.

| Policy | Meaning | Launcher behaviour |
|--------|---------|--------------------|
| `active` | Healthy, orchestrated, no issues | Started unconditionally |
| `optional` | Deliberate governance state — valid role, individually tracked path to active | Started if available; failure does not abort system |
| `skip` | Archived, deleted, or unfinished stub | **Never started** — registry entry kept for audit tracking only |

### Startup Policy State Machine

States and legal transitions:

```
         ┌─────────────────────────────────────┐
         │  optional → active                  │
         │  (promotion checklist complete;      │
         │   governance review passed)          │
         ▼                                     │
    ┌─────────┐   active → optional        ┌──────────┐
    │ active  │ ─────────────────────────► │ optional │
    └─────────┘   (known issue / drift;    └──────────┘
         │         soft-fail tolerated)         │
         │                                      │
         │  active → skip                       │  optional → skip
         │  (node retired / archived /          │  (repair attempt abandoned;
         │   identified as stub)                │   node archived)
         ▼                                      ▼
                        ┌──────┐
                        │ skip │
                        └──────┘
```

| Transition | Trigger | Required action |
|------------|---------|-----------------|
| `optional` → `active` | Promotion checklist complete; governance review passed | Update `startup_policy` in `node_dependencies.json`; update manifest counts |
| `active` → `optional` | Node develops a known issue or config drift | Demote to allow soft-fail startup; open a tracking issue |
| `active` → `skip` | Node retired, archived, or confirmed stub | Update `startup_policy`; document reason in registry `description` |
| `optional` → `skip` | Repair attempt abandoned | Update `startup_policy`; document reason in registry `description` |

> **Note**: `skip` is a terminal/holding state.  A `skip` node must not be started by any launcher path.  To resurrect a skipped node, open a dedicated PR with a full implementation review.

---

## Optional-Node Governance (PR-8)

`optional` is a **deliberate, governable state**, not an undefined bucket.
Every optional node must:

1. Appear in `node_dependencies.json` with `startup_policy: "optional"` explicitly set.
2. Meet the optional-node minimum baseline (see below).
3. Have a tracked path toward `active` (or a documented decision to remain optional / be archived).

Maintainers can inspect the health of the optional-node set by running:

```bash
python scripts/node_audit.py --print-summary
# Then open docs/NODE_SYSTEM_AUDIT.md §Optional-Node Governance for the full table
```

### Optional-Node Minimum Baseline

The following checks must pass for a node to be considered a **well-governed optional node**.
Failing any of these is a governance gap requiring remediation.

| Check | Requirement |
|-------|-------------|
| `registry_present` | Entry in `node_dependencies.json` with `startup_policy: "optional"` |
| `has_main_py` | `main.py` exists in node directory |
| `has_fusion_entry` | `fusion_entry.py` exists in node directory |
| `syntax_ok` | `main.py` and `fusion_entry.py` pass `py_compile` |
| `has_readme` | `README.md` exists (describability — maintainers must be able to understand the node) |
| `hygiene_clean` | No runtime-artifact files (`.pid`, `.log`, `.tmp`, `.lock`, `__pycache__`, etc.) in node root |

> The optional baseline is deliberately weaker than `active`.  Packaging
> (Dockerfile / requirements.txt) and runtime-contract endpoints (/health, /status)
> are **not** required for optional — they are tracked as **promotion-gap** checks
> (see §Promotion Checklist below).

### Promotion-Gap Checks (delta to `active`)

These checks are surfaced per optional node in the audit report and track what
must be addressed before the node is eligible for promotion:

| Check | Requirement |
|-------|-------------|
| `has_dockerfile` | `Dockerfile` present in node directory |
| `has_requirements` | `requirements.txt` present |
| `has_health_endpoint` | `/health` endpoint declared in `main.py` (static inspection) |
| `has_status_endpoint` | `/status` endpoint declared in `main.py` (static inspection) |

### PR-8 Optional-Node Baseline Status

After PR-8 remediation all 29 optional nodes pass the optional baseline.

| Category | Count |
|----------|-------|
| Optional nodes (total) | 29 |
| Baseline: **pass** | 29 |
| Baseline: **partial** | 0 |
| Baseline: **fail** | 0 |
| Promotion gap: **ready** (all active-grade checks pass) | 29 |

> **All 29 optional nodes are promotion-ready** per the technical gap checks.
> Actual promotion still requires the governance review steps in §Promotion Checklist.

---

## Active Node Counts (post PR-8)

> **PR-8 change**: 6 optional nodes that were missing `README.md` now have one,
> bringing all 29 optional nodes to the optional baseline.

| Category | Count |
|----------|-------|
| Total nodes in registry | 130 |
| `startup_policy = active` (keep nodes) | 95 |
| `startup_policy = optional` (governed optional-node set) | 29 |
| `startup_policy = skip` (archived / deleted / stubs) | 6 |

---

## Promotion Checklist: `optional` → `active`

Use this checklist when promoting a node.  All items must be checked before
changing `startup_policy` from `"optional"` to `"active"`.

### 1. Technical checks (must pass audit engine)

- [ ] `main.py` exists and passes `py_compile`
- [ ] `fusion_entry.py` exists and passes `py_compile`
- [ ] `README.md` exists and describes port, endpoints, env vars, and dependencies
- [ ] `Dockerfile` present and builds successfully
- [ ] `requirements.txt` present and pinned/validated
- [ ] `/health` endpoint declared and returns `{"status": "healthy"}` when live
- [ ] `/status` endpoint declared and returns operational state when live
- [ ] No hygiene violations in node root
- [ ] Node is registered in `node_dependencies.json` with explicit `startup_policy`
- [ ] No port conflicts with other registered nodes

### 2. Runtime validation

- [ ] Node starts cleanly under `launcher/node_startup.py`
- [ ] `/health` probe returns HTTP 200 within the health-check timeout
- [ ] `/status` probe returns HTTP 200 with a meaningful state payload
- [ ] Node does not abort system startup on failure (launcher soft-fail confirmed)

### 3. Governance review

- [ ] Node role is documented in `README.md` and understood by a maintainer
- [ ] Node description in `node_dependencies.json` is accurate
- [ ] No known open issues blocking promotion
- [ ] `docs/NODE_ACTIVE_MANIFEST.md` counts updated

### 4. Commit actions

1. Change `startup_policy` from `"optional"` to `"active"` in `node_dependencies.json`.
2. Update node description / audit metadata fields if needed.
3. Update counts table in `docs/NODE_ACTIVE_MANIFEST.md`.
4. Run `python scripts/node_audit.py` to regenerate `docs/node_audit_report.json`
   and `docs/NODE_SYSTEM_AUDIT.md`.
5. Run `python scripts/validate_runtime.py` — all checks must pass.
6. Open a PR with health-check evidence in the description.

---

## Optional Nodes — Full Set (post PR-8)

All 29 optional nodes pass the optional baseline and are tracked for promotion.

| Node | Port | Group | Baseline | Promo Gap |
|------|------|-------|----------|-----------|
| `Node_60_ReinforcementLearning` | 8060 | academic | pass | ready |
| `Node_63_FuzzyLogicEngine` | 8063 | academic | pass | ready |
| `Node_70_AutonomousLearning` | 8070 | academic | pass | ready |
| `Node_71_MultiDeviceCoordination` | 8071 | extended | pass | ready |
| `Node_75_DataPipeline` | 8075 | extended | pass | ready |
| `Node_76_AlertManager` | 8076 | extended | pass | ready |
| `Node_77_TaskScheduler` | 8077 | extended | pass | ready |
| `Node_78_DataValidator` | 8078 | extended | pass | ready |
| `Node_86_SpeechProcessor` | 8086 | extended | pass | ready |
| `Node_87_ImageAnalysis` | 8087 | extended | pass | ready |
| `Node_88_WorkflowEngine` | 8088 | extended | pass | ready |
| `Node_89_APIGateway` | 8089 | extended | pass | ready |
| `Node_93_VideoProcessor` | 8093 | extended | pass | ready |
| `Node_94_AudioAnalysis` | 8094 | extended | pass | ready |
| `Node_98_MultimodalFusion` | 8098 | extended | pass | ready |
| `Node_99_EmbeddingService` | 8099 | extended | pass | ready |
| `Node_107_FunctionCalling` | 8107 | development | pass | ready |
| `Node_108_MetaCognition` | 8108 | academic | pass | ready |
| `Node_109_ProactiveSensing` | 8109 | academic | pass | ready |
| `Node_114_DocumentIntelligence` | 8114 | development | pass | ready |
| `Node_115_PluginManager` | 8115 | development | pass | ready |
| `Node_116_ExternalToolWrapper` | 8116 | development | pass | ready |
| `Node_117_OpenCode` | 8117 | development | pass | ready |
| `Node_118_NodeFactory` | 8118 | development | pass | ready |
| `Node_119_BenchmarkEval` | 8119 | development | pass | ready |
| `Node_120_File` | 8120 | development | pass | ready |
| `Node_121_Web` | 8121 | development | pass | ready |
| `Node_122_Shell` | 8122 | development | pass | ready |
| `Node_124_LinuxDesktopAuto` | 8124 | extended | pass | ready |

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

1. **Promote optional nodes** — Use the PR-8 promotion checklist above to promote
   each `startup_policy: "optional"` node individually.  All 29 currently pass
   the technical promotion-gap checks; promotion requires per-node runtime
   validation and governance review.
2. **Resolve MemorySystem duplicate** — Decide canonical node between
   `Node_80_MemorySystem` and `Node_100_MemorySystem`.
3. **Resolve MediaGen duplicate** — Decide canonical node between
   `Node_125_MediaGen` and `Node_128_MediaGen`.
4. **Complete `Node_130_AutonomousCoding`** — Extend stub to a meaningful
   implementation before promoting to `optional` or `active`.
5. **Add `Node_26_Discord` Dockerfile** — Required for containerised deployment.

---

*Last updated: PR-8 — Optional-Node Governance & Promotion Workflow*
