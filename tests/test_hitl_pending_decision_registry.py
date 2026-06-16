"""PR-HITL: tests for the human-in-the-loop pending-decision registry."""
import asyncio

import pytest

from core.interaction.pending_decision_registry import (
    DecisionStatus,
    OnTimeout,
    PendingDecisionRegistry,
    derive_default_on_timeout,
    request_human_decision,
)


def _fresh() -> PendingDecisionRegistry:
    return PendingDecisionRegistry()


def test_derive_default_on_timeout_composite():
    assert derive_default_on_timeout("high", has_default=True) == OnTimeout.CANCEL
    assert derive_default_on_timeout("high", has_default=False) == OnTimeout.CANCEL
    assert derive_default_on_timeout("normal", has_default=True) == OnTimeout.DEFAULT_OPTION
    assert derive_default_on_timeout("normal", has_default=False) == OnTimeout.PROCEED
    assert derive_default_on_timeout("low", has_default=True) == OnTimeout.PROCEED


@pytest.mark.asyncio
async def test_resolve_wins():
    reg = _fresh()
    rec = reg.register(options=["confirm", "cancel"], timeout_s=5, decision_id="d1")

    async def replier():
        await asyncio.sleep(0.01)
        assert reg.resolve("d1", selected_option="confirm", source="wear") is True

    asyncio.create_task(replier())
    outcome = await reg.await_decision(rec)
    assert outcome.status == DecisionStatus.RESOLVED
    assert outcome.selected_option == "confirm"
    assert outcome.should_proceed is True
    assert reg.stats()["resolved"] == 1


@pytest.mark.asyncio
async def test_timeout_default_option():
    reg = _fresh()
    rec = reg.register(
        options=["a", "b"], default_option="a",
        on_timeout=OnTimeout.DEFAULT_OPTION, timeout_s=0.05, decision_id="d2",
    )
    outcome = await reg.await_decision(rec)
    assert outcome.status == DecisionStatus.TIMEOUT_DEFAULT
    assert outcome.selected_option == "a"
    assert outcome.timed_out and outcome.should_proceed


@pytest.mark.asyncio
async def test_timeout_cancel_high_urgency():
    reg = _fresh()
    # high urgency with no pinned policy → derive CANCEL
    rec = reg.register(options=["go"], urgency="high", timeout_s=0.05, decision_id="d3")
    assert rec.on_timeout == OnTimeout.CANCEL
    outcome = await reg.await_decision(rec)
    assert outcome.status == DecisionStatus.TIMEOUT_CANCEL
    assert outcome.timed_out and not outcome.should_proceed


@pytest.mark.asyncio
async def test_timeout_proceed_low_urgency():
    reg = _fresh()
    rec = reg.register(options=["go"], urgency="low", timeout_s=0.05, decision_id="d4")
    assert rec.on_timeout == OnTimeout.PROCEED
    outcome = await reg.await_decision(rec)
    assert outcome.status == DecisionStatus.TIMEOUT_PROCEED
    assert outcome.should_proceed


@pytest.mark.asyncio
async def test_fanout_first_reply_wins():
    reg = _fresh()
    rec = reg.register(options=["x"], timeout_s=5, decision_id="d5")
    assert reg.resolve("d5", selected_option="x", source="watch") is True
    # second reply (e.g. from phone) is a no-op
    assert reg.resolve("d5", selected_option="x", source="phone") is False
    outcome = await reg.await_decision(rec)
    assert outcome.status == DecisionStatus.RESOLVED and outcome.source == "watch"


@pytest.mark.asyncio
async def test_resolve_unknown_id_is_false():
    reg = _fresh()
    assert reg.resolve("nope", selected_option="x") is False


@pytest.mark.asyncio
async def test_request_human_decision_end_to_end(monkeypatch):
    import core.interaction.pending_decision_registry as mod

    emitted = []

    async def fake_emit(device_id, message):
        emitted.append((device_id, message["payload"]["decision_id"]))

    # singleton registry is used by request_human_decision + resolve
    reg = mod.get_pending_decision_registry()

    async def driver():
        # wait for the emit to happen, then resolve via the singleton
        for _ in range(100):
            if emitted:
                break
            await asyncio.sleep(0.005)
        did = emitted[0][1]
        assert reg.resolve(did, selected_option="confirm", source="wear") is True

    asyncio.create_task(driver())
    outcome = await request_human_decision(
        title="Proceed?",
        options=[{"id": "confirm", "label": "确认"}, {"id": "cancel", "label": "取消"}],
        urgency="normal",
        timeout_s=5,
        devices=["watch-1", "phone-1"],
        emit=fake_emit,
    )
    assert outcome.status == DecisionStatus.RESOLVED
    assert outcome.selected_option == "confirm"
    # fanned out to both devices
    assert {d for d, _ in emitted} == {"watch-1", "phone-1"}
