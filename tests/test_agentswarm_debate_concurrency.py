"""tests/test_agentswarm_debate_concurrency.py
==================================================

Node_126_AgentSwarm's DebateOrchestrator runs each debate round (proposal /
critique / defense) over N independent reasoning agents. Each agent method is
a real network call (httpx to Node_58's /chat) - the agents within a single
round don't depend on each other at all. The rounds used to be driven by a
plain ``for agent in agents: await agent.propose(...)`` loop, so an N-agent
debate took N times a single LLM call's latency instead of roughly one call's
latency - the "swarm" was serialized, not concurrent.

These tests prove the rounds now run agents via asyncio.gather(): timing a
round over 5 agents (each an artificial 0.3s delay) must stay close to 0.3s,
not scale to 5 * 0.3s.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from nodes.Node_126_AgentSwarm.main import (
    AgentProposal,
    Critique,
    DebateOrchestrator,
    ReasoningStrategy,
)

DELAY_S = 0.3
AGENT_COUNT = 5
# Generous ceiling: concurrent should land near DELAY_S; sequential would be
# AGENT_COUNT * DELAY_S (1.5s) or worse for the critique round (10 calls).
CONCURRENT_CEILING_S = DELAY_S * 2


class _FakeAgent:
    """Stands in for a real ReasoningAgent without hitting the network."""

    def __init__(self, agent_id: str, strategy: ReasoningStrategy):
        self.agent_id = agent_id
        self.strategy = strategy

    async def propose(self, problem, context) -> AgentProposal:
        await asyncio.sleep(DELAY_S)
        return AgentProposal(
            agent_id=self.agent_id,
            strategy=self.strategy,
            solution="x",
            reasoning=[],
            confidence=0.5,
        )

    async def critique(self, target: AgentProposal) -> Critique:
        await asyncio.sleep(DELAY_S)
        return Critique(
            critic_id=self.agent_id,
            target_id=target.agent_id,
            points=["p"],
            severity="minor",
        )

    async def defend(self, critiques) -> AgentProposal:
        await asyncio.sleep(DELAY_S)
        return AgentProposal(
            agent_id=self.agent_id,
            strategy=self.strategy,
            solution="y",
            reasoning=[],
            confidence=0.6,
        )


def _agents():
    return [_FakeAgent(f"a{i}", ReasoningStrategy.COT) for i in range(AGENT_COUNT)]


class TestDebateRoundConcurrency:
    def test_proposal_round_runs_agents_concurrently(self):
        orch = DebateOrchestrator()
        agents = _agents()

        async def run():
            t0 = time.monotonic()
            result = await orch._run_proposal_round(agents, "problem", {})
            return result, time.monotonic() - t0

        result, elapsed = asyncio.run(run())
        assert len(result.proposals) == AGENT_COUNT
        assert elapsed < CONCURRENT_CEILING_S, (
            f"proposal round took {elapsed:.2f}s for {AGENT_COUNT} agents - " f"looks sequential, not concurrent"
        )

    def test_critique_round_runs_agents_concurrently(self):
        orch = DebateOrchestrator()
        agents = _agents()

        async def run():
            round1 = await orch._run_proposal_round(agents, "problem", {})
            t0 = time.monotonic()
            result = await orch._run_critique_round(agents, round1.proposals)
            return result, time.monotonic() - t0

        result, elapsed = asyncio.run(run())
        # 5 agents x 2 targets each = 10 independent critique calls.
        assert len(result.critiques) == AGENT_COUNT * 2
        assert elapsed < CONCURRENT_CEILING_S, (
            f"critique round took {elapsed:.2f}s for {AGENT_COUNT * 2} calls - " f"looks sequential, not concurrent"
        )

    def test_defense_round_runs_agents_concurrently(self):
        orch = DebateOrchestrator()
        agents = _agents()

        async def run():
            round1 = await orch._run_proposal_round(agents, "problem", {})
            round2 = await orch._run_critique_round(agents, round1.proposals)
            t0 = time.monotonic()
            result = await orch._run_defense_round(agents, round2.critiques)
            return result, time.monotonic() - t0

        result, elapsed = asyncio.run(run())
        assert len(result.proposals) == AGENT_COUNT
        assert elapsed < CONCURRENT_CEILING_S, (
            f"defense round took {elapsed:.2f}s for {AGENT_COUNT} agents - " f"looks sequential, not concurrent"
        )
