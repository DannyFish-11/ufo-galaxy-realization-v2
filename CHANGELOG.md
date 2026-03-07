# Changelog

All notable changes to Galaxy are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

Open pull requests pending review / merge:

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
