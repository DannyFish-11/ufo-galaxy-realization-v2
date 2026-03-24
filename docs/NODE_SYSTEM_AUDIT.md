# Galaxy Node-System Audit Report

> Generated: 2026-03-24T15:11:26Z
> Authority: `scripts/node_audit.py` — canonical repository governance engine (PR-2)

## Summary Counts

| Metric | Count |
|--------|-------|
| Total nodes audited | **130** |
| Runnable nodes (has main.py + ≥100 lines) | 129 |
| Orchestrated nodes (in node_dependencies.json) | 129 |
| Stub nodes (main.py < 100 lines) | 1 |

## Recommended Actions

| Action | Count | Meaning |
|--------|-------|---------|
| **keep** | 124 | Healthy, orchestrated, no issues |
| **repair** | 1 | Valuable role; fix config/impl before use |
| **archive** | 2 | Non-trivial but not orchestrated; preserve |
| **delete** | 3 | Placeholder/stub/duplicate with no unique value |

## Failure Summary by Category

| Category | Failing | Warning |
|----------|---------|---------|
| Source completeness (main.py / fusion_entry.py / README.md) | 0 | 1 |
| Syntax safety (py_compile check) | 0 | 0 |
| Packaging (Dockerfile / requirements.txt) | 0 | 0 |
| Registry governance (node_dependencies.json + policy) | 0 | 0 |
| Runtime contract (health / status endpoint) | 0 | 0 |
| Hygiene (no runtime artifacts) | 0 | 0 |

## Config Drift

### Nodes in `node_dependencies.json` but NOT on disk
_None — config and disk are in sync for this direction._

### Nodes on disk but NOT in `node_dependencies.json`
_None._

### Nodes missing `main.py`
_None — all nominal nodes have a main.py._

### Reserved (placeholder) nodes
- `Node_28_Reserved`
- `Node_29_Reserved`
- `Node_30_Reserved`
- `Node_31_Reserved`
- `Node_32_Reserved`

### Duplicate role nodes
- MediaGen: Node_125_MediaGen, Node_128_MediaGen
- MemorySystem: Node_100_MemorySystem, Node_80_MemorySystem
- Reserved: Node_28_Reserved, Node_29_Reserved, Node_30_Reserved, Node_31_Reserved, Node_32_Reserved

### Numbering gaps
Missing node numbers: [129]

## Port Conflicts
_No port conflicts detected across registry entries._

## Nodes with Hygiene Violations
_No hygiene violations detected._

## Nodes with Missing Required Artifacts

Nodes missing one or more of: `main.py`, `fusion_entry.py`, `README.md`

| Node | main.py | fusion_entry.py | README.md |
|------|---------|-----------------|-----------|
| `Node_130_AutonomousCoding` | ✓ | ✓ | ✗ |

## Nodes with Syntax Errors
_No syntax errors detected._

## Packaging Coverage

> **Canonical source of truth:** `scripts/node_audit.py` — `tools/check_node_packaging.sh` is a thin companion that defers to this report.

### Nodes Missing `Dockerfile`

_All nodes have a `Dockerfile`._

### Nodes Missing `requirements.txt`

_All nodes have a `requirements.txt`._

### Packaging Summary by Policy Class

| Policy Class | Total | Full Coverage | Missing Dockerfile | Missing requirements.txt |
|-------------|-------|--------------|-------------------|--------------------------|
| `active` | 95 | 95 | 0 | 0 |
| `optional` | 29 | 29 | 0 | 0 |
| `skip` | 6 | 6 | 0 | 0 |

## Optional-Node Governance (PR-8)

> **Optional nodes** are a deliberate governance state: registered in
> `node_dependencies.json` with `startup_policy: optional`, started if
> available (startup failure does not abort the system), and on a tracked
> path to promotion to `active`.

### Optional-Node Counts

| Category | Count |
|----------|-------|
| Total optional nodes | **29** |
| Baseline: **pass** (all optional-baseline checks green) | 29 |
| Baseline: **partial** (some checks warn) | 0 |
| Baseline: **fail** (one or more checks failing) | 0 |
| Promotion gap: **ready** (all active-grade checks pass) | 29 |
| Promotion gap: **near_ready** (≤1 gap to active) | 0 |
| Promotion gap: **not_ready** (≥2 gaps to active) | 0 |

### Optional-Baseline Minimum Requirements

An optional node must satisfy the following to be considered well-governed:

| Check | Requirement |
|-------|-------------|
| `registry_present` | Entry in `node_dependencies.json` with `startup_policy: optional` |
| `has_main_py` | `main.py` exists |
| `has_fusion_entry` | `fusion_entry.py` exists |
| `syntax_ok` | `main.py` / `fusion_entry.py` pass `py_compile` |
| `has_readme` | `README.md` exists (describability requirement) |
| `hygiene_clean` | No runtime-artifact violations in node root |

### Optional-Node Baseline Status

| Node | Baseline | Promotion | reg | main | fusion | syn | readme | hyg | docker | req | health | status |
|------|----------|-----------|-----|------|--------|-----|--------|-----|--------|-----|--------|--------|
| `Node_107_FunctionCalling` | **pass** | ready | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_108_MetaCognition` | **pass** | ready | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_109_ProactiveSensing` | **pass** | ready | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_114_DocumentIntelligence` | **pass** | ready | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_115_PluginManager` | **pass** | ready | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_116_ExternalToolWrapper` | **pass** | ready | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_117_OpenCode` | **pass** | ready | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_118_NodeFactory` | **pass** | ready | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_119_BenchmarkEval` | **pass** | ready | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_120_File` | **pass** | ready | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_121_Web` | **pass** | ready | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_122_Shell` | **pass** | ready | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_124_LinuxDesktopAuto` | **pass** | ready | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_60_ReinforcementLearning` | **pass** | ready | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_63_FuzzyLogicEngine` | **pass** | ready | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_70_AutonomousLearning` | **pass** | ready | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_71_MultiDeviceCoordination` | **pass** | ready | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_75_DataPipeline` | **pass** | ready | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_76_AlertManager` | **pass** | ready | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_77_TaskScheduler` | **pass** | ready | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_78_DataValidator` | **pass** | ready | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_86_SpeechProcessor` | **pass** | ready | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_87_ImageAnalysis` | **pass** | ready | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_88_WorkflowEngine` | **pass** | ready | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_89_APIGateway` | **pass** | ready | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_93_VideoProcessor` | **pass** | ready | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_94_AudioAnalysis` | **pass** | ready | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_98_MultimodalFusion` | **pass** | ready | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_99_EmbeddingService` | **pass** | ready | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

**Baseline column key:** ✓=pass · ✗=fail · ~=warn · ?=unknown

**Promotion columns** (docker, req, health, status) show gaps that must be
closed before a node is eligible for `optional → active` promotion.

### Promotion-Ready Optional Nodes

These nodes meet all active-grade promotion-gap checks and may be candidates
for `optional → active` promotion after governance review:

- `Node_107_FunctionCalling`
- `Node_108_MetaCognition`
- `Node_109_ProactiveSensing`
- `Node_114_DocumentIntelligence`
- `Node_115_PluginManager`
- `Node_116_ExternalToolWrapper`
- `Node_117_OpenCode`
- `Node_118_NodeFactory`
- `Node_119_BenchmarkEval`
- `Node_120_File`
- `Node_121_Web`
- `Node_122_Shell`
- `Node_124_LinuxDesktopAuto`
- `Node_60_ReinforcementLearning`
- `Node_63_FuzzyLogicEngine`
- `Node_70_AutonomousLearning`
- `Node_71_MultiDeviceCoordination`
- `Node_75_DataPipeline`
- `Node_76_AlertManager`
- `Node_77_TaskScheduler`
- `Node_78_DataValidator`
- `Node_86_SpeechProcessor`
- `Node_87_ImageAnalysis`
- `Node_88_WorkflowEngine`
- `Node_89_APIGateway`
- `Node_93_VideoProcessor`
- `Node_94_AudioAnalysis`
- `Node_98_MultimodalFusion`
- `Node_99_EmbeddingService`

### Optional Nodes with Baseline Gaps

These nodes have at least one failing optional-baseline check and need
remediation before they can be considered well-governed optional nodes:

_All optional nodes meet the optional baseline._

## Node Inventory

| Node | Lines | Group | Port | Policy | Tier | Action | src | syn | pkg | reg | rt | hyg |
|------|-------|-------|------|--------|------|--------|-----|-----|-----|-----|----|-----|
| `Node_00_StateMachine` | 390 | core | 8000 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_01_OneAPI` | 721 | core | 7995 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_02_Tasker` | 316 | core | 8002 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_03_SecretVault` | 324 | core | 8003 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_04_Router` | 480 | core | 8004 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_05_Auth` | 370 | core | 8005 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_06_Filesystem` | 354 | core | 8006 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_07_Git` | 334 | core | 8007 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_08_Fetch` | 199 | core | 8008 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_09_Sandbox` | 388 | core | 7996 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_100_MemorySystem` | 690 | academic | 8100 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_101_CodeEngine` | 612 | academic | 8101 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_102_DebugOptimize` | 608 | academic | 8102 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_103_KnowledgeGraph` | 650 | academic | 8103 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_104_AgentCPM` | 804 | academic | 8104 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_105_UnifiedKnowledgeBase` | 546 | academic | 8105 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_106_GitHubFlow` | 491 | academic | 8106 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_107_FunctionCalling` | 462 | development | 8107 | optional | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_108_MetaCognition` | 601 | academic | 8108 | optional | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_109_ProactiveSensing` | 532 | academic | 8109 | optional | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_10_Slack` | 232 | development | 8010 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_110_SmartOrchestrator` | 664 | core | 7997 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_111_ContextManager` | 593 | core | 7998 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_112_SelfHealing` | 994 | core | 7999 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_113_AndroidVLM` | 278 | enhancement | 8113 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_114_DocumentIntelligence` | 321 | development | 8114 | optional | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_115_PluginManager` | 322 | development | 8115 | optional | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_116_ExternalToolWrapper` | 498 | development | 8116 | optional | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_117_OpenCode` | 472 | development | 8117 | optional | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_118_NodeFactory` | 613 | development | 8118 | optional | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_119_BenchmarkEval` | 430 | development | 8119 | optional | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_11_GitHub` | 303 | development | 8011 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_120_File` | 748 | development | 8120 | optional | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_121_Web` | 561 | development | 8121 | optional | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_122_Shell` | 552 | development | 8122 | optional | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_123_Calendar` | 223 | development | 8123 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_124_LinuxDesktopAuto` | 456 | extended | 8124 | optional | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_125_MediaGen` | 409 | extended | 8125 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_126_AgentSwarm` | 981 | extended | 8126 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_127_BambuLab` | 172 | extended | 8127 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_128_MediaGen` | 316 | extended | 8128 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_12_Postgres` | 253 | development | 8012 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_130_AutonomousCoding` | 90 | development | 8130 | skip | stub | **repair** | ~ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_13_SQLite` | 230 | development | 8013 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_14_FFmpeg` | 253 | development | 8014 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_15_OCR` | 293 | development | 8015 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_16_Email` | 205 | development | 8016 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_17_EdgeTTS` | 149 | development | 8017 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_18_DeepL` | 232 | development | 8018 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_19_Crypto` | 291 | development | 8019 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_20_Qdrant` | 275 | development | 8020 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_21_Notion` | 343 | development | 8021 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_22_BraveSearch` | 170 | development | 8022 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_23_Time` | 225 | development | 9000 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_24_Weather` | 260 | development | 8024 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_25_GoogleSearch` | 299 | development | 8025 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_26_Discord` | 249 | tools | 8023 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_27_SmartHome` | 303 | tools | 8027 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_28_Reserved` | 252 | development | 8028 | skip | orchestrated | **archive** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_29_Reserved` | 262 | development | 8029 | skip | orchestrated | **archive** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_30_Reserved` | 123 | development | 8030 | skip | orchestrated | **delete** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_31_Reserved` | 123 | extended | 8031 | skip | orchestrated | **delete** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_32_Reserved` | 123 | extended | 8032 | skip | orchestrated | **delete** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_33_ADB` | 499 | extended | 8033 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_34_Scrcpy` | 290 | extended | 8034 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_35_AppleScript` | 130 | extended | 8035 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_36_UIAWindows` | 370 | extended | 8036 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_37_LinuxDBus` | 134 | extended | 8037 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_38_BLE` | 198 | extended | 8038 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_39_SSH` | 186 | extended | 8039 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_40_SFTP` | 195 | extended | 8040 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_41_MQTT` | 236 | extended | 8041 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_42_CANbus` | 164 | extended | 8042 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_43_MAVLink` | 141 | extended | 8043 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_44_NFC` | 158 | extended | 8044 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_45_DesktopAuto` | 198 | extended | 8045 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_46_Camera` | 183 | extended | 8046 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_47_Audio` | 224 | extended | 8047 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_48_Serial` | 190 | extended | 9001 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_49_OctoPrint` | 434 | extended | 8049 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_50_Transformer` | 294 | extended | 8050 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_51_QuantumDispatcher` | 644 | extended | 8051 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_52_QiskitSimulator` | 595 | extended | 8052 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_53_GraphLogic` | 348 | extended | 8053 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_54_SymbolicMath` | 759 | extended | 8054 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_55_MultiModal` | 188 | extended | 8055 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_56_Planning` | 182 | extended | 9002 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_57_QuantumCloud` | 185 | extended | 8057 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_58_ModelRouter` | 1057 | extended | 8058 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_59_CausalInference` | 149 | extended | 8059 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_60_ReinforcementLearning` | 319 | academic | 8060 | optional | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_61_GeometricReasoning` | 166 | extended | 8061 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_62_ProbabilisticProgramming` | 135 | extended | 8062 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_63_FuzzyLogicEngine` | 399 | academic | 8063 | optional | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_64_Telemetry` | 823 | extended | 8064 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_65_LoggerCentral` | 633 | extended | 8065 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_66_ConfigManager` | 386 | extended | 8066 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_67_HealthMonitor` | 654 | extended | 8067 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_68_Security` | 428 | extended | 8068 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_69_BackupRestore` | 759 | extended | 8069 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_70_AutonomousLearning` | 503 | academic | 8070 | optional | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_71_MultiDeviceCoordination` | 846 | extended | 8071 | optional | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_72_KnowledgeBase` | 414 | extended | 8072 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_73_Learning` | 389 | extended | 8073 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_74_DigitalTwin` | 403 | extended | 8074 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_75_DataPipeline` | 345 | extended | 8075 | optional | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_76_AlertManager` | 335 | extended | 8076 | optional | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_77_TaskScheduler` | 374 | extended | 8077 | optional | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_78_DataValidator` | 303 | extended | 8078 | optional | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_79_LocalLLM` | 798 | extended | 8079 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_80_MemorySystem` | 948 | extended | 8080 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_81_Orchestrator` | 689 | academic | 8081 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_82_NetworkGuard` | 445 | academic | 8082 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_83_NewsAggregator` | 468 | academic | 8083 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_84_StockTracker` | 482 | academic | 8084 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_85_PromptLibrary` | 604 | academic | 8085 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_86_SpeechProcessor` | 635 | extended | 8086 | optional | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_87_ImageAnalysis` | 597 | extended | 8087 | optional | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_88_WorkflowEngine` | 597 | extended | 8088 | optional | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_89_APIGateway` | 520 | extended | 8089 | optional | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_90_MultimodalVision` | 590 | academic | 8090 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_91_MultimodalAgent` | 419 | academic | 8091 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_92_AutoControl` | 307 | academic | 8092 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_93_VideoProcessor` | 485 | extended | 8093 | optional | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_94_AudioAnalysis` | 450 | extended | 8094 | optional | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_95_WebRTC_Receiver` | 470 | academic | 8095 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_96_SmartTransportRouter` | 412 | academic | 8096 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_97_AcademicSearch` | 592 | academic | 8097 | active | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_98_MultimodalFusion` | 318 | extended | 8098 | optional | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Node_99_EmbeddingService` | 317 | extended | 8099 | optional | orchestrated | **keep** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

**Column key:** src=source_completeness · syn=syntax_safety · pkg=packaging · reg=registry_governance · rt=runtime_contract · hyg=hygiene
**Icon key:** ✓=pass · ~=warn · ✗=fail · ?=unknown

---
*This report is generated by `scripts/node_audit.py` (canonical governance engine). Re-run after node changes to refresh.*