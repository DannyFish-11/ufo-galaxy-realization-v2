# Changelog

All notable changes to UFO Galaxy are documented here.

## [Unreleased]

### Added
- CI workflow (`.github/workflows/ci.yml`) – runs pytest on push/PR to `main`
- Cross-platform integration tests (`tests/test_cross_platform_integration.py`) covering AIP v3.0 protocol messages
- `CHANGELOG.md` and `CONTRIBUTING.md` documentation

### Removed
- Duplicate Android client source code under `enhancements/clients/android_client/` (Kotlin, Gradle, scripts, extra docs); canonical source lives at [DannyFish-11/ufo-galaxy-android](https://github.com/DannyFish-11/ufo-galaxy-android)

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
