# Contributing to UFO Galaxy

Thank you for contributing!

## Adding a New Node

1. Create a directory under `nodes/` following the naming convention `Node_XX_Name/`.
2. Each node directory must contain at minimum:
   - `main.py` – entry point with the node's core logic
   - `fusion_entry.py` – integration shim used by the fusion layer
3. Register the node in `node_dependencies.json` if it has dependencies on other nodes.

## Running Tests

```bash
python -m pytest tests/ -v
```

> **Note:** `pytest` and `pytest-asyncio` live in `requirements-dev.txt`.
> Install them before running tests:
>
> ```bash
> pip install -r requirements-dev.txt
> ```

### Verifying the Three Autonomous Loops

```bash
python -m pytest tests/test_autonomous_loops.py -v
```

### Verifying Capability Registration

```bash
python scripts/verify_capability_registry.py
```

## Branch & PR Conventions

- Work on a feature branch: `feature/<short-description>` or `fix/<short-description>`
- Keep commits small and focused; write meaningful commit messages
- Open a pull request targeting `main`
- All CI checks must pass before merging

## Android Client

The Android client code belongs **exclusively** in the
[DannyFish-11/ufo-galaxy-android](https://github.com/DannyFish-11/ufo-galaxy-android)
repository.  Do **not** add Kotlin, Gradle, or Android-specific build files to
this repository.  The server-side AIP v3.0 bridge lives in
`galaxy_gateway/android_bridge.py`.
