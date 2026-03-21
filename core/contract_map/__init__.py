"""
core/contract_map/__init__.py
==============================
Cross-Plane Contract Map & Messaging Taxonomy for the Galaxy runtime.

This package provides a **read-only, inspectable** representation of the
message planes and contract boundaries that already exist in the Galaxy
codebase.  It does not replace any existing schema, transport, or router.

Public API
----------
Planes::

    from core.contract_map import PlaneKind

Message kinds::

    from core.contract_map import MessageKind

Descriptor model::

    from core.contract_map import ContractDescriptor

Registry access::

    from core.contract_map import get_contract_registry

Introspection helpers::

    from core.contract_map import (
        get_planes_snapshot,
        get_messages_snapshot,
        get_descriptor_for_kind,
        get_required_fields_summary,
        get_contracts_for_plane,
    )
"""

from .plane_kind import PlaneKind
from .message_kind import MessageKind
from .contract_descriptor import ContractDescriptor
from .contract_registry import (
    ContractRegistry,
    get_contract_registry,
    reset_contract_registry,
)
from .contract_introspection import (
    get_planes_snapshot,
    get_messages_snapshot,
    get_descriptor_for_kind,
    get_required_fields_summary,
    get_contracts_for_plane,
)

__all__ = [
    "PlaneKind",
    "MessageKind",
    "ContractDescriptor",
    "ContractRegistry",
    "get_contract_registry",
    "reset_contract_registry",
    "get_planes_snapshot",
    "get_messages_snapshot",
    "get_descriptor_for_kind",
    "get_required_fields_summary",
    "get_contracts_for_plane",
]
