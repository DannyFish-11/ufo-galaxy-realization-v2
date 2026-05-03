from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reset_task_runtimes():
    from core.canonical_task import reset_canonical_task_runtime
    from core.task_graph_runtime import reset_task_graph_runtime
    from core.routes._shared import task_queue

    reset_canonical_task_runtime()
    reset_task_graph_runtime()
    task_queue.clear()
    yield
    reset_canonical_task_runtime()
    reset_task_graph_runtime()
    task_queue.clear()


def _make_bridge() -> SimpleNamespace:
    return SimpleNamespace(
        _pending_responses={},
        _devices={},
        _lock=asyncio.Lock(),
    )


@pytest.mark.asyncio
async def test_task_cancel_updates_canonical_task_graph_and_task_queue():
    from core.canonical_task import (
        TaskLifecycle,
        build_canonical_task,
        get_canonical_task_runtime,
    )
    from core.routes._shared import task_queue
    from core.task_graph_runtime import GraphNode, GraphNodeState, get_task_graph_runtime
    from galaxy_gateway.android.handlers.task_lifecycle import handle_task_cancel

    task_id = "canon_cancel_1"
    bridge = _make_bridge()
    bridge._devices["android_1"] = SimpleNamespace(current_task_id=task_id)

    task = build_canonical_task(task_id=task_id, register=True)
    get_canonical_task_runtime().update_lifecycle(task_id, TaskLifecycle.RUNNING)
    get_task_graph_runtime().register_node(GraphNode(task_id=task_id, state=GraphNodeState.RUNNING))
    task_queue[task_id] = {"task_id": task_id, "status": "running"}

    fake_openclawd = MagicMock()
    fake_openclawd.cancel_task.return_value = True
    with patch("core.openclawd.get_openclawd", return_value=fake_openclawd):
        resp = await handle_task_cancel(
            bridge,
            None,
            {
                "type": "task_cancel",
                "device_id": "android_1",
                "task_id": task_id,
                "message_id": "cancel_msg_1",
            },
        )

    assert resp["type"] == "task_cancel_ack"
    assert resp["cancelled"] is True
    assert get_canonical_task_runtime().get_by_task_id(task_id).lifecycle.value == "cancelled"
    assert get_task_graph_runtime().get_node_by_task_id(task_id).state.value == "cancelled"
    assert task_queue[task_id]["status"] == "cancelled"
    fake_openclawd.cancel_task.assert_called_once_with(task_id)


@pytest.mark.asyncio
async def test_task_status_prefers_canonical_runtime_over_bridge_local_future():
    from core.task_graph_runtime import GraphNode, GraphNodeState, get_task_graph_runtime
    from galaxy_gateway.android.handlers.task_lifecycle import handle_task_status

    task_id = "canon_status_1"
    bridge = _make_bridge()
    fut = asyncio.get_running_loop().create_future()
    bridge._pending_responses[task_id] = fut
    get_task_graph_runtime().register_node(GraphNode(task_id=task_id, state=GraphNodeState.CANCELLED))

    resp = await handle_task_status(
        bridge,
        None,
        {
            "type": "task_status",
            "device_id": "android_2",
            "task_id": task_id,
            "message_id": "status_msg_1",
        },
    )

    assert resp["type"] == "task_status_response"
    assert resp["status"] == "cancelled"


@pytest.mark.asyncio
async def test_task_status_resolves_pending_from_canonical_task_runtime():
    from core.canonical_task import (
        TaskLifecycle,
        build_canonical_task,
        get_canonical_task_runtime,
    )
    from galaxy_gateway.android.handlers.task_lifecycle import handle_task_status

    task_id = "canon_status_2"
    bridge = _make_bridge()
    task = build_canonical_task(task_id=task_id, register=True)
    get_canonical_task_runtime().update_lifecycle(task_id, TaskLifecycle.PLANNED)

    resp = await handle_task_status(
        bridge,
        None,
        {
            "type": "task_status",
            "device_id": "android_3",
            "task_id": task_id,
            "message_id": "status_msg_2",
        },
    )

    assert task is not None
    assert resp["type"] == "task_status_response"
    assert resp["status"] == "pending"
