# galaxy_gateway/legacy — Legacy Gateway Compatibility Layer

This directory contains legacy compatibility code for the galaxy gateway
that is retained for backward compatibility.

## Modules

| Module | Canonical Replacement |
|--------|----------------------|
| `task_decomposer.py` | `core.task_graph.TaskGraph` |
| `capability_registry.py` | `core.capability_runtime` |

These modules are NOT part of the canonical runtime path.
