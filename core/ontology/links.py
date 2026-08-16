#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/ontology/links.py — Link Types：把隐式关联提为显式声明
============================================================

**Stage 3：让"对象之间有什么关系"成为可查询的声明，而不是散落的字段访问。**

现状是这样的：任务之间的依赖写死在 ``TaskGraphRelations`` 的四个字段里
（``dependencies`` / ``retry_of`` / ``fallback_of`` / ``children``）；任务和设备的
关联藏在 ``TaskRouting.selected_targets``；设备和能力的关联在
``DeviceRegistry.capability_index`` 这个 dict 里；分组和标签又各是一个 dict。

这些关系都**真实存在**，但它们是隐式的：想知道"这个系统里有哪些关系、从任务能
走到什么"，只能去读五个文件的字段名。本模块把它们登记成 :class:`LinkType`，
于是关系本身可以被列举、被遍历、被断言。

边界（这一层刻意做得很薄）
--------------------------
1. **不存储。** 没有新的表、新的文件、新的索引。每个 LinkType 带一个 resolver，
   resolver 去读**已经存在**的字段或索引。关系的真值仍在原 registry。
2. **不改写。** 全部只读。本层不提供任何写入或删除关系的入口——因为写入的权威
   属于 UDM / DeviceRegistry / CanonicalTaskRuntime，多一个写入口就是多一个真相源。
3. **不派发。** 与 ``CommandRouter`` 无关。
4. **可独立回滚。** 没有任何既有代码路径依赖本模块；删掉整个 ``core/ontology/``
   包，系统行为不变。这是刻意的——Stage 3 的收益是表达力，风险必须为零。

为什么这层值得存在
------------------
OAG 那套论述里，"客户 A 关联了订单 B"之所以是确定的，是因为 Link Type 直接这么
说了，而不是 LLM 从文本里推断的。这个仓库的关系一直是确定的（它们就是字段），
但**没有一个地方能列举它们**——于是任何想遍历关系的代码只能各自硬编码字段名，
而硬编码的字段名会漂移。本模块给的是那个可列举的地方。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.Ontology.Links")

__all__ = [
    "LINK_REGISTRY_IS_DECLARATION_AUTHORITY",
    "LINKS_ARE_PROJECTIONS_NOT_STORAGE_POLICY",
    "LINKS_DO_NOT_MUTATE_POLICY",
    "LINK_RESOLUTION_IS_DETERMINISTIC_POLICY",
    "Cardinality",
    "LinkType",
    "LinkTypeRegistry",
    "get_link_registry",
    "reset_link_registry",
    "resolve_link",
]


# ---------------------------------------------------------------------------
# Authority / policy sentinels
# ---------------------------------------------------------------------------

LINK_REGISTRY_IS_DECLARATION_AUTHORITY: str = (
    "ONTOLOGY_LINKS::AUTHORITY: "
    "This registry is authoritative for *which relations exist and how to walk "
    "them* — the declarations.  It is NOT authoritative for the relation data "
    "itself: that stays in UnifiedDeviceManager, DeviceRegistry and "
    "CanonicalTaskRuntime, which remain the sole write authorities."
)

LINKS_ARE_PROJECTIONS_NOT_STORAGE_POLICY: str = (
    "ONTOLOGY_LINKS::POLICY_1: "
    "A LinkType stores no edges.  Every resolver reads fields or indexes that "
    "already exist on the owning registry, so this layer cannot drift out of sync "
    "with the truth — there is no second copy to drift."
)

LINKS_DO_NOT_MUTATE_POLICY: str = (
    "ONTOLOGY_LINKS::POLICY_2: "
    "Resolution is strictly read-only.  This module exposes no way to create, "
    "update or delete a relation: an additional write entry point would be an "
    "additional source of truth, which is the defect this whole effort removes."
)

LINK_RESOLUTION_IS_DETERMINISTIC_POLICY: str = (
    "ONTOLOGY_LINKS::POLICY_3: "
    "Resolution walks declared fields only.  No similarity ranking, no inference, "
    "no LLM.  'Task A depends on task B' is read from the object, never guessed — "
    "which is precisely what makes it usable on a decision path."
)


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class Cardinality(str, Enum):
    """How many targets one source may link to."""

    ONE = "one"
    MANY = "many"


@dataclass(frozen=True)
class LinkType:
    """A declared, walkable relation between two object types.

    Attributes
    ----------
    name:
        Stable identifier, e.g. ``"task_depends_on"``.
    source_type / target_type:
        Object type names, e.g. ``"CanonicalTask"`` / ``"Device"``.
    cardinality:
        ``ONE`` or ``MANY`` — checked against what the resolver actually returns.
    resolver:
        ``(source_object) -> List[str]`` returning target identifiers.  Must be
        pure and read-only; it reads an existing field or index.
    inverse:
        Optional name of the reverse LinkType, when one is also declared.
    description:
        Where the relation physically lives, so a reader can go verify it.
    """

    name: str
    source_type: str
    target_type: str
    cardinality: Cardinality
    resolver: Callable[[Any], List[str]] = field(compare=False, repr=False, default=lambda _obj: [])
    inverse: str = ""
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "source_type": self.source_type,
            "target_type": self.target_type,
            "cardinality": self.cardinality.value,
            "inverse": self.inverse,
            "description": self.description,
        }


# ---------------------------------------------------------------------------
# Resolvers over already-existing state
# ---------------------------------------------------------------------------
#
# Every resolver below reads a field or index that predates this module.  None of
# them creates, caches or persists anything.


def _str_list(value: Any) -> List[str]:
    """Normalise a field into a list of non-empty identifier strings.

    A non-iterable value means the relation field is not the shape its LinkType
    declares.  Resolution still yields ``[]`` — the resolver contract is a list —
    but it says so out loud: an empty result that silently means "couldn't read
    it" is indistinguishable from "there genuinely are no targets", and that
    conflation is the exact failure mode this whole object-anchoring effort
    exists to remove.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    try:
        return [str(v) for v in value if str(v).strip()]
    except TypeError:
        logger.warning(
            "link field is not iterable (type=%s, value=%.80r); resolving to [] — "
            "the declared LinkType and the object's actual shape disagree",
            type(value).__name__,
            value,
        )
        return []


def _task_field(task: Any, *path: str) -> Any:
    node: Any = task
    for part in path:
        node = getattr(node, part, None)
        if node is None:
            return None
    return node


def _resolve_task_dependencies(task: Any) -> List[str]:
    return _str_list(_task_field(task, "graph", "dependencies"))


def _resolve_task_children(task: Any) -> List[str]:
    return _str_list(_task_field(task, "graph", "children"))


def _resolve_task_retry_of(task: Any) -> List[str]:
    return _str_list(_task_field(task, "graph", "retry_of"))


def _resolve_task_fallback_of(task: Any) -> List[str]:
    return _str_list(_task_field(task, "graph", "fallback_of"))


def _resolve_task_parent(task: Any) -> List[str]:
    return _str_list(_task_field(task, "identity", "parent_task_id"))


def _resolve_task_root(task: Any) -> List[str]:
    return _str_list(_task_field(task, "identity", "root_task_id"))


def _resolve_task_targets(task: Any) -> List[str]:
    return _str_list(_task_field(task, "routing", "selected_targets"))


def _resolve_task_session(task: Any) -> List[str]:
    return _str_list(_task_field(task, "identity", "session_id"))


def _resolve_device_capabilities(device: Any) -> List[str]:
    """Capabilities a device reports.

    Reads the device's own capability collection rather than inverting
    ``DeviceRegistry.capability_index``: the device object is the closer source.
    """
    caps = getattr(device, "capabilities", None)
    if caps is None:
        return []
    out: List[str] = []
    for cap in caps if isinstance(caps, (list, tuple, set)) else [caps]:
        name = getattr(cap, "name", None) or (cap if isinstance(cap, str) else None)
        if name:
            out.append(str(name))
    return out


def _resolve_capability_devices(capability_name: Any) -> List[str]:
    """Inverse of the above, read straight from ``DeviceRegistry.capability_index``."""
    try:
        from core.device_registry import DeviceRegistry

        registry = DeviceRegistry.get_instance()
        return _str_list(registry.capability_index.get(str(capability_name), []))
    except Exception as exc:  # noqa: BLE001 — resolution is best-effort, never fatal
        logger.debug("capability→devices resolution skipped: %s", exc)
        return []


def _resolve_group_devices(group_name: Any) -> List[str]:
    try:
        from core.device_registry import DeviceRegistry

        return _str_list(DeviceRegistry.get_instance().groups.get(str(group_name), []))
    except Exception as exc:  # noqa: BLE001
        logger.debug("group→devices resolution skipped: %s", exc)
        return []


def _resolve_tag_devices(tag_name: Any) -> List[str]:
    try:
        from core.device_registry import DeviceRegistry

        return _str_list(DeviceRegistry.get_instance().tag_index.get(str(tag_name), []))
    except Exception as exc:  # noqa: BLE001
        logger.debug("tag→devices resolution skipped: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class LinkTypeRegistry:
    """Holds the declared LinkTypes and resolves them against live objects."""

    def __init__(self) -> None:
        self._links: Dict[str, LinkType] = {}
        self._lock = threading.Lock()

    # ── Declaration ───────────────────────────────────────────────────────

    def register(self, link: LinkType, *, replace: bool = False) -> LinkType:
        """Declare *link*.

        Raises ``ValueError`` on a duplicate name unless *replace* is set — a
        silently overwritten declaration is how a relation layer starts lying.
        """
        if not link.name:
            raise ValueError("LinkType must have a non-empty name")
        with self._lock:
            if link.name in self._links and not replace:
                raise ValueError(f"LinkType {link.name!r} is already declared")
            self._links[link.name] = link
        return link

    def get(self, name: str) -> Optional[LinkType]:
        return self._links.get(name)

    def names(self) -> List[str]:
        return sorted(self._links)

    def all(self) -> List[LinkType]:
        return [self._links[n] for n in self.names()]

    def for_source(self, source_type: str) -> List[LinkType]:
        """Every relation walkable *from* objects of *source_type*.

        Only the outbound direction is indexed.  A symmetric ``for_target()``
        was written first and then removed: nothing walks *into* an object yet
        (:meth:`~core.canonical_task_store.CanonicalTaskStore.related` walks out
        of a stored task), and a public method with no caller is exactly the
        unused surface this layer is supposed to be reducing.  Add it back
        together with the consumer that needs it, not ahead of one.
        """
        return [link for link in self.all() if link.source_type == source_type]

    # ── Resolution ────────────────────────────────────────────────────────

    def resolve(self, source: Any, link_name: str) -> List[str]:
        """Return the target identifiers *source* links to via *link_name*.

        Raises ``KeyError`` for an undeclared link — asking for a relation that
        does not exist is a programming error, not an empty result.  Resolver
        failures degrade to ``[]``: a registry being unavailable is an
        environment condition, not a bug in the caller.
        """
        link = self._links.get(link_name)
        if link is None:
            raise KeyError(f"undeclared LinkType: {link_name!r}")
        try:
            targets = link.resolver(source) or []
        except Exception as exc:  # noqa: BLE001
            logger.debug("LinkType %s resolution failed: %s", link_name, exc)
            return []
        if link.cardinality is Cardinality.ONE and len(targets) > 1:
            logger.warning(
                "LinkType %s declares cardinality=one but resolved %d targets; truncating",
                link_name,
                len(targets),
            )
            return targets[:1]
        return list(targets)

    def resolve_all(self, source: Any, source_type: str) -> Dict[str, List[str]]:
        """Walk every relation declared for *source_type* at once."""
        return {link.name: self.resolve(source, link.name) for link in self.for_source(source_type)}

    # ── Consistency ───────────────────────────────────────────────────────

    def validate(self) -> List[str]:
        """Return a list of declaration problems (empty when consistent).

        Checks that every declared ``inverse`` exists and that the pair actually
        points back — a stated inverse that does not invert is worse than none,
        because callers will trust it.
        """
        problems: List[str] = []
        for link in self.all():
            if not link.inverse:
                continue
            other = self._links.get(link.inverse)
            if other is None:
                problems.append(f"{link.name}: declares inverse {link.inverse!r} which is not registered")
                continue
            if other.inverse != link.name:
                problems.append(f"{link.name} ↔ {other.name}: inverse is not mutual")
            if other.source_type != link.target_type or other.target_type != link.source_type:
                problems.append(
                    f"{link.name} ↔ {other.name}: endpoint types do not mirror "
                    f"({link.source_type}→{link.target_type} vs {other.source_type}→{other.target_type})"
                )
        return problems

    def to_dict(self) -> Dict[str, Any]:
        return {"links": [link.to_dict() for link in self.all()]}


# ---------------------------------------------------------------------------
# Declarations — every one of these relations already exists in the codebase
# ---------------------------------------------------------------------------

_DECLARATIONS: Tuple[LinkType, ...] = (
    LinkType(
        name="task_depends_on",
        source_type="CanonicalTask",
        target_type="CanonicalTask",
        cardinality=Cardinality.MANY,
        resolver=_resolve_task_dependencies,
        description="CanonicalTask.graph.dependencies — tasks that must complete first",
    ),
    LinkType(
        name="task_has_child",
        source_type="CanonicalTask",
        target_type="CanonicalTask",
        cardinality=Cardinality.MANY,
        resolver=_resolve_task_children,
        inverse="task_has_parent",
        description="CanonicalTask.graph.children — tasks spawned by this one",
    ),
    LinkType(
        name="task_has_parent",
        source_type="CanonicalTask",
        target_type="CanonicalTask",
        cardinality=Cardinality.ONE,
        resolver=_resolve_task_parent,
        inverse="task_has_child",
        description="CanonicalTask.identity.parent_task_id",
    ),
    LinkType(
        name="task_root",
        source_type="CanonicalTask",
        target_type="CanonicalTask",
        cardinality=Cardinality.ONE,
        resolver=_resolve_task_root,
        description="CanonicalTask.identity.root_task_id — top of the task tree",
    ),
    LinkType(
        name="task_retry_of",
        source_type="CanonicalTask",
        target_type="CanonicalTask",
        cardinality=Cardinality.ONE,
        resolver=_resolve_task_retry_of,
        description="CanonicalTask.graph.retry_of — the attempt this one retries",
    ),
    LinkType(
        name="task_fallback_of",
        source_type="CanonicalTask",
        target_type="CanonicalTask",
        cardinality=Cardinality.ONE,
        resolver=_resolve_task_fallback_of,
        description="CanonicalTask.graph.fallback_of — the task this one falls back for",
    ),
    LinkType(
        name="task_targets_device",
        source_type="CanonicalTask",
        target_type="Device",
        cardinality=Cardinality.MANY,
        resolver=_resolve_task_targets,
        description="CanonicalTask.routing.selected_targets — devices this task routes to",
    ),
    LinkType(
        name="task_in_session",
        source_type="CanonicalTask",
        target_type="Session",
        cardinality=Cardinality.ONE,
        resolver=_resolve_task_session,
        description="CanonicalTask.identity.session_id",
    ),
    LinkType(
        name="device_has_capability",
        source_type="Device",
        target_type="Capability",
        cardinality=Cardinality.MANY,
        resolver=_resolve_device_capabilities,
        inverse="capability_of_device",
        description="Device.capabilities — capabilities the device reports",
    ),
    LinkType(
        name="capability_of_device",
        source_type="Capability",
        target_type="Device",
        cardinality=Cardinality.MANY,
        resolver=_resolve_capability_devices,
        inverse="device_has_capability",
        description="DeviceRegistry.capability_index — devices offering a capability",
    ),
    LinkType(
        name="group_contains_device",
        source_type="DeviceGroup",
        target_type="Device",
        cardinality=Cardinality.MANY,
        resolver=_resolve_group_devices,
        description="DeviceRegistry.groups — device group membership",
    ),
    LinkType(
        name="tag_marks_device",
        source_type="DeviceTag",
        target_type="Device",
        cardinality=Cardinality.MANY,
        resolver=_resolve_tag_devices,
        description="DeviceRegistry.tag_index — devices carrying a tag",
    ),
)


def _build_registry() -> LinkTypeRegistry:
    registry = LinkTypeRegistry()
    for link in _DECLARATIONS:
        registry.register(link)
    problems = registry.validate()
    if problems:
        # Loud but non-fatal: a bad declaration must be visible without taking
        # down a process that does not even use this layer.
        logger.warning("LinkTypeRegistry declaration problems: %s", "; ".join(problems))
    return registry


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[LinkTypeRegistry] = None
_instance_lock = threading.Lock()


def get_link_registry() -> LinkTypeRegistry:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = _build_registry()
    return _instance


def reset_link_registry() -> None:
    """Testing only: drop the singleton."""
    global _instance
    with _instance_lock:
        _instance = None


def resolve_link(source: Any, link_name: str) -> List[str]:
    """Convenience wrapper over the singleton registry."""
    return get_link_registry().resolve(source, link_name)
