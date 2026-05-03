"""PR-25: Canonical perception fact-boundary authority.

This module formalises the perception truth boundary so new code can reason
about one authoritative perception fact source while still recognising the
remaining request-input and compatibility surfaces.

Authoritative rule:
    response.metadata.canonical_perception_state

Supporting inputs (not fact sources):
    request.multimodal_context
    runtime_shell.continuous_perception_frame

Derived / read-model surfaces:
    response.metadata.unified_control_plan.canonical_perception_summary
    response.metadata.desktop_status_projection

Compat-only surface:
    response.metadata.multimodal_context
"""

from __future__ import annotations

import dataclasses
import enum
from typing import Any, Dict, List, Optional

PERCEPTION_FACT_BOUNDARY_IS_AUTHORITY = (
    "PERCEPTION_FACT_BOUNDARY::CANONICAL_PERCEPTION_STATE_IS_SOLE_FACT_SOURCE_V1"
)
PERCEPTION_FACT_BOUNDARY_PR25_SENTINEL = (
    "PERCEPTION_FACT_BOUNDARY::PR25_BOUNDARY_SUMMARY_AND_SURFACE_CATALOG_V1"
)


class PerceptionSurfaceKind(str, enum.Enum):
    """Classifies how a surface participates in the perception contract."""

    REQUEST_INPUT = "request_input"
    CONTINUOUS_INPUT = "continuous_input"
    CANONICAL_FACT = "canonical_fact"
    DERIVED_READ_MODEL = "derived_read_model"
    COMPAT_ONLY = "compat_only"


@dataclasses.dataclass(frozen=True)
class PerceptionSurfaceRecord:
    """Static catalog record for a perception-related surface."""

    surface_path: str
    kind: PerceptionSurfaceKind
    authority_owner: str
    description: str
    replacement: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "surface_path": self.surface_path,
            "kind": self.kind.value,
            "authority_owner": self.authority_owner,
            "description": self.description,
            "replacement": self.replacement,
            "is_authoritative": self.kind == PerceptionSurfaceKind.CANONICAL_FACT,
        }


PERCEPTION_SURFACE_CATALOG: List[PerceptionSurfaceRecord] = [
    PerceptionSurfaceRecord(
        surface_path="request.multimodal_context",
        kind=PerceptionSurfaceKind.REQUEST_INPUT,
        authority_owner="adapter_surfaces",
        description=(
            "Request-layer multimodal payload bundle. Valid as an ingress input, "
            "but not an internal perception fact source."
        ),
        replacement="response.metadata.canonical_perception_state",
    ),
    PerceptionSurfaceRecord(
        surface_path="runtime_shell.continuous_perception_frame",
        kind=PerceptionSurfaceKind.CONTINUOUS_INPUT,
        authority_owner="desktop_presence_runtime",
        description=(
            "Shell-owned continuous host perception snapshot consumed by OpenClawd "
            "when building canonical_perception_state."
        ),
        replacement="response.metadata.canonical_perception_state",
    ),
    PerceptionSurfaceRecord(
        surface_path="response.metadata.canonical_perception_state",
        kind=PerceptionSurfaceKind.CANONICAL_FACT,
        authority_owner="openclawd",
        description=(
            "Single authoritative perception fact source for routing, diagnostics, "
            "and control-plan assembly."
        ),
    ),
    PerceptionSurfaceRecord(
        surface_path="response.metadata.unified_control_plan.canonical_perception_summary",
        kind=PerceptionSurfaceKind.DERIVED_READ_MODEL,
        authority_owner="openclawd",
        description=(
            "Derived perception summary embedded in the unified control plan. "
            "Reads from canonical_perception_state and must not compete with it."
        ),
        replacement="response.metadata.canonical_perception_state",
    ),
    PerceptionSurfaceRecord(
        surface_path="response.metadata.desktop_status_projection",
        kind=PerceptionSurfaceKind.DERIVED_READ_MODEL,
        authority_owner="desktop_presence_runtime",
        description=(
            "Shell-facing projection surface that must remain downstream of the "
            "canonical perception/control artifacts."
        ),
        replacement="response.metadata.canonical_perception_state",
    ),
    PerceptionSurfaceRecord(
        surface_path="response.metadata.multimodal_context",
        kind=PerceptionSurfaceKind.COMPAT_ONLY,
        authority_owner="openclawd",
        description=(
            "Deprecated fused multimodal payload retained only for backward "
            "compatibility. New code must not treat it as perception truth."
        ),
        replacement="response.metadata.canonical_perception_state",
    ),
]


def get_perception_surface_catalog() -> List[PerceptionSurfaceRecord]:
    """Return the static perception surface catalog."""

    return list(PERCEPTION_SURFACE_CATALOG)


def classify_perception_surface(surface_path: str) -> Optional[PerceptionSurfaceRecord]:
    """Return the catalog record for *surface_path*, when known."""

    for record in PERCEPTION_SURFACE_CATALOG:
        if record.surface_path == surface_path:
            return record
    return None


def build_perception_fact_boundary_summary(
    response_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a serialisable summary of the governed perception fact boundary."""

    metadata = response_metadata or {}
    ucp = metadata.get("unified_control_plan") or {}
    present_surfaces: List[str] = []

    if metadata.get("canonical_perception_state") is not None:
        present_surfaces.append("response.metadata.canonical_perception_state")
    if isinstance(ucp, dict) and ucp.get("canonical_perception_summary") is not None:
        present_surfaces.append(
            "response.metadata.unified_control_plan.canonical_perception_summary"
        )
    if metadata.get("desktop_status_projection") is not None:
        present_surfaces.append("response.metadata.desktop_status_projection")
    if metadata.get("multimodal_context") is not None:
        present_surfaces.append("response.metadata.multimodal_context")

    compat_surfaces_present = [
        path for path in present_surfaces if path == "response.metadata.multimodal_context"
    ]
    derived_surfaces_present = [
        path
        for path in present_surfaces
        if path in {
            "response.metadata.unified_control_plan.canonical_perception_summary",
            "response.metadata.desktop_status_projection",
        }
    ]

    return {
        "authority": PERCEPTION_FACT_BOUNDARY_IS_AUTHORITY,
        "pr_sentinel": PERCEPTION_FACT_BOUNDARY_PR25_SENTINEL,
        "canonical_fact_surface": "response.metadata.canonical_perception_state",
        "request_input_surface": "request.multimodal_context",
        "continuous_input_surface": "runtime_shell.continuous_perception_frame",
        "derived_read_surfaces": [
            "response.metadata.unified_control_plan.canonical_perception_summary",
            "response.metadata.desktop_status_projection",
        ],
        "compat_only_surfaces": ["response.metadata.multimodal_context"],
        "canonical_fact_present": metadata.get("canonical_perception_state") is not None,
        "derived_surfaces_present": derived_surfaces_present,
        "compat_surfaces_present": compat_surfaces_present,
        "present_surfaces": present_surfaces,
        "requires_compat_migration": bool(compat_surfaces_present),
        "surface_catalog": [record.to_dict() for record in PERCEPTION_SURFACE_CATALOG],
    }
