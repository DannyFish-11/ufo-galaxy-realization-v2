"""Canonical operational support boundaries for declared device classes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from core.device_types import DeviceType, resolve_device_type

DEVICE_OPERATIONAL_SUPPORT_AUTHORITY: str = (
    "DEVICE_OPERATIONAL_SUPPORT_AUTHORITY::"
    "core.device_operational_support is the canonical truth surface for which "
    "declared device classes are actually operational near-peers in V2."
)

DECLARED_TYPES_MUST_NOT_IMPLY_OPERATIONAL_SUPPORT_POLICY: str = (
    "POLICY::DECLARED_TYPES_MUST_NOT_IMPLY_OPERATIONAL_SUPPORT: "
    "A device class being declared in enums or registration contracts does not "
    "mean it is an operational dispatch/control near-peer. Unsupported classes "
    "must be demoted from dispatch/support surfaces."
)

NEAR_PEER_OPERATIONAL_TYPES: frozenset[str] = frozenset(
    {DeviceType.ANDROID.value, DeviceType.WINDOWS.value}
)
OBSERVABLE_BUT_NON_OPERATIONAL_TYPES: frozenset[str] = frozenset(
    {
        DeviceType.MACOS.value,
        DeviceType.LINUX.value,
        DeviceType.BROWSER.value,
        DeviceType.CLOUD.value,
    }
)


class OperationalSupportTier(str, Enum):
    near_peer_operational = "near_peer_operational"
    observable_but_not_operational = "observable_but_not_operational"
    declared_non_operational = "declared_non_operational"


@dataclass(frozen=True)
class DeviceOperationalSupportVerdict:
    device_type: str
    support_tier: OperationalSupportTier
    control_capable: bool
    execution_capable: bool
    closure_integrated: bool
    dispatch_target_capable: bool
    near_peer_operational: bool
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_type": self.device_type,
            "support_tier": self.support_tier.value,
            "control_capable": self.control_capable,
            "execution_capable": self.execution_capable,
            "closure_integrated": self.closure_integrated,
            "dispatch_target_capable": self.dispatch_target_capable,
            "near_peer_operational": self.near_peer_operational,
            "reason": self.reason,
            "authority": DEVICE_OPERATIONAL_SUPPORT_AUTHORITY,
        }


def classify_device_operational_support(raw_device_type: str) -> DeviceOperationalSupportVerdict:
    resolved = resolve_device_type(raw_device_type)
    device_type = resolved.value

    if device_type in NEAR_PEER_OPERATIONAL_TYPES:
        return DeviceOperationalSupportVerdict(
            device_type=device_type,
            support_tier=OperationalSupportTier.near_peer_operational,
            control_capable=True,
            execution_capable=True,
            closure_integrated=True,
            dispatch_target_capable=True,
            near_peer_operational=True,
            reason=(
                "Implemented runtime/control paths exist and the device class is "
                "treated as an operational near-peer."
            ),
        )

    if device_type in OBSERVABLE_BUT_NON_OPERATIONAL_TYPES:
        return DeviceOperationalSupportVerdict(
            device_type=device_type,
            support_tier=OperationalSupportTier.observable_but_not_operational,
            control_capable=False,
            execution_capable=False,
            closure_integrated=False,
            dispatch_target_capable=False,
            near_peer_operational=False,
            reason=(
                "The class may be discoverable or registrable, but V2 does not "
                "have real near-peer dispatch/control closure for it."
            ),
        )

    return DeviceOperationalSupportVerdict(
        device_type=device_type,
        support_tier=OperationalSupportTier.declared_non_operational,
        control_capable=False,
        execution_capable=False,
        closure_integrated=False,
        dispatch_target_capable=False,
        near_peer_operational=False,
        reason=(
            "The class is declared for taxonomy/contract coverage only and is "
            "not operationally supported as a dispatch/control peer."
        ),
    )


def get_device_operational_support(
    *,
    device_id: Optional[str] = None,
    device_record: Optional[Any] = None,
    raw_device_type: Optional[str] = None,
) -> DeviceOperationalSupportVerdict:
    if raw_device_type is None and device_record is None and device_id:
        try:
            from core.unified.device_manager import get_unified_device_manager

            device_record = get_unified_device_manager().get_device(device_id)
        except Exception:
            device_record = None

    if raw_device_type is None and device_record is not None:
        if isinstance(device_record, dict):
            raw_device_type = str(
                device_record.get("device_type")
                or device_record.get("platform")
                or device_record.get("type")
                or ""
            )
        else:
            raw_device_type = str(
                getattr(device_record, "device_type", None)
                or getattr(device_record, "platform", None)
                or getattr(device_record, "type", None)
                or ""
            )

    return classify_device_operational_support(str(raw_device_type or "unknown"))


def build_device_support_matrix(
    *,
    observed_types: Optional[List[str]] = None,
) -> Dict[str, Any]:
    declared_types = sorted(t.value for t in DeviceType)
    observed = {
        resolve_device_type(str(item or "unknown")).value for item in (observed_types or [])
    }
    matrix: List[Dict[str, Any]] = []
    for device_type in declared_types:
        verdict = classify_device_operational_support(device_type)
        payload = verdict.to_dict()
        payload.update(
            {
                "declared": True,
                "registered": device_type in observed,
                "observable": device_type in observed,
                "unsupported_but_declared": not verdict.dispatch_target_capable,
                "runtime_status": (
                    "operational"
                    if verdict.dispatch_target_capable
                    else verdict.support_tier.value
                ),
            }
        )
        matrix.append(payload)
    return {
        "support_matrix": matrix,
        "observed_device_types": sorted(observed),
        "authority": DEVICE_OPERATIONAL_SUPPORT_AUTHORITY,
        "policy": DECLARED_TYPES_MUST_NOT_IMPLY_OPERATIONAL_SUPPORT_POLICY,
    }

