"""core/android_boundary_visibility_router.py
==============================================
Dual-Repo Hidden/Visible Boundary Router — Android-Originated Information

This module implements the first runtime path where Android-originated information
and V2-local information share the **same** hidden/visible boundary resolution logic
(foreground / background / operator classification via ``classify_content_layer``).

Previously, Android-originated blockers, results, and signals were interpreted
locally in handler code (``action_lifecycle_surface`` parsing, scattered metadata
checks). This module converges those scattered interpretations into the unified
hidden-visible boundary governance.

Boundary governance table (Android-originated keys)::

    android_blocker            → FOREGROUND_PRESENCE_ACTION
    android_confirmation_needed → FOREGROUND_PRESENCE_ACTION
    android_result_summary     → FOREGROUND_PRESENCE_ACTION
    android_lifecycle_phase    → FOREGROUND_PRESENCE_ACTION
    android_device_state       → BACKGROUND_SEMANTIC   (hidden from foreground)
    android_context            → BACKGROUND_SEMANTIC   (hidden from foreground)
    android_participation_state → BACKGROUND_SEMANTIC
    android_execution_signal   → OPERATOR_AUDIT_TRUTH  (demoted for non-operators)

Runtime path formed (dual-repo shared boundary logic, goal B)::

    _apply_hidden_visible_boundary (core/routes/chat.py)
        → extract_android_originated_info          (this module)
        → apply_dual_repo_boundary_to_visible_action (this module)
            → classify_content_layer              (hidden_context_visible_action_surface.py)
                ← same function used for V2-local metadata keys
        → DualRepoBoundaryDecision
        → updated visible_action_surface / demoted_fields

Scattered-to-unified convergence (goal D):
    Android blocker and android_confirmation_needed previously had
    handler-local / lifecycle-local interpretation inside
    ``_apply_hidden_visible_boundary``. This module extracts them from
    ``action_lifecycle_surface`` (when ``origin`` is android-side) into
    canonical ``android_*`` keys and routes them through
    ``classify_content_layer`` — the unified boundary classifier.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from core.hidden_context_visible_action_surface import SurfaceLayer, classify_content_layer

DUAL_REPO_BOUNDARY_SENTINEL = (
    "DUAL_REPO_BOUNDARY::ANDROID_V2_UNIFIED_HIDDEN_VISIBLE_BOUNDARY_V1"
)

# ---------------------------------------------------------------------------
# Android-originated info keys recognised by this router
# ---------------------------------------------------------------------------

#: Canonical content keys for Android-originated information.
#: These are the same keys registered in LAYER_CONTENT_RULES so that
#: classify_content_layer returns the correct tier for each.
ANDROID_INFO_CONTENT_KEYS: tuple[str, ...] = (
    "android_blocker",
    "android_confirmation_needed",
    "android_result_summary",
    "android_lifecycle_phase",
    "android_presence_signal",
    "android_stream_readiness",
    "android_device_state",
    "android_context",
    "android_participation_state",
    "android_execution_signal",
)
ANDROID_STREAM_COUPLED_FEEDBACK: str = "多端持续感知已联动"
# English: "Multi-device continuous perception is linked."


# ---------------------------------------------------------------------------
# Boundary decision result
# ---------------------------------------------------------------------------


@dataclass
class DualRepoBoundaryDecision:
    """Result of applying the dual-repo hidden/visible boundary to Android info.

    Attributes
    ----------
    foreground_items
        Android-originated items classified as FOREGROUND_PRESENCE_ACTION.
        These contribute to the visible_action_surface.
    background_items
        Android-originated items classified as BACKGROUND_SEMANTIC.
        Suppressed from foreground; available in background context only.
    operator_items
        Android-originated items classified as OPERATOR_AUDIT_TRUTH.
        Demoted for non-operator requests.
    android_boundary_applied
        True iff at least one Android-originated item was classified.
    boundary_affected_foreground
        True iff at least one Android-originated item changed the foreground
        visible action payload (visible_action_surface was updated).
    sentinel
        Module sentinel for contract verification.
    """

    foreground_items: Dict[str, Any] = field(default_factory=dict)
    background_items: Dict[str, Any] = field(default_factory=dict)
    operator_items: Dict[str, Any] = field(default_factory=dict)
    android_boundary_applied: bool = False
    boundary_affected_foreground: bool = False
    sentinel: str = DUAL_REPO_BOUNDARY_SENTINEL

    def to_dict(self) -> Dict[str, Any]:
        return {
            "foreground_items": self.foreground_items,
            "background_items": self.background_items,
            "operator_items": self.operator_items,
            "android_boundary_applied": self.android_boundary_applied,
            "boundary_affected_foreground": self.boundary_affected_foreground,
            "sentinel": self.sentinel,
        }


# ---------------------------------------------------------------------------
# Extraction — scattered → unified convergence
# ---------------------------------------------------------------------------


def _extract_blocker_reason(lifecycle: Dict[str, Any]) -> str:
    """Extract the blocker reason string from a lifecycle surface dict."""
    return str(
        lifecycle.get("blocker_reason")
        or (lifecycle.get("blocker") or {}).get("reason", "")
        or ""
    ).strip()


def _derive_presence_mode_from_signal(*, current_mode: str) -> str:
    normalized = current_mode.strip().lower()
    if normalized in {"", "unknown", "static", "silent"}:
        return "liminal"
    return current_mode


def _extract_canonical_continuous_ingress(result: Dict[str, Any]) -> Dict[str, Any]:
    direct_ingress = result.get("canonical_continuous_ingress")
    if isinstance(direct_ingress, dict):
        return direct_ingress

    metadata = result.get("metadata")
    if not isinstance(metadata, dict):
        return {}
    ingress_backbone = metadata.get("desktop_native_ingress_backbone")
    if not isinstance(ingress_backbone, dict):
        return {}
    maybe_ingress = ingress_backbone.get("canonical_continuous_ingress")
    if isinstance(maybe_ingress, dict):
        return maybe_ingress
    return {}


def extract_android_originated_info(result: Dict[str, Any]) -> Dict[str, Any]:
    """Extract Android-originated information from a result dict.

    Looks for two sources:

    1. ``result["android_originated_info"]`` — explicit Android info block
       containing any subset of :data:`ANDROID_INFO_CONTENT_KEYS`.

    2. ``result["action_lifecycle_surface"]["origin"] == "android_*"``  —
       lifecycle surface with an android origin.  Blocker/confirmation/phase
       are extracted into canonical ``android_*`` keys.  This is the
       **scattered-to-unified convergence**: previously these fields were
       consumed only by hardcoded handler paths; now they also enter the
       unified boundary classifier.

    Returns a flat ``{canonical_content_key: value}`` dict.  Keys from source 1
    take precedence over keys derived from source 2.
    """
    android_info: Dict[str, Any] = {}

    # Source 1: explicit android_originated_info block
    explicit = result.get("android_originated_info")
    if isinstance(explicit, dict):
        for key in ANDROID_INFO_CONTENT_KEYS:
            if key in explicit:
                android_info[key] = explicit[key]

    # Source 2: action_lifecycle_surface with android origin (scattered → unified)
    lifecycle = result.get("action_lifecycle_surface")
    if isinstance(lifecycle, dict):
        origin = str(lifecycle.get("origin", ""))
        if origin.startswith("android"):
            blocker_reason = _extract_blocker_reason(lifecycle)
            if blocker_reason and "android_blocker" not in android_info:
                android_info["android_blocker"] = blocker_reason
            confirmation = bool(
                lifecycle.get("confirmation_needed", False)
            )
            if confirmation and "android_confirmation_needed" not in android_info:
                android_info["android_confirmation_needed"] = confirmation
            phase = str(lifecycle.get("phase") or "").strip()
            if phase and "android_lifecycle_phase" not in android_info:
                android_info["android_lifecycle_phase"] = phase

    # Source 3: canonical default Android presence runtime + canonical continuous ingress.
    # This links Android presence participation with stream readiness under the
    # same boundary governance path used for Android blockers/results.
    android_presence_runtime = result.get("android_presence_runtime")
    if isinstance(android_presence_runtime, dict):
        if bool(android_presence_runtime.get("any_presence_participant")):
            if bool(android_presence_runtime.get("any_foreground_presence")):
                android_info.setdefault("android_presence_signal", "foreground_presence")
            elif bool(android_presence_runtime.get("any_drives_manifest")):
                android_info.setdefault("android_presence_signal", "manifest_ready")
            elif bool(android_presence_runtime.get("any_drives_liminal")):
                android_info.setdefault("android_presence_signal", "liminal_ready")
            else:
                android_info.setdefault("android_presence_signal", "presence_participant")

            canonical_continuous_ingress = _extract_canonical_continuous_ingress(result)
            families = canonical_continuous_ingress.get("families") or {}
            if not isinstance(families, dict):
                families = {}
            desktop_stream_present = bool(
                (families.get("desktop_continuous_stream") or {}).get("is_present")
            )
            android_stream_present = bool(
                (families.get("android_device_continuous_stream") or {}).get("is_present")
            )
            if desktop_stream_present or android_stream_present:
                android_info.setdefault("android_stream_readiness", "presence_stream_coupled")

    return android_info


# ---------------------------------------------------------------------------
# Boundary resolution — shared path (goal B)
# ---------------------------------------------------------------------------


def apply_dual_repo_boundary_to_visible_action(
    android_info: Dict[str, Any],
    visible_action_surface: Dict[str, Any],
    demoted_fields: List[str],
    is_operator_request: bool,
) -> DualRepoBoundaryDecision:
    """Apply the unified hidden/visible boundary to Android-originated information.

    This is the core dual-repo boundary resolution.  Android-originated items
    are classified by the **same** ``classify_content_layer`` function used
    for V2-local metadata, and the classification determines their
    foreground / background / operator tier.

    Parameters
    ----------
    android_info:
        Android-originated information dict (from
        :func:`extract_android_originated_info`).
    visible_action_surface:
        The current visible action surface dict.  **Mutated in-place** with
        items whose layer is ``FOREGROUND_PRESENCE_ACTION``.
    demoted_fields:
        Running list of demoted operator fields.  **Extended in-place** with
        ``"android:<key>"`` labels for ``OPERATOR_AUDIT_TRUTH`` items when the
        request is not operator-facing.
    is_operator_request:
        Whether this is an operator-facing request.

    Returns
    -------
    DualRepoBoundaryDecision
        Classification result with foreground / background / operator tiers.
        ``boundary_affected_foreground`` is ``True`` iff at least one
        Android item updated the foreground visible action surface.
    """
    decision = DualRepoBoundaryDecision()

    if not android_info:
        return decision

    decision.android_boundary_applied = True

    # Classify every Android-originated key via the shared boundary function
    for key, value in android_info.items():
        layer = classify_content_layer(key)
        if layer == SurfaceLayer.FOREGROUND_PRESENCE_ACTION:
            decision.foreground_items[key] = value
        elif layer == SurfaceLayer.OPERATOR_AUDIT_TRUTH:
            decision.operator_items[key] = value
        else:
            decision.background_items[key] = value

    # ── Helper: set a visible_action_surface field only if it is not already set
    def _set_foreground_if_absent(surface_key: str, value: Any) -> None:
        if value and not visible_action_surface.get(surface_key):
            visible_action_surface[surface_key] = value
            decision.boundary_affected_foreground = True

    # Foreground items → contribute to visible_action_surface
    for key, value in decision.foreground_items.items():
        if key == "android_blocker":
            # Unified convergence: android_blocker drives the same
            # blocker_summary field as V2-local blockers.  This is the
            # behavioral change: foreground response will now include the
            # android-originated blocker without requiring separate
            # hardcoded lifecycle parsing.
            _set_foreground_if_absent("blocker_summary", str(value) if value else "")
        elif key == "android_confirmation_needed":
            _set_foreground_if_absent("confirmation_needed", bool(value) if value else False)
        elif key == "android_result_summary":
            _set_foreground_if_absent("result_artifacts_summary", str(value) if value else "")
        elif key == "android_lifecycle_phase" and value:
            # Annotate visible_action_surface with android-side lifecycle phase.
            # This supplements (does not replace) the V2-derived current_action_state.
            visible_action_surface.setdefault("android_lifecycle_phase", str(value))
            decision.boundary_affected_foreground = True
        elif key == "android_presence_signal" and value:
            visible_action_surface["android_presence_signal"] = str(value)
            current_mode = str(visible_action_surface.get("current_presence_mode") or "")
            visible_action_surface["current_presence_mode"] = _derive_presence_mode_from_signal(
                current_mode=current_mode
            )
            decision.boundary_affected_foreground = True
        elif key == "android_stream_readiness" and value:
            visible_action_surface["continuous_stream_readiness"] = str(value)
            visible_action_surface.setdefault(
                "lifecycle_status_feedback",
                "android_presence_stream_coupled",
            )
            visible_action_surface.setdefault(
                "lightweight_status_feedback",
                ANDROID_STREAM_COUPLED_FEEDBACK,
            )
            decision.boundary_affected_foreground = True
        else:
            _set_foreground_if_absent(key, value)

    # Operator items → demote for non-operator requests, include for operators
    for key, value in decision.operator_items.items():
        if not is_operator_request:
            demoted_fields.append(f"android:{key}")
        else:
            visible_action_surface[key] = value

    # Background items are suppressed from foreground (no action needed)

    return decision
