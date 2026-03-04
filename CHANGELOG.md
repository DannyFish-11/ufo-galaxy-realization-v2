# Changelog

All notable changes to UFO Galaxy are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### In Progress
- PR #4 – (open) Additional capability registry enhancements
- PR #5 – (open) Connection manager improvements

---

## [3.0.0] – 2026-03-04

### Added – PR #11: Three autonomy loops end-to-end
- `AutoFixer._code_fix()` now runs a real sandbox test before/after patching and
  commits the change to disk (`[SANDBOX_TEST]` / `[COMMIT]` lifecycle).
- Loop 2 (learning → planner weights) wired end-to-end.
- Loop 3 (capability gap → `autonomous_coder._deploy_as_node`) wired end-to-end.

### Fixed – PR #8 / #9: psutil optional-import
- Made `psutil` import optional in `nodes/node_112_self_healing/main.py` so the
  three-loops CI passes on environments without the native extension.

### Added – PR #6: Autonomous loop tests
- `tests/test_autonomous_loops.py` validates Loop 1 (self-heal → code fix),
  Loop 2 (learning), and Loop 3 (auto-expand) in isolation via pytest.

### Added – PR #3: Three L4 autonomous feedback loops
- **Loop 1** – Self-healing code fix via `node_112_self_healing`.
- **Loop 2** – Learning strategy propagation to `autonomous_planner`.
- **Loop 3** – Capability gap → auto-registration via `autonomous_coder`.

### Added – PR #2: Android bridge + AIP v3.0 protocol alignment
- `galaxy_gateway/android_bridge.py` aligned with `AIPMessageV3.kt`.
- `ufo-galaxy-android` established as the sole Android client source.
- Full `device_register` / `heartbeat` / `task_result` handshake implemented.

### Added – PR #1: Initial node implementations + deployment setup
- Initial multi-node architecture under `nodes/`.
- Capability registry scaffolding in `core/capability_manager.py`.
- Connection manager base in `galaxy_gateway/`.
- Deployment guide and Docker Compose files.

---

[Unreleased]: https://github.com/DannyFish-11/ufo-galaxy-realization-v2/compare/main...HEAD
[3.0.0]: https://github.com/DannyFish-11/ufo-galaxy-realization-v2/releases/tag/v3.0.0
