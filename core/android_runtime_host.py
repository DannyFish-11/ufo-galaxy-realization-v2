"""core/android_runtime_host.py
=================================
Android First-Class Runtime Host — PR-5 (post-533 dual-repo unification, main-repo half).

This module canonicalises the distinction between Android as a **connected
device** (remote control surface) and Android as a **first-class runtime
host** (autonomous local executor that can join the OpenClawd runtime fabric).

Background
----------
Prior to PR-5, Android was modelled primarily as a connected peripheral: a
device that could send commands, receive projections, and be registered in the
device registry.  The ``source_runtime_posture`` semantics introduced by
PR-533 and adopted on the Android side (PR-106 in the Android repo) created
the structural basis for distinguishing these two roles.

This module closes the main-repo half of PR-5 by providing:

1. :class:`AndroidRuntimeHostRole` — canonical role classification enum.
2. :class:`AndroidRuntimeHostIdentity` — stable, wire-safe identity snapshot
   for an Android device evaluated as a runtime-host candidate.
3. :func:`classify_android_runtime_host` — derives the role from a
   ``RegisteredRuntimeDevice``-shaped input (or a compatible dict).
4. :func:`build_android_runtime_host_identity` — constructs an
   :class:`AndroidRuntimeHostIdentity` from a device record.
5. Policy sentinels confirming PR-5 integration.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Posture-preserving** — fully respects ``source_runtime_posture`` values
  established by PR-533 (``control_only``, ``join_runtime``).
- **Multi-device role compatible** — honours ``CoordinationRole`` semantics
  from PR-6 (``source_controller``, ``joined_runtime_participant``, etc.).
- **Graceful defaults** — unknown or missing fields always yield
  :attr:`AndroidRuntimeHostRole.UNCLASSIFIED`.
- **Fully serialisable** — :meth:`AndroidRuntimeHostIdentity.to_dict` and
  :meth:`AndroidRuntimeHostIdentity.to_json` produce stable, round-trippable
  JSON representations.

Classification logic
--------------------
Android devices are classified by inspecting three signals from the
``RegisteredRuntimeDevice`` contract:

1. ``source_runtime_posture`` — ``join_runtime`` indicates explicit host opt-in.
2. ``is_runtime_host`` — True when the registration adapter already marked the
   device as a runtime host.
3. ``autonomy.runtime_enabled`` + ``autonomy.supports_remote_handoff`` — older
   registrations without an explicit posture field but with these flags set are
   treated as partial runtime hosts.

Usage::

    from core.android_runtime_host import (
        AndroidRuntimeHostRole,
        AndroidRuntimeHostIdentity,
        classify_android_runtime_host,
        build_android_runtime_host_identity,
    )

    from contracts.registered_runtime_device import from_android_registration

    device = from_android_registration({
        "device_id": "phone_001",
        "name": "My Pixel",
        "source_runtime_posture": "join_runtime",
        "app_version": "3.2.0",
    })

    role = classify_android_runtime_host(device)
    # AndroidRuntimeHostRole.FULL_RUNTIME_HOST

    identity = build_android_runtime_host_identity(device)
    payload = identity.to_dict()
"""

from __future__ import annotations

import json
import uuid
from enum import Enum
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _make_android_fallback_id() -> str:
    """Generate a fallback device ID for Android records without one."""
    return f"android_{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class AndroidRuntimeHostRole(str, Enum):
    """Classification of an Android device's runtime-host role.

    Distinguishes devices that are first-class runtime hosts from those that
    are merely connected control surfaces.

    Values
    ------
    FULL_RUNTIME_HOST
        The device explicitly joins the runtime (``source_runtime_posture ==
        'join_runtime'`` and ``is_runtime_host == True``).  It may receive
        handoff, run local inference, and participate as an equal peer in the
        OpenClawd execution fabric.
    PARTIAL_RUNTIME_HOST
        The device has Galaxy-app autonomy flags set (``runtime_enabled``,
        ``supports_remote_handoff``) but did not supply an explicit
        ``join_runtime`` posture.  Treated as a runtime-capable device that
        should be upgraded to full host status when posture is clarified.
    CONNECTED_DEVICE_ONLY
        The device is registered and connected but is not acting as a runtime
        host.  It can control and observe, but tasks are not dispatched to it
        as an autonomous participant.
    UNCLASSIFIED
        Insufficient information to classify the device.  Treated conservatively
        as connected-device-only for dispatch purposes.
    """

    FULL_RUNTIME_HOST = "full_runtime_host"
    PARTIAL_RUNTIME_HOST = "partial_runtime_host"
    CONNECTED_DEVICE_ONLY = "connected_device_only"
    UNCLASSIFIED = "unclassified"

    @classmethod
    def from_string(cls, value: str) -> "AndroidRuntimeHostRole":
        """Return a :class:`AndroidRuntimeHostRole` from a raw string,
        defaulting to :attr:`UNCLASSIFIED` on unrecognised values.
        """
        try:
            return cls(str(value).lower())
        except (ValueError, AttributeError):
            return cls.UNCLASSIFIED


# ---------------------------------------------------------------------------
# Identity snapshot
# ---------------------------------------------------------------------------


class AndroidRuntimeHostIdentity:
    """Stable, serialisable snapshot of an Android device's runtime-host
    identity (PR-5).

    Attributes
    ----------
    device_id:
        Stable unique identifier for the underlying device.
    device_name:
        Human-readable name, if available.
    role:
        Derived :class:`AndroidRuntimeHostRole` classification.
    source_runtime_posture:
        The ``source_runtime_posture`` value from the device record.
    is_runtime_host:
        The ``is_runtime_host`` flag from the device record.
    runtime_enabled:
        Whether the Galaxy runtime is activated on this device.
    supports_remote_handoff:
        Whether the device can participate in cross-device handoff.
    runtime_version:
        Version of the Galaxy app/runtime on the device, if known.
    formation_eligible:
        Whether this device is eligible to participate in a device formation
        as a full peer (True only for FULL_RUNTIME_HOST and
        PARTIAL_RUNTIME_HOST roles).
    snapshot_id:
        Auto-generated stable identifier for this snapshot record.
    """

    __slots__ = (
        "device_id",
        "device_name",
        "role",
        "source_runtime_posture",
        "is_runtime_host",
        "runtime_enabled",
        "supports_remote_handoff",
        "runtime_version",
        "formation_eligible",
        "snapshot_id",
    )

    def __init__(
        self,
        device_id: str,
        device_name: str = "",
        role: AndroidRuntimeHostRole = AndroidRuntimeHostRole.UNCLASSIFIED,
        source_runtime_posture: str = "control_only",
        is_runtime_host: bool = False,
        runtime_enabled: bool = False,
        supports_remote_handoff: bool = False,
        runtime_version: Optional[str] = None,
        formation_eligible: bool = False,
        snapshot_id: Optional[str] = None,
    ) -> None:
        self.device_id = device_id
        self.device_name = device_name
        self.role = role
        self.source_runtime_posture = source_runtime_posture
        self.is_runtime_host = is_runtime_host
        self.runtime_enabled = runtime_enabled
        self.supports_remote_handoff = supports_remote_handoff
        self.runtime_version = runtime_version
        self.formation_eligible = formation_eligible
        self.snapshot_id = snapshot_id or f"arhi_{uuid.uuid4().hex[:12]}"

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "snapshot_id": self.snapshot_id,
            "device_id": self.device_id,
            "device_name": self.device_name,
            "role": self.role.value if isinstance(self.role, AndroidRuntimeHostRole) else str(self.role),
            "source_runtime_posture": self.source_runtime_posture,
            "is_runtime_host": self.is_runtime_host,
            "runtime_enabled": self.runtime_enabled,
            "supports_remote_handoff": self.supports_remote_handoff,
            "runtime_version": self.runtime_version,
            "formation_eligible": self.formation_eligible,
        }

    def to_json(self, **kwargs: Any) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AndroidRuntimeHostIdentity":
        """Reconstruct from a plain dict (e.g., from :meth:`to_dict`)."""
        return cls(
            device_id=str(data.get("device_id", "") or ""),
            device_name=str(data.get("device_name", "") or ""),
            role=AndroidRuntimeHostRole.from_string(
                str(data.get("role", "unclassified"))
            ),
            source_runtime_posture=str(
                data.get("source_runtime_posture", "control_only") or "control_only"
            ),
            is_runtime_host=bool(data.get("is_runtime_host", False)),
            runtime_enabled=bool(data.get("runtime_enabled", False)),
            supports_remote_handoff=bool(data.get("supports_remote_handoff", False)),
            runtime_version=data.get("runtime_version"),
            formation_eligible=bool(data.get("formation_eligible", False)),
            snapshot_id=data.get("snapshot_id"),
        )

    def __repr__(self) -> str:
        return (
            f"AndroidRuntimeHostIdentity("
            f"device_id={self.device_id!r}, "
            f"role={self.role!r}, "
            f"posture={self.source_runtime_posture!r})"
        )


# ---------------------------------------------------------------------------
# Classification function
# ---------------------------------------------------------------------------


def classify_android_runtime_host(device: Any) -> AndroidRuntimeHostRole:
    """Derive the :class:`AndroidRuntimeHostRole` for *device*.

    The function is tolerant of both
    :class:`~contracts.registered_runtime_device.RegisteredRuntimeDevice`
    instances and compatible plain dicts.

    Classification rules (evaluated in order):

    1. **FULL_RUNTIME_HOST**: ``source_runtime_posture == 'join_runtime'``
       *and* ``is_runtime_host == True``.
    2. **FULL_RUNTIME_HOST** (posture-only): ``source_runtime_posture ==
       'join_runtime'`` even if ``is_runtime_host`` is False/missing (the
       posture declaration takes precedence).
    3. **PARTIAL_RUNTIME_HOST**: ``is_runtime_host == True`` but posture is
       ``control_only`` — device has Galaxy app with runtime support but
       hasn't declared full join posture.
    4. **PARTIAL_RUNTIME_HOST** (autonomy flags): ``autonomy.runtime_enabled``
       *and* ``autonomy.supports_remote_handoff`` without an explicit posture.
    5. **CONNECTED_DEVICE_ONLY**: device is online but no runtime-host signals
       are present.
    6. **UNCLASSIFIED**: insufficient data.

    Parameters
    ----------
    device:
        A ``RegisteredRuntimeDevice`` instance, a ``to_dict()``-serialised
        dict, or any object with compatible attribute or key access.

    Returns
    -------
    AndroidRuntimeHostRole
    """
    try:
        # Support both attribute-style and dict-style access.
        if isinstance(device, dict):
            posture = str(device.get("source_runtime_posture", "control_only") or "control_only")
            is_host = bool(device.get("is_runtime_host", False))
            autonomy_raw = device.get("autonomy") or {}
            if isinstance(autonomy_raw, dict):
                rt_enabled = bool(autonomy_raw.get("runtime_enabled", False))
                rt_handoff = bool(autonomy_raw.get("supports_remote_handoff", False))
            else:
                rt_enabled = bool(getattr(autonomy_raw, "runtime_enabled", False))
                rt_handoff = bool(getattr(autonomy_raw, "supports_remote_handoff", False))
            online = bool(device.get("online", False))
        else:
            posture = str(getattr(device, "source_runtime_posture", "control_only") or "control_only")
            is_host = bool(getattr(device, "is_runtime_host", False))
            autonomy = getattr(device, "autonomy", None)
            if autonomy is not None:
                rt_enabled = bool(getattr(autonomy, "runtime_enabled", False))
                rt_handoff = bool(getattr(autonomy, "supports_remote_handoff", False))
            else:
                rt_enabled = bool(getattr(device, "runtime_enabled", False))
                rt_handoff = bool(getattr(device, "supports_remote_handoff", False))
            online = bool(getattr(device, "online", False))

        # Rule 1 & 2: explicit join_runtime posture → FULL_RUNTIME_HOST
        if posture == "join_runtime":
            return AndroidRuntimeHostRole.FULL_RUNTIME_HOST

        # Rule 3: is_runtime_host flag without join_runtime posture
        if is_host:
            return AndroidRuntimeHostRole.PARTIAL_RUNTIME_HOST

        # Rule 4: autonomy flags without explicit posture
        if rt_enabled and rt_handoff:
            return AndroidRuntimeHostRole.PARTIAL_RUNTIME_HOST

        # Rule 5: device is connected but not a runtime host
        if online:
            return AndroidRuntimeHostRole.CONNECTED_DEVICE_ONLY

        # Rule 6: insufficient data
        return AndroidRuntimeHostRole.UNCLASSIFIED

    except Exception as exc:
        return AndroidRuntimeHostRole.UNCLASSIFIED


# ---------------------------------------------------------------------------
# Identity builder
# ---------------------------------------------------------------------------


def build_android_runtime_host_identity(device: Any) -> AndroidRuntimeHostIdentity:
    """Build an :class:`AndroidRuntimeHostIdentity` from *device*.

    Parameters
    ----------
    device:
        A ``RegisteredRuntimeDevice`` instance or compatible dict.

    Returns
    -------
    AndroidRuntimeHostIdentity
        Fully populated identity snapshot.  Degrades gracefully on
        malformed or missing inputs.
    """
    try:
        if isinstance(device, dict):
            device_id = str(device.get("device_id", "") or _make_android_fallback_id())
            device_name = str(device.get("device_name", "") or "")
            posture = str(device.get("source_runtime_posture", "control_only") or "control_only")
            is_host = bool(device.get("is_runtime_host", False))
            autonomy_raw = device.get("autonomy") or {}
            if isinstance(autonomy_raw, dict):
                rt_enabled = bool(autonomy_raw.get("runtime_enabled", False))
                rt_handoff = bool(autonomy_raw.get("supports_remote_handoff", False))
                rt_version: Optional[str] = autonomy_raw.get("runtime_version")
            else:
                rt_enabled = bool(getattr(autonomy_raw, "runtime_enabled", False))
                rt_handoff = bool(getattr(autonomy_raw, "supports_remote_handoff", False))
                rt_version = getattr(autonomy_raw, "runtime_version", None)
        else:
            device_id = str(getattr(device, "device_id", "") or _make_android_fallback_id())
            device_name = str(getattr(device, "device_name", "") or "")
            posture = str(getattr(device, "source_runtime_posture", "control_only") or "control_only")
            is_host = bool(getattr(device, "is_runtime_host", False))
            autonomy = getattr(device, "autonomy", None)
            if autonomy is not None:
                rt_enabled = bool(getattr(autonomy, "runtime_enabled", False))
                rt_handoff = bool(getattr(autonomy, "supports_remote_handoff", False))
                rt_version = getattr(autonomy, "runtime_version", None)
            else:
                rt_enabled = bool(getattr(device, "runtime_enabled", False))
                rt_handoff = bool(getattr(device, "supports_remote_handoff", False))
                rt_version = getattr(device, "runtime_version", None)

        role = classify_android_runtime_host(device)
        formation_eligible = role in (
            AndroidRuntimeHostRole.FULL_RUNTIME_HOST,
            AndroidRuntimeHostRole.PARTIAL_RUNTIME_HOST,
        )

        return AndroidRuntimeHostIdentity(
            device_id=device_id,
            device_name=device_name,
            role=role,
            source_runtime_posture=posture,
            is_runtime_host=is_host,
            runtime_enabled=rt_enabled,
            supports_remote_handoff=rt_handoff,
            runtime_version=rt_version,
            formation_eligible=formation_eligible,
        )
    except Exception as exc:
        try:
            fallback_id = str(getattr(device, "device_id", "") or _make_android_fallback_id())
        except Exception as exc:
            logger.debug("Fallback triggered: %s", exc)
            fallback_id = _make_android_fallback_id()
        return AndroidRuntimeHostIdentity(device_id=fallback_id)


# ---------------------------------------------------------------------------
# PR-5 policy sentinels
# ---------------------------------------------------------------------------

# Confirms that this module provides canonical Android runtime-host
# classification for the main-repo half of PR-5 (post-533 dual-repo track).
ANDROID_FIRST_CLASS_RUNTIME_HOST_PR5_SENTINEL = (
    "ANDROID_FIRST_CLASS_RUNTIME_HOST_PR5_SENTINEL"
)

# Confirms that AndroidRuntimeHostRole distinguishes runtime-host identity
# from mere connected-device presence.
ANDROID_RUNTIME_HOST_DISTINCT_FROM_CONNECTED_DEVICE_PR5 = (
    "ANDROID_RUNTIME_HOST_DISTINCT_FROM_CONNECTED_DEVICE_PR5"
)

# Confirms that posture semantics from PR-533 are preserved and honoured in
# the classification logic above.
ANDROID_RUNTIME_HOST_POSTURE_PRESERVED_PR5 = (
    "ANDROID_RUNTIME_HOST_POSTURE_PRESERVED_PR5"
)

# ---------------------------------------------------------------------------
# Android local AI / on-device inference status sentinels
# ---------------------------------------------------------------------------
# These sentinels make the status of Android-side local AI capabilities
# explicit and machine-checkable.  They prevent the "code present in
# architecture, absent from default runtime" ambiguity from being silently
# treated as an active capability.
#
# Background: The Android repository contains LocalGroundingService /
# LocalPlannerService interfaces whose default implementations (NoOpGroundingService
# et al.) return errors without performing any inference.  Devices register
# without local AI capabilities unless explicitly configured and an actual
# model is loaded at runtime.  This state must not be misread as "active".
# ---------------------------------------------------------------------------

ANDROID_LOCAL_AI_UNAVAILABLE_BY_DEFAULT: str = (
    "ANDROID_LOCAL_AI_UNAVAILABLE_BY_DEFAULT_V2: "
    "Android on-device local AI (LlamaCppPlannerService / NcnnGroundingService / "
    "LocalInferenceRuntimeManager) is NOT ACTIVE / UNAVAILABLE in the default runtime "
    "configuration. As of 2026-05-02, the inference runtimes ARE bundled (llama.cpp "
    "b4833, NCNN ncnn-android-vulkan:20240410) and real JNI implementations exist. "
    "However, inference_mode defaults to 'center' so local inference is OFF unless "
    "explicitly set to 'local' by the operator AND model files (~1.65 GB) have been "
    "downloaded. Devices do not advertise local_ai capability until explicitly "
    "configured and models are provisioned. This capability remains UNAVAILABLE by "
    "default and must not be treated as active without explicit operator action."
)

ANDROID_LOCAL_AI_IS_ROADMAP_NOT_DEFAULT: str = (
    "ANDROID_LOCAL_AI_NOT_DEFAULT_ACTIVE_V2: "
    "Android local AI / on-device grounding / local planner is NOT active by default. "
    "The inference runtimes are now bundled (this is no longer a ROADMAP gap) and "
    "real JNI implementations exist (LlamaCppPlannerService, NcnnGroundingService). "
    "However, inference_mode defaults to 'center', so local inference is not activated "
    "unless the operator explicitly configures inference_mode=local and downloads models. "
    "The ROADMAP gap (missing build deps) has been resolved; the remaining gap is "
    "operator-driven activation and first-run model provisioning."
)

ANDROID_LOCAL_AI_DEFAULT_CAPABILITY_FLAG: bool = False
"""Runtime default for Android local AI capability.

``False`` means Android devices are NOT assumed to have local inference
capability unless they explicitly register with it.  This constant is the
canonical machine-checkable expression of the default-off status described
by :data:`ANDROID_LOCAL_AI_UNAVAILABLE_BY_DEFAULT`.
"""

