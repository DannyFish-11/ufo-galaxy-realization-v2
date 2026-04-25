"""core/mesh/staged_mesh_role_contract.py
==========================================
PR-2: Staged Mesh Role Contract — Explicit Declaration of staged_mesh
Main-Chain Role and Connection to LiveMeshRuntimeEngine.

Background
----------
The Galaxy V2 runtime supports a ``staged_mesh`` dispatch mode where a task is
distributed across multiple registered participants via a
:class:`~contracts.mesh_session_coordinator.MeshSessionCoordinatorState` and
executed via :func:`~core.mesh.live_mesh_runtime_engine.run_live_mesh_session`.

Prior to PR-J (live mesh runtime engine integration), the ``staged_mesh`` mode
existed in the dispatch plan but was only executed up to the "plan prepared"
stage, i.e. the coordinator state was assembled but no live execution occurred.
This created a structural gap where ``staged_mesh`` was described as a main-
chain capability but did not actually drive real multi-device execution.

PR-J closed that gap by integrating :func:`run_live_mesh_session` into
:mod:`core.runtime.source_dispatch_orchestrator`.  The ``staged_mesh`` path
in :func:`~core.runtime.source_dispatch_orchestrator.orchestrate_source_runtime_dispatch`
now:

1. Calls :func:`~core.mesh.mesh_session_coordinator.coordinate_mesh_session`
   to assemble a coordinator state.
2. Calls :func:`~core.mesh.live_mesh_runtime_engine.run_live_mesh_session`
   to promote the coordinator from ``pending`` to ``active`` and drive the
   session to a live convergent result.
3. Returns a :class:`~contracts.source_dispatch.SourceDispatchResult` with
   ``action_taken='staged_mesh_coordinated'`` and the live run outcome.

This module provides the **explicit, machine-checkable declaration** of this
role for PR-2 so that:

1. CI conformance tests can assert that the staged mesh path is connected to
   the live runtime engine.
2. Operators can determine at a glance whether staged mesh is a live or simulated
   path.
3. If in future the live execution path is changed, this contract must be
   explicitly updated — preventing silent regression to a "plan prepared only"
   path.

Mesh role classification
------------------------
Per this contract, staged mesh holds the role
``STAGED_MESH_MAIN_CHAIN_ROLE = "main_chain_live_execution"``.

This means:

* ``staged_mesh`` is a **main-chain** dispatch mode (not experimental, not
  deferred, not simulated).
* It produces a **live** execution result (not a "plan prepared" stub).
* It relies on :func:`run_live_mesh_session` from
  :mod:`core.mesh.live_mesh_runtime_engine` for the live execution step.
* It relies on :func:`coordinate_mesh_session` from
  :mod:`core.mesh.mesh_session_coordinator` for coordinator state assembly.
* It is invoked by
  :func:`~core.runtime.source_dispatch_orchestrator.orchestrate_source_runtime_dispatch`
  when ``mode == SourceDispatchMode.staged_mesh``.

If the live execution path is ever decoupled from staged mesh, the role MUST
be updated to ``"deferred"`` or ``"simulated"`` and
:data:`STAGED_MESH_IS_CONNECTED_TO_LIVE_ENGINE` MUST be set to False.

Public API
----------
Sentinels
~~~~~~~~~
:data:`STAGED_MESH_ROLE_CONTRACT_AUTHORITY`
:data:`STAGED_MESH_ROLE_CONTRACT_PR2_SENTINEL`
:data:`STAGED_MESH_MAIN_CHAIN_ROLE`
:data:`STAGED_MESH_IS_CONNECTED_TO_LIVE_ENGINE`
:data:`STAGED_MESH_LIVE_ENGINE_MODULE`
:data:`STAGED_MESH_ORCHESTRATOR_MODULE`
:data:`STAGED_MESH_LIVE_CONNECTION_POLICY`
:data:`STAGED_MESH_ROLE_DOWNGRADE_POLICY`
:data:`STAGED_MESH_RESULT_SHAPE_POLICY`
:data:`STAGED_MESH_GRACEFUL_DEGRADATION_POLICY`

Functions
~~~~~~~~~
:func:`verify_staged_mesh_live_connection` → dict
:func:`get_staged_mesh_role` → str
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

STAGED_MESH_ROLE_CONTRACT_AUTHORITY: str = (
    "STAGED_MESH_ROLE_CONTRACT::"
    "EXPLICIT_DECLARATION_OF_STAGED_MESH_MAIN_CHAIN_ROLE_AND_LIVE_ENGINE_CONNECTION_V1"
)

STAGED_MESH_ROLE_CONTRACT_PR2_SENTINEL: str = (
    "SENTINEL::STAGED_MESH_ROLE_CONTRACT_PR2: "
    "core.mesh.staged_mesh_role_contract is the canonical declaration that "
    "staged_mesh dispatch is connected to LiveMeshRuntimeEngine and holds "
    "main_chain_live_execution role; "
    "package=PR-2::staged-mesh-role-contract::session-migration-mesh-closure"
)

# ---------------------------------------------------------------------------
# Role declaration
# ---------------------------------------------------------------------------

STAGED_MESH_MAIN_CHAIN_ROLE: str = "main_chain_live_execution"
"""Explicit role classification for staged_mesh dispatch mode.

Values:
  ``"main_chain_live_execution"``
      staged_mesh is a main-chain dispatch mode with true live execution
      via :func:`core.mesh.live_mesh_runtime_engine.run_live_mesh_session`.
  ``"deferred"``
      staged_mesh produces a "plan prepared" result only; live execution
      is not performed.  MUST NOT be used while PR-J integration is active.
  ``"simulated"``
      staged_mesh simulates execution without live participant coordination.
      For testing or dry-run contexts only.
"""

STAGED_MESH_IS_CONNECTED_TO_LIVE_ENGINE: bool = True
"""True when staged_mesh is connected to LiveMeshRuntimeEngine.

Set to False if/when staged_mesh is decoupled from the live engine.
"""

# ---------------------------------------------------------------------------
# Module path references
# ---------------------------------------------------------------------------

STAGED_MESH_LIVE_ENGINE_MODULE: str = "core.mesh.live_mesh_runtime_engine"
"""The module providing run_live_mesh_session() for live mesh execution."""

STAGED_MESH_ORCHESTRATOR_MODULE: str = "core.runtime.source_dispatch_orchestrator"
"""The module that invokes staged_mesh execution in the main dispatch chain."""

STAGED_MESH_COORDINATOR_MODULE: str = "core.mesh.mesh_session_coordinator"
"""The module providing coordinate_mesh_session() for coordinator state assembly."""

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

STAGED_MESH_LIVE_CONNECTION_POLICY: str = (
    "POLICY::STAGED_MESH_LIVE_CONNECTION_PR2: "
    "When staged_mesh dispatch is selected by the SourceDispatchOrchestrator, "
    "the orchestrator MUST invoke run_live_mesh_session() from "
    "core.mesh.live_mesh_runtime_engine after assembling the coordinator state "
    "via coordinate_mesh_session().  Returning a 'plan prepared' result without "
    "calling run_live_mesh_session() is a protocol violation and MUST be treated "
    "as a regression from the PR-J main-chain integration."
)

STAGED_MESH_ROLE_DOWNGRADE_POLICY: str = (
    "POLICY::STAGED_MESH_ROLE_DOWNGRADE_PR2: "
    "If the live execution path is decoupled from staged_mesh (e.g. because "
    "the live engine is not yet mature enough for production use), the "
    "staged_mesh role MUST be explicitly downgraded by: "
    "(1) setting STAGED_MESH_MAIN_CHAIN_ROLE to 'deferred'; "
    "(2) setting STAGED_MESH_IS_CONNECTED_TO_LIVE_ENGINE to False; "
    "(3) updating the result shape to carry action_taken='staged_mesh_plan_only'; "
    "(4) updating this sentinel to reflect the downgrade.  "
    "Silent maintenance of a 'main_chain_live_execution' declaration while the "
    "live engine is not called is a structural integrity violation."
)

STAGED_MESH_RESULT_SHAPE_POLICY: str = (
    "POLICY::STAGED_MESH_RESULT_SHAPE_PR2: "
    "The SourceDispatchResult produced by staged_mesh execution MUST carry: "
    "  action_taken='staged_mesh_coordinated' on success; "
    "  live_outcome from the LiveMeshRunResult; "
    "  live_merged_result containing the aggregated participant outputs; "
    "  decision_reason='staged_mesh:coordinated' on success or "
    "  'staged_mesh:coordinator_error' on failure.  "
    "Missing or empty live_outcome when STAGED_MESH_IS_CONNECTED_TO_LIVE_ENGINE "
    "is True indicates the live execution step was skipped."
)

STAGED_MESH_GRACEFUL_DEGRADATION_POLICY: str = (
    "POLICY::STAGED_MESH_GRACEFUL_DEGRADATION_PR2: "
    "When the MeshSessionCoordinator or LiveMeshRuntimeEngine raises an "
    "exception during staged_mesh execution, the orchestrator MUST: "
    "(1) catch the exception; "
    "(2) append a descriptive error to the result errors list; "
    "(3) set success=False in the result; "
    "(4) log a WARNING (not an ERROR) to avoid unnecessary alert fatigue; "
    "(5) NOT fall through to local execution — staged_mesh errors MUST surface "
    "as staged_mesh failures, not silent local fallback."
)

# ---------------------------------------------------------------------------
# Verification helper
# ---------------------------------------------------------------------------


def verify_staged_mesh_live_connection() -> Dict[str, Any]:
    """Verify that the live mesh runtime engine is importable and connectable.

    Returns a dict with keys:
    - ``live_engine_importable``: bool
    - ``coordinator_importable``: bool
    - ``orchestrator_importable``: bool
    - ``run_live_mesh_session_callable``: bool
    - ``coordinate_mesh_session_callable``: bool
    - ``role``: str (current STAGED_MESH_MAIN_CHAIN_ROLE value)
    - ``is_connected``: bool (current STAGED_MESH_IS_CONNECTED_TO_LIVE_ENGINE value)
    - ``errors``: list[str]
    """
    result: Dict[str, Any] = {
        "live_engine_importable": False,
        "coordinator_importable": False,
        "orchestrator_importable": False,
        "run_live_mesh_session_callable": False,
        "coordinate_mesh_session_callable": False,
        "role": STAGED_MESH_MAIN_CHAIN_ROLE,
        "is_connected": STAGED_MESH_IS_CONNECTED_TO_LIVE_ENGINE,
        "errors": [],
    }

    try:
        from core.mesh.live_mesh_runtime_engine import (  # noqa: F401
            LiveMeshRuntimeEngine,
            run_live_mesh_session,
        )
        result["live_engine_importable"] = True
        result["run_live_mesh_session_callable"] = callable(run_live_mesh_session)
    except Exception as exc:
        result["errors"].append(f"live_engine_import_error:{exc}")

    try:
        from core.mesh.mesh_session_coordinator import (  # noqa: F401
            coordinate_mesh_session,
        )
        result["coordinator_importable"] = True
        result["coordinate_mesh_session_callable"] = callable(coordinate_mesh_session)
    except Exception as exc:
        result["errors"].append(f"coordinator_import_error:{exc}")

    try:
        from core.runtime.source_dispatch_orchestrator import (  # noqa: F401
            orchestrate_source_runtime_dispatch,
        )
        result["orchestrator_importable"] = True
    except Exception as exc:
        result["errors"].append(f"orchestrator_import_error:{exc}")

    return result


def get_staged_mesh_role() -> str:
    """Return the current staged mesh role classification.

    Returns
    -------
    str
        The value of :data:`STAGED_MESH_MAIN_CHAIN_ROLE`.
    """
    return STAGED_MESH_MAIN_CHAIN_ROLE


# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    # Sentinels
    "STAGED_MESH_ROLE_CONTRACT_AUTHORITY",
    "STAGED_MESH_ROLE_CONTRACT_PR2_SENTINEL",
    "STAGED_MESH_MAIN_CHAIN_ROLE",
    "STAGED_MESH_IS_CONNECTED_TO_LIVE_ENGINE",
    "STAGED_MESH_LIVE_ENGINE_MODULE",
    "STAGED_MESH_ORCHESTRATOR_MODULE",
    "STAGED_MESH_COORDINATOR_MODULE",
    "STAGED_MESH_LIVE_CONNECTION_POLICY",
    "STAGED_MESH_ROLE_DOWNGRADE_POLICY",
    "STAGED_MESH_RESULT_SHAPE_POLICY",
    "STAGED_MESH_GRACEFUL_DEGRADATION_POLICY",
    # Functions
    "verify_staged_mesh_live_connection",
    "get_staged_mesh_role",
]
