"""core/capability_registry.py
==============================
PR-11 — Canonical Device Capability Registry and Capability-Resolution Helper Layer.

This module is the single canonical location for device capability summaries
and capability-match resolution.  It aggregates capability metadata from
the sources that are already present in the repository (device registry,
capability bus, gateway capability registry) in a **best-effort, defensive
manner** so that:

- Capability checks no longer need to be scattered across ad-hoc call sites.
- Partial / missing metadata degrades gracefully (records reasons rather than
  raising exceptions).
- Consumers get a stable, serialisable view regardless of which underlying
  capability source is available at import time.

Architecture role
-----------------
This module is **read-only** and **additive** — it does not mutate any
existing registry.  It acts as a thin aggregation/projection layer on top of:

  1. ``core.device_registry.DeviceRegistry``  (capability_index + Device objects)
  2. ``core.capability_bus.CapabilityBus``     (CapabilityBusEntry objects with DEVICE role)
  3. Canonical gateway capability projection
     (per-device action schemas — legacy surface)

Each source is imported lazily with a ``try/except`` so that import failures
(circular-import avoidance, missing optional dependencies) are recorded in
``reasons`` rather than crashing the caller.

Public API
----------
  CAPABILITY_REGISTRY_AUTHORITY  — module-level sentinel string
  DeviceCapabilitySummary        — serialisable summary for a single device
  CapabilityMatchResult          — match result for a requirement check
  get_device_capability_summary(device_id)
  device_matches_capabilities(device_id, required_capabilities)
  get_devices_matching_capabilities(required_capabilities)
"""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.CapabilityRegistry")

# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

CAPABILITY_REGISTRY_AUTHORITY = "core.capability_registry" " — canonical device capability resolution layer (PR-11)"

CAPABILITY_REGISTRY_ROUTING_GUARD = (
    "CAPABILITY_REGISTRY_ROUTING_GUARD_V1: "
    "routing-context modules must not use core.capability_registry as a "
    "selection/routing authority. Canonical routing must use "
    "core.capability_network_runtime_policy query helpers instead."
)

_ROUTING_CONTEXT_MODULE_BASENAMES = frozenset(
    {
        "command_router.py",
        "formation_resolver.py",
        "device_router.py",
    }
)
_MISUSE_EVENT_LIMIT = 100


@dataclass
class CapabilityRegistryMisuseEvent:
    """Structured event recorded when routing code uses the capability registry."""

    operation: str
    caller_module: str
    caller_function: str
    device_id: str = ""
    required_capabilities: List[str] = field(default_factory=list)
    reason: str = CAPABILITY_REGISTRY_ROUTING_GUARD

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operation": self.operation,
            "caller_module": self.caller_module,
            "caller_function": self.caller_function,
            "device_id": self.device_id,
            "required_capabilities": list(self.required_capabilities),
            "reason": self.reason,
        }


_capability_registry_misuse_events: List[CapabilityRegistryMisuseEvent] = []

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class DeviceCapabilitySummary:
    """Serialisable capability summary for a single device.

    Attributes
    ----------
    device_id:
        Unique device identifier.
    available:
        ``True`` when the device is known and at least one capability source
        confirmed its existence.  ``False`` when the device cannot be found in
        any source.
    declared_capabilities:
        Capability names declared by the device during registration (sourced
        from ``DeviceRegistry``).
    resolved_capabilities:
        Union of all capability names resolved across every available source.
        This is the recommended field for requirement matching.
    sources:
        Diagnostic dict mapping source name → raw data extracted from that
        source.  Useful for debugging but not for policy decisions.
    reasons:
        Human-readable notes explaining any degradation or fallback that
        occurred during resolution.
    """

    device_id: str
    available: bool = False
    declared_capabilities: List[str] = field(default_factory=list)
    resolved_capabilities: List[str] = field(default_factory=list)
    sources: Dict[str, Any] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return {
            "device_id": self.device_id,
            "available": self.available,
            "declared_capabilities": list(self.declared_capabilities),
            "resolved_capabilities": list(self.resolved_capabilities),
            "sources": dict(self.sources),
            "reasons": list(self.reasons),
        }


@dataclass
class CapabilityMatchResult:
    """Result of a capability-requirement match for a single device.

    Attributes
    ----------
    device_id:
        Unique device identifier.
    required_capabilities:
        The capability names that were tested.
    matched:
        ``True`` when every required capability is present in the device's
        resolved capabilities.
    missing_capabilities:
        Capabilities from *required_capabilities* that are absent.
    sources:
        Diagnostic dict forwarded from the underlying
        :class:`DeviceCapabilitySummary`.
    reasons:
        Human-readable notes (forwarded from summary + any match-level notes).
    """

    device_id: str
    required_capabilities: List[str] = field(default_factory=list)
    matched: bool = False
    missing_capabilities: List[str] = field(default_factory=list)
    sources: Dict[str, Any] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return {
            "device_id": self.device_id,
            "required_capabilities": list(self.required_capabilities),
            "matched": self.matched,
            "missing_capabilities": list(self.missing_capabilities),
            "sources": dict(self.sources),
            "reasons": list(self.reasons),
        }


# ---------------------------------------------------------------------------
# Internal helpers — source aggregation (all imports are lazy + defensive)
# ---------------------------------------------------------------------------


def _record_capability_registry_misuse_event(
    event: CapabilityRegistryMisuseEvent,
) -> None:
    _capability_registry_misuse_events.append(event)
    if len(_capability_registry_misuse_events) > _MISUSE_EVENT_LIMIT:
        del _capability_registry_misuse_events[:-_MISUSE_EVENT_LIMIT]


def _guard_routing_context_usage(
    *,
    operation: str,
    device_id: str = "",
    required_capabilities: Optional[List[str]] = None,
) -> None:
    """Record misuse when routing-context modules consult the compat registry."""

    try:
        stack = inspect.stack()
    except Exception:
        return

    for frameinfo in stack[2:]:
        filename = (getattr(frameinfo, "filename", "") or "").replace("\\", "/")
        basename = filename.rsplit("/", 1)[-1]
        if basename not in _ROUTING_CONTEXT_MODULE_BASENAMES:
            continue

        event = CapabilityRegistryMisuseEvent(
            operation=operation,
            caller_module=filename,
            caller_function=getattr(frameinfo, "function", ""),
            device_id=device_id,
            required_capabilities=list(required_capabilities or []),
        )
        _record_capability_registry_misuse_event(event)
        logger.warning(
            "capability_registry misuse detected | operation=%s caller=%s function=%s "
            "device_id=%s required_capabilities=%s policy=%s",
            operation,
            filename,
            getattr(frameinfo, "function", ""),
            device_id,
            list(required_capabilities or []),
            CAPABILITY_REGISTRY_ROUTING_GUARD,
        )
        return


def get_capability_registry_misuse_events() -> List[CapabilityRegistryMisuseEvent]:
    """Return recorded routing-context misuse events."""

    return list(_capability_registry_misuse_events)


def reset_capability_registry_misuse_events() -> None:
    """Reset recorded routing-context misuse events (tests only)."""

    _capability_registry_misuse_events.clear()


def _collect_from_device_registry(device_id: str) -> Dict[str, Any]:
    """Return ``{"caps": [...], "available": bool}`` from DeviceRegistry.

    Returns an empty dict with a reason string on any failure.
    """
    result: Dict[str, Any] = {"caps": [], "available": False, "reason": None}
    try:
        from core.device_registry import device_registry  # local singleton

        device = device_registry.get(device_id)
        if device is None:
            result["reason"] = "device_registry: device_id not found"
            return result

        result["available"] = True
        cap_names = [cap.name for cap in getattr(device, "capabilities", []) if cap.name is not None and cap.name != ""]
        result["caps"] = cap_names
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("Fallback triggered: %s", exc)
        result["reason"] = f"device_registry: import/access error — {exc}"
        logger.debug(
            "capability_registry: device_registry source unavailable for %s — %s",
            device_id,
            exc,
        )
    return result


def _collect_from_capability_bus(device_id: str) -> Dict[str, Any]:
    """Return ``{"caps": [...]}`` from CapabilityBus (DEVICE-role entries).

    Returns an empty dict on any failure.
    """
    result: Dict[str, Any] = {"caps": [], "reason": None}
    try:
        from core.capability_bus import CapabilityBusRole, get_capability_bus

        bus = get_capability_bus()
        prefix = f"device__{device_id}__"
        entries = [e for e in bus.list_by_role(CapabilityBusRole.DEVICE) if e.name.startswith(prefix)]
        # Extract action suffix as capability name
        caps = [e.name[len(prefix) :] for e in entries if e.name[len(prefix) :] != ""]
        result["caps"] = caps
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("Fallback triggered: %s", exc)
        result["reason"] = f"capability_bus: import/access error — {exc}"
        logger.debug(
            "capability_registry: capability_bus source unavailable for %s — %s",
            device_id,
            exc,
        )
    return result


def _collect_from_gateway_registry(device_id: str) -> Dict[str, Any]:
    """Return ``{"caps": [...]}`` from the canonical gateway capability view.

    Returns an empty dict on any failure.
    """
    result: Dict[str, Any] = {"caps": [], "reason": None}
    try:
        from core.unified.gateway_capability_projection import (
            get_gateway_capabilities_for_device,
        )

        schemas = get_gateway_capabilities_for_device(device_id)
        caps = [s.action for s in schemas if s.action]
        result["caps"] = caps
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("Fallback triggered: %s", exc)
        result["reason"] = f"gateway_capability_projection: import/access error — {exc}"
        logger.debug(
            "capability_registry: gateway_capability_projection source unavailable for %s — %s",
            device_id,
            exc,
        )
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_device_capability_summary(device_id: str) -> DeviceCapabilitySummary:
    """Return a :class:`DeviceCapabilitySummary` for *device_id*.

    Aggregates from all available capability sources.  If a source is
    unavailable (import error, device not found, etc.) the failure is
    recorded in ``reasons`` and resolution continues with the remaining
    sources.

    Args:
        device_id: The identifier of the device to summarise.

    Returns:
        A :class:`DeviceCapabilitySummary` with ``available=True`` when the
        device was found in at least one source.
    """
    _guard_routing_context_usage(
        operation="get_device_capability_summary",
        device_id=device_id,
    )
    summary = DeviceCapabilitySummary(device_id=device_id)

    # ── Source 1: DeviceRegistry ──────────────────────────────────────────
    dr_data = _collect_from_device_registry(device_id)
    summary.sources["device_registry"] = dr_data.get("caps", [])
    if dr_data.get("available"):
        summary.available = True
        summary.declared_capabilities = list(dr_data.get("caps", []))
    if dr_data.get("reason"):
        summary.reasons.append(dr_data["reason"])

    # ── Source 2: CapabilityBus ───────────────────────────────────────────
    cb_data = _collect_from_capability_bus(device_id)
    summary.sources["capability_bus"] = cb_data.get("caps", [])
    if cb_data.get("reason"):
        summary.reasons.append(cb_data["reason"])

    # ── Source 3: canonical gateway capability projection ─────────────────
    gw_data = _collect_from_gateway_registry(device_id)
    summary.sources["gateway_capability_registry"] = gw_data.get("caps", [])
    if gw_data.get("reason"):
        summary.reasons.append(gw_data["reason"])

    # ── Merge resolved capabilities (union, order-preserving, deduped) ──
    seen: set = set()
    resolved: List[str] = []
    for cap in dr_data.get("caps", []) + cb_data.get("caps", []) + gw_data.get("caps", []):
        if cap and cap not in seen:
            seen.add(cap)
            resolved.append(cap)
    summary.resolved_capabilities = resolved

    if not summary.available:
        logger.debug(
            "capability_registry: device %s not found in any source — reasons: %s",
            device_id,
            summary.reasons,
        )

    return summary


def device_matches_capabilities(
    device_id: str,
    required_capabilities: List[str],
) -> CapabilityMatchResult:
    """Check whether *device_id* satisfies *required_capabilities*.

    Args:
        device_id: The identifier of the device to check.
        required_capabilities: List of capability names that must be present.

    Returns:
        A :class:`CapabilityMatchResult` with ``matched=True`` when every
        required capability is covered by the device's resolved capabilities.
    """
    _guard_routing_context_usage(
        operation="device_matches_capabilities",
        device_id=device_id,
        required_capabilities=required_capabilities,
    )
    summary = get_device_capability_summary(device_id)
    resolved_set = set(summary.resolved_capabilities)

    missing = [cap for cap in required_capabilities if cap not in resolved_set]
    matched = len(missing) == 0 and summary.available

    result = CapabilityMatchResult(
        device_id=device_id,
        required_capabilities=list(required_capabilities),
        matched=matched,
        missing_capabilities=missing,
        sources=summary.sources,
        reasons=list(summary.reasons),
    )

    if not matched:
        if not summary.available:
            result.reasons.append(f"device_matches_capabilities: device {device_id!r} not found in any source")
        if missing:
            result.reasons.append(f"device_matches_capabilities: missing capabilities — {missing}")
        logger.debug(
            "capability_registry: device %s does not match requirements %s — missing=%s",
            device_id,
            required_capabilities,
            missing,
        )

    return result


def get_devices_matching_capabilities(
    required_capabilities: List[str],
) -> List[str]:
    """Return the device IDs of all devices that satisfy *required_capabilities*.

    Iterates over every device known to ``DeviceRegistry`` (the primary
    source of device enumeration) and runs :func:`device_matches_capabilities`
    for each one.

    Args:
        required_capabilities: List of capability names that must be present.

    Returns:
        A list of device IDs whose resolved capabilities satisfy every
        requirement.  Returns an empty list if the registry is unavailable or
        no device matches.
    """
    _guard_routing_context_usage(
        operation="get_devices_matching_capabilities",
        required_capabilities=required_capabilities,
    )
    all_device_ids: List[str] = []
    try:
        from core.device_registry import device_registry

        all_device_ids = [d.device_id for d in device_registry.list_devices()]
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "capability_registry: get_devices_matching_capabilities — "
            "could not enumerate devices from device_registry: %s",
            exc,
        )
        return []

    matching: List[str] = []
    for device_id in all_device_ids:
        result = device_matches_capabilities(device_id, required_capabilities)
        if result.matched:
            matching.append(device_id)

    return matching


def device_satisfies_required_capabilities(
    device_id: str,
    declared_capabilities: Optional[List[str]],
    required_capabilities: Optional[List[str]],
) -> bool:
    """*device_id* 是否满足 *required_capabilities* —— 供调用方已持有设备对象时使用。

    修的是什么
    ----------
    本模块的 docstring 把自己写成「device capability 与能力匹配的唯一规范位置」，
    但三处活的选择路径都没走它，各自写了一句**只看单一来源**的判断::

        core/device_pool_manager.py（两处）        all(c in dev.capabilities for c in required)
        core/device_selection/canonical_device_selector.py   同形

    而 :func:`get_device_capability_summary` 明确合并**三个来源**取并集：
    ``device_registry`` / ``capability_bus`` / ``gateway_capability_registry``。
    只要某项能力是经后两条通道上报、没同步进调用方手里那份列表，单源判断就会把
    一台**确实具备该能力**的设备判成不匹配、从候选里剔除。

    实测复现（同一台设备、同一项能力）::

        device_registry              ['basic']
        capability_bus               ['basic', 'screen_capture']
        → 并集 resolved               ['basic', 'screen_capture']
        规范匹配器 matched=True   /   单源判断 matched=False

    为什么不直接改调用 :func:`device_matches_capabilities`
    ------------------------------------------------------
    那个函数在设备**不存在于任何来源**时返回 ``matched=False``（``summary.available``
    为假）。而调用方手里的设备是从自己的池子/入参里来的，未必登记在 DeviceRegistry ——
    直接替换会把这类设备**新增排除**，那是引入回归而不是修缺陷。所以这里只做**并集**：
    调用方原来能匹配的一个都不会掉，只可能多认出来几台。

    为什么先做便宜的检查
    --------------------
    三源解析每台设备要查三处，而这是选择热路径上的循环。先用调用方已持有的
    *declared_capabilities* 判一次；**只有在这一步会判失败时**才去付多源解析的代价。
    常见情况（能力本来就在手里那份列表中）零额外开销。

    解析器自身出错时返回单源判断的结果 —— 与本模块其余部分的降级语义一致：
    权威不可用不该让派发链整体失败。
    """
    if not required_capabilities:
        return True

    declared = set(declared_capabilities or [])
    missing = [c for c in required_capabilities if c not in declared]
    if not missing:
        return True

    try:
        resolved = set(get_device_capability_summary(device_id).resolved_capabilities)
    except Exception as exc:  # pragma: no cover - 权威不可用时降级为单源结论
        logger.debug(
            "device_satisfies_required_capabilities: canonical resolution unavailable "
            "for %r (%s) — falling back to declared capabilities only",
            device_id,
            exc,
        )
        return False

    still_missing = [c for c in missing if c not in resolved]
    if still_missing:
        return False

    logger.debug(
        "device_satisfies_required_capabilities: %r satisfies %s only via non-declared "
        "capability sources (declared=%s resolved=%s) — single-source check would have "
        "excluded this device",
        device_id,
        missing,
        sorted(declared),
        sorted(resolved),
    )
    return True
