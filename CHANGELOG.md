# Changelog

All notable changes to Galaxy are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

Open pull requests pending review / merge:

- **PR-S1** – Protocol Single Source of Truth (v3-only): `galaxy_gateway/protocol/aip_v3.py`
  is now the sole canonical protocol definition. Direct imports of `aip_protocol_v2` are
  blocked at import-time; all message types previously in `ExtendedMessageType` (Phases 1–5)
  are promoted into `MessageType` in v3. Legacy inputs are still accepted via
  `galaxy_gateway/protocol/compat.py` (normalised → v3 `AIPMessage`). A new CI job
  (`v3-protocol-guard`) and unit test (`tests/test_v3_protocol_guard.py`) enforce no
  residual v2 references in source code.

- **PR-S5** – Schema / 文档更新 (v3 JSON Schemas + documentation hardening):
  - Added `galaxy_gateway/protocol/schemas/` with JSON Schema (Draft 2020-12) files for all
    five primary AIP v3 message types: `device_register`, `heartbeat`, `capability_report`,
    `task_assign`, and `command_result`, plus a shared `aip_envelope` base schema.
  - `capability_report` schema enforces the three v3-required fields: `platform`,
    `supported_actions` (non-empty array), and `version` (pattern `^3\.`).
  - All schemas reject `version` values below `"3.0"` (pattern `^3\.`) so they describe
    the **post-compat** canonical v3 objects that handlers receive; legacy clients must pass
    through `galaxy_gateway/protocol/compat.parse_message_compat()` first.
  - `docs/ANDROID_PROTOCOL_ALIGNMENT.md` updated: new Section 10 "JSON Schema 参考与 v3
    Payload 示例" documents schema file index, v3 required fields table, full payload
    examples for all five types, the legacy→v3 auto-conversion flow diagram, and how to run
    the schema validation test suite.
  - Added `tests/test_v3_schemas.py`: 50 test cases covering schema load, embedded-example
    validation (positive), and rejection of missing required fields (negative).
  - Compat layer (`compat.py`) is unchanged; docs clarify it is the single entry point for
    legacy inputs and that business fields (`platform`, `supported_actions`) are **not**
    back-filled by compat.

- **PR #4** – Wire `/ws/android` to `android_bridge`: integrates the Android stack with the
  V2 backend, enabling end-to-end AIP v3.0 message flow between the Android client and the server.
- **PR #5** – Remove Android client duplication: canonical Android source moved to
  [DannyFish-11/galaxy-android](https://github.com/DannyFish-11/galaxy-android);
  Kotlin/Gradle files removed from this repository.

---

## [v2.0] – Milestone: Core Infrastructure + Autonomous Loops + Android Bridge

### Added – PR #1: Initial nodes and project structure
- Core node implementations: Tasker, Auth, SecretVault, Filesystem, databases, tools,
  search, and more
- Base `core/` framework with async task execution and LLM routing

### Added – PR #2: Capability registry and discovery
- `core/capability_manager.py` — OpenClaw-style central capability index
- Capability registration at node startup with status tracking (online / offline / error)
- Persistent storage in `config/capabilities.json`
- Discovery API: query by name, category, node ID, or keyword

### Added – PR #3: Connection manager with heartbeat and auto-reconnect
- `core/connection_manager.py` — stable connection manager (Sunflower-style)
- Automatic heartbeat with configurable interval and exponential back-off reconnect
- Real-time health monitoring and fault recovery

### Added – PR #6: Self-heal loop (Loop 1 — Self-Heal → Code-Fix → Verify)
- `Node_112_SelfHealing` — anomaly detection and automated diagnosis
- `AutoFixer._code_fix()` calls `AutonomousCoder.generate_and_execute()` for sandboxed repairs
- `FixAction.CODE_FIX` keyword-driven action routing; optional `psutil` import

### Added – PR #7: Learning loop (Loop 2 — Learn → Weight Update → Routing)
- `LearningOptimizer` — extracts performance insights from execution history
- `AutonomousPlanner.update_decision_weights()` adjusts routing strategy weights
- Feedback loop: learn → update weights → optimised routing on next invocation

### Added – PR #8: Auto-expand loop (Loop 3 — Capability Gap → Deploy New Node)
- `AutonomousCoder._deploy_as_node()` — generates new node code to fill detected gaps
- Auto-registers new nodes in `NodeFactory` and `CapabilityManager`
- Capability index updated immediately so new nodes are available for routing

### Added – PR #9: Android bridge and AIP v3.0 protocol alignment
- `galaxy_gateway/android_bridge.py` — full WebSocket bridge for Android ↔ Server
- AIP v3.0 message types: `device_register`, `heartbeat`, `task_result`,
  `capability_report`, `diagnostics_payload`, `vision_request`
- `MessageBuilder` factory methods for all server → device responses
  (`register_ack`, `heartbeat_ack`, `capability_report_ack`, `diagnostics_payload_ack`,
  `vision_result`, etc.)

### Added – PR #10: Dashboard (Vue 3 + FastAPI)
- `dashboard/` — real-time monitoring and management UI
- Node health, capability browser, and device list panels

### Added – PR #11: `Node_113_AndroidVLM` + vision integration
- Android screenshot → `VisionPipeline` analysis → `task_assign` reply
- `MessageBuilder.vision_result()` factory method for vision responses
