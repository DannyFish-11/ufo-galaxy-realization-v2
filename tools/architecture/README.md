# tools/architecture — Architecture Tooling and Diagnostics

This directory contains architecture-level tooling, diagnostics, and scenario harness
code. These modules are NOT part of the canonical runtime execution path.

## Modules

| Module | Description |
|--------|-------------|
| `architecture_completion.py` | Architecture completion tracking |
| `architecture_diagnostics.py` | Diagnostic tools and analysis |
| `architecture_invariants.py` | Invariant checks and validation |
| `architecture_live_status.py` | Live architecture status monitoring |
| `architecture_status_report.py` | Status reporting utilities |
| `architecture_truth_guards.py` | Architecture truth and authority guards |
| `scenario_harness.py` | Scenario-based testing and validation harness |

## Usage

These tools are primarily used by:
- Tests in `tests/` that validate architecture invariants
- Developer diagnostics and status checks
- CI/CD validation scripts in `scripts/`

## Backward Compatibility

All original `core/architecture_*.py` and `core/scenario_harness.py` paths remain
functional as compatibility shims that re-export from this package.
