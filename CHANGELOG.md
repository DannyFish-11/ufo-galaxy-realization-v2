# Changelog

All notable changes to UFO Galaxy are documented here.

## [Unreleased]

### Added
- CI workflow (`.github/workflows/ci.yml`) – runs pytest (including dev dependencies) on push/PR to `main`
- Cross-platform integration tests (`tests/test_cross_platform_integration.py`) covering AIP v3.0 protocol messages
- Cross-device integration tests (`tests/test_cross_device_integration.py`) – full Android ↔ Server handshake
- `CHANGELOG.md` and `CONTRIBUTING.md` documentation
- `vision_request` handler in `android_bridge.py`: Android screenshot → VisionPipeline analysis → `task_assign` reply (断链2/3)
- OneAPI dynamic model discovery in `multi_llm_router.py` via `config/api_config.json` + `/v1/models` (断链4)
- `capability_report` handler persists `supported_actions` into `AndroidDevice` (断链5)
- `MessageBuilder.capability_report_ack`, `MessageBuilder.diagnostics_payload_ack`, `MessageBuilder.vision_result` factory methods

### Removed
- Duplicate Android client source code under `enhancements/clients/android_client/` (Kotlin, Gradle, scripts, extra docs); canonical source lives at [DannyFish-11/ufo-galaxy-android](https://github.com/DannyFish-11/ufo-galaxy-android)

---

## [v2.1]

### Added – PR #5: Remove Android client duplication
- Removed Android client source (Kotlin, Gradle, scripts) from this repository to eliminate duplication.
- Redirected contributors to [DannyFish-11/ufo-galaxy-android](https://github.com/DannyFish-11/ufo-galaxy-android) as the sole canonical source for the Android client.

### Added – PR #4: Wire `/ws/android` to `android_bridge`
- Integrated the Android stack with the V2 backend by wiring the `/ws/android` WebSocket endpoint to `android_bridge`.
- Enables end-to-end AIP v3.0 message flow between the Android client and the server.

---

## [v2.0]

### Added
- Initial system with node implementations: Tasker, Auth, SecretVault, Filesystem, databases, tools, search, and more
- Capability registration & discovery system (OpenClaw style)
- Connection manager with heartbeat and auto-reconnect
- Three autonomous loops
  - **Loop 1** – Self-heal: detects and attempts automated code fixes (`node_112_self_healing`)
  - **Loop 2** – Learning: updates planner strategy from execution history (`galaxy_main_loop_l4` + `autonomous_planner`)
  - **Loop 3** – Auto-expand: detects capability gaps and deploys new nodes (`autonomous_coder._deploy_as_node`)
- Android bridge integration (AIP v3.0 protocol, `Node_113_AndroidVLM`)
- Dashboard – Vue 3 + FastAPI monitoring UI (`dashboard/`)
