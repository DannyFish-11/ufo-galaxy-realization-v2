"""tests/test_ontology_links_stage3.py
=======================================
Tests for the explicit Link Type layer (Stage 3).

背景
----
任务之间的依赖写死在 ``TaskGraphRelations`` 的四个字段里;任务和设备的关联藏在
``TaskRouting.selected_targets``;设备和能力的关联在 ``DeviceRegistry.capability_index``;
分组和标签又各是一个 dict。这些关系都**真实存在**,但它们是隐式的——想知道
"这个系统里有哪些关系、从任务能走到什么",只能去读五个文件的字段名。

本层把它们登记成可列举、可遍历的 :class:`LinkType`。刻意做得很薄:

  不存储(resolver 读已有字段) / 不改写(全只读) / 不派发 / 可整包删除而行为不变。

最后一条是本阶段的安全前提,由 E01 显式钉住:没有任何既有代码路径依赖本模块。

Coverage matrix
---------------
Group A — Policy sentinels
  A01. LINK_REGISTRY_IS_DECLARATION_AUTHORITY separates declaration from data.
  A02. LINKS_ARE_PROJECTIONS_NOT_STORAGE_POLICY exists.
  A03. LINKS_DO_NOT_MUTATE_POLICY exists.
  A04. LINK_RESOLUTION_IS_DETERMINISTIC_POLICY rules out inference.

Group B — Declarations
  B01. The registry is non-empty and validates cleanly.
  B02. Declared inverses are mutual and mirror their endpoint types.
  B03. Task relations cover every TaskGraphRelations field.
  B04. Device/capability/group/tag relations are declared.
  B05. for_source / for_target index correctly.
  B06. to_dict() is JSON-safe.
  B07. Every declaration carries a description pointing at where it lives.

Group C — Resolution against real objects
  C01. task_depends_on reads graph.dependencies.
  C02. task_has_child reads graph.children.
  C03. task_has_parent reads identity.parent_task_id.
  C04. task_targets_device reads routing.selected_targets.
  C05. task_in_session reads identity.session_id.
  C06. task_retry_of / task_fallback_of read their fields.
  C07. Empty fields resolve to [] rather than [""].
  C08. resolve_all walks every relation for the type.

Group D — Registry contract
  D01. Undeclared link raises KeyError (not a silent empty result).
  D02. cardinality=ONE truncates a multi-valued resolver.
  D03. Duplicate declaration is rejected unless replace=True.
  D04. A raising resolver degrades to [] instead of propagating.
  D05. validate() reports a dangling inverse.
  D06. validate() reports a non-mutual inverse.
  D07. validate() reports mirrored-endpoint mismatch.

Group E — Additive-only guarantee
  E01. No existing module imports core.ontology — the package is removable.
  E02. The module exposes no mutation entry points.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from core.canonical_task import build_canonical_task
from core.ontology import (
    Cardinality,
    LinkType,
    LinkTypeRegistry,
    get_link_registry,
    resolve_link,
)


@pytest.fixture
def registry():
    return get_link_registry()


def _task(**kw):
    return build_canonical_task(register=False, **kw)


# ---------------------------------------------------------------------------
# Group A — Policy sentinels
# ---------------------------------------------------------------------------


class TestGroupAPolicies:
    def test_a01_declaration_vs_data_authority(self):
        from core.ontology import LINK_REGISTRY_IS_DECLARATION_AUTHORITY

        text = LINK_REGISTRY_IS_DECLARATION_AUTHORITY
        assert "AUTHORITY" in text
        assert "NOT authoritative for the relation data" in text
        assert "sole write authorities" in text

    def test_a02_projection_not_storage(self):
        from core.ontology import LINKS_ARE_PROJECTIONS_NOT_STORAGE_POLICY

        text = LINKS_ARE_PROJECTIONS_NOT_STORAGE_POLICY
        assert "POLICY_1" in text
        assert "stores no edges" in text

    def test_a03_no_mutation(self):
        from core.ontology import LINKS_DO_NOT_MUTATE_POLICY

        text = LINKS_DO_NOT_MUTATE_POLICY
        assert "POLICY_2" in text
        assert "read-only" in text

    def test_a04_deterministic_resolution(self):
        from core.ontology import LINK_RESOLUTION_IS_DETERMINISTIC_POLICY

        text = LINK_RESOLUTION_IS_DETERMINISTIC_POLICY
        assert "POLICY_3" in text
        assert "No similarity ranking" in text
        assert "never guessed" in text


# ---------------------------------------------------------------------------
# Group B — Declarations
# ---------------------------------------------------------------------------


class TestGroupBDeclarations:
    def test_b01_registry_validates_clean(self, registry):
        assert registry.all()
        assert registry.validate() == []

    def test_b02_inverses_are_mutual(self, registry):
        for link in registry.all():
            if not link.inverse:
                continue
            other = registry.get(link.inverse)
            assert other is not None, f"{link.name} declares missing inverse {link.inverse}"
            assert other.inverse == link.name
            assert other.source_type == link.target_type
            assert other.target_type == link.source_type

    def test_b03_every_task_graph_field_is_declared(self, registry):
        """TaskGraphRelations has four fields; all four must be walkable."""
        names = set(registry.names())
        assert {"task_depends_on", "task_has_child", "task_retry_of", "task_fallback_of"} <= names

    def test_b04_device_side_relations_declared(self, registry):
        names = set(registry.names())
        assert {
            "device_has_capability",
            "capability_of_device",
            "group_contains_device",
            "tag_marks_device",
        } <= names

    def test_b05_indexes_by_endpoint(self, registry):
        from_task = {link.name for link in registry.for_source("CanonicalTask")}
        assert "task_depends_on" in from_task
        assert "capability_of_device" not in from_task
        to_device = {link.name for link in registry.for_target("Device")}
        assert {"task_targets_device", "capability_of_device"} <= to_device

    def test_b06_to_dict_json_safe(self, registry):
        payload = registry.to_dict()
        json.dumps(payload)
        assert payload["links"]
        assert all("cardinality" in link for link in payload["links"])

    def test_b07_declarations_say_where_the_relation_lives(self, registry):
        for link in registry.all():
            assert link.description, f"{link.name} has no description"


# ---------------------------------------------------------------------------
# Group C — Resolution
# ---------------------------------------------------------------------------


class TestGroupCResolution:
    def test_c01_depends_on(self):
        t = _task(goal="t")
        t.graph.dependencies = ["a", "b"]
        assert resolve_link(t, "task_depends_on") == ["a", "b"]

    def test_c02_children(self):
        t = _task(goal="t")
        t.graph.children = ["c1", "c2"]
        assert resolve_link(t, "task_has_child") == ["c1", "c2"]

    def test_c03_parent(self):
        parent = _task(goal="p")
        child = _task(goal="c", parent_task_id=parent.identity.task_id)
        assert resolve_link(child, "task_has_parent") == [parent.identity.task_id]

    def test_c04_targets_device(self):
        t = _task(goal="t")
        t.routing.selected_targets = ["dev-1", "dev-2"]
        assert resolve_link(t, "task_targets_device") == ["dev-1", "dev-2"]

    def test_c05_session(self):
        t = _task(goal="t", session_id="sess-1")
        assert resolve_link(t, "task_in_session") == ["sess-1"]

    def test_c06_retry_and_fallback(self):
        t = _task(goal="t")
        t.graph.retry_of = "orig-1"
        t.graph.fallback_of = "fb-1"
        assert resolve_link(t, "task_retry_of") == ["orig-1"]
        assert resolve_link(t, "task_fallback_of") == ["fb-1"]

    def test_c07_empty_field_yields_empty_list(self):
        """An unset single-valued field must not resolve to ['']."""
        t = _task(goal="t")
        assert resolve_link(t, "task_retry_of") == []
        assert resolve_link(t, "task_has_parent") == []
        assert resolve_link(t, "task_depends_on") == []

    def test_c08_resolve_all_covers_the_type(self, registry):
        t = _task(goal="t", session_id="s")
        t.graph.dependencies = ["a"]
        walked = registry.resolve_all(t, "CanonicalTask")
        assert set(walked) == {link.name for link in registry.for_source("CanonicalTask")}
        assert walked["task_depends_on"] == ["a"]


# ---------------------------------------------------------------------------
# Group D — Registry contract
# ---------------------------------------------------------------------------


class TestGroupDContract:
    def test_d01_undeclared_link_raises(self):
        with pytest.raises(KeyError):
            resolve_link(_task(goal="t"), "task_eats_pizza")

    def test_d02_cardinality_one_truncates(self):
        r = LinkTypeRegistry()
        r.register(
            LinkType(
                name="one_but_many",
                source_type="X",
                target_type="Y",
                cardinality=Cardinality.ONE,
                resolver=lambda _o: ["a", "b", "c"],
            )
        )
        assert r.resolve(None, "one_but_many") == ["a"]

    def test_d03_duplicate_declaration_rejected(self):
        r = LinkTypeRegistry()
        link = LinkType(name="dup", source_type="X", target_type="Y", cardinality=Cardinality.MANY)
        r.register(link)
        with pytest.raises(ValueError):
            r.register(link)
        r.register(link, replace=True)  # explicit override is allowed

    def test_d04_raising_resolver_degrades(self):
        def boom(_o):
            raise RuntimeError("resolver exploded")

        r = LinkTypeRegistry()
        r.register(LinkType(name="boom", source_type="X", target_type="Y", cardinality=Cardinality.MANY, resolver=boom))
        assert r.resolve(None, "boom") == []

    def test_d05_validate_reports_dangling_inverse(self):
        r = LinkTypeRegistry()
        r.register(
            LinkType(name="a_to_b", source_type="A", target_type="B", cardinality=Cardinality.MANY, inverse="missing")
        )
        problems = r.validate()
        assert any("not registered" in p for p in problems)

    def test_d06_validate_reports_non_mutual_inverse(self):
        r = LinkTypeRegistry()
        r.register(
            LinkType(name="a_to_b", source_type="A", target_type="B", cardinality=Cardinality.MANY, inverse="b_to_a")
        )
        r.register(
            LinkType(name="b_to_a", source_type="B", target_type="A", cardinality=Cardinality.MANY, inverse="other")
        )
        assert any("not mutual" in p for p in r.validate())

    def test_d07_validate_reports_endpoint_mismatch(self):
        """A stated inverse that does not invert is worse than none — callers trust it."""
        r = LinkTypeRegistry()
        r.register(
            LinkType(name="a_to_b", source_type="A", target_type="B", cardinality=Cardinality.MANY, inverse="b_to_a")
        )
        r.register(
            LinkType(name="b_to_a", source_type="C", target_type="D", cardinality=Cardinality.MANY, inverse="a_to_b")
        )
        assert any("do not mirror" in p for p in r.validate())


# ---------------------------------------------------------------------------
# Group E — Additive-only guarantee
# ---------------------------------------------------------------------------


class TestGroupEAdditiveOnly:
    def test_e01_no_existing_code_depends_on_this_package(self):
        """Stage 3's safety premise: deleting core/ontology/ changes no behaviour.

        The value here is expressiveness, so the risk must be zero. If some module
        starts importing it, that is a deliberate decision that should update this
        test — not something that happens quietly.
        """
        proc = subprocess.run(
            ["grep", "-rn", "--include=*.py", "-e", "core.ontology", "-e", "core/ontology", "core", "galaxy_gateway"],
            capture_output=True,
            text=True,
        )
        offenders = [
            line for line in proc.stdout.splitlines() if line.strip() and not line.startswith("core/ontology/")
        ]
        assert offenders == [], "core.ontology must stay dependency-free:\n" + "\n".join(offenders)

    def test_e02_no_mutation_entry_points(self):
        """POLICY_2 says read-only; assert the surface actually is."""
        import core.ontology.links as mod

        forbidden = {"add_link", "set_link", "delete_link", "remove_link", "write_link", "link"}
        public = {n for n in dir(mod) if not n.startswith("_")}
        assert not (public & forbidden), public & forbidden
        # register() declares a *type*, not an edge — edges are never stored.
        registry = LinkTypeRegistry()
        assert not hasattr(registry, "add_edge")
        assert not hasattr(registry, "connect")
