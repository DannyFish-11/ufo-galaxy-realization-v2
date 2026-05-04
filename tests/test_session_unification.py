from __future__ import annotations

import asyncio

import pytest


def _reset_session_state() -> None:
    from core.cognitive.working_memory import reset_working_memory
    from core.session_execution_lane import reset_session_execution_lane_manager
    from core.session_manager import get_session_manager

    reset_working_memory()
    reset_session_execution_lane_manager()
    sm = get_session_manager()
    sm._sessions.clear()
    sm._user_active_session.clear()


def test_build_canonical_session_identity_uses_session_manager_for_conversation_continuity() -> None:
    from core.session_identity import build_canonical_session_identity

    _reset_session_state()
    identity = build_canonical_session_identity(
        user_id="user_01",
        device_id="phone_01",
        runtime_session_id="runtime_abc123",
    )

    assert identity.conversation_session_id.startswith("session_")
    assert identity.control_session_id == "control_runtime_abc1"


@pytest.mark.asyncio
async def test_session_execution_lane_serializes_same_conversation_session() -> None:
    from core.session_execution_lane import get_session_execution_lane_manager

    _reset_session_state()
    manager = get_session_execution_lane_manager()
    events: list[str] = []

    async def _runner(name: str, delay: float) -> None:
        async with manager.acquire("session_same", control_session_id=name):
            events.append(f"start:{name}")
            await asyncio.sleep(delay)
            events.append(f"end:{name}")

    await asyncio.gather(_runner("c1", 0.05), _runner("c2", 0.01))

    assert events == ["start:c1", "end:c1", "start:c2", "end:c2"]


@pytest.mark.asyncio
async def test_session_memory_facade_writes_once_and_reads_from_unified_sources() -> None:
    from core.session_manager import get_session_manager
    from core.session_memory_facade import get_session_context, record_session_turn

    _reset_session_state()
    await record_session_turn(
        conversation_session_id="session_facade",
        role="user",
        content="hello",
        user_id="user_x",
        device_id="device_x",
        trace_id="trace_1",
    )
    await record_session_turn(
        conversation_session_id="session_facade",
        role="user",
        content="hello",
        user_id="user_x",
        device_id="device_x",
        trace_id="trace_1",
    )

    context = get_session_context("session_facade", max_turns=5)
    history = get_session_manager().get_full_history("session_facade")

    assert context == [{"role": "user", "content": "hello"}]
    assert len(history) == 1
    assert history[0]["metadata"]["trace_id"] == "trace_1"


@pytest.mark.asyncio
async def test_desktop_runtime_threads_canonical_session_ids_and_lane_metadata(monkeypatch) -> None:
    import sys
    import types

    from core.desktop_presence_runtime import DesktopPresenceRuntime

    _reset_session_state()
    fake_pkg = types.ModuleType("core.multimodal")
    fake_pkg.__path__ = []  # type: ignore[attr-defined]
    fake_mod = types.ModuleType("core.multimodal.perception_source_registry")

    class _FakePerceptionSourceRegistry:
        pass

    fake_mod.PerceptionSourceRegistry = _FakePerceptionSourceRegistry
    monkeypatch.setitem(sys.modules, "core.multimodal", fake_pkg)
    monkeypatch.setitem(
        sys.modules,
        "core.multimodal.perception_source_registry",
        fake_mod,
    )
    runtime = DesktopPresenceRuntime()

    async def _fake_dispatch(self, **kwargs):
        return {
            "success": True,
            "response": "ok",
            "metadata": {
                "handler": "fake_dispatch",
                "session_id": kwargs["session_id"],
            },
        }

    monkeypatch.setattr(
        DesktopPresenceRuntime,
        "_dispatch",
        _fake_dispatch,
    )

    result = await runtime.handle_request(
        "hello",
        source="chat",
        user_id="user_02",
        device_id="phone_02",
    )

    assert result["conversation_session_id"].startswith("session_")
    assert result["control_session_id"].startswith("control_")
    assert result["metadata"]["session_id"] == result["conversation_session_id"]
    assert (
        result["metadata"]["session_execution_lane"]["conversation_session_id"]
        == result["conversation_session_id"]
    )


@pytest.mark.asyncio
async def test_agent_kernel_async_record_session_uses_unified_facade(monkeypatch) -> None:
    from core.agent.kernel import AgentKernel

    calls = []

    async def _fake_record_session_turn(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(
        "core.session_memory_facade.record_session_turn",
        _fake_record_session_turn,
    )

    kernel = AgentKernel()
    await kernel._record_session(
        "session_kernel",
        "u",
        "a",
        control_session_id="control_kernel",
        runtime_attachment_session_id="attach_kernel",
        device_id="device_kernel",
    )

    assert len(calls) == 2
    assert calls[0]["conversation_session_id"] == "session_kernel"
    assert calls[0]["metadata"]["control_session_id"] == "control_kernel"
