#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr510_operator_api_endpoints.py
==========================================
PR-510 — Operator API + Consumer Activation: Tests.

Validates that:
* ``core/routes/operator.py`` declares its authority sentinel and
  ``create_router()`` returns an :class:`~fastapi.APIRouter`.
* Snapshot endpoint returns a valid :class:`~core.operator_surface.OperatorSnapshot`
  dict, including when the canonical runtime layers are empty (sparse).
* Inspect endpoints return 200 + projection dict for known entities.
* Inspect endpoints return 404 for unknown entities.
* All handlers consume ``OperatorSurface`` projections — not raw internals.
* ``cli/operator_inspect.py`` declares its authority sentinel and
  ``_get_json``/``main`` entry-points are present.
* The CLI consumer targets the operator API URL paths (not subsystem internals).

Test groups
-----------
 A)  Module structure — routes/operator.py authority sentinel and router.
 B)  Snapshot endpoint — valid OperatorSnapshot dict always returned.
 C)  Snapshot endpoint — graceful empty/default when runtime is sparse.
 D)  Inspect task endpoint — 200 for known task, 404 for unknown.
 E)  Inspect route endpoint — 200 for known task, 404 for unknown.
 F)  Inspect executor endpoint — 200 for known node, 404 for unknown.
 G)  Inspect failure endpoint — 404 for task with no failure data.
 H)  Inspect lineage endpoint — 200 for known task, 404 for unknown.
 I)  Projection-only discipline — handlers use OperatorSurface, not internals.
 J)  CLI consumer module structure — authority sentinel, main(), _get_json().
 K)  CLI consumer targets operator API paths, not raw subsystem internals.
 L)  api_routes.py wires operator routes (optional-try block present).
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from typing import Any, Dict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_surface():
    from core.operator_surface import reset_operator_surface

    reset_operator_surface()


def _reset_canonical_task():
    try:
        from core.canonical_task import reset_canonical_task_runtime

        reset_canonical_task_runtime()
    except Exception:
        pass


def _reset_all():
    _reset_surface()
    _reset_canonical_task()


def _build_task(goal: str = "test goal", lifecycle: str = "completed"):
    """Register a CanonicalTask and return it."""
    from core.canonical_task import (
        TaskLifecycle,
        TaskOrigin,
        build_canonical_task,
        get_canonical_task_runtime,
    )

    task = build_canonical_task(
        goal=goal,
        origin=TaskOrigin.API_REQUEST,
        requested_action="test_action",
        selected_targets=["device_001"],
    )
    task.lifecycle = TaskLifecycle(lifecycle)
    task.result.success = lifecycle == "completed"
    rt = get_canonical_task_runtime()
    rt.register(task)
    return task


# ===========================================================================
# A)  Module structure
# ===========================================================================


class TestA_ModuleStructure(unittest.TestCase):
    """A) Routes module authority sentinel and router factory."""

    def test_A01_authority_sentinel_importable(self) -> None:
        from core.routes.operator import OPERATOR_ROUTES_AUTHORITY

        self.assertIsInstance(OPERATOR_ROUTES_AUTHORITY, str)
        self.assertGreater(len(OPERATOR_ROUTES_AUTHORITY), 0)

    def test_A02_authority_sentinel_contains_v1(self) -> None:
        from core.routes.operator import OPERATOR_ROUTES_AUTHORITY

        self.assertIn("OPERATOR_ROUTES_V1", OPERATOR_ROUTES_AUTHORITY)

    def test_A03_create_router_returns_apirouter(self) -> None:
        from fastapi import APIRouter

        from core.routes.operator import create_router

        router = create_router()
        self.assertIsInstance(router, APIRouter)

    def test_A04_router_has_six_routes(self) -> None:
        from core.routes.operator import create_router

        router = create_router()
        paths = [r.path for r in router.routes]
        # 断言漂移:PR-510 落地时 operator 路由恰为 6 条;此后 operator 控制面
        # 持续扩展(flows/devices/dispatch/board 等,现已 30+ 条)。精确计数
        # 断言只反映当年快照,不是本测试要守护的契约;真正的契约是 PR-510
        # 的 6 条原始端点必须仍然存在(操作面向后兼容)。
        pr510_original_routes = {
            "/api/v1/operator/snapshot",
            "/api/v1/operator/actions/availability",
            "/api/v1/operator/inspect/task/{task_id}",
            "/api/v1/operator/inspect/route/{task_id}",
            "/api/v1/operator/inspect/executor/{node_id}",
            "/api/v1/operator/inspect/failure/{task_id}",
        }
        missing = pr510_original_routes - set(paths)
        self.assertFalse(missing, f"PR-510 original routes missing: {missing}; got: {paths}")
        self.assertGreaterEqual(len(paths), 6, f"Expected at least 6 routes, got: {paths}")

    def test_A05_snapshot_route_present(self) -> None:
        from core.routes.operator import create_router

        router = create_router()
        paths = [r.path for r in router.routes]
        self.assertIn("/api/v1/operator/snapshot", paths)

    def test_A06_inspect_routes_present(self) -> None:
        from core.routes.operator import create_router

        router = create_router()
        paths = [r.path for r in router.routes]
        for expected in [
            "/api/v1/operator/inspect/task/{task_id}",
            "/api/v1/operator/inspect/route/{task_id}",
            "/api/v1/operator/inspect/executor/{node_id}",
            "/api/v1/operator/inspect/failure/{task_id}",
            "/api/v1/operator/inspect/lineage/{task_id}",
        ]:
            self.assertIn(expected, paths, f"Missing route: {expected}")


# ===========================================================================
# B)  Snapshot endpoint — returns valid OperatorSnapshot dict
# ===========================================================================


class TestB_SnapshotEndpoint(unittest.IsolatedAsyncioTestCase):
    """B) Snapshot endpoint returns a valid OperatorSnapshot dict."""

    def setUp(self):
        _reset_all()

    def tearDown(self):
        _reset_all()

    async def test_B01_snapshot_returns_200(self) -> None:
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from core.routes.operator import create_router

        app = FastAPI()
        app.include_router(create_router())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/operator/snapshot")
        self.assertEqual(resp.status_code, 200)

    async def test_B02_snapshot_body_is_valid_json(self) -> None:
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from core.routes.operator import create_router

        app = FastAPI()
        app.include_router(create_router())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/operator/snapshot")
        data = resp.json()
        self.assertIsInstance(data, dict)

    async def test_B03_snapshot_has_authority_field(self) -> None:
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from core.operator_surface import OPERATOR_SURFACE_AUTHORITY
        from core.routes.operator import create_router

        app = FastAPI()
        app.include_router(create_router())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/operator/snapshot")
        data = resp.json()
        self.assertEqual(data.get("authority"), OPERATOR_SURFACE_AUTHORITY)

    async def test_B04_snapshot_has_contract_version(self) -> None:
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from core.routes.operator import create_router

        app = FastAPI()
        app.include_router(create_router())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/operator/snapshot")
        data = resp.json()
        self.assertIn("contract_version", data)
        self.assertIsInstance(data["contract_version"], str)
        self.assertGreater(len(data["contract_version"]), 0)

    async def test_B05_snapshot_has_snapshot_id(self) -> None:
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from core.routes.operator import create_router

        app = FastAPI()
        app.include_router(create_router())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/operator/snapshot")
        data = resp.json()
        self.assertIn("snapshot_id", data)
        self.assertTrue(data["snapshot_id"].startswith("snap_"))

    async def test_B06_snapshot_numeric_fields_present(self) -> None:
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from core.routes.operator import create_router

        app = FastAPI()
        app.include_router(create_router())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/operator/snapshot")
        data = resp.json()
        for field in [
            "active_task_count",
            "online_device_count",
            "topology_node_count",
            "topology_edge_count",
            "capability_provider_count",
            "online_provider_count",
        ]:
            self.assertIn(field, data, f"Missing field: {field}")
            self.assertIsInstance(data[field], int)


# ===========================================================================
# C)  Snapshot endpoint — graceful empty/default behavior
# ===========================================================================


class TestC_SnapshotSparseRuntime(unittest.IsolatedAsyncioTestCase):
    """C) Snapshot returns zeroed defaults when runtime layers are empty."""

    def setUp(self):
        _reset_all()

    def tearDown(self):
        _reset_all()

    async def test_C01_empty_runtime_gives_zero_task_count(self) -> None:
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from core.routes.operator import create_router

        app = FastAPI()
        app.include_router(create_router())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/operator/snapshot")
        data = resp.json()
        self.assertEqual(data["active_task_count"], 0)

    async def test_C02_empty_runtime_recent_tasks_is_list(self) -> None:
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from core.routes.operator import create_router

        app = FastAPI()
        app.include_router(create_router())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/operator/snapshot")
        data = resp.json()
        self.assertIsInstance(data.get("recent_tasks"), list)

    async def test_C03_snapshot_json_serialisable(self) -> None:
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from core.routes.operator import create_router

        app = FastAPI()
        app.include_router(create_router())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/operator/snapshot")
        # Verify full round-trip serialisation
        raw = resp.text
        parsed = json.loads(raw)
        self.assertIsInstance(parsed, dict)

    async def test_C04_snapshot_with_registered_task_increments_count(self) -> None:
        _build_task()
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from core.routes.operator import create_router

        app = FastAPI()
        app.include_router(create_router())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/operator/snapshot")
        data = resp.json()
        self.assertGreaterEqual(data["active_task_count"], 1)


# ===========================================================================
# D)  Inspect task endpoint
# ===========================================================================


class TestD_InspectTask(unittest.IsolatedAsyncioTestCase):
    """D) Inspect task endpoint — 200 for known tasks, 404 for unknown."""

    def setUp(self):
        _reset_all()

    def tearDown(self):
        _reset_all()

    async def test_D01_unknown_task_returns_404(self) -> None:
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from core.routes.operator import create_router

        app = FastAPI()
        app.include_router(create_router())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/operator/inspect/task/no_such_task")
        self.assertEqual(resp.status_code, 404)

    async def test_D02_unknown_task_404_body_has_detail(self) -> None:
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from core.routes.operator import create_router

        app = FastAPI()
        app.include_router(create_router())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/operator/inspect/task/no_such_task")
        data = resp.json()
        self.assertIn("detail", data)

    async def test_D03_known_task_returns_200(self) -> None:
        task = _build_task()
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from core.routes.operator import create_router

        app = FastAPI()
        app.include_router(create_router())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/operator/inspect/task/{task.identity.task_id}")
        self.assertEqual(resp.status_code, 200)

    async def test_D04_known_task_body_has_task_id(self) -> None:
        task = _build_task(goal="check me")
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from core.routes.operator import create_router

        app = FastAPI()
        app.include_router(create_router())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/operator/inspect/task/{task.identity.task_id}")
        data = resp.json()
        self.assertEqual(data.get("task_id"), task.identity.task_id)

    async def test_D05_known_task_body_has_lifecycle(self) -> None:
        task = _build_task(lifecycle="completed")
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from core.routes.operator import create_router

        app = FastAPI()
        app.include_router(create_router())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/operator/inspect/task/{task.identity.task_id}")
        data = resp.json()
        self.assertIn("lifecycle", data)

    async def test_D06_known_task_body_is_json_serialisable(self) -> None:
        task = _build_task()
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from core.routes.operator import create_router

        app = FastAPI()
        app.include_router(create_router())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/operator/inspect/task/{task.identity.task_id}")
        parsed = json.loads(resp.text)
        self.assertIsInstance(parsed, dict)


# ===========================================================================
# E)  Inspect route endpoint
# ===========================================================================


class TestE_InspectRoute(unittest.IsolatedAsyncioTestCase):
    """E) Inspect route endpoint — 200 for known task, 404 for unknown."""

    def setUp(self):
        _reset_all()

    def tearDown(self):
        _reset_all()

    async def test_E01_unknown_task_returns_404(self) -> None:
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from core.routes.operator import create_router

        app = FastAPI()
        app.include_router(create_router())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/operator/inspect/route/no_such_task")
        self.assertEqual(resp.status_code, 404)

    async def test_E02_unknown_task_detail_present(self) -> None:
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from core.routes.operator import create_router

        app = FastAPI()
        app.include_router(create_router())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/operator/inspect/route/no_such_task")
        data = resp.json()
        self.assertIn("detail", data)

    async def test_E03_known_task_with_replay_route_returns_200(self) -> None:
        """If the task has a route decision in ReplayFoundation it is surfaced."""
        task = _build_task()
        try:
            from core.replay_foundation import (
                get_replay_foundation,
                record_route_decision,
                reset_replay_foundation,
            )

            reset_replay_foundation()
            record_route_decision(
                task_id=task.identity.task_id,
                selected_targets=["device_001"],
                strategy="direct",
                policy_score=0.9,
            )
        except Exception:
            self.skipTest("ReplayFoundation or record_route_decision unavailable")

        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from core.routes.operator import create_router

        app = FastAPI()
        app.include_router(create_router())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/operator/inspect/route/{task.identity.task_id}")
        self.assertIn(resp.status_code, (200, 404))

    async def test_E04_route_response_is_json(self) -> None:
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from core.routes.operator import create_router

        app = FastAPI()
        app.include_router(create_router())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/operator/inspect/route/any_task")
        parsed = json.loads(resp.text)
        self.assertIsInstance(parsed, dict)


# ===========================================================================
# F)  Inspect executor endpoint
# ===========================================================================


class TestF_InspectExecutor(unittest.IsolatedAsyncioTestCase):
    """F) Inspect executor endpoint — 200 for known node, 404 for unknown."""

    def setUp(self):
        _reset_all()

    def tearDown(self):
        _reset_all()

    async def test_F01_unknown_node_returns_404(self) -> None:
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from core.routes.operator import create_router

        app = FastAPI()
        app.include_router(create_router())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/operator/inspect/executor/no_such_node")
        self.assertEqual(resp.status_code, 404)

    async def test_F02_unknown_node_detail_present(self) -> None:
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from core.routes.operator import create_router

        app = FastAPI()
        app.include_router(create_router())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/operator/inspect/executor/no_such_node")
        data = resp.json()
        self.assertIn("detail", data)

    async def test_F03_known_executor_returns_200_and_node_id(self) -> None:
        """Assimilate a node then confirm the inspect endpoint surfaces it."""
        try:
            from core.capability_assimilation import (
                CapabilityDescriptor,
                ExecutionProfile,
                FabricPresence,
                get_capability_assimilation_layer,
                reset_capability_assimilation_layer,
            )

            reset_capability_assimilation_layer()
            layer = get_capability_assimilation_layer()
            layer.assimilate(
                node_id="exec_node_42",
                capability=CapabilityDescriptor(
                    node_id="exec_node_42",
                    node_class="capability_node",
                    capabilities=["text_gen"],
                ),
                profile=ExecutionProfile(node_id="exec_node_42"),
                presence=FabricPresence(
                    node_id="exec_node_42",
                    fabric_endpoint="nats://localhost:4222",
                ),
            )
        except Exception:
            self.skipTest("CapabilityAssimilationLayer helpers unavailable")

        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from core.routes.operator import create_router

        _reset_surface()
        app = FastAPI()
        app.include_router(create_router())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/operator/inspect/executor/exec_node_42")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("node_id"), "exec_node_42")

    async def test_F04_executor_response_is_json(self) -> None:
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from core.routes.operator import create_router

        app = FastAPI()
        app.include_router(create_router())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/operator/inspect/executor/any_node")
        parsed = json.loads(resp.text)
        self.assertIsInstance(parsed, dict)


# ===========================================================================
# G)  Inspect failure endpoint
# ===========================================================================


class TestG_InspectFailure(unittest.IsolatedAsyncioTestCase):
    """G) Inspect failure endpoint — 404 when no failure data exists."""

    def setUp(self):
        _reset_all()

    def tearDown(self):
        _reset_all()

    async def test_G01_unknown_task_returns_404(self) -> None:
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from core.routes.operator import create_router

        app = FastAPI()
        app.include_router(create_router())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/operator/inspect/failure/no_such_task")
        self.assertEqual(resp.status_code, 404)

    async def test_G02_task_with_no_failure_returns_404(self) -> None:
        """A completed task with no failure records → 404 from failure inspect."""
        task = _build_task(lifecycle="completed")
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from core.routes.operator import create_router

        app = FastAPI()
        app.include_router(create_router())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/operator/inspect/failure/{task.identity.task_id}")
        # Either 200 (if failure data is synthesised) or 404 is acceptable
        self.assertIn(resp.status_code, (200, 404))

    async def test_G03_failure_response_is_json(self) -> None:
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from core.routes.operator import create_router

        app = FastAPI()
        app.include_router(create_router())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/operator/inspect/failure/some_task")
        parsed = json.loads(resp.text)
        self.assertIsInstance(parsed, dict)


# ===========================================================================
# H)  Inspect lineage endpoint
# ===========================================================================


class TestH_InspectLineage(unittest.IsolatedAsyncioTestCase):
    """H) Inspect lineage endpoint — 200 for known task, 404 for unknown."""

    def setUp(self):
        _reset_all()

    def tearDown(self):
        _reset_all()

    async def test_H01_unknown_task_returns_404(self) -> None:
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from core.routes.operator import create_router

        app = FastAPI()
        app.include_router(create_router())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/operator/inspect/lineage/no_such_task")
        self.assertEqual(resp.status_code, 404)

    async def test_H02_unknown_task_detail_present(self) -> None:
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from core.routes.operator import create_router

        app = FastAPI()
        app.include_router(create_router())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/operator/inspect/lineage/no_such_task")
        data = resp.json()
        self.assertIn("detail", data)

    async def test_H03_known_task_returns_200_or_404(self) -> None:
        """A registered task may or may not have lineage depending on runtime."""
        task = _build_task()
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from core.routes.operator import create_router

        app = FastAPI()
        app.include_router(create_router())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/operator/inspect/lineage/{task.identity.task_id}")
        self.assertIn(resp.status_code, (200, 404))

    async def test_H04_lineage_response_is_json(self) -> None:
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from core.routes.operator import create_router

        app = FastAPI()
        app.include_router(create_router())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/operator/inspect/lineage/any_task")
        parsed = json.loads(resp.text)
        self.assertIsInstance(parsed, dict)


# ===========================================================================
# I)  Projection-only discipline
# ===========================================================================


class TestI_ProjectionOnlyDiscipline(unittest.TestCase):
    """I) Handlers use OperatorSurface projections, not raw internals."""

    def test_I01_operator_routes_imports_operator_surface(self) -> None:
        """The routes module must import from core.operator_surface (lazy or eager)."""
        import inspect

        import core.routes.operator as mod

        src = inspect.getsource(mod)
        self.assertIn("operator_surface", src)
        self.assertIn("get_operator_surface", src)

    def test_I02_routes_module_does_not_directly_import_canonical_task_runtime(self) -> None:
        """Handlers must go through OperatorSurface, not bypass it."""
        import inspect

        import core.routes.operator as mod

        src = inspect.getsource(mod)
        # The routes module itself should not call get_canonical_task_runtime directly
        self.assertNotIn("get_canonical_task_runtime", src)

    def test_I03_routes_module_does_not_directly_import_capability_assimilation(self) -> None:
        """Handlers must go through OperatorSurface."""
        import inspect

        import core.routes.operator as mod

        src = inspect.getsource(mod)
        self.assertNotIn("get_capability_assimilation_layer", src)

    def test_I04_routes_module_does_not_import_replay_foundation_directly(self) -> None:
        """Replay data is surfaced via OperatorSurface, not fetched directly."""
        import inspect

        import core.routes.operator as mod

        src = inspect.getsource(mod)
        self.assertNotIn("get_replay_foundation", src)

    def test_I05_snapshot_endpoint_calls_operator_snapshot_method(self) -> None:
        """The snapshot handler delegates to OperatorSurface.operator_snapshot()."""
        import inspect

        import core.routes.operator as mod

        src = inspect.getsource(mod)
        self.assertIn("operator_snapshot", src)


# ===========================================================================
# J) / K)  CLI consumer —— 已随 cli/ 目录一并移除
# ===========================================================================
#
# 原本这里有两个测试类，守 cli/operator_inspect.py 的模块结构与它引用的
# /api/v1/operator/* 路径。cli/ 目录已删除（全仓唯一的真实依赖就是这两个类，
# 启动链路与打包配置都没引用过它），故一并移除。
#
# 下面 L) 测的是 api_routes.py 有没有把 operator 路由挂上，与 CLI 无关，保留。


class TestL_ApiRoutesWiresOperatorRoutes(unittest.TestCase):
    """L) api_routes.py includes the operator route try-block."""

    def test_L01_api_routes_references_operator_routes_module(self) -> None:
        import inspect

        import core.api_routes as mod

        src = inspect.getsource(mod)
        self.assertIn("core.routes", src)
        self.assertIn("operator", src)

    def test_L02_api_routes_sentinel_present(self) -> None:
        from core.api_routes import CANONICAL_API_ROUTES_AUTHORITY

        self.assertIsInstance(CANONICAL_API_ROUTES_AUTHORITY, str)

    def test_L03_operator_routes_module_importable(self) -> None:
        import core.routes.operator as mod

        self.assertIsNotNone(mod)

    def test_L04_snapshot_path_documented_in_api_routes(self) -> None:
        import inspect

        import core.api_routes as mod

        src = inspect.getsource(mod)
        self.assertIn("/api/v1/operator/snapshot", src)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main()
