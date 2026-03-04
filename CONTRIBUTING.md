# Contributing to UFO Galaxy

Thank you for your interest in contributing! This guide covers everything you need to get started.

---

## Development Environment

**Requirements:** Python 3.11 or higher.

```bash
# 1. Clone the repository
git clone https://github.com/DannyFish-11/ufo-galaxy-realization-v2.git
cd ufo-galaxy-realization-v2

# 2. (Recommended) Create a virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. Install all dependencies
pip install -r requirements.txt
```

---

## Running Tests

```bash
python -m pytest tests/ -v
```

To run a specific test file:

```bash
python -m pytest tests/test_autonomous_loops.py -v
```

---

## Adding a New Node

1. Create the node directory:

   ```
   nodes/Node_XX_YourName/
   ├── main.py           # Core logic and FastAPI app (if applicable)
   └── fusion_entry.py   # Entry point for the Fusion scheduler
   ```

2. Register the node's capability in `core/capability_manager.py` by adding an
   entry to the capability registry with the node's name, description, and
   supported actions.

3. Add tests under `tests/` to cover the new node's behaviour.

---

## Verifying the Three Autonomous Loops

The three L4 feedback loops can be validated independently:

```bash
python -m pytest tests/test_autonomous_loops.py -v
```

| Loop | Description |
|------|-------------|
| Loop 1 | Self-healing → code fix (`node_112_self_healing`) |
| Loop 2 | Learning → planner strategy weights (`autonomous_planner`) |
| Loop 3 | Capability gap → auto-expand (`autonomous_coder._deploy_as_node`) |

---

## Android Client

The Android client lives exclusively in the
[**DannyFish-11/ufo-galaxy-android**](https://github.com/DannyFish-11/ufo-galaxy-android)
repository. Protocol definitions (AIP v3.0) are shared via
`galaxy_gateway/android_bridge.py` on this side and `AIPMessageV3.kt` on the
Android side.

---

## Pull Request Guidelines

- Target the **`main`** branch.
- Use a descriptive title (e.g. `feat: add Node_115_Planner capability`).
- Include tests that cover the new or changed behaviour.
- Keep commits focused; one logical change per commit.
- The CI workflow (`.github/workflows/ci.yml`) must pass before merge.
