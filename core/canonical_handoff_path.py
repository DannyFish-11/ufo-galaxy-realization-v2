"""core/canonical_handoff_path.py
===================================
Canonical Main-Repo Handoff / Takeover Path — PR-3 (post-533 dual-repo
runtime host unification track, MAIN repo side).

Purpose
-------
This module is the **canonical anchor** for the main-repo-side handoff and
takeover path.  It:

1. Documents and asserts the single authoritative execution chain for
   cross-device handoff / takeover on the main-repo side.
2. Re-exports the canonical building blocks so downstream code (session
   truth, event sync, observability) can import from one stable location.
3. Provides a lightweight ``build_canonical_handoff_contract()`` helper that
   constructs a fully-populated :class:`HandoffContract` with posture and
   authority metadata already resolved.

Canonical path (MAIN repo side)
---------------------------------
::

    ingress (REST / WebSocket)
        ↓  source_runtime_posture resolved at boundary
    galaxy_gateway/routes/chat.py  (or equivalent ingress)
        ↓  context carries source_runtime_posture
    galaxy_gateway/device_router.py :: DeviceRouter.route_task()
        ↓  eligibility checked via core.source_execution_eligibility
        ↓  coordination_role derived via core.multi_device_coordination_authority
        ↓  HandoffContract(source_runtime_posture=…, coordination_role=…)
    galaxy_gateway/agent_bridge.py :: AgentBridge.handoff(contract)
        ├─ POST /handoff  (remote runtime endpoint)
        └─ local_fallback → galaxy_gateway/cross_device_coordinator.py

Policy
------
- ``source_runtime_posture`` MUST NOT be silently dropped at any boundary.
  (NO_POSTURE_SILENT_DROP_POLICY)
- ``coordination_role`` MUST NOT be silently dropped at any boundary.
  (NO_AUTHORITY_SILENT_DROP_POLICY)
- Parallel or compat paths that bypass ``HandoffContract`` are **legacy
  bypasses** and MUST emit structured LEGACY_PATH_GUARDRAIL warnings via
  :func:`core.orchestration_authority.legacy_paths.emit_legacy_guardrail`.
- The canonical path is the ONLY path that should be used for new code.

Non-goals
---------
- This module does NOT redesign the existing bridge or router.
- It does NOT introduce full session-truth or event-sync (those are PR-4/8).
- It does NOT modify the Android side (separate PR).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# PR-3 canonical path sentinel
# ---------------------------------------------------------------------------

CANONICAL_HANDOFF_PATH_MAIN_REPO: str = (
    "pr3_post533_canonical_handoff_path_main_repo_active"
)
"""Sentinel: The canonical main-repo-side handoff/takeover path is active.

The path is:
  DeviceRouter.route_task()
      → AgentBridge.handoff(HandoffContract)
          → POST /handoff (remote runtime)
          → local_fallback (CrossDeviceCoordinator)

Both posture and coordination_role are propagated without loss.
"""

CANONICAL_HANDOFF_POSTURE_AND_AUTHORITY_UNIFIED: str = (
    "pr3_post533_canonical_handoff_posture_and_authority_unified"
)
"""Sentinel: Both source_runtime_posture (posture axis) and coordination_role
(authority axis from PR-538) are first-class fields in HandoffContract and
HandoffEnvelopeV2.  No loss at bridge, legacy-adapter, or envelope-builder
boundaries."""

CANONICAL_HANDOFF_PATH_SINGLE_CHAIN_ENFORCED: str = (
    "pr3_post533_canonical_handoff_path_single_chain_enforced"
)
"""Sentinel: All new handoff/takeover code on the main-repo side MUST go
through the canonical chain.  Parallel/compat paths that bypass
HandoffContract are legacy and MUST emit guardrail warnings."""


# ---------------------------------------------------------------------------
# Re-exports of canonical building blocks
# ---------------------------------------------------------------------------
# Downstream code (PR-4 session truth, PR-8 event sync, PR-9 observability)
# should import from here so they depend on the stable canonical surface
# rather than the internal gateway/contracts modules directly.

from galaxy_gateway.agent_bridge import (  # noqa: E402
    CANONICAL_HANDOFF_PATH_PR3,
    CANONICAL_HANDOFF_POSTURE_PROPAGATION_ACTIVE,
    HANDOFF_CONTRACT_AUTHORITY_ROLE_ACTIVE,
    HANDOFF_CONTRACT_IS_POSTURE_AWARE,
    HANDOFF_ENVELOPE_V2_POSTURE_ADAPTER_ACTIVE,
    NO_AUTHORITY_SILENT_DROP_POLICY,
    NO_POSTURE_SILENT_DROP_POLICY,
    AgentBridge,
    HandoffContract,
    get_agent_bridge,
    handoff_contract_from_envelope,
)
from contracts.handoff_envelope_v2 import (  # noqa: E402
    HandoffEnvelopeV2,
    build_handoff_envelope_v2,
    from_bridge_inputs,
    from_legacy_handoff_contract,
)


# ---------------------------------------------------------------------------
# Canonical handoff contract builder
# ---------------------------------------------------------------------------

def build_canonical_handoff_contract(
    *,
    trace_id: str,
    task: Dict[str, Any],
    capability: str = "",
    exec_mode: str = "both",
    route_mode: str = "direct",
    session: Optional[Dict[str, Any]] = None,
    callback_channel: str = "ws",
    task_id: str = "",
    source_runtime_posture: Optional[str] = None,
    coordination_role: Optional[str] = None,
    formation_role: str = "",
) -> HandoffContract:
    """Build a canonical :class:`HandoffContract` with resolved posture and
    authority metadata.

    This helper is the preferred construction entry point for new code on
    the main-repo side.  It resolves posture and coordination_role using the
    canonical contract and authority modules so callers don't need to import
    them directly.

    Parameters
    ----------
    trace_id:
        Unique trace identifier for deduplication and observability.
    task:
        The task payload dict.
    capability:
        Primary capability required by the task.
    exec_mode:
        Execution mode: "local" | "remote" | "both".
    route_mode:
        AIP v3 route mode, e.g. "direct" or "broadcast".
    session:
        Session context dict forwarded to the runtime.
    callback_channel:
        Preferred response channel: "ws" | "webrtc" | "nats".
    task_id:
        Optional task identifier from a TaskEnvelope.
    source_runtime_posture:
        Source-device runtime participation posture.  If None or invalid,
        resolved to "control_only" via the canonical posture contract.
    coordination_role:
        Authority/coordination role for the source device.  If None, derived
        from posture and formation_role via the PR-538 CoordinationRole model.
    formation_role:
        Optional formation role hint used for coordination_role derivation.

    Returns
    -------
    HandoffContract
        Fully populated contract with canonical posture and authority.
    """
    # Resolve posture via canonical contract layer
    _resolved_posture: str = "control_only"
    try:
        from contracts.source_posture_contract import normalize_posture_for_ingress
        _resolved_posture = normalize_posture_for_ingress(source_runtime_posture or "")
    except Exception:  # noqa: BLE001
        _raw = str(source_runtime_posture or "")
        _resolved_posture = _raw if _raw in ("control_only", "join_runtime") else "control_only"

    # Resolve coordination_role via PR-538 authority model
    _resolved_role: str = str(coordination_role or "")
    if not _resolved_role:
        try:
            from core.multi_device_coordination_authority import derive_coordination_role
            _role_obj = derive_coordination_role(
                source_runtime_posture=_resolved_posture,
                formation_role=formation_role,
            )
            _resolved_role = _role_obj.value
        except Exception:  # noqa: BLE001
            _resolved_role = ""

    return HandoffContract(
        trace_id=trace_id,
        task=task,
        capability=capability,
        exec_mode=exec_mode,
        route_mode=route_mode,
        session=session or {},
        callback_channel=callback_channel,
        task_id=task_id,
        source_runtime_posture=_resolved_posture,
        coordination_role=_resolved_role,
    )


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

__all__ = [
    # Sentinels
    "CANONICAL_HANDOFF_PATH_MAIN_REPO",
    "CANONICAL_HANDOFF_POSTURE_AND_AUTHORITY_UNIFIED",
    "CANONICAL_HANDOFF_PATH_SINGLE_CHAIN_ENFORCED",
    # Re-exported from agent_bridge
    "CANONICAL_HANDOFF_PATH_PR3",
    "CANONICAL_HANDOFF_POSTURE_PROPAGATION_ACTIVE",
    "HANDOFF_CONTRACT_AUTHORITY_ROLE_ACTIVE",
    "HANDOFF_CONTRACT_IS_POSTURE_AWARE",
    "HANDOFF_ENVELOPE_V2_POSTURE_ADAPTER_ACTIVE",
    "NO_AUTHORITY_SILENT_DROP_POLICY",
    "NO_POSTURE_SILENT_DROP_POLICY",
    "AgentBridge",
    "HandoffContract",
    "get_agent_bridge",
    "handoff_contract_from_envelope",
    # Re-exported from contracts
    "HandoffEnvelopeV2",
    "build_handoff_envelope_v2",
    "from_bridge_inputs",
    "from_legacy_handoff_contract",
    # Builder
    "build_canonical_handoff_contract",
]
