"""
core.ontology — 显式关系层（Link Types）
========================================

把散落在各 registry 里的**隐式关联**提为可声明、可遍历的关系类型。

    from core.ontology import get_link_registry, resolve_link

本包是**纯附加的只读投影**：它不存储关系、不改动任何 registry、不参与派发。
关系的权威仍然在各自的 registry（UDM / DeviceRegistry / CanonicalTaskRuntime），
本层只是把"它们之间有哪些关系、怎么走"这件事写成声明而不是散落的字段访问。
"""

from core.ontology.links import (
    LINK_REGISTRY_IS_DECLARATION_AUTHORITY,
    LINK_RESOLUTION_IS_DETERMINISTIC_POLICY,
    LINKS_ARE_PROJECTIONS_NOT_STORAGE_POLICY,
    LINKS_DO_NOT_MUTATE_POLICY,
    Cardinality,
    LinkType,
    LinkTypeRegistry,
    get_link_registry,
    resolve_link,
)

__all__ = [
    "LINK_REGISTRY_IS_DECLARATION_AUTHORITY",
    "LINKS_ARE_PROJECTIONS_NOT_STORAGE_POLICY",
    "LINKS_DO_NOT_MUTATE_POLICY",
    "LINK_RESOLUTION_IS_DETERMINISTIC_POLICY",
    "Cardinality",
    "LinkType",
    "LinkTypeRegistry",
    "get_link_registry",
    "resolve_link",
]
