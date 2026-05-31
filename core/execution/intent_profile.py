"""core/execution/intent_profile.py
=====================================
ExecutionIntentProfile — canonical execution intent contract for Galaxy.

This module defines the **ExecutionIntentProfile**: a serialisable, wire-safe
object that represents *what the system intends to execute* before any
readiness gating, fallback routing, projection assembly, or policy alignment
takes place.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **No breaking API changes** — fully backward-compatible.
- **Fully serialisable** — :meth:`ExecutionIntentProfile.to_dict` and
  :meth:`ExecutionIntentProfile.to_json` produce stable, round-trippable output.
- **Graceful defaults** — all fields beyond the minimal required set are optional
  and carry safe defaults so that callers with partial metadata can always build
  a valid profile.

Usage::

    from core.execution.intent_profile import build_execution_intent_profile

    profile = build_execution_intent_profile(
        state_continuum=continuum_dict,
        runtime_session_id="sess-abc",
        source="openclawd",
    )
    payload = profile.to_dict()

See ``docs/EXECUTION_INTENT_PROFILE.md`` for the full specification.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# IntentMode — normalised execution-mode vocabulary
# ---------------------------------------------------------------------------


class IntentMode:
    """Canonical intent-mode constants.

    Derived from action_level and optional override signals.

    advisory
        Observe and/or emit lightweight ambient hints; no action.
    assistive
        Proactive partial engagement — soft target focus, context app launch.
    direct
        Explicit, user-initiated direct action.
    autonomous
        Self-directed execution with full policy compliance.
    """

    ADVISORY = "advisory"
    ASSISTIVE = "assistive"
    DIRECT = "direct"
    AUTONOMOUS = "autonomous"

    _LEVEL_MAP: Dict[str, str] = {
        "observe": ADVISORY,
        "hint": ADVISORY,
        "assist": ASSISTIVE,
        "execute": DIRECT,
    }

    @classmethod
    def from_action_level(cls, action_level: str) -> str:
        """Return the normalised :class:`IntentMode` constant for *action_level*."""
        return cls._LEVEL_MAP.get(action_level.lower(), cls.ADVISORY)


# ---------------------------------------------------------------------------
# ExecutionIntentProfile
# ---------------------------------------------------------------------------


class ExecutionIntentProfile(BaseModel):
    """Canonical, wire-safe execution intent profile.

    Captures *what the system intends to execute* in a stable structure that
    downstream modules (executor, policy gate, projection, governance) can
    consume consistently.

    Fields
    ------
    intent_id
        Unique identifier for this intent instance (UUID4).
    runtime_session_id
        Identifier of the active runtime/OpenClawd session.  May be ``None``
        when not yet established.
    source
        Origin of the intent
        (``"chat"`` / ``"openclawd"`` / ``"e2e"`` / ``"runtime"`` / custom).
    action_level
        Graduated action level from the Decision Gate
        (``"observe"`` / ``"hint"`` / ``"assist"`` / ``"execute"``).
        Defaults to ``"observe"`` (safe no-op).
    intent_mode
        Normalised execution mode derived from *action_level* and context
        (``"advisory"`` / ``"assistive"`` / ``"direct"`` / ``"autonomous"``).
    target_type
        Category of the execution target
        (e.g. ``"app"``, ``"window"``, ``"url"``, ``"device"``, ``"command"``).
        ``None`` when no target is identified.
    target_ref
        Specific target reference (app name, window title, device ID, …).
        ``None`` when unavailable.
    target_payload
        Auxiliary parameters for the target execution (free-form dict).
    device_scope
        Scope of target device(s)
        (``"local"`` / ``"remote"`` / ``"multi-device"``).
        ``None`` until resolved.
    runtime_domain
        Runtime domain string (``"local"`` / ``"cross_device"`` / ``"transition"``).
        ``None`` when unresolved.
    confidence
        Confidence score [0.0, 1.0] derived from the Decision Gate signal.
        Defaults to ``0.0``.
    safety_constraints
        List of active safety constraint tags (e.g. ``"allowlist_required"``).
    origin_state
        Short tag describing the originating continuum/decision state
        (e.g. ``"manifest"``, ``"liminal"``).  ``None`` when unavailable.
    notes
        Optional human-readable notes or debug context.
    degrade_reason
        Non-``None`` when the intent was downgraded (e.g. ``"policy_blocked"``).
    """

    intent_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for this intent instance.",
    )
    runtime_session_id: Optional[str] = Field(
        default=None,
        description="Active runtime / OpenClawd session ID.",
    )
    source: str = Field(
        default="openclawd",
        description="Origin of the intent (chat / openclawd / e2e / runtime / other).",
    )
    action_level: str = Field(
        default="observe",
        description="Graduated action level from the Decision Gate.",
    )
    intent_mode: str = Field(
        default=IntentMode.ADVISORY,
        description="Normalised execution mode (advisory / assistive / direct / autonomous).",
    )
    target_type: Optional[str] = Field(
        default=None,
        description="Category of the execution target (app / window / url / device / command).",
    )
    target_ref: Optional[str] = Field(
        default=None,
        description="Specific target reference (app name, window title, device ID, …).",
    )
    target_payload: Dict[str, Any] = Field(
        default_factory=dict,
        description="Auxiliary parameters for the target execution.",
    )
    device_scope: Optional[str] = Field(
        default=None,
        description="Scope of target device(s) (local / remote / multi-device).",
    )
    runtime_domain: Optional[str] = Field(
        default=None,
        description="Runtime domain string (local / cross_device / transition).",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confidence score [0, 1] from the Decision Gate.",
    )
    safety_constraints: List[str] = Field(
        default_factory=list,
        description="Active safety constraint tags.",
    )
    origin_state: Optional[str] = Field(
        default=None,
        description="Originating continuum/decision state tag (manifest / liminal / …).",
    )
    notes: Optional[str] = Field(
        default=None,
        description="Optional human-readable notes or debug context.",
    )
    degrade_reason: Optional[str] = Field(
        default=None,
        description="Non-None when the intent was downgraded (e.g. policy_blocked).",
    )

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation of this profile."""
        return self.model_dump()

    def to_json(self, **kwargs: Any) -> str:
        """Return a compact JSON string representation of this profile."""
        return json.dumps(self.to_dict(), **kwargs)

    # ------------------------------------------------------------------
    # Factory / builder class methods
    # ------------------------------------------------------------------

    @classmethod
    def from_state_continuum(
        cls,
        state_continuum: Optional[Dict[str, Any]],
        *,
        runtime_session_id: Optional[str] = None,
        source: str = "openclawd",
        entry_mode: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> "ExecutionIntentProfile":
        """Build an :class:`ExecutionIntentProfile` from a serialised continuum state dict.

        Parameters
        ----------
        state_continuum:
            Serialised ``ContinuumState`` dict (as produced by
            ``OpenClawd._run_continuum()``).  Gracefully handles ``None`` and
            partial dicts — missing fields fall back to safe defaults.
        runtime_session_id:
            Active session ID to stamp on the profile.
        source:
            Intent origin tag (``"openclawd"`` by default).
        entry_mode:
            Ingress-layer execution mode
            (``"local"`` | ``"cross_device"`` | ``"hybrid"`` | ``None``).
            Mapped to ``device_scope`` when provided.
        notes:
            Optional debug/context note to attach.

        Returns
        -------
        ExecutionIntentProfile
            A fully-populated (or minimally-populated) profile.  Never raises.
        """
        try:
            return _build_from_continuum(
                state_continuum,
                runtime_session_id=runtime_session_id,
                source=source,
                entry_mode=entry_mode,
                notes=notes,
            )
        except Exception:
            # Last-resort fallback — return a minimal safe profile
            return cls(
                runtime_session_id=runtime_session_id,
                source=source,
                notes=notes,
            )

    def compact_summary(self) -> Dict[str, Any]:
        """Return a compact, projection-safe summary of key intent fields.

        Suitable for inclusion in :class:`~core.projection.runtime_projection.RuntimeProjection`
        or governance/debug surfaces without bloating the full schema.
        """
        return {
            "intent_id": self.intent_id,
            "source": self.source,
            "action_level": self.action_level,
            "intent_mode": self.intent_mode,
            "target_type": self.target_type,
            "target_ref": self.target_ref,
            "device_scope": self.device_scope,
            "runtime_domain": self.runtime_domain,
            "confidence": self.confidence,
            "degrade_reason": self.degrade_reason,
        }


# ---------------------------------------------------------------------------
# Module-level builder (preferred public API)
# ---------------------------------------------------------------------------


def build_execution_intent_profile(
    state_continuum: Optional[Dict[str, Any]] = None,
    *,
    runtime_session_id: Optional[str] = None,
    source: str = "openclawd",
    entry_mode: Optional[str] = None,
    notes: Optional[str] = None,
) -> ExecutionIntentProfile:
    """Build a canonical :class:`ExecutionIntentProfile` from available runtime signals.

    This is the **preferred entry-point** for constructing an intent profile.
    It normalises scattered inputs (continuum state, action_level, metadata,
    runtime session, device/entry mode) into the unified profile contract.

    Parameters
    ----------
    state_continuum:
        Serialised ``ContinuumState`` dict.  ``None`` is safe — produces a
        minimal observe-level profile.
    runtime_session_id:
        Active OpenClawd / runtime session ID.
    source:
        Origin tag (``"chat"`` / ``"openclawd"`` / ``"e2e"`` / ``"runtime"``).
    entry_mode:
        Ingress-layer execution mode string.  Mapped to ``device_scope``.
    notes:
        Optional debug note.

    Returns
    -------
    ExecutionIntentProfile
        Always returns a valid profile; never raises.
    """
    return ExecutionIntentProfile.from_state_continuum(
        state_continuum,
        runtime_session_id=runtime_session_id,
        source=source,
        entry_mode=entry_mode,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _build_from_continuum(
    state_continuum: Optional[Dict[str, Any]],
    *,
    runtime_session_id: Optional[str],
    source: str,
    entry_mode: Optional[str],
    notes: Optional[str],
) -> ExecutionIntentProfile:
    """Internal implementation that extracts fields from *state_continuum*."""
    sc = state_continuum or {}

    # --- action_level ------------------------------------------------------
    action_level = "observe"
    try:
        decision = sc.get("decision") or {}
        if isinstance(decision, dict):
            action_level = str(decision.get("action_level", "observe"))
    except Exception as exc:
        logger.warning("Exception suppressed: %s", exc)

    # --- confidence ---------------------------------------------------------
    confidence = 0.0
    try:
        decision = sc.get("decision") or {}
        if isinstance(decision, dict):
            raw_conf = decision.get("decision_confidence", 0.0)
            confidence = float(raw_conf) if raw_conf is not None else 0.0
            confidence = max(0.0, min(1.0, confidence))
    except Exception as exc:
        logger.warning("Exception suppressed: %s", exc)

    # --- target extraction --------------------------------------------------
    target_ref: Optional[str] = None
    target_type: Optional[str] = None
    target_payload: Dict[str, Any] = {}
    try:
        meta = sc.get("metadata") or {}
        if isinstance(meta, dict):
            target_ref = meta.get("execution_target") or meta.get("assist_target") or None
            target_type = meta.get("target_type") or None
            raw_payload = meta.get("target_payload")
            if isinstance(raw_payload, dict):
                target_payload = raw_payload
    except Exception as exc:
        logger.warning("Exception suppressed: %s", exc)

    # Infer target_type when absent
    if target_ref and not target_type:
        target_type = _infer_target_type(target_ref)

    # --- runtime_domain / device_scope ------------------------------------
    runtime_domain: Optional[str] = None
    device_scope: Optional[str] = None
    try:
        runtime_domain = str(sc.get("runtime_domain")) if sc.get("runtime_domain") else None
    except Exception as exc:
        logger.warning("Exception suppressed: %s", exc)

    if entry_mode:
        device_scope = _entry_mode_to_device_scope(entry_mode)
    elif runtime_domain:
        device_scope = _runtime_domain_to_device_scope(runtime_domain)

    # --- origin_state -------------------------------------------------------
    origin_state: Optional[str] = None
    try:
        phase = sc.get("phase") or sc.get("tri_state_phase") or None
        if phase:
            origin_state = str(phase)
    except Exception as exc:
        logger.warning("Exception suppressed: %s", exc)

    # --- safety_constraints -------------------------------------------------
    safety_constraints: List[str] = []
    try:
        meta = sc.get("metadata") or {}
        if isinstance(meta, dict):
            raw_sc = meta.get("safety_constraints")
            if isinstance(raw_sc, list):
                safety_constraints = [str(c) for c in raw_sc]
    except Exception as exc:
        logger.warning("Exception suppressed: %s", exc)

    # --- intent_mode --------------------------------------------------------
    intent_mode = IntentMode.from_action_level(action_level)

    return ExecutionIntentProfile(
        runtime_session_id=runtime_session_id,
        source=source,
        action_level=action_level,
        intent_mode=intent_mode,
        target_type=target_type,
        target_ref=target_ref,
        target_payload=target_payload,
        device_scope=device_scope,
        runtime_domain=runtime_domain,
        confidence=confidence,
        safety_constraints=safety_constraints,
        origin_state=origin_state,
        notes=notes,
    )


def _infer_target_type(target_ref: str) -> str:
    """Heuristically infer a ``target_type`` from a *target_ref* string.

    The heuristic checks for URL schemes, device prefixes, and known executable
    extensions in the final path component before falling back to ``"app"``.
    """
    lower = target_ref.lower()
    if lower.startswith(("http://", "https://", "ftp://")):
        return "url"
    if lower.startswith(("\\\\", "//")):
        return "unc_path"
    if lower.startswith("device:") or lower.startswith("dev-"):
        return "device"
    # Only classify as app when the *last* component has a known executable extension.
    _known_exe_exts = (".exe", ".bat", ".cmd", ".sh", ".app", ".msi", ".ps1")
    _last = lower.split("/")[-1].split("\\")[-1]
    if any(_last.endswith(ext) for ext in _known_exe_exts):
        return "app"
    return "app"


def _entry_mode_to_device_scope(entry_mode: str) -> Optional[str]:
    """Map an ingress *entry_mode* string to a ``device_scope`` value."""
    mapping: Dict[str, str] = {
        "local": "local",
        "cross_device": "remote",
        "hybrid": "multi-device",
    }
    return mapping.get(entry_mode.lower())


def _runtime_domain_to_device_scope(runtime_domain: str) -> Optional[str]:
    """Map a *runtime_domain* string to a ``device_scope`` value."""
    mapping: Dict[str, str] = {
        "local": "local",
        "cross_device": "remote",
        "transition": "local",
    }
    return mapping.get(runtime_domain.lower())
