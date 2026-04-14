from __future__ import annotations

from dataclasses import dataclass


@dataclass
class _FakeEnvelope:
    trace_id: str = "trace-1"
    task_id: str = "task-1"

    def model_dump(self):
        return {"trace_id": self.trace_id, "task_id": self.task_id, "payload": {"k": "v"}}


def test_try_remote_handoff_uses_agent_bridge_handoff(monkeypatch):
    import core.runtime.source_dispatch_orchestrator as mod

    called = {"handoff": 0}

    class FakeContract:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeBridge:
        def __init__(self, *args, **kwargs):
            pass

        async def handoff(self, contract):
            called["handoff"] += 1
            return {"success": True, "trace_id": contract.kwargs.get("trace_id")}

    import galaxy_gateway.agent_bridge as bridge_mod

    monkeypatch.setattr(bridge_mod, "AgentBridge", FakeBridge)
    monkeypatch.setattr(bridge_mod, "HandoffContract", FakeContract)

    result = mod._try_remote_handoff(_FakeEnvelope())

    assert result["success"] is True
    assert called["handoff"] == 1
